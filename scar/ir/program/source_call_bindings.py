"""Qualified conditional source Use-to-formal ports, not observed identities."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum

from scar.ir.program.call_edges import CallLinkStatus, CallRecordAnchor, CallSiteLink, CodeSourceLink, InvocationKey
from scar.ir.program.call_operand_routes import OperandRouteCondition
from scar.ir.program.functions import BindingOrigin, CallBindingStatus, CandidateBinding, ParameterBinding
from scar.ir.program.ids import OperationID, RegionID, UseID, ValueID
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.record_codec import decode, encode, loads as strict_loads
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID, ValueSlotID


def _need(value, detail):
    if not value:
        raise ValueError("source call ports: " + detail)


def _exact(value, kind):
    _need(type(value) is kind, "expected exact " + kind.__name__)
    if hasattr(value, "__post_init__"):
        value.__post_init__()


@dataclass(frozen=True, slots=True)
class SourceBodyNamespace:
    """The producer's original graph namespace, not a new graph or node ID."""
    graph: SourceArtifactLocator
    graph_representation: str
    definition: OperationDefinitionID
    source: SourceReference | None
    entry: str
    region: RegionID

    def __post_init__(self):
        _exact(self.graph, SourceArtifactLocator)
        _exact(self.definition, OperationDefinitionID)
        _exact(self.region, RegionID)
        if self.source is not None:
            _exact(self.source, SourceReference)
        prefix = "scar.program-graph/"
        _need(type(self.graph_representation) is str and self.graph_representation.startswith(prefix)
              and self.graph_representation[len(prefix):].isdigit(), "original graph representation")
        _need(type(self.entry) is str and bool(self.entry), "original body entry")
        _need(self.graph.declaration is not None, "body graph needs its original declaration")

    def original_namespace(self):
        return {"artifact": {"uri": self.graph.artifact.uri, "decoded_sha256": self.graph.decoded_sha256},
                "representation": self.graph_representation, "record_pointer": self.graph.pointer,
                "body": {"definition": encode(self.definition), "source": encode(self.source), "entry": self.entry}}


@dataclass(frozen=True, slots=True)
class SourceArgumentPort:
    index: int
    actual_body: SourceBodyNamespace
    operation: OperationID
    actual_source: SourceReference
    actual_use: UseID
    actual_value: ValueID
    formal_body: SourceBodyNamespace
    formal_slot: ValueSlotID
    formal_value: ValueID
    formal_name: str
    parameter: ParameterBinding

    def __post_init__(self):
        _need(type(self.index) is int and self.index >= 0, "nonnegative argument index")
        for value, kind in ((self.actual_body, SourceBodyNamespace), (self.formal_body, SourceBodyNamespace),
                            (self.operation, OperationID), (self.actual_source, SourceReference),
                            (self.actual_use, UseID), (self.actual_value, ValueID),
                            (self.formal_slot, ValueSlotID), (self.formal_value, ValueID),
                            (self.parameter, ParameterBinding)):
            _exact(value, kind)
        _need(type(self.formal_name) is str and bool(self.formal_name), "formal name")
        _need(self.parameter.slot == self.formal_slot and self.parameter.origin is BindingOrigin.ARGUMENT
              and self.parameter.argument_indices == (self.index,), "parameter route differs from source operand")


@dataclass(frozen=True, slots=True)
class SourceCallPortBinding:
    attempt: CallRecordAnchor
    handshake: CallRecordAnchor
    entry: CallRecordAnchor
    caller: InvocationKey
    callee: InvocationKey
    caller_code: CodeSourceLink
    callee_code: CodeSourceLink
    call: CallSiteLink
    caller_body: SourceBodyNamespace
    callee_body: SourceBodyNamespace
    candidate: CandidateBinding
    ports: tuple[SourceArgumentPort, ...]
    rule: str = "EXACT_FUNCTION_POSITIONAL_SOURCE_PORTS_V1"
    conditions: tuple[OperandRouteCondition, ...] = tuple(OperandRouteCondition)

    def __post_init__(self):
        for value, kind in ((self.attempt, CallRecordAnchor), (self.handshake, CallRecordAnchor),
                            (self.entry, CallRecordAnchor), (self.caller, InvocationKey), (self.callee, InvocationKey),
                            (self.caller_code, CodeSourceLink), (self.callee_code, CodeSourceLink),
                            (self.call, CallSiteLink), (self.caller_body, SourceBodyNamespace),
                            (self.callee_body, SourceBodyNamespace), (self.candidate, CandidateBinding)):
            _exact(value, kind)
        _need((self.caller.process_id, self.caller.thread_id) == (self.callee.process_id, self.callee.thread_id)
              and self.caller != self.callee, "direct entry process/thread/invocation differs")
        _need(self.rule == "EXACT_FUNCTION_POSITIONAL_SOURCE_PORTS_V1"
              and self.conditions == tuple(OperandRouteCondition), "conditional source rule requirements changed")
        _need(self.call.status is self.caller_code.status is self.callee_code.status is CallLinkStatus.VERIFIED
              and self.caller_code.code == self.call.site.code
              and self.caller_code.definition == self.caller_body.definition
              and self.callee_code.definition == self.callee_body.definition,
              "source call/CodeVersion differs from qualified bodies")
        _need(self.candidate.status is CallBindingStatus.CONDITIONAL and self.candidate.call == self.call.call
              and self.candidate.source == self.call.source
              and self.candidate.target == self.callee_body.definition
              and self.call.execution_owner == self.caller_body.definition
              and self.call.core_region == self.caller_body.region, "candidate/body/source call differs")
        _need(type(self.ports) is tuple and len(self.ports) == len(self.candidate.arguments)
              and tuple(p.index for p in self.ports) == tuple(range(len(self.ports))), "ordered source ports")
        for port, actual in zip(self.ports, self.candidate.arguments):
            _exact(port, SourceArgumentPort)
            _need(port.actual_body == self.caller_body and port.formal_body == self.callee_body
                  and port.operation == self.call.core_operation and port.actual_use == actual.use
                  and port.actual_source == actual.source and port.parameter in self.candidate.routes,
                  "argument port changed its qualified caller/callee/source route")


