"""Static source-to-original-code contexts, without executing target code.

Annotation markers retain the original expressions and their symbol effects.
The constant-reference path proposes a code owner; exact owner instruction,
layout, exception, line-table and non-code-constant agreement authorizes it.
Query code fingerprints are never used as original program identities.
"""
import ast
import dis
from hashlib import sha256
import json
from types import CodeType
from scar.analysis.source_syntax import _restore_ast
from scar.ir.literals import PythonLiteral
from scar.ir.record_codec import encode
from scar.ir.program import source_productions as P
from scar.ir.program.protocol_signatures import ExceptionABI


def _json(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)


def _require(condition,path,detail):
    if not condition:
        from scar.analysis.source_productions import ProductionError
        raise ProductionError('COMPILATION_CONTEXT',str(path),detail)


def code_paths(root):
    pending=[((),root)]
    while pending:
        path,unit=pending.pop();yield path,unit
        pending.extend(((*path,i),c) for i,c in enumerate(unit.co_consts) if type(c) is CodeType)


def _constant(value,code=None):
    if type(value) is CodeType:
        _require(code is not None,'constant','code constant needs its original digest resolver')
        return ['CODE',code(value)]
    if type(value) is tuple:return ['TUPLE',[_constant(v,code) for v in value]]
    if type(value) is frozenset:return ['FROZENSET',sorted((_constant(v,code) for v in value),key=_json)]
    if type(value) is slice:return ['SLICE',[_constant(v,code) for v in (value.start,value.stop,value.step)]]
    return ['LITERAL',encode(PythonLiteral.from_python(value,exact=True))]


_LAYOUT=('co_code','co_exceptiontable','co_linetable','co_names','co_varnames','co_cellvars','co_freevars',
    'co_argcount','co_posonlyargcount','co_kwonlyargcount','co_nlocals','co_stacksize','co_flags','co_firstlineno',
    'co_filename','co_name','co_qualname')


def code_digest(unit,memo=None):
    """Canonical compiler values, including IEEE bits; no interning/address IDs."""
    memo={} if memo is None else memo
    if id(unit) not in memo:
        fields={name:(getattr(unit,name).hex() if type(getattr(unit,name)) is bytes else getattr(unit,name)) for name in _LAYOUT}
        fields['constants']=[_constant(v,lambda c:code_digest(c,memo)) for v in unit.co_consts]
        fields['schema']='SCAR_COMPILED_CODE_V1'
        memo[id(unit)]=sha256(_json(fields).encode('ascii')).hexdigest()
    return memo[id(unit)]


def _owner_matches(original,query):
    if any(getattr(original,name)!=getattr(query,name) for name in _LAYOUT):return False
    if len(original.co_consts)!=len(query.co_consts):return False
    for left,right in zip(original.co_consts,query.co_consts):
        if type(left) is CodeType or type(right) is CodeType:
            if not type(left) is type(right) is CodeType:return False
            # Bodies/constants of annotation callbacks are deliberately
            # changed, while their scope, argument and capture layout stays.
            metadata=(name for name in _LAYOUT if name not in (
                'co_code','co_exceptiontable','co_linetable','co_stacksize'))
            if any(getattr(left,name)!=getattr(right,name) for name in metadata):return False
        elif _constant(left)!=_constant(right):return False
    return True


def _marker_values(value):
    if type(value) is bytes:yield value
    elif type(value) in (tuple,frozenset):
        for member in value:yield from _marker_values(member)
    elif type(value) is slice:
        for member in (value.start,value.stop,value.step):yield from _marker_values(member)


