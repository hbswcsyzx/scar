"""Source-compiled module prelude over existing mapping/world interfaces.

Compiler offsets are layout evidence, not runtime events or fabricated source
atoms. The historical profile retains a required boundary; the expanded profile
connects each known compiler macro. Deferred child bodies stay separate.
"""
from __future__ import annotations

import ast
import __future__
from dataclasses import dataclass, replace
import dis
from types import CodeType

from scar.ir.program.module_entries import (
    CompilerStructuredFrameBodyOverlay, FrameBodyProtocolKind as K,
    ModuleCompilerCellSlot, ModuleCompilerChild, ModuleCompilerGlobalRead,
    ModuleCompilerInstruction, ModuleCompilerPrologue,
)
from scar.ir.program.ids import RegionID
from scar.ir.program.model import Behavior, ExitKind, TerminatorKind
from scar.ir.program.source import GapKind
from scar.trace.code_snapshot import code_key


@dataclass(frozen=True, slots=True)
class CompilerPreludePlan:
    cells: tuple[ModuleCompilerCellSlot, ...]
    instructions: tuple[ModuleCompilerInstruction, ...]
    children: tuple[ModuleCompilerChild, ...]
    first_source_offset: int

    @property
    def required(self):
        return bool(self.cells or any(x.opcode not in ('RESUME','EXTENDED_ARG') for x in self.instructions))


def compiler_prelude_plan(code, tree=None):
    if type(code) is not CodeType or code.co_name != '<module>' or code.co_freevars:
        raise ValueError('compiler prefix needs its exact non-closure module root')
    all_rows=tuple(dis.get_instructions(code,adaptive=False,show_caches=False))
    rows=tuple(x for x in all_rows if x.opname!='EXTENDED_ARG')
    index=0;roles={};cells=[];children=[]
    while index<len(rows) and rows[index].opname=='MAKE_CELL':
        row=rows[index]
        if row.argval not in code.co_cellvars:
            raise ValueError('module MAKE_CELL does not name its compiler-owned local slot')
        cells.append(ModuleCompilerCellSlot(row.argval,code.co_cellvars.index(row.argval),row.offset))
        roles[row.offset]=('OWNED_CELL_ALLOCATION',row.argval,None);index+=1
    cells=tuple(sorted(cells,key=lambda x:x.ordinal))
    if tuple(x.name for x in cells)!=code.co_cellvars:
        raise ValueError('module compiler-owned cells lack their exact leading MAKE_CELL allocations')
    if index>=len(rows) or rows[index].opname!='RESUME' or rows[index].arg!=0:
        raise ValueError('module compiler prefix lacks its exact RESUME entry')
    roles[rows[index].offset]=('COMPILER_ENTRY',None,None);index+=1
    if type(tree) is not ast.Module:
        raise ValueError('module compiler prefix classification requires the original AST, not a child name')
    pending=list(tree.body);named_annotations=False
    while pending:
        node=pending.pop()
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef,ast.Lambda)):
            continue
        if isinstance(node,ast.AnnAssign) and isinstance(node.target,ast.Name) and node.simple:
            named_annotations=True
        pending.extend(ast.iter_child_nodes(node))
    generated_factory=named_annotations and not (code.co_flags & __future__.annotations.compiler_flag)
    if generated_factory:
        if not (index<len(rows) and rows[index].opname=='LOAD_CONST' and type(rows[index].argval) is CodeType
                and rows[index].argval.co_name=='__annotate__'):
            raise ValueError('module annotations lack their exact generated factory prefix')
        load=rows[index];child=load.argval
        # Source-owned module annotations and the actual compiler future flags
        # select this generated rule. A same-spelled user definition, including
        # one at the first statement, is left after this exact prefix boundary.
        window=rows[index:index+3]
        if len(window)!=3 or window[1].opname!='MAKE_FUNCTION' or window[2].opname!='STORE_NAME' or window[2].argval!='__annotate__' or child.co_freevars:
            raise ValueError('module generated annotation factory interface is unsupported')
        path=(load.arg,)
        if type(load.arg) is not int or code.co_consts[load.arg] is not child:
            raise ValueError('generated annotation child lost its exact constant slot')
        children.append(ModuleCompilerChild(path,code_key(child),child.co_name,tuple(child.co_freevars),
            tuple(ModuleCompilerGlobalRead(x.offset,x.argval) for x in dis.get_instructions(child)
                  if x.opname=='LOAD_GLOBAL' and type(x.argval)is str)))
        for row,role in zip(window,('DEFERRED_CHILD_CODE','DEFERRED_CHILD_FACTORY','NAMESPACE_FACTORY_WRITE')):
            roles[row.offset]=(role,row.argval if row.opname=='STORE_NAME' else None,path if row is load else None)
        index+=3
    if index+1<len(rows) and rows[index].opname=='BUILD_SET' and rows[index].arg==0 and rows[index+1].opname=='STORE_NAME' and rows[index+1].argval=='__conditional_annotations__':
        # This pair is the compiler's conditional-annotation namespace setup,
        # not content of the same-spelled compiler cell.
        if '__conditional_annotations__' not in code.co_cellvars:
            raise ValueError('conditional annotation setup lacks its compiler-owned layout')
        roles[rows[index].offset]=('NAMESPACE_SET_ALLOCATION',None,None)
        roles[rows[index+1].offset]=('NAMESPACE_SET_WRITE',rows[index+1].argval,None);index+=2
    if index<len(rows) and rows[index].opname=='SETUP_ANNOTATIONS':
        roles[rows[index].offset]=('ANNOTATIONS_NAMESPACE_SETUP',None,None);index+=1
    if index>=len(rows):
        raise ValueError('module compiler prefix has no remaining source/completion boundary')
    end=rows[index].offset
    instructions=[]
    for row in all_rows:
        if row.offset>=end:break
        role,name,path=roles.get(row.offset,('ENCODING_PREFIX',None,None))
        if row.offset not in roles and row.opname!='EXTENDED_ARG':
            raise ValueError('unrecognized instruction inside compiler module prefix')
        instructions.append(ModuleCompilerInstruction(row.offset,row.opname,row.arg,tuple(row.positions),role,name,path))
    return CompilerPreludePlan(cells,tuple(instructions),tuple(children),end)


