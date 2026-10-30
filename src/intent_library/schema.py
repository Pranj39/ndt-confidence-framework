"""Pydantic models for endpoint groups, intents, resolved checks, and results.

Intents are declarative L2/L3 properties (proposal §8.5, block 03). Targets are
either ``group:<name>`` references into an :class:`EndpointGroupRegistry` or raw
IPv4 addresses/CIDR prefixes; ``any`` is accepted for destinations.
"""

from __future__ import annotations

from enum import Enum
from ipaddress import IPv4Address, IPv4Network, ip_address, ip_network
import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

GROUP_PREFIX = "group:"
SERVICE_PORTS: dict[str, tuple[str, int]] = {
    "web": ("tcp", 443),
    "https": ("tcp", 443),
    "http": ("tcp", 80),
    "ssh": ("tcp", 22),
    "dns": ("udp", 53),
}
PROTOCOLS = ("ip", "tcp", "udp", "icmp")
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class IntentType(str, Enum):
    """Kinds of network property an intent asserts."""

    REACHABILITY = "reachability"
    ISOLATION = "isolation"
    SERVICE_ACCESS = "service_access"
    LOOP_FREE = "loop_free"


class Severity(str, Enum):
    """Operational impact if the intent is violated."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class IntentStatus(str, Enum):
    """Outcome of evaluating one intent against a twin snapshot."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"


EXPECTED_BY_TYPE: dict[IntentType, str] = {
    IntentType.REACHABILITY: "ACCEPTED",
    IntentType.ISOLATION: "DENIED",
    IntentType.SERVICE_ACCESS: "ACCEPTED",
    IntentType.LOOP_FREE: "LOOP_FREE",
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


def _check_name(value: str, label: str) -> str:
    if not _NAME_PATTERN.fullmatch(value):
        raise ValueError(
            f"{label} must start with a letter or digit and contain only letters, digits, "
            f"'_', '.', or '-': {value!r}"
        )
    return value


def _ipv4_network(value: str, label: str, *, strict: bool = True) -> IPv4Network:
    try:
        network = ip_network(value, strict=strict)
    except ValueError as error:
        raise ValueError(
            f"{label} is not a valid IPv4 address or CIDR prefix: {value!r}"
        ) from error
    if not isinstance(network, IPv4Network):
        raise ValueError(f"{label} must be IPv4: {value!r}")
    return network


def _check_port(value: Optional[int], label: str) -> Optional[int]:
    if value is not None and not 1 <= value <= 65535:
        raise ValueError(f"{label} must be between 1 and 65535, got {value}")
    return value


class EndpointGroup(_StrictModel):
    """A named set of subnets and host addresses (e.g. ``students``).

    ``aliases`` are alternative names that resolve to this group, e.g. the
    auto-discovered ``student_lab`` for a curated ``students`` group.
    """

    name: str
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    subnets: list[str] = Field(default_factory=list)
    hosts: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _check_name(value, "Endpoint group name")

    @field_validator("aliases")
    @classmethod
    def _validate_aliases(cls, values: list[str]) -> list[str]:
        return [_check_name(value, "Endpoint group alias") for value in values]

    @field_validator("subnets")
    @classmethod
    def _validate_subnets(cls, values: list[str]) -> list[str]:
        return [str(_ipv4_network(value, "Group subnet")) for value in values]

    @field_validator("hosts")
    @classmethod
    def _validate_hosts(cls, values: list[str]) -> list[str]:
        hosts: list[str] = []
        for value in values:
            network = _ipv4_network(value, "Group host")
            if network.prefixlen != 32:
                raise ValueError(f"Group host must be a single address or /32: {value!r}")
            hosts.append(str(network))
        return hosts

    @property
    def prefixes(self) -> list[str]:
        """Return subnets followed by hosts, without duplicates."""
        return list(dict.fromkeys([*self.subnets, *self.hosts]))


class EndpointGroupRegistry(_StrictModel):
    """A collection of endpoint groups whose names and aliases are all unique."""

    groups: list[EndpointGroup] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_names(self) -> EndpointGroupRegistry:
        names = [group.name for group in self.groups]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"Duplicate endpoint group names: {duplicates}")
        owners: dict[str, str] = {name: name for name in names}
        for group in self.groups:
            for alias in group.aliases:
                if alias in owners:
                    raise ValueError(
                        f"Alias {alias!r} of group {group.name!r} conflicts with "
                        f"{'group' if owners[alias] == alias else 'an alias of'} "
                        f"{owners[alias]!r}"
                    )
                owners[alias] = group.name
        return self

    def get_group(self, name: str) -> Optional[EndpointGroup]:
        """Return the group whose name or alias is ``name``, or ``None``."""
        for group in self.groups:
            if group.name == name:
                return group
        return next((group for group in self.groups if name in group.aliases), None)

    def get_all_prefixes(self, group_name: str) -> list[str]:
        """Return all subnets and hosts of a group (by name or alias).

        Raises ``ValueError`` if no group has that name or alias.
        """
        group = self.get_group(group_name)
        if group is None:
            known = ", ".join(
                group.name + (f" (aliases: {', '.join(group.aliases)})" if group.aliases else "")
                for group in self.groups
            )
            raise ValueError(
                f"Unknown endpoint group {group_name!r} (known groups: {known or 'none'})"
            )
        return group.prefixes


