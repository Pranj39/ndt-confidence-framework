"""Interactive prompt flow for authoring a new intent (``twin-builder add-intent``)."""

from __future__ import annotations

from ipaddress import ip_network
import re
from typing import Callable, Optional, TypeVar

from pydantic import ValidationError

from .schema import (
    EXPECTED_BY_TYPE,
    GROUP_PREFIX,
    SERVICE_PORTS,
    EndpointGroupRegistry,
    Intent,
    IntentSuite,
    IntentType,
    Severity,
)

InputFunction = Callable[[str], str]
OutputFunction = Callable[[str], None]
_T = TypeVar("_T")

_TYPE_CHOICES = (
    ("Isolation", IntentType.ISOLATION),
    ("Reachability", IntentType.REACHABILITY),
    ("Service Access", IntentType.SERVICE_ACCESS),
    ("Loop Free", IntentType.LOOP_FREE),
)
_SEVERITY_CHOICES = (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW)
_PORT_PATTERN = re.compile(r"^(?:(tcp|udp)/)?(\d{1,5})$")
_ID_PATTERN = re.compile(r"^([A-Za-z]+-)(\d+)$")


class WizardAborted(Exception):
    """Raised when the user ends input (EOF) before the intent is complete."""


class IntentWizard:
    """Ask for intent fields one at a time, re-prompting on invalid answers."""

    def __init__(
        self,
        suite: IntentSuite,
        registry: EndpointGroupRegistry,
        input_func: Optional[InputFunction] = None,
        output_func: Optional[OutputFunction] = None,
    ) -> None:
        self.suite = suite
        self.registry = registry
        # Resolve the builtins at call time so redirected/patched input() is honoured.
        self._input = input_func if input_func is not None else input
        self._output = output_func if output_func is not None else print

    def run(self) -> Intent:
        """Collect answers and return a validated (not yet saved) :class:`Intent`."""
        self._show_groups()
        intent_id = self._ask("Intent ID", self._parse_id, default=self._next_id())
        name = self._ask("Intent name", _parse_text)
        intent_type = self._ask_choice(
            "Intent type",
            [label for label, _ in _TYPE_CHOICES],
            [kind for _, kind in _TYPE_CHOICES],
        )
        src: Optional[str] = None
        dst: Optional[str] = None
        service: Optional[str] = None
        protocol: Optional[str] = None
        dst_port: Optional[int] = None
        if intent_type is not IntentType.LOOP_FREE:
            src = self._ask("Source group index (or IPv4 address/CIDR)", self._parse_target)
            dst = self._ask("Destination group index (or IPv4 address/CIDR)", self._parse_target)
            required = intent_type is IntentType.SERVICE_ACCESS
            hint = f"{'/'.join(SERVICE_PORTS)}, a port like 443 or udp/53"
            if required:
                service, protocol, dst_port = self._ask(
                    f"Service ({hint})", _parse_required_service
                )
            else:
                service, protocol, dst_port = self._ask(
                    f"Service or port ({hint}; blank = any IP)", _parse_service, default=""
                )
        severity = self._ask_choice(
            "Severity",
            [item.value for item in _SEVERITY_CHOICES],
            list(_SEVERITY_CHOICES),
            default=2,
        )
        description = self._ask(
            "Description",
            _parse_text,
            default=_default_description(intent_type, src, dst, service, protocol, dst_port),
        )
        if service is not None:
            protocol = SERVICE_PORTS[service][0]
        try:
            return Intent(
                id=intent_id,
                name=name,
                type=intent_type,
                description=description,
                severity=severity,
                src=src,
                dst=dst,
                service=service,
                protocol=protocol if protocol is not None else "ip",
                dst_port=dst_port,
                expected=EXPECTED_BY_TYPE[intent_type],
            )
        except ValidationError as error:
            raise ValueError(f"The answers do not form a valid intent:\n{error}") from error

    def _show_groups(self) -> None:
        self._output("Endpoint groups:")
        if not self.registry.groups:
            self._output("  (none - enter IPv4 addresses/CIDRs instead)")
        for index, group in enumerate(self.registry.groups, start=1):
            prefixes = ", ".join(group.prefixes) or "no prefixes"
            label = f" - {group.description}" if group.description else ""
            aliases = f" [aliases: {', '.join(group.aliases)}]" if group.aliases else ""
            self._output(f"  [{index}] {group.name}{aliases}{label} ({prefixes})")

    def _ask(self, prompt: str, parse: Callable[[str], _T], default: object = None) -> _T:
        suffix = f" [{default}]" if default not in (None, "") else ""
        while True:
            try:
                answer = self._input(f"{prompt}{suffix}: ").strip()
            except EOFError as error:
                raise WizardAborted("Input ended before the intent was complete") from error
            if not answer and default is not None:
                answer = str(default)
            try:
                return parse(answer)
            except ValueError as error:
                self._output(f"  Invalid answer: {error}")

    def _ask_choice(
        self, prompt: str, labels: list[str], values: list[_T], default: Optional[int] = None
    ) -> _T:
        options = ", ".join(f"{index}: {label}" for index, label in enumerate(labels, start=1))

        def parse(answer: str) -> _T:
            if not answer.isdigit() or not 1 <= int(answer) <= len(values):
                raise ValueError(f"enter a number from 1 to {len(values)}")
            return values[int(answer) - 1]

        return self._ask(f"{prompt} ({options})", parse, default=default)

    def _parse_id(self, answer: str) -> str:
        if not answer:
            raise ValueError("an intent ID is required")
        if self.suite.get_by_id(answer) is not None:
            raise ValueError(f"{answer!r} already exists in suite {self.suite.name!r}")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", answer):
            raise ValueError("use letters, digits, '_', '.', or '-' (e.g. INT-005)")
        return answer

    def _parse_target(self, answer: str) -> str:
        if answer.isdigit():
            index = int(answer)
            if not 1 <= index <= len(self.registry.groups):
                raise ValueError(f"group index must be 1-{len(self.registry.groups)}")
            return f"{GROUP_PREFIX}{self.registry.groups[index - 1].name}"
        if answer.startswith(GROUP_PREFIX):
            if self.registry.get_group(answer[len(GROUP_PREFIX) :]) is None:
                raise ValueError(f"unknown group {answer!r}")
            return answer
        try:
            ip_network(answer, strict=False)
        except ValueError as error:
            raise ValueError("enter a group index or an IPv4 address/CIDR") from error
        return answer

    def _next_id(self) -> str:
        numbers = [
            (match.group(1), int(match.group(2)), len(match.group(2)))
            for match in (_ID_PATTERN.fullmatch(intent.id) for intent in self.suite.intents)
            if match
        ]
        if not numbers:
            return "INT-001"
        prefix, number, width = max(numbers, key=lambda item: item[1])
        candidate = number + 1
        while self.suite.get_by_id(f"{prefix}{candidate:0{width}d}") is not None:
            candidate += 1
        return f"{prefix}{candidate:0{width}d}"