def mark_memory(builder, identity):
    original=builder.operation_records[identity]
    marked=replace(original,behaviors=original.behaviors+(Behavior.MEMORY,))
    builder.operations[builder.operations.index(original)]=marked;builder.operation_records[identity]=marked


def build_compiler_region(builder):
    """Build only the known compiler prelude's interface, before AST statements."""
    if getattr(builder,'supports_expanded_compiler_prologue',False):
        return build_expanded_compiler_region(builder)
    from scar.analysis.program_lowering import _key, _REF
    plan=builder.compiler_plan
    if not plan.required:return None
    builder.function_context=RegionID(_key('module-compiler-prefix',builder.unit.initializer.wire,
        builder.unit.snapshot.fingerprint,builder.evidence.code_layout_key))
    builder.function_blocks=[]
    child=builder.new_block(builder.tree,extra_types=(_REF,_REF,_REF));world=child.state
    refs=builder.block_arguments[child.block][:-1]
    normal,_,identity=builder.invoke_results(child,builder.tree,
        tuple((value,builder.tree,'compiler-borrowed-namespace',i,None) for i,value in enumerate(refs)),
        result_types=(),failure_handler=lambda failed,error:builder.body_exit(failed,error,ExitKind.RAISE))
    builder.protocol(identity,K.REQUIRED_COMPILER_PROLOGUE,builder.tree);mark_memory(builder,identity)
    builder.body_exit(normal,builder.literal(builder.tree,None),ExitKind.NORMAL)
    builder.regions.append(replace(builder.assemble_region(world),label='required compiler-generated module prologue',parent=builder.frame_region))
    return builder.function_context,identity


def invoke_compiler_region(builder,cursor,child):
    if getattr(builder,'supports_expanded_compiler_prologue',False):
        return invoke_expanded_compiler_region(builder,cursor,child)
    if child is None:return cursor,None
    region,opaque=child
    cursor,_,identity=builder.invoke(cursor,builder.tree,
        tuple((value,builder.tree,'compiler-prefix-namespace',i,None) for i,value in enumerate(builder.entry_references)))
    original=builder.operation_records[identity];operation=replace(original,callee=region)
    builder.operations[builder.operations.index(original)]=operation;builder.operation_records[identity]=operation
    mark_memory(builder,identity);builder.protocol(identity,K.INVOKE_COMPILER_PROLOGUE,builder.tree)
    plan=builder.compiler_plan
    record=ModuleCompilerPrologue(builder.declaration.compilation,plan.cells,plan.instructions,plan.children,
        plan.first_source_offset,region,opaque,identity,cursor.block)
    builder.gap(GapKind.EFFECT_SUMMARY,builder.tree,
        'compiler-generated prefix has an exact layout and connected normal/raise/world interface; internal cell allocation, namespace setup and deferred factory remain required expansion')
    from scar.ir.program.module_entries import ModuleFrontier
    builder.module_frontiers.append(ModuleFrontier(builder.unit,'COMPILER_PROLOGUE_REQUIRED_EXPANSION',
        'only the exact compiler-generated entry prefix remains internally unexpanded; owned cell slots, namespace setup and deferred child facts are separate from original AST statements'))
    return cursor,record


def validate_compiler_prologue(result,code_evidence,context):
    """Independently read original code layout and actual core endpoints."""
    from scar.ir.program.model import ReferenceValue,StateVersionValue,LiteralOrigin
    from scar.ir.program.module_entries import RequiredModuleExpansion
    overlay=result.module
    from scar.ir.program import module_entries as module_ir
    if type(overlay) is getattr(module_ir,'ExpandedCompilerFrameBodyOverlay',None):
        return validate_expanded_compiler_prologue(result,code_evidence,context)
    if type(overlay)is not CompilerStructuredFrameBodyOverlay:
        raise ValueError('compiler prologue requires its explicit overlay variant')
    plan=compiler_prelude_plan(code_evidence.code,context.tree)
    prefix=overlay.compiler_prologue
    if (prefix is not None)!=plan.required:
        raise ValueError('compiler prefix presence differs from the original module layout')
    if prefix is None:return None
    if (prefix.compilation!=code_evidence.to_reference() or prefix.cells!=plan.cells or prefix.instructions!=plan.instructions
        or prefix.children!=plan.children or prefix.first_source_offset!=plan.first_source_offset
        or prefix.required_expansion is not RequiredModuleExpansion.REQUIRED):
        raise ValueError('compiler prefix facts differ from independent source compilation')
    return validate_compiler_prologue_core(overlay,result.graph)


