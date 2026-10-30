"""Tests for Component 03 (Intent Library) and its twin-builder CLI commands.

Batfish is never contacted: ``PolicySession`` imitates the pybatfish session API
and the ``SECURITY_POLICY_CORE`` ACL of ``examples/thapathali_complex.json``.
"""

from __future__ import annotations

import json
from ipaddress import ip_network
from pathlib import Path
import shutil
from types import SimpleNamespace
from typing import Any, Iterator

from pydantic import ValidationError
import pytest

from src.intent_library import (
    EndpointGroup,
    EndpointGroupRegistry,
    Intent,
    IntentEvaluator,
    IntentResolver,
    IntentStatus,
    IntentSuite,
    IntentType,
    SuiteEvaluationReport,
    auto_discover_groups,
    load_group_registry,
    load_intent_suite,
    save_group_registry,
    save_intent_suite,
)
from src.twin_builder import Interface, NetworkEvidence, Node, TwinBuilder, TwinVerifier
from src.twin_builder import cli
from src.twin_builder.cli import main


_ROOT = Path(__file__).resolve().parents[1]
_COMPLEX = _ROOT / "examples" / "thapathali_complex.json"
_GROUPS = _ROOT / "examples" / "thapathali_groups.json"
_INTENTS = _ROOT / "examples" / "thapathali_intents.json"
_STUDENTS = ip_network("10.0.10.0/24")
_EXAM_DB = ip_network("10.0.20.10/32")


def _evidence() -> NetworkEvidence:
    return NetworkEvidence.model_validate_json(_COMPLEX.read_text(encoding="utf-8"))


def _answer(rows: list[dict[str, Any]]) -> SimpleNamespace:
    return SimpleNamespace(answer=lambda: SimpleNamespace(frame=lambda: rows))


def _step(action: str, **detail: Any) -> SimpleNamespace:
    return SimpleNamespace(action=action, detail=SimpleNamespace(**detail) if detail else None)


def _trace(disposition: str, *hops: tuple[str, list[SimpleNamespace]]) -> SimpleNamespace:
    return SimpleNamespace(
        disposition=disposition,
        hops=[SimpleNamespace(node=node, steps=steps) for node, steps in hops],
    )


class PolicySession:
    """Fake pybatfish session whose traceroutes follow the complex example's ACL."""

    def __init__(
        self, enforce_acl: bool = True, loops: list[dict[str, Any]] | None = None
    ) -> None:
        self.enforce_acl = enforce_acl
        self.loops = loops or []
        self.traceroutes: list[tuple[str, dict[str, Any]]] = []
        self.q = SimpleNamespace(
            fileParseStatus=lambda: _answer([{"File_Name": "configs/R1.cfg", "Status": "PASSED"}]),
            initIssues=lambda: _answer([]),
            traceroute=self._traceroute,
            detectLoops=lambda: _answer(self.loops),
        )

    def set_network(self, name: str) -> str:
        return name

    def init_snapshot(self, upload: str, name: str, overwrite: bool) -> str:
        return name

    def _traceroute(self, startLocation: str, headers: dict[str, Any]) -> SimpleNamespace:
        self.traceroutes.append((startLocation, headers))
        source = ip_network(headers["srcIps"], strict=False)
        destination = ip_network(headers["dstIps"], strict=False)
        ingress = _step("RECEIVED", inputInterface="GigabitEthernet0/1")
        egress = _step("TRANSMITTED", outputInterface="GigabitEthernet0/0")
        if self.enforce_acl and source.subnet_of(_STUDENTS) and destination.subnet_of(_EXAM_DB):
            trace = _trace(
                "DENIED_IN",
                ("r2-core-dept", [ingress, _step("FORWARDED"), egress]),
                (
                    "r1-core-admin",
                    [
                        _step(
                            "DENIED",
                            filter="SECURITY_POLICY_CORE",
                            inputInterface="GigabitEthernet0/0",
                        )
                    ],
                ),
            )
        else:
            trace = _trace(
                "ACCEPTED",
                ("r2-core-dept", [ingress, _step("FORWARDED")]),
                ("r1-core-admin", [_step("RECEIVED", inputInterface="GigabitEthernet0/0")]),
            )
        return _answer([{"Flow": "flow", "Traces": [trace], "TraceCount": 1}])


