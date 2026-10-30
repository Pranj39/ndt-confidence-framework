"""Unit tests for Component 02 twin generation."""

from dataclasses import asdict
import json
from pathlib import Path

import pytest
import yaml

from src.twin_builder import (
    ACL,
    ACLRule,
    Interface,
    Link,
    NetworkEvidence,
    Node,
    OSPFConfig,
    OSPFNetwork,
    StaticRoute,
    TwinBuilder,
)


@pytest.fixture
def two_router_evidence() -> NetworkEvidence:
    """Return a small synthetic topology with OSPF and a static route."""
    return NetworkEvidence(
        name="two-router-lab",
        nodes=[
            Node(
                name="R1",
                kind="router",
                interfaces=[
                    Interface("GigabitEthernet0/0", "10.0.12.1/24"),
                    Interface("Loopback0", "10.1.1.1/32"),
                ],
                static_routes=[StaticRoute("192.168.20.0/24", "10.0.12.2", 5)],
                ospf=OSPFConfig(
                    router_id="1.1.1.1",
                    networks=[OSPFNetwork("10.0.12.0/24", 0)],
                    passive_interfaces=["Loopback0"],
                ),
            ),
            Node(
                name="R2",
                kind="router",
                interfaces=[
                    Interface("GigabitEthernet0/0", "10.0.12.2/24"),
                    Interface("Loopback0", "10.2.2.2/32"),
                ],
                ospf=OSPFConfig(
                    router_id="2.2.2.2",
                    networks=[OSPFNetwork("10.0.12.0/24", "0")],
                ),
            ),
        ],
        links=[Link("R1", "GigabitEthernet0/0", "R2", "GigabitEthernet0/0")],
    )


def test_builds_batfish_snapshot_configs(
    tmp_path: Path, two_router_evidence: NetworkEvidence
) -> None:
    snapshot_path = Path(TwinBuilder().build_batfish_snapshot(two_router_evidence, tmp_path))
    config_dir = snapshot_path / "configs"
    r1_config = (config_dir / "R1.cfg").read_text(encoding="utf-8")
    r2_config = (config_dir / "R2.cfg").read_text(encoding="utf-8")

    assert snapshot_path == tmp_path / "batfish_snapshot"
    assert (config_dir / "R1.cfg").is_file()
    assert (config_dir / "R2.cfg").is_file()
    assert "ip address 10.0.12.1 255.255.255.0" in r1_config
    assert "ip route 192.168.20.0 255.255.255.0 10.0.12.2 5" in r1_config
    assert "network 10.0.12.0 0.0.0.255 area 0" in r1_config
    assert "router-id 2.2.2.2" in r2_config


def test_renders_interface_descriptions(
    tmp_path: Path, two_router_evidence: NetworkEvidence
) -> None:
    interface = two_router_evidence.nodes[0].interfaces[0]
    interface.description = "Uplink to R2"
    builder = TwinBuilder()

    batfish = Path(builder.build_batfish_snapshot(two_router_evidence, tmp_path))
    builder.build_containerlab(two_router_evidence, tmp_path)

    r1_config = (batfish / "configs" / "R1.cfg").read_text(encoding="utf-8")
    assert f"interface {interface.name}\n description Uplink to R2\n" in r1_config
    frr = (tmp_path / "containerlab" / "clab-configs" / "R1" / "frr.conf").read_text(
        encoding="utf-8"
    )
    assert " description Uplink to R2\n" in frr
    r2_config = (batfish / "configs" / "R2.cfg").read_text(encoding="utf-8")
    assert "description" not in r2_config


@pytest.mark.parametrize("description", ["", "   ", "x\nhostname evil", "tab\there", "x" * 201])
def test_rejects_unsafe_interface_descriptions(description: str) -> None:
    with pytest.raises(ValueError, match="description"):
        Interface(name="Gi0/0", description=description)


