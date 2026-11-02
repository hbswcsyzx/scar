"""Bounded value facts over the one contextual program dependency graph.

No target executes. Binding-token payload, reference provenance, immutable
scalar content, and builtin type are distinct fields. A dependency edge is
not an identity rule; only the explicit port/field rules below transfer facts.
"""
from __future__ import annotations

import ast
from collections import defaultdict,deque,OrderedDict
from dataclasses import dataclass,replace
from enum import Enum
from itertools import product
from typing import Literal
from scar.analysis.constants_v2 import _BudgetExceeded,_Unsupported

from scar.ir.literals import PythonLiteral,LiteralKind,literal_builtin_type,_preflight_literal
from scar.ir.program.bindings import BindingState
from scar.ir.program.dependencies import (DependencyCondition as Condition,
    DependencyEvidence as Evidence,DependencyFrontier as Frontier,
    DependencyKind as K,DependencyMeaning as M,DependencyPoint as Point,
    DependencyStrength as Strength,DependencyEdge)
from scar.ir.program.ids import OperationID,UseID,ValueID
from scar.ir.program.ids import BlockID,RegionID
from scar.ir.program.model import (DataValue,ReferenceValue,LocalBindingValue,StateVersionValue,
    LiteralOrigin,ExactLiteralOrigin,OperationResult,BlockArgument)
from scar.analysis.program_value_control import (ControlEntryScope,ControlNecessity,
    OccurrenceField,TypedRouteRefutation)


def _extended_unary(condition):
    """A known unary name with additional operands is an unknown signature."""
    return condition.operands!=()and(condition.domain,condition.name)in{
        ('canonical','SUCCESSOR_SELECTED'),('canonical','COMPLETION_SLOT'),
        ('canonical.binding','READ_NORMAL_REQUIRES_BOUND'),
        ('control.analysis','ORIGINAL_EDGE_REQUIRED_FOR_ENTRY_REACHABILITY')}


class FieldPrecision(str,Enum):
    EXACT='EXACT'
    CONDITIONAL='CONDITIONAL'
    CANDIDATE='CANDIDATE'
    UNKNOWN='UNKNOWN'
    NOT_APPLICABLE='NOT_APPLICABLE'


@dataclass(frozen=True,slots=True)
class ValueAlternative:
    value: PythonLiteral | Point | str
    conditions: tuple[Condition,...] = ()
    evidence: tuple[Evidence,...] = ()
    premises: tuple[Point,...] = ()
    strength: Strength = Strength.EXACT

    def __post_init__(self):
        if type(self.value)not in(PythonLiteral,Point,str):raise TypeError('value alternative must be an immutable literal, original reference point or builtin type name')
        for rows,kind in((self.conditions,Condition),(self.evidence,Evidence),(self.premises,Point)):
            if type(rows)is not tuple or any(type(item)is not kind for item in rows):raise TypeError('value proof requires typed immutable predicates, evidence and premises')
        if type(self.strength)is not Strength:raise TypeError('value proof needs DependencyStrength')


@dataclass(frozen=True,slots=True)
class ValueField:
    alternatives: tuple[ValueAlternative,...] = ()
    unknown_paths: tuple[Frontier,...] = ()
    applicable: bool = True

    def __post_init__(self):
        if (type(self.alternatives)is not tuple or any(type(a)is not ValueAlternative for a in self.alternatives)
                or type(self.unknown_paths)is not tuple or any(type(f)is not Frontier for f in self.unknown_paths)
                or type(self.applicable)is not bool):raise TypeError('value field requires typed alternatives, explicit unknown paths and applicability')

    @property
    def precision(self):
        if not self.applicable:return FieldPrecision.NOT_APPLICABLE
        if not self.alternatives:return FieldPrecision.UNKNOWN
        values={a.value for a in self.alternatives}
        if self.unknown_paths or len(values)>1 or any(a.strength is Strength.MAY for a in self.alternatives):
            return FieldPrecision.CANDIDATE
        if any(a.conditions for a in self.alternatives):return FieldPrecision.CONDITIONAL
        return FieldPrecision.EXACT


@dataclass(frozen=True,slots=True)
class ValueFields:
    """Reference *definition* provenance is not object/storage identity.

    Equal source Points may describe repeated factories/loop occurrences.
    No reference-source equality proves mutable contents unchanged. Operator
    source Points denote the checked normal-result0 field, not the op object.
    """
    reference_sources: ValueField = ValueField()
    scalar_constant: ValueField = ValueField()
    builtin_type: ValueField = ValueField()
    immutable_tuple: ValueField = ValueField()

    def __post_init__(self):
        if any(type(a.value)is not Point for a in self.reference_sources.alternatives):
            raise TypeError('reference provenance contains only original DependencyPoints')
        if any(type(a.value)is not PythonLiteral or a.value.kind not in _SCALARS for a in self.scalar_constant.alternatives):
            raise TypeError('scalar constant contains only supported immutable builtin scalar literals')
        if any(type(a.value)is not str or not a.value.startswith('builtins.')for a in self.builtin_type.alternatives):
            raise TypeError('builtin type field contains only builtin type names')
        if any(type(a.value)is not PythonLiteral or a.value.kind is not LiteralKind.TUPLE for a in self.immutable_tuple.alternatives):
            raise TypeError('immutable tuple content contains only recursively immutable builtin tuple literals')
        for alternative in self.immutable_tuple.alternatives:
            # Frozen dataclass syntax does not protect externally forged
            # children. Reuse the bounded, iterative literal grammar check:
            # only builtin scalar payloads and exact tuple children survive.
            _preflight_literal(alternative.value)


_NA=ValueField(applicable=False)
_TOKEN=ValueFields(_NA,_NA,_NA,_NA)
_SCALARS=frozenset((LiteralKind.NONE,LiteralKind.BOOL,LiteralKind.INT,LiteralKind.FLOAT64,
    LiteralKind.COMPLEX128,LiteralKind.STR,LiteralKind.STR_CODEPOINTS,LiteralKind.BYTES,LiteralKind.ELLIPSIS))
_FIELDS=('reference_sources','scalar_constant','builtin_type','immutable_tuple')


@dataclass(frozen=True,slots=True)
class BindingStateAlternative:
    """One possible binding state, independently of its Python payload."""
    state: BindingState
    conditions: tuple[Condition,...] = ()
    evidence: tuple[Evidence,...] = ()
    premises: tuple[Point,...] = ()
    strength: Strength = Strength.EXACT

    def __post_init__(self):
        if type(self.state)is not BindingState or self.state is BindingState.UNKNOWN:
            raise TypeError('binding alternatives assert only BOUND or UNBOUND; unknown paths are separate')
        for rows,kind in((self.conditions,Condition),(self.evidence,Evidence),(self.premises,Point)):
            if type(rows)is not tuple or any(type(item)is not kind for item in rows):
                raise TypeError('binding proof requires typed immutable predicates, evidence and premises')
        if type(self.strength)is not Strength:raise TypeError('binding proof needs DependencyStrength')


@dataclass(frozen=True,slots=True)
class BindingStateField:
    alternatives: tuple[BindingStateAlternative,...] = ()
    unknown_paths: tuple[Frontier,...] = ()
    applicable: bool = True

    def __post_init__(self):
        if (type(self.alternatives)is not tuple or any(type(a)is not BindingStateAlternative for a in self.alternatives)
                or type(self.unknown_paths)is not tuple or any(type(f)is not Frontier for f in self.unknown_paths)
                or type(self.applicable)is not bool):
            raise TypeError('binding field requires typed states, explicit unknown paths and applicability')

    @property
    def precision(self):
        if not self.applicable:return FieldPrecision.NOT_APPLICABLE
        if not self.alternatives:return FieldPrecision.UNKNOWN
        if self.unknown_paths or len({a.state for a in self.alternatives})>1 or any(
                a.strength is Strength.MAY for a in self.alternatives):return FieldPrecision.CANDIDATE
        if any(a.conditions for a in self.alternatives):return FieldPrecision.CONDITIONAL
        return FieldPrecision.EXACT


_NO_BINDING=BindingStateField(applicable=False)


@dataclass(frozen=True,slots=True)
class ValueFact:
    point: Point
    fields: ValueFields = ValueFields()
    binding_payload: ValueFields | None = None
    binding_state: BindingStateField = _NO_BINDING
    feasible: bool | None = None
    role: Literal['VALUE','LITERAL','NORMAL_RESULT_0','BINDING_PAYLOAD','NONVALUE','NO_NORMAL_RESULT'] = 'VALUE'
    occurrence: OccurrenceField = OccurrenceField()
    infeasibility: tuple[Evidence,...] = ()

    @property
    def reference_sources(self):return self.fields.reference_sources
    @property
    def scalar_constant(self):return self.fields.scalar_constant
    @property
    def builtin_type(self):return self.fields.builtin_type
    @property
    def immutable_tuple(self):return self.fields.immutable_tuple
    @property
    def binding_states(self):
        """Convenient known-state projection; it does not assert closure."""
        return tuple(sorted({a.state for a in self.binding_state.alternatives},key=lambda state:state.value))


@dataclass(frozen=True,slots=True)
class ValueAnalysisBudget:
    max_points: int = 512
    max_edges: int = 2048
    max_steps: int = 8192
    max_alternatives: int = 8
    max_conditions: int = 64
    max_int_bits: int = 4096
    max_bytes: int = 65536
    max_work: int = 1000000
    max_sequence_items: int = 4096
    max_literal_depth: int = 64
    max_compiled_units: int = 4
    max_compiled_bytes: int = 16777216

    def __post_init__(self):
        if any(type(getattr(self,k))is not int or getattr(self,k)<1 for k in self.__dataclass_fields__):
            raise ValueError('value-analysis bounds must be positive integers')


@dataclass(frozen=True,slots=True)
class BranchSelectionProof:
    """Stable normal-value fact for one original contextual BRANCH."""
    branch: Point
    predicate: Point
    selected_index: int
    alternatives: tuple[ValueAlternative,...]
    evidence: Evidence

    def __post_init__(self):
        if (type(self.branch)is not Point or type(self.branch.node)is not OperationID
                or type(self.predicate)is not Point or type(self.predicate.node)is not UseID
                or self.branch.namespace!=self.predicate.namespace or self.branch.context!=self.predicate.context
                or type(self.selected_index)is not int or self.selected_index not in(0,1)
                or type(self.alternatives)is not tuple or not self.alternatives
                or any(type(a)is not ValueAlternative or a.strength is not Strength.EXACT
                    or type(a.value)is not PythonLiteral or a.value.kind is not LiteralKind.BOOL
                    or a.value.payload is not(self.selected_index==0)
                    or any(_extended_unary(c)for c in a.conditions)for a in self.alternatives)
                or type(self.evidence)is not Evidence):
            raise TypeError('branch proof needs an original branch/predicate context and stable builtin bool alternatives')


@dataclass(frozen=True,slots=True)
class BindingReadProof:
    read: Point
    binding: Point
    condition: Condition
    alternatives: tuple[BindingStateAlternative,...]
    evidence: Evidence

    def __post_init__(self):
        if (type(self.read)is not Point or type(self.read.node)is not OperationID
                or type(self.binding)is not Point or type(self.binding.node)is not UseID
                or self.read.namespace!=self.binding.namespace or self.read.context!=self.binding.context
                or type(self.condition)is not Condition or self.condition.subject!=self.read
                or self.condition.domain!='canonical.binding' or self.condition.name!='READ_NORMAL_REQUIRES_BOUND'
                or self.condition.operands!=()or self.condition.index is not None
                or type(self.alternatives)is not tuple or not self.alternatives
                or any(type(a)is not BindingStateAlternative or a.state is not BindingState.BOUND
                    or a.strength is not Strength.EXACT or any(_extended_unary(c)for c in a.conditions)
                    for a in self.alternatives)
                or type(self.evidence)is not Evidence):
            raise TypeError('binding-read proof needs the original read/input scope and complete BOUND alternatives')


