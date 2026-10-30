"""Batfish-backed verification of generated Twin Builder snapshots.

``pybatfish`` is an optional dependency (``pip install -e .[verify]``) and is
imported lazily, so the rest of the package works without it. Verification
talks only to a local Batfish service analysing generated configuration files;
it never contacts network devices.
"""

from __future__ import annotations

import ipaddress
import math
from pathlib import Path
import re
from typing import Any, Callable, Iterable

from .schema import NetworkEvidence

SessionFactory = Callable[[str, int], Any]
HeaderFactory = Callable[..., Any]

_ACCEPTED_DISPOSITIONS = frozenset({"ACCEPTED", "DELIVERED_TO_SUBNET", "EXITS_NETWORK"})
_DENIED_DISPOSITIONS = frozenset({"DENIED_IN", "DENIED_OUT"})
_ROUTE_COLUMNS = ("Node", "Network", "Next_Hop_IP", "Protocol")
_UNQUOTED_SPECIFIER_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.:/-]*")
UNKNOWN_SOURCE_MESSAGE = "Source IP does not belong to any known network in evidence."
_TRACE_PROTOCOLS = frozenset({"tcp", "udp", "icmp"})


class VerificationError(RuntimeError):
    """Raised when a Batfish verification step cannot be completed."""


class BatfishUnavailableError(VerificationError):
    """Raised when pybatfish is missing or the Batfish service is unreachable."""


class SnapshotNotLoadedError(VerificationError):
    """Raised when a query runs before ``load_snapshot`` succeeds."""


