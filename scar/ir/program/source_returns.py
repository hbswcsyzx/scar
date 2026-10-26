"""Conditional language return views over original qualified source endpoints."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .call_edges import InvocationKey
from .ids import BlockID, OperationID, UseID, ValueID
from .model import CompletionResult
from .native import ExitPortRef
from .providers import ProviderFactReference
from .source_call_bindings import SourceBodyNamespace, _exact, _need
from .structured import ControlEdgeReference


class SourceReturnCondition(str, Enum):
    ORIGINAL_TARGET_AND_ENTRY_BINDING = 'ORIGINAL_TARGET_AND_ENTRY_BINDING'
    CALLEE_COMPLETES_NORMALLY = 'CALLEE_COMPLETES_NORMALLY'
    CALL_NORMAL_EDGE_SELECTED = 'CALL_NORMAL_EDGE_SELECTED'
    CALLEE_RETURN_SITE_SELECTED = 'CALLEE_RETURN_SITE_SELECTED'


@dataclass(frozen=True, slots=True)
class SourceReturnSite:
    exit_port: ExitPortRef
    block: BlockID
    operation: OperationID
    use: UseID
    value: ValueID
    terminator_position: int
    condition: SourceReturnCondition = SourceReturnCondition.CALLEE_RETURN_SITE_SELECTED

    def __post_init__(self):
        for value, kind in ((self.exit_port, ExitPortRef), (self.block, BlockID), (self.operation, OperationID),
                            (self.use, UseID), (self.value, ValueID)):
            _exact(value, kind)
        _need(self.exit_port.index == 0 and type(self.terminator_position) is int and self.terminator_position == 0,
              'Python return view selects original object payload0, never world')
        _need(self.condition is SourceReturnCondition.CALLEE_RETURN_SITE_SELECTED, 'return-site condition changed')


@dataclass(frozen=True, slots=True)
class SourceNormalReturnBinding:
    binding_source: ProviderFactReference
    binding_index: int
    caller: InvocationKey
    callee: InvocationKey
    caller_body: SourceBodyNamespace
    callee_body: SourceBodyNamespace
    operation: OperationID
    completion_edge: ControlEdgeReference
    completion: CompletionResult
    landing_block: BlockID
    landing_position: int
    landing_value: ValueID
    sites: tuple[SourceReturnSite, ...]
    rule: str = 'PYTHON_SINGLE_OBJECT_NORMAL_RETURN_V1'
    conditions: tuple[SourceReturnCondition, ...] = (
        SourceReturnCondition.ORIGINAL_TARGET_AND_ENTRY_BINDING,
        SourceReturnCondition.CALLEE_COMPLETES_NORMALLY,
        SourceReturnCondition.CALL_NORMAL_EDGE_SELECTED)

    def __post_init__(self):
        for value, kind in ((self.binding_source, ProviderFactReference), (self.caller, InvocationKey),
                            (self.callee, InvocationKey), (self.caller_body, SourceBodyNamespace),
                            (self.callee_body, SourceBodyNamespace), (self.operation, OperationID),
                            (self.completion_edge, ControlEdgeReference), (self.completion, CompletionResult),
                            (self.landing_block, BlockID), (self.landing_value, ValueID)):
            _exact(value, kind)
        _need(type(self.binding_index) is int and self.binding_index >= 0
              and type(self.landing_position) is int and self.landing_position >= 0, 'exact original indices required')
        _need(self.operation == self.completion_edge.operation and self.completion.index == 0,
              'bound CALL normal object result0 required; world is excluded')
        _need(type(self.sites) is tuple and bool(self.sites), 'normal return needs actual terminal Use alternatives')
        for site in self.sites:
            _exact(site, SourceReturnSite)
            _need(site.exit_port.region == self.callee_body.region, 'return site belongs to another source namespace')
        _need(len({(s.operation, s.use) for s in self.sites}) == len(self.sites), 'duplicate original return site')
        _need(self.rule == 'PYTHON_SINGLE_OBJECT_NORMAL_RETURN_V1' and self.conditions == (
            SourceReturnCondition.ORIGINAL_TARGET_AND_ENTRY_BINDING,
            SourceReturnCondition.CALLEE_COMPLETES_NORMALLY,
            SourceReturnCondition.CALL_NORMAL_EDGE_SELECTED), 'conditional return contract changed')
