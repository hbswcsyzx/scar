"""Real call occurrences attached to original F4 callsite declarations."""
from dataclasses import dataclass
from .ids import ProviderID
from .providers import ProviderFactReference
from .normal_links import CodeScopeWitness
from .normal_targets import GlobalPort
from .call_edges import CodeCapture, CallRecordAnchor
from .call_operands import OperandCallAttempt
from .python_call_targets import PythonCallTarget
from .source_observed_codes import ObservedSourceCodeLink
from .normal_targets import FunctionConnection


@dataclass(frozen=True, slots=True)
class ObservedSourceCallsite:
    id: ProviderID
    unit: str
    query: int
    call: ProviderFactReference
    callee: GlobalPort
    result: GlobalPort
    owner: CodeScopeWitness
    caller: CodeCapture
    attempt: OperandCallAttempt
    target: PythonCallTarget
    target_anchor: CallRecordAnchor
    rule: str
    code_link: ProviderID | None
    # Alternative original exec selections; a shared code does not choose one.
    profile_alternatives: tuple[ProviderFactReference, ...] = ()


@dataclass(frozen=True, slots=True)
class ObservedSourceCallsiteFrontier:
    unit: str
    attempt: OperandCallAttempt
    reason: str
    candidates: tuple[ProviderFactReference, ...] = ()


@dataclass(frozen=True, slots=True)
class ObservedSourceFunctionGroup:
    query: int
    code: ObservedSourceCodeLink
    observations: tuple[ObservedSourceCallsite, ...]
    connection: FunctionConnection
    parent_interfaces: tuple[int, ...]
    # Possible additional receiver prefixes beyond the source actuals, not
    # observed values. Creation-time defaults never refute a layout.
    argument_prefixes: tuple[int, ...]
    argument_layout_proven: bool
    # Actual frame records prove body entry independently of the receiver's
    # weak identity or its explicit/implicit argument layout.
    body_entries: tuple[CallRecordAnchor, ...] = ()


@dataclass(frozen=True, slots=True)
class ObservedSourceFunctionFrontier:
    observation: ObservedSourceCallsite
    reason: str