class TwinVerifier:
    """Load generated snapshots into Batfish and query routes and traces."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 9996,
        *,
        session_factory: SessionFactory | None = None,
        header_factory: HeaderFactory | None = None,
    ) -> None:
        """Configure the Batfish endpoint; no connection is made until first use.

        ``session_factory`` and ``header_factory`` replace pybatfish's ``Session``
        and ``HeaderConstraints`` and exist mainly for offline testing.
        """
        if not host:
            raise ValueError("Batfish host must not be empty")
        if not 0 < port < 65536:
            raise ValueError(f"Batfish port must be between 1 and 65535, got {port}")
        self.host = host
        self.port = port
        self._session_factory = session_factory
        self._header_factory = header_factory
        self._session: Any | None = None
        self._snapshot_loaded = False
        self.evidence: NetworkEvidence | None = None

    @property
    def endpoint(self) -> str:
        """Return the configured Batfish ``host:port`` endpoint."""
        return f"{self.host}:{self.port}"

    def load_snapshot(
        self,
        snapshot_dir: str | Path,
        network_name: str = "campus_network",
        evidence: NetworkEvidence | None = None,
    ) -> dict[str, Any]:
        """Initialise ``snapshot_dir`` in Batfish and summarise parse problems.

        ``evidence`` (the model the snapshot was compiled from) is retained so
        ``test_trace`` can auto-detect its start location.

        Returns a dict with ``network``, ``snapshot``, per-file ``files`` status,
        ``errors``, ``warnings`` and an overall ``ok`` flag.
        """
        if evidence is not None:
            self.evidence = evidence
        snapshot_path = Path(snapshot_dir)
        configs_dir = snapshot_path / "configs"
        if not configs_dir.is_dir() or not any(configs_dir.glob("*.cfg")):
            raise VerificationError(
                f"{snapshot_path} is not a Batfish snapshot: expected .cfg files in "
                f"{configs_dir} (run 'twin-builder compile' first)"
            )
        if not network_name:
            raise ValueError("network_name must not be empty")

        session = self._get_session()
        self._snapshot_loaded = False
        snapshot_name = _snapshot_name(snapshot_path)
        try:
            session.set_network(network_name)
            snapshot = session.init_snapshot(
                str(snapshot_path), name=snapshot_name, overwrite=True
            )
            file_rows = _records(session.q.fileParseStatus().answer().frame())
            issue_rows = _records(session.q.initIssues().answer().frame())
        except Exception as error:
            raise self._query_error("load snapshot", error) from error
        self._snapshot_loaded = True

        files: list[dict[str, Any]] = []
        errors: list[str] = []
        warnings: list[str] = []
        for row in file_rows:
            file_name = _text(row.get("File_Name")) or "<unknown file>"
            status = _text(row.get("Status")) or "UNKNOWN"
            files.append({"file": file_name, "status": status, "nodes": _names(row.get("Nodes"))})
            if status == "FAILED":
                errors.append(f"{file_name}: parsing failed")
            elif status != "PASSED":
                warnings.append(f"{file_name}: {status}")
        for row in issue_rows:
            issue_type = _text(row.get("Type")) or "Issue"
            nodes = ", ".join(_names(row.get("Nodes"))) or "snapshot"
            details = _text(row.get("Details")) or ""
            line_text = _text(row.get("Line_Text"))
            message = f"{issue_type} on {nodes}: {details}".rstrip(": ")
            if line_text:
                message += f" [{line_text}]"
            (errors if "error" in issue_type.lower() else warnings).append(message)

        return {
            "network": network_name,
            "snapshot": _text(snapshot) or snapshot_name,
            "files": files,
            "errors": errors,
            "warnings": warnings,
            "ok": not errors,
        }

    def get_computed_routes(self) -> list[dict[str, str | None]]:
        """Return Batfish's computed RIB as ``Node/Network/Next_Hop_IP/Protocol`` rows."""
        session = self._require_snapshot()
        try:
            rows = _records(session.q.routes().answer().frame())
        except Exception as error:
            raise self._query_error("query routes", error) from error
        routes = [{column: _text(row.get(column)) for column in _ROUTE_COLUMNS} for row in rows]
        return sorted(routes, key=lambda route: tuple(route[column] or "" for column in _ROUTE_COLUMNS))

    def resolve_start_location(
        self, src_ip: str, evidence: NetworkEvidence | None = None
    ) -> str:
        """Return the Batfish start location that owns ``src_ip``.

        1. A host interface configured with exactly ``src_ip`` → that host's name.
        2. A router's own interface address → that router's name.
        3. Otherwise the most specific enabled router interface subnet containing
           ``src_ip`` → ``@enter(Router[Interface])``, so the flow enters through
           that interface and its ingress ACL is evaluated.

        ``evidence`` defaults to the evidence attached by ``load_snapshot``.
        Raises ``ValueError`` when ``src_ip`` is invalid or not in any subnet.
        """
        model = evidence if evidence is not None else self.evidence
        if model is None:
            raise ValueError(
                "No evidence available to resolve the start location; pass evidence or "
                "supply start_node explicitly"
            )
        try:
            address = ipaddress.ip_address(src_ip)
        except ValueError as error:
            raise ValueError(f"Invalid source IP address: {src_ip!r}") from error

        for node in model.nodes:
            if node.kind == "host" and any(
                _interface_address(interface) == address for interface in node.interfaces
            ):
                return node.name

        best: tuple[int, str, str] | None = None
        for node in model.nodes:
            if node.kind != "router":
                continue
            for interface in node.interfaces:
                if not interface.enabled or interface.ip_address is None:
                    continue
                if _interface_address(interface) == address:
                    return node.name
                network = ipaddress.ip_network(interface.ip_address, strict=False)
                if address in network and (best is None or network.prefixlen > best[0]):
                    best = (network.prefixlen, node.name, interface.name)
        if best is None:
            raise ValueError(f"{UNKNOWN_SOURCE_MESSAGE} ({src_ip})")
        return f"@enter({_specifier_name(best[1])}[{_specifier_name(best[2])}])"

    def test_trace(
        self,
        start_node: str | None = None,
        src_ip: str | None = None,
        dst_ip: str | None = None,
        protocol: str | None = None,
        dst_port: int | None = None,
    ) -> dict[str, Any]:
        """Trace a flow and report disposition, hops, and ACL drops.

        When ``start_node`` is ``None`` the start location is auto-detected from
        ``src_ip`` with ``resolve_start_location`` and the loaded evidence.
        ``src_ip``/``dst_ip`` may be addresses or CIDR prefixes. ``protocol``
        (``tcp``/``udp``/``icmp``; ``ip`` or ``None`` means any) and ``dst_port``
        further constrain the traced flow.

        ``disposition`` is ``ACCEPTED`` when every path is delivered, ``DENIED``
        when any path is dropped by a filter, otherwise Batfish's own value
        (for example ``NO_ROUTE``). The raw per-path values are kept in ``traces``.
        """
        if not src_ip:
            raise ValueError("src_ip must not be empty")
        if not dst_ip:
            raise ValueError("dst_ip must not be empty")
        if start_node == "":
            raise ValueError("start_node must not be empty")
        header_constraints: dict[str, Any] = {"srcIps": src_ip, "dstIps": dst_ip}
        if protocol is not None and protocol.lower() != "ip":
            if protocol.lower() not in _TRACE_PROTOCOLS:
                raise ValueError(f"Unsupported trace protocol: {protocol!r}")
            header_constraints["ipProtocols"] = [protocol.upper()]
        if dst_port is not None:
            if not 0 < dst_port < 65536:
                raise ValueError(f"dst_port must be between 1 and 65535, got {dst_port}")
            if protocol is None or protocol.lower() not in ("tcp", "udp"):
                raise ValueError("dst_port requires protocol 'tcp' or 'udp'")
            header_constraints["dstPorts"] = str(dst_port)
        session = self._require_snapshot()
        auto_detected = start_node is None
        location = self.resolve_start_location(src_ip) if start_node is None else start_node
        try:
            headers = self._headers(**header_constraints)
            rows = _records(
                session.q.traceroute(startLocation=location, headers=headers).answer().frame()
            )
        except VerificationError:
            raise
        except Exception as error:
            raise self._query_error("run traceroute", error) from error

        traces = [_trace_summary(trace) for row in rows for trace in (row.get("Traces") or [])]
        if not traces:
            raise VerificationError(
                f"Batfish returned no trace from {location!r}; check that the node exists "
                "in the snapshot"
            )
        dispositions = [trace["batfish_disposition"] for trace in traces]
        if any(value in _DENIED_DISPOSITIONS for value in dispositions):
            disposition = "DENIED"
        elif all(value in _ACCEPTED_DISPOSITIONS for value in dispositions):
            disposition = "ACCEPTED"
        else:
            disposition = next(
                value for value in dispositions if value not in _ACCEPTED_DISPOSITIONS
            )
        primary = next(
            (trace for trace in traces if trace["batfish_disposition"] in _DENIED_DISPOSITIONS),
            traces[0],
        )
        return {
            "start_node": location,
            "start_location_auto_detected": auto_detected,
            "src_ip": src_ip,
            "dst_ip": dst_ip,
            "disposition": disposition,
            "hops": primary["hops"],
            "dropped_by_acl": primary["dropped_by_acl"],
            "traces": traces,
        }

    def detect_loops(self) -> list[dict[str, Any]]:
        """Return forwarding loops found by Batfish's ``detectLoops`` question.

        Each entry has the looping ``flow`` text, the ``nodes`` on the loop, and
        the summarised ``traces``. An empty list means the data plane is loop-free.
        """
        session = self._require_snapshot()
        try:
            rows = _records(session.q.detectLoops().answer().frame())
        except Exception as error:
            raise self._query_error("detect loops", error) from error
        loops: list[dict[str, Any]] = []
        for row in rows:
            traces = [_trace_summary(trace) for trace in (row.get("Traces") or [])]
            nodes = list(
                dict.fromkeys(hop["node"] for trace in traces for hop in trace["hops"])
            )
            loops.append({"flow": _text(row.get("Flow")), "nodes": nodes, "traces": traces})
        return loops

    def _get_session(self) -> Any:
        if self._session is not None:
            return self._session
        factory = self._session_factory or _pybatfish_session_factory()
        try:
            self._session = factory(self.host, self.port)
        except OSError as error:
            raise BatfishUnavailableError(
                f"Cannot reach Batfish at {self.endpoint}. Start a local Batfish service, "
                "e.g. 'docker run -d -p 9996:9996 batfish/allinone', or pass "
                f"--host/--port. ({type(error).__name__})"
            ) from error
        except Exception as error:
            raise BatfishUnavailableError(
                f"Cannot open a Batfish session at {self.endpoint}: {error}"
            ) from error
        return self._session

    def _require_snapshot(self) -> Any:
        if self._session is None or not self._snapshot_loaded:
            raise SnapshotNotLoadedError("No snapshot loaded; call load_snapshot() first")
        return self._session

    def _headers(self, **constraints: str) -> Any:
        factory = self._header_factory
        if factory is None:
            try:
                from pybatfish.datamodel.flow import HeaderConstraints
            except ImportError as error:
                raise BatfishUnavailableError(_INSTALL_HINT) from error
            factory = HeaderConstraints
        return factory(**constraints)

    def _query_error(self, action: str, error: Exception) -> VerificationError:
        if isinstance(error, OSError):
            return BatfishUnavailableError(
                f"Lost connection to Batfish at {self.endpoint} while trying to {action}: {error}"
            )
        return VerificationError(f"Batfish failed to {action}: {error}")