def test_builds_containerlab_topology_and_router_configs(
    tmp_path: Path, two_router_evidence: NetworkEvidence
) -> None:
    topology_path = Path(TwinBuilder().build_containerlab(two_router_evidence, tmp_path))
    containerlab_dir = tmp_path / "containerlab"
    r1_dir = containerlab_dir / "clab-configs" / "R1"
    r1_config = (r1_dir / "frr.conf").read_text(encoding="utf-8")
    r1_daemons = (r1_dir / "daemons").read_text(encoding="utf-8")
    topology = topology_path.read_text(encoding="utf-8")

    assert topology_path == containerlab_dir / "two-router-lab.clab.yml"
    assert topology_path.is_file()
    assert (containerlab_dir / "clab-configs" / "R2" / "frr.conf").is_file()
    assert (containerlab_dir / "clab-configs" / "R2" / "daemons").is_file()
    assert "ip address 10.0.12.1/24" in r1_config
    assert "ip route 192.168.20.0/24 10.0.12.2 5" in r1_config
    assert "network 10.0.12.0/24 area 0" in r1_config
    assert "interface lo" in r1_config
    assert "passive-interface lo" in r1_config
    assert "ospfd=yes" in r1_daemons
    assert "zebra=yes" in r1_daemons
    assert "frrouting/frr:v8.5.2" in topology
    assert "clab-configs/R1/frr.conf:/etc/frr/frr.conf" in topology
    assert "R1:eth1" in topology
    assert "R2:eth1" in topology
    parsed_topology = yaml.safe_load(topology)
    assert parsed_topology["topology"]["nodes"]["R1"]["image"] == "frrouting/frr:v8.5.2"
    assert parsed_topology["topology"]["links"][0]["endpoints"] == ["R1:eth1", "R2:eth1"]


def test_prune_evidence_returns_independent_pruned_copy(
    two_router_evidence: NetworkEvidence,
) -> None:
    original_link = two_router_evidence.links[0]
    original_route = two_router_evidence.get_node("R1").static_routes[0]

    pruned = TwinBuilder().prune_evidence(
        two_router_evidence,
        drop_links=[original_link],
        drop_routes=[original_route],
    )

    assert pruned is not two_router_evidence
    assert pruned.links == []
    assert pruned.get_node("R1").static_routes == []
    assert two_router_evidence.links == [original_link]
    assert two_router_evidence.get_node("R1").static_routes == [original_route]


def test_rejects_links_to_unknown_interfaces() -> None:
    with pytest.raises(ValueError, match="unknown interface"):
        NetworkEvidence(
            name="invalid-topology",
            nodes=[Node("R1", "router", interfaces=[Interface("eth1")])],
            links=[Link("R1", "eth2", "R1", "eth1")],
        )


def test_builds_bridge_switch_and_alpine_host_nodes(tmp_path: Path) -> None:
    evidence = NetworkEvidence(
        name="mixed-node-lab",
        nodes=[
            Node("SW1", "switch", interfaces=[Interface("Ethernet1")]),
            Node("H1", "host", interfaces=[Interface("eth1", "192.0.2.10/24")]),
        ],
        links=[Link("SW1", "Ethernet1", "H1", "eth1")],
    )

    topology_path = Path(TwinBuilder().build_containerlab(evidence, tmp_path))
    topology = yaml.safe_load(topology_path.read_text(encoding="utf-8"))
    nodes = topology["topology"]["nodes"]

    assert nodes["SW1"]["kind"] == "bridge"
    assert "image" not in nodes["SW1"]
    assert nodes["H1"]["kind"] == "linux"
    assert nodes["H1"]["image"] == "alpine:latest"


def test_builds_batfish_acl_rules(tmp_path: Path) -> None:
    evidence = NetworkEvidence(
        name="acl-lab",
        nodes=[
            Node(
                name="R1",
                kind="router",
                interfaces=[
                    Interface(
                        name="GigabitEthernet0/0",
                        ip_address="10.0.12.1/24",
                        applied_ingress_acl="BLOCK_STUDENT_TO_EXAM",
                        applied_egress_acl="BLOCK_STUDENT_TO_EXAM",
                    )
                ],
                acls=[
                    ACL(
                        name="BLOCK_STUDENT_TO_EXAM",
                        rules=[
                            ACLRule(
                                action="permit",
                                protocol="tcp",
                                source="10.0.1.0/24",
                                destination="10.0.2.0/24",
                                port=443,
                            ),
                            ACLRule(
                                action="deny",
                                source="10.0.1.0/24",
                                destination="10.0.2.0/24",
                            ),
                            ACLRule(
                                action="permit",
                                protocol="icmp",
                                source="any",
                                destination="10.0.2.0/24",
                            ),
                        ],
                    )
                ],
            )
        ],
    )

    snapshot_path = Path(TwinBuilder().build_batfish_snapshot(evidence, tmp_path))
    r1_config = (snapshot_path / "configs" / "R1.cfg").read_text(encoding="utf-8")

    assert "ip access-list extended BLOCK_STUDENT_TO_EXAM" in r1_config
    assert " permit tcp 10.0.1.0 0.0.0.255 10.0.2.0 0.0.0.255 eq 443" in r1_config.splitlines()
    assert " deny ip 10.0.1.0 0.0.0.255 10.0.2.0 0.0.0.255" in r1_config.splitlines()
    assert " permit icmp any 10.0.2.0 0.0.0.255" in r1_config.splitlines()
    assert "ip access-group BLOCK_STUDENT_TO_EXAM in" in r1_config
    assert "ip access-group BLOCK_STUDENT_TO_EXAM out" in r1_config