def _verifier(session: PolicySession, tmp_path: Path, evidence: NetworkEvidence) -> TwinVerifier:
    verifier = TwinVerifier(
        session_factory=lambda host, port: session, header_factory=lambda **kwargs: kwargs
    )
    snapshot = TwinBuilder().build_batfish_snapshot(evidence, tmp_path / "twin")
    verifier.load_snapshot(snapshot, evidence=evidence)
    return verifier


def _evaluator(
    session: PolicySession,
    tmp_path: Path,
    evidence: NetworkEvidence,
    registry: EndpointGroupRegistry | None = None,
) -> IntentEvaluator:
    registry = registry if registry is not None else load_group_registry(_GROUPS)
    return IntentEvaluator(_verifier(session, tmp_path, evidence), evidence, registry)


def _intent(**overrides: Any) -> Intent:
    values: dict[str, Any] = {
        "id": "INT-T",
        "name": "Test intent",
        "type": "isolation",
        "description": "test",
        "src": "group:students",
        "dst": "group:exam_db",
        "expected": "DENIED",
    }
    values.update(overrides)
    return Intent.model_validate(values)


# --- auto-discovery ---------------------------------------------------------------------------


def test_auto_discover_groups_from_evidence() -> None:
    registry = auto_discover_groups(_evidence())
    groups = {group.name: group for group in registry.groups}

    assert groups["student_lab_pc"].hosts == ["10.0.10.100/32"]
    assert groups["student_lab_pc"].subnets == []
    assert groups["exam_db_server"].hosts == ["10.0.20.10/32"]
    assert groups["student_lab"].subnets == ["10.0.10.0/24"]
    assert groups["student_lab"].description == "Student Lab"
    assert groups["faculty_lan"].subnets == ["10.0.40.0/24"]
    assert groups["exam_servers"].subnets == ["10.0.20.0/24"]
    assert groups["emis_services"].subnets == ["10.0.30.0/24"]
    assert groups["net_10_0_12_0_24"].subnets == ["10.0.12.0/24"]
    assert groups["net_10_255_0_1_32"].subnets == ["10.255.0.1/32"]
    assert not any(name.startswith("sw") for name in groups)
    assert EndpointGroupRegistry.model_validate(registry.model_dump()) == registry


def test_auto_discover_vlan_description_and_fallback_rules() -> None:
    evidence = NetworkEvidence(
        name="lab",
        nodes=[
            Node(
                name="R1",
                kind="router",
                interfaces=[
                    Interface("Gi0/0", "10.1.1.1/24", vlan_id=10, description="Admin Office!"),
                    Interface("Gi0/1", "192.168.5.1/24", description="***"),
                    Interface("Gi0/2"),
                ],
            ),
            Node(
                name="H-1",
                kind="host",
                interfaces=[Interface("eth1", "10.1.1.5/24", vlan_id=10)],
            ),
            Node(name="H-2", kind="host", interfaces=[Interface("eth1", "10.1.1.6/24")]),
        ],
    )

    groups = {group.name: group for group in auto_discover_groups(evidence).groups}

    assert groups["admin_office"].subnets == ["10.1.1.0/24"]
    assert groups["vlan_10"].subnets == ["10.1.1.0/24"]
    assert groups["net_192_168_5_0_24"].subnets == ["192.168.5.0/24"]
    assert groups["h_1"].hosts == ["10.1.1.5/32"]
    assert groups["h_2"].hosts == ["10.1.1.6/32"]
    assert "net_10_1_1_0_24" not in groups
    assert len(groups) == 5


# --- resolver ---------------------------------------------------------------------------------