_INSTALL_HINT = (
    "pybatfish is not installed; install the optional verifier dependency with "
    "'pip install -e .[verify]'"
)


def _pybatfish_session_factory() -> SessionFactory:
    try:
        from pybatfish.client.session import Session
    except ImportError as error:
        raise BatfishUnavailableError(_INSTALL_HINT) from error

    def create(host: str, port: int) -> Any:
        return Session(host=host, port=port)

    return create


def _interface_address(interface: Any) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if not interface.enabled or interface.ip_address is None:
        return None
    return ipaddress.ip_interface(interface.ip_address).ip


def _specifier_name(name: str) -> str:
    if _UNQUOTED_SPECIFIER_NAME.fullmatch(name):
        return name
    return '"' + name.replace('"', '\\"') + '"'


def _snapshot_name(snapshot_path: Path) -> str:
    name = snapshot_path.resolve().name or "snapshot"
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in name)


def _records(frame: Any) -> list[dict[str, Any]]:
    if hasattr(frame, "to_dict"):
        return list(frame.to_dict("records"))
    return [dict(row) for row in frame]


def _text(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return str(value)


def _names(value: Any) -> list[str]:
    if value is None or isinstance(value, float):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return [str(getattr(item, "hostname", item)) for item in value]
    return [str(value)]


def _trace_summary(trace: Any) -> dict[str, Any]:
    disposition = str(getattr(trace, "disposition", "UNKNOWN"))
    hops: list[dict[str, Any]] = []
    dropped_by: str | None = None
    for hop in getattr(trace, "hops", None) or []:
        steps: list[dict[str, Any]] = []
        for step in getattr(hop, "steps", None) or []:
            action = str(getattr(step, "action", ""))
            detail = getattr(step, "detail", None)
            filter_name = getattr(detail, "filter", None)
            interface = (
                getattr(detail, "inputInterface", None)
                or getattr(detail, "outputInterface", None)
                or getattr(detail, "interface", None)
            )
            steps.append(
                {
                    "action": action,
                    "type": type(detail).__name__ if detail is not None else None,
                    "filter": str(filter_name) if filter_name else None,
                    "interface": str(interface) if interface else None,
                }
            )
            if action == "DENIED" and filter_name and dropped_by is None:
                dropped_by = str(filter_name)
        hops.append({"node": str(getattr(hop, "node", "?")), "steps": steps})
    return {"batfish_disposition": disposition, "hops": hops, "dropped_by_acl": dropped_by}