class SourcePortIssueKind(str, Enum):
    HANDSHAKE_BOUNDARY = "HANDSHAKE_BOUNDARY"
    CAPTURE_GAP = "CAPTURE_GAP"
    CODE_WITNESS_UNAVAILABLE = "CODE_WITNESS_UNAVAILABLE"
    SOURCE_CORE_BOUNDARY = "SOURCE_CORE_BOUNDARY"
    DISPATCH_BOUNDARY = "DISPATCH_BOUNDARY"
    CALL_INSTRUCTION_BOUNDARY = "CALL_INSTRUCTION_BOUNDARY"
    BODY_NAMESPACE_UNAVAILABLE = "BODY_NAMESPACE_UNAVAILABLE"
    BINDING_INCOMPLETE = "BINDING_INCOMPLETE"
    BUDGET = "BUDGET"


@dataclass(frozen=True, slots=True)
class SourceCallPortIssue:
    kind: SourcePortIssueKind
    attempt: CallRecordAnchor
    caller: InvocationKey
    detail: str

    def __post_init__(self):
        _exact(self.kind, SourcePortIssueKind)
        _exact(self.attempt, CallRecordAnchor)
        _exact(self.caller, InvocationKey)
        _need(type(self.detail) is str and bool(self.detail), "specific source binding issue")


@dataclass(frozen=True, slots=True)
class SourceCallPortBudget:
    max_attempts: int = 1_000_000
    max_bindings: int = 100_000
    max_ports: int = 1_000_000

    def __post_init__(self):
        _need(all(type(n) is int and n > 0 for n in (self.max_attempts, self.max_bindings, self.max_ports)),
              "positive exact source-port budgets")


@dataclass(frozen=True, slots=True)
class SourceCallPortModel:
    budget: SourceCallPortBudget
    attempt_count: int
    bindings: tuple[SourceCallPortBinding, ...]
    issues: tuple[SourceCallPortIssue, ...]

    def __post_init__(self):
        _exact(self.budget, SourceCallPortBudget)
        _need(type(self.attempt_count) is int and 0 <= self.attempt_count <= self.budget.max_attempts,
              "complete attempt denominator exceeds budget")
        for records, kind in ((self.bindings, SourceCallPortBinding), (self.issues, SourceCallPortIssue)):
            _need(type(records) is tuple, "typed source-port record tuple")
            for record in records:
                _exact(record, kind)
        anchors = [b.attempt for b in self.bindings] + [i.attempt for i in self.issues]
        _need(len(anchors) == len(set(anchors)) == self.attempt_count, "each attempt needs exactly one binding or issue")
        _need(len(self.bindings) <= self.budget.max_bindings
              and sum(len(b.ports) for b in self.bindings) <= self.budget.max_ports, "source-port output budget")

    def summary(self):
        return {"attempts": self.attempt_count, "bound_calls": len(self.bindings),
                "argument_ports": sum(len(b.ports) for b in self.bindings),
                "issues": dict(Counter(i.kind.value for i in self.issues)),
                "reference_identity_established": False, "contents_state_ready_established": False,
                "whole_program_complete": False, "transformation_authorized": False}

    def to_dict(self):
        return {"schema": "scar.source-call-port-bindings", "schema_version": 1,
                "model": encode(self), "summary": self.summary()}

    @classmethod
    def from_dict(cls, value):
        _need(type(value) is dict and set(value) == {"schema", "schema_version", "model", "summary"}
              and value["schema"] == "scar.source-call-port-bindings"
              and type(value["schema_version"]) is int and value["schema_version"] == 1, "source-port transport")
        model = decode(cls, value["model"])
        _need(model.summary() == value["summary"], "source-port summary differs from exact records")
        return model

    @classmethod
    def loads(cls, payload):
        return cls.from_dict(strict_loads(payload))