def validate_compiler_prologue_core(overlay,graph):
    """Join stored declarations to real graph ports; no source replay claim."""
    from scar.ir.program import module_entries as module_ir
    if type(overlay) is getattr(module_ir,'ExpandedCompilerFrameBodyOverlay',None):
        return validate_expanded_compiler_prologue_core(overlay,graph)
    from scar.ir.program.model import ReferenceValue,StateVersionValue,LiteralOrigin
    from scar.ir.program.source_subjects import SourceCompilationFrameRoot,FrameKind,MappingFramePorts
    if type(overlay)is not CompilerStructuredFrameBodyOverlay:
        raise ValueError('compiler prologue requires its explicit overlay variant')
    prefix=overlay.compiler_prologue
    if (len(graph.frame_roots)!=1 or type(graph.frame_roots[0])is not SourceCompilationFrameRoot
        or graph.frame_roots[0].kind is not FrameKind.MODULE
        or graph.frame_roots[0].scope!=overlay.root_scope
        or type(graph.frame_roots[0].entry)is not MappingFramePorts
        or graph.frame_roots[0].entry.closure_cells
        or graph.frame_roots[0].code!=overlay.declaration.compilation):
        raise ValueError('compiler module must retain its source-compiled root and real mapping entry ABI')
    if prefix is None:return None
    if prefix.compilation!=overlay.declaration.compilation:
        raise ValueError('compiler prefix has another module compilation')
    regions={r.id:r for r in graph.regions};ops={o.id:o for o in graph.operations};values={v.id:v for v in graph.values}
    blocks={b.id:b for r in graph.regions for b in r.blocks};protocols={p.operation:p for p in overlay.protocols}
    region=regions.get(prefix.region);opaque=ops.get(prefix.operation);call=ops.get(prefix.invocation)
    if (region is None or region.parent!=graph.root or opaque is None or call is None or call.callee!=region.id
        or protocols.get(opaque.id) is None or protocols[opaque.id].kind is not K.REQUIRED_COMPILER_PROLOGUE
        or protocols.get(call.id) is None or protocols[call.id].kind is not K.INVOKE_COMPILER_PROLOGUE):
        raise ValueError('compiler prefix lost its actual required region and invoking operation')
    root=graph.frame_roots[0];entry=root.entry;refs=(entry.locals_namespace,entry.globals_namespace,entry.builtins_namespace)
    parent=regions[graph.root];parent_entry=blocks[parent.entry]
    if (len(parent_entry.operations)!=2 or parent_entry.operations[-1]!=call.id
        or protocols[parent_entry.operations[0]].kind.value!='FRAME_ENTER'
        or ops[parent_entry.operations[0]].results!=(call.uses[-1].value,)):
        raise ValueError('compiler prefix must consume the actual frame-entry world before source statements')
    if (tuple(u.value for u in call.uses[:-1])!=refs or any(type(values[u.value])is not ReferenceValue for u in call.uses[:-1])
        or type(values[call.uses[-1].value])is not StateVersionValue
        or call.effects_complete or opaque.effects_complete
        or Behavior.MEMORY not in call.behaviors or Behavior.MEMORY not in opaque.behaviors):
        raise ValueError('compiler prefix must preserve original namespace/reference/world ports and open effects')
    child_entry=blocks[region.entry]
    child_ops=[ops[key] for block in region.blocks for key in block.operations]
    links=[link for link in overlay.operation_links if link.operation==opaque.id]
    if (len(child_ops)!=3 or child_entry.operations!=(opaque.id,)
        or len(links)!=1 or links[0].source!=overlay.declaration.unit
        or links[0].semantic_operation is not None or links[0].opcode is not None):
        raise ValueError('compiler prefix must remain exactly its declared generated boundary, without fabricated source operations')
    if tuple(u.value for u in opaque.uses)!=child_entry.arguments:
        raise ValueError('compiler prefix internal boundary does not consume its actual entry ports')
    if (call.terminator is None or call.terminator.kind is not TerminatorKind.INVOKE
        or opaque.terminator is None or opaque.terminator.kind is not TerminatorKind.INVOKE
        or tuple(e.kind for e in call.terminator.successors)!=(ExitKind.NORMAL,ExitKind.RAISE)
        or call.terminator.successors[0].block!=prefix.normal):
        raise ValueError('compiler prefix lost its paired normal/raise continuation')
    normal=next(e for e in opaque.terminator.successors if e.kind is ExitKind.NORMAL)
    failure=next(e for e in opaque.terminator.successors if e.kind is ExitKind.RAISE)
    if (len(blocks[normal.block].arguments)!=1 or len(blocks[failure.block].arguments)!=3
        or not any(e.kind is ExitKind.RAISE and len(e.types)==3 for e in region.exits)):
        raise ValueError('compiler prefix internal world/paired exception interface differs')
    for block,kind,expected in ((blocks[normal.block],ExitKind.NORMAL,(None,)),
                                (blocks[failure.block],ExitKind.RAISE,())):
        if len(block.operations)!=1:
            raise ValueError('compiler prefix completion must forward its original boundary results directly')
        term=ops[block.operations[0]].terminator
        if term.kind is not (TerminatorKind.RETURN if kind is ExitKind.NORMAL else TerminatorKind.RAISE):
            raise ValueError('compiler prefix completion kind differs')
        by_use={use.id:use.value for use in ops[block.operations[0]].uses}
        payload=tuple(by_use[use] for use in term.values)
        if kind is ExitKind.RAISE:
            if payload!=block.arguments:
                raise ValueError('compiler prefix raise must preserve its own exception, traceback and post-world')
        elif (len(payload)!=2 or payload[-1]!=block.arguments[-1]
              or type(values[payload[0]].origin)is not LiteralOrigin or values[payload[0]].origin.value is not None):
            raise ValueError('compiler prefix internal normal marker/post-world differs')
    return prefix


@dataclass(frozen=True,slots=True)
class _ExpandedCompilerChild:
    region: RegionID
    cells: tuple
    operations: tuple
    constant_reads: tuple


