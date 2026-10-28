"""Tests for JSON-to-artifact execution and the standard-library HTML visualizer."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from src.twin_builder import NetworkEvidence, generate_interactive_map
from src.twin_builder.cli import main


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SAMPLE = _REPOSITORY_ROOT / "examples" / "thapathali_lab.json"


def test_generate_interactive_map(tmp_path: Path) -> None:
    evidence = NetworkEvidence.model_validate_json(_SAMPLE.read_text(encoding="utf-8"))
    output = tmp_path / "nested" / "topology.html"

    assert generate_interactive_map(evidence, str(output)) == str(output)
    html = output.read_text(encoding="utf-8")
    payload = html.split('<script id="topology-data" type="application/json">', 1)[1]
    data = json.loads(payload.split("</script>", 1)[0])
    nodes = {node["id"]: node for node in data["nodes"]}

    for node in evidence.nodes:
        assert node.name in html
    assert nodes["R1-Core"]["color"] == "#ff6b6b"
    assert nodes["R1-Core"]["shape"] == "box"
    assert nodes["SW1-Distribution"]["color"] == "#4ecdc4"
    assert nodes["SW1-Distribution"]["shape"] == "diamond"
    assert nodes["Student-PC"]["color"] == "#ffe66d"
    assert nodes["Student-PC"]["shape"] == "dot"
    assert "GigabitEthernet0/0: 10.0.10.1/24" in nodes["R1-Core"]["title"]
    assert "Ingress ACL: BLOCK_STUDENT_TO_EXAM" in nodes["R1-Core"]["title"]
    assert len(data["edges"]) == len(evidence.links)
    assert data["edges"][0]["label"] == "GigabitEthernet0/0 <-> GigabitEthernet0/1"
    assert "physics: {enabled: true" in html
    assert "dragNodes: true" in html
    assert "https://unpkg.com/vis-network/standalone/umd/vis-network.min.js" in html
    assert "Map unavailable: Vis.js could not load" in html


def test_visualizer_escapes_embedded_script_text(tmp_path: Path) -> None:
    evidence = NetworkEvidence.model_validate_json(_SAMPLE.read_text(encoding="utf-8"))
    evidence.name = "</script><script>alert('example')</script>"
    evidence.nodes[0].interfaces[0].applied_egress_acl = "<b>example</b>"

    html_path = generate_interactive_map(evidence, str(tmp_path / "topology.html"))
    html = Path(html_path).read_text(encoding="utf-8")

    assert evidence.name not in html
    assert "\\u003c/script\\u003e" in html
    assert "title.textContent = node.title" in html
    assert "\\u003cb\\u003eexample\\u003c/b\\u003e" in html


def test_cli_executes_sample_end_to_end(tmp_path: Path) -> None:
    output = tmp_path / "lab output"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.twin_builder.cli",
            str(_SAMPLE),
            "--output",
            str(output),
            "--visualize",
        ],
        cwd=_REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    for node in ("R1-Core", "SW1-Distribution", "Exam-Server", "Student-PC"):
        assert (output / "batfish_snapshot" / "configs" / f"{node}.cfg").is_file()
    router_config = output / "batfish_snapshot" / "configs" / "R1-Core.cfg"
    config = router_config.read_text(encoding="utf-8")
    assert (
        "ip access-list extended BLOCK_STUDENT_TO_EXAM\n"
        " deny ip 10.0.10.0 0.0.0.255 10.0.20.10 0.0.0.0\n"
        " permit ip any any\n!"
    ) in config
    assert "ip access-group BLOCK_STUDENT_TO_EXAM in" in config
    assert (output / "containerlab" / "thapathali-lab.clab.yml").is_file()
    router_dir = output / "containerlab" / "clab-configs" / "R1-Core"
    assert (router_dir / "frr.conf").is_file()
    assert (router_dir / "daemons").is_file()
    assert (output / "topology.html").is_file()
    assert "Batfish snapshot" in result.stdout
    assert "Containerlab" in result.stdout
    assert "Interactive map" in result.stdout
    assert str(output / "topology.html") in result.stdout
    assert "Containerlab does not enforce them" in result.stderr


def test_cli_defaults_to_dist_without_visualization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    assert main([str(_SAMPLE)]) == 0
    assert (tmp_path / "dist" / "batfish_snapshot" / "configs" / "R1-Core.cfg").is_file()
    assert not (tmp_path / "dist" / "topology.html").exists()
    assert "Interactive map" not in capsys.readouterr().out


@pytest.mark.parametrize("input_text", ["not JSON", "[]", '{"name": "lab", "nodes": [1]}'])
def test_cli_reports_invalid_input_before_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], input_text: str
) -> None:
    input_path = tmp_path / "invalid.json"
    input_path.write_text(input_text, encoding="utf-8")
    output = tmp_path / "output"

    with pytest.raises(SystemExit) as error:
        main([str(input_path), "-o", str(output), "--visualize"])

    assert error.value.code == 2
    captured = capsys.readouterr()
    assert "cannot load evidence" in captured.err
    assert captured.out == ""
    assert not output.exists()


def test_cli_reports_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main([str(tmp_path / "missing.json")])

    assert error.value.code == 2
    assert "cannot load evidence" in capsys.readouterr().err


def test_cli_reports_output_write_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "not-a-directory"
    output.write_text("existing file", encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        main([str(_SAMPLE), "-o", str(output)])

    assert error.value.code == 1
    captured = capsys.readouterr()
    assert "cannot write twin artifacts" in captured.err
    assert captured.out == ""
