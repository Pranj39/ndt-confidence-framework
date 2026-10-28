"""Render validated network evidence as Batfish and Containerlab inputs."""

from __future__ import annotations

from dataclasses import replace
from ipaddress import IPv4Interface, ip_interface, ip_network
import json
from pathlib import Path
from typing import Iterable

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .schema import Link, NetworkEvidence, Node, StaticRoute


_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


class TwinBuilder:
    """Compile network evidence into reproducible local twin artifacts."""

    def __init__(self) -> None:
        self._templates = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            undefined=StrictUndefined,
            autoescape=False,
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._templates.filters["yaml_quote"] = lambda value: json.dumps(str(value))

    def build_batfish_snapshot(self, evidence: NetworkEvidence, output_dir: str | Path) -> str:
        """Write Cisco-compatible configs and return the snapshot directory path."""
        snapshot_dir = Path(output_dir) / "batfish_snapshot"
        config_dir = snapshot_dir / "configs"
        config_dir.mkdir(parents=True, exist_ok=True)
        template = self._templates.get_template("batfish_cisco.j2")

        for node in evidence.nodes:
            (config_dir / f"{node.name}.cfg").write_text(
                template.render(**self._batfish_node_context(node)),
                encoding="utf-8",
            )
        return str(snapshot_dir)

    def build_containerlab(self, evidence: NetworkEvidence, output_dir: str | Path) -> str:
        """Write FRR configs and a Containerlab topology; return the YAML path."""
        containerlab_dir = Path(output_dir) / "containerlab"
        config_root = containerlab_dir / "clab-configs"
        containerlab_dir.mkdir(parents=True, exist_ok=True)

        interface_names = self._container_interface_names(evidence)
        frr_template = self._templates.get_template("frr_conf.j2")
        daemons_template = self._templates.get_template("frr_daemons.j2")
        for node in evidence.nodes:
            if node.kind != "router":
                continue
            node_config_dir = config_root / node.name
            node_config_dir.mkdir(parents=True, exist_ok=True)
            context = self._frr_node_context(node, interface_names[node.name])
            (node_config_dir / "frr.conf").write_text(
                frr_template.render(**context),
                encoding="utf-8",
            )
            (node_config_dir / "daemons").write_text(
                daemons_template.render(has_ospf=node.ospf is not None),
                encoding="utf-8",
            )

        topology_context = self._containerlab_context(evidence, interface_names)
        topology_path = containerlab_dir / f"{evidence.name}.clab.yml"
        topology_path.write_text(
            self._templates.get_template("containerlab.yml.j2").render(**topology_context),
            encoding="utf-8",
        )
        return str(topology_path)

    def prune_evidence(
        self,
        evidence: NetworkEvidence,
        drop_links: Iterable[Link] | None = None,
        drop_routes: Iterable[StaticRoute] | None = None,
    ) -> NetworkEvidence:
        """Return a copy with selected links and matching static routes removed.

        Link selectors use exact ``Link`` values. Route selectors remove matching
        ``StaticRoute`` values from any node that contains them.
        """
        links_to_drop = set(drop_links or ())
        routes_to_drop = tuple(drop_routes or ())
        return NetworkEvidence(
            name=evidence.name,
            nodes=[
                replace(
                    node,
                    static_routes=[
                        route for route in node.static_routes if route not in routes_to_drop
                    ],
                )
                for node in evidence.nodes
            ],
            links=[link for link in evidence.links if link not in links_to_drop],
        )

    @staticmethod
    def _batfish_node_context(node: Node) -> dict[str, object]:
        interfaces: list[dict[str, object]] = []
        for interface in node.interfaces:
            address = ip_interface(interface.ip_address) if interface.ip_address else None
            interfaces.append(
                {
                    "name": interface.name,
                    "address": str(address.ip) if isinstance(address, IPv4Interface) else None,
                    "netmask": str(address.network.netmask)
                    if isinstance(address, IPv4Interface)
                    else None,
                    "vlan_id": interface.vlan_id,
                    "enabled": interface.enabled,
                }
            )

        static_routes = [
            {
                "network": str(ip_network(route.prefix, strict=False).network_address),
                "netmask": str(ip_network(route.prefix, strict=False).netmask),
                "next_hop": route.next_hop,
                "admin_distance": route.admin_distance,
            }
            for route in node.static_routes
        ]
        ospf = None
        if node.ospf is not None:
            ospf = {
                "router_id": node.ospf.router_id,
                "networks": [
                    {
                        "network": str(ip_network(network.prefix, strict=False).network_address),
                        "wildcard": str(ip_network(network.prefix, strict=False).hostmask),
                        "area": network.area,
                    }
                    for network in node.ospf.networks
                ],
                "passive_interfaces": node.ospf.passive_interfaces,
            }
        return {
            "name": node.name,
            "interfaces": interfaces,
            "static_routes": static_routes,
            "ospf": ospf,
        }

    @staticmethod
    def _container_interface_names(evidence: NetworkEvidence) -> dict[str, dict[str, str]]:
        interface_names = {node.name: {} for node in evidence.nodes}
        next_port = {node.name: 1 for node in evidence.nodes}
        for link in evidence.links:
            for node_name, interface_name in (
                (link.source_node, link.source_iface),
                (link.target_node, link.target_iface),
            ):
                if interface_name not in interface_names[node_name]:
                    interface_names[node_name][interface_name] = f"eth{next_port[node_name]}"
                    next_port[node_name] += 1

        for node in evidence.nodes:
            for interface in node.interfaces:
                if (
                    interface.name.lower().startswith("loopback")
                    and interface.name not in interface_names[node.name]
                ):
                    interface_names[node.name][interface.name] = "lo"
                elif interface.name not in interface_names[node.name]:
                    interface_names[node.name][interface.name] = f"eth{next_port[node.name]}"
                    next_port[node.name] += 1
        return interface_names

    @staticmethod
    def _frr_node_context(node: Node, interface_names: dict[str, str]) -> dict[str, object]:
        interfaces = [
            {
                "name": interface_names[interface.name],
                "ip_address": interface.ip_address,
                "enabled": interface.enabled,
            }
            for interface in node.interfaces
            if interface.name in interface_names
        ]
        static_routes = [
            {
                "prefix": str(ip_network(route.prefix, strict=False)),
                "next_hop": route.next_hop,
                "admin_distance": route.admin_distance,
            }
            for route in node.static_routes
        ]
        ospf = None
        if node.ospf is not None:
            ospf = {
                "router_id": node.ospf.router_id,
                "networks": [
                    {"prefix": str(ip_network(network.prefix, strict=False)), "area": network.area}
                    for network in node.ospf.networks
                ],
                "passive_interfaces": [
                    interface_names[name] for name in node.ospf.passive_interfaces
                ],
            }
        return {
            "hostname": node.name,
            "interfaces": interfaces,
            "static_routes": static_routes,
            "ospf": ospf,
        }

    @staticmethod
    def _containerlab_context(
        evidence: NetworkEvidence,
        interface_names: dict[str, dict[str, str]],
    ) -> dict[str, object]:
        linked_interfaces = {
            (node_name, interface_name)
            for link in evidence.links
            for node_name, interface_name in (
                (link.source_node, link.source_iface),
                (link.target_node, link.target_iface),
            )
        }
        nodes: list[dict[str, object]] = []
        for node in evidence.nodes:
            commands = []
            if node.kind != "switch":
                for interface in node.interfaces:
                    device_name = interface_names[node.name][interface.name]
                    is_unlinked_linux_interface = (
                        device_name.startswith("eth")
                        and (node.name, interface.name) not in linked_interfaces
                    )
                    if is_unlinked_linux_interface:
                        commands.append(f"ip link add {device_name} type dummy")
                    if node.kind == "host" and interface.ip_address:
                        address = ip_interface(interface.ip_address)
                        commands.append(f"ip address add {address} dev {device_name}")
                    if node.kind == "host" and interface.enabled:
                        commands.append(f"ip link set {device_name} up")
                    elif node.kind == "host":
                        commands.append(f"ip link set {device_name} down")

            if node.kind == "host":
                for route in node.static_routes:
                    prefix = ip_network(route.prefix, strict=False)
                    commands.append(
                        f"ip route add {prefix} via {route.next_hop} "
                        f"metric {route.admin_distance}"
                    )

            item: dict[str, object] = {
                "name": node.name,
                "image": "frrouting/frr:v8.5.2" if node.kind == "router" else "alpine:latest",
                "clab_kind": "bridge" if node.kind == "switch" else "linux",
                "is_router": node.kind == "router",
                "has_image": node.kind != "switch",
                "exec_commands": commands,
            }
            nodes.append(item)

        links = [
            {
                "source": (
                    f"{link.source_node}:"
                    f"{interface_names[link.source_node][link.source_iface]}"
                ),
                "target": (
                    f"{link.target_node}:"
                    f"{interface_names[link.target_node][link.target_iface]}"
                ),
            }
            for link in evidence.links
        ]
        return {"name": evidence.name, "nodes": nodes, "links": links}