def _compiler_return(builder,cursor,cells):
    """Return internal frame handles; this Region is not a Python call frame."""
    from scar.ir.program.ids import OperationID
    from scar.ir.program.model import Operation,Terminator
    from scar.ir.program.source import SourceRole
    identity=builder.fresh(OperationID,'compiler-prefix-return')
    refs=tuple(builder.use(identity,value,builder.tree,'compiler-owned-cell',i) for i,value in enumerate(cells))
    state=builder.use(identity,cursor.state,builder.tree,'compiler-post-world',0)
    uses=(*refs,state)
    builder.emit(cursor,Operation(identity,'compiler-prefix-return',(Behavior.CONTROL,),uses,
        terminator=Terminator(TerminatorKind.RETURN,exit='normal',values=tuple(u.id for u in uses))),
        builder.tree,SourceRole.CONTROL)


def build_expanded_compiler_region(builder):
    """Expand compiler macros using the original namespace/world interfaces.

    Successful cell creation installs a frame-owned slot. Only the handles of
    those slots cross the normal Region interface; they are not closure inputs
    or aliases of same-spelled namespace bindings. A failing prefix owns the
    cleanup of its partially initialized slots before returning the same pair.
    """
    from scar.analysis.program_lowering import _key,_REF
    from scar.ir.program.ids import OperationID,ValueID
    from scar.ir.program.model import (AccessMode,Operation,OperationResult,ReferenceValue,StateAccess)
    from scar.ir.program.source import SourceRole
    from scar.ir.program.module_entries import ModuleCompilerOperation,ModuleCompilerConstant
    from scar.ir.program.state_addresses import AddressEffect,NamespaceKey,ReferenceOwner
    plan=builder.compiler_plan
    if not plan.required:return None
    builder.function_context=RegionID(_key('module-compiler-prefix-ops',builder.unit.initializer.wire,
        builder.unit.snapshot.fingerprint,builder.evidence.code_layout_key))
    builder.function_blocks=[]
    cursor=builder.new_block(builder.tree,extra_types=(_REF,_REF,_REF));world=cursor.state
    refs=builder.block_arguments[cursor.block][:-1]
    held=[];cells=[];cell_by_name={};steps=[];constants=[];stack=None

    def retain(at,value,role):
        builder.frame_transition(at,builder.tree,((value,builder.tree,role),),K.COMPILER_RETAIN_OWNED)
        held.append(value)

    def invoke(at,instruction,kind,inputs,*,result=False,memory=False,consumed=()):
        def failed(failure,error):
            for value in reversed([value for value in held if value not in consumed]):
                builder.frame_transition(failure,builder.tree,((value,builder.tree,'compiler-prefix-unwind'),),K.COMPILER_RELEASE_OWNED)
            builder.body_exit(failure,error,ExitKind.RAISE)
        at,outputs,identity=builder.invoke_results(at,builder.tree,tuple(inputs),
            result_types=(_REF,) if result else (),failure_handler=failed)
        builder.protocol(identity,kind,builder.tree)
        if memory:mark_memory(builder,identity)
        steps.append(ModuleCompilerOperation(instruction.role,(instruction.offset,),identity))
        for value in consumed:
            if value not in held:raise ValueError('compiler stack consumption has no outstanding hold')
            held.remove(value)
        return at,outputs[0] if outputs else None

    for instruction in plan.instructions:
        role=instruction.role
        if role in ('COMPILER_ENTRY','ENCODING_PREFIX'):continue
        if role=='OWNED_CELL_ALLOCATION':
            cursor,value=invoke(cursor,instruction,K.COMPILER_MAKE_CELL,(),result=True,memory=True)
            cells.append(value);cell_by_name[instruction.name]=value;retain(cursor,value,'compiler-owned-cell')
        elif role=='DEFERRED_CHILD_CODE':
            if stack is not None:raise ValueError('compiler code-slot read would overwrite a pending value')
            path=instruction.child_code_path
            if path is None or len(path)!=1 or type(builder.evidence.code.co_consts[path[0]]) is not CodeType:
                raise ValueError('compiler factory requires its exact child code-table slot')
            identity=builder.fresh(OperationID,'compiler-code-reference')
            before=builder.use(identity,cursor.state,builder.tree,'compiler-code-world',0)
            value=ReferenceValue(builder.fresh(ValueID,'compiler-code-reference'),builder.function_context,OperationResult(identity,0))
            builder.add_value(value);builder.link_value(value,builder.tree,SourceRole.EXPRESSION)
            builder.emit(cursor,Operation(identity,'compiler-code-reference',(Behavior.READ,),(before,),(value.id,),
                (StateAccess(builder.world,before.id,AccessMode.READ),),effects_complete=False),builder.tree,SourceRole.EXPRESSION)
            builder.protocol(identity,K.COMPILER_READ_CODE_CONSTANT,builder.tree)
            steps.append(ModuleCompilerOperation(role,(instruction.offset,),identity))
            constants.append(ModuleCompilerConstant(identity,path,builder.evidence.code_layout_key));stack=value.id
        elif role=='DEFERRED_CHILD_FACTORY':
            if stack is None:raise ValueError('compiler factory lost its original code reference')
            cursor,stack=invoke(cursor,instruction,K.COMPILER_MAKE_FUNCTION,
                ((stack,builder.tree,'compiler-function-code',0,None),
                 (refs[1],builder.tree,'compiler-function-globals',0,None)),result=True,memory=True)
            retain(cursor,stack,'compiler-stack-payload')
        elif role=='NAMESPACE_SET_ALLOCATION':
            if stack is not None:raise ValueError('compiler set allocation would overwrite a pending value')
            cursor,stack=invoke(cursor,instruction,K.COMPILER_BUILD_SET,(),result=True,memory=True)
            retain(cursor,stack,'compiler-stack-payload')
        elif role in ('NAMESPACE_FACTORY_WRITE','NAMESPACE_SET_WRITE'):
            if stack is None or instruction.name is None:raise ValueError('compiler namespace store lost its input/key')
            key=builder.literal(builder.tree,instruction.name)
            cursor,_=invoke(cursor,instruction,K.COMPILER_STORE_NAME,
                ((refs[0],builder.tree,'compiler-locals-owner',0,None),
                 (key,builder.tree,'compiler-namespace-key',0,None),
                 (stack,builder.tree,'compiler-assigned-reference',0,None)),consumed=(stack,))
            operation=builder.operation_records[steps[-1].operation]
            builder._addresses(operation.id,(AddressEffect(ReferenceOwner(operation.uses[0].id),
                (NamespaceKey(operation.uses[1].id),),AccessMode.WRITE),));stack=None
        elif role=='ANNOTATIONS_NAMESPACE_SETUP':
            key=builder.literal(builder.tree,'__annotations__')
            cursor,_=invoke(cursor,instruction,K.COMPILER_SETUP_ANNOTATIONS,
                ((refs[0],builder.tree,'compiler-locals-owner',0,None),
                 (key,builder.tree,'compiler-namespace-key',0,None)),memory=True)
            operation=builder.operation_records[steps[-1].operation]
            builder._addresses(operation.id,tuple(AddressEffect(ReferenceOwner(operation.uses[0].id),
                (NamespaceKey(operation.uses[1].id),),mode) for mode in (AccessMode.READ,AccessMode.WRITE)))
        else:raise ValueError('compiler macro role has no expanded rule: '+role)
    if stack is not None or held!=cells:
        raise ValueError('compiler prefix completion has a leaked stack reference or lost frame cell')
    ordered_cells=tuple(cell_by_name[slot.name]for slot in plan.cells)
    _compiler_return(builder,cursor,ordered_cells)
    region=builder.assemble_region(world)
    region=replace(region,label='expanded compiler-generated module prologue',parent=builder.frame_region,
        exits=tuple(replace(port,types=(_REF,)*len(cells)+(builder.state_type,))
                    if port.kind is ExitKind.NORMAL else port for port in region.exits))
    builder.regions.append(region)
    return _ExpandedCompilerChild(region.id,ordered_cells,tuple(steps),tuple(constants))