class CandidateProbe(_StrictModel):
    """Operational probe template handed to the Probe Selector (Component 06)."""

    probe_type: Literal["icmp", "tcp_syn", "traceroute"]
    source_node: str
    destination_ip: str
    destination_port: Optional[int] = None

    @field_validator("source_node")
    @classmethod
    def _validate_source(cls, value: str) -> str:
        return _check_name(value, "Probe source node")

    @field_validator("destination_ip")
    @classmethod
    def _validate_destination(cls, value: str) -> str:
        try:
            address = ip_address(value)
        except ValueError as error:
            raise ValueError(f"Probe destination must be an IPv4 address: {value!r}") from error
        if not isinstance(address, IPv4Address):
            raise ValueError(f"Probe destination must be IPv4: {value!r}")
        return value

    @field_validator("destination_port")
    @classmethod
    def _validate_port(cls, value: Optional[int]) -> Optional[int]:
        return _check_port(value, "Probe destination port")

    @model_validator(mode="after")
    def _port_matches_type(self) -> CandidateProbe:
        if self.probe_type == "tcp_syn" and self.destination_port is None:
            raise ValueError("tcp_syn probes require destination_port")
        if self.probe_type == "icmp" and self.destination_port is not None:
            raise ValueError("icmp probes do not take destination_port")
        return self