def test_resolver_expands_cartesian_product_of_groups() -> None:
    registry = EndpointGroupRegistry(
        groups=[
            EndpointGroup(name="clients", subnets=["10.0.10.0/24", "10.0.40.0/24"]),
            EndpointGroup(name="servers", hosts=["10.0.20.10", "10.0.30.10/32"]),
        ]
    )
    resolver = IntentResolver(registry, _evidence(), TwinVerifier())
    intent = _intent(
        type="service_access",
        src="group:clients",
        dst="group:servers",
        service="web",
        expected="ACCEPTED",
    )

    checks = resolver.resolve_intent(intent)

    assert [(check.src_ip, check.dst_ip) for check in checks] == [
        ("10.0.10.0/24", "10.0.20.10/32"),
        ("10.0.10.0/24", "10.0.30.10/32"),
        ("10.0.40.0/24", "10.0.20.10/32"),
        ("10.0.40.0/24", "10.0.30.10/32"),
    ]
    assert {(check.protocol, check.dst_port, check.expected) for check in checks} == {
        ("tcp", 443, "ACCEPTED")
    }
    assert [check.start_location for check in checks] == [
        "@enter(R2-Core-Dept[GigabitEthernet0/1])",
        "@enter(R2-Core-Dept[GigabitEthernet0/1])",
        "@enter(R2-Core-Dept[GigabitEthernet0/2])",
        "@enter(R2-Core-Dept[GigabitEthernet0/2])",
    ]


def test_resolver_targets_services_and_host_start_locations() -> None:
    resolver = IntentResolver(load_group_registry(_GROUPS), _evidence(), TwinVerifier())

    assert resolver.expand_targets("group:exam_db") == ["10.0.20.10/32"]
    assert resolver.expand_targets("10.0.30.10") == ["10.0.30.10"]
    assert resolver.expand_targets("10.0.40.0/24") == ["10.0.40.0/24"]
    assert resolver.expand_targets(None) == ["any"]
    assert resolver.expand_targets("any") == ["any"]
    assert resolver.resolve_service_ports("http", None, None) == ("tcp", 80)
    assert resolver.resolve_service_ports("ssh", "ip", None) == ("tcp", 22)
    assert resolver.resolve_service_ports("dns", None, None) == ("udp", 53)
    assert resolver.resolve_service_ports("web", None, 8443) == ("tcp", 8443)
    assert resolver.resolve_service_ports(None, "udp", 161) == ("udp", 161)
    assert resolver.resolve_service_ports(None, None, None) == ("ip", None)
    with pytest.raises(ValueError, match="Unknown service"):
        resolver.resolve_service_ports("smtp", None, None)
    with pytest.raises(ValueError, match="requires protocol"):
        resolver.resolve_service_ports(None, "ip", 80)

    [check] = resolver.resolve_intent(
        _intent(type="reachability", src="group:exam_db", dst="any", expected="ACCEPTED")
    )
    assert check.start_location == "Exam-DB-Server"
    assert check.dst_ip == "0.0.0.0/0"

    [loop_check] = resolver.resolve_intent(
        _intent(type="loop_free", src=None, dst=None, expected="LOOP_FREE")
    )
    assert loop_check.expected == "LOOP_FREE"
    assert loop_check.start_location == "*"


def test_unknown_group_raises_descriptive_error() -> None:
    resolver = IntentResolver(load_group_registry(_GROUPS), _evidence(), TwinVerifier())

    with pytest.raises(ValueError, match="Unknown endpoint group 'nope'.*students"):
        resolver.expand_targets("group:nope")
    with pytest.raises(ValueError, match="Unknown endpoint group 'nope'"):
        resolver.resolve_intent(_intent(dst="group:nope"))
    with pytest.raises(ValueError, match="Target must be"):
        resolver.expand_targets("not-a-target")
    empty_registry = EndpointGroupRegistry(groups=[EndpointGroup(name="empty")])
    with pytest.raises(ValueError, match="has no subnets or hosts"):
        IntentResolver(empty_registry, _evidence(), TwinVerifier()).expand_targets("group:empty")