def invoke_expanded_compiler_region(builder,cursor,child):
    from scar.analysis.program_lowering import _REF
    from scar.ir.program.module_entries import ExpandedModuleCompilerPrologue,ModuleFrontier
    if child is None:
        builder.compiler_cell_references=()
        return cursor,None
    cursor,cells,identity=builder.invoke_results(cursor,builder.tree,
        tuple((value,builder.tree,'compiler-prefix-namespace',i,None) for i,value in enumerate(builder.entry_references)),
        result_types=(_REF,)*len(child.cells))
    original=builder.operation_records[identity]
    replacement=replace(original,callee=child.region)
    builder.operations[builder.operations.index(original)]=replacement;builder.operation_records[identity]=replacement
    mark_memory(builder,identity);builder.protocol(identity,K.INVOKE_EXPANDED_COMPILER_PROLOGUE,builder.tree)
    builder.compiler_cell_references=tuple(cells)
    builder.active_temporaries.extend(cells)
    plan=builder.compiler_plan
    record=ExpandedModuleCompilerPrologue(builder.declaration.compilation,plan.cells,plan.instructions,plan.children,
        plan.first_source_offset,child.region,identity,cursor.block,tuple(cells),child.operations,child.constant_reads)
    builder.gap(GapKind.EFFECT_SUMMARY,builder.tree,
        'compiler macros retain exact operands, owned cells, partial namespace addresses and ordered post-worlds; runtime identity and complete effects remain open')
    if plan.children:
        builder.module_frontiers.append(ModuleFrontier(builder.unit,'COMPILER_DEFERRED_CHILD_REQUIRED_EXPANSION',
            'compiler factory/global-read facts are recorded; the generated child code body is deferred and still requires its own canonical expansion'))
    return cursor,record


def validate_expanded_compiler_prologue(result,code_evidence,context):
    """Check generated source layout independently of recorded operation joins."""
    from scar.ir.program.module_entries import ExpandedCompilerFrameBodyOverlay
    overlay=result.module
    if type(overlay) is not ExpandedCompilerFrameBodyOverlay:
        raise ValueError('expanded compiler prefix needs its explicit source profile')
    plan=compiler_prelude_plan(code_evidence.code,context.tree);prefix=overlay.compiler_prologue
    if (prefix is not None)!=plan.required:
        raise ValueError('expanded compiler prefix presence differs from original source compilation')
    if prefix is not None and (prefix.compilation!=code_evidence.to_reference()
            or prefix.cells!=plan.cells or prefix.instructions!=plan.instructions
            or prefix.children!=plan.children or prefix.first_source_offset!=plan.first_source_offset):
        raise ValueError('expanded compiler prefix differs from the independently compiled source plan')
    return validate_expanded_compiler_prologue_core(overlay,result.graph)


