"""Component 03 - Intent Library: declarative intents verified against the twin."""

from .evaluator import IntentEvaluator
from .loader import (
    load_group_registry,
    load_intent_suite,
    save_group_registry,
    save_intent_suite,
)
from .resolver import IntentResolver, auto_discover_groups
from .schema import (
    SERVICE_PORTS,
    CandidateProbe,
    CheckOutcome,
    EndpointGroup,
    EndpointGroupRegistry,
    Intent,
    IntentResult,
    IntentStatus,
    IntentSuite,
    IntentType,
    ResolvedCheck,
    Severity,
    SuiteEvaluationReport,
)
from .wizard import IntentWizard, WizardAborted, run_add_intent_wizard

__all__ = [
    "SERVICE_PORTS",
    "CandidateProbe",
    "CheckOutcome",
    "EndpointGroup",
    "EndpointGroupRegistry",
    "Intent",
    "IntentEvaluator",
    "IntentResolver",
    "IntentResult",
    "IntentStatus",
    "IntentSuite",
    "IntentType",
    "IntentWizard",
    "ResolvedCheck",
    "Severity",
    "SuiteEvaluationReport",
    "WizardAborted",
    "auto_discover_groups",
    "load_group_registry",
    "load_intent_suite",
    "run_add_intent_wizard",
    "save_group_registry",
    "save_intent_suite",
]
