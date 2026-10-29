"""Verify original nested-function factories without executing their source.

The compiler layout binds a real factory/code Use to an exact lexical child
slot. It never makes a same-name declaration a callable, identifies a runtime
function instance, or equates its globals/defaults/captured-cell contents.
"""
from __future__ import annotations

import ast
import hashlib
import sys
from types import CodeType

from scar.ir.record_codec import encode
from scar.ir.program.model import ExitKind, OperationResult, TerminatorKind
from scar.ir.program.source_language import decode_language_overlay
from scar.ir.program.static_calls import StaticFunctionCreationRoute
from scar.ir.v2.semantic import OperationKind, SemanticRelation
from scar.analysis.program_lowering import _Unsupported
from scar.analysis.source_function_definition_lowering import compiler_plan
from scar.analysis.static_compilation import StaticCodeEvidence, _scope_nodes
from scar.analysis.static_function_environment import validate_static_body_namespace
from scar.analysis.static_namespace import normal_reference, protocol_kinds
from scar.trace.code_snapshot import code_key


def _span(reference):
    return (reference.start_line, reference.end_line, reference.start_column, reference.end_column)


def _source_nodes(tree, reference):
    return [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
            and (node.lineno, node.end_lineno, node.col_offset, node.end_col_offset) == _span(reference)]


def _factory(*, graph, index, document, namespace, source_text, operation, value,
             normal_edge, compiled_module=None, source_tree=None, scope_paths=None):
    """Shared source/compiler/port proof; qualified source IDs are joined above."""
    if index.graph is not graph:
        raise ValueError('nested factory index belongs to another original graph')
    metadata = validate_static_body_namespace(graph, document, namespace)
    protocols = protocol_kinds(document)
    if protocols.get(operation.id) != 'MAKE_NESTED_FUNCTION':
        return None
    if index.operations.get(operation.id) != operation:
        raise ValueError('nested factory is not its original operation')
    if (operation.terminator is None or operation.terminator.kind is not TerminatorKind.INVOKE
            or tuple(edge.kind for edge in operation.terminator.successors) != (ExitKind.NORMAL, ExitKind.RAISE)
            or normal_reference(index, operation.id) != (normal_edge, value)):
        raise ValueError('nested factory changed its original paired normal/raise reference boundary')
    compilation = document.get('static_compilation')
    language_wire = document.get('language')
    if compilation is None or language_wire is None:
        return None
    language = decode_language_overlay(language_wire)
    if language.source != metadata.source or language.code_evidence != compilation:
        raise ValueError('nested factory compiler/language source provenance differs')
    if (type(source_text) is not str
            or 'sha256:' + hashlib.sha256(source_text.encode()).hexdigest() != metadata.source.fingerprint):
        raise ValueError('nested factory retained text differs from its original source snapshot')
    compiler = compilation.get('compiler')
    if (type(compiler) is not dict or compiler.get('implementation') != sys.implementation.name
            or compiler.get('version') != list(sys.version_info[:3])
            or compiler.get('cache_tag') != sys.implementation.cache_tag):
        return None
    if (compiler.get('mode') != 'exec' or compiler.get('flags') != 0
            or compiler.get('dont_inherit') is not True or compiler.get('optimize') != 0):
        raise ValueError('nested factory has an unsupported source compiler profile')
    if compiled_module is None:
        compiled_module = compile(source_text, metadata.source.path, 'exec',
                                  flags=0, dont_inherit=True, optimize=0)
    if type(compiled_module) is not CodeType:
        raise TypeError('nested factory compiler root must be a no-exec CodeType product')
    root_key = code_key(compiled_module)
    path = compilation.get('code_path')
    if type(path) is not list or not path or any(type(position) is not int or position < 0 for position in path):
        raise ValueError('nested factory has no exact original parent compiler path')
    parent = compiled_module
    for position in path:
        if position >= len(parent.co_consts) or type(parent.co_consts[position]) is not CodeType:
            raise ValueError('nested factory parent path does not select an original child CodeType')
        parent = parent.co_consts[position]
    evidence = StaticCodeEvidence(metadata.source, compilation['namespace_root'], namespace.definition,
        namespace.source, tuple(path), parent, code_key(parent), sys.implementation.name,
        tuple(sys.version_info[:3]), compiler['python'], sys.implementation.cache_tag,
        root_code_layout_key=root_key)
    replayed = encode(evidence.to_dict())
    if 'layout' not in compilation:
        # Early source-compilation records did not retain the compiler tables.
        # This replay derives them from the independently selected parent code;
        # it does not attribute those newly reconstructed fields to the saved
        # record. Every field that the old record actually retained still has
        # to match, including both code keys, exact path and compiler profile.
        replayed.pop('layout')
    if replayed != compilation:
        raise ValueError('nested factory parent layout/path differs from independent source compilation')
    tree = ast.parse(source_text, filename=metadata.source.path, type_comments=True) if source_tree is None else source_tree
    if scope_paths is None:
        found, issues = {}, []
        _scope_nodes(tree, compiled_module, (), ast.Module, found, issues)
        scope_paths = {span: tuple(rows) for span, rows in found.items()}
    parents = [row for row in scope_paths.get(_span(namespace.source), ())
               if row[0] == tuple(path) and row[1] is parent and isinstance(row[2], ast.FunctionDef)]
    if len(parents) != 1:
        raise ValueError('nested factory parent code is not its original lexical source function')
    links = [link for link in metadata.operation_links if link.operation == operation.id]
    if len(links) != 1:
        raise ValueError('nested factory lacks its unique original declaration source')
    source = links[0].source
    if (source.path != metadata.source.path or source.fingerprint != metadata.source.fingerprint
            or links[0].opcode is not None):
        raise ValueError('nested factory declaration source differs from its parent snapshot')
    nodes = _source_nodes(tree, source)
    if len(nodes) != 1:
        raise ValueError('nested factory lacks its exact original FunctionDef AST')
    node = nodes[0]
    try:
        _, child, _ = compiler_plan(node, parent)
    except _Unsupported:
        return None
    children = [row for row in scope_paths.get(_span(source), ())
                if row[0] == tuple(path) + (child.arg,) and row[1] is child.argval and row[2] is node]
    if len(children) != 1:
        raise ValueError('nested factory child slot does not select its exact original lexical definition')
    sources = [row for row in metadata.use_links if row.operation == operation.id and row.role == 'function-code']
    if len(sources) != 1 or sources[0].index != 0 or sources[0].source != source:
        raise ValueError('nested factory lacks its original function-code Use role/source')
    code_use = index.use_site(sources[0].use)
    if code_use.operation != operation.id or code_use.use.id not in operation.invoke_arguments:
        raise ValueError('nested factory code Use belongs to another operation')
    origin = index.values[code_use.use.value].origin
    if type(origin) is not OperationResult:
        raise ValueError('nested factory code does not come from an original constant operation')
    constant = index.operations.get(origin.operation)
    constants = [row for row in language.constants if row.operation == origin.operation]
    if (constant is None or protocols.get(origin.operation) != 'READ_CODE_CONSTANT'
            or len(constants) != 1 or code_use.use.value not in constant.results
            or constants[0].source != source or constants[0].code_key != evidence.code_layout_key
            or constants[0].constant_path != (child.arg,)
            or parent.co_consts[child.arg] is not child.argval):
        raise ValueError('nested factory code Use changed its original parent constant slot/source')
    return metadata, source, node, links[0], code_use.use.id, constants[0], compiled_module, scope_paths