class CompilationContextIndex:
    def __init__(self,source):
        self.source=source;self._contexts=None

    def _collect(self):
        source=self.source;syntax=source.context.syntax;roles=source.roles
        publications={}
        for occurrence,node in enumerate(syntax.nodes):
            if node.constructor!='AnnAssign':continue
            pub=source.statements.annotation_publication(occurrence,ExceptionABI.EXCEPTION_WORLD)
            if pub is not None and pub.publication is P.AnnotationPublicationKind.DEFERRED:publications[occurrence]=pub
        if not publications:return {}
        tree=_restore_ast(syntax.root,syntax.nodes);objects={syntax.root:tree};pending=[syntax.root]
        while pending:
            current=pending.pop();node=syntax.nodes[current];obj=objects[current]
            for name,value in zip(roles.fields[node.constructor],node.fields):
                if value.kind=='NODE':objects[value.reference]=getattr(obj,name);pending.append(value.reference)
                elif value.kind=='LIST':
                    for member,child in zip(value.items,getattr(obj,name)):
                        if member.kind=='NODE':objects[member.reference]=child;pending.append(member.reference)
        original=[compile(tree,source.input.path,syntax.mode,dont_inherit=True,optimize=i) for i in (0,1,2)]
        occupied={b for root in original for _,unit in code_paths(root) for c in unit.co_consts for b in _marker_values(c)}
        markers={}
        for occurrence,pub in publications.items():
            suffix=0
            while (marker:=('SCAR-CONTEXT:'+str(occurrence)+':'+str(suffix)).encode()) in occupied:suffix+=1
            occupied.add(marker)
            scope=source.context.context_at_slot(pub.annotation).state.environment;markers[marker]=scope
            value=objects[occurrence].annotation
            mark=ast.copy_location(ast.Constant(value=marker),value)
            objects[occurrence].annotation=ast.copy_location(ast.Tuple(elts=[value,mark],ctx=ast.Load()),value)
        result={}
        for level,root in enumerate(original):
            owners=dict(code_paths(root))
            query=compile(tree,source.input.path,syntax.mode,dont_inherit=True,optimize=level)
            queries=dict(code_paths(query));groups={}
            for path,callback in queries.items():
                scopes={markers[b] for c in callback.co_consts for b in _marker_values(c) if b in markers}
                if not scopes:continue
                _require(len(scopes)==1 and bool(path),path,'marker callback must have one original scope and a constant owner')
                groups.setdefault(scopes.pop(),set()).add(path[:-1])
            memo={}
            for scope,paths in groups.items():
                request=source.scope_annotations.request(scope);variant=request.variants[level]
                registrations={e.registration.index:e.registration for e in variant.entries if e.registration is not None}
                sites=[];unverified=[]
                creator=source.context.material.scopes[scope].parent
                expected='LOAD_DEREF' if source.context.material.scopes[creator].kind=='CLASS' else 'LOAD_NAME'
                for path in sorted(paths):
                    left=owners.get(path);right=queries[path]
                    if left is None or not _owner_matches(left,right):unverified.append(path);continue
                    reference=P.CompiledCodeReference(level,path,code_digest(left,memo),len(left.co_code))
                    ops=[op for op in dis.get_instructions(left) if op.opname not in ('EXTENDED_ARG','NOT_TAKEN')]
                    for i,op in enumerate(ops):
                        if op.opname!='SET_ADD' or op.arg!=1 or i<2 or i+1>=len(ops):continue
                        lookup,index=ops[i-2:i];discard=ops[i+1]
                        if lookup.opname!=expected or lookup.argval!='__conditional_annotations__':continue
                        _require(index.opname in ('LOAD_CONST','LOAD_SMALL_INT') and type(index.argval) is int
                            and index.argval in registrations and discard.opname=='POP_TOP',path,
                            'original registry insertion differs from its source-bound compiler registration')
                        sites.append(P.AnnotationEmissionSite(registrations[index.argval],reference,
                            lookup.offset,index.offset,op.offset,discard.offset))
                status=P.CompilationContextStatus.OWNER_LAYOUT_UNVERIFIED if unverified else P.CompilationContextStatus.VERIFIED
                result[scope,level]=(status,tuple(sites),tuple(unverified))
        return result

    def sites(self,scope,level,*,emitted):
        if self._contexts is None:self._contexts=self._collect()
        row=self._contexts.get((scope,level))
        if row is not None:return row
        return (P.CompilationContextStatus.OWNER_LAYOUT_UNVERIFIED if emitted else
            P.CompilationContextStatus.NO_RETAINED_OWNER,(),())

    def bind(self,parameter,code,offset):
        _require(parameter==self.source.annotation_states.parameter(parameter.publication),'parameter',
            'compiler input differs from its original source domain/context evidence')
        matches={site.registration for variant in parameter.variants for site in variant.producer_sites
            if site.code==code and site.insert_offset==offset}
        _require(len(matches)==1,offset,'exact original code version/path and insertion offset must select one registration')
        return matches.pop()
