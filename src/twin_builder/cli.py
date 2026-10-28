"""Command-line entry point: compile evidence, verify snapshots, and graph labs.

Subcommands::

    twin-builder compile <input_json> [-o OUTPUT] [--visualize]
    twin-builder verify <snapshot_dir> [--node NODE --src-ip SRC --dst-ip DST]
    twin-builder graph <clab_yaml_path>

For backward compatibility, ``twin-builder <input_json> ...`` is treated as
``compile``.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Sequence

from .builder import TwinBuilder
from .schema import NetworkEvidence
from .verifier import TwinVerifier, VerificationError
from .visualizer import generate_interactive_map

_COMMANDS = ("compile", "verify", "graph")
EVIDENCE_FILENAME = "evidence.json"


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and dispatch to the selected subcommand."""
    arguments_list = list(sys.argv[1:] if argv is None else argv)
    if arguments_list and arguments_list[0] not in _COMMANDS and not arguments_list[0].startswith("-"):
        arguments_list.insert(0, "compile")
    parser = _build_parser()
    arguments = parser.parse_args(arguments_list)
    return int(arguments.handler(arguments, arguments.parser))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="twin-builder",
        description="Compile, verify, and visualise local network digital twins.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    compile_parser = subparsers.add_parser(
        "compile",
        help="Build Batfish and Containerlab artifacts from JSON evidence",
        description="Build local Batfish and Containerlab artifacts from JSON evidence.",
    )
    compile_parser.add_argument("input_file", type=Path, help="Path to a JSON NetworkEvidence file")
    compile_parser.add_argument(
        "-o", "--output", type=Path, default=Path("./dist"), help="Output directory (default: ./dist)"
    )
    compile_parser.add_argument(
        "--visualize", action="store_true", help="Also generate an interactive topology.html map"
    )
    compile_parser.set_defaults(handler=_run_compile, parser=compile_parser)

    verify_parser = subparsers.add_parser(
        "verify",
        help="Load a snapshot into a local Batfish service and inspect routes/traces",
        description=(
            "Load a generated snapshot into a local Batfish service, report parse status, "
            "print computed routes, and optionally trace a flow."
        ),
    )
    verify_parser.add_argument(
        "snapshot_dir", type=Path, help="Snapshot directory containing configs/ (e.g. dist/batfish_snapshot)"
    )
    verify_parser.add_argument(
        "--node",
        help="Start node/location for the traceroute (default: auto-detect from --src-ip)",
    )
    verify_parser.add_argument("--src-ip", type=_ip_address, help="Source IP for the traceroute")
    verify_parser.add_argument("--dst-ip", type=_ip_address, help="Destination IP for the traceroute")
    verify_parser.add_argument(
        "--evidence",
        type=Path,
        help=(
            "Evidence JSON used to auto-detect the start location when --node is omitted "
            f"(default: <snapshot_dir>/../{EVIDENCE_FILENAME} written by 'compile')"
        ),
    )
    verify_parser.add_argument("--network", default="campus_network", help="Batfish network name")
    verify_parser.add_argument("--host", default="localhost", help="Batfish host (default: localhost)")
    verify_parser.add_argument("--port", type=int, default=9996, help="Batfish port (default: 9996)")
    verify_parser.set_defaults(handler=_run_verify, parser=verify_parser)

    graph_parser = subparsers.add_parser(
        "graph",
        help="Open the Containerlab web graph for a generated topology",
        description="Run 'sudo containerlab graph -t <clab_yaml_path>' for a local topology file.",
    )
    graph_parser.add_argument("clab_yaml_path", type=Path, help="Path to a .clab.yml topology")
    graph_parser.set_defaults(handler=_run_graph, parser=graph_parser)
    return parser


def _ip_address(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value))
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"invalid IP address: {value!r}") from error


