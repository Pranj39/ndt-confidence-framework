"""Endpoint-group discovery and compilation of intents into concrete checks."""

from __future__ import annotations

from ipaddress import ip_interface, ip_network
import re
from typing import Optional

from ._twin import NetworkEvidence, TwinVerifier
from .schema import (
    GROUP_PREFIX,
    SERVICE_PORTS,
    EndpointGroup,
    EndpointGroupRegistry,
    Intent,
    IntentType,
    ResolvedCheck,
)

ANY = "any"
_ANY_PREFIX = "0.0.0.0/0"
_LOOP_CHECK_LOCATION = "*"


def slugify(text: str) -> Optional[str]:
    """Return a lowercase ``[a-z0-9_]`` group name for ``text``, or ``None``."""
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or None


def auto_discover_groups(evidence: NetworkEvidence) -> EndpointGroupRegistry:
    """Derive endpoint groups from evidence when no curated registry exists.

    * every addressed host node → ``<host_slug>`` with its ``/32`` addresses;
    * every addressed interface with a description → ``<description_slug>``;
    * every addressed interface with a VLAN id → ``vlan_<id>``;
    * any other addressed router/switch interface → ``net_<cidr_slug>``.

    Description/VLAN/net groups hold the interface's subnet. Groups with the
    same name are merged, keeping the first description.
    """
    groups: dict[str, EndpointGroup] = {}

    def add(name: Optional[str], description: str, *, subnet: str = "", host: str = "") -> None:
        if name is None:
            return
        group = groups.setdefault(name, EndpointGroup(name=name, description=description))
        bucket = group.subnets if subnet else group.hosts
        value = subnet or host
        if value not in bucket:
            bucket.append(value)

    for node in evidence.nodes:
        addressed = [interface for interface in node.interfaces if interface.ip_address]
        if node.kind == "host":
            for interface in addressed:
                address = ip_interface(interface.ip_address)
                add(slugify(node.name), f"Host {node.name}", host=f"{address.ip}/32")
        for interface in addressed:
            subnet = str(ip_interface(interface.ip_address).network)
            labelled = False
            description_name = slugify(interface.description) if interface.description else None
            if description_name is not None:
                add(description_name, str(interface.description), subnet=subnet)
                labelled = True
            if interface.vlan_id is not None:
                add(f"vlan_{interface.vlan_id}", f"VLAN {interface.vlan_id}", subnet=subnet)
                labelled = True
            if not labelled and node.kind != "host":
                add(
                    f"net_{slugify(subnet)}",
                    f"Subnet {subnet} ({node.name} {interface.name})",
                    subnet=subnet,
                )

    # Re-validate so appended prefixes are normalised exactly like loaded registries.
    return EndpointGroupRegistry.model_validate(
        {"groups": [group.model_dump() for group in groups.values()]}
    )


class IntentResolver:
    """Expand intents into the Cartesian product of concrete ``ResolvedCheck`` flows."""

    def __init__(
        self,
        registry: Optional[EndpointGroupRegistry],
        evidence: NetworkEvidence,
        verifier: TwinVerifier,
    ) -> None:
        self.evidence = evidence
        self.verifier = verifier
        self.registry = registry if registry is not None else auto_discover_groups(evidence)
        self._start_locations: dict[str, str] = {}

    def expand_targets(self, target_spec: Optional[str]) -> list[str]:
        """Expand ``group:<name>``, an IPv4 address/CIDR, or ``None``/``any``.

        Raises ``ValueError`` for unknown or empty groups and malformed targets.
        """
        if target_spec is None or target_spec == ANY:
            return [ANY]
        if target_spec.startswith(GROUP_PREFIX):
            name = target_spec[len(GROUP_PREFIX) :]
            prefixes = self.registry.get_all_prefixes(name)
            if not prefixes:
                raise ValueError(f"Endpoint group {name!r} has no subnets or hosts")
            return prefixes
        try:
            ip_network(target_spec, strict=False)
        except ValueError as error:
            raise ValueError(
                f"Target must be 'group:<name>', an IPv4 address/CIDR, or 'any': {target_spec!r}"
            ) from error
        return [target_spec]

    def resolve_service_ports(
        self, service: Optional[str], protocol: Optional[str], port: Optional[int]
    ) -> tuple[str, Optional[int]]:
        """Map a service name (or explicit protocol/port) to ``(protocol, port)``."""
        if service is not None:
            try:
                service_protocol, service_port = SERVICE_PORTS[service.lower()]
            except KeyError as error:
                raise ValueError(
                    f"Unknown service {service!r}; expected one of {sorted(SERVICE_PORTS)}"
                ) from error
            if protocol not in (None, "ip", service_protocol):
                raise ValueError(f"Service {service!r} uses {service_protocol}, not {protocol!r}")
            return service_protocol, port if port is not None else service_port
        resolved_protocol = (protocol or "ip").lower()
        if port is not None and resolved_protocol not in ("tcp", "udp"):
            raise ValueError("A destination port requires protocol 'tcp' or 'udp'")
        return resolved_protocol, port

    def resolve_intent(self, intent: Intent) -> list[ResolvedCheck]:
        """Compile ``intent`` into one check per (source prefix, destination prefix)."""
        if intent.type is IntentType.LOOP_FREE:
            return [
                ResolvedCheck(
                    intent_id=intent.id,
                    src_ip=ANY,
                    dst_ip=ANY,
                    protocol="ip",
                    dst_port=None,
                    expected=intent.expected,
                    start_location=_LOOP_CHECK_LOCATION,
                )
            ]
        sources = self.expand_targets(intent.src)
        destinations = [
            _ANY_PREFIX if value == ANY else value for value in self.expand_targets(intent.dst)
        ]
        if ANY in sources:
            raise ValueError(f"Intent {intent.id}: source must be a group or IPv4 address/prefix")
        protocol, dst_port = self.resolve_service_ports(
            intent.service, intent.protocol, intent.dst_port
        )
        return [
            ResolvedCheck(
                intent_id=intent.id,
                src_ip=source,
                dst_ip=destination,
                protocol=protocol,
                dst_port=dst_port,
                expected=intent.expected,
                start_location=self._start_location(source),
            )
            for source in sources
            for destination in destinations
        ]

    def _start_location(self, source: str) -> str:
        if source not in self._start_locations:
            # A prefix enters the twin where its network address would: a host for /32s,
            # otherwise the router interface that owns the subnet.
            address = str(ip_network(source, strict=False).network_address)
            self._start_locations[source] = self.verifier.resolve_start_location(
                address, self.evidence
            )
        return self._start_locations[source]
