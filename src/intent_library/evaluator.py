"""Evaluate intents against a Batfish-loaded twin snapshot."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from ._twin import NetworkEvidence, TwinVerifier, VerificationError
from .resolver import IntentResolver
from .schema import (
    CheckOutcome,
    EndpointGroupRegistry,
    Intent,
    IntentResult,
    IntentStatus,
    IntentSuite,
    IntentType,
    ResolvedCheck,
    SuiteEvaluationReport,
)


class IntentEvaluator:
    """Compile intents with :class:`IntentResolver` and check them with Batfish.

    ``verifier`` must already have the snapshot loaded (``load_snapshot``).
    """

    def __init__(
        self,
        verifier: TwinVerifier,
        evidence: NetworkEvidence,
        registry: Optional[EndpointGroupRegistry] = None,
    ) -> None:
        self.verifier = verifier
        self.evidence = evidence
        self.resolver = IntentResolver(registry, evidence, verifier)

    @property
    def registry(self) -> EndpointGroupRegistry:
        """Return the registry in use (curated or auto-discovered)."""
        return self.resolver.registry

    def evaluate_intent(self, intent: Intent) -> IntentResult:
        """Return PASSED/FAILED/ERROR for ``intent`` with path evidence."""
        base: dict[str, Any] = {
            "intent_id": intent.id,
            "name": intent.name,
            "type": intent.type,
            "severity": intent.severity,
        }
        try:
            checks = self.resolver.resolve_intent(intent)
        except ValueError as error:
            return IntentResult(
                **base, status=IntentStatus.ERROR, disposition="ERROR", details=str(error)
            )
        if intent.type is IntentType.LOOP_FREE:
            return self._evaluate_loop_free(base, checks[0])
        return self._evaluate_flows(base, intent, checks)

    def evaluate_suite(self, suite: IntentSuite) -> SuiteEvaluationReport:
        """Evaluate every intent and compute verification coverage ``V_q``."""
        results = [self.evaluate_intent(intent) for intent in suite.intents]
        passed = sum(result.status is IntentStatus.PASSED for result in results)
        failed = sum(result.status is IntentStatus.FAILED for result in results)
        errors = sum(result.status is IntentStatus.ERROR for result in results)
        total = len(results)
        return SuiteEvaluationReport(
            suite_name=suite.name,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            total_intents=total,
            passed_count=passed,
            failed_count=failed,
            error_count=errors,
            verification_coverage=round(passed / total, 4) if total else 0.0,
            results=results,
        )

    def _evaluate_flows(
        self, base: dict[str, Any], intent: Intent, checks: list[ResolvedCheck]
    ) -> IntentResult:
        outcomes: list[CheckOutcome] = []
        cone: list[str] = []
        filters: list[str] = []
        for check in checks:
            try:
                trace = self.verifier.test_trace(
                    check.start_location,
                    check.src_ip,
                    check.dst_ip,
                    protocol=check.protocol,
                    dst_port=check.dst_port,
                )
            except (VerificationError, ValueError) as error:
                outcomes.append(
                    CheckOutcome(check=check, disposition="ERROR", passed=False, error=str(error))
                )
                continue
            check_filters = _unique(
                trace_summary["dropped_by_acl"]
                for trace_summary in trace["traces"]
                if trace_summary["dropped_by_acl"]
            )
            _extend_unique(cone, _dependency_cone(trace["traces"]))
            _extend_unique(filters, check_filters)
            outcomes.append(
                CheckOutcome(
                    check=check,
                    disposition=trace["disposition"],
                    passed=trace["disposition"] == check.expected,
                    hops=[hop["node"] for hop in trace["hops"]],
                    dropping_filter=", ".join(check_filters) or None,
                )
            )

        failed = [item for item in outcomes if item.error is None and not item.passed]
        errored = [item for item in outcomes if item.error is not None]
        if failed:
            status = IntentStatus.FAILED
            mismatches = "; ".join(
                f"{_flow_label(item.check)} => {item.disposition}"
                + _isolation_hint(intent, item.disposition)
                for item in failed
            )
            details = (
                f"{len(failed)} of {len(outcomes)} check(s) did not return "
                f"{intent.expected}: {mismatches}"
            )
        elif errored:
            status = IntentStatus.ERROR
            problems = "; ".join(f"{_flow_label(item.check)}: {item.error}" for item in errored)
            details = (
                f"{len(errored)} of {len(outcomes)} check(s) could not be evaluated: {problems}"
            )
        else:
            status = IntentStatus.PASSED
            details = f"All {len(outcomes)} check(s) returned {intent.expected} as expected"
        return IntentResult(
            **base,
            status=status,
            disposition=", ".join(_unique(item.disposition for item in outcomes)),
            details=details,
            dependency_cone=cone,
            trace_hops=[
                f"{_flow_label(item.check)}: {' -> '.join(item.hops) or '-'} [{item.disposition}]"
                for item in outcomes
            ],
            dropping_filter=", ".join(filters) or None,
            checks=outcomes,
        )

    def _evaluate_loop_free(self, base: dict[str, Any], check: ResolvedCheck) -> IntentResult:
        try:
            loops = self.verifier.detect_loops()
        except VerificationError as error:
            outcome = CheckOutcome(
                check=check, disposition="ERROR", passed=False, error=str(error)
            )
            return IntentResult(
                **base,
                status=IntentStatus.ERROR,
                disposition="ERROR",
                details=str(error),
                checks=[outcome],
            )
        if not loops:
            routers = [node.name for node in self.evidence.nodes if node.kind == "router"]
            outcome = CheckOutcome(check=check, disposition="LOOP_FREE", passed=True)
            return IntentResult(
                **base,
                status=IntentStatus.PASSED,
                disposition="LOOP_FREE",
                details="Batfish detectLoops found no forwarding loops",
                dependency_cone=routers,
                checks=[outcome],
            )
        cone: list[str] = []
        for loop in loops:
            _extend_unique(cone, _dependency_cone(loop["traces"]))
        trace_hops = [
            f"{loop['flow'] or 'flow'}: {' -> '.join(loop['nodes']) or '-'} [LOOP]"
            for loop in loops
        ]
        outcome = CheckOutcome(
            check=check, disposition="LOOP", passed=False, hops=loops[0]["nodes"]
        )
        return IntentResult(
            **base,
            status=IntentStatus.FAILED,
            disposition="LOOP",
            details=f"Batfish detectLoops found {len(loops)} looping flow(s)",
            dependency_cone=cone,
            trace_hops=trace_hops,
            checks=[outcome],
        )


def _dependency_cone(traces: list[dict[str, Any]]) -> list[str]:
    """Nodes and ``node[interface]`` pairs touched by any trace path."""
    cone: list[str] = []
    for trace in traces:
        for hop in trace["hops"]:
            _extend_unique(cone, [hop["node"]])
            _extend_unique(
                cone,
                [
                    f"{hop['node']}[{step['interface']}]"
                    for step in hop["steps"]
                    if step.get("interface")
                ],
            )
    return cone


def _isolation_hint(intent: Intent, disposition: str) -> str:
    # Isolation is deliberately strict: only an ACL/filter drop (DENIED) proves intentional
    # isolation. A blackhole such as NO_ROUTE fails, because the next routing change could
    # silently restore reachability.
    if intent.type is IntentType.ISOLATION and disposition != "ACCEPTED":
        return " (blocked, but not by an ACL/filter)"
    return ""


def _flow_label(check: ResolvedCheck) -> str:
    service = check.protocol if check.dst_port is None else f"{check.protocol}/{check.dst_port}"
    return f"{check.src_ip} -> {check.dst_ip} ({service})"


def _unique(values: Any) -> list[str]:
    return list(dict.fromkeys(values))


def _extend_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)