def test_resolver_auto_discovers_registry_when_none() -> None:
    resolver = IntentResolver(None, _evidence(), TwinVerifier())

    assert resolver.registry.get_group("student_lab") is not None
    assert resolver.expand_targets("group:faculty_pc") == ["10.0.40.50/32"]


# --- schema and persistence -------------------------------------------------------------------


def test_example_suite_and_registry_load() -> None:
    suite = load_intent_suite(_INTENTS)
    registry = load_group_registry(_GROUPS)

    assert [intent.id for intent in suite.intents] == ["INT-001", "INT-002", "INT-003", "INT-004"]
    assert suite.get_by_id("INT-002").service == "web"
    assert suite.get_by_id("INT-404") is None
    assert [intent.id for intent in suite.filter_by_type("loop_free")] == ["INT-004"]
    assert [intent.id for intent in suite.filter_by_type(IntentType.ISOLATION)] == ["INT-001"]
    assert suite.get_by_id("INT-002").candidate_probe.destination_port == 443
    assert [group.name for group in registry.groups] == [
        "students",
        "exam_db",
        "emis_portal",
        "faculty",
    ]
    assert registry.get_all_prefixes("faculty") == ["10.0.40.0/24"]
    assert registry.get_group("missing") is None


def test_intent_suite_and_registry_round_trip(tmp_path: Path) -> None:
    suite = load_intent_suite(_INTENTS)
    registry = load_group_registry(_GROUPS)
    suite_path = tmp_path / "nested" / "intents.json"
    registry_path = tmp_path / "groups.json"

    save_intent_suite(suite, suite_path)
    save_group_registry(registry, registry_path)

    assert load_intent_suite(suite_path) == suite
    assert load_group_registry(registry_path) == registry
    raw = json.loads(suite_path.read_text(encoding="utf-8"))
    assert raw["intents"][0]["type"] == "isolation"
    assert raw["intents"][0]["severity"] == "CRITICAL"
    assert "dst_port" not in raw["intents"][0]
    assert list(tmp_path.joinpath("nested").iterdir()) == [suite_path]


