"""State sequencing over original F4 ports, distinct from value aliases."""
from dataclasses import dataclass

from .normal_targets import GlobalPort, Body
from .normal_graph import Edge
from .providers import ProviderArtifact, ProviderFactReference


@dataclass(frozen=True, slots=True)
class OperationStateTransition:
    before: GlobalPort
    after: GlobalPort
    instruction_type: str
    conditions: tuple[str, ...] = ('NORMAL_OPERATION_COMPLETION_SELECTED', 'OPERATION_EFFECTS_REMAIN_OPEN')


@dataclass(frozen=True, slots=True)
class SequencedAccess:
    fact: ProviderFactReference
    table: str
    action: str
    world_before: GlobalPort
    world_after: GlobalPort


@dataclass(frozen=True, slots=True)
class SourceWorldFlow:
    projection: ProviderFactReference
    source_templates: ProviderArtifact
    unit: str
    caller_body: Body
    anchor: GlobalPort
    normal_exit: GlobalPort
    edges: tuple[Edge, ...]
    operations: tuple[OperationStateTransition, ...]
    accesses: tuple[SequencedAccess, ...]
    anchor_reaches_exit: bool
    conditions: tuple[str, ...]
    semantics: str = 'CONDITIONAL_SHARED_STATE_PATHS_NOT_RUNTIME_ORDER_OR_CONTENT_PRESERVATION'
