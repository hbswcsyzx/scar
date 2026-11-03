"""Read original IMPORT_NAME/FROM ports using retained-source compilation.

No module is imported and no target/default/annotation is executed.  These
records describe requests and field-read alternatives, never loader identity.
"""
from __future__ import annotations

import ast
from collections import defaultdict
import dis
import hashlib
from types import SimpleNamespace

from scar.analysis.static_namespace import normal_reference
from scar.ir.program.environments import EnvironmentRole as E
from scar.ir.program.model import (CompletionResult,ExitKind,LiteralOrigin,
    OperationResult,ReferenceValue,StateVersionValue,TerminatorKind)
from scar.ir.program.source_language import decode_language_overlay
from scar.ir.program.static_calls import (StaticCallFrontier,StaticImportFromRead,
    StaticImportFromRequest)
from scar.ir.v2.common import SourceReference


def _need(ok,detail):
    if not ok:raise ValueError('static FROM ports: '+detail)


def _span(node):return node.lineno,node.end_lineno,node.col_offset,node.end_col_offset


def derive_import_from_interfaces(body,*,text,semantic,module,metadata,links,protocols,blocks):
    """Return original requests, typed reads and exact unsupported adapters.

    Ordinals come from the original normal CFG corridor, not graph-record
    insertion order.  The CodeConstantSource and exact compiler import rule
    independently check the request's fromlist and ordered member operations.
    """
    by_operation=defaultdict(list)
    for row in links:by_operation[row.operation].append(row)
    tree=ast.parse(text,filename=metadata.source.path,type_comments=True)
    nodes=defaultdict(list)
    for node in ast.walk(tree):
        if isinstance(node,ast.ImportFrom):nodes[_span(node)].append(node)
    selected=[];members_by_source=defaultdict(list)
    for operation in body.graph.operations:
        if protocols.get(operation.id)in('IMPORT_FROM_314','FUNCTION_IMPORT_FROM'):
            own=by_operation[operation.id]
            _need(len(own)==1,'FROM member lacks its unique original source link')
            members_by_source[own[0].source].append(operation)
        if protocols.get(operation.id)not in ('IMPORT_NAME_314','FUNCTION_IMPORT_NAME'):continue
        own=by_operation[operation.id]
        _need(len(own)==1,'import request lacks its unique original source link')
        source=own[0].source
        if type(source)is not SourceReference:continue
        matches=nodes.get((source.start_line,source.end_line,source.start_column,source.end_column),())
        if not matches:continue
        atom=semantic.source_atoms.get(source.atom_id)
        _need(len(matches)==1 and atom is not None and atom.kind=='ImportFrom' and atom.reference==source
              and source.path==metadata.source.path and source.fingerprint==metadata.source.fingerprint
              and own[0].semantic_operation is None,
              'FROM request does not match its exact original source occurrence')
        selected.append((operation,source,matches[0]))
    if not selected:return {},(),()
    if body.document.get('class')is not None:
        return {},(),tuple(StaticCallFrontier('CLASS_IMPORT_FROM_COMPILER_ADAPTER_OPEN',
            'The original class IMPORT_NAME/FROM operations remain in their source graph; '
            'this reader has no class compiler-port adapter and does not infer a module source.',source)
            for _,source,_ in selected)
    _need(type(text)is str and 'sha256:'+hashlib.sha256(text.encode()).hexdigest()==metadata.source.fingerprint,
          'retained source fingerprint differs')
    # Reuse the shared audited exact CodeRef/CodeEvidence replay; this verifies
    # compiler identity, flags, both code keys and the complete constant path.
    from scar.analysis.static_function_origins import _replay_compilation
    root=compile(text,metadata.source.path,'exec',flags=0,dont_inherit=True,optimize=0)
    namespace_root=(module.declaration.unit.namespace_root if module is not None else
                    body.document['static_compilation']['namespace_root'])
    inputs=SimpleNamespace(document=body.document,sources=module if module is not None else metadata,
        metadata=metadata,namespace=body.namespace)
    code_path,code=_replay_compilation(inputs,root,namespace_root)
    if body.namespace.source is not None:
        from scar.analysis.static_compilation import _scope_nodes
        found={};issues=[];_scope_nodes(tree,root,(),ast.Module,found,issues)
        source=body.namespace.source
        matches=[row for row in found.get((source.start_line,source.end_line,source.start_column,source.end_column),())
                 if row[0]==code_path and row[1] is code and isinstance(row[2],(ast.FunctionDef,ast.AsyncFunctionDef))]
        _need(len(matches)==1,'function import owner is not its original lexical compiler scope')
    if module is not None:
        constants=module.constants
        from scar.analysis.source_module_lowering import _mapping_source_instructions,mapping_import_plan
        evidence=SimpleNamespace(code=code)
        # Only the module helper's instruction splitter needs this code here;
        # the root CodeRef itself has already been independently replayed.
        instructions=_mapping_source_instructions(SimpleNamespace(tree=tree),evidence,profile=module.profile)
        frame=body.graph.frame_roots[0].entry
        namespaces=(frame.builtins_namespace,frame.globals_namespace,frame.locals_namespace)
    else:
        language=decode_language_overlay(body.document['language']);constants=language.constants
        from scar.analysis.source_import_lowering import compiler_import
        instructions=tuple(dis.get_instructions(code,adaptive=False,show_caches=False))
        environments=[env for env in body.graph.environments
            if env.region==body.graph.root and env.code_definition==body.namespace.definition]
        _need(len(environments)==1,'function import lacks its original environment')
        refs={member.role:member.reference for member in environments[0].members}
        namespaces=(refs[E.GLOBALS_NAMESPACE],refs[E.BUILTINS_NAMESPACE])
    def literal(use,expected):
        origin=body.index.values[use.value].origin
        _need(type(origin)is LiteralOrigin and type(origin.value)is type(expected) and origin.value==expected,
              'request or member literal differs from original source/compiler')
    def ports(operation):
        _need(operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
              and operation.callee is None and not operation.effects_complete
              and operation.invoke_arguments==tuple(use.id for use in operation.uses)
              and type(body.index.values[operation.uses[-1].value])is StateVersionValue
              and all(type(body.index.values[use.value])is ReferenceValue for use in operation.uses[:-1]),
              'import lost its actual incomplete reference/world invoke')
        for kind in (ExitKind.NORMAL,ExitKind.RAISE):
            edges=[edge for edge in operation.terminator.successors if edge.kind is kind]
            signatures=[s for s in operation.completions if s.kind is kind]
            _need(len(edges)==len(signatures)==1
                  and edges[0].arguments==tuple(CompletionResult(i)for i in range(len(signatures[0].types))),
                  'import changed its NORMAL/RAISE completion ports')
        normal=normal_reference(body.index,operation.id,blocks=blocks)
        _need(normal is not None,'import lacks its unique original NORMAL reference')
        return normal
    from scar.analysis.program_lowering import _Unsupported
    requests={};reads=[];frontiers=[]
    for operation,source,node in selected:
        if any(alias.name=='*'for alias in node.names):
            frontiers.append(StaticCallFrontier('IMPORT_FROM_STAR_BINDINGS_OPEN',
                'The original star-import request is retained; no fixed IMPORT_FROM member list is invented.',source))
            continue
        try:
            if module is not None:mapping_import_plan(node,code,instructions=instructions)
            else:compiler_import(node,code)
        except _Unsupported as error:
            frontiers.append(StaticCallFrontier('IMPORT_FROM_COMPILER_PROTOCOL_OPEN',
                error.kind.value+': '+error.detail+'; the actual operations remain in the original graph.',source))
            continue
        offset=len(namespaces)
        _need(len(operation.uses)==offset+5 and tuple(use.value for use in operation.uses[:offset])==namespaces,
              'request replaced original saved namespace references')
        requested,level,fromlist,lookup=operation.uses[offset:-1]
        literal(requested,node.module or '');literal(level,node.level);literal(lookup,'__import__')
        origin=body.index.values[fromlist.value].origin
        candidates=[row for row in constants if type(origin)is OperationResult and row.operation==origin.operation]
        _need(type(origin)is OperationResult and origin.index==0 and len(candidates)==1,
              'fromlist is not its unique original code-constant reference')
        constant=candidates[0]
        from scar.trace.code_snapshot import code_key
        _need(constant.source==source and constant.code_key==code_key(code)
              and len(constant.constant_path)==1 and protocols.get(constant.operation)=='READ_CODE_CONSTANT'
              and body.index.operations[constant.operation].results==(fromlist.value,),
              'fromlist CodeConstantSource changed its source/producer/code layout')
        index=constant.constant_path[0]
        _need(index<len(code.co_consts) and type(code.co_consts[index])is tuple
              and code.co_consts[index]==tuple(alias.name for alias in node.names),
              'fromlist slot does not contain original ordered member names')
        loads=[row for row in instructions if row.opname=='LOAD_CONST' and row.arg==index
               and tuple(row.positions)==_span(node)]
        _need(len(loads)==1,'fromlist lacks its unique exact original compiler LOAD_CONST')
        normal,result=ports(operation)
        request=StaticImportFromRequest(requested.id,level.id,fromlist.id,constant)
        requests[operation.id]=(node,source,request)
        source_reads=members_by_source[source]
        _need(len(source_reads)==len(node.names),'FROM members are missing or duplicated')
        allowed={op.id for op in source_reads};ordered=[];seen=set()
        cursor=operation.terminator.successors[normal.successor_index].block
        state=blocks[cursor].arguments[-1]
        while len(ordered)<len(node.names):
            _need(cursor not in seen,'import member normal corridor cycles before completing its source')
            seen.add(cursor);block=blocks[cursor];following=None
            for identity in block.operations:
                op=body.index.operations[identity]
                worlds=[use.value for use in op.uses if type(body.index.values[use.value])is StateVersionValue]
                _need(not worlds or all(value==state for value in worlds),'import member corridor bypassed its preceding world')
                if op.id in allowed:ordered.append(op)
                term=op.terminator
                if term is not None:
                    _need(term.kind is TerminatorKind.INVOKE,'import member corridor has an unsupported branch')
                    next_edge=[edge for edge in term.successors if edge.kind is ExitKind.NORMAL]
                    _need(len(next_edge)==1,'import member corridor lacks a unique normal continuation')
                    following=next_edge[0].block;state=blocks[following].arguments[-1];break
                for value in op.results:
                    if type(body.index.values[value])is StateVersionValue:state=value
            if len(ordered)==len(node.names):break
            _need(following is not None,'import member corridor ended before all original members')
            cursor=following
        for ordinal,(op,alias) in enumerate(zip(ordered,node.names)):
            own=by_operation[op.id]
            _need(len(own)==1 and own[0].source==source and len(op.uses)==3
                  and op.uses[0].value==result,'IMPORT_FROM replaced its retained actual request result')
            literal(op.uses[1],alias.name)
            edge,value=ports(op)
            reads.append(StaticImportFromRead(body.namespace,op.id,source,ordinal,alias.name,
                op.uses[0].id,op.uses[1].id,op.uses[2].id,edge,value,operation.id))
    return requests,tuple(reads),tuple(frontiers)


__all__=['derive_import_from_interfaces']