def test_loader_reports_invalid_files(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"name": "x", "intents": [{"id": "A"}]}', encoding="utf-8")

    with pytest.raises(ValueError, match="not a valid intent suite"):
        load_intent_suite(path)
    with pytest.raises(FileNotFoundError):
        load_group_registry(tmp_path / "missing.json")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"expected": "ACCEPTED"}, "isolation intents must expect 'DENIED'"),
        ({"type": "reachability"}, "reachability intents must expect 'ACCEPTED'"),
        ({"dst": None}, "require both src and dst"),
        ({"src": "any"}, "not 'any'"),
        ({"src": "10.0.10.300/24"}, "not a valid IPv4"),
        ({"dst": "group:bad name"}, "Group reference"),
        ({"dst_port": 80}, "dst_port requires protocol"),
        ({"service": "smtp"}, "Unknown service"),
        ({"service": "dns", "protocol": "tcp"}, "uses udp"),
        ({"type": "service_access", "expected": "ACCEPTED"}, "require service or dst_port"),
        ({"type": "loop_free", "expected": "LOOP_FREE"}, "do not take src"),
        ({"id": "INT 1"}, "Intent id"),
        ({"extra": True}, "Extra inputs"),
    ],
)
def test_intent_validation(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _intent(**overrides)


def test_registry_and_suite_reject_duplicates() -> None:
    with pytest.raises(ValidationError, match="Duplicate endpoint group names"):
        EndpointGroupRegistry(groups=[EndpointGroup(name="a"), EndpointGroup(name="a")])
    with pytest.raises(ValidationError, match="Duplicate intent ids"):
        IntentSuite(name="s", intents=[_intent(), _intent()])
    with pytest.raises(ValidationError, match="single address or /32"):
        EndpointGroup(name="a", hosts=["10.0.0.0/24"])
    with pytest.raises(ValidationError, match="host bits set|not a valid"):
        EndpointGroup(name="a", subnets=["10.0.10.1/24"])


# --- evaluator --------------------------------------------------------------------------------


def test_evaluator_maps_denied_to_passed_for_isolation(tmp_path: Path) -> None:
    session = PolicySession()
    evidence = _evidence()
    evaluator = _evaluator(session, tmp_path, evidence)

    result = evaluator.evaluate_intent(load_intent_suite(_INTENTS).get_by_id("INT-001"))

    assert result.status is IntentStatus.PASSED
    assert result.disposition == "DENIED"
    assert result.dropping_filter == "SECURITY_POLICY_CORE"
    assert result.dependency_cone == [
        "r2-core-dept",
        "r2-core-dept[GigabitEthernet0/1]",
        "r2-core-dept[GigabitEthernet0/0]",
        "r1-core-admin",
        "r1-core-admin[GigabitEthernet0/0]",
    ]
    assert result.trace_hops == [
        "10.0.10.0/24 -> 10.0.20.10/32 (ip): r2-core-dept -> r1-core-admin [DENIED]"
    ]
    assert session.traceroutes == [
        (
            "@enter(R2-Core-Dept[GigabitEthernet0/1])",
            {"srcIps": "10.0.10.0/24", "dstIps": "10.0.20.10/32"},
        )
    ]


def test_evaluator_sends_service_constraints(tmp_path: Path) -> None:
    session = PolicySession()
    evidence = _evidence()
    evaluator = _evaluator(session, tmp_path, evidence)

    result = evaluator.evaluate_intent(load_intent_suite(_INTENTS).get_by_id("INT-002"))

    assert result.status is IntentStatus.PASSED
    assert session.traceroutes[0][1] == {
        "srcIps": "10.0.10.0/24",
        "dstIps": "10.0.30.10/32",
        "ipProtocols": ["TCP"],
        "dstPorts": "443",
    }
    assert result.checks[0].check.protocol == "tcp"
    assert result.checks[0].check.dst_port == 443


def test_evaluate_suite_reports_coverage(tmp_path: Path) -> None:
    evidence = _evidence()
    suite = load_intent_suite(_INTENTS)
    registry = load_group_registry(_GROUPS)

    healthy = _evaluator(PolicySession(), tmp_path / "a", evidence, registry)
    report = healthy.evaluate_suite(suite)
    assert (report.total_intents, report.passed_count, report.failed_count) == (4, 4, 0)
    assert report.verification_coverage == 1.0
    loop_result = report.results[3]
    assert loop_result.disposition == "LOOP_FREE"
    assert loop_result.dependency_cone == ["R1-Core-Admin", "R2-Core-Dept"]

    broken = IntentEvaluator(
        _verifier(PolicySession(enforce_acl=False), tmp_path / "b", evidence), evidence, registry
    )
    report = broken.evaluate_suite(suite)
    assert (report.passed_count, report.failed_count, report.error_count) == (3, 1, 0)
    assert report.verification_coverage == 0.75
    failed = report.results[0]
    assert failed.status is IntentStatus.FAILED
    assert failed.disposition == "ACCEPTED"
    assert "did not return DENIED" in failed.details
    assert failed.dropping_filter is None
    assert SuiteEvaluationReport.model_validate_json(report.model_dump_json()) == report


def test_loop_free_fails_when_batfish_finds_loops(tmp_path: Path) -> None:
    loop = _trace(
        "LOOP", ("r1-core-admin", [_step("FORWARDED")]), ("r2-core-dept", [_step("FORWARDED")])
    )
    session = PolicySession(loops=[{"Flow": "10.0.10.5->10.9.9.9", "Traces": [loop]}])
    evidence = _evidence()
    evaluator = IntentEvaluator(_verifier(session, tmp_path, evidence), evidence)

    result = evaluator.evaluate_intent(load_intent_suite(_INTENTS).get_by_id("INT-004"))

    assert result.status is IntentStatus.FAILED
    assert result.disposition == "LOOP"
    assert result.dependency_cone == ["r1-core-admin", "r2-core-dept"]
    assert result.trace_hops == ["10.0.10.5->10.9.9.9: r1-core-admin -> r2-core-dept [LOOP]"]


def test_evaluator_reports_errors(tmp_path: Path) -> None:
    session = PolicySession()
    evidence = _evidence()
    evaluator = _evaluator(session, tmp_path, evidence)

    unknown = evaluator.evaluate_intent(_intent(dst="group:nope"))
    assert unknown.status is IntentStatus.ERROR
    assert "Unknown endpoint group 'nope'" in unknown.details

    outside = evaluator.evaluate_intent(_intent(src="192.168.99.0/24"))
    assert outside.status is IntentStatus.ERROR
    assert "does not belong to any known network" in outside.details

    def broken(**kwargs: Any) -> SimpleNamespace:
        raise RuntimeError("batfish exploded")

    session.q.traceroute = broken
    failed_query = evaluator.evaluate_intent(_intent())
    assert failed_query.status is IntentStatus.ERROR
    assert "batfish exploded" in failed_query.details
    assert failed_query.checks[0].error is not None

    not_loaded = IntentEvaluator(
        TwinVerifier(), evidence, load_group_registry(_GROUPS)
    ).evaluate_intent(_intent())
    assert not_loaded.status is IntentStatus.ERROR
    assert "load_snapshot" in not_loaded.details


# --- CLI --------------------------------------------------------------------------------------


@pytest.fixture
def compiled(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    output = tmp_path / "dist"
    assert main(["compile", str(_COMPLEX), "-o", str(output)]) == 0
    capsys.readouterr()
    return output


def _patch_batfish(monkeypatch: pytest.MonkeyPatch, session: PolicySession) -> None:
    monkeypatch.setattr(
        cli,
        "TwinVerifier",
        lambda host, port: TwinVerifier(
            host,
            port,
            session_factory=lambda h, p: session,
            header_factory=lambda **kwargs: kwargs,
        ),
    )


def test_cli_check_intents_prints_report_and_json(
    compiled: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_batfish(monkeypatch, PolicySession())
    report_path = tmp_path / "reports" / "intents.json"

    exit_code = main(
        [
            "check-intents",
            str(compiled / "batfish_snapshot"),
            str(_INTENTS),
            "--groups",
            str(_GROUPS),
            "--json-out",
            str(report_path),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert f"Endpoint groups: 4 loaded from {_GROUPS}" in output
    assert "INT-001  PASSED  CRITICAL  isolation" in output
    assert (
        "check 10.0.10.0/24 -> 10.0.20.10/32 (ip) from "
        "@enter(R2-Core-Dept[GigabitEthernet0/1]): DENIED [ok]"
    ) in output
    assert "dropped by SECURITY_POLICY_CORE" in output
    assert "check 10.0.10.0/24 -> 10.0.30.10/32 (tcp/443)" in output
    assert "cone: r2-core-dept" in output
    assert "Verification coverage (Vq): 4/4 = 1.00" in output
    report = SuiteEvaluationReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    assert report.passed_count == 4


def test_cli_check_intents_failure_exit_and_auto_groups(
    compiled: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_batfish(monkeypatch, PolicySession(enforce_acl=False))
    suite = IntentSuite(
        name="auto",
        intents=[_intent(src="group:student_lab", dst="group:exam_db_server")],
    )
    suite_path = tmp_path / "auto.json"
    save_intent_suite(suite, suite_path)

    exit_code = main(["check-intents", str(compiled / "batfish_snapshot"), str(suite_path)])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "auto-discovered from thapathali-campus-core" in output
    assert "INT-T  FAILED" in output
    assert "[MISMATCH]" in output
    assert "details: 1 of 1 check(s) did not return DENIED" in output
    assert "Verification coverage (Vq): 0/1 = 0.00" in output


def test_cli_check_intents_input_errors(
    compiled: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        main(["check-intents", str(compiled / "batfish_snapshot"), str(bad)])
    assert error.value.code == 2
    assert "cannot load intents or groups" in capsys.readouterr().err

    with pytest.raises(SystemExit) as error:
        main(["check-intents", str(tmp_path / "elsewhere" / "snap"), str(_INTENTS)])
    assert error.value.code == 2
    assert "pass --evidence <json>" in capsys.readouterr().err


def _scripted_input(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> list[str]:
    prompts: list[str] = []
    remaining: Iterator[str] = iter(answers)

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        try:
            return next(remaining)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", fake_input)
    return prompts


def test_cli_add_intent_wizard_appends_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    intents_path = tmp_path / "intents.json"
    shutil.copyfile(_INTENTS, intents_path)
    prompts = _scripted_input(
        monkeypatch,
        [
            "INT-001",  # duplicate -> re-prompt
            "",  # default INT-005
            "Students blocked from EMIS SSH",
            "9",  # invalid type -> re-prompt
            "1",  # isolation
            "1",  # students
            "3",  # emis_portal
            "ssh",
            "1",  # CRITICAL
            "",  # default description
        ],
    )

    exit_code = main(
        [
            "add-intent",
            "--intents",
            str(intents_path),
            "--evidence",
            str(_COMPLEX),
            "--groups",
            str(_GROUPS),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "[1] students [aliases: student_lab] - Student computer lab (10.0.10.0/24)" in output
    assert "[3] emis_portal" in output
    assert "'INT-001' already exists" in output
    assert "enter a number from 1 to 4" in output
    assert prompts[1] == "Intent ID [INT-005]: "
    suite = load_intent_suite(intents_path)
    assert len(suite.intents) == 5
    added = suite.get_by_id("INT-005")
    assert added is not None
    assert added.type is IntentType.ISOLATION
    assert (added.src, added.dst, added.service) == ("group:students", "group:emis_portal", "ssh")
    assert added.protocol == "tcp"
    assert added.severity.value == "CRITICAL"
    assert added.expected == "DENIED"
    assert added.description == "group:students must not reach group:emis_portal (ssh traffic)"
    assert "Added INT-005 'Students blocked from EMIS SSH' (isolation, CRITICAL)" in output
    assert f"Saved {intents_path} (5 intents)" in output


def test_cli_add_intent_creates_suite_with_auto_groups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    intents_path = tmp_path / "new" / "intents.json"
    _scripted_input(monkeypatch, ["", "Core loop free", "4", "", ""])

    assert main(["add-intent", "--intents", str(intents_path), "--evidence", str(_COMPLEX)]) == 0

    output = capsys.readouterr().out
    assert "] student_lab - Student Lab (10.0.10.0/24)" in output
    suite = load_intent_suite(intents_path)
    assert suite.name == "thapathali-campus-core-intents"
    [intent] = suite.intents
    assert (intent.id, intent.type) == ("INT-001", IntentType.LOOP_FREE)
    assert intent.expected == "LOOP_FREE"
    assert intent.severity.value == "HIGH"
    assert "groups were auto-discovered" in output


def test_cli_add_intent_service_port_and_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    intents_path = tmp_path / "intents.json"
    shutil.copyfile(_INTENTS, intents_path)
    original = intents_path.read_text(encoding="utf-8")
    _scripted_input(
        monkeypatch,
        [
            "INT-010",
            "Faculty DNS",
            "3",  # service access
            "4",  # faculty
            "10.0.30.10",
            "",  # blank service is rejected for service access
            "udp/99999",
            "udp/53",
            "3",  # MEDIUM
            "custom",
        ],
    )

    assert main(["add-intent", "--intents", str(intents_path), "--groups", str(_GROUPS)]) == 0
    added = load_intent_suite(intents_path).get_by_id("INT-010")
    assert added is not None
    assert added.type is IntentType.SERVICE_ACCESS
    assert (added.src, added.dst) == ("group:faculty", "10.0.30.10")
    assert (added.protocol, added.dst_port, added.service) == ("udp", 53, None)
    assert added.description == "custom"
    output = capsys.readouterr().out
    assert "service access intents need a service name or port" in output
    assert "port must be between 1 and 65535" in output

    _scripted_input(monkeypatch, ["INT-011", "Half finished"])
    before = intents_path.read_text(encoding="utf-8")
    assert main(["add-intent", "--intents", str(intents_path), "--groups", str(_GROUPS)]) == 130
    assert intents_path.read_text(encoding="utf-8") == before
    assert "was not changed" in capsys.readouterr().err
    assert before != original


def test_cli_add_intent_requires_groups_or_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as error:
        main(["add-intent", "--intents", str(tmp_path / "x.json")])
    assert error.value.code == 2
    assert "--evidence is required unless --groups is given" in capsys.readouterr().err


# --- aliases and strict isolation -------------------------------------------------------------


def test_group_aliases_resolve_to_curated_groups() -> None:
    registry = load_group_registry(_GROUPS)

    assert registry.get_group("student_lab") is registry.get_group("students")
    assert registry.get_all_prefixes("exam_db_server") == ["10.0.20.10/32"]
    assert registry.get_all_prefixes("faculty_lan") == registry.get_all_prefixes("faculty")
    with pytest.raises(ValueError, match=r"students \(aliases: student_lab\)"):
        registry.get_all_prefixes("nope")

    resolver = IntentResolver(registry, _evidence(), TwinVerifier())
    by_alias = resolver.resolve_intent(
        _intent(src="group:student_lab", dst="group:exam_db_server")
    )
    by_name = resolver.resolve_intent(_intent(src="group:students", dst="group:exam_db"))
    assert by_alias == by_name


@pytest.mark.parametrize(
    ("groups", "message"),
    [
        (
            [{"name": "a", "aliases": ["b"]}, {"name": "b"}],
            "Alias 'b' of group 'a' conflicts with group 'b'",
        ),
        (
            [{"name": "a", "aliases": ["x"]}, {"name": "b", "aliases": ["x"]}],
            "Alias 'x' of group 'b' conflicts with an alias of 'a'",
        ),
        ([{"name": "a", "aliases": ["a"]}], "Alias 'a' of group 'a' conflicts with group 'a'"),
        ([{"name": "a", "aliases": ["bad alias"]}], "Endpoint group alias"),
    ],
)
def test_registry_rejects_conflicting_aliases(groups: list[dict[str, Any]], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        EndpointGroupRegistry.model_validate({"groups": groups})


@pytest.mark.parametrize("use_curated_groups", [True, False])
def test_example_suite_passes_with_curated_or_auto_groups(
    tmp_path: Path, use_curated_groups: bool
) -> None:
    evidence = _evidence()
    registry = (
        load_group_registry(_GROUPS) if use_curated_groups else auto_discover_groups(evidence)
    )
    evaluator = IntentEvaluator(_verifier(PolicySession(), tmp_path, evidence), evidence, registry)

    report = evaluator.evaluate_suite(load_intent_suite(_INTENTS))

    assert [result.status for result in report.results] == [IntentStatus.PASSED] * 4
    assert report.verification_coverage == 1.0


@pytest.mark.parametrize("blackhole", ["NO_ROUTE", "NULL_ROUTED"])
def test_isolation_by_blackhole_fails(tmp_path: Path, blackhole: str) -> None:
    session = PolicySession()
    evaluator = _evaluator(session, tmp_path, _evidence())
    session.q.traceroute = lambda startLocation, headers: _answer(
        [{"Traces": [_trace(blackhole, ("r2-core-dept", [_step(blackhole)]))]}]
    )

    result = evaluator.evaluate_intent(_intent())

    assert result.status is IntentStatus.FAILED
    assert result.disposition == blackhole
    assert f"=> {blackhole} (blocked, but not by an ACL/filter)" in result.details
    assert result.dropping_filter is None


def test_cli_check_intents_example_suite_without_groups(
    compiled: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_batfish(monkeypatch, PolicySession())

    assert main(["check-intents", str(compiled / "batfish_snapshot"), str(_INTENTS)]) == 0
    output = capsys.readouterr().out
    assert "auto-discovered from thapathali-campus-core" in output
    assert "Verification coverage (Vq): 4/4 = 1.00" in output