@dataclass(frozen=True,slots=True)
class ValueAnalysisResult:
    roots: tuple[Point,...]
    facts: tuple[ValueFact,...]
    edges: tuple[DependencyEdge,...]
    frontiers: tuple[Frontier,...]
    usage: dict[str,int]
    exhausted: bool
    branch_proofs: tuple[BranchSelectionProof,...] = ()
    binding_proofs: tuple[BindingReadProof,...] = ()
    worklist_stable: bool = False
    route_refutations: tuple[TypedRouteRefutation,...] = ()

    def for_point(self,point):
        return next((fact for fact in self.facts if fact.point==point),None)


class ProgramValueAnalysis:
    def __init__(self,session,graph=None,*,budget=None):
        self.session=session;self.graph=graph if graph is not None else session.graph()
        self.budget=budget or ValueAnalysisBudget()
        if type(self.budget)is not ValueAnalysisBudget:raise TypeError('expected ValueAnalysisBudget')
        self._facts={};self._incoming={};self._dependents=defaultdict(set);self._frontiers={}
        self._operators={};self._roles={};self._usage={'points':0,'edges':0,'steps':0,'work':0,'output_bytes':0}
        self._widened=set();self._exhausted=True
        self._worklist_stable=False
        self._evaluations={}
        self._point_unknown=defaultdict(tuple)
        self._unsettled={}
        self._compiled_units=OrderedDict();self._constant_tables={};self._code_literals={}
        self._compiled_bytes=0
        self._branch_conditions={};self._branch_proofs={}
        self._binding_guards={};self._binding_proofs={}
        self._truth_tables={};self._truth_contracts={}
        self._control_inputs={};self._control_unknown=defaultdict(tuple);self._entry_scopes={}
        self._point_refutations={};self._route_refutations={};self._jump_proofs={}
        self._refuted_inputs=defaultdict(list)

    def _note(self,point,kind,detail):
        item=Frontier(point,kind,detail);self._frontiers[item]=item
        return item

    def _value(self,point):
        index=self.session.index(point.namespace)
        node=point.node
        if type(node)is UseID:node=index.use_site(node).use.value
        return index.values.get(node),index

    def _control_owner(self,point):
        index=self.session.index(point.namespace);node=point.node
        if type(node)in(OperationID,BlockID):return point
        if type(node)is UseID:return Point(point.namespace,index.use_site(node).operation,point.context)
        if type(node)is ValueID:
            origin=index.values[node].origin
            if type(origin)is OperationResult:return Point(point.namespace,origin.operation,point.context)
            if type(origin)is BlockArgument:return Point(point.namespace,origin.block,point.context)
        return None

    def _entry_scope(self,point):
        index=self.session.index(point.namespace)
        block=point.node if type(point.node)is BlockID else index._operation_blocks.get(point.node)
        region=index._blocks.get(block)
        if region is None:return None
        key=point.namespace,region,point.context
        if key in self._entry_scopes:return self._entry_scopes[key]
        original=index.regions[region];blocks={b.id for b in original.blocks};graph=index.graph
        opaque=(point.context is None or any(port.block in blocks and port.block!=original.entry for port in graph.control_ports)
            or any(row.region==region for row in graph.resumable_bodies)
            or any(row.region==region for row in graph.native_boundaries)
            or any(row.region==region or row.body==region for row in graph.driver_interfaces)
            or any(row.body==region for row in graph.resumable_creates))
        from scar.ir.program.model import TerminatorKind
        opaque|=any(index.operations[op].terminator is not None and index.operations[op].terminator.kind
            in(TerminatorKind.SUSPEND,TerminatorKind.BODY_DRIVE)for b in original.blocks for op in b.operations)
        anchors=(Point(point.namespace,region,point.context),Point(point.namespace,original.entry,point.context))
        sources=(point.namespace.graph,)
        if point.context:
            frame=point.context[-1]
            # This first adapter supports the original synchronous direct
            # region interface. A saved Python candidate frame is not by
            # itself a proof of synchronous body activation or entry scope.
            caller=self.session.index(frame.caller);operation=caller.operations.get(frame.operation)
            opaque|=(frame.target!=point.namespace or frame.caller!=point.namespace or frame.entry!=region
                or frame.callee_use is not None or operation is None or operation.callee!=region)
            anchors=(*anchors,Point(frame.caller,frame.operation,point.context[:-1]))
            sources=tuple(dict.fromkeys((*sources,frame.caller.graph)))
        else:opaque|=region!=point.namespace.root
        scope=None if opaque else ControlEntryScope(anchors[0],anchors[1],
            Evidence('SELECTED_ORIGINAL_REGION_ENTRY_SCOPE_V1',sources,anchors))
        self._entry_scopes[key]=scope
        return scope

    def _necessary_control(self,edge):
        if (edge.kind is not K.CONTROL or edge.strength is not Strength.EXACT
                or edge.source.namespace!=edge.target.namespace or edge.source.context!=edge.target.context
                or type(edge.source.node)is not OperationID or type(edge.target.node)not in(OperationID,BlockID)
                or not any(e.rule=='CFG_ENTRY_EDGE_DOMINANCE_CONTROL_NECESSITY_V1'for e in edge.evidence)):
            return None
        scope=self._entry_scope(edge.target)
        if scope is None:return None
        selectors=[c for c in edge.conditions if c.domain=='canonical'and c.name=='SUCCESSOR_SELECTED'
            and c.operands==()and c.subject==edge.source]
        qualifiers=[c for c in edge.conditions if c.domain=='control.analysis'
            and c.name=='ORIGINAL_EDGE_REQUIRED_FOR_ENTRY_REACHABILITY'and c.operands==()and c.subject==scope.region]
        operation=self.session.index(edge.source.namespace).operations[edge.source.node]
        if (len(selectors)!=1 or len(qualifiers)!=1 or len(edge.conditions)!=2 or operation.terminator is None
                or selectors[0].index is None or selectors[0].index>=len(operation.terminator.successors)):
            return None
        evidence=Evidence('ORIGINAL_ENTRY_EDGE_NECESSITY_V1',tuple(dict.fromkeys(
            source for row in edge.evidence for source in row.sources)),(edge.source,edge.target,scope.region,scope.entry))
        return ControlNecessity(selectors[0],scope,(edge,),evidence)

    def _join_occurrence(self,point,old,new):
        if not old.applicable:return new
        if not new.applicable:return old
        # Retain one original proof chain per necessary choice. Keeping the
        # shortest/first witness avoids exponential paths and cyclic growth.
        rows={}
        for row in(*old.requirements,*new.requirements):
            key=row.choice,row.scope.region
            if key not in rows:rows[key]=row
        unknown=tuple(dict.fromkeys((*old.unknown_paths,*new.unknown_paths)))
        if len(rows)>self.budget.max_conditions:
            unknown=tuple(dict.fromkeys((*unknown,self._note(point,'CONTROL_REQUIREMENT_BUDGET',
                'Additional original necessary choices exceed the finite requirement domain.'))))
        return OccurrenceField(tuple(rows.values())[:self.budget.max_conditions],unknown,True)

    def _compute_occurrence(self,point):
        owner=self._control_owner(point)
        if owner is None:return OccurrenceField()
        result=OccurrenceField(unknown_paths=self._control_unknown[point],applicable=True)
        for edge in self._control_inputs.get(point,()):
            if edge.source not in self._facts:continue
            source=self._facts[edge.source].occurrence
            rows=[]
            if edge.kind is K.CONTROL:
                direct=self._necessary_control(edge)
                if direct is None:continue
                rows.append(direct)
            for requirement in source.requirements:
                if requirement.chain[-1].target!=edge.source:continue
                chain=(*requirement.chain,edge)
                if edge in requirement.chain:continue
                rows.append(replace(requirement,chain=chain,evidence=Evidence(
                    'ORIGINAL_CONTROL_NECESSITY_CHAIN_V1',tuple(dict.fromkeys(
                        (*requirement.evidence.sources,*(s for row in edge.evidence for s in row.sources)))),
                    (requirement.choice.subject,point,requirement.scope.region,edge.source))))
            result=self._join_occurrence(point,result,OccurrenceField(tuple(rows),source.unknown_paths,True))
        return result

    def _discover_control(self,point,pending,edges):
        owner=self._control_owner(point)
        if owner is None:self._control_inputs[point]=();return
        if owner==point:
            neighborhood=self.graph.incoming(point,kinds=(K.CONTROL,))
        else:
            value=self.session.index(point.namespace).values.get(point.node)
            kind=(K.RESULT if value is not None and type(value.origin)is OperationResult
                and type(value)is not StateVersionValue else K.STATE_OUTPUT if value is not None
                and type(value.origin)is OperationResult else K.CONTAINS)
            neighborhood=self.graph.incoming(point,kinds=(kind,))
        self._exhausted&=neighborhood.enumerated
        self._frontiers.update((f,f)for f in neighborhood.frontiers)
        notes=[];inputs=[]
        if not neighborhood.enumerated:
            notes.append(self._note(point,'CONTROL_RELATION_ENUMERATION_OPEN',
                'Additional control/ownership relations were not enumerated; no absence-of-path claim is made.'))
        if owner==point and self._entry_scope(point)is None:
            notes.append(self._note(point,'CONTROL_ENTRY_SCOPE_OPEN',
                'Original-entry reachability is not established for this context/native/resumption/external-entry scope.'))
        for edge in neighborhood.edges:
            if edge not in edges and len(edges)>=self.budget.max_edges:
                notes.append(self._note(point,'CONTROL_DISCOVERY_BUDGET','Further original control inputs remain unvisited.'))
                self._exhausted=False;break
            edges[edge]=edge
            relevant=(self._necessary_control(edge)is not None if owner==point else
                edge.source==owner and edge.target==point and edge.strength is Strength.EXACT)
            if relevant:
                inputs.append(edge);pending.append(edge.source);self._dependents[edge.source].add(point)
        if owner!=point and not inputs:
            notes.append(self._note(point,'CONTROL_OWNER_INTERFACE_OPEN','The original occurrence owner interface was not supplied.'))
        self._control_inputs[point]=tuple(inputs)
        self._control_unknown[point]=tuple(dict.fromkeys(notes))

    def _evaluation_budget(self):
        from scar.analysis.constants_v2 import EvaluationBudget
        return EvaluationBudget(max_int_bits=self.budget.max_int_bits,max_bytes=self.budget.max_bytes,
            max_work=self.budget.max_work,max_total_output_bytes=self.budget.max_bytes*16,
            max_sequence_items=self.budget.max_sequence_items,max_literal_depth=self.budget.max_literal_depth)

    @staticmethod
    def _literal_size(literal,budget):
        from scar.analysis.constants_v2 import _literal_size
        # The legacy evaluator's envelope predates exact complex/codepoint
        # literal kinds. Keep its bounds and add their conservative payload
        # sizes without round-tripping the original exact bits/codepoints.
        size=_literal_size(literal,budget);extra=0;pending=[literal]
        while pending:
            item=pending.pop()
            if item.kind is LiteralKind.TUPLE:pending.extend(item.items)
            elif item.kind is LiteralKind.COMPLEX128:extra+=8
            elif item.kind is LiteralKind.STR_CODEPOINTS:extra+=max(0,len(item.payload)//2-8)
        if size.bytes+extra>budget.max_bytes:raise _BudgetExceeded('exact literal payload budget exceeded')
        return replace(size,bytes=size.bytes+extra)

    def _literal(self,point,literal,evidence,*,reference=False):
        self._literal_size(literal,self._evaluation_budget())
        alternative=ValueAlternative(literal,evidence=(evidence,))
        builtin=literal_builtin_type(literal)
        return ValueFields(ValueField((ValueAlternative(point,evidence=(evidence,)),))if reference else _NA,
            ValueField((alternative,))if literal.kind in _SCALARS else _NA,
            ValueField((replace(alternative,value=builtin.__module__+'.'+builtin.__qualname__),)),
            ValueField((alternative,))if literal.kind is LiteralKind.TUPLE else _NA)

    def _unknown(self,point,kind,detail):
        note=self._note(point,kind,detail);field=ValueField(unknown_paths=(note,))
        return ValueFields(field,field,field,field)

    def _compiled_constant(self,point,value):
        """Read an existing constant-table contract from static compile output.

        This never imports or executes the program. The original compiler
        declaration and code path must reproduce exactly; a separate guard
        keeps active runtime code identity unproved.
        """
        if type(value.origin)is not OperationResult or value.origin.index!=0:return None
        body=self.session.load(point.namespace)
        if not hasattr(body,'document'):return None
        table=self._constant_tables.get(point.namespace)
        if table is None:
            from scar.ir.record_codec import decode
            from scar.ir.program.source_language import CodeConstantSource
            from scar.analysis.static_namespace import protocol_kinds
            owner='module'if getattr(body,'module',None)is not None else'language'
            rows=(getattr(body,'module',None).constants if owner=='module'else
                tuple(decode(CodeConstantSource,row)for row in(body.document.get('language')or{}).get('constants',())))
            protocols=protocol_kinds(body.document)
            table={row.operation:(row,owner,n)for n,row in enumerate(rows)
                if protocols.get(row.operation)=='READ_CODE_CONSTANT'}
            self._constant_tables[point.namespace]=table
        selected=table.get(value.origin.operation)
        if selected is None:return None
        row,owner,ordinal=selected;cache_key=point.namespace,value.id
        literal=self._code_literals.get(cache_key)
        if literal is None:
            from pathlib import Path
            import dis,json
            from scar.ir.record_codec import encode
            from scar.analysis.program_lowering import PreparedSource
            from scar.analysis.static_compilation import compile_source_unit
            from scar.ir.semantics_v2 import SourceSemanticsGraph
            compilation=body.document.get('static_compilation')
            if type(compilation)is not dict or compilation.get('evidence_kind')!='SOURCE_COMPILATION':
                return self._unknown(point,'CODE_CONSTANT_PROVENANCE_OPEN','Constant-table read lacks its original static compiler declaration; runtime code is not substituted.')
            tree,semantic,text=self.session.source_context(body)
            key=(body.metadata.source.path,body.metadata.source.fingerprint,body.unit['namespace_root'],
                json.dumps(compilation.get('compiler'),sort_keys=True))
            cached_unit=self._compiled_units.get(key)
            if cached_unit is None:
                if len(text)>self.budget.max_compiled_bytes:raise _BudgetExceeded('compiler source exceeds its byte budget')
                source_bytes=len(text.encode('utf-8'))
                if source_bytes>self.budget.max_compiled_bytes:raise _BudgetExceeded('compiler source exceeds its byte budget')
                semantics=SourceSemanticsGraph.from_dict(self.session.read(body.unit['artifacts']['semantics']),semantic)
                # Compilation only consumes the original semantic/snapshot
                # and AST fields; it does not need another CFG or symbol walk.
                prepared=PreparedSource(Path(body.metadata.source.path),Path(body.unit['namespace_root']),
                    text,semantic,semantics,None,tree,{})
                from scar.analysis.static_compilation import StaticCompilationError
                try:compiled=compile_source_unit(prepared)
                except StaticCompilationError as error:
                    return self._unknown(point,'CODE_CONSTANT_PROVENANCE_OPEN',str(error))
                import sys
                from types import CodeType
                pending=[compiled.root_code];seen=set();size=source_bytes+len(compiled.entries)*256
                while pending:
                    item=pending.pop()
                    if id(item)in seen:continue
                    seen.add(id(item));size+=sys.getsizeof(item)
                    if size>self.budget.max_compiled_bytes:raise _BudgetExceeded('static compiler products exceed their byte budget')
                    if type(item)is CodeType:
                        pending.extend((item.co_code,item.co_consts,item.co_names,item.co_varnames,item.co_freevars,
                            item.co_cellvars,item.co_linetable,item.co_exceptiontable,item.co_filename,item.co_name,item.co_qualname))
                    elif type(item)in(tuple,frozenset):pending.extend(item)
                while self._compiled_units and(len(self._compiled_units)>=self.budget.max_compiled_units
                        or self._compiled_bytes+size>self.budget.max_compiled_bytes):
                    _,(_,released)=self._compiled_units.popitem(last=False);self._compiled_bytes-=released
                self._compiled_units[key]=(compiled,size);self._compiled_bytes+=size
                self._usage['compiled_cache_bytes']=self._compiled_bytes
            else:compiled=cached_unit[0]
            self._compiled_units.move_to_end(key)
            source_body=point.namespace.source_body
            evidence=(compiled.for_module(body.module.declaration.unit)if getattr(body,'module',None)is not None else
                compiled.for_definition(source_body.definition,source_body.source)if source_body is not None and source_body.source is not None else None)
            if evidence is None or encode(evidence.to_dict())!=compilation or row.code_key!=evidence.code_layout_key:
                return self._unknown(point,'CODE_CONSTANT_PROVENANCE_OPEN','Original source/compiler/code path does not reproduce this declared constant table.')
            if body.graph.frame_roots:
                from scar.ir.program.source_subjects import SourceCompilationFrameRoot
                scopes={scope.id:scope for scope in body.graph.control_scopes}
                roots=[root for root in body.graph.frame_roots if scopes[root.scope].region==value.region]
                if len(roots)!=1 or type(roots[0])is not SourceCompilationFrameRoot or roots[0].code!=evidence.to_reference():
                    return self._unknown(point,'CODE_CONSTANT_PROVENANCE_OPEN','Constant table is not owned by this original source-compilation frame/root.')
            atom=semantic.source_atoms.get(row.source.atom_id)
            nodes=[n for n in ast.walk(tree)if atom is not None and type(n).__name__==atom.kind and
                (getattr(n,'lineno',None),getattr(n,'end_lineno',None),getattr(n,'col_offset',None),getattr(n,'end_col_offset',None))==
                (row.source.start_line,row.source.end_line,row.source.start_column,row.source.end_column)]
            if (atom is None or atom.reference!=row.source or row.source.path!=body.metadata.source.path
                    or row.source.fingerprint!=body.metadata.source.fingerprint or len(nodes)!=1
                    or len(row.constant_path)!=1):
                return self._unknown(point,'CODE_CONSTANT_PROVENANCE_OPEN','Constant source/atom/slot has no supported exact literal correspondence.')
            instructions=[i for i in dis.get_instructions(evidence.code,adaptive=False,show_caches=False)
                if i.opname=='LOAD_CONST'and i.arg==row.constant_path[0]and tuple(i.positions)==
                    (row.source.start_line,row.source.end_line,row.source.start_column,row.source.end_column)]
            if len(instructions)!=1 or type(instructions[0].argval)not in(tuple,str,bytes,int,bool,float,complex,type(None),type(Ellipsis)):
                return self._unknown(point,'CODE_CONSTANT_CONTENT_UNSUPPORTED','This exact compiler table slot is not a supported immutable builtin literal.')
            try:literal=PythonLiteral.from_python(instructions[0].argval,exact=True)
            except (TypeError,ValueError)as error:raise _Unsupported('compiler constant is outside bounded immutable content: '+str(error))from error
            size=self._literal_size(literal,self._evaluation_budget())
            from scar.analysis.constants_v2 import _reserve
            _reserve(size,self._usage,self._evaluation_budget());self._usage['output_bytes']+=size.bytes
            self._code_literals[cache_key]=literal
        source=replace(point.namespace.graph,pointer='#/'+owner+'/constants/'+str(ordinal))
        compilation_source=replace(point.namespace.graph,pointer='#/static_compilation')
        evidence=Evidence('SOURCE_COMPILED_IMMUTABLE_BUILTIN_V1',(source,compilation_source),(point,))
        fields=self._literal(point,literal,evidence,reference=type(value)is ReferenceValue)
        condition=Condition('scar.static-compilation','ACTIVE_CODE_MATCHES_SOURCE_COMPILATION',
            Point(point.namespace,value.origin.operation,point.context))
        return ValueFields(*(replace(getattr(fields,name),alternatives=tuple(replace(a,
            conditions=(*a.conditions,condition))for a in getattr(fields,name).alternatives))for name in _FIELDS))

    def _seed(self,point):
        value,index=self._value(point)
        evidence=Evidence('CANONICAL_IMMUTABLE_LITERAL_V1',(point.namespace.graph,),(point,))
        if type(point.node)is OperationID:
            from scar.ir.program.model import TerminatorKind
            operation=index.operations[point.node]
            if operation.terminator is not None and operation.terminator.kind is TerminatorKind.BRANCH:
                return ValueFact(point,_TOKEN,role='NONVALUE')
            if any(read.operation==point.node and read.normal_result is None for read in index.graph.binding_reads):
                return ValueFact(point,_TOKEN,feasible=False,role='NO_NORMAL_RESULT')
            return ValueFact(point,role='NORMAL_RESULT_0')
        if type(value)is LocalBindingValue:
            definition=next(((n,b)for n,b in enumerate(index.graph.binding_definitions)if b.value==value.id),None)
            state=BindingStateField()
            payload=ValueFields()
            # A Use receives its state through the original VALUE_USE edge;
            # its source definition is not a shortcut around that interface.
            if type(point.node)is ValueID and definition is not None:
                ordinal,definition=definition
                if definition.state is BindingState.UNKNOWN:
                    payload=self._unknown(point,'LOCAL_BINDING_PAYLOAD_OPEN','UNKNOWN update does not retain its previous payload.')
                    state=BindingStateField(unknown_paths=(self._note(point,'LOCAL_BINDING_STATE_OPEN',
                        'An UNKNOWN binding update asserts neither BOUND nor UNBOUND; its previous token is not an unchanged-state proof.'),))
                else:
                    source=replace(point.namespace.graph,pointer=point.namespace.graph.pointer.rstrip('/')+'/binding_definitions/'+str(ordinal))
                    evidence=Evidence('CANONICAL_BINDING_DEFINITION_STATE_V1',(source,),(point,))
                    state=BindingStateField((BindingStateAlternative(definition.state,evidence=(evidence,)),))
                    if definition.state is BindingState.UNBOUND:payload=_TOKEN
            return ValueFact(point,_TOKEN,payload,state,role='BINDING_PAYLOAD')
        if type(value)is StateVersionValue or value is None:
            return ValueFact(point,_TOKEN,role='NONVALUE')
        if type(point.node)is ValueID:
            literal=(PythonLiteral.from_python(value.origin.value,exact=True)if type(value.origin)is LiteralOrigin
                else value.origin.literal if type(value.origin)is ExactLiteralOrigin else None)
            if literal is not None:
                try:return ValueFact(point,self._literal(point,literal,evidence,reference=type(value)is ReferenceValue),feasible=True,role='LITERAL')
                except (ValueError,TypeError,OverflowError,_BudgetExceeded,_Unsupported)as error:
                    return ValueFact(point,self._unknown(point,'LITERAL_FIELD_BUDGET',str(error)))
            for evaluation in index.graph.literal_evaluations:
                from scar.ir.program.literal_validation import literal_site
                resolved=literal_site(index.graph,evaluation.site)
                if resolved['result'].id==value.id and type(evaluation.literal)is PythonLiteral:
                    try:return ValueFact(point,self._literal(point,evaluation.literal,evidence,reference=type(value)is ReferenceValue),feasible=True,role='LITERAL')
                    except (ValueError,TypeError,OverflowError,_BudgetExceeded,_Unsupported)as error:
                        return ValueFact(point,self._unknown(point,'LITERAL_FIELD_BUDGET',str(error)))
            try:
                constant=self._compiled_constant(point,value)
                if constant is not None:return ValueFact(point,constant,feasible=True,role='LITERAL')
            except (_BudgetExceeded,_Unsupported)as error:
                return ValueFact(point,self._unknown(point,'CODE_CONSTANT_CONTENT_BUDGET',str(error)))
        if type(value)is DataValue and value.data_type in ('builtins.int','builtins.bool','builtins.float','builtins.str','builtins.bytes','builtins.complex','builtins.NoneType','builtins.tuple'):
            return ValueFact(point,ValueFields(reference_sources=_NA,
                scalar_constant=_NA if value.data_type=='builtins.tuple'else ValueField(),
                immutable_tuple=ValueField()if value.data_type=='builtins.tuple'else _NA,
                builtin_type=ValueField((ValueAlternative(value.data_type,evidence=(evidence,)),))))
        if type(value)is DataValue:return ValueFact(point,ValueFields(reference_sources=_NA))
        return ValueFact(point)

    def _join_field(self,point,name,old,new):
        if not old.applicable or not new.applicable:
            if not old.applicable and not new.applicable:return old
            known=new if old.applicable is False else old
            if not known.alternatives and not known.unknown_paths:return _NA
            gap=self._note(point,'FIELD_APPLICABILITY_ALTERNATIVE',name+' also has a nonapplicable path; scalar/object alternatives are not conflated.')
            return replace(known,unknown_paths=tuple(dict.fromkeys((*known.unknown_paths,gap))))
        alternatives={}
        for item in (*old.alternatives,*new.alternatives):
            key=item.value,frozenset(item.conditions),item.strength
            previous=alternatives.get(key)
            if previous is None:alternatives[key]=item
            else:alternatives[key]=replace(previous,evidence=tuple(dict.fromkeys((*previous.evidence,*item.evidence))),
                premises=tuple(dict.fromkeys((*previous.premises,*item.premises))))
        unknown=tuple(dict.fromkeys((*old.unknown_paths,*new.unknown_paths)))
        if len(alternatives)>self.budget.max_alternatives:
            unknown=tuple(dict.fromkeys((*unknown,self._note(point,'VALUE_FIELD_WIDENED',name+' exceeded its finite alternative bound; remaining paths stay unknown.'))))
            self._widened.add((point,name))
        return ValueField(tuple(alternatives.values())[:self.budget.max_alternatives],unknown)

    def _join(self,point,old,new,prefix=''):
        return ValueFields(*(self._join_field(point,prefix+name,getattr(old,name),getattr(new,name))
            for name in _FIELDS))

    def _join_binding(self,point,old,new):
        if not old.applicable:return new
        if not new.applicable:return old
        alternatives={}
        for item in (*old.alternatives,*new.alternatives):
            key=item.state,frozenset(item.conditions),item.strength
            previous=alternatives.get(key)
            if previous is None:alternatives[key]=item
            else:alternatives[key]=replace(previous,evidence=tuple(dict.fromkeys((*previous.evidence,*item.evidence))),
                premises=tuple(dict.fromkeys((*previous.premises,*item.premises))))
        unknown=tuple(dict.fromkeys((*old.unknown_paths,*new.unknown_paths)))
        if len(alternatives)>self.budget.max_alternatives:
            unknown=tuple(dict.fromkeys((*unknown,self._note(point,'BINDING_STATE_WIDENED',
                'Binding-state alternatives exceed the finite proof bound; remaining paths stay unknown.'))))
        return BindingStateField(tuple(alternatives.values())[:self.budget.max_alternatives],unknown)

    def _transfer_binding(self,field,edge):
        if not field.applicable:
            return BindingStateField(unknown_paths=(self._note(edge.target,'BINDING_SOURCE_NOT_TOKEN',
                'An input to the original binding-token interface has no binding-state proof.'),))
        alternatives=[];unknown=list(field.unknown_paths)
        for item in field.alternatives:
            conditions=tuple(dict.fromkeys((*item.conditions,*edge.conditions)))
            if len(conditions)>self.budget.max_conditions:
                unknown.append(self._note(edge.target,'BINDING_CONDITION_BUDGET',
                    'Binding-state guards exceed the explicit condition budget.'));continue
            strength=Strength.MAY if edge.strength is Strength.MAY or item.strength is Strength.MAY else Strength.EXACT
            proofs=tuple(proof.evidence for proof in self._edge_branch_proofs(edge))
            alternatives.append(BindingStateAlternative(item.state,conditions,
                tuple(dict.fromkeys((*item.evidence,*edge.evidence,*proofs))),
                tuple(dict.fromkeys((*item.premises,edge.source))),strength))
        if edge.strength is Strength.MAY:
            unknown.append(self._note(edge.target,'MAY_BINDING_STATE_OPEN',
                'A may-dependence binding source does not close other possible states.'))
        return BindingStateField(tuple(alternatives),tuple(dict.fromkeys(unknown)))

    def _binding_input(self,condition):
        if (condition.domain!='canonical.binding' or condition.name!='READ_NORMAL_REQUIRES_BOUND'
                or condition.operands!=()or condition.index is not None or condition.subject is None
                or type(condition.subject.node)is not OperationID):return None
        read=condition.subject
        index=self.session.index(read.namespace)
        rows=[row for row in index.graph.binding_reads if row.operation==read.node and row.normal_result is not None]
        if len(rows)!=1:return None
        row=rows[0]
        value=index.values.get(index.use_site(row.binding).use.value)
        if type(value)is not LocalBindingValue:return None
        result=Point(read.namespace,row.normal_result,read.context)
        binding=Point(read.namespace,row.binding,read.context)
        self._binding_guards[condition]=(binding,result)
        return binding,result

    def _condition_evidence(self,condition):
        if condition.operands!=():return None
        prior=(self._branch_proofs.get(condition.subject)if condition.domain=='canonical'
            and condition.name=='SUCCESSOR_SELECTED'else None)
        if prior is not None and condition.index==prior.selected_index:return prior.evidence
        binding=self._binding_proofs.get(condition)
        if binding is not None:return binding.evidence
        if (condition.domain=='canonical'and condition.name=='SUCCESSOR_SELECTED'
                and condition.subject is not None and type(condition.subject.node)is OperationID):
            from scar.ir.program.model import TerminatorKind
            operation=self.session.index(condition.subject.namespace).operations[condition.subject.node]
            term=operation.terminator
            if term is not None and term.kind is TerminatorKind.JUMP and len(term.successors)==1 and condition.index==0:
                evidence=self._jump_proofs.get(condition)
                if evidence is None:
                    evidence=Evidence('ORIGINAL_SINGLE_SUCCESSOR_JUMP_ROUTE_PREMISE_V1',
                        (condition.subject.namespace.graph,),(condition.subject,
                            Point(condition.subject.namespace,term.successors[0].block,condition.subject.context)))
                    self._jump_proofs[condition]=evidence
                return evidence
        return None

    def _value_route(self,edge):
        if (edge.kind is K.RESULT and type(edge.source.node)is OperationID
                and self._operator(edge.source)is not None):
            # Operation facts describe normal result0, not an exception or
            # every completion slot of that same producer.
            return self._normal_result_zero(edge.target,edge)
        return (edge.kind in(K.VALUE_USE,K.ARGUMENT,K.COMPLETION,K.STATE_VALUE,K.ENVIRONMENT,K.BLOCK_ARGUMENT,
                K.BINDING_PAYLOAD,K.BINDING_READ)and edge.meaning in(M.VALUE,M.REFERENCE,M.BINDING))

    def _all_routes_refuted(self,point):
        """Close only a complete original family of normal value ports."""
        if self._point_unknown.get(point):return None
        value,index=self._value(point);incoming=self._incoming.get(point,())
        suppliers=[e for e in incoming if self._value_route(e)]
        if not suppliers or any(e.strength is Strength.MAY for e in suppliers):return None
        selected=None
        if type(point.node)is UseID:
            original=index.use_site(point.node).use
            matches=[e for e in suppliers if e.kind is K.VALUE_USE
                and e.source==Point(point.namespace,original.value,point.context)]
            if len(matches)==1 and suppliers==matches:selected=matches
        elif type(point.node)is ValueID:
            reads=[r for r in index.graph.binding_reads if r.normal_result==point.node]
            if len(reads)==1:
                matches=[e for e in suppliers if e.kind is K.BINDING_READ and
                    e.source==Point(point.namespace,reads[0].binding,point.context)]
                if len(matches)==1 and suppliers==matches:selected=matches
            elif type(value.origin)is BlockArgument and all(e.kind is K.BLOCK_ARGUMENT for e in suppliers):
                if self._entry_scope(Point(point.namespace,value.origin.block,point.context))is None:return None
                expected=set()
                for operation in index.graph.operations:
                    if operation.terminator is None:continue
                    for ordinal,successor in enumerate(operation.terminator.successors):
                        if successor.block!=value.origin.block:continue
                        actual=successor.arguments[value.origin.index]
                        if type(actual)is not UseID:return None
                        expected.add((Point(point.namespace,actual,point.context),Condition('canonical',
                            'SUCCESSOR_SELECTED',Point(point.namespace,operation.id,point.context),ordinal)))
                observed={(e.source,c)for e in suppliers for c in e.conditions if c.domain=='canonical'
                    and c.name=='SUCCESSOR_SELECTED'and c.operands==()}
                if expected and expected==observed and len(suppliers)==len(expected):selected=suppliers
            elif type(value.origin)is BlockArgument and point.context and all(e.kind is K.ARGUMENT for e in suppliers):
                frame=point.context[-1];operation=index.operations.get(frame.operation)
                if (frame.caller==point.namespace and frame.target==point.namespace and frame.entry==value.region
                        and operation is not None and operation.callee==value.region
                        and value.origin.block==index.regions[value.region].entry):
                    arguments=operation.invoke_arguments if operation.terminator is not None else operation.call_arguments
                    if value.origin.index<len(arguments):
                        expected=Point(point.namespace,arguments[value.origin.index],point.context[:-1])
                        matches=[e for e in suppliers if e.source==expected]
                        if len(matches)==1 and matches==suppliers:selected=matches
            if selected is None:
                producers=[e for e in incoming if e.kind is K.RESULT and type(e.source.node)is OperationID]
                if len(producers)==1:
                    if suppliers==producers and self._value_route(producers[0]):selected=producers
                    elif self._closed_local_result(point,producers[0]):
                        matches=[e for e in suppliers if e.kind is K.COMPLETION]
                        if matches and matches==suppliers:selected=matches
        if selected is None or any(edge not in self._route_refutations for edge in selected):return None
        evidence=Evidence('COMPLETE_ORIGINAL_VALUE_ROUTES_REFUTED_V1',(point.namespace.graph,),
            (point,*tuple(dict.fromkeys(e.source for e in selected))))
        return tuple(dict.fromkeys((evidence,*(self._route_refutations[e].evidence for e in selected))))

    def _freeze_refutations(self,edges):
        if not self._worklist_stable:return False
        changed=False
        for point,fact in self._facts.items():
            proofs=list(fact.infeasibility if fact.feasible is False else())
            for requirement in fact.occurrence.requirements:
                if requirement.choice.operands!=():continue
                branch=self._branch_proofs.get(requirement.choice.subject)
                if branch is None or branch.selected_index==requirement.choice.index:continue
                # Required edge traversals may belong to different iterations.
                # Compare only to one already stable, uniform contextual bool
                # proof; opposite static requirements alone are not a conflict.
                proofs.extend((requirement.evidence,requirement.scope.evidence,branch.evidence,
                    Evidence('NECESSARY_ENTRY_CHOICE_REFUTED_V1',(point.namespace.graph,),
                        (point,requirement.choice.subject,requirement.scope.region,requirement.scope.entry))))
            if proofs and point not in self._point_refutations:
                self._point_refutations[point]=tuple(dict.fromkeys(proofs));changed=True
        for edge in edges:
            if (not self._value_route(edge)or edge.strength is not Strength.EXACT
                    or edge in self._route_refutations):continue
            sources=self._point_refutations.get(edge.source,())
            if not sources:
                rejected=[self._branch_proofs[c.subject].evidence for c in edge.conditions
                    if c.domain=='canonical'and c.name=='SUCCESSOR_SELECTED'and c.subject in self._branch_proofs
                    and c.operands==()and c.index!=self._branch_proofs[c.subject].selected_index]
                if not rejected:continue
                sources=tuple(rejected)
            evidence=Evidence('ORIGINAL_VALUE_ROUTE_SOURCE_INFEASIBLE_V1',tuple(dict.fromkeys(
                (*[s for row in edge.evidence for s in row.sources],*[s for row in sources for s in row.sources]))),
                (edge.source,edge.target))
            proof=TypedRouteRefutation(edge,sources,evidence)
            self._route_refutations[edge]=proof;self._refuted_inputs[edge.target].append(proof);changed=True
        return changed

    def _binding_definite(self,field,state):
        return (field.applicable and bool(field.alternatives) and not field.unknown_paths
            and all(a.state is state and a.strength is Strength.EXACT
                and all(self._condition_evidence(c)is not None for c in a.conditions)
                for a in field.alternatives))

    def _transfer(self,fields,edge):
        def field(value):
            alternatives=[];unknown=list(value.unknown_paths)
            for item in value.alternatives:
                conditions=tuple(dict.fromkeys((*item.conditions,*edge.conditions)))
                if len(conditions)>self.budget.max_conditions:
                    unknown.append(self._note(edge.target,'VALUE_CONDITION_BUDGET','Guard alternatives exceed the explicit condition budget.'));continue
                strength=Strength.MAY if edge.strength is Strength.MAY or item.strength is Strength.MAY else Strength.EXACT
                proofs=tuple(proof.evidence for proof in self._edge_branch_proofs(edge))
                alternatives.append(ValueAlternative(item.value,conditions,tuple(dict.fromkeys((*item.evidence,*edge.evidence,*proofs))),
                    tuple(dict.fromkeys((*item.premises,edge.source))),strength))
            if edge.strength is Strength.MAY:
                unknown.append(self._note(edge.target,'MAY_VALUE_SOURCE_OPEN','A may-dependence source does not close the other possible value paths.'))
            # A possible source does not close the target's other possible
            # types. Keep that open path even when this source's particular
            # field is N/A; a declared target DataValue type is enforced later.
            return ValueField(tuple(alternatives),tuple(dict.fromkeys(unknown)),
                value.applicable or edge.strength is Strength.MAY)
        return ValueFields(*(field(getattr(fields,name))for name in _FIELDS))

    def _operator(self,point):
        if point in self._operators:return self._operators[point]
        body=self.session.load(point.namespace);operation=body.index.operations[point.node]
        truth=self._truth_contract(point)
        if truth is not None:
            result=('TRUTH',(truth[0],));self._operators[point]=result;return result
        sources=body.module if getattr(body,'module',None)is not None else getattr(body,'metadata',None)
        if sources is None:
            self._operators[point]=None;return None
        links=[l for l in sources.operation_links if l.operation==point.node]
        result=None
        if len(links)==1 and links[0].opcode is not None:
            opcode=links[0].opcode.name
            from scar.analysis.constants_v2 import _BINARY,_UNARY
            if opcode in _BINARY or opcode in _UNARY or opcode in('INDEX','BUILD_TUPLE'):
                tree,semantic,text=self.session.source_context(body);source=links[0].source
                atom=semantic.source_atoms.get(source.atom_id)
                if (source.path!=body.metadata.source.path or source.fingerprint!=body.metadata.source.fingerprint
                        or atom is None or atom.reference!=source):
                    self._operators[point]=None;return None
                nodes=[n for n in ast.walk(tree)if isinstance(n,(ast.BinOp,ast.UnaryOp,ast.Subscript,ast.Tuple))
                    and (n.lineno,n.end_lineno,n.col_offset,n.end_col_offset)==
                        (source.start_line,source.end_line,source.start_column,source.end_column)]
                if len(nodes)==1:
                    from scar.analysis.source_semantics_v2 import _BINARY as BINARY_AST,_UNARY as UNARY_AST
                    node=nodes[0]
                    if atom.kind!=type(node).__name__:
                        self._operators[point]=None;return None
                    if isinstance(node,ast.BinOp):
                        expected=BINARY_AST.get(type(node.op));children=(node.left,node.right);names=('left','right','operand')
                    elif isinstance(node,ast.UnaryOp):
                        expected=UNARY_AST.get(type(node.op));children=(node.operand,);names=('operand',)
                    elif isinstance(node,ast.Subscript)and isinstance(node.ctx,ast.Load)and not isinstance(node.slice,ast.Slice):
                        expected='INDEX';children=(node.value,node.slice);names=('receiver','index')
                    elif isinstance(node,ast.Tuple)and isinstance(node.ctx,ast.Load)and not any(isinstance(c,ast.Starred)for c in node.elts):
                        expected='BUILD_TUPLE';children=tuple(node.elts);names=('element',)
                    else:
                        self._operators[point]=None;return None
                    if expected==opcode:
                        roles={u.use:u for u in sources.use_links if u.operation==point.node}
                        if len(roles)!=sum(u.operation==point.node for u in sources.use_links):
                            self._operators[point]=None;return None
                        operands=[]
                        for use in operation.uses:
                            role=roles.get(use.id)
                            if role is not None and role.role in names:
                                operands.append(use.id)
                        expected_roles=(('receiver','index')if opcode=='INDEX'else('element',)*len(children))
                        precise_roles=(opcode not in('INDEX','BUILD_TUPLE')or
                            tuple(roles[use].role for use in operands)==expected_roles)
                        if len(operands)==len(children)and precise_roles and all(
                            (roles[use].source.start_line,roles[use].source.end_line,
                             roles[use].source.start_column,roles[use].source.end_column)==
                            (child.lineno,child.end_lineno,child.col_offset,child.end_col_offset)
                            and roles[use].source.path==source.path and roles[use].source.fingerprint==source.fingerprint
                            and(opcode not in('INDEX','BUILD_TUPLE')or roles[use].index==i)
                            for i,(use,child)in enumerate(zip(operands,children))):
                            result=opcode,tuple(operands)
        self._operators[point]=result
        return result

    def _truth_contract(self,point):
        """An original Python TRUTH interface, not a name/label heuristic."""
        if point in self._truth_contracts:return self._truth_contracts[point]
        body=self.session.load(point.namespace)
        if not hasattr(body,'document'):
            self._truth_contracts[point]=None;return None
        table=self._truth_tables.get(point.namespace)
        if table is None:
            from scar.ir.record_codec import decode
            from scar.ir.v2.common import SourceReference
            table=defaultdict(list)
            for key in('module','structured','class'):
                for row in(body.document.get(key)or{}).get('protocols',()):
                    if row['kind']=='TRUTH':
                        table[decode(OperationID,row['operation'])].append(decode(SourceReference,row['source']))
            self._truth_tables[point.namespace]=table
        declared=table.get(point.node,())
        if len(declared)!=1:
            self._truth_contracts[point]=None;return None
        from scar.ir.program.model import ExitKind,TerminatorKind,CompletionResult,ValueType,ValueKind,UseRole
        operation=body.index.operations[point.node];term=operation.terminator
        source=declared[0];sources=body.module if getattr(body,'module',None)is not None else body.metadata
        links=[l for l in sources.operation_links if l.operation==point.node]
        refs=[u for u in operation.uses if type(body.index.values[u.value])is ReferenceValue]
        worlds=[u for u in operation.uses if type(body.index.values[u.value])is StateVersionValue]
        result=None
        if (term is not None and term.kind is TerminatorKind.INVOKE and operation.callee is None
                and len(refs)==len(worlds)==1 and len(operation.uses)==2
                and refs[0].role is UseRole.REFERENCE and worlds[0].role is UseRole.STATE_CONTENT
                and tuple(operation.invoke_arguments)==tuple(u.id for u in operation.uses)
                and {c.kind for c in operation.completions}=={ExitKind.NORMAL,ExitKind.RAISE}
                and len(links)==1 and links[0].source==source):
            use_links=[u for u in sources.use_links if u.operation==point.node and u.use==refs[0].id]
            normal=[(n,e)for n,e in enumerate(term.successors)if e.kind is ExitKind.NORMAL]
            signature=next(c for c in operation.completions if c.kind is ExitKind.NORMAL)
            before=body.index.values[worlds[0].value]
            if (len(use_links)==1 and use_links[0].role=='protocol-input'and use_links[0].index==0
                    and use_links[0].source==source and len(normal)==1 and len(signature.types)==2
                    and type(signature.types[0])is ValueType and signature.types[0].kind is ValueKind.DATA
                    and signature.types[0].data_type=='builtins.bool'and type(signature.types[1])is ValueType
                    and signature.types[1].kind is ValueKind.STATE and signature.types[1].location==before.location):
                n,edge=normal[0];block=body.index._block_records[edge.block]
                outputs=[v for v,a in zip(block.arguments,edge.arguments)if type(a)is CompletionResult
                    and a.index==0 and type(body.index.values[v])is DataValue
                    and body.index.values[v].data_type=='builtins.bool']
                tree,semantic,text=self.session.source_context(body);atom=semantic.source_atoms.get(source.atom_id)
                nodes=[v for v in ast.walk(tree)if isinstance(v,ast.expr)and atom is not None and type(v).__name__==atom.kind
                    and(v.lineno,v.end_lineno,v.col_offset,v.end_col_offset)==
                        (source.start_line,source.end_line,source.start_column,source.end_column)]
                if (len(outputs)==1 and len(nodes)==1 and atom.reference==source
                        and source.path==body.metadata.source.path and source.fingerprint==body.metadata.source.fingerprint):
                    result=refs[0].id,worlds[0].id,n,outputs[0],source
        self._truth_contracts[point]=result
        return result

    @staticmethod
    def _literal_truth(literal):
        # Inspect only validated immutable builtin representations. No host
        # bool/len dispatch runs on a program reference or its elements.
        _preflight_literal(literal)
        kind=literal.kind
        if kind is LiteralKind.BOOL:return literal.payload
        if kind is LiteralKind.NONE:return False
        if kind is LiteralKind.INT:return literal.payload!='0'
        if kind is LiteralKind.FLOAT64:return int(literal.payload,16)&0x7fffffffffffffff!=0
        if kind is LiteralKind.COMPLEX128:
            return (int(literal.payload[:16],16)&0x7fffffffffffffff!=0
                or int(literal.payload[16:],16)&0x7fffffffffffffff!=0)
        if kind is LiteralKind.ELLIPSIS:return True
        if kind in(LiteralKind.STR,LiteralKind.STR_CODEPOINTS,LiteralKind.BYTES):return literal.payload!=''
        if kind is LiteralKind.TUPLE:return len(literal.items)!=0
        raise _Unsupported('no closed builtin truth rule for this literal kind')

    def _closed_local_result(self,point,producer):
        """Whether original synchronous region ports fully explain this slot.

        A saved may-target or a lone COMPLETION edge is insufficient. This
        accepts only the core's actual ``operation.callee`` plus every
        original normal exit Use in the exact direct-region call frame.
        It closes value routing, never effects, purity or state contents.
        """
        if (point.context is None or point.namespace!=producer.source.namespace
                or point.context!=producer.source.context):return False
        if self._point_unknown.get(point):return False
        index=self.session.index(point.namespace);operation=index.operations[producer.source.node]
        if operation.callee is None:return False
        region=index.regions.get(operation.callee)
        if region is None:return False
        from scar.ir.program.model import CompletionResult,ExitKind,TerminatorKind,value_type
        from scar.ir.program.native import ExitPortRef
        normal=[port for port in region.exits if port.kind is ExitKind.NORMAL]
        if len(normal)!=1:return False
        origin=index.values[point.node].origin
        if operation.terminator is None:
            if type(origin)is not OperationResult or origin.operation!=operation.id:return False
            slot=origin.index
            if slot>=len(operation.results)or operation.results[slot]!=point.node:return False
            arguments=operation.call_arguments
        elif operation.terminator.kind is TerminatorKind.INVOKE:
            if type(origin)is not BlockArgument:return False
            selected=[(n,edge,edge.arguments[origin.index])for n,edge in enumerate(operation.terminator.successors)
                if edge.kind is ExitKind.NORMAL and edge.block==origin.block and origin.index<len(edge.arguments)
                and type(edge.arguments[origin.index])is CompletionResult]
            if len(selected)!=1:return False
            successor,edge,actual=selected[0];slot=actual.index;arguments=operation.invoke_arguments
            signatures=[s for s in operation.completions if s.kind is ExitKind.NORMAL]
            if len(signatures)!=1 or signatures[0].types!=normal[0].types:return False
        else:return False
        if slot>=len(normal[0].types)or value_type(index.values[point.node])!=normal[0].types[slot]:return False
        formals=index.entry_arguments(operation.callee)
        if len(arguments)!=len(formals):return False
        for actual,formal in zip(arguments,formals):
            site=index.use_site(actual)
            if site.operation!=operation.id:return False
            before,after=value_type(index.values[site.use.value]),value_type(formal)
            if before!=after:return False
        terminals={site.use.id for site in index.exit_port_uses(ExitPortRef(operation.callee,normal[0].name,slot))}
        if not terminals:return False
        matched=set()
        for incoming in self._incoming[point]:
            if incoming.kind is not K.COMPLETION:continue
            context=incoming.source.context
            if (incoming.meaning is not M.VALUE or incoming.strength is not Strength.EXACT
                    or incoming.source.namespace!=point.namespace
                    or context is None or len(context)!=len(point.context)+1 or context[:-1]!=point.context):return False
            frame=context[-1]
            if (frame.caller!=point.namespace or frame.target!=point.namespace or frame.operation!=operation.id
                    or frame.entry!=operation.callee or frame.callee_use is not None
                    or frame.callee_value is not None or incoming.source.node not in terminals):return False
            if operation.terminator is not None and not any(c.domain=='canonical'and c.name=='SUCCESSOR_SELECTED'
                    and c.operands==()and c.subject==producer.source and c.index==successor for c in incoming.conditions):return False
            matched.add(incoming.source.node)
        return matched==terminals

    def _normal_result_zero(self,point,edge):
        """Route a checked operation's normal value, never exception slot 0."""
        if (point.namespace!=edge.source.namespace or point.context!=edge.source.context
                or type(point.node)is not ValueID):return False
        from scar.ir.program.model import CompletionResult,ExitKind,TerminatorKind
        index=self.session.index(point.namespace);operation=index.operations[edge.source.node]
        origin=index.values[point.node].origin
        if any(_extended_unary(c)and c.subject==edge.source for c in edge.conditions):return False
        slots=[c.index for c in edge.conditions if c.domain=='canonical'and c.name=='COMPLETION_SLOT'
            and c.operands==()and c.subject==edge.source]
        if slots not in([],[0]):return False
        if operation.terminator is None:
            return (type(origin)is OperationResult and origin.operation==operation.id and origin.index==0
                and len(operation.results)>0 and operation.results[0]==point.node)
        if operation.terminator.kind is not TerminatorKind.INVOKE or type(origin)is not BlockArgument:return False
        matches=[]
        for ordinal,successor in enumerate(operation.terminator.successors):
            if (successor.kind is ExitKind.NORMAL and successor.block==origin.block
                    and origin.index<len(successor.arguments)):
                actual=successor.arguments[origin.index]
                if type(actual)is CompletionResult and actual.index==0:matches.append(ordinal)
        if len(matches)!=1:return False
        choices=[c.index for c in edge.conditions if c.domain=='canonical'and c.name=='SUCCESSOR_SELECTED'
            and c.operands==()and c.subject==edge.source]
        return choices==matches

    @staticmethod
    def _content(fields):
        # Alternative content domains are disjoint fields, not separate
        # dependency paths. A scalar's nonapplicable tuple field adds no gap.
        parts=(fields.scalar_constant,fields.immutable_tuple)
        return ValueField(tuple(a for field in parts for a in field.alternatives),
            tuple(dict.fromkeys(gap for field in parts for gap in field.unknown_paths)))

    def _evaluate_operator(self,point,operator):
        from scar.analysis.constants_v2 import (_builtin,_python_value,_literal,
            _reserve,_work,_Size,ConstantRuntimeRequirement,_BudgetExceeded,_Unsupported)
        opcode,operands=operator
        parents=[Point(point.namespace,use,point.context)for use in operands]
        if any(p not in self._facts for p in parents):
            return self._unknown(point,'VALUE_OPERAND_UNVISITED','A checked original operand lies beyond the discovered graph scope.')
        fields=[self._content(self._facts[p].fields)for p in parents]
        unknown=tuple(dict.fromkeys(gap for field in fields for gap in field.unknown_paths))
        alternatives=[];tuples=[];types=[];references=[]
        contract=Evidence('CANONICAL_IMMUTABLE_BUILTIN_OPERATOR_V1',(point.namespace.graph,),(point,*parents))
        if opcode in('BUILD_TUPLE','TRUTH'):
            if opcode=='BUILD_TUPLE':references.append(ValueAlternative(point,evidence=(contract,)))
            types.append(ValueAlternative('builtins.tuple'if opcode=='BUILD_TUPLE'else'builtins.bool',evidence=(contract,)))
        if any(not field.alternatives for field in fields):
            if unknown:
                kind=('IMMUTABLE_TUPLE_ELEMENT_OPEN'if opcode=='BUILD_TUPLE'else
                    'IMMUTABLE_INDEX_KEY_OPEN'if opcode=='INDEX'and not fields[1].alternatives else
                    'IMMUTABLE_INDEX_RECEIVER_OPEN'if opcode=='INDEX'else
                    'BUILTIN_TRUTH_CONTENT_OPEN'if opcode=='TRUTH'else'BUILTIN_INPUT_CONTENT_OPEN')
                unknown=(*unknown,self._note(point,kind,'Original operand content is not a proved immutable builtin literal; no user protocol or mutable contents are evaluated.'))
            gap=ValueField(unknown_paths=unknown)
            return ValueFields(_NA if opcode=='TRUTH'else ValueField(tuple(references))if references else gap,
                _NA if opcode=='BUILD_TUPLE'else gap,ValueField(tuple(types))if types else gap,
                _NA if opcode=='TRUTH'else gap)
        budget=self._evaluation_budget()
        combinations=product(*(field.alternatives for field in fields))
        for number,items in enumerate(combinations):
            if number>=self.budget.max_alternatives:
                unknown=(*unknown,self._note(point,'BUILTIN_ALTERNATIVE_BUDGET','Exact builtin input combinations exceed the bounded evaluator scope.'));break
            literals=tuple(item.value for item in items)
            try:
                key=opcode,literals
                cached=self._evaluations.get(key)
                if cached is None:
                    sizes=tuple(self._literal_size(literal,budget)for literal in literals)
                    state={'work':self._usage['work'],'output_bytes':self._usage['output_bytes']}
                    if opcode=='TRUTH':
                        value=self._literal_truth(literals[0]);literal=PythonLiteral.from_python(value)
                        _reserve(_Size(8,0,1),state,budget);_work(1,state,budget);floating=False
                    elif opcode=='BUILD_TUPLE':
                        estimate=_Size(8*len(literals)+sum(s.bytes for s in sizes),
                            len(literals)+sum(s.items for s in sizes),1+max((s.depth for s in sizes),default=0),
                            max((s.bits for s in sizes),default=0))
                        _reserve(estimate,state,budget);_work(max(1,estimate.items),state,budget)
                        literal=PythonLiteral(LiteralKind.TUPLE,items=literals);floating=False
                    elif opcode=='INDEX'and literals[0].kind is LiteralKind.TUPLE:
                        if literals[1].kind not in(LiteralKind.INT,LiteralKind.BOOL):
                            raise _Unsupported('immutable tuple indexing currently supports exact builtin int/bool keys, not arbitrary __index__ or slices')
                        index=_python_value(literals[1]);sequence=literals[0].items
                        _work(1,state,budget)
                        if index < -len(sequence)or index>=len(sequence):raise IndexError('immutable tuple index is out of range')
                        literal=sequence[index];_reserve(self._literal_size(literal,budget),state,budget);floating=False
                    else:
                        values=tuple(_python_value(literal)for literal in literals)
                        value=_builtin(opcode,values,sizes,budget,state,literals)
                        literal=_literal(value);floating=type(value)is float and opcode!='INDEX'
                    size=self._literal_size(literal,budget);self._usage['work']=state['work'];self._usage['output_bytes']+=size.bytes
                    builtin=literal_builtin_type(literal);cached=literal,builtin.__module__+'.'+builtin.__qualname__,floating
                    self._evaluations[key]=cached
                literal,type_name,is_float=cached
                guards=tuple(dict.fromkeys((*[c for item in items for c in item.conditions],
                    *(()if opcode=='TRUTH'else(Condition.from_enum(ConstantRuntimeRequirement.BUILTIN_RUNTIME_MATCH),)),
                    *([Condition.from_enum(ConstantRuntimeRequirement.FLOATING_ENVIRONMENT_MATCH)]if is_float else[]))))
                if len(guards)>self.budget.max_conditions:
                    unknown=(*unknown,self._note(point,'VALUE_CONDITION_BUDGET','Builtin premise predicates exceed the finite guard bound.'));continue
                evidence=tuple(dict.fromkeys(e for item in items for e in item.evidence))
                anchors=(point,*parents)
                if opcode=='TRUTH':
                    truth=self._truth_contract(point)
                    anchors=(*anchors,Point(point.namespace,truth[1],point.context),Point(point.namespace,truth[3],point.context))
                evidence=(*evidence,Evidence('BOUNDED_BUILTIN_TRUTH_NORMAL_V1'if opcode=='TRUTH'else'BOUNDED_BUILTIN_SCALAR_V1',
                    (point.namespace.graph,),anchors))
                alternative=ValueAlternative(literal,guards,evidence,tuple(parents),
                    Strength.MAY if any(item.strength is Strength.MAY for item in items)else Strength.EXACT)
                (tuples if literal.kind is LiteralKind.TUPLE else alternatives).append(alternative)
                types.append(replace(alternative,value=type_name))
                if opcode!='TRUTH':references.append(replace(alternative,value=point))
            except (_BudgetExceeded,_Unsupported,ArithmeticError,LookupError,ValueError,TypeError)as error:
                kind=('IMMUTABLE_INDEX_OUT_OF_RANGE'if isinstance(error,IndexError)else
                    'IMMUTABLE_INDEX_KEY_UNSUPPORTED'if opcode=='INDEX'and isinstance(error,_Unsupported)else
                    'BUILTIN_TRUTH_CONTENT_UNSUPPORTED'if opcode=='TRUTH'else'BUILTIN_SCALAR_RULE_OPEN')
                unknown=(*unknown,self._note(point,kind,type(error).__name__+': '+str(error)))
        return ValueFields(reference_sources=_NA if opcode=='TRUTH'else ValueField(tuple(references),unknown),
            scalar_constant=_NA if opcode=='BUILD_TUPLE'or tuples and not alternatives and not unknown else ValueField(tuple(alternatives),unknown),
            builtin_type=ValueField(tuple(types))if opcode in('BUILD_TUPLE','TRUTH')else ValueField(tuple(types),unknown),
            immutable_tuple=_NA if opcode=='TRUTH'or alternatives and not tuples and not unknown else ValueField(tuple(tuples),unknown))

    def _branch_predicate(self,branch):
        if branch in self._branch_conditions:return self._branch_conditions[branch]
        if type(branch.node)is not OperationID:return None
        from scar.ir.program.model import TerminatorKind
        index=self.session.index(branch.namespace);operation=index.operations[branch.node]
        term=operation.terminator
        if term is None or term.kind is not TerminatorKind.BRANCH:return None
        use=index.use_site(term.condition)
        value=index.values[use.use.value]
        if use.operation!=operation.id or type(value)is not DataValue or value.data_type!='builtins.bool':
            raise ValueError('canonical BRANCH must retain its original builtin-bool condition Use')
        predicate=Point(branch.namespace,term.condition,branch.context)
        self._branch_conditions[branch]=predicate
        return predicate

    def _edge_branch_proofs(self,edge):
        return tuple(dict.fromkeys(self._branch_proofs[c.subject]for c in edge.conditions
            if c.domain=='canonical'and c.name=='SUCCESSOR_SELECTED'and c.operands==()and c.subject in self._branch_proofs))

    def _edge_selected(self,edge):
        return all(c.index==self._branch_proofs[c.subject].selected_index for c in edge.conditions
            if c.domain=='canonical'and c.name=='SUCCESSOR_SELECTED'and c.operands==()and c.subject in self._branch_proofs)

    def _necessary_normal_entry(self,condition,branch,predicate):
        """An original normal completion required to reach this exact branch.

        This is an entering-point premise. It does not make an INVOKE succeed
        or remove its exception edge, and does not accept a runtime guard.
        """
        if (condition.domain!='canonical'or condition.name!='SUCCESSOR_SELECTED'
                or condition.operands!=()or condition.subject is None or type(condition.subject.node)is not OperationID
                or condition.subject.namespace!=branch.namespace or condition.subject.context!=branch.context):return None
        producer=condition.subject;truth=self._truth_contract(producer)
        if truth is None or condition.index!=truth[2]:return None
        index=self.session.index(branch.namespace);block=index._operation_blocks[branch.node]
        if (predicate.namespace!=branch.namespace or predicate.context!=branch.context
                or predicate.node!=index.operations[branch.node].terminator.condition
                or index.use_site(predicate.node).operation!=branch.node):return None
        region=index._blocks[block]
        before=index.values[index.use_site(predicate.node).use.value]
        if (block==index.regions[region].entry or type(before.origin)is not BlockArgument
                or before.origin.block!=block or before.id!=truth[3]):return None
        predecessors=[(op.id,n)for op in index.graph.operations if op.terminator is not None
            for n,edge in enumerate(op.terminator.successors)if edge.block==block]
        if predecessors!=[(producer.node,truth[2])]:return None
        if (any(port.block==block for port in index.graph.control_ports)
                or any(row.region==region for row in index.graph.resumable_bodies)
                or any(row.region==region for row in index.graph.native_boundaries)
                or any(row.region==region or row.body==region for row in index.graph.driver_interfaces)
                or any(row.body==region for row in index.graph.resumable_creates)):
            return None
        return Evidence('BRANCH_ENTRY_REQUIRES_ORIGINAL_TRUTH_NORMAL_V1',(branch.namespace.graph,),
            (branch,predicate,producer,Point(branch.namespace,block,branch.context)))

    def _freeze_bindings(self):
        if not self._worklist_stable:return ()
        added=[]
        for condition,(binding,result)in self._binding_guards.items():
            if condition in self._binding_proofs or binding not in self._facts or binding.context is None:continue
            self.session.check()
            # Recheck the original read interface, not just a condition name
            # propagated by an unrelated provider or activation.
            if not any(edge.kind is K.BINDING_READ and edge.meaning is M.BINDING
                    and edge.source==binding and edge.target==result and condition in edge.conditions
                    and edge.strength is Strength.EXACT for edge in self._incoming.get(result,())):continue
            field=self._facts[binding].binding_state
            if self._facts[binding].feasible is False:continue
            if not self._binding_definite(field,BindingState.BOUND):continue
            alternatives=tuple(replace(a,evidence=tuple(dict.fromkeys((*a.evidence,
                *(self._condition_evidence(c)for c in a.conditions)))))for a in field.alternatives)
            value=self.session.index(binding.namespace).use_site(binding.node).use.value
            evidence=Evidence('READ_BINDING_DEFINITELY_BOUND_V1',(binding.namespace.graph,),
                (condition.subject,binding,Point(binding.namespace,value,binding.context)))
            added.append(BindingReadProof(condition.subject,binding,condition,alternatives,evidence))
        return tuple(added)

    def _freeze_branches(self):
        # A stopped worklist is not a closed predicate. In particular, an
        # early singleton can still acquire another value through a backedge.
        if not self._worklist_stable:return ()
        added=[]
        for branch,predicate in self._branch_conditions.items():
            if branch in self._branch_proofs or predicate not in self._facts:continue
            # BRANCH is a NONVALUE point: an incomplete predicate interface
            # cannot be represented by opening its N/A scalar fields.
            if self._point_unknown.get(branch):continue
            inputs=[edge for edge in self._incoming.get(branch,())if edge.kind is K.CONTROL_CONDITION]
            if (len(inputs)!=1 or inputs[0].source!=predicate or inputs[0].target!=branch
                    or inputs[0].strength is not Strength.EXACT
                    or any(_extended_unary(c)for c in inputs[0].conditions)):continue
            fact=self._facts[predicate];field=fact.scalar_constant
            if (fact.feasible is False or not field.applicable or not field.alternatives or field.unknown_paths
                    or any(a.strength is not Strength.EXACT or type(a.value)is not PythonLiteral
                        or a.value.kind is not LiteralKind.BOOL or type(a.value.payload)is not bool
                        for a in field.alternatives)):
                continue
            values={a.value.payload for a in field.alternatives}
            if len(values)!=1:continue
            # Do not silently accept runtime/dispatch/code-instance guards.
            # An earlier frozen BRANCH can justify its own selected edge;
            # all other predicate scopes remain conditional and unfiltered.
            alternatives=[];closed=True
            for alternative in field.alternatives:
                premises=[]
                for condition in alternative.conditions:
                    proven=self._condition_evidence(condition)
                    if proven is not None:premises.append(proven);continue
                    necessary=self._necessary_normal_entry(condition,branch,predicate)
                    if necessary is None:closed=False;break
                    premises.append(necessary)
                if not closed:break
                alternatives.append(replace(alternative,evidence=tuple(dict.fromkeys((*alternative.evidence,*premises)))))
            if not closed:
                self._note(branch,'BRANCH_PREDICATE_GUARDS_OPEN',
                    'A builtin-bool candidate retains undischarged original guards; both value paths remain.')
                continue
            selected=0 if next(iter(values))else 1
            evidence=Evidence('STABLE_BUILTIN_BOOL_SELECTS_SUCCESSOR_'+str(selected)+'_V1',
                (branch.namespace.graph,),(branch,predicate))
            added.append(BranchSelectionProof(branch,predicate,selected,tuple(alternatives),evidence))
        return tuple(added)

    def _compute(self,point):
        seed=replace(self._seed(point),occurrence=self._compute_occurrence(point))
        impossible=self._point_refutations.get(point)or self._all_routes_refuted(point)
        if impossible:return replace(seed,fields=_TOKEN,feasible=False,infeasibility=impossible)
        fields=seed.fields;payload=seed.binding_payload;binding_state=seed.binding_state
        if seed.role in('LITERAL','NO_NORMAL_RESULT'):return seed
        possible=[];read_state=_NO_BINDING;normal_open=bool(self._point_unknown.get(point))
        operator=self._operator(point)if type(point.node)is OperationID else None
        if operator is not None:
            operands=[Point(point.namespace,u,point.context)for u in operator[1]]
            absent=[p for p in operands if p in self._facts and self._facts[p].feasible is False]
            if absent:
                evidence=Evidence('CHECKED_NORMAL_OPERATOR_REQUIRES_ORIGINAL_OPERANDS_V1',
                    (point.namespace.graph,),(point,*absent))
                return replace(seed,fields=_TOKEN,feasible=False,infeasibility=(evidence,))
            fields=self._join(point,fields,self._evaluate_operator(point,operator))
        for edge in self._incoming[point]:
            if not self._edge_selected(edge)or edge in self._route_refutations:continue
            parent=self._facts[edge.source]
            if edge.strength is Strength.MAY:normal_open=True
            if edge.kind is K.BINDING_PAYLOAD:
                payload=self._join(point,payload or ValueFields(),self._transfer(parent.fields,edge),'binding_payload.')
            elif edge.kind is K.BINDING_READ:
                # The read's own BOUND guard is not an assumption usable to
                # establish its input state or prove its NORMAL impossible.
                state_edge=replace(edge,conditions=tuple(c for c in edge.conditions
                    if self._binding_guards.get(c)!=(edge.source,edge.target)))
                read_state=self._join_binding(point,read_state,self._transfer_binding(parent.binding_state,state_edge))
                if parent.binding_payload is not None:
                    fields=self._join(point,fields,self._transfer(parent.binding_payload,edge));possible.append(parent.feasible)
            elif edge.kind in (K.VALUE_USE,K.ARGUMENT,K.COMPLETION,K.STATE_VALUE,K.ENVIRONMENT,K.BLOCK_ARGUMENT)and edge.meaning in(M.VALUE,M.REFERENCE,M.BINDING):
                if parent.binding_payload is not None:
                    payload=self._join(point,payload or ValueFields(),self._transfer(parent.binding_payload,edge),'binding_payload.')
                    if binding_state.applicable:
                        binding_state=self._join_binding(point,binding_state,self._transfer_binding(parent.binding_state,edge))
                else:fields=self._join(point,fields,self._transfer(parent.fields,edge))
                possible.append(parent.feasible)
            elif edge.kind is K.RESULT and type(edge.source.node)is OperationID:
                # Producer selection is not identity. Only a checked opcode's
                # normal result0 may use the arithmetic field computed above.
                if self._operator(edge.source)is not None and self._normal_result_zero(point,edge):
                    fields=self._join(point,fields,self._transfer(parent.fields,edge));possible.append(parent.feasible)
                elif not any(e.kind in(K.BINDING_READ,K.STATE_VALUE)for e in self._incoming[point]):
                    if not self._closed_local_result(point,edge):
                        normal_open=True
                        fields=self._join(point,fields,self._unknown(point,'PRODUCER_VALUE_CONTRACT_OPEN',
                            'Original producer/result routing is not fully covered by a declared local synchronous interface; known candidate completions do not close other normal paths.'))
        value,index=self._value(point)
        feasible=seed.feasible
        if any(e.kind is K.BINDING_READ for e in self._incoming[point]):
            feasible=(False if not normal_open and self._binding_definite(read_state,BindingState.UNBOUND)
                else True if not normal_open and self._binding_definite(read_state,BindingState.BOUND)else None)
        elif possible:feasible=True if True in possible else None
        infeasibility=()
        if feasible is False:
            infeasibility=(Evidence('ORIGINAL_BINDING_READ_HAS_NO_BOUND_NORMAL_INPUT_V1',
                (point.namespace.graph,),(point,*tuple(e.source for e in self._incoming[point]if e.kind is K.BINDING_READ))),)
        # Opaque producers and missing bindings leave an unknown path rather
        # than converting the absence of a constant into a purity assertion.
        if not self._incoming[point]and not any((fields.reference_sources.alternatives,fields.scalar_constant.alternatives,
                fields.builtin_type.alternatives))and seed.role not in('BINDING_PAYLOAD','NONVALUE'):
            fields=self._join(point,fields,self._unknown(point,'VALUE_SOURCE_OPEN','No supported original value-source rule supplies this field.'))
        if self._point_unknown.get(point):
            unknown=ValueField(unknown_paths=self._point_unknown[point]);gap=ValueFields(unknown,unknown,unknown,unknown)
            if payload is not None:payload=self._join(point,payload,gap,'binding_payload.')
            else:fields=self._join(point,fields,gap)
            if binding_state.applicable:
                binding_state=self._join_binding(point,binding_state,BindingStateField(unknown_paths=self._point_unknown[point]))
        if type(value)is DataValue and seed.builtin_type.alternatives:
            fields=replace(fields,builtin_type=seed.builtin_type,
                scalar_constant=fields.scalar_constant if seed.scalar_constant.applicable else _NA,
                immutable_tuple=fields.immutable_tuple if seed.immutable_tuple.applicable else _NA)
        if type(value)is DataValue:fields=replace(fields,reference_sources=_NA)
        if seed.role in('BINDING_PAYLOAD','NONVALUE'):fields=_TOKEN
        excluded=tuple(proof.evidence for proof in self._refuted_inputs.get(point,()))
        if excluded:
            def annotated(current):
                return ValueFields(*(replace(getattr(current,name),alternatives=tuple(replace(a,
                    evidence=tuple(dict.fromkeys((*a.evidence,*excluded))))for a in getattr(current,name).alternatives))
                    for name in _FIELDS))
            fields=annotated(fields)
            if payload is not None:payload=annotated(payload)
            if binding_state.applicable:binding_state=replace(binding_state,alternatives=tuple(replace(a,
                evidence=tuple(dict.fromkeys((*a.evidence,*excluded))))for a in binding_state.alternatives))
        return replace(seed,fields=fields,binding_payload=payload,binding_state=binding_state,feasible=feasible,
            infeasibility=infeasibility)

    def _settle(self):
        self._worklist_stable=False
        work=deque(self._facts);queued=set(work);unseeded_opened=False
        while work or not unseeded_opened:
            if not work:
                # Bottom is useful while solving cycles, but a completed
                # demand cannot hide an unseeded alternative behind a known
                # sibling. Open each unresolved *field*, then propagate that
                # fact through the same bounded queue before publishing.
                unseeded_opened=True
                for point,fact in tuple(self._facts.items()):
                    if fact.feasible is False or fact.role in('NONVALUE','NO_NORMAL_RESULT'):continue
                    binding_state=fact.binding_state;payload=fact.binding_payload
                    if binding_state.applicable and not binding_state.alternatives and not binding_state.unknown_paths:
                        binding_state=BindingStateField(unknown_paths=(self._note(point,'BINDING_STATE_UNRESOLVED',
                            'The binding-token demand has no seeded state proof; a cycle or missing input is not definitely bound.'),))
                    fields=fact.fields
                    for prefix,current in(('',fields),('binding_payload.',payload)):
                        if current is None:continue
                        for name in _FIELDS:
                            field=getattr(current,name)
                            if field.applicable and not field.alternatives and not field.unknown_paths:
                                gap=self._note(point,'VALUE_FIELD_UNRESOLVED',prefix+name+' has no seeded finite proof; other known fields are retained.')
                                current=replace(current,**{name:replace(field,unknown_paths=(gap,))})
                        if prefix:payload=current
                        else:fields=current
                    if fields!=fact.fields or payload!=fact.binding_payload or binding_state!=fact.binding_state:
                        self._facts[point]=replace(fact,fields=fields,binding_payload=payload,binding_state=binding_state)
                        for dependent in self._dependents.get(point,()):
                            if dependent not in queued:queued.add(dependent);work.append(dependent)
                if not work:break
            if self._usage['steps']>=self.budget.max_steps:
                for point in work:
                    self._unsettled[point]=self._note(point,'VALUE_FIXED_POINT_BUDGET','Unsettled original dependency demand remains open.')
                self._exhausted=False;return
            point=work.popleft();queued.remove(point);self._usage['steps']+=1
            try:new=self._compute(point)
            except (OverflowError,TimeoutError)as error:
                self._unsettled[point]=self._note(point,'VALUE_EVALUATION_BUDGET',str(error));self._exhausted=False;return
            old=self._facts[point]
            merged=replace(new,fields=self._join(point,old.fields,new.fields),
                binding_payload=self._join(point,old.binding_payload or ValueFields(),new.binding_payload,'binding_payload.')if new.binding_payload is not None else old.binding_payload,
                binding_state=self._join_binding(point,old.binding_state,new.binding_state),
                occurrence=self._join_occurrence(point,old.occurrence,new.occurrence))
            if merged!=old:
                self._facts[point]=merged
                for dependent in self._dependents.get(point,()):
                    if dependent not in queued:queued.add(dependent);work.append(dependent)
        self._worklist_stable=True

    def analyze(self,roots):
        roots=tuple(roots)
        if not roots or any(type(p)is not Point for p in roots):raise TypeError('value analysis needs qualified DependencyPoint roots')
        if self._facts:raise ValueError('a value-analysis scope is used once')
        selected=frozenset((K.VALUE_USE,K.OPERAND,K.RESULT,K.BLOCK_ARGUMENT,K.ARGUMENT,K.COMPLETION,
            K.STATE_VALUE,K.ENVIRONMENT,K.BINDING_PAYLOAD,K.BINDING_READ,K.CONTROL_CONDITION))
        pending=deque(roots);edges={}
        while pending:
            point=pending.popleft()
            if point in self._facts:continue
            if len(self._facts)>=self.budget.max_points:
                self._note(point,'VALUE_POINT_BUDGET','Unvisited original dependency point is retained.');self._exhausted=False;continue
            try:
                self.session.check();self._facts[point]=self._seed(point)
                if type(point.node)is OperationID:self._branch_predicate(point)
                neighborhood=self.graph.incoming(point,kinds=(K.CONTROL_CONDITION,)
                    if point in self._branch_conditions else selected)
                self._exhausted&=neighborhood.enumerated
                self._frontiers.update((f,f)for f in neighborhood.frontiers)
                blockers=tuple(f for f in neighborhood.frontiers if f.kind in(
                    'STATIC_RELATION_SCOPE_OPEN','UNBOUND_CALL_CONTEXT','RELATION_CONTEXT_UNRESOLVED',
                    'CALL_RELATIONS_NOT_PUBLISHED','NAMESPACE_STATE_CLOSURE_OPEN','MODULE_L_G_ALIAS_CONTRACT_OPEN',
                    'LOCAL_BINDING_PAYLOAD_OPEN','CALL_CONTEXT_UNKNOWN'))
                if not neighborhood.enumerated:
                    blockers=(*blockers,self._note(point,'VALUE_RELATION_ENUMERATION_OPEN','The shared graph did not enumerate every relevant original dependency.'))
                self._point_unknown[point]=tuple(dict.fromkeys(blockers))
                retained=[]
                for edge in neighborhood.edges:
                    if edge not in edges and len(edges)>=self.budget.max_edges:
                        gap=self._note(point,'VALUE_EDGE_BUDGET','Additional original input edges remain unprocessed.')
                        self._point_unknown[point]=tuple(dict.fromkeys((*self._point_unknown[point],gap)))
                        self._exhausted=False;break
                    edges[edge]=edge;retained.append(edge);self._dependents[edge.source].add(point);pending.append(edge.source)
                    for condition in edge.conditions:
                        binding=self._binding_input(condition)
                        if binding is not None:
                            for source in binding:pending.append(source)
                            self._dependents[binding[0]].add(point)
                        if (condition.domain!='canonical'or condition.name!='SUCCESSOR_SELECTED'
                                or condition.operands!=()or condition.subject is None):continue
                        predicate=self._branch_predicate(condition.subject)
                        if predicate is None:continue
                        if condition.index not in(0,1):raise ValueError('BRANCH selection changed its original successor ordinal')
                        # The subject and its actual CONTROL_CONDITION edge
                        # are discovered through the same original graph.
                        pending.append(condition.subject)
                        self._dependents[predicate].add(point)
                self._incoming[point]=tuple(retained)
                self._discover_control(point,pending,edges)
            except (OverflowError,TimeoutError)as error:
                gap=self._note(point,'VALUE_DISCOVERY_BUDGET',str(error));self._exhausted=False
                if point in self._facts:
                    self._incoming.setdefault(point,());self._unsettled[point]=gap
                    self._point_unknown[point]=tuple(dict.fromkeys((*self._point_unknown[point],gap)))
                break
        self._usage['points']=len(self._facts);self._usage['edges']=len(edges)
        # Edges cut by the discovery budget keep their explicit unknown path.
        for point,incoming in tuple(self._incoming.items()):
            self._incoming[point]=tuple(e for e in incoming if e.source in self._facts)
            if len(self._incoming[point])!=len(incoming):
                gap=self._note(point,'VALUE_DEPENDENCY_UNVISITED','Original source endpoint lies beyond discovery budget.')
                self._point_unknown[point]=tuple(dict.fromkeys((*self._point_unknown[point],gap)))
        for point,incoming in tuple(self._control_inputs.items()):
            self._control_inputs[point]=tuple(e for e in incoming if e.source in self._facts)
            if len(self._control_inputs[point])!=len(incoming):
                gap=self._note(point,'CONTROL_DEPENDENCY_UNVISITED','An original controller/owner lies beyond the shared discovery budget.')
                self._control_unknown[point]=tuple(dict.fromkeys((*self._control_unknown[point],gap)))
        discovery_frontiers=dict(self._frontiers)
        self._usage['branch_refinements']=0;self._usage['branches_proved']=0;self._usage['bindings_proved']=0
        self._usage['route_refinements']=0;self._usage['routes_refuted']=0
        while True:
            self._settle()
            try:
                while True:
                    bindings=self._freeze_bindings()
                    if not bindings:break
                    self._binding_proofs.update((proof.condition,proof)for proof in bindings)
                    self._usage['bindings_proved']=len(self._binding_proofs)
                added=self._freeze_branches()
                self._branch_proofs.update((proof.branch,proof)for proof in added)
                self._usage['branches_proved']=len(self._branch_proofs)
                refuted=self._freeze_refutations(edges)
                self._usage['routes_refuted']=len(self._route_refutations)
            except (OverflowError,TimeoutError)as error:
                self._note(roots[0],'BINDING_PROOF_BUDGET',str(error));self._exhausted=False;break
            if not added and not refuted:break
            # Closed proofs only grow across rounds. Derived field facts are
            # recomputed from their original seeds: no stale value/unknown
            # from a refuted arm survives an in-place cumulative join.
            try:
                seeds={}
                for point in self._facts:
                    self.session.check();seeds[point]=self._seed(point)
            except (OverflowError,TimeoutError)as error:
                self._note(point,'BRANCH_REFINEMENT_BUDGET',str(error));self._exhausted=False
                self._worklist_stable=False
                break  # Previous completed round remains a sound fallback.
            self._usage['branch_refinements']+=bool(added)
            self._usage['route_refinements']+=bool(refuted)
            self._facts=seeds;self._frontiers=dict(discovery_frontiers);self._widened.clear()
        # A stopped queue is an open path, not a completed conditional proof.
        # Only affected dependents are marked; independent literals retain
        # their exact content/type fields.
        pending=deque(self._unsettled.items());seen=set()
        while pending:
            point,gap=pending.popleft()
            if point in seen:continue
            seen.add(point);fact=self._facts[point]
            if fact.occurrence.applicable:
                fact=replace(fact,occurrence=replace(fact.occurrence,unknown_paths=tuple(dict.fromkeys(
                    (*fact.occurrence.unknown_paths,gap)))))
                self._facts[point]=fact
            if fact.role!='LITERAL':
                def opened(fields):
                    return ValueFields(*(replace(getattr(fields,n),unknown_paths=tuple(dict.fromkeys(
                        (*getattr(fields,n).unknown_paths,gap))))if getattr(fields,n).applicable else getattr(fields,n)
                        for n in _FIELDS))
                self._facts[point]=replace(fact,fields=opened(fact.fields),
                    binding_payload=opened(fact.binding_payload)if fact.binding_payload is not None else None,
                    binding_state=replace(fact.binding_state,unknown_paths=tuple(dict.fromkeys(
                        (*fact.binding_state.unknown_paths,gap))))if fact.binding_state.applicable else fact.binding_state,
                    feasible=None if fact.role!='NO_NORMAL_RESULT'else fact.feasible)
            pending.extend((dependent,gap)for dependent in self._dependents.get(point,()))
        for point,fact in tuple(self._facts.items()):
            if fact.feasible is False:self._facts[point]=replace(fact,fields=_TOKEN)
        return ValueAnalysisResult(roots,tuple(self._facts.values()),tuple(edges),tuple(self._frontiers),dict(self._usage),self._exhausted,
            tuple(self._branch_proofs.values()),tuple(self._binding_proofs.values()),self._worklist_stable,
            tuple(self._route_refutations.values()))


__all__=['ProgramValueAnalysis','ValueAnalysisBudget','ValueAnalysisResult','ValueFact',
    'ValueFields','ValueField','ValueAlternative','FieldPrecision','BranchSelectionProof',
    'BindingStateAlternative','BindingStateField','BindingReadProof']
