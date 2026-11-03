"""Shared source/compiler proof of existing function-creation ports.

The input is an already verified original body with the same read-only source
context used by the call linker: graph/index/document/namespace, module or
class_entry, links_by_op/uses_by_op, and context.tree/semantic/docs/unit,
context.defs_by_atom and its qualified definitions mapping.  Each definitions
value retains (SourceDefinitionReference, signature, lexical entry, body row).
Only immutable compilation products may be retained on that source context;
there is no successful-verification cache, file lookup, target import, target
execution, new target resolution, publication or graph construction here.

A raw factory result is distinct from decorator application or a final binding.
Missing source scopes and unsupported factory kinds retain their existing
boundary; neither a spelling nor a qualname alone chooses a target.
"""
from __future__ import annotations

import ast

from scar.ir.program.model import OperationResult
from scar.ir.program.static_calls import StaticFunctionCreationRoute
from scar.ir.v2.common import SourceReference


def extract_class_function_creation(body, operation, value, normal_edge):
    """Join a class-suite factory through its original lexical code path.

    Annotation factories without a user DefinitionID retain their compiler
    provenance, but cannot manufacture a SourceDefinitionReference. The
    returned route is only the creation relation, not closure/default state
    or evidence that any decorator returned this function unchanged.
    """
    from scar.ir.program.class_entries import ClassSuiteOverlay, ClassSuiteMethodOverlay
    from scar.analysis.static_compilation import _scope_nodes
    from scar.trace.code_snapshot import code_key
    from scar.analysis.static_namespace import normal_reference
    overlay=body.class_entry
    if type(overlay) not in (ClassSuiteOverlay, ClassSuiteMethodOverlay):return None
    factories=[record for record in overlay.factories if record.operation==operation.id]
    if len(factories)!=1:raise ValueError('class factory lacks its unique original creation record')
    factory=factories[0]
    if factory.definition is None:return None
    context=body.context
    if factory.definition not in context.definitions:
        return None  # A source declaration without a qualified function interface stays open.
    links=body.links_by_op.get(operation.id,())
    qualified,_,_,_=context.definitions[factory.definition]
    source=factory.source
    normal=normal_reference(body.index,operation.id)
    if (len(links)!=1 or links[0].source!=source or qualified.source!=source
            or factory.reference!=value or normal!=(normal_edge,value)):
        raise ValueError('class factory source/normal result differs from its original qualified body')
    declarations=[d for d in context.semantic.definitions.values()
        if d.id==links[0].semantic_operation and d.metadata.get('phase')=='definition_time'
        and d.code_id==source.atom_id.wire and source.atom_id in d.source_atoms]
    definition=context.semantic.definitions.get(factory.definition)
    if (len(declarations)!=1 or definition is None or definition.metadata.get('phase')!='call_time'
            or definition.code_id!=source.atom_id.wire or source.atom_id not in definition.source_atoms):
        raise ValueError('class factory did not retain its original declaration/call-time definition')
    codes=[row for row in body.uses_by_op.get(operation.id,())if row.role=='function-code']
    if len(codes)!=1:raise ValueError('class factory lacks its actual code Use')
    code_use=body.index.use_site(codes[0].use).use
    origin=body.index.values[code_use.value].origin
    records=[r for r in overlay.constants if isinstance(origin,OperationResult)
             and r.operation==origin.operation and r.reference==code_use.value]
    if (code_use.value!=factory.code_reference or len(records)!=1
            or records[0].constant_path!=factory.constant_path or len(factory.constant_path)!=1):
        raise ValueError('class factory code does not come from its original constant slot')
    parent=getattr(context,'compiled_module_for_namespace',None)
    if parent is None:
        parent=compile(context.docs['source']['text'],context.unit['path'],'exec',
                       flags=0,dont_inherit=True,optimize=0)
        context.compiled_module_for_namespace=parent
        context.compiled_module_layout_for_namespace=code_key(parent)
    if context.compiled_module_layout_for_namespace!=overlay.compilation.root_code_layout_key:
        raise ValueError('class factory module layout differs from retained source compilation')
    scopes=getattr(context,'compiled_scope_paths_for_namespace',None)
    if scopes is None:
        found={};issues=[]
        _scope_nodes(context.tree,parent,(),ast.Module,found,issues)
        scopes={span:tuple(rows)for span,rows in found.items()}
        context.compiled_scope_paths_for_namespace=scopes
    class_span=(overlay.source.start_line,overlay.source.end_line,overlay.source.start_column,overlay.source.end_column)
    parents=[row for row in scopes.get(class_span,())
             if row[0]==overlay.compilation.code_path and isinstance(row[2],ast.ClassDef)]
    if len(parents)!=1 or code_key(parents[0][1])!=overlay.compilation.code_layout_key:
        raise ValueError('class factory parent code is not its original ClassDef compiler scope')
    span=(source.start_line,source.end_line,source.start_column,source.end_column)
    full_path=overlay.compilation.code_path+factory.constant_path
    children=[row for row in scopes.get(span,())if row[0]==full_path
              and isinstance(row[2],(ast.FunctionDef,ast.AsyncFunctionDef))]
    if len(children)!=1:
        raise ValueError('class factory child is not a unique original lexical source function')
    child_path,child,node=children[0]
    parent_code=parents[0][1]
    if (parent_code.co_consts[factory.constant_path[0]] is not child
            or child.co_name!=node.name or child.co_qualname!=parent_code.co_qualname+'.'+node.name
            or child.co_firstlineno!=min([node.lineno]+[d.lineno for d in node.decorator_list])
            or tuple(child.co_freevars)!=factory.free_names):
        raise ValueError('class factory child slot/name/qualname/firstline/closure layout differs')
    return StaticFunctionCreationRoute(operation.id,normal_edge,value,code_use.id,
        origin.operation,overlay.compilation.code_layout_key,factory.constant_path,qualified)


