"""Generator creation and lazy definition, independent of an external consumer.

Reuse the existing exact child-code/body construction. No driver, request or
body activation is introduced merely because a reference can escape to CALL.
The V1 fixed-unpack producer is unchanged, including its implementation hash.
"""
from __future__ import annotations

import ast
import dis
from hashlib import sha256
from pathlib import Path
from types import CodeType

from scar.analysis.program_lowering import _Unsupported, _REF
from scar.analysis.source_generator_lowering import TABLES, child_code, _body, _PREFIX
from scar.analysis.source_heap_lowering import _source_definition, expression_for_heap_target, _hold
from scar.analysis.source_mapping_lowering import _transfer
from scar.ir.program.drivers import ResumableCreate, CreationCapture, DriverRule, DriverRuleProfile, NormalResultPort
from scar.ir.program.ids import OperationID, ValueID
from scar.ir.program.model import AccessMode, Behavior, ExitKind, Operation, OperationResult, ReferenceValue, StateAccess
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.source import GapKind, SourceRole
from scar.ir.program.source_language import CodeConstantSource
from scar.ir.program.structured import PythonProtocolKind as K
from scar.ir.v2.semantic import OperationKind


VERSION = 'PYTHON_GENEXPR_CREATION_314_V1'


def creation_code_sources(code, node):
    """All conditional PCs for one original constant slot/source occurrence.

    The common CFG entry separates repeat evaluations. No path may visit two
    creation loads before revisiting that entry. Exception-table edges are
    included; this is evidence about alternative source implementations, not
    an observed PC or an invented consumer/drive execution.
    """
    span=lambda n:(n.lineno,n.end_lineno,n.col_offset,n.end_col_offset)
    rows=tuple(dis.get_instructions(code)); positions={r.offset:i for i,r in enumerate(rows)}
    loads=[r for r in rows if r.opname=='LOAD_CONST' and tuple(r.positions)==span(node)
           and type(r.argval) is CodeType and r.argval.co_name=='<genexpr>']
    if not loads or len({r.arg for r in loads})!=1:
        raise _Unsupported(GapKind.CODE_VERSION,node,'GENEXPR_CREATION_ORIGINAL_CONSTANT_SLOT_AMBIGUOUS')
    index=loads[0].arg; child=code.co_consts[index]
    if (any(r.argval is not child for r in loads) or child.co_argcount!=1 or child.co_varnames[:1]!=('.0',)
            or not child.co_flags&0x20 or child.co_cellvars or child.co_varnames[1:2]!=(node.generators[0].target.id,)):
        raise _Unsupported(GapKind.CODE_VERSION,node,'GENEXPR_CREATION_CHILD_INTERFACE_UNRECOVERED')
    sites=[]
    for load in loads:
        at=positions[load.offset]
        if rows[at+1].opname!='MAKE_FUNCTION':
            raise _Unsupported(GapKind.CODE_VERSION,node,'GENEXPR_CREATION_FACTORY_INTERFACE_UNRECOVERED')
        if child.co_freevars:
            prefix=rows[at-len(child.co_freevars)-1:at]
            if (len(prefix)!=len(child.co_freevars)+1 or prefix[-1].opname!='BUILD_TUPLE'
                    or prefix[-1].arg!=len(child.co_freevars)
                    or tuple(r.argval for r in prefix[:-1])!=child.co_freevars
                    or any(r.opname not in ('LOAD_FAST','LOAD_FAST_BORROW')for r in prefix[:-1])
                    or rows[at+2].opname!='SET_FUNCTION_ATTRIBUTE' or rows[at+2].arg!=8):
                raise _Unsupported(GapKind.CODE_VERSION,node,'GENEXPR_CREATION_CAPTURE_INTERFACE_UNRECOVERED')
        calls=[r for r in rows[at+2:]if r.opname=='CALL' and r.arg==0 and tuple(r.positions)==span(node)]
        if not calls:raise _Unsupported(GapKind.CODE_VERSION,node,'GENEXPR_CREATION_CALL_INTERFACE_UNRECOVERED')
        call=calls[0]
        gets=[r for r in rows[at+2:positions[call.offset]]if r.opname=='GET_ITER' and tuple(r.positions)==span(node.generators[0].iter)]
        if len(gets)!=1:raise _Unsupported(GapKind.CODE_VERSION,node,'GENEXPR_CREATION_EAGER_ITERATOR_UNRECOVERED')
        sites.append({'load_pc':load.offset,'make_pc':rows[at+1].offset,'get_iter_pc':gets[0].offset,'call_pc':call.offset})
    edges={r.offset:set()for r in rows}
    for i,row in enumerate(rows):
        if row.opcode in dis.hasjump:edges[row.offset].add(row.argval)
        if row.opname not in ('RETURN_VALUE','RETURN_CONST','RAISE_VARARGS','RERAISE',
                'JUMP_FORWARD','JUMP_BACKWARD','JUMP_BACKWARD_NO_INTERRUPT') and i+1<len(rows):
            edges[row.offset].add(rows[i+1].offset)
    for exception in dis.Bytecode(code).exception_entries:
        for row in rows:
            if exception.start<=row.offset<exception.end:edges[row.offset].add(exception.target)
    reachable=set();todo=[rows[0].offset]
    while todo:
        pc=todo.pop()
        if pc not in reachable:reachable.add(pc);todo.extend(edges[pc])
    predecessors={pc:set()for pc in reachable}
    for pc in reachable:
        for nxt in edges[pc]:predecessors[nxt].add(pc)
    dom={pc:({pc}if pc==rows[0].offset else set(reachable))for pc in reachable};changed=True
    while changed:
        changed=False
        for pc in reachable-{rows[0].offset}:
            value={pc}|set.intersection(*(dom[p]for p in predecessors[pc]))
            if value!=dom[pc]:dom[pc]=value;changed=True
    common=set.intersection(*(dom[r.offset]for r in loads));entry=max(common,key=lambda pc:len(dom[pc]))
    for load in loads:
        seen=set();todo=list(edges[load.offset])
        while todo:
            pc=todo.pop()
            if pc==entry or pc in seen:continue
            if any(pc==other.offset for other in loads if other.offset!=load.offset):
                raise _Unsupported(GapKind.CODE_VERSION,node,'GENEXPR_CREATION_SITES_NOT_EXCLUSIVE')
            seen.add(pc);todo.extend(edges[pc])
    return index,child,{'constant_path':[index],'source_span':span(node),'common_entry_pc':entry,
        'conditional_sites':sites,'capture_names':list(child.co_freevars),'condition':'one alternative before revisiting common entry'}


