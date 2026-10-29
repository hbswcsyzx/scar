"""Source-compiled module prelude over existing mapping/world interfaces.

Compiler offsets are layout evidence, not runtime events or fabricated source
atoms. The exact prelude remains one required expansion before the original AST
suite. Owned cells, namespace writes and deferred child reads stay distinct.
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