def extract_function_creation(body, operation, value, normal_edge):
    """Join an explicit factory's code slot to its original shared body.

    This never treats APPLY_DECORATOR or an arbitrary same-source result as
    the original function. Compilation is of retained text, never exec.
    """
    if body.module is None:
        if body.class_entry is not None:
            return extract_class_function_creation(body,operation,value,normal_edge)
        from scar.analysis.static_nested_creation import verify_nested_function_creation
        return verify_nested_function_creation(body,operation,value,normal_edge)
    from scar.analysis.source_mapping_function_lowering import mapping_function_plan
    from scar.trace.code_snapshot import code_key
    from scar.ir.program.model import OperationResult
    context = body.context
    links = body.links_by_op.get(operation.id, ())
    if len(links) != 1 or type(links[0].source) is not SourceReference:
        raise ValueError("module factory lacks its unique original declaration source")
    source = links[0].source
    declarations = [d for d in context.semantic.definitions.values()
                    if d.id == links[0].semantic_operation and d.metadata.get("phase") == "definition_time"
                    and d.code_id == source.atom_id.wire and source.atom_id in d.source_atoms]
    definitions = [definition for definition in context.defs_by_atom.get(source.atom_id, ())
                   if context.semantic.definitions[definition].metadata.get("phase") == "call_time"]
    nodes = [n for n in ast.walk(context.tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and (n.lineno,n.end_lineno,n.col_offset,n.end_col_offset) ==
             (source.start_line,source.end_line,source.start_column,source.end_column)]
    if len(declarations) != 1 or len(definitions) != 1 or len(nodes) != 1:
        raise ValueError("module factory declaration/body source join is not exact")
    codes = [row for row in body.uses_by_op.get(operation.id, ()) if row.role == "function-code"]
    if len(codes) != 1:
        raise ValueError("module factory does not have its original code Use")
    code_use = body.index.use_site(codes[0].use).use
    origin = body.index.values[code_use.value].origin
    if type(origin) is not OperationResult:
        raise ValueError("module factory code is not its original constant operation result")
    records = [row for row in body.module.constants if row.operation == origin.operation]
    if len(records) != 1 or len(records[0].constant_path) != 1 or records[0].source != source:
        raise ValueError("module factory code constant does not retain its exact slot/source")
    parent = getattr(context, "compiled_module_for_namespace", None)
    if parent is None:
        parent = compile(context.docs["source"]["text"], context.unit["path"], "exec",
                         flags=0, dont_inherit=True, optimize=0)
        context.compiled_module_for_namespace = parent
        context.compiled_module_layout_for_namespace = code_key(parent)
    record = records[0]
    if context.compiled_module_layout_for_namespace != record.code_key or record.code_key != body.module.declaration.compilation.code_layout_key:
        raise ValueError("module factory code-slot layout differs from retained source compilation")
    plan = mapping_function_plan(nodes[0], parent)
    if record.constant_path != (plan.child.arg,) or parent.co_consts[plan.child.arg] is not plan.child.argval:
        raise ValueError("module factory code slot does not select this source function's compiled child")
    definition = definitions[0]
    return StaticFunctionCreationRoute(operation.id, normal_edge, value, code_use.id,
        origin.operation, record.code_key, record.constant_path, context.definitions[definition][0])


__all__ = ["extract_function_creation", "extract_class_function_creation"]
