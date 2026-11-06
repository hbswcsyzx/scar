"""Conditional content projections at source call state boundaries."""
from dataclasses import dataclass

from .configuration_composition import ConfigurationProtocolSource
from .normal_links import CodeScopeWitness
from .normal_targets import GlobalPort
from .providers import ProviderArtifact,ProviderFactReference


@dataclass(frozen=True,slots=True)
class SourceStateProjection:
    value_graph: ProviderArtifact
    value_expression: int
    facts: ProviderArtifact
    protocol: ConfigurationProtocolSource
    source_function: GlobalPort
    caller: CodeScopeWitness
    call: ProviderFactReference
    attribute: ProviderFactReference
    attribute_result: GlobalPort
    callee: GlobalPort
    callee_alias_rows: tuple[int,...]
    receiver: GlobalPort
    world_before: GlobalPort
    world_after: GlobalPort
    data_result: GlobalPort
    normal_return: GlobalPort
    none_origin: GlobalPort
    none_alias_rows: tuple[int,...]
    conditions: tuple[str,...]
    semantics: str = 'CONDITIONAL_CONTENT_AT_CALL_RESULT_WORLD_NOT_PYTHON_RESULT_OR_TASK_STATE'
