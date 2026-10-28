"""Typed, validated data models for the network evidence graph."""

from __future__ import annotations

from dataclasses import MISSING, dataclass, field, fields, is_dataclass
from ipaddress import (
    IPv4Address,
    IPv4Interface,
    IPv4Network,
    ip_address,
    ip_interface,
    ip_network,
)
import json
import re
from types import UnionType
from typing import Literal, TypeVar, get_args, get_origin, get_type_hints


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
    applied_ingress_acl: str | None = None
    applied_egress_acl: str | None = None

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
        for acl_name in (self.applied_ingress_acl, self.applied_egress_acl):
            if acl_name is not None:
                _validate_name(acl_name, "Applied ACL name")


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
class ACLRule:
    """A basic IPv4 extended access-control-list rule."""

    action: Literal["permit", "deny"]
    source: str
    destination: str
    protocol: Literal["ip", "tcp", "udp", "icmp"] = "ip"
    port: int | None = None

    def __post_init__(self) -> None:
        if self.action not in get_args(Literal["permit", "deny"]):
            raise ValueError(f"Unsupported ACL action: {self.action!r}")
        if self.protocol not in get_args(Literal["ip", "tcp", "udp", "icmp"]):
            raise ValueError(f"Unsupported ACL protocol: {self.protocol!r}")
        for label, address in (("Source", self.source), ("Destination", self.destination)):
            if address != "any":
                _ipv4_network(address, f"ACL {label.lower()}")
        if self.port is not None:
            if self.protocol not in ("tcp", "udp"):
                raise ValueError("ACL port matching is supported only for TCP and UDP")
            if isinstance(self.port, bool) or not isinstance(self.port, int):
                raise TypeError("ACL port must be an integer")
            if not 1 <= self.port <= 65535:
                raise ValueError("ACL port must be between 1 and 65535")


@dataclass(slots=True)
class ACL:
    """A named ordered list of ACL rules."""

    name: str
    rules: list[ACLRule] = field(default_factory=list)

    def __post_init__(self) -> None:
        _validate_name(self.name, "ACL name")


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
    acls: list[ACL] = field(default_factory=list)

    def __post_init__(self) -> None:
        _validate_name(self.name, "Node name")
        if self.kind not in ("router", "switch", "host"):
            raise ValueError(f"Unsupported node kind: {self.kind!r}")
        interface_names = [interface.name for interface in self.interfaces]
        if len(interface_names) != len(set(interface_names)):
            raise ValueError(f"Node {self.name!r} contains duplicate interface names")
        if self.ospf is not None and self.kind != "router":
            raise ValueError("OSPF configuration is supported only on router nodes")
        acl_names = [acl.name for acl in self.acls]
        if len(acl_names) != len(set(acl_names)):
            raise ValueError(f"Node {self.name!r} contains duplicate ACL names")
        unknown_acls = {
            acl_name
            for interface in self.interfaces
            for acl_name in (
                interface.applied_ingress_acl,
                interface.applied_egress_acl,
            )
            if acl_name is not None and acl_name not in acl_names
        }
        if unknown_acls:
            raise ValueError(f"Node {self.name!r} applies undefined ACLs: {sorted(unknown_acls)}")
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

    @classmethod
    def model_validate_json(cls, json_data: str | bytes | bytearray) -> NetworkEvidence:
        """Parse JSON into nested dataclasses, rejecting invalid or unknown fields.

        This provides the JSON-loading API without requiring Pydantic. Existing
        dataclass constructors perform IPv4, ACL, OSPF, and graph validation.
        """
        return _model_from_json(cls, json.loads(json_data), cls.__name__)

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


_Model = TypeVar("_Model")


def _model_from_json(model_type: type[_Model], value: object, path: str) -> _Model:
    """Construct a dataclass only after validating its JSON field types."""
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be a JSON object")
    if not is_dataclass(model_type):
        raise TypeError(f"Unsupported JSON model: {model_type}")
    model_fields = {item.name: item for item in fields(model_type)}
    unknown_fields = value.keys() - model_fields.keys()
    if unknown_fields:
        raise ValueError(f"{path} has unknown fields: {sorted(unknown_fields)}")
    annotations = get_type_hints(model_type)
    arguments: dict[str, object] = {}
    for name, item in model_fields.items():
        field_path = f"{path}.{name}"
        if name in value:
            arguments[name] = _json_field_value(value[name], annotations[name], field_path)
        elif item.default is MISSING and item.default_factory is MISSING:
            raise ValueError(f"{field_path} is required")
    try:
        return model_type(**arguments)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{path}: {error}") from error


def _json_field_value(value: object, annotation: object, path: str) -> object:
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin is UnionType:
        if value is None and type(None) in arguments:
            return None
        candidates = [item for item in arguments if item is not type(None)]
        if len(candidates) == 1:
            return _json_field_value(value, candidates[0], path)
        if type(value) in candidates:
            return value
    elif origin is list:
        if not isinstance(value, list):
            raise ValueError(f"{path} must be a JSON array")
        return [
            _json_field_value(item, arguments[0], f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    elif origin is Literal:
        if any(type(value) is type(item) and value == item for item in arguments):
            return value
    elif isinstance(annotation, type) and is_dataclass(annotation):
        return _model_from_json(annotation, value, path)
    elif annotation in (str, int, bool) and type(value) is annotation:
        return value
    raise ValueError(f"{path} must match {annotation}")