def creation_rule():
    raw = Path(__file__).read_bytes()
    return DriverRule(DriverRuleProfile.PYTHON_RESUMPTION_V1,
        ProviderFactReference(ProviderArtifact('scar://source-language/'+VERSION+'/producer',
            sha256(raw).hexdigest(),len(raw),VERSION),
            'Creation and lazy body definition only; no consumer/drive/activation implied'))


def lower_creation(builder, node, cursor):
    if not builder.has_language('LEXICAL_LOCALS') or builder.has_language('GENEXPR_314_V1'):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX,node,'GENEXPR_CREATION_REQUIRES_LEXICAL_LOCALS_AND_DISTINCT_POLICY')
    evidence = builder.language_options.code_evidence
    if evidence is None:
        raise _Unsupported(GapKind.CODE_VERSION,node,'GENEXPR_READONLY_CHILD_CODE_WITNESS_REQUIRED')
    if (len(node.generators)!=1 or node.generators[0].is_async or node.generators[0].ifs
            or not isinstance(node.generators[0].target,ast.Name)):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX,node,'GENEXPR_CLAUSE_INTERFACE_UNIMPLEMENTED')
    definition = _source_definition(builder,node)
    if definition.kind is not OperationKind.OPAQUE or definition.metadata.get('ast_type')!='GeneratorExp':
        raise _Unsupported(GapKind.SOURCE_MAPPING,node,'GENEXPR_ORIGINAL_SG_SCOPE_REQUIRED')
    index, code, sites = creation_code_sources(evidence.code,node)
    if any(name not in builder.cell_references for name in code.co_freevars):
        raise _Unsupported(GapKind.SOURCE_MAPPING,node,'GENEXPR_CAPTURE_REQUIRES_ACTUAL_PARENT_CELL')
    if not hasattr(builder,'generator_records'):
        builder.generator_records={name:[]for name in TABLES};builder.generator_handles={}
    body, environment, port, _suspend = _body(builder,node,definition,code,index)
    identity = builder.fresh(OperationID,'genexpr-code')
    before = builder.use(identity,cursor.state,node,'code-constant-world',0)
    value = ReferenceValue(builder.fresh(ValueID,'genexpr-code'),builder.function_context,OperationResult(identity,0))
    builder.add_value(value);builder.link_value(value,node,SourceRole.EXPRESSION)
    builder.emit(cursor,Operation(identity,'child code reference',(Behavior.READ,),(before,),(value.id,),
        (StateAccess(builder.world,before.id,AccessMode.READ),),effects_complete=False),node,SourceRole.EXPRESSION)
    builder.protocol(identity,K.READ_CODE_CONSTANT,node)
    builder.language_constants.append(CodeConstantSource(identity,builder.source(node),evidence.code_layout_key,(index,)))
    cells=tuple(builder.cell_references[name]for name in code.co_freevars)
    inputs=(value.id,builder.environment_references[_PREFIX[1]],*cells)
    cursor,function_env,identity=builder.invoke_results(cursor,node,
        tuple((v,node,'function-input',n,None)for n,v in enumerate(inputs)),result_types=(_REF,)*5)
    builder.protocol(identity,K.MAKE_GENEXPR_FUNCTION,node)
    function,*_ = function_env
    baseline=len(builder.active_temporaries);_hold(builder,cursor,node,function)
    try:
        outer=node.generators[0].iter
        cursor,iterable=expression_for_heap_target(builder,outer,cursor)
        if cursor is None:return None,None
        _hold(builder,cursor,outer,iterable)
        def get_failed(at,exception):
            held=tuple(builder.active_temporaries)
            try:
                _transfer(builder,((outer,iterable),),outer);builder.finish_exit(at,outer,exception,ExitKind.RAISE)
            finally:builder.active_temporaries[:]=held
        cursor,iterator,_=builder.invoke_protocol(cursor,outer,(iterable,),K.GET_ITERATOR,failure_handler=get_failed)
        _transfer(builder,((outer,iterable),),outer);_hold(builder,cursor,outer,iterator)
        actual=(*function_env,*cells,iterator);consumed=((node,function),(outer,iterator))
        def failed(at,exception):
            held=tuple(builder.active_temporaries)
            try:
                _transfer(builder,consumed,node);builder.finish_exit(at,node,exception,ExitKind.RAISE)
            finally:builder.active_temporaries[:]=held
        cursor,results,identity=builder.invoke_results(cursor,node,
            tuple((v,node,'creation-capture',n,None)for n,v in enumerate(actual)),result_types=(_REF,),failure_handler=failed)
        builder.protocol(identity,K.CREATE_GENEXPR,node);_transfer(builder,consumed,node)
        op=builder.operation_records[identity]
        captures=tuple(CreationCapture(formal,use.id)for formal,use in
            zip((*[m.reference for m in environment.members],port.value),op.uses))
        builder.generator_records['resumable_creates'].append(ResumableCreate(identity,body.id,captures[0].source,
            captures,NormalResultPort(0),creation_rule()))
        # Deliberately no generator_handles registration: generic consumers use
        # ordinary reference/world calls, not the old fixed-unpack drive path.
        builder.gap(GapKind.EFFECT_SUMMARY,node,
            'generator creation and lazy body are declared; escaping consumers/drive count, NEXT/SEND/THROW/CLOSE, '
            'dynamic activation, reference identity, contents and finalizer/noncompletion effects remain unresolved')
        builder.gap(GapKind.CODE_VERSION,node,'one source creation uses original constant slot '+str(index)+
            '; conditional LOAD_CONST PCs '+repr([s['load_pc']for s in sites['conditional_sites']])+
            ' before common entry '+str(sites['common_entry_pc'])+' is revisited; no observed PC selected')
        return cursor,results[0]
    finally:del builder.active_temporaries[baseline:]
