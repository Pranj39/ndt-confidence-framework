"""Tests for TwinVerifier and the verify/graph/compile CLI subcommands.

Batfish itself is never required: a fake session mimics the pybatfish API,
and the unreachable-service test points at a closed local port.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from src.twin_builder import (
    BatfishUnavailableError,
    NetworkEvidence,
    SnapshotNotLoadedError,
    TwinBuilder,
    TwinVerifier,
    VerificationError,
)
from src.twin_builder import cli
from src.twin_builder.cli import main


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SAMPLE = _REPOSITORY_ROOT / "examples" / "thapathali_lab.json"
_COMPLEX = _REPOSITORY_ROOT / "examples" / "thapathali_complex.json"


def _complex_evidence() -> NetworkEvidence:
    return NetworkEvidence.model_validate_json(_COMPLEX.read_text(encoding="utf-8"))


def _sample_evidence() -> NetworkEvidence:
    return NetworkEvidence.model_validate_json(_SAMPLE.read_text(encoding="utf-8"))


class FakeFrame:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def to_dict(self, orient: str) -> list[dict[str, Any]]:
        assert orient == "records"
        return self.rows


class FakeQuestion:
    def __init__(self, session: FakeSession, name: str, kwargs: dict[str, Any]) -> None:
        self.session = session
        self.name = name
        self.kwargs = kwargs

    def answer(self) -> SimpleNamespace:
        self.session.calls.append((self.name, self.kwargs))
        result = self.session.answers[self.name]
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(frame=lambda: FakeFrame(result))


class FakeQuestions:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    def __getattr__(self, name: str) -> Any:
        return lambda **kwargs: FakeQuestion(self.session, name, kwargs)


@dataclass
class FakeSession:
    answers: dict[str, Any] = field(default_factory=dict)
    calls: list[tuple[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.q = FakeQuestions(self)

    def set_network(self, name: str) -> str:
        self.calls.append(("set_network", name))
        return name

    def init_snapshot(self, upload: str, name: str, overwrite: bool) -> str:
        self.calls.append(("init_snapshot", (upload, name, overwrite)))
        return name


@dataclass
class FilterStepDetail:
    filter: str


def _step(action: str, detail: Any = None) -> SimpleNamespace:
    return SimpleNamespace(action=action, detail=detail)


def _trace(disposition: str, hops: list[tuple[str, list[SimpleNamespace]]]) -> SimpleNamespace:
    return SimpleNamespace(
        disposition=disposition,
        hops=[SimpleNamespace(node=node, steps=steps) for node, steps in hops],
    )


def _denied_trace() -> SimpleNamespace:
    return _trace(
        "DENIED_IN",
        [
            (
                "r1-core",
                [
                    _step("RECEIVED"),
                    _step("DENIED", FilterStepDetail("BLOCK_STUDENT_TO_EXAM")),
                ],
            )
        ],
    )


def _accepted_trace() -> SimpleNamespace:
    return _trace(
        "ACCEPTED",
        [
            ("r1", [_step("ORIGINATED"), _step("FORWARDED"), _step("TRANSMITTED")]),
            ("r2", [_step("RECEIVED"), _step("ACCEPTED")]),
        ],
    )


def _default_answers() -> dict[str, Any]:
    return {
        "fileParseStatus": [
            {"File_Name": "configs/R1.cfg", "Status": "PASSED", "Nodes": ["r1"]},
            {"File_Name": "configs/R2.cfg", "Status": "PARTIALLY_UNRECOGNIZED", "Nodes": ["r2"]},
        ],
        "initIssues": [
            {
                "Nodes": ["r2"],
                "Type": "Parse warning",
                "Details": "This syntax is unrecognized",
                "Line_Text": "unknown-command",
            }
        ],
        "routes": [
            {
                "Node": "r2",
                "VRF": "default",
                "Network": "10.0.12.0/30",
                "Next_Hop_IP": "AUTO/NONE(-1l)",
                "Protocol": "connected",
            },
            {
                "Node": "r1",
                "VRF": "default",
                "Network": "10.255.0.2/32",
                "Next_Hop_IP": "10.0.12.2",
                "Protocol": "ospf",
            },
            {"Node": "r1", "Network": "0.0.0.0/0", "Next_Hop_IP": float("nan"), "Protocol": "static"},
        ],
        "traceroute": [{"Flow": "flow", "Traces": [_denied_trace()], "TraceCount": 1}],
    }


@pytest.fixture
def snapshot_dir(tmp_path: Path) -> Path:
    return Path(TwinBuilder().build_batfish_snapshot(_sample_evidence(), tmp_path))


def _verifier(session: FakeSession) -> TwinVerifier:
    return TwinVerifier(
        session_factory=lambda host, port: session,
        header_factory=lambda **kwargs: kwargs,
    )


def test_load_snapshot_summarises_parse_status(snapshot_dir: Path) -> None:
    session = FakeSession(_default_answers())
    created: list[tuple[str, int]] = []
    verifier = TwinVerifier(
        "batfish.local",
        9996,
        session_factory=lambda host, port: created.append((host, port)) or session,
    )

    summary = verifier.load_snapshot(snapshot_dir, network_name="lab")

    assert created == [("batfish.local", 9996)]
    assert session.calls[0] == ("set_network", "lab")
    assert session.calls[1] == ("init_snapshot", (str(snapshot_dir), "batfish_snapshot", True))
    assert summary["network"] == "lab"
    assert summary["snapshot"] == "batfish_snapshot"
    assert summary["ok"] is True
    assert summary["errors"] == []
    assert summary["files"][0] == {"file": "configs/R1.cfg", "status": "PASSED", "nodes": ["r1"]}
    assert "configs/R2.cfg: PARTIALLY_UNRECOGNIZED" in summary["warnings"]
    assert (
        "Parse warning on r2: This syntax is unrecognized [unknown-command]" in summary["warnings"]
    )


def test_load_snapshot_reports_errors(snapshot_dir: Path) -> None:
    answers = _default_answers()
    answers["fileParseStatus"] = [{"File_Name": "configs/R1.cfg", "Status": "FAILED", "Nodes": []}]
    answers["initIssues"] = [{"Nodes": ["r1"], "Type": "Convert error", "Details": "bad ACL"}]

    summary = _verifier(FakeSession(answers)).load_snapshot(snapshot_dir)

    assert summary["ok"] is False
    assert summary["errors"] == ["configs/R1.cfg: parsing failed", "Convert error on r1: bad ACL"]


def test_get_computed_routes_returns_clean_sorted_rows(snapshot_dir: Path) -> None:
    verifier = _verifier(FakeSession(_default_answers()))
    verifier.load_snapshot(snapshot_dir)

    routes = verifier.get_computed_routes()

    assert routes == [
        {"Node": "r1", "Network": "0.0.0.0/0", "Next_Hop_IP": None, "Protocol": "static"},
        {"Node": "r1", "Network": "10.255.0.2/32", "Next_Hop_IP": "10.0.12.2", "Protocol": "ospf"},
        {
            "Node": "r2",
            "Network": "10.0.12.0/30",
            "Next_Hop_IP": "AUTO/NONE(-1l)",
            "Protocol": "connected",
        },
    ]


def test_trace_reports_acl_denial(snapshot_dir: Path) -> None:
    session = FakeSession(_default_answers())
    verifier = _verifier(session)
    verifier.load_snapshot(snapshot_dir)

    result = verifier.test_trace("R1-Core", "10.0.10.50", "10.0.20.10")

    assert session.calls[-1] == (
        "traceroute",
        {"startLocation": "R1-Core", "headers": {"srcIps": "10.0.10.50", "dstIps": "10.0.20.10"}},
    )
    assert result["disposition"] == "DENIED"
    assert result["dropped_by_acl"] == "BLOCK_STUDENT_TO_EXAM"
    assert result["hops"] == [
        {
            "node": "r1-core",
            "steps": [
                {"action": "RECEIVED", "type": None, "filter": None},
                {"action": "DENIED", "type": "FilterStepDetail", "filter": "BLOCK_STUDENT_TO_EXAM"},
            ],
        }
    ]
    assert result["traces"][0]["batfish_disposition"] == "DENIED_IN"


def test_trace_reports_accepted_and_other_dispositions(snapshot_dir: Path) -> None:
    answers = _default_answers()
    answers["traceroute"] = [{"Traces": [_accepted_trace()]}]
    verifier = _verifier(FakeSession(answers))
    verifier.load_snapshot(snapshot_dir)

    accepted = verifier.test_trace("R1", "10.0.12.1", "10.255.0.2")
    assert accepted["disposition"] == "ACCEPTED"
    assert accepted["dropped_by_acl"] is None
    assert [hop["node"] for hop in accepted["hops"]] == ["r1", "r2"]

    answers["traceroute"] = [{"Traces": [_trace("NO_ROUTE", [("r1", [_step("RECEIVED")])])]}]
    assert verifier.test_trace("R1", "10.0.12.1", "192.168.99.1")["disposition"] == "NO_ROUTE"

    answers["traceroute"] = [{"Traces": []}]
    with pytest.raises(VerificationError, match="no trace from 'Missing'"):
        verifier.test_trace("Missing", "10.0.12.1", "10.255.0.2")


def test_queries_require_loaded_snapshot() -> None:
    verifier = _verifier(FakeSession(_default_answers()))

    with pytest.raises(SnapshotNotLoadedError, match="load_snapshot"):
        verifier.get_computed_routes()
    with pytest.raises(SnapshotNotLoadedError):
        verifier.test_trace("R1", "10.0.0.1", "10.0.0.2")


def test_load_snapshot_rejects_non_snapshot_directory(tmp_path: Path) -> None:
    verifier = TwinVerifier(session_factory=lambda host, port: pytest.fail("must not connect"))

    with pytest.raises(VerificationError, match="not a Batfish snapshot"):
        verifier.load_snapshot(tmp_path)


def test_unreachable_batfish_raises_descriptive_error(snapshot_dir: Path) -> None:
    def refuse(host: str, port: int) -> Any:
        raise ConnectionRefusedError(111, "Connection refused")

    verifier = TwinVerifier("localhost", 9996, session_factory=refuse)

    with pytest.raises(BatfishUnavailableError) as error:
        verifier.load_snapshot(snapshot_dir)

    message = str(error.value)
    assert "Cannot reach Batfish at localhost:9996" in message
    assert "docker run" in message


def test_query_failures_are_wrapped(snapshot_dir: Path) -> None:
    answers = _default_answers()
    answers["routes"] = ConnectionResetError("reset by peer")
    verifier = _verifier(FakeSession(answers))
    verifier.load_snapshot(snapshot_dir)

    with pytest.raises(BatfishUnavailableError, match="Lost connection.*query routes"):
        verifier.get_computed_routes()

    answers["traceroute"] = RuntimeError("bad location")
    with pytest.raises(VerificationError, match="failed to run traceroute: bad location"):
        verifier.test_trace("R9", "10.0.0.1", "10.0.0.2")


@pytest.mark.skipif(importlib.util.find_spec("pybatfish") is None, reason="pybatfish not installed")
def test_real_pybatfish_unreachable_service(snapshot_dir: Path) -> None:
    verifier = TwinVerifier("127.0.0.1", 1)

    with pytest.raises(BatfishUnavailableError, match=r"Cannot reach Batfish at 127\.0\.0\.1:1"):
        verifier.load_snapshot(snapshot_dir)


@pytest.mark.parametrize("port", [0, 70000])
def test_rejects_invalid_port(port: int) -> None:
    with pytest.raises(ValueError, match="port"):
        TwinVerifier(port=port)


def _patch_cli_verifier(monkeypatch: pytest.MonkeyPatch, answers: dict[str, Any]) -> list[Any]:
    created: list[Any] = []

    def factory(host: str = "localhost", port: int = 9996) -> TwinVerifier:
        verifier = TwinVerifier(
            host,
            port,
            session_factory=lambda h, p: FakeSession(answers),
            header_factory=lambda **kwargs: kwargs,
        )
        created.append((host, port))
        return verifier

    monkeypatch.setattr(cli, "TwinVerifier", factory)
    return created


def test_cli_verify_prints_routes_and_trace(
    snapshot_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    created = _patch_cli_verifier(monkeypatch, _default_answers())

    exit_code = main(
        [
            "verify",
            str(snapshot_dir),
            "--node",
            "R1-Core",
            "--src-ip",
            "10.0.10.50",
            "--dst-ip",
            "10.0.20.10",
            "--port",
            "19996",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert created == [("localhost", 19996)]
    assert "Snapshot batfish_snapshot in network campus_network: OK" in output
    assert "Computed routes (3):" in output
    assert "10.255.0.2/32" in output and "ospf" in output
    assert "Traceroute 10.0.10.50 -> 10.0.20.10 from R1-Core: DENIED" in output
    assert "[1] r1-core: RECEIVED -> DENIED (BLOCK_STUDENT_TO_EXAM)" in output
    assert "Dropped by ACL: BLOCK_STUDENT_TO_EXAM" in output


def test_cli_verify_without_trace_and_with_parse_errors(
    snapshot_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answers = _default_answers()
    answers["fileParseStatus"] = [{"File_Name": "configs/R1.cfg", "Status": "FAILED"}]
    _patch_cli_verifier(monkeypatch, answers)

    assert main(["verify", str(snapshot_dir)]) == 1
    output = capsys.readouterr().out
    assert "ERROR   configs/R1.cfg: parsing failed" in output
    assert "Traceroute" not in output


def test_cli_verify_reports_unreachable_batfish(
    snapshot_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(host: str, port: int) -> Any:
        raise ConnectionRefusedError(111, "Connection refused")

    monkeypatch.setattr(
        cli,
        "TwinVerifier",
        lambda host, port: TwinVerifier(host, port, session_factory=refuse),
    )

    assert main(["verify", str(snapshot_dir)]) == 1
    captured = capsys.readouterr()
    assert "Cannot reach Batfish at localhost:9996" in captured.err


@pytest.mark.parametrize(
    "extra",
    [["--node", "R1"], ["--src-ip", "10.0.0.1"], ["--dst-ip", "10.0.0.2"], ["--src-ip", "bogus"]],
)
def test_cli_verify_validates_trace_options(
    snapshot_dir: Path, capsys: pytest.CaptureFixture[str], extra: list[str]
) -> None:
    with pytest.raises(SystemExit) as error:
        main(["verify", str(snapshot_dir), *extra])

    assert error.value.code == 2
    assert "error" in capsys.readouterr().err


def test_cli_graph_invokes_containerlab(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    topology = Path(TwinBuilder().build_containerlab(_sample_evidence(), tmp_path))
    calls: list[list[str]] = []
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda command, check: calls.append(command) or subprocess.CompletedProcess(command, 0),
    )

    assert main(["graph", str(topology)]) == 0
    assert calls == [["sudo", "containerlab", "graph", "-t", str(topology)]]
    assert "sudo containerlab graph -t" in capsys.readouterr().out


def test_cli_graph_reports_missing_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as error:
        main(["graph", str(tmp_path / "missing.clab.yml")])
    assert error.value.code == 2
    assert "topology file not found" in capsys.readouterr().err

    topology = tmp_path / "lab.clab.yml"
    topology.write_text("name: lab\n", encoding="utf-8")
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not run"))
    assert main(["graph", str(topology)]) == 1
    assert "'containerlab' was not found" in capsys.readouterr().err


def test_cli_compile_subcommand(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "out"

    assert main(["compile", str(_SAMPLE), "-o", str(output), "--visualize"]) == 0
    assert (output / "batfish_snapshot" / "configs" / "R1-Core.cfg").is_file()
    assert (output / "containerlab" / "thapathali-lab.clab.yml").is_file()
    assert (output / "topology.html").is_file()
    assert "Interactive map" in capsys.readouterr().out


def test_cli_requires_a_command(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main([])
    assert error.value.code == 2
    assert "COMMAND" in capsys.readouterr().err


# --- Start-location auto-detection (examples/thapathali_complex.json) ---


@pytest.mark.parametrize(
    ("src_ip", "expected"),
    [
        ("10.0.10.100", "Student-Lab-PC"),
        ("10.0.40.50", "Faculty-PC"),
        ("10.0.10.55", "@enter(R2-Core-Dept[GigabitEthernet0/1])"),
        ("10.0.20.99", "@enter(R1-Core-Admin[GigabitEthernet0/1])"),
        ("10.0.12.2", "R2-Core-Dept"),
        ("10.255.0.1", "R1-Core-Admin"),
    ],
)
def test_resolve_start_location(src_ip: str, expected: str) -> None:
    verifier = TwinVerifier(session_factory=lambda host, port: pytest.fail("must not connect"))

    assert verifier.resolve_start_location(src_ip, _complex_evidence()) == expected


def test_resolve_start_location_prefers_most_specific_router_subnet() -> None:
    evidence = _complex_evidence()
    router = evidence.get_node("R1-Core-Admin")
    router.interfaces[0].ip_address = "10.0.0.1/8"

    verifier = TwinVerifier()
    assert verifier.resolve_start_location("10.0.12.77", evidence) == (
        "@enter(R2-Core-Dept[GigabitEthernet0/0])"
    )
    assert verifier.resolve_start_location("10.9.9.9", evidence) == (
        "@enter(R1-Core-Admin[GigabitEthernet0/0])"
    )


def test_resolve_start_location_errors() -> None:
    verifier = TwinVerifier()

    with pytest.raises(ValueError, match="Source IP does not belong to any known network"):
        verifier.resolve_start_location("192.168.99.5", _complex_evidence())
    with pytest.raises(ValueError, match="Invalid source IP"):
        verifier.resolve_start_location("not-an-ip", _complex_evidence())
    with pytest.raises(ValueError, match="No evidence available"):
        verifier.resolve_start_location("10.0.10.100")


def test_trace_auto_detects_start_location_and_reports_denied(tmp_path: Path) -> None:
    evidence = _complex_evidence()
    snapshot = TwinBuilder().build_batfish_snapshot(evidence, tmp_path)
    session = FakeSession(_default_answers())
    verifier = _verifier(session)
    verifier.load_snapshot(snapshot, evidence=evidence)

    assert verifier.resolve_start_location("10.0.10.100") == "Student-Lab-PC"
    result = verifier.test_trace(src_ip="10.0.10.100", dst_ip="10.0.20.10")

    assert session.calls[-1] == (
        "traceroute",
        {
            "startLocation": "Student-Lab-PC",
            "headers": {"srcIps": "10.0.10.100", "dstIps": "10.0.20.10"},
        },
    )
    assert result["start_node"] == "Student-Lab-PC"
    assert result["start_location_auto_detected"] is True
    assert result["disposition"] == "DENIED"
    assert result["dropped_by_acl"] == "BLOCK_STUDENT_TO_EXAM"


def test_trace_without_start_node_or_evidence_fails(snapshot_dir: Path) -> None:
    verifier = _verifier(FakeSession(_default_answers()))
    verifier.load_snapshot(snapshot_dir)

    with pytest.raises(ValueError, match="No evidence available"):
        verifier.test_trace(src_ip="10.0.10.100", dst_ip="10.0.20.10")


def test_cli_verify_auto_detects_node_from_compiled_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "dist"
    assert main(["compile", str(_COMPLEX), "-o", str(output)]) == 0
    assert (output / "evidence.json").is_file()
    capsys.readouterr()
    _patch_cli_verifier(monkeypatch, _default_answers())

    exit_code = main(
        [
            "verify",
            str(output / "batfish_snapshot"),
            "--src-ip",
            "10.0.10.100",
            "--dst-ip",
            "10.0.20.10",
        ]
    )

    stdout = capsys.readouterr().out
    assert exit_code == 0
    assert (
        "Traceroute 10.0.10.100 -> 10.0.20.10 from Student-Lab-PC (auto-detected): DENIED"
        in stdout
    )


def test_cli_verify_auto_detect_with_explicit_evidence_and_unknown_ip(
    snapshot_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_cli_verifier(monkeypatch, _default_answers())
    base = ["verify", str(snapshot_dir), "--evidence", str(_COMPLEX)]

    assert main([*base, "--src-ip", "10.0.10.55", "--dst-ip", "10.0.20.10"]) == 0
    assert "from @enter(R2-Core-Dept[GigabitEthernet0/1]) (auto-detected)" in (
        capsys.readouterr().out
    )

    assert main([*base, "--src-ip", "192.168.99.5", "--dst-ip", "10.0.20.10"]) == 1
    assert "Source IP does not belong to any known network" in capsys.readouterr().err


def test_cli_verify_auto_detect_requires_evidence(
    snapshot_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as error:
        main(["verify", str(snapshot_dir), "--src-ip", "10.0.10.100", "--dst-ip", "10.0.20.10"])

    assert error.value.code == 2
    assert "pass --evidence <json> or --node <name>" in capsys.readouterr().err