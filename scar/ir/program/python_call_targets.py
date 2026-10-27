"""Versioned observed Python targets, separate from legacy operand v1 facts."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import re
from scar.ir.program.call_edges import CallRecordAnchor,InvocationKey
from scar.ir.program.call_operands import FunctionLayout, _reference
from scar.ir.record_codec import encode,decode,loads as strict_loads
from scar.ir.program.source_call_bindings import SourceBodyNamespace, SourceArgumentPort, _exact, _need
from scar.ir.program.call_edges import CallSiteLink, CodeSourceLink, CallLinkStatus
from scar.ir.program.call_operand_routes import OperandRouteCondition
from scar.ir.program.functions import CandidateBinding
from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.v2.ids import ValueSlotID

class PythonTargetKind(str,Enum):
    FUNCTION='FUNCTION'
    BOUND_METHOD='BOUND_METHOD'
    NORMALIZED_RECEIVER_FUNCTION='NORMALIZED_RECEIVER_FUNCTION'
    NATIVE_BUILTIN='NATIVE_BUILTIN'
    NATIVE_WRAPPER='NATIVE_WRAPPER'
    OTHER_UNCLASSIFIED='OTHER_UNCLASSIFIED'

class PythonCodeScope(str,Enum):
    PROJECT='PROJECT'
    OBSERVED_EXTERNAL_PYTHON='OBSERVED_EXTERNAL_PYTHON'
    NONFILESYSTEM_PYTHON='NONFILESYSTEM_PYTHON'
    NO_PYTHON_CODE='NO_PYTHON_CODE'

class ReceiverRole(str,Enum):
    BOUND_METHOD_RECEIVER='BOUND_METHOD_RECEIVER'
    IMPLICIT_CALL_RECEIVER='IMPLICIT_CALL_RECEIVER'

class ReceiverCondition(str,Enum):
    NO_INTERVENING_CALL_LAYOUT_MUTATION='NO_INTERVENING_CALL_LAYOUT_MUTATION'

@dataclass(frozen=True,slots=True)
class PythonSourcePortBudget:
    max_sidecar_bytes:int=32_000_000
    max_sidecar_rows:int=1_000_000
    max_attempts:int=1_000_000
    max_bindings:int=100_000
    max_ports:int=1_000_000
    def __post_init__(self):
        if any(type(getattr(self,name)) is not int or getattr(self,name)<1 for name in self.__dataclass_fields__):
            raise ValueError('positive independent Python source-port ceilings required')

@dataclass(frozen=True,slots=True)
class BoundReceiver:
    role:ReceiverRole
    reference:str
    explicit_positional:int|None=None
    conditions:tuple[ReceiverCondition,...]=()
    def __post_init__(self):
        if type(self.role) is not ReceiverRole or type(self.reference) is not str or not self.reference:
            raise ValueError('typed observed bound receiver required')
        _reference(self.reference)
        if self.role is ReceiverRole.IMPLICIT_CALL_RECEIVER:
            if type(self.explicit_positional) is not int or self.explicit_positional<0 or self.conditions!=(ReceiverCondition.NO_INTERVENING_CALL_LAYOUT_MUTATION,):
                raise ValueError('normalized CALL receiver requires finite ABI and explicit mutation condition')
        elif self.explicit_positional is not None or self.conditions:
            raise ValueError('actual MethodType fields do not use normalized CALL arity inference')

@dataclass(frozen=True,slots=True)
class PythonCallTarget:
    attempt_index:int
    caller:InvocationKey
    kind:PythonTargetKind
    callable_reference:str
    function_reference:str|None
    code:str|None
    layout:FunctionLayout|None
    receiver:BoundReceiver|None
    scope:PythonCodeScope
    def __post_init__(self):
        if type(self.attempt_index) is not int or self.attempt_index<1 or type(self.caller) is not InvocationKey:
            raise ValueError('target requires original attempt and caller')
        self.caller.__post_init__()
        if type(self.kind) is not PythonTargetKind or type(self.scope) is not PythonCodeScope:
            raise ValueError('typed target category/scope required')
        _reference(self.callable_reference)
        python=self.kind in (PythonTargetKind.FUNCTION,PythonTargetKind.BOUND_METHOD,PythonTargetKind.NORMALIZED_RECEIVER_FUNCTION)
        if python:
            if not self.function_reference or not self.code or type(self.layout) is not FunctionLayout or self.scope is PythonCodeScope.NO_PYTHON_CODE:
                raise ValueError('observed Python function/code/layout required')
            self.layout.__post_init__()
            _reference(self.function_reference)
            if re.fullmatch(r'pycode-v2:[0-9a-f]{64}',self.code) is None:raise ValueError('original stable code fingerprint required')
        elif any(v is not None for v in (self.function_reference,self.code,self.layout,self.receiver)) or self.scope is not PythonCodeScope.NO_PYTHON_CODE:
            raise ValueError('non-Python/unclassified target cannot claim Python fields')
        if (self.kind in (PythonTargetKind.BOUND_METHOD,PythonTargetKind.NORMALIZED_RECEIVER_FUNCTION))!=(type(self.receiver) is BoundReceiver):
            raise ValueError('only observed method/explicit CALL receiver ABI has receiver role')
        if self.receiver is not None:self.receiver.__post_init__()
        if self.kind is PythonTargetKind.NORMALIZED_RECEIVER_FUNCTION:
            _need(self.function_reference==self.callable_reference
                and self.layout.argcount>=self.receiver.explicit_positional+1 and self.layout.kwonlyargcount==0,
                'normalized CALL receiver layout omits its receiver or positional prefix')

@dataclass(frozen=True,slots=True)
class PythonEntryBinding:
    attempt_index:int
    caller:InvocationKey
    callee:InvocationKey
    entry_index:int
    code:str
    receiver_parameter_index:int|None
    receiver_reference:str|None
    def __post_init__(self):
        if any(type(x) is not int or x<1 for x in (self.attempt_index,self.entry_index)) or type(self.caller) is not InvocationKey or type(self.callee) is not InvocationKey:
            raise ValueError('original attempt/frame entry required')
        self.caller.__post_init__();self.callee.__post_init__()
        if type(self.code) is not str or re.fullmatch(r'pycode-v2:[0-9a-f]{64}',self.code) is None:raise ValueError('entry code fingerprint required')
        if (self.caller.process_id,self.caller.thread_id)!=(self.callee.process_id,self.callee.thread_id) or self.caller==self.callee:
            raise ValueError('Python entry requires actual direct distinct same-thread invocations')
        if (self.receiver_parameter_index is None)!=(self.receiver_reference is None):raise ValueError('receiver entry role incomplete')
        if self.receiver_parameter_index is not None and (type(self.receiver_parameter_index) is not int or self.receiver_parameter_index!=0):raise ValueError('Python bound receiver is first formal port, independent of source actual indices')
        if self.receiver_reference is not None:_reference(self.receiver_reference)

@dataclass(frozen=True,slots=True)
class PythonTargetGap:
    attempt_index:int|None
    reason:str
    def __post_init__(self):
        if self.attempt_index is not None and (type(self.attempt_index) is not int or self.attempt_index<1):raise ValueError('gap original attempt')
        if type(self.reason) is not str or not self.reason:raise ValueError('specific target/entry gap required')

_TYPES={'TARGET':PythonCallTarget,'ENTRY':PythonEntryBinding,'GAP':PythonTargetGap}
def target_record(kind,value):
    if kind not in _TYPES or type(value) is not _TYPES[kind]:raise ValueError('closed target record kind/type')
    value.__post_init__();return {'schema':'scar.python-call-targets','schema_version':2,'kind':kind,'value':encode(value)}
def read_target_record(document):
    if type(document) is not dict or set(document)!={'schema','schema_version','kind','value'} or document['schema']!='scar.python-call-targets' or type(document['schema_version']) is not int or document['schema_version']!=2 or document['kind'] not in _TYPES:
        raise ValueError('unsupported Python target capability record')
    return document['kind'],decode(_TYPES[document['kind']],document['value'])


@dataclass(frozen=True,slots=True)
class SourceReceiverPort:
    """A bound-callable projection of an existing callee Use, not a new SSA value."""
    actual_body:SourceBodyNamespace
    operation:OperationID
    callable_use:UseID
    callable_value:ValueID
    formal_body:SourceBodyNamespace
    formal_slot:ValueSlotID
    formal_value:ValueID
    formal_name:str
    observed:BoundReceiver
    projection:str='PYTHON_BOUND_CALLABLE_RECEIVER_V1'
    def __post_init__(self):
        for value,kind in ((self.actual_body,SourceBodyNamespace),(self.formal_body,SourceBodyNamespace),
                (self.operation,OperationID),(self.callable_use,UseID),(self.callable_value,ValueID),
                (self.formal_slot,ValueSlotID),(self.formal_value,ValueID),(self.observed,BoundReceiver)):_exact(value,kind)
        _need(type(self.formal_name) is str and bool(self.formal_name) and self.projection=='PYTHON_BOUND_CALLABLE_RECEIVER_V1','receiver projection contract')


@dataclass(frozen=True,slots=True)
class PythonSourcePortBinding:
    target:PythonCallTarget
    target_anchor:CallRecordAnchor
    entry:PythonEntryBinding
    entry_anchor:CallRecordAnchor
    attempt:CallRecordAnchor
    frame_entry:CallRecordAnchor
    caller_code:CodeSourceLink
    callee_code:CodeSourceLink
    call:CallSiteLink
    caller_body:SourceBodyNamespace
    callee_body:SourceBodyNamespace
    receiver:SourceReceiverPort|None
    arguments:tuple[SourceArgumentPort,...]
    candidate:CandidateBinding|None
    conditions:tuple[OperandRouteCondition,...]=tuple(OperandRouteCondition)
    def __post_init__(self):
        for value,kind in ((self.target,PythonCallTarget),(self.target_anchor,CallRecordAnchor),
                (self.entry,PythonEntryBinding),(self.entry_anchor,CallRecordAnchor),(self.attempt,CallRecordAnchor),
                (self.frame_entry,CallRecordAnchor),(self.caller_code,CodeSourceLink),(self.callee_code,CodeSourceLink),
                (self.call,CallSiteLink),(self.caller_body,SourceBodyNamespace),(self.callee_body,SourceBodyNamespace)):_exact(value,kind)
        _need(self.target.attempt_index==self.entry.attempt_index==self.attempt.index
            and self.target.caller==self.entry.caller and self.target.code==self.entry.code==self.callee_code.code
            and self.entry.entry_index==self.frame_entry.index,'original target/entry anchor mismatch')
        _need(self.call.status is self.caller_code.status is self.callee_code.status is CallLinkStatus.VERIFIED
            and self.call.site.code==self.caller_code.code and self.call.execution_owner==self.caller_body.definition
            and self.call.core_region==self.caller_body.region and self.caller_code.definition==self.caller_body.definition
            and self.callee_code.definition==self.callee_body.definition,'qualified original source/code/body differs')
        _need(self.conditions==tuple(OperandRouteCondition),'conditional source rule changed')
        _need(type(self.arguments) is tuple and tuple(p.index for p in self.arguments)==tuple(range(len(self.arguments))),'explicit argument indices exclude receiver')
        for port in self.arguments:
            _exact(port,SourceArgumentPort)
            _need(port.actual_body==self.caller_body and port.formal_body==self.callee_body and port.operation==self.call.core_operation,'argument original namespace differs')
        if self.target.receiver is not None:
            _exact(self.receiver,SourceReceiverPort)
            _need(self.candidate is None and self.receiver.observed==self.target.receiver
                and self.receiver.actual_body==self.caller_body and self.receiver.formal_body==self.callee_body
                and self.receiver.operation==self.call.core_operation and self.receiver.callable_use==self.call.callee_use
                and self.receiver.callable_value==self.call.callee_value and self.entry.receiver_parameter_index==0,
                'receiver is its independent bound-callable projection, never an explicit actual')
        else:
            _need(self.receiver is None,'ordinary function cannot acquire a receiver')
            _exact(self.candidate,CandidateBinding)
            _need(self.candidate.call==self.call.call and self.candidate.source==self.call.source
                and self.candidate.target==self.callee_body.definition
                and len(self.candidate.arguments)==len(self.arguments),'original function candidate differs')
            for port,actual in zip(self.arguments,self.candidate.arguments):
                _need(port.actual_use==actual.use and port.actual_source==actual.source
                    and port.parameter in self.candidate.routes,'explicit function source route differs')


@dataclass(frozen=True,slots=True)
class PythonSourcePortIssue:
    target_anchor:CallRecordAnchor
    attempt_index:int
    detail:str
    def __post_init__(self):
        _exact(self.target_anchor,CallRecordAnchor)
        _need(type(self.attempt_index) is int and self.attempt_index>0 and type(self.detail) is str and bool(self.detail),'explicit Python source-port boundary required')


@dataclass(frozen=True,slots=True)
class ObservedPythonCallGraph:
    source:str
    source_sha256:str
    targets:tuple[PythonCallTarget,...]
    entries:tuple[PythonEntryBinding,...]
    gaps:tuple[PythonTargetGap,...]
    target_anchors:tuple[CallRecordAnchor,...]
    entry_anchors:tuple[CallRecordAnchor,...]
    def __post_init__(self):
        if type(self.source) is not str or not self.source.startswith('/') or type(self.source_sha256) is not str or re.fullmatch(r'[0-9a-f]{64}',self.source_sha256) is None:raise ValueError('exact original target collection identity required')
        for sequence,kind in ((self.targets,PythonCallTarget),(self.entries,PythonEntryBinding),(self.gaps,PythonTargetGap),
                (self.target_anchors,CallRecordAnchor),(self.entry_anchors,CallRecordAnchor)):
            if type(sequence) is not tuple or any(type(v) is not kind for v in sequence):raise ValueError('typed observed graph records required')
            for value in sequence:value.__post_init__()
        if len(self.targets)!=len(self.target_anchors) or len(self.entries)!=len(self.entry_anchors):raise ValueError('original evidence anchors must cover graph records')
        keys=[(t.caller.process_id,t.attempt_index) for t in self.targets]
        if len(keys)!=len(set(keys)):raise ValueError('duplicate original target')
    def summary(self):
        from collections import Counter
        return {'targets':len(self.targets),'entries':len(self.entries),'gaps':len(self.gaps),
                'kinds':dict(Counter(t.kind.value for t in self.targets)),
                'receiver_entries':sum(e.receiver_parameter_index is not None for e in self.entries),
                'contents_state_ready_established':False,'whole_program_complete':False}
    def to_dict(self):
        return {'schema':'scar.observed-python-call-graph','schema_version':2,'graph':encode(self),'summary':self.summary()}
    @classmethod
    def from_dict(cls,value):
        if type(value) is not dict or set(value)!={'schema','schema_version','graph','summary'} or value['schema']!='scar.observed-python-call-graph' or type(value['schema_version']) is not int or value['schema_version']!=2:raise ValueError('unsupported observed Python graph transport')
        graph=decode(cls,value['graph'])
        if graph.summary()!=value['summary']:raise ValueError('observed Python graph summary differs')
        return graph


@dataclass(frozen=True,slots=True)
class PythonSourcePortModel:
    """New receiver-aware relation version; old SourceCallPortModel stays v1."""
    observed:ObservedPythonCallGraph
    bindings:tuple[PythonSourcePortBinding,...]
    issues:tuple[PythonSourcePortIssue,...]
    def __post_init__(self):
        if type(self.observed) is not ObservedPythonCallGraph:raise ValueError('original observed Python graph required')
        self.observed.__post_init__()
        for sequence,kind in ((self.bindings,PythonSourcePortBinding),(self.issues,PythonSourcePortIssue)):
            if type(sequence) is not tuple or any(type(v) is not kind for v in sequence):raise ValueError('typed Python source port records required')
            for value in sequence:value.__post_init__()
        original=set(self.observed.target_anchors)
        covered=[b.target_anchor for b in self.bindings]+[i.target_anchor for i in self.issues]
        if len(covered)!=len(original) or set(covered)!=original:raise ValueError('every original observed target needs binding or explicit boundary')
        targets=dict(zip(self.observed.target_anchors,self.observed.targets))
        entries=dict(zip(self.observed.entry_anchors,self.observed.entries))
        for binding in self.bindings:
            if targets[binding.target_anchor]!=binding.target or entries.get(binding.entry_anchor)!=binding.entry:raise ValueError('source relation changed its original observed target/entry')
        for issue in self.issues:
            if targets[issue.target_anchor].attempt_index!=issue.attempt_index:raise ValueError('source boundary changed its original target')
    def summary(self):
        return {'targets':len(self.observed.targets),'bound_calls':len(self.bindings),
            'receiver_ports':sum(b.receiver is not None for b in self.bindings),
            'explicit_argument_ports':sum(len(b.arguments) for b in self.bindings),'open_targets':len(self.issues),
            'reference_identity_established':False,'effects_state_ready_established':False,'whole_program_complete':False}
    def to_dict(self):
        return {'schema':'scar.python-source-port-bindings','schema_version':2,
            'observed':self.observed.to_dict(),'bindings':encode(self.bindings),'issues':encode(self.issues),'summary':self.summary()}
    @classmethod
    def loads(cls,payload):
        value=strict_loads(payload)
        if type(value) is not dict or set(value)!={'schema','schema_version','observed','bindings','issues','summary'} or value['schema']!='scar.python-source-port-bindings' or type(value['schema_version']) is not int or value['schema_version']!=2:raise ValueError('unsupported receiver-aware source port transport')
        model=cls(ObservedPythonCallGraph.from_dict(value['observed']),tuple(decode(PythonSourcePortBinding,b) for b in value['bindings']),tuple(decode(PythonSourcePortIssue,i) for i in value['issues']))
        if model.summary()!=value['summary']:raise ValueError('source ports summary differs from records')
        return model

