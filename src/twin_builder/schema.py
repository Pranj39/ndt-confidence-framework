"""Typed, validated data models for the network evidence graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from ipaddress import (
    IPv4Address,
    IPv4Interface,
    IPv4Network,
    ip_address,
    ip_interface,
    ip_network,
)
import re
from typing import Literal


NodeKind = Literal["router", "switch", "host"]
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_INTERFACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]*$")


def _validate_name(value: str, label: str) -> None:
    if not value or not _NAME_PATTERN.fullmatch(value):
        raise ValueError(
            f"{label} must start with an alphanumeric character and contain only "
            "letters, digits, underscores, periods, or hyphens"
        )


def _validate_interface_name(value: str, label: str) -> None:
    if not value or not _INTERFACE_PATTERN.fullmatch(value):
        raise ValueError(f"{label} contains unsupported characters: {value!r}")


def _ipv4_network(value: str, label: str) -> IPv4Network:
    try:
        network = ip_network(value, strict=False)
    except ValueError as error:
        raise ValueError(f"{label} must be a valid IPv4 CIDR prefix: {value!r}") from error
    if not isinstance(network, IPv4Network):
        raise ValueError(f"{label} must be IPv4: {value!r}")
    return network


@dataclass(slots=True)
class Interface:
    """An IPv4 interface and its administrative/VLAN state."""

    name: str
    ip_address: str | None = None
    vlan_id: int | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        _validate_interface_name(self.name, "Interface name")
        if self.ip_address is not None:
            try:
                address = ip_interface(self.ip_address)
            except ValueError as error:
                raise ValueError(
                    f"Interface IP must be a valid IPv4 CIDR address: {self.ip_address!r}"
                ) from error
            if not isinstance(address, IPv4Interface):
                raise ValueError(f"Interface IP must be IPv4: {self.ip_address!r}")
        if self.vlan_id is not None:
            if isinstance(self.vlan_id, bool) or not isinstance(self.vlan_id, int):
                raise TypeError("VLAN ID must be an integer")
            if not 1 <= self.vlan_id <= 4094:
                raise ValueError("VLAN ID must be between 1 and 4094")
        if not isinstance(self.enabled, bool):
            raise TypeError("Interface enabled must be a bool")


@dataclass(slots=True)
class StaticRoute:
    """An IPv4 static route."""

    prefix: str
    next_hop: str
    admin_distance: int = 1

    def __post_init__(self) -> None:
        _ipv4_network(self.prefix, "Route prefix")
        try:
            next_hop = ip_address(self.next_hop)
        except ValueError as error:
            raise ValueError(
                f"Route next hop must be a valid IPv4 address: {self.next_hop!r}"
            ) from error
        if not isinstance(next_hop, IPv4Address):
            raise ValueError(f"Route next hop must be IPv4: {self.next_hop!r}")
        if isinstance(self.admin_distance, bool) or not isinstance(self.admin_distance, int):
            raise TypeError("Administrative distance must be an integer")
        if not 1 <= self.admin_distance <= 255:
            raise ValueError("Administrative distance must be between 1 and 255")


@dataclass(slots=True)
class OSPFNetwork:
    """An IPv4 network advertised into an OSPF area."""

    prefix: str
    area: str | int

    def __post_init__(self) -> None:
        _ipv4_network(self.prefix, "OSPF prefix")
        area = str(self.area)
        if area.isdigit():
            if int(area) > 0xFFFFFFFF:
                raise ValueError("OSPF numeric area must fit in 32 bits")
        else:
            try:
                parsed_area = ip_address(area)
            except ValueError as error:
                raise ValueError(
                    f"OSPF area must be a 32-bit number or IPv4 address: {area!r}"
                ) from error
            if not isinstance(parsed_area, IPv4Address):
                raise ValueError(f"OSPF area must be IPv4: {area!r}")


@dataclass(slots=True)
class OSPFConfig:
    """OSPF router identity, advertised networks, and passive interfaces."""

    router_id: str
    networks: list[OSPFNetwork] = field(default_factory=list)
    passive_interfaces: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        try:
            router_id = ip_address(self.router_id)
        except ValueError as error:
            raise ValueError(
                f"OSPF router ID must be a valid IPv4 address: {self.router_id!r}"
            ) from error
        if not isinstance(router_id, IPv4Address):
            raise ValueError(f"OSPF router ID must be IPv4: {self.router_id!r}")
        for interface_name in self.passive_interfaces:
            _validate_interface_name(interface_name, "Passive interface name")


@dataclass(slots=True)
class Node:
    """A network element and its configuration evidence."""

    name: str
    kind: NodeKind
    interfaces: list[Interface] = field(default_factory=list)
    static_routes: list[StaticRoute] = field(default_factory=list)
    ospf: OSPFConfig | None = None

    def __post_init__(self) -> None:
        _validate_name(self.name, "Node name")
        if self.kind not in ("router", "switch", "host"):
            raise ValueError(f"Unsupported node kind: {self.kind!r}")
        interface_names = [interface.name for interface in self.interfaces]
        if len(interface_names) != len(set(interface_names)):
            raise ValueError(f"Node {self.name!r} contains duplicate interface names")
        if self.ospf is not None and self.kind != "router":
            raise ValueError("OSPF configuration is supported only on router nodes")
        unknown_passive = set(
            self.ospf.passive_interfaces if self.ospf else ()
        ) - set(interface_names)
        if unknown_passive:
            raise ValueError(
                f"Node {self.name!r} has unknown passive interfaces: {sorted(unknown_passive)}"
            )


@dataclass(slots=True, frozen=True)
class Link:
    """A point-to-point connection between two node interfaces."""

    source_node: str
    source_iface: str
    target_node: str
    target_iface: str

    def __post_init__(self) -> None:
        _validate_name(self.source_node, "Source node name")
        _validate_interface_name(self.source_iface, "Source interface name")
        _validate_name(self.target_node, "Target node name")
        _validate_interface_name(self.target_iface, "Target interface name")


@dataclass(slots=True)
class NetworkEvidence:
    """A named network graph with checked links and node lookup helpers."""

    name: str
    nodes: list[Node] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)

    def __post_init__(self) -> None:
        _validate_name(self.name, "Evidence name")
        node_names = [node.name for node in self.nodes]
        if len(node_names) != len(set(node_names)):
            raise ValueError("Network evidence contains duplicate node names")

        node_by_name = {node.name: node for node in self.nodes}
        occupied_interfaces: set[tuple[str, str]] = set()
        for link in self.links:
            for node_name, interface_name in (
                (link.source_node, link.source_iface),
                (link.target_node, link.target_iface),
            ):
                if node_name not in node_by_name:
                    raise ValueError(f"Link refers to unknown node {node_name!r}")
                interface_names = {item.name for item in node_by_name[node_name].interfaces}
                if interface_name not in interface_names:
                    raise ValueError(
                        f"Link refers to unknown interface {node_name}:{interface_name}"
                    )
                endpoint = (node_name, interface_name)
                if endpoint in occupied_interfaces:
                    raise ValueError(
                        f"Interface {node_name}:{interface_name} is used by multiple links"
                    )
                occupied_interfaces.add(endpoint)

    def get_node(self, name: str) -> Node:
        """Return a node by name or raise ``KeyError`` if it is absent."""
        for node in self.nodes:
            if node.name == name:
                return node
        raise KeyError(f"No node named {name!r} in network {self.name!r}")

    def find_node(self, name: str) -> Node | None:
        """Return a node by name, or ``None`` when it is absent."""
        return next((node for node in self.nodes if node.name == name), None)