def verify_nested_function_creation(body, operation, value, normal_edge):
    """Return a verified qualified creation route, or an unconnected frontier.

    ``body.context`` supplies already verified retained source/semantic records.
    Cache only compilation products in that source context; never import or
    execute its target module. A source name alone never admits a definition.
    """
    if protocol_kinds(body.document).get(operation.id) != 'MAKE_NESTED_FUNCTION':
        return None
    context = body.context
    result = _factory(graph=body.graph, index=body.index, document=body.document,
        namespace=body.namespace, source_text=context.docs['source']['text'], operation=operation,
        value=value, normal_edge=normal_edge,
        compiled_module=getattr(context, 'compiled_module_for_namespace', None), source_tree=context.tree,
        scope_paths=getattr(context, 'compiled_scope_paths_for_namespace', None))
    if result is None:
        return None
    metadata, source, node, link, code_use, constant, compiled_module, scope_paths = result
    declarations = [row for row in context.semantic.definitions.values()
        if row.code_id == source.atom_id.wire and source.atom_id in row.source_atoms
        and row.metadata.get('phase') == 'definition_time']
    definitions = [row for row in context.semantic.definitions.values()
        if row.code_id == source.atom_id.wire and source.atom_id in row.source_atoms
        and row.metadata.get('phase') == 'call_time' and row.kind in (OperationKind.FUNCTION, OperationKind.METHOD)]
    if (len(declarations) != 1 or len(definitions) != 1
            or link.semantic_operation != declarations[0].id or definitions[0].label != node.name):
        raise ValueError('nested factory did not retain its original declaration/body definition IDs')
    slots = [context.semantic.slots[edge.target.id] for edge in context.semantic.edges.values()
             if edge.source.id == declarations[0].id and edge.relation is SemanticRelation.WRITES_SLOT]
    if len(slots) != 1 or slots[0].owner != body.namespace.definition or slots[0].name != node.name:
        raise ValueError('nested factory does not write its original parent lexical name slot')
    qualified = context.definitions.get(definitions[0].id)
    if qualified is None:
        return None
    qualified = qualified[0]
    if qualified.source != source or qualified.snapshot != metadata.source:
        raise ValueError('nested factory qualified body differs from its original source definition')
    context.compiled_module_for_namespace = compiled_module
    context.compiled_module_layout_for_namespace = code_key(compiled_module)
    context.compiled_scope_paths_for_namespace = scope_paths
    return StaticFunctionCreationRoute(operation.id, normal_edge, value, code_use,
        constant.operation, constant.code_key, constant.constant_path, qualified)


def validate_nested_function_creation(creation, *, graph, index, document, namespace,
                                     source_text, compiled_module=None):
    """Replay the shared compiler/port proof for an already source-checked ID.

    The enclosing query verifies the qualified definition's original lexical
    entry and semantic locator. This reader independently checks its source,
    factory, code Use, parent compiler path and exact relative child slot.
    """
    if type(creation) is not StaticFunctionCreationRoute:
        raise TypeError('nested factory reader requires its typed original creation route')
    creation.__post_init__()
    operation = index.operations.get(creation.factory)
    if operation is None:
        raise ValueError('nested factory reader has no original factory operation')
    result = _factory(graph=graph, index=index, document=document, namespace=namespace,
        source_text=source_text, operation=operation, value=creation.normal_value,
        normal_edge=creation.normal_edge, compiled_module=compiled_module)
    if result is None:
        raise ValueError('nested factory has no connected supported source/compiler proof')
    metadata, source, _, _, code_use, constant, _, _ = result
    if (creation.definition.source != source or creation.definition.snapshot != metadata.source
            or creation.code_use != code_use or creation.code_constant_operation != constant.operation
            or creation.code_layout_key != constant.code_key or creation.constant_path != constant.constant_path):
        raise ValueError('nested factory relation changed its original qualified compiler/source endpoints')
    return True


__all__ = ['verify_nested_function_creation', 'validate_nested_function_creation']
