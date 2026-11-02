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
from scar.ir.program.model import (DataValue,ReferenceValue,LocalBindingValue,StateVersionValue,
    LiteralOrigin,ExactLiteralOrigin,OperationResult,BlockArgument)


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
class ValueFact:
    point: Point
    fields: ValueFields = ValueFields()
    binding_payload: ValueFields | None = None
    binding_states: tuple[BindingState,...] = ()
    feasible: bool | None = None
    role: Literal['VALUE','LITERAL','NORMAL_RESULT_0','BINDING_PAYLOAD','NONVALUE','NO_NORMAL_RESULT'] = 'VALUE'

    @property
    def reference_sources(self):return self.fields.reference_sources
    @property
    def scalar_constant(self):return self.fields.scalar_constant
    @property
    def builtin_type(self):return self.fields.builtin_type
    @property
    def immutable_tuple(self):return self.fields.immutable_tuple


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
                    or a.value.payload is not(self.selected_index==0)for a in self.alternatives)
                or type(self.evidence)is not Evidence):
            raise TypeError('branch proof needs an original branch/predicate context and stable builtin bool alternatives')


@dataclass(frozen=True,slots=True)
class ValueAnalysisResult:
    roots: tuple[Point,...]
    facts: tuple[ValueFact,...]
    edges: tuple[DependencyEdge,...]
    frontiers: tuple[Frontier,...]
    usage: dict[str,int]
    exhausted: bool
    branch_proofs: tuple[BranchSelectionProof,...] = ()

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
        self._evaluations={}
        self._point_unknown=defaultdict(tuple)
        self._unsettled={}
        self._compiled_units=OrderedDict();self._constant_tables={};self._code_literals={}
        self._compiled_bytes=0
        self._branch_conditions={};self._branch_proofs={}

    def _note(self,point,kind,detail):
        item=Frontier(point,kind,detail);self._frontiers[item]=item
        return item

    def _value(self,point):
        index=self.session.index(point.namespace)
        node=point.node
        if type(node)is UseID:node=index.use_site(node).use.value
        return index.values.get(node),index

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
            definition=next((b for b in index.graph.binding_definitions if b.value==value.id),None)
            state=(definition.state,)if definition is not None else ()
            payload=ValueFields()
            if definition is not None and definition.state is BindingState.UNKNOWN:
                payload=self._unknown(point,'LOCAL_BINDING_PAYLOAD_OPEN','UNKNOWN update does not retain its previous payload.')
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
                    and c.subject==producer.source and c.index==successor for c in incoming.conditions):return False
            matched.add(incoming.source.node)
        return matched==terminals

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
        if opcode=='BUILD_TUPLE':
            references.append(ValueAlternative(point,evidence=(contract,)))
            types.append(ValueAlternative('builtins.tuple',evidence=(contract,)))
        if any(not field.alternatives for field in fields):
            if unknown:
                kind=('IMMUTABLE_TUPLE_ELEMENT_OPEN'if opcode=='BUILD_TUPLE'else
                    'IMMUTABLE_INDEX_KEY_OPEN'if opcode=='INDEX'and not fields[1].alternatives else
                    'IMMUTABLE_INDEX_RECEIVER_OPEN'if opcode=='INDEX'else'BUILTIN_INPUT_CONTENT_OPEN')
                unknown=(*unknown,self._note(point,kind,'Original operand content is not a proved immutable builtin literal; no user protocol or mutable contents are evaluated.'))
            gap=ValueField(unknown_paths=unknown)
            return ValueFields(ValueField(tuple(references))if references else gap,
                _NA if opcode=='BUILD_TUPLE'else gap,ValueField(tuple(types))if types else gap,gap)
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
                    if opcode=='BUILD_TUPLE':
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
                    Condition.from_enum(ConstantRuntimeRequirement.BUILTIN_RUNTIME_MATCH),
                    *([Condition.from_enum(ConstantRuntimeRequirement.FLOATING_ENVIRONMENT_MATCH)]if is_float else[]))))
                if len(guards)>self.budget.max_conditions:
                    unknown=(*unknown,self._note(point,'VALUE_CONDITION_BUDGET','Builtin premise predicates exceed the finite guard bound.'));continue
                evidence=tuple(dict.fromkeys(e for item in items for e in item.evidence))
                evidence=(*evidence,Evidence('BOUNDED_BUILTIN_SCALAR_V1',(point.namespace.graph,),(point,*parents)))
                alternative=ValueAlternative(literal,guards,evidence,tuple(parents),
                    Strength.MAY if any(item.strength is Strength.MAY for item in items)else Strength.EXACT)
                (tuples if literal.kind is LiteralKind.TUPLE else alternatives).append(alternative)
                types.append(replace(alternative,value=type_name))
                references.append(replace(alternative,value=point))
            except (_BudgetExceeded,_Unsupported,ArithmeticError,LookupError,ValueError,TypeError)as error:
                kind=('IMMUTABLE_INDEX_OUT_OF_RANGE'if isinstance(error,IndexError)else
                    'IMMUTABLE_INDEX_KEY_UNSUPPORTED'if opcode=='INDEX'and isinstance(error,_Unsupported)else'BUILTIN_SCALAR_RULE_OPEN')
                unknown=(*unknown,self._note(point,kind,type(error).__name__+': '+str(error)))
        return ValueFields(reference_sources=ValueField(tuple(references),unknown),
            scalar_constant=_NA if opcode=='BUILD_TUPLE'or tuples and not alternatives and not unknown else ValueField(tuple(alternatives),unknown),
            builtin_type=ValueField(tuple(types))if opcode=='BUILD_TUPLE'else ValueField(tuple(types),unknown),
            immutable_tuple=_NA if alternatives and not tuples and not unknown else ValueField(tuple(tuples),unknown))

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
            if c.domain=='canonical'and c.name=='SUCCESSOR_SELECTED'and c.subject in self._branch_proofs))

    def _edge_selected(self,edge):
        return all(c.index==self._branch_proofs[c.subject].selected_index for c in edge.conditions
            if c.domain=='canonical'and c.name=='SUCCESSOR_SELECTED'and c.subject in self._branch_proofs)

    def _freeze_branches(self):
        # A stopped worklist is not a closed predicate. In particular, an
        # early singleton can still acquire another value through a backedge.
        if not self._exhausted or self._unsettled:return ()
        added=[]
        for branch,predicate in self._branch_conditions.items():
            if branch in self._branch_proofs or predicate not in self._facts:continue
            inputs=[edge for edge in self._incoming.get(branch,())if edge.kind is K.CONTROL_CONDITION]
            if (len(inputs)!=1 or inputs[0].source!=predicate or inputs[0].target!=branch
                    or inputs[0].strength is not Strength.EXACT):continue
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
            if any(c.domain!='canonical'or c.name!='SUCCESSOR_SELECTED'
                    or c.subject not in self._branch_proofs
                    or c.index!=self._branch_proofs[c.subject].selected_index
                    for a in field.alternatives for c in a.conditions):
                self._note(branch,'BRANCH_PREDICATE_GUARDS_OPEN',
                    'A builtin-bool candidate retains undischarged original guards; both value paths remain.')
                continue
            selected=0 if next(iter(values))else 1
            evidence=Evidence('STABLE_BUILTIN_BOOL_SELECTS_SUCCESSOR_'+str(selected)+'_V1',
                (branch.namespace.graph,),(branch,predicate))
            added.append(BranchSelectionProof(branch,predicate,selected,field.alternatives,evidence))
        return tuple(added)

    def _compute(self,point):
        seed=self._seed(point);fields=seed.fields;payload=seed.binding_payload;states=set(seed.binding_states)
        if seed.role in('LITERAL','NO_NORMAL_RESULT'):return seed
        possible=[];normal_open=bool(self._point_unknown.get(point))
        operator=self._operator(point)if type(point.node)is OperationID else None
        if operator is not None:
            fields=self._join(point,fields,self._evaluate_operator(point,operator))
        for edge in self._incoming[point]:
            if not self._edge_selected(edge):continue
            parent=self._facts[edge.source]
            if edge.strength is Strength.MAY:normal_open=True
            if edge.kind is K.BINDING_PAYLOAD:
                payload=self._join(point,payload or ValueFields(),self._transfer(parent.fields,edge),'binding_payload.');states.add(BindingState.BOUND)
            elif edge.kind is K.BINDING_READ:
                states.update(parent.binding_states)
                if parent.binding_payload is not None:
                    fields=self._join(point,fields,self._transfer(parent.binding_payload,edge));possible.append(parent.feasible)
            elif edge.kind in (K.VALUE_USE,K.ARGUMENT,K.COMPLETION,K.STATE_VALUE,K.ENVIRONMENT,K.BLOCK_ARGUMENT)and edge.meaning in(M.VALUE,M.REFERENCE,M.BINDING):
                if parent.binding_payload is not None:
                    payload=self._join(point,payload or ValueFields(),self._transfer(parent.binding_payload,edge),'binding_payload.')
                    states.update(parent.binding_states)
                else:fields=self._join(point,fields,self._transfer(parent.fields,edge))
                possible.append(parent.feasible)
            elif edge.kind is K.RESULT and type(edge.source.node)is OperationID:
                # Producer selection is not identity. Only a checked opcode's
                # normal result0 may use the arithmetic field computed above.
                slots=[c.index for c in edge.conditions if c.domain=='canonical'and c.name=='COMPLETION_SLOT']
                if self._operator(edge.source)is not None and(not slots or slots==[0]):
                    fields=self._join(point,fields,self._transfer(parent.fields,edge));possible.append(parent.feasible)
                elif not any(e.kind in(K.BINDING_READ,K.STATE_VALUE)for e in self._incoming[point]):
                    if not self._closed_local_result(point,edge):
                        normal_open=True
                        fields=self._join(point,fields,self._unknown(point,'PRODUCER_VALUE_CONTRACT_OPEN',
                            'Original producer/result routing is not fully covered by a declared local synchronous interface; known candidate completions do not close other normal paths.'))
        value,index=self._value(point)
        feasible=seed.feasible
        if any(e.kind is K.BINDING_READ for e in self._incoming[point]):
            feasible=False if states=={BindingState.UNBOUND}else True if BindingState.BOUND in states else None
        elif possible:feasible=True if True in possible else False if not normal_open and all(p is False for p in possible)else None
        # Opaque producers and missing bindings leave an unknown path rather
        # than converting the absence of a constant into a purity assertion.
        if not self._incoming[point]and not any((fields.reference_sources.alternatives,fields.scalar_constant.alternatives,
                fields.builtin_type.alternatives))and seed.role not in('BINDING_PAYLOAD','NONVALUE'):
            fields=self._join(point,fields,self._unknown(point,'VALUE_SOURCE_OPEN','No supported original value-source rule supplies this field.'))
        if self._point_unknown.get(point):
            unknown=ValueField(unknown_paths=self._point_unknown[point]);gap=ValueFields(unknown,unknown,unknown,unknown)
            if payload is not None:payload=self._join(point,payload,gap,'binding_payload.')
            else:fields=self._join(point,fields,gap)
        if type(value)is DataValue and seed.builtin_type.alternatives:
            fields=replace(fields,builtin_type=seed.builtin_type,
                scalar_constant=fields.scalar_constant if seed.scalar_constant.applicable else _NA,
                immutable_tuple=fields.immutable_tuple if seed.immutable_tuple.applicable else _NA)
        if type(value)is DataValue:fields=replace(fields,reference_sources=_NA)
        if seed.role in('BINDING_PAYLOAD','NONVALUE'):fields=_TOKEN
        return replace(seed,fields=fields,binding_payload=payload,binding_states=tuple(sorted(states,key=lambda s:s.value)),feasible=feasible)

    def _settle(self):
        work=deque(self._facts);queued=set(work);unseeded_opened=False
        while work or not unseeded_opened:
            if not work:
                # Bottom is useful while solving cycles, but a completed
                # demand cannot hide an unseeded alternative behind a known
                # sibling. Open each unresolved *field*, then propagate that
                # fact through the same bounded queue before publishing.
                unseeded_opened=True
                for point,fact in tuple(self._facts.items()):
                    if fact.feasible is False or fact.role in('BINDING_PAYLOAD','NONVALUE','NO_NORMAL_RESULT'):continue
                    fields=fact.fields
                    for name in _FIELDS:
                        field=getattr(fields,name)
                        if field.applicable and not field.alternatives and not field.unknown_paths:
                            gap=self._note(point,'VALUE_FIELD_UNRESOLVED',name+' has no seeded finite proof; other known fields are retained.')
                            fields=replace(fields,**{name:replace(field,unknown_paths=(gap,))})
                    if fields!=fact.fields:
                        self._facts[point]=replace(fact,fields=fields)
                        for dependent in self._dependents.get(point,()):
                            if dependent not in queued:queued.add(dependent);work.append(dependent)
                if not work:break
            if self._usage['steps']>=self.budget.max_steps:
                for point in work:
                    self._unsettled[point]=self._note(point,'VALUE_FIXED_POINT_BUDGET','Unsettled original dependency demand remains open.')
                self._exhausted=False;break
            point=work.popleft();queued.remove(point);self._usage['steps']+=1
            try:new=self._compute(point)
            except (OverflowError,TimeoutError)as error:
                self._unsettled[point]=self._note(point,'VALUE_EVALUATION_BUDGET',str(error));self._exhausted=False;break
            old=self._facts[point]
            merged=replace(new,fields=self._join(point,old.fields,new.fields),
                binding_payload=self._join(point,old.binding_payload or ValueFields(),new.binding_payload,'binding_payload.')if new.binding_payload is not None else old.binding_payload,
                binding_states=tuple(sorted(set((*old.binding_states,*new.binding_states)),key=lambda s:s.value)))
            if merged!=old:
                self._facts[point]=merged
                for dependent in self._dependents.get(point,()):
                    if dependent not in queued:queued.add(dependent);work.append(dependent)

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
                    if len(edges)>=self.budget.max_edges:
                        self._note(point,'VALUE_EDGE_BUDGET','Additional original input edges remain unprocessed.');self._exhausted=False;break
                    edges[edge]=edge;retained.append(edge);self._dependents[edge.source].add(point);pending.append(edge.source)
                    for condition in edge.conditions:
                        if (condition.domain!='canonical'or condition.name!='SUCCESSOR_SELECTED'
                                or condition.subject is None):continue
                        predicate=self._branch_predicate(condition.subject)
                        if predicate is None:continue
                        if condition.index not in(0,1):raise ValueError('BRANCH selection changed its original successor ordinal')
                        # The subject and its actual CONTROL_CONDITION edge
                        # are discovered through the same original graph.
                        pending.append(condition.subject)
                        self._dependents[predicate].add(point)
                self._incoming[point]=tuple(retained)
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
                self._facts[point]=replace(self._facts[point],fields=self._unknown(point,'VALUE_DEPENDENCY_UNVISITED','Original source endpoint lies beyond discovery budget.'))
        discovery_frontiers=dict(self._frontiers)
        self._usage['branch_refinements']=0;self._usage['branches_proved']=0
        while True:
            self._settle()
            added=self._freeze_branches()
            if not added:break
            # Closed proofs only grow across rounds. Derived field facts are
            # recomputed from their original seeds: no stale value/unknown
            # from a refuted arm survives an in-place cumulative join.
            try:
                seeds={}
                for point in self._facts:
                    self.session.check();seeds[point]=self._seed(point)
            except (OverflowError,TimeoutError)as error:
                self._note(point,'BRANCH_REFINEMENT_BUDGET',str(error));self._exhausted=False
                break  # Previous completed round remains a sound fallback.
            self._branch_proofs.update((proof.branch,proof)for proof in added)
            self._usage['branch_refinements']+=1;self._usage['branches_proved']=len(self._branch_proofs)
            self._facts=seeds;self._frontiers=dict(discovery_frontiers);self._widened.clear()
        for point,fact in tuple(self._facts.items()):
            if fact.feasible is False:
                self._facts[point]=replace(fact,fields=_TOKEN)
        # A stopped queue is an open path, not a completed conditional proof.
        # Only affected dependents are marked; independent literals retain
        # their exact content/type fields.
        pending=deque(self._unsettled.items());seen=set()
        while pending:
            point,gap=pending.popleft()
            if point in seen:continue
            seen.add(point);fact=self._facts[point]
            if fact.role!='LITERAL':
                def opened(fields):
                    return ValueFields(*(replace(getattr(fields,n),unknown_paths=tuple(dict.fromkeys(
                        (*getattr(fields,n).unknown_paths,gap))))if getattr(fields,n).applicable else getattr(fields,n)
                        for n in _FIELDS))
                self._facts[point]=replace(fact,fields=opened(fact.fields),
                    binding_payload=opened(fact.binding_payload)if fact.binding_payload is not None else None)
            pending.extend((dependent,gap)for dependent in self._dependents.get(point,()))
        return ValueAnalysisResult(roots,tuple(self._facts.values()),tuple(edges),tuple(self._frontiers),dict(self._usage),self._exhausted,tuple(self._branch_proofs.values()))


__all__=['ProgramValueAnalysis','ValueAnalysisBudget','ValueAnalysisResult','ValueFact',
    'ValueFields','ValueField','ValueAlternative','FieldPrecision','BranchSelectionProof']
