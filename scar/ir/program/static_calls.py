"""Qualified static call relations over original graphs; never invocations.

These records add relationships, not operations, values or state carriers.
Every target is conditional. A sole candidate is not a verified dynamic target.
"""
from __future__ import annotations

from dataclasses import dataclass
import json

from scar.ir.record_codec import decode, encode, loads as strict_loads
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID
from .functions import CandidateBinding
from .ids import BlockID, LocationID, OperationID, UseID, ValueID
from .model import ExitKind, ValueKind
from .native import ExitPortRef
from .providers import ProviderArtifact
from .source_call_bindings import SourceArgumentPort, SourceBodyNamespace
from .source_references import SourceDefinitionReference
from .source_returns import SourceReturnSite
from .structured import ControlEdgeReference


def _exact(value, kind):
    if type(value) is not kind:
        raise TypeError("static calls require exact " + kind.__name__)
    method = getattr(value, "__post_init__", None)
    if method is not None:
        method()


def _rows(value, kind):
    if type(value) is not tuple:
        raise TypeError("static relation rows must be tuples")
    for row in value:
        _exact(row, kind)


@dataclass(frozen=True, slots=True)
class StaticCallFrontier:
    kind: str
    detail: str
    source: SourceReference | None = None

    def __post_init__(self):
        if any(type(text) is not str or not text for text in (self.kind, self.detail)):
            raise ValueError("static frontier needs a precise kind/detail")
        if self.source is not None:
            _exact(self.source, SourceReference)


@dataclass(frozen=True, slots=True)
class StaticTerminalPort:
    """One original callee terminal operand, conditional on that exit site."""
    port: ExitPortRef
    block: BlockID
    operation: OperationID
    use: UseID
    value: ValueID

    def __post_init__(self):
        for value, kind in ((self.port, ExitPortRef), (self.block, BlockID),
                            (self.operation, OperationID), (self.use, UseID), (self.value, ValueID)):
            _exact(value, kind)


@dataclass(frozen=True, slots=True)
class StaticCompletionRoute:
    """Callee exit alternatives -> caller produced completion formal.

    STATE maps call interfaces, never equates LocationIDs or proves mod/ref.
    Reference payload mapping is language dependence, not observed equality.
    """
    kind: ExitKind
    value_kind: ValueKind
    caller_edge: ControlEdgeReference
    completion_index: int
    landing_block: BlockID
    landing_value: ValueID
    callee_port: ExitPortRef
    terminals: tuple[StaticTerminalPort, ...]

    def __post_init__(self):
        for value, kind in ((self.kind, ExitKind), (self.value_kind, ValueKind),
                            (self.caller_edge, ControlEdgeReference), (self.landing_block, BlockID),
                            (self.landing_value, ValueID), (self.callee_port, ExitPortRef)):
            _exact(value, kind)
        if type(self.completion_index) is not int or self.completion_index < 0:
            raise ValueError("completion index must be nonnegative")
        _rows(self.terminals, StaticTerminalPort)
        if not self.terminals or any(row.port != self.callee_port for row in self.terminals):
            raise ValueError("completion route needs its original exact terminal alternatives")


@dataclass(frozen=True, slots=True)
class StaticStateEntryRoute:
    caller_use: UseID
    caller_value: ValueID
    caller_location: LocationID
    callee_value: ValueID
    callee_location: LocationID
    basis: str = "COARSE_CALL_WORLD_INTERFACE_NOT_LOCATION_IDENTITY"

    def __post_init__(self):
        for value, kind in ((self.caller_use, UseID), (self.caller_value, ValueID),
                            (self.callee_value, ValueID), (self.caller_location, LocationID),
                            (self.callee_location, LocationID)):
            _exact(value, kind)
        if self.basis != "COARSE_CALL_WORLD_INTERFACE_NOT_LOCATION_IDENTITY":
            raise ValueError("static state mapping cannot claim state-content identity")


