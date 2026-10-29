"""Independent compiler-stack and canonical-port checks for class suites."""
from __future__ import annotations

import ast
import dis
from types import CodeType

from scar.analysis.static_compilation import compile_source_unit
from scar.analysis.source_class_validation import _source_semantics,_expected_header_inputs,_expected_body_statements
from scar.ir.program.class_entries import (
    ClassNormalPayloadKind,ClassSuiteMethodOverlay,validate_class_suite_core,
)
from scar.ir.program.model import (
    BlockArgument,ExitKind,LiteralOrigin,OperationResult,ReferenceValue,
    StateVersionValue,TerminatorKind,
)
from scar.ir.program.validation import require_valid


def require_valid_class_suite(prepared,definition,source,*,code_evidence,result):
    def need(ok,why):
        if not ok:raise ValueError('class suite source: '+why)
    snapshot,semantic,node=_source_semantics(prepared,definition,source)
    independently_compiled=compile_source_unit(prepared)
    evidence=independently_compiled.for_definition(definition,source)
    need(evidence.to_reference()==code_evidence.to_reference(),'independent no-exec compilation differs')
    graph,metadata,overlay=result.graph,result.metadata,result.overlay
    require_valid(graph);validate_class_suite_core(overlay,graph,metadata)
    need(overlay.parent_definition==semantic.parent_id and overlay.compilation==evidence.to_reference(),'original lexical/compile context differs')
    need(overlay.inputs==_expected_header_inputs(prepared,node),'original class-header input order differs')
    need(overlay.statements==_expected_body_statements(prepared,node),'class source statements omitted/reordered')
    for rows in (metadata.operation_links,metadata.value_links,metadata.use_links):
        for link in rows:
            atom=prepared.semantic.source_atoms.get(link.source.atom_id)
            need(atom is not None and atom.reference==link.source,'invented/changed source atom')
    for link in metadata.operation_links:
        if link.semantic_operation is not None:
            original=prepared.semantic.definitions.get(link.semantic_operation)
            need(original is not None and original.code_id==link.source.atom_id.wire,'original semantic correspondence differs')
    operations={o.id:o for o in graph.operations};values={v.id:v for v in graph.values}
    blocks={b.id:b for r in graph.regions for b in r.blocks}
    protocols={p.operation:p for p in overlay.protocols};mapping=overlay.interface.mapping
    namespace=(mapping.locals_namespace,mapping.globals_namespace,mapping.builtins_namespace)
    free=dict(zip(overlay.interface.co_freevars,mapping.closure_cells));cells={}
    constants={c.operation:c for c in overlay.constants};constant_values={};code_values={};tuples={};functions={}
    factories={f.operation:f for f in overlay.factories};stack=[]
    method_profile=type(overlay)is ClassSuiteMethodOverlay
    method_lookups={x.operation:x for x in overlay.method_lookups}if method_profile else{}
    method_calls={x.operation:x for x in overlay.method_calls}if method_profile else{}
    method_carriers={}
    rows=tuple(dis.get_instructions(evidence.code,adaptive=False,show_caches=False))
    applications=set()
    from scar.analysis.source_class_validation import _source_reference
    for n in ast.walk(node):
        if not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
        ref_n=_source_reference(prepared,n)
        definitions=[d for d in prepared.semantic.definitions.values()if d.code_id==ref_n.atom_id.wire and d.metadata.get('phase')=='call_time']
        for d in definitions:
            try:proof=independently_compiled.for_definition(d.id,ref_n)
            except ValueError:continue
            if proof.code_path[:-1]!=evidence.code_path:continue
            loads=[r for r in rows if r.opname=='LOAD_CONST'and r.arg==proof.code_path[-1]and type(r.argval)is CodeType]
            binding=n.name
            if binding.startswith('__')and not binding.endswith('__')and node.name.lstrip('_'):
                binding='_'+node.name.lstrip('_')+binding
            stores=[r for r in rows if r.opname=='STORE_NAME'and r.argval==binding and tuple(r.positions)==(n.lineno,n.end_lineno,n.col_offset,n.end_col_offset)
                    and loads and r.offset>loads[0].offset]
            if len(loads)!=1 or len(stores)!=1:continue
            calls=[r for r in rows if loads[0].offset<r.offset<stores[0].offset and r.opname in ('CALL','CALL_KW','CALL_FUNCTION_EX')]
            expected=[(x.lineno,x.end_lineno,x.col_offset,x.end_col_offset)for x in reversed(n.decorator_list)]
            if len(calls)==len(expected)and all(r.opname=='CALL'and r.arg==0 and tuple(r.positions)==s for r,s in zip(calls,expected)):
                applications.update(r.offset for r in calls)
    need(len(overlay.instructions)<=len(rows),'extra compiler witnesses')
    def normal(op):
        need(op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE,'missing original invoke')
        edge=next(e for e in op.terminator.successors if e.kind is ExitKind.NORMAL)
        return blocks[edge.block].arguments[:-1]
    def operands(op):return tuple(u.value for u in op.uses[:-1])
    def literal(v,expected):
        origin=values[v].origin
        need(type(origin)is LiteralOrigin and type(origin.value)is type(expected) and origin.value==expected,'literal operand differs')
    def consumed_cleanup(op):
        # Independently replay the frame's still-owned references after the
        # original compiler pops. Consumed lookup/call inputs must not be
        # retained until frame cleanup, unless another actual stack/frame
        # binding independently owns that reference.
        refs=(*namespace,*free.values(),*cells.values(),*(v for v in stack if v is not None))
        expected=tuple(dict.fromkeys(v for v in refs if type(values[v])is ReferenceValue))
        failure=next(e for e in op.terminator.successors if e.kind is ExitKind.RAISE)
        cleanup=operations[blocks[failure.block].operations[0]]
        need(tuple(u.value for u in cleanup.uses[:-3])==expected,
             'consumed lookup/call input retained past its primitive or frame references lost')
    for row,witness in zip(rows,overlay.instructions):
        need((row.offset,row.opname,row.arg,tuple(row.positions))==
             (witness.offset,witness.opcode,witness.argument,witness.positions),'compiler opcode/order/position changed')
        need(tuple(stack)==witness.stack_before,'original compiler stack input differs')
        op=operations.get(witness.operation);p=protocols.get(witness.operation)
        if op is not None:need(p is not None and p.offset==row.offset and p.source==witness.source,'compiler/core witness endpoint differs')
        name,arg=row.opname,row.argval
        kind={'LOAD_CONST':'READ_CODE_CONSTANT','LOAD_NAME':'LOAD_NAME_314','STORE_NAME':'STORE_NAME_314',
              'STORE_DEREF':'STORE_CELL','MAKE_FUNCTION':'MAKE_FUNCTION_314','LOAD_ATTR':'LOAD_ATTRIBUTE',
              'RETURN_VALUE':'FRAME_EXIT_NORMAL','POP_TOP':'FRAME_DISCARD'}.get(name,name)
        if name=='LOAD_ATTR'and row.arg&1:
            need(method_profile,'historical suite admitted method-mode LOAD_ATTR')
            kind='LOAD_METHOD_314'
        if name in ('CALL','CALL_KW'):
            receiver_index=len(stack)-row.arg-(1 if name=='CALL_KW'else 0)-1
            method=method_carriers.get(stack[receiver_index])if method_profile else None
            kind='CALL_METHOD_314'if method is not None else 'APPLY_DECORATOR_314'if row.offset in applications else 'CALL'
        if op is not None:need(p.kind==kind,'compiler/source protocol classification differs')
        if name in ('RESUME','COPY_FREE_VARS','NOP','EXTENDED_ARG'):
            need(op is None,'encoding-only instruction became a program operation')
        elif name=='PUSH_NULL':stack.append(None)
        elif name=='COPY':stack.append(stack[-row.arg])
        elif name=='SWAP':stack[-1],stack[-row.arg]=stack[-row.arg],stack[-1]
        elif name=='LOAD_FAST_BORROW':
            need(arg in cells or arg in free,'borrow is not an original compiler cell reference')
            stack.append(cells.get(arg,free.get(arg)))
        elif name=='LOAD_LOCALS':stack.append(namespace[0])
        elif name=='LOAD_SMALL_INT':
            need(len(witness.stack_after)==len(stack)+1,'small literal result missing')
            value=witness.stack_after[-1];literal(value,arg);stack.append(value)
        elif name=='LOAD_CONST':
            record=constants.get(op.id)
            need(record is not None and record.constant_path==(row.arg,) and op.results==(record.reference,),
                 'original constant table slot/result differs')
            if type(arg)is CodeType:code_values[record.reference]=(row.arg,arg)
            else:constant_values[record.reference]=arg
            stack.append(record.reference)
        elif name=='MAKE_CELL':
            declared=[c for c in overlay.cells if c.operation==op.id]
            need(len(declared)==1 and declared[0].name==arg and arg not in cells,'cell allocation source differs')
            cells[arg]=normal(op)[0]
        elif name in ('LOAD_NAME','LOAD_GLOBAL'):
            expected=namespace if name=='LOAD_NAME' else namespace[1:]
            actual=operands(op);need(actual[:-1]==expected,'class L/G/saved-B lookup order differs');literal(actual[-1],arg)
            stack.append(normal(op)[0])
            if name=='LOAD_GLOBAL' and row.arg&1:stack.append(None)
        elif name in ('STORE_NAME','STORE_GLOBAL','DELETE_NAME'):
            actual=operands(op);owner=namespace[1] if name=='STORE_GLOBAL' else namespace[0]
            need(actual[0]==owner,'class mapping write targets the wrong namespace');literal(actual[1],arg)
            if name!='DELETE_NAME':need(actual[2:]==(stack.pop(),),'mapping write changed its original stack value')
        elif name in ('LOAD_DEREF','LOAD_FROM_DICT_OR_DEREF'):
            cell=cells.get(arg,free.get(arg));actual=operands(op)
            if name=='LOAD_DEREF':need(actual==(cell,),'deref lost its original cell')
            else:
                owner=stack.pop();need(actual[0]==owner and actual[2:]==(cell,),'class-deref mapping/cell priority differs');literal(actual[1],arg)
            stack.append(normal(op)[0])
        elif name=='STORE_DEREF':
            value=stack.pop();need(operands(op)==(cells.get(arg,free.get(arg)),value),'cell write dependency differs')
        elif name in ('BUILD_TUPLE','BUILD_LIST','BUILD_SET','BUILD_MAP'):
            count=row.arg*(2 if name=='BUILD_MAP' else 1);items=tuple(stack.pop()for _ in range(count))[::-1]
            need(operands(op)==items,'container packing input order differs')
            value=normal(op)[0];stack.append(value)
            if name=='BUILD_TUPLE':tuples[value]=items
        elif name=='MAKE_FUNCTION':
            code=stack.pop();need(code in code_values,'factory code was not read from its original slot')
            index,child=code_values[code];factory=factories.get(op.id)
            need(factory is not None and factory.code_reference==code and factory.constant_path==(index,)
                 and factory.free_names==tuple(child.co_freevars),'factory code/closure descriptor differs')
            need(operands(op)==(code,namespace[1]),'class local mapping was used as method globals')
            if factory.definition is not None:
                proof=independently_compiled.for_definition(factory.definition,factory.source)
                need(proof.code_path==evidence.code_path+(index,),'method body is not the original child definition')
            functions[factory.reference]=child;stack.append(normal(op)[0])
        elif name=='SET_FUNCTION_ATTRIBUTE':
            function=stack.pop();value=stack.pop();need(operands(op)==(function,value) and function in functions,'function attribute lost fresh factory identity')
            if row.arg==8:
                expected=tuple(cells.get(n,free.get(n))for n in functions[function].co_freevars)
                need(None not in expected and tuples.get(value)==expected,'closure field captures wrong/order cell references')
            stack.append(function)
        elif name=='LOAD_ATTR':
            owner=stack.pop();actual=operands(op)
            need(len(actual)==2 and actual[0]==owner,'attribute owner differs');literal(actual[1],arg)
            if row.arg&1:
                lookup=method_lookups.get(op.id);returned=normal(op)
                need(lookup is not None and returned==(lookup.callable,lookup.optional_self,lookup.has_self),
                     'method lookup lost its callable/self/boolean completion interface')
                consumed_cleanup(op)
                method_carriers[lookup.optional_self]=lookup
                stack.extend(returned[:2])
            else:stack.append(normal(op)[0])
        elif name in ('CALL','CALL_KW'):
            keyword=stack.pop()if name=='CALL_KW'else None
            args=tuple(stack.pop()for _ in range(row.arg))[::-1];receiver=stack.pop();callee=stack.pop()
            method=method_carriers.get(receiver)if method_profile else None
            if method is not None:
                record=method_calls.get(op.id)
                need(record is not None and record.lookup==method.operation and callee==method.callable,
                     'method CALL lost its original lookup/callable association')
                expected=(callee,receiver,method.has_self,*args,*((keyword,)if keyword is not None else ()))
            else:
                if receiver is not None:args=(receiver,*args)
                expected=(callee,*args,*((keyword,)if keyword is not None else ()))
            need(operands(op)==expected,'callable/receiver/arguments/selector were reordered')
            if method_profile:consumed_cleanup(op)
            link=next(x for x in metadata.operation_links if x.operation==op.id)
            from scar.ir.semantics_v2 import Opcode
            if row.offset in applications:
                need(link.opcode is None and link.semantic_operation is None,
                     'decorator application cannot masquerade as the original AST CALL')
            if link.opcode is Opcode.CALL:
                matches=[n for n in ast.walk(node)if isinstance(n,ast.Call)and
                    (n.lineno,n.end_lineno,n.col_offset,n.end_col_offset)==tuple(row.positions)]
                need(len(matches)==1,'source CALL lost its original AST occurrence')
                call=matches[0];sources=[x for x in metadata.use_links if x.operation==op.id]
                callee_sources=[x for x in sources if x.use==op.uses[0].id]
                need(len(callee_sources)==1 and callee_sources[0].source==_source_reference(prepared,call.func),
                     'source CALL callee Use has wrong original source')
            stack.append(normal(op)[0])
        elif name in ('BINARY_OP','UNARY_NEGATIVE','UNARY_INVERT','UNARY_NOT'):
            args=tuple(stack.pop()for _ in range(2 if name=='BINARY_OP'else 1))[::-1]
            need(operands(op)==args,'value-operation inputs differ');stack.append(normal(op)[0])
        elif name=='POP_TOP':
            value=stack.pop();need(op.uses[0].value==value,'discard changed its reference')
        elif name=='RETURN_VALUE':
            value=stack.pop();need(not stack and op.uses[-2].value==value,'normal completion must preserve its actual payload')
            if overlay.normal_payload is ClassNormalPayloadKind.CLASS_CELL:
                need(value==cells['__class__'],'class suite returned a value instead of the compiler class cell')
            else:need(value in constant_values and constant_values[value]is None,'class suite None return lost its original code-slot None')
        else:raise ValueError('class suite source: unadmitted compiler witness '+name)
        need(tuple(stack)==witness.stack_after,'original compiler result stack differs')
    if overlay.remaining is None:
        need(len(overlay.instructions)==len(rows) and rows[-1].opname=='RETURN_VALUE','suite silently dropped source/compiler suffix')
    else:
        need(len(overlay.instructions)<len(rows) and rows[len(overlay.instructions)].offset==overlay.remaining.first_offset,
             'remaining compiler continuation starts at wrong offset')
        need(tuple(stack)==overlay.remaining.stack_inputs,'remaining compiler continuation lost partial-evaluation inputs')
        selectors=tuple(dict.fromkeys(method_carriers[v].has_self for v in stack if v in method_carriers))
        expected=(*namespace,*free.values(),*cells.values(),*(v for v in stack if v is not None),*selectors)
        need(operands(operations[overlay.remaining.operation])==expected,
             'remaining continuation lost its exact frame/stack/method-selector inputs')
    need(set(cells)==set(overlay.interface.co_cellvars),'compiler-owned cells not allocated before suite completion')
    return {'valid':True,'source_compilation_replayed':True,'runtime_target_executed':False,
            'suite_complete':overlay.remaining is None,'effects_complete':False}