def validate_expanded_compiler_prologue_core(overlay,graph):
    """Check exact compiler macro ports, normal flow, cleanup and cell escape.

    This is a structural join against saved compilation declarations. A caller
    which needs source semantics must also run the independent source-plan
    check above. It does not turn partial namespace effects into content facts.
    """
    from scar.ir.program.module_entries import ExpandedCompilerFrameBodyOverlay
    from scar.ir.program.model import (AccessMode,BlockArgument,CompletionResult,LiteralOrigin,
        OperationResult,ReferenceValue,StateVersionValue,ValueKind,ValueType,value_type)
    from scar.ir.program.source_subjects import FrameKind,MappingFramePorts,SourceCompilationFrameRoot
    from scar.ir.program.state_addresses import (AddressCoverage,InvokeStateOperand,NamespaceKey,ReferenceOwner)

    def need(condition,detail):
        if not condition:raise ValueError('expanded compiler prefix: '+detail)
    need(type(overlay) is ExpandedCompilerFrameBodyOverlay,'explicit overlay missing')
    need(len(graph.frame_roots)==1,'root frame is not unique')
    frame=graph.frame_roots[0]
    need(type(frame) is SourceCompilationFrameRoot and frame.kind is FrameKind.MODULE
         and type(frame.entry) is MappingFramePorts and not frame.entry.closure_cells
         and frame.scope==overlay.root_scope and frame.code==overlay.declaration.compilation,
         'original mapping frame/compiler root differs')
    prefix=overlay.compiler_prologue
    if prefix is None:return None
    need(prefix.compilation==frame.code,'prefix compilation differs from frame')
    regions={r.id:r for r in graph.regions};ops={o.id:o for o in graph.operations};values={v.id:v for v in graph.values}
    blocks={b.id:b for r in graph.regions for b in r.blocks}
    owners={op:(r.id,b.id)for r in graph.regions for b in r.blocks for op in b.operations}
    protocols={p.operation:p for p in overlay.protocols}
    links={p.operation:p for p in overlay.operation_links}
    use_links={(p.operation,p.use):p for p in overlay.use_links}
    refinements={p.site.operation:p for p in graph.state_address_refinements}
    region=regions.get(prefix.region);call=ops.get(prefix.invocation)
    need(region is not None and region.parent==graph.root and call is not None
         and call.callee==region.id and owners[call.id][0]==graph.root
         and protocols[call.id].kind is K.INVOKE_EXPANDED_COMPILER_PROLOGUE,
         'child region/call linkage differs')
    root=regions[graph.root];root_entry=blocks[root.entry];entry=blocks[region.entry]
    need(len(root_entry.operations)==2 and root_entry.operations[-1]==call.id
         and protocols[root_entry.operations[0]].kind.value=='FRAME_ENTER'
         and ops[root_entry.operations[0]].results==(call.uses[-1].value,),
         'compiler macros must run after the real frame enter, before original source')
    parent_refs=(frame.entry.locals_namespace,frame.entry.globals_namespace,frame.entry.builtins_namespace)
    need(tuple(u.value for u in call.uses[:-1])==parent_refs and len(entry.arguments)==4
         and all(type(values[v]) is ReferenceValue for v in entry.arguments[:-1]),
         'borrowed namespaces differ from the original entry')
    state=value_type(values[entry.arguments[-1]]);ref=ValueType(ValueKind.REFERENCE)
    need(state.kind is ValueKind.STATE and value_type(values[call.uses[-1].value])==state,
         'child and caller state domains differ')
    refs=entry.arguments[:-1]

    def invocation(op,ninputs,nresults,memory):
        need(op.callee is None or op.id==call.id,'compiler macro hides another callee')
        need(not op.effects_complete and len(op.uses)==ninputs+1
             and all(type(values[u.value]) is ReferenceValue for u in op.uses[:-1])
             and value_type(values[op.uses[-1].value])==state
             and op.invoke_arguments==tuple(u.id for u in op.uses)
             and set(op.behaviors)=={Behavior.CONTROL,Behavior.READ,Behavior.WRITE}|({Behavior.MEMORY}if memory else set())
             and op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE
             and tuple((c.kind,c.types)for c in op.completions)==
                 ((ExitKind.NORMAL,(ref,)*nresults+(state,)),(ExitKind.RAISE,(ref,ref,state)))
             and tuple(e.kind for e in op.terminator.successors)==(ExitKind.NORMAL,ExitKind.RAISE)
             and all(e.arguments==tuple(CompletionResult(i)for i in range(len(c.types)))
                     for e,c in zip(op.terminator.successors,op.completions)),
             'compiler invoke operand/behavior/normal/paired-raise interface differs')
        normal,failure=(blocks[e.block]for e in op.terminator.successors)
        need(tuple(value_type(values[v])for v in normal.arguments)==(ref,)*nresults+(state,)
             and tuple(value_type(values[v])for v in failure.arguments)==(ref,ref,state),
             'compiler landing types differ')
        return normal,failure

    caller_normal,_=invocation(call,3,len(prefix.cells),True)
    need(caller_normal.id==prefix.normal and caller_normal.arguments[:-1]==prefix.cell_values,
         'parent normal cell handles differ from their CompletionResult indices')
    need(tuple((p.kind,p.types)for p in region.exits)==
         ((ExitKind.NORMAL,(ref,)*len(prefix.cells)+(state,)),(ExitKind.RAISE,(ref,ref,state))),
         'child exit interface must retain cells/world and original paired raise')
    meaningful=[p for p in prefix.instructions if p.role not in ('COMPILER_ENTRY','ENCODING_PREFIX')]
    need(len(prefix.operations)==len(meaningful)
         and all(p.role==i.role and p.offsets==(i.offset,)for p,i in zip(prefix.operations,meaningful)),
         'macro coverage/order does not match exact compiler prefix')
    mapped={p.operation:p for p in prefix.operations}
    need(all(key in ops and owners[key][0]==region.id and links[key].source==overlay.declaration.unit
             and links[key].semantic_operation is None and links[key].opcode is None for key in mapped),
         'compiler operations invented source definitions or escaped their region')
    constants={p.operation:p for p in prefix.constant_reads}
    need(set(constants)<={p.operation for p in prefix.operations},'code provenance lacks its macro')
    expected_kinds={'OWNED_CELL_ALLOCATION':K.COMPILER_MAKE_CELL,'DEFERRED_CHILD_CODE':K.COMPILER_READ_CODE_CONSTANT,
        'DEFERRED_CHILD_FACTORY':K.COMPILER_MAKE_FUNCTION,'NAMESPACE_FACTORY_WRITE':K.COMPILER_STORE_NAME,
        'NAMESPACE_SET_ALLOCATION':K.COMPILER_BUILD_SET,'NAMESPACE_SET_WRITE':K.COMPILER_STORE_NAME,
        'ANNOTATIONS_NAMESPACE_SETUP':K.COMPILER_SETUP_ANNOTATIONS}

    def literal(value,expected):
        origin=values[value].origin
        need(type(origin) is LiteralOrigin and type(origin.value)is type(expected) and origin.value==expected,
             'namespace key is not its exact original compiler string')

    def transition(op,current,expected_kind,value,role):
        need(protocols.get(op.id) is not None and protocols[op.id].kind is expected_kind
             and len(op.uses)==2 and op.uses[0].value==value and op.uses[1].value==current
             and len(op.results)==1 and value_type(values[op.results[0]])==state
             and set(op.behaviors)=={Behavior.READ,Behavior.WRITE,Behavior.MEMORY}
             and op.terminator is None and not op.effects_complete
             and len(op.accesses)==1 and op.accesses[0].before==op.uses[1].id
             and op.accesses[0].after==op.results[0] and op.accesses[0].mode is AccessMode.READ_WRITE
             and use_links[(op.id,op.uses[0].id)].role==role,
             'owned-reference transition lost its original value/current world/role')
        return op.results[0]

    failure_operations=set()
    def failure_path(block,held):
        current=block.arguments[-1];expected=tuple(reversed(held))
        need(len(block.operations)==len(expected)+1,'failure cleanup has missing/extra actions')
        failure_operations.update(block.operations)
        for identity,value in zip(block.operations,expected):
            current=transition(ops[identity],current,K.COMPILER_RELEASE_OWNED,value,'compiler-prefix-unwind')
        final=ops[block.operations[-1]]
        need(final.behaviors==(Behavior.CONTROL,) and not final.results and not final.accesses
             and final.callee is None and len(final.uses)==3
             and final.terminator is not None and final.terminator.kind is TerminatorKind.RAISE
             and final.terminator.values==tuple(u.id for u in final.uses)
             and tuple(next(u.value for u in final.uses if u.id==key)for key in final.terminator.values)
                 ==(*block.arguments[:-1],current),
             'failure cleanup changed its original exception/traceback pair or post-world')

    corridor=[];current_block=entry;seen=set()
    while current_block.id not in seen:
        seen.add(current_block.id);corridor.extend(ops[x]for x in current_block.operations)
        terminal=corridor[-1].terminator
        if terminal.kind is TerminatorKind.RETURN:break
        need(terminal.kind is TerminatorKind.INVOKE,'compiler normal corridor contains an undeclared branch')
        current_block=blocks[next(e.block for e in terminal.successors if e.kind is ExitKind.NORMAL)]
    else:raise ValueError('expanded compiler prefix: normal corridor cycles')
    need([o.id for o in corridor if o.id in mapped]==[p.operation for p in prefix.operations],
         'normal CFG reorders or disconnects original compiler macros')
    positions={o.id:i for i,o in enumerate(corridor)}
    held=[];cells=[];cell_by_name={};stack=None;current=entry.arguments[-1]
    used_constants=set();used_retains=set()
    for record,instruction in zip(prefix.operations,meaningful):
        op=ops[record.operation];role=record.role
        need(protocols[op.id].kind is expected_kinds.get(role),'compiler role/protocol differs')
        if role=='DEFERRED_CHILD_CODE':
            need(stack is None and op.id in constants and op.terminator is None and op.behaviors==(Behavior.READ,)
                 and len(op.uses)==len(op.results)==len(op.accesses)==1 and op.uses[0].value==current
                 and op.accesses[0].before==op.uses[0].id and op.accesses[0].mode is AccessMode.READ
                 and op.accesses[0].after is None and not op.effects_complete
                 and type(values[op.results[0]]) is ReferenceValue,
                 'code slot read is not its original borrowed reference/current-world read')
            provenance=constants[op.id]
            need(provenance.constant_path==instruction.child_code_path
                 and provenance.code_key==prefix.compilation.code_layout_key
                 and any(x.code_path==provenance.constant_path for x in prefix.children),
                 'generated code reference lost its exact compiler child slot')
            stack=op.results[0];used_constants.add(op.id);continue
        ninputs={'OWNED_CELL_ALLOCATION':0,'DEFERRED_CHILD_FACTORY':2,'NAMESPACE_SET_ALLOCATION':0,
                 'NAMESPACE_FACTORY_WRITE':3,'NAMESPACE_SET_WRITE':3,'ANNOTATIONS_NAMESPACE_SETUP':2}[role]
        result=role in ('OWNED_CELL_ALLOCATION','DEFERRED_CHILD_FACTORY','NAMESPACE_SET_ALLOCATION')
        normal,failure=invocation(op,ninputs,int(result),role not in ('NAMESPACE_FACTORY_WRITE','NAMESPACE_SET_WRITE'))
        need(op.uses[-1].value==current,'compiler macro lost its exact preceding post-world')
        consumed=()
        if role=='DEFERRED_CHILD_FACTORY':
            need(stack is not None and tuple(u.value for u in op.uses[:-1])==(stack,refs[1]),
                 'generated factory code/G inputs differ; class locals are not globals')
        if role in ('NAMESPACE_FACTORY_WRITE','NAMESPACE_SET_WRITE'):
            need(stack is not None and op.uses[0].value==refs[0] and op.uses[2].value==stack,
                 'compiler namespace store lost its distinct payload/local owner')
            literal(op.uses[1].value,instruction.name);consumed=(stack,)
        if role=='ANNOTATIONS_NAMESPACE_SETUP':
            need(op.uses[0].value==refs[0],'annotation setup owner is not its original locals namespace')
            literal(op.uses[1].value,'__annotations__')
        if role in ('NAMESPACE_FACTORY_WRITE','NAMESPACE_SET_WRITE','ANNOTATIONS_NAMESPACE_SETUP'):
            address=refinements.get(op.id);modes=(AccessMode.READ,AccessMode.WRITE) if role=='ANNOTATIONS_NAMESPACE_SETUP' else(AccessMode.WRITE,)
            need(address is not None and type(address.site)is InvokeStateOperand
                 and address.site.state_use==op.uses[-1].id and address.coverage is AddressCoverage.PARTIAL
                 and len(address.effects)==len(modes)
                 and all(type(e.owner)is ReferenceOwner and e.owner.use==op.uses[0].id
                         and len(e.path)==1 and type(e.path[0])is NamespaceKey and e.path[0].key==op.uses[1].id
                         and e.mode is mode for e,mode in zip(address.effects,modes)),
                 'namespace address must retain its partial original owner/key/state Uses')
        failure_path(failure,[x for x in held if x not in consumed])
        held=[x for x in held if x not in consumed];current=normal.arguments[-1]
        if result:
            value=normal.arguments[0]
            following=corridor[positions[op.id]+1]
            current=transition(following,current,K.COMPILER_RETAIN_OWNED,value,
                'compiler-owned-cell' if role=='OWNED_CELL_ALLOCATION' else 'compiler-stack-payload')
            held.append(value);used_retains.add(following.id)
            if role=='OWNED_CELL_ALLOCATION':cells.append(value);cell_by_name[instruction.name]=value
            else:stack=value
        if consumed:stack=None
    need(set(constants)==used_constants and held==cells and stack is None,'compiler completion lost code provenance or leaked temporary')
    need({o.id for o in corridor}==set(mapped)|used_retains|{corridor[-1].id},'undeclared normal compiler actions')
    returned=corridor[-1];ordered_cells=tuple(cell_by_name[slot.name]for slot in prefix.cells)
    need(returned.behaviors==(Behavior.CONTROL,) and not returned.results and not returned.accesses
         and returned.callee is None and len(returned.uses)==len(cells)+1
         and returned.terminator.kind is TerminatorKind.RETURN
         and returned.terminator.values==tuple(u.id for u in returned.uses)
         and tuple(next(u.value for u in returned.uses if u.id==key)for key in returned.terminator.values)==(*ordered_cells,current),
         'normal completion must forward exactly its installed frame cells and latest world')
    child_operations={identity for block in region.blocks for identity in block.operations}
    need(child_operations=={o.id for o in corridor}|failure_operations,
         'child region contains operations outside its checked normal and failure corridors')
    need(all(links[identity].source==overlay.declaration.unit
             and links[identity].semantic_operation is None and links[identity].opcode is None
             for identity in child_operations),
         'generated compiler actions cannot acquire fabricated source operations')
    need(len(cells)==len(prefix.cells),'MAKE_CELL values and declared slots differ')
    # Cell handles must remain live on every parent frame exit which is
    # dominated by successful prefix completion. Earlier/failing entry paths
    # cannot receive these values (ordinary SSA validation checks this too).
    parent_blocks={b.id:b for b in root.blocks};pred={b:set()for b in parent_blocks}
    for b in root.blocks:
        term=ops[b.operations[-1]].terminator
        for edge in term.successors if term is not None else ():
            if edge.block in pred:pred[edge.block].add(b.id)
    reachable={root.entry};pending=[root.entry]
    while pending:
        b=pending.pop();term=ops[parent_blocks[b].operations[-1]].terminator
        for edge in term.successors if term is not None else ():
            if edge.block in parent_blocks and edge.block not in reachable:
                reachable.add(edge.block);pending.append(edge.block)
    dom={b:({b}if b==root.entry else set(reachable))for b in reachable};changed=True
    while changed:
        changed=False
        for b in reachable-{root.entry}:
            parents=pred[b]&reachable;value={b}|(set.intersection(*(dom[p]for p in parents))if parents else set())
            if value!=dom[b]:dom[b]=value;changed=True
    for b in root.blocks:
        for identity in b.operations:
            marker=protocols.get(identity)
            if marker is None or marker.kind.value not in ('FRAME_EXIT','FRAME_EXIT_EXCEPTION_PACKET'):continue
            if prefix.normal not in dom.get(b.id,set()):continue
            held_values={u.value for u in ops[identity].uses if use_links[(identity,u.id)].role=='held-temporary'}
            need(set(prefix.cell_values)<=held_values,'installed compiler cells were lost before their parent frame exit')
    return prefix