def run_add_intent_wizard(
    suite: IntentSuite,
    registry: EndpointGroupRegistry,
    input_func: Optional[InputFunction] = None,
    output_func: Optional[OutputFunction] = None,
) -> Intent:
    """Run :class:`IntentWizard` and return the new intent."""
    return IntentWizard(suite, registry, input_func, output_func).run()


def _parse_text(answer: str) -> str:
    if not answer:
        raise ValueError("a value is required")
    return answer


def _parse_required_service(answer: str) -> tuple[Optional[str], Optional[str], Optional[int]]:
    if not answer:
        raise ValueError("service access intents need a service name or port")
    return _parse_service(answer)


def _parse_service(answer: str) -> tuple[Optional[str], Optional[str], Optional[int]]:
    """Return ``(service, protocol, port)`` from ``web`` / ``443`` / ``udp/53`` / blank."""
    if not answer:
        return None, None, None
    lowered = answer.lower()
    if lowered in SERVICE_PORTS:
        return lowered, None, None
    match = _PORT_PATTERN.fullmatch(lowered)
    if match is None:
        raise ValueError(f"enter one of {', '.join(SERVICE_PORTS)}, a port, or tcp|udp/<port>")
    port = int(match.group(2))
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    return None, match.group(1) or "tcp", port


def _default_description(
    intent_type: IntentType,
    src: Optional[str],
    dst: Optional[str],
    service: Optional[str],
    protocol: Optional[str],
    dst_port: Optional[int],
) -> str:
    if intent_type is IntentType.LOOP_FREE:
        return "The data plane has no forwarding loops"
    traffic = service or (f"{protocol}/{dst_port}" if dst_port is not None else "IP")
    verb = "must not reach" if intent_type is IntentType.ISOLATION else "must reach"
    return f"{src} {verb} {dst} ({traffic} traffic)"