def test_rejects_interface_applying_undefined_acl() -> None:
    with pytest.raises(ValueError, match="undefined ACLs"):
        Node(
            name="R1",
            kind="router",
            interfaces=[Interface("GigabitEthernet0/0", applied_ingress_acl="MISSING")],
        )


def test_rejects_duplicate_acl_names_on_node() -> None:
    with pytest.raises(ValueError, match="duplicate ACL names"):
        Node(
            name="R1",
            kind="router",
            acls=[ACL("EDGE_FILTER"), ACL("EDGE_FILTER")],
        )


def test_rejects_acl_port_for_non_transport_protocol() -> None:
    with pytest.raises(ValueError, match="only for TCP and UDP"):
        ACLRule(action="permit", protocol="icmp", source="any", destination="any", port=80)


def test_model_validate_json_constructs_nested_models() -> None:
    evidence = NetworkEvidence(
        name="json-lab",
        nodes=[
            Node(
                name="R1",
                kind="router",
                interfaces=[
                    Interface("eth1", "10.0.1.1/24", applied_ingress_acl="FILTER")
                ],
                static_routes=[StaticRoute("10.0.2.0/24", "10.0.1.2")],
                ospf=OSPFConfig(
                    "10.255.0.1",
                    networks=[OSPFNetwork("10.0.1.0/24", "0.0.0.0")],
                    passive_interfaces=["eth1"],
                ),
                acls=[ACL("FILTER", [ACLRule("permit", "any", "any")])],
            ),
            Node("H1", "host", interfaces=[Interface("eth1", "10.0.1.2/24")]),
        ],
        links=[Link("R1", "eth1", "H1", "eth1")],
    )

    parsed = NetworkEvidence.model_validate_json(json.dumps(asdict(evidence)))

    assert parsed == evidence
    assert isinstance(parsed.nodes[0], Node)
    assert isinstance(parsed.nodes[0].interfaces[0], Interface)
    assert isinstance(parsed.nodes[0].acls[0].rules[0], ACLRule)
    assert isinstance(parsed.links[0], Link)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "name is required"),
        ({"name": "lab", "extra": 1}, "unknown fields"),
        ({"name": "lab", "nodes": None}, "must be a JSON array"),
        ({"name": "lab", "nodes": [{}]}, "name is required"),
        ({"name": "lab", "nodes": [{"name": "R1", "kind": "invalid"}]}, "kind must match"),
        (
            {
                "name": "lab",
                "nodes": [
                    {
                        "name": "R1",
                        "kind": "router",
                        "interfaces": [{"name": "eth1", "enabled": 1}],
                    }
                ],
            },
            "enabled must match",
        ),
        (
            {
                "name": "lab",
                "nodes": [
                    {
                        "name": "R1",
                        "kind": "router",
                        "ospf": {
                            "router_id": "10.255.0.1",
                            "networks": [{"prefix": "10.0.1.0/24", "area": True}],
                        },
                    }
                ],
            },
            "area must match",
        ),
        (
            {
                "name": "lab",
                "nodes": [
                    {
                        "name": "H1",
                        "kind": "host",
                        "interfaces": [{"name": "eth1", "ip_address": "invalid"}],
                    }
                ],
            },
            "valid IPv4 CIDR",
        ),
        (
            {
                "name": "lab",
                "links": [
                    {
                        "source_node": "missing",
                        "source_iface": "eth1",
                        "target_node": "also-missing",
                        "target_iface": "eth1",
                    }
                ],
            },
            "unknown node",
        ),
    ],
)
def test_model_validate_json_rejects_invalid_evidence(
    payload: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        NetworkEvidence.model_validate_json(json.dumps(payload))