class Intent(_StrictModel):
    """A declarative network property such as "students cannot reach exam_db"."""

    id: str
    name: str
    type: IntentType
    description: str
    severity: Severity = Severity.HIGH
    src: Optional[str] = None
    dst: Optional[str] = None
    service: Optional[str] = None
    protocol: Optional[str] = "ip"
    dst_port: Optional[int] = None
    expected: Literal["ACCEPTED", "DENIED", "LOOP_FREE"]
    tags: list[str] = Field(default_factory=list)
    candidate_probe: Optional[CandidateProbe] = None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return _check_name(value, "Intent id")

    @field_validator("name", "description")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("src", "dst")
    @classmethod
    def _validate_target(cls, value: Optional[str]) -> Optional[str]:
        if value is None or value == "any":
            return value
        if value.startswith(GROUP_PREFIX):
            _check_name(value[len(GROUP_PREFIX) :], "Group reference")
            return value
        _ipv4_network(value, "Intent target")
        return value

    @field_validator("service")
    @classmethod
    def _validate_service(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.lower()
        if normalized not in SERVICE_PORTS:
            raise ValueError(f"Unknown service {value!r}; expected one of {sorted(SERVICE_PORTS)}")
        return normalized

    @field_validator("protocol")
    @classmethod
    def _validate_protocol(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.lower()
        if normalized not in PROTOCOLS:
            raise ValueError(f"Unsupported protocol {value!r}; expected one of {PROTOCOLS}")
        return normalized

    @field_validator("dst_port")
    @classmethod
    def _validate_port(cls, value: Optional[int]) -> Optional[int]:
        return _check_port(value, "Destination port")

    @model_validator(mode="after")
    def _consistent(self) -> Intent:
        expected = EXPECTED_BY_TYPE[self.type]
        if self.expected != expected:
            raise ValueError(
                f"{self.type.value} intents must expect {expected!r}, got {self.expected!r}"
            )
        if self.type is IntentType.LOOP_FREE:
            flow_fields = (self.src, self.dst, self.service, self.dst_port)
            if any(value is not None for value in flow_fields):
                raise ValueError("loop_free intents do not take src, dst, service, or dst_port")
            return self
        if self.src is None or self.dst is None:
            raise ValueError(f"{self.type.value} intents require both src and dst")
        if self.src == "any":
            raise ValueError("src must be a group or IPv4 address/prefix, not 'any'")
        needs_service = self.type is IntentType.SERVICE_ACCESS
        if needs_service and self.service is None and self.dst_port is None:
            raise ValueError("service_access intents require service or dst_port")
        if self.service is not None:
            service_protocol = SERVICE_PORTS[self.service][0]
            if self.protocol not in (None, "ip", service_protocol):
                raise ValueError(
                    f"Service {self.service!r} uses {service_protocol}, not {self.protocol!r}"
                )
        elif self.dst_port is not None and self.protocol not in ("tcp", "udp"):
            raise ValueError("dst_port requires protocol 'tcp' or 'udp'")
        return self


class IntentSuite(_StrictModel):
    """A versioned collection of intents with unique ids."""

    name: str
    version: str = "1.0.0"
    description: Optional[str] = None
    intents: list[Intent]

    @model_validator(mode="after")
    def _unique_ids(self) -> IntentSuite:
        ids = [intent.id for intent in self.intents]
        duplicates = sorted({value for value in ids if ids.count(value) > 1})
        if duplicates:
            raise ValueError(f"Duplicate intent ids: {duplicates}")
        return self

    def get_by_id(self, intent_id: str) -> Optional[Intent]:
        """Return the intent with ``intent_id``, or ``None``."""
        return next((intent for intent in self.intents if intent.id == intent_id), None)

    def filter_by_type(self, intent_type: IntentType | str) -> list[Intent]:
        """Return intents of the given type."""
        wanted = IntentType(intent_type)
        return [intent for intent in self.intents if intent.type is wanted]


class ResolvedCheck(_StrictModel):
    """One concrete flow (or loop query) compiled from an intent."""

    intent_id: str
    src_ip: str
    dst_ip: str
    protocol: str
    dst_port: Optional[int]
    expected: str
    start_location: str


class CheckOutcome(_StrictModel):
    """Batfish result for one :class:`ResolvedCheck`."""

    check: ResolvedCheck
    disposition: str
    passed: bool
    hops: list[str] = Field(default_factory=list)
    dropping_filter: Optional[str] = None
    error: Optional[str] = None


class IntentResult(_StrictModel):
    """Verdict for one intent, with the evidence behind it."""

    intent_id: str
    name: str
    status: IntentStatus
    disposition: str
    details: str
    type: Optional[IntentType] = None
    severity: Optional[Severity] = None
    dependency_cone: list[str] = Field(default_factory=list)
    trace_hops: list[str] = Field(default_factory=list)
    dropping_filter: Optional[str] = None
    checks: list[CheckOutcome] = Field(default_factory=list)


class SuiteEvaluationReport(_StrictModel):
    """Results for a whole suite plus verification coverage ``V_q``."""

    suite_name: str
    timestamp: str
    total_intents: int
    passed_count: int
    failed_count: int
    error_count: int = 0
    verification_coverage: float
    results: list[IntentResult]