def _run_compile(arguments: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    try:
        evidence_text = arguments.input_file.read_text(encoding="utf-8")
        evidence = NetworkEvidence.model_validate_json(evidence_text)
    except (OSError, UnicodeError, ValueError) as error:
        parser.exit(2, f"{parser.prog}: error: cannot load evidence: {error}\n")

    builder = TwinBuilder()
    try:
        snapshot_path = builder.build_batfish_snapshot(evidence, arguments.output)
        topology_path = builder.build_containerlab(evidence, arguments.output)
        evidence_path = arguments.output / EVIDENCE_FILENAME
        evidence_path.write_text(evidence_text, encoding="utf-8")
        html_path = (
            generate_interactive_map(evidence, str(arguments.output / "topology.html"))
            if arguments.visualize
            else None
        )
    except OSError as error:
        parser.exit(1, f"{parser.prog}: error: cannot write twin artifacts: {error}\n")

    print(f"Twin Builder: {evidence.name}")
    print(f"  Nodes: {len(evidence.nodes)} | Links: {len(evidence.links)}")
    print(f"  Batfish snapshot : {snapshot_path}")
    print(f"  Containerlab     : {topology_path}")
    print(f"  Evidence copy    : {evidence_path}")
    if html_path is not None:
        print(f"  Interactive map  : {html_path}")
    if any(node.acls for node in evidence.nodes):
        print(
            "Note: ACLs are rendered only for Batfish; Containerlab does not enforce them.",
            file=sys.stderr,
        )
    return 0


def _run_verify(arguments: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if arguments.node is not None and not (arguments.src_ip and arguments.dst_ip):
        parser.error("--node requires --src-ip and --dst-ip")
    if bool(arguments.src_ip) != bool(arguments.dst_ip):
        parser.error("--src-ip and --dst-ip must be provided together")
    run_trace = bool(arguments.src_ip and arguments.dst_ip)
    evidence = None
    if run_trace and arguments.node is None:
        evidence = _load_verify_evidence(arguments, parser)
    try:
        verifier = TwinVerifier(host=arguments.host, port=arguments.port)
    except ValueError as error:
        parser.error(str(error))

    try:
        summary = verifier.load_snapshot(arguments.snapshot_dir, arguments.network, evidence)
        _print_parse_summary(summary)
        routes = verifier.get_computed_routes()
        _print_routes(routes)
        if run_trace:
            _print_trace(verifier.test_trace(arguments.node, arguments.src_ip, arguments.dst_ip))
    except (VerificationError, ValueError) as error:
        print(f"{parser.prog}: error: {error}", file=sys.stderr)
        return 1
    return 0 if summary["ok"] else 1


def _load_verify_evidence(
    arguments: argparse.Namespace, parser: argparse.ArgumentParser
) -> NetworkEvidence:
    path: Path = arguments.evidence or arguments.snapshot_dir.parent / EVIDENCE_FILENAME
    if arguments.evidence is None and not path.is_file():
        parser.exit(
            2,
            f"{parser.prog}: error: --node was omitted and no evidence was found at {path}; "
            "pass --evidence <json> or --node <name>\n",
        )
    try:
        return NetworkEvidence.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        parser.exit(2, f"{parser.prog}: error: cannot load evidence: {error}\n")


def _print_parse_summary(summary: dict[str, Any]) -> None:
    status = "OK" if summary["ok"] else "ERRORS"
    print(f"Snapshot {summary['snapshot']} in network {summary['network']}: {status}")
    for file_status in summary["files"]:
        print(f"  {file_status['status']:<24} {file_status['file']}")
    for message in summary["errors"]:
        print(f"  ERROR   {message}")
    for message in summary["warnings"]:
        print(f"  WARNING {message}")


def _print_routes(routes: list[dict[str, str | None]]) -> None:
    print(f"\nComputed routes ({len(routes)}):")
    if not routes:
        print("  (none)")
        return
    headers = ("Node", "Network", "Next_Hop_IP", "Protocol")
    rows = [tuple(route.get(header) or "-" for header in headers) for route in routes]
    widths = [max(len(header), *(len(row[index]) for row in rows)) for index, header in enumerate(headers)]
    print("  " + "  ".join(header.ljust(width) for header, width in zip(headers, widths)))
    print("  " + "  ".join("-" * width for width in widths))
    for row in rows:
        print("  " + "  ".join(cell.ljust(width) for cell, width in zip(row, widths)))


def _print_trace(result: dict[str, Any]) -> None:
    origin = " (auto-detected)" if result.get("start_location_auto_detected") else ""
    print(
        f"\nTraceroute {result['src_ip']} -> {result['dst_ip']} from {result['start_node']}"
        f"{origin}: {result['disposition']}"
    )
    for index, hop in enumerate(result["hops"], start=1):
        actions = " -> ".join(
            step["action"] + (f" ({step['filter']})" if step.get("filter") else "")
            for step in hop["steps"]
        )
        print(f"  [{index}] {hop['node']}: {actions or '-'}")
    if result["dropped_by_acl"]:
        print(f"  Dropped by ACL: {result['dropped_by_acl']}")
    if len(result["traces"]) > 1:
        dispositions = ", ".join(trace["batfish_disposition"] for trace in result["traces"])
        print(f"  {len(result['traces'])} paths: {dispositions}")


def _run_graph(arguments: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    topology = arguments.clab_yaml_path
    if not topology.is_file():
        parser.exit(2, f"{parser.prog}: error: topology file not found: {topology}\n")
    if shutil.which("containerlab") is None:
        print(
            f"{parser.prog}: error: 'containerlab' was not found on PATH; install it on a "
            "Linux host (https://containerlab.dev/install/)",
            file=sys.stderr,
        )
        return 1
    command = ["containerlab", "graph", "-t", str(topology)]
    if not _is_root():
        if shutil.which("sudo") is None:
            print(f"{parser.prog}: error: 'sudo' is required to run containerlab", file=sys.stderr)
            return 1
        command.insert(0, "sudo")
    print(f"Running: {' '.join(command)}  (press Ctrl+C to stop the web graph)")
    try:
        return subprocess.run(command, check=False).returncode
    except KeyboardInterrupt:
        return 130
    except OSError as error:
        print(f"{parser.prog}: error: cannot run containerlab: {error}", file=sys.stderr)
        return 1


def _is_root() -> bool:
    geteuid = getattr(os, "geteuid", None)
    return geteuid is not None and geteuid() == 0


if __name__ == "__main__":
    raise SystemExit(main())