@dataclass(frozen=True, slots=True)
class StaticCallTarget:
    definition: SourceDefinitionReference
    body: SourceBodyNamespace | None
    basis: tuple[str, ...]
    binding: CandidateBinding | None = None
    arguments: tuple[SourceArgumentPort, ...] = ()
    normal_returns: tuple[SourceReturnSite, ...] = ()
    completions: tuple[StaticCompletionRoute, ...] = ()
    state_entry: StaticStateEntryRoute | None = None
    frontiers: tuple[StaticCallFrontier, ...] = ()
    qualification: str = "CONDITIONAL_STATIC_CANDIDATE"

    def __post_init__(self):
        _exact(self.definition, SourceDefinitionReference)
        if self.body is not None:
            _exact(self.body, SourceBodyNamespace)
            if self.body.definition != self.definition.definition or self.body.source != self.definition.source:
                raise ValueError("callee body differs from the original qualified definition")
        if type(self.basis) is not tuple or not self.basis or any(type(x) is not str or not x for x in self.basis):
            raise ValueError("candidate needs explicit source-resolution bases")
        if self.binding is not None:
            _exact(self.binding, CandidateBinding)
            if self.binding.target != self.definition.definition:
                raise ValueError("signature binding names another candidate")
        for rows, kind in ((self.arguments, SourceArgumentPort), (self.normal_returns, SourceReturnSite),
                           (self.completions, StaticCompletionRoute), (self.frontiers, StaticCallFrontier)):
            _rows(rows, kind)
        if self.state_entry is not None:
            _exact(self.state_entry, StaticStateEntryRoute)
        if self.body is None and (self.arguments or self.normal_returns or self.completions or self.state_entry):
            raise ValueError("missing body cannot supply invented ports")
        if self.body is not None:
            if any(port.formal_body != self.body for port in self.arguments):
                raise ValueError("formal belongs to another body namespace")
            if any(route.callee_port.region != self.body.region for route in self.completions):
                raise ValueError("completion belongs to another callee region")
        if self.qualification != "CONDITIONAL_STATIC_CANDIDATE":
            raise ValueError("static target cannot claim an observed or unconditional dispatch")


@dataclass(frozen=True, slots=True)
class StaticCallSite:
    caller: SourceBodyNamespace
    operation: OperationID
    source: SourceReference
    semantic_call: OperationDefinitionID | None
    callee_use: UseID | None
    callee_value: ValueID | None
    targets: tuple[StaticCallTarget, ...] = ()
    frontiers: tuple[StaticCallFrontier, ...] = ()
    target_set_complete: bool = False

    def __post_init__(self):
        _exact(self.caller, SourceBodyNamespace)
        _exact(self.operation, OperationID)
        _exact(self.source, SourceReference)
        if self.semantic_call is not None:
            _exact(self.semantic_call, OperationDefinitionID)
        if (self.callee_use is None) != (self.callee_value is None):
            raise ValueError("callee Use/value must be present together")
        if self.callee_use is not None:
            _exact(self.callee_use, UseID)
            _exact(self.callee_value, ValueID)
        _rows(self.targets, StaticCallTarget)
        _rows(self.frontiers, StaticCallFrontier)
        for target in self.targets:
            if any(port.actual_body != self.caller or port.operation != self.operation for port in target.arguments):
                raise ValueError("actual port belongs to another original caller")
        if self.target_set_complete is not False:
            raise ValueError("the initial linker does not prove target-set closure")


@dataclass(frozen=True, slots=True)
class StaticCallShard:
    source_model: ProviderArtifact
    caller: SourceBodyNamespace
    calls: tuple[StaticCallSite, ...]

    def __post_init__(self):
        _exact(self.source_model, ProviderArtifact)
        _exact(self.caller, SourceBodyNamespace)
        _rows(self.calls, StaticCallSite)
        if any(call.caller != self.caller for call in self.calls):
            raise ValueError("one static relation shard must preserve its caller namespace")
        if len({call.operation for call in self.calls}) != len(self.calls):
            raise ValueError("canonical CALL must occur once per caller")


def dumps(shard: StaticCallShard) -> str:
    _exact(shard, StaticCallShard)
    return json.dumps({"schema": "scar.static-calls", "schema_version": 1,
                       "relations": encode(shard)}, sort_keys=True, separators=(",", ":"), allow_nan=False)


def loads(payload: str) -> StaticCallShard:
    document = strict_loads(payload)
    if (type(document) is not dict or set(document) != {"schema", "schema_version", "relations"}
            or document["schema"] != "scar.static-calls" or type(document["schema_version"]) is not int
            or document["schema_version"] != 1):
        raise ValueError("unsupported static call relation shard")
    return decode(StaticCallShard, document["relations"])


__all__ = ["StaticCallFrontier", "StaticTerminalPort", "StaticCompletionRoute",
           "StaticStateEntryRoute", "StaticCallTarget", "StaticCallSite", "StaticCallShard", "dumps", "loads"]
