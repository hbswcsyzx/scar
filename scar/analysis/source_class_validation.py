"""Independent source and canonical-core validation for static class frames."""
from __future__ import annotations

import ast

from scar.analysis.static_compilation import StaticCodeEvidence, compile_source_unit
from scar.ir.program.class_entries import (
    ClassBodyStatement, ClassEntryInput, ClassEntryInputRole, ClassEntryResult,
    ClassFrontierKind, ClassNormalPayloadKind, compiler_cell_protocol,
)
from scar.ir.program.control import ControlScopeKind
from scar.ir.program.control_validation import control_errors
from scar.ir.program.model import (
    Behavior, BlockArgument, CompletionSignature, ExitKind, Operation,
    ReferenceValue, TerminatorKind, UseRole, ValueKind, ValueType,
)
from scar.ir.program.source import OperationSource
from scar.ir.program.source_subjects import (
    ClassCompilerCellRole, ClassFrameABI, FrameKind, SourceCompilationFrameRoot,
)
from scar.ir.program.validation import require_valid
from scar.ir.semantics_v2 import Opcode, SourceSnapshot
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID
from scar.ir.v2.semantic import OperationKind


def _need(condition, detail):
    if not condition:
        raise ValueError("static class entry: " + detail)


def _span(node):
    return (node.lineno, node.end_lineno, node.col_offset, node.end_col_offset)


def _source_reference(prepared, node):
    span = _span(node)
    snapshot = prepared.semantics.sources[str(prepared.path)]
    matches = [atom.reference for atom in prepared.semantic.source_atoms.values()
               if atom.kind == type(node).__name__ and atom.reference.path == str(prepared.path)
               and atom.reference.fingerprint == snapshot.fingerprint
               and (atom.reference.start_line, atom.reference.end_line,
                    atom.reference.start_column, atom.reference.end_column) == span]
    if len(matches) != 1:
        raise ValueError("static class entry: source span has no unique retained source atom")
    return matches[0]


def _expected_header_inputs(prepared, node):
    rows, order = [], 0
    for index, expression in enumerate(node.decorator_list):
        rows.append(ClassEntryInput(ClassEntryInputRole.DECORATOR, index, order,
                                    _source_reference(prepared, expression)))
        order += 1
    for index, expression in enumerate(node.bases):
        rows.append(ClassEntryInput(ClassEntryInputRole.BASE, index, order,
                                    _source_reference(prepared, expression)))
        order += 1
    for index, keyword in enumerate(node.keywords):
        role = (ClassEntryInputRole.METACLASS if keyword.arg == "metaclass" else
                ClassEntryInputRole.CLASS_KEYWORD if keyword.arg is not None else
                ClassEntryInputRole.CLASS_KEYWORD_EXPANSION)
        rows.append(ClassEntryInput(role, index, order,
                                    _source_reference(prepared, keyword.value), keyword.arg))
        order += 1
    return tuple(rows)


def _expected_body_statements(prepared, node):
    pending, rows = list(reversed(node.body)), []
    while pending:
        current = pending.pop()
        if isinstance(current, ast.stmt):
            rows.append(current)
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        pending.extend(reversed(list(ast.iter_child_nodes(current))))
    return tuple(ClassBodyStatement(index, type(statement).__name__,
                                    _source_reference(prepared, statement))
                 for index, statement in enumerate(rows))


def _source_semantics(prepared, definition, source):
    _need(type(definition) is OperationDefinitionID and type(source) is SourceReference,
          "validator needs the original definition and source reference")
    source.__post_init__()
    snapshot = prepared.semantics.sources.get(source.path)
    _need(type(snapshot) is SourceSnapshot and source.path == str(prepared.path)
          and source.fingerprint == snapshot.fingerprint,
          "class source differs from the retained snapshot")
    atom = prepared.semantic.source_atoms.get(source.atom_id)
    semantic = prepared.semantic.definitions.get(definition)
    _need(atom is not None and atom.reference == source and atom.kind == "ClassDef"
          and semantic is not None and semantic.kind is OperationKind.OPAQUE
          and semantic.code_id == source.atom_id.wire and source.atom_id in semantic.source_atoms
          and semantic.source_file == source.path,
          "ID is not the original SourceGraph opaque ClassDef operation")
    nodes = [node for node in ast.walk(prepared.tree)
             if type(node) is ast.ClassDef and _span(node) == (
                 source.start_line, source.end_line, source.start_column, source.end_column)]
    _need(len(nodes) == 1 and semantic.label == "class " + nodes[0].name,
          "source span does not select the original ClassDef")
    return snapshot, semantic, nodes[0]


def require_valid_source_class_entry(prepared, definition, source, *, code_evidence, result,
                                    max_operations=10000):
    """Recompile retained source and validate the class root plus required body.

    This validates only the source-compiled static fragment. It makes no claim
    that a parent has supplied a prepared namespace/closure or invoked the
    metaclass, and it does not certify effects or class-object identity.
    """
    _need(type(result) is ClassEntryResult, "result must be exact ClassEntryResult")
    _need(type(max_operations) is int and 3 <= max_operations <= 100000,
          "operation limit must be in [3,100000]")
    snapshot, semantic, node = _source_semantics(prepared, definition, source)
    _need(type(code_evidence) is StaticCodeEvidence,
          "class validation requires StaticCodeEvidence, not a capture witness")
    code_evidence.require_definition(snapshot, definition, source)

    independently_compiled = compile_source_unit(prepared).for_definition(definition, source)
    _need(independently_compiled.to_reference() == code_evidence.to_reference(),
          "supplied class code differs from a fresh no-exec compilation of the retained source")
    code = independently_compiled.code
    _need(code.co_name == node.name and code.co_argcount == 0
          and code.co_posonlyargcount == 0 and code.co_kwonlyargcount == 0,
          "compiler class-body name/formal layout differs")
    stages, normal_payload = compiler_cell_protocol(code)

    graph, metadata, overlay = result.graph, result.metadata, result.overlay
    _need(metadata.source == snapshot and overlay.source == source
          and overlay.definition == definition and overlay.parent_definition == semantic.parent_id,
          "overlay does not preserve original source, definition, lexical parent and snapshot")
    _need(overlay.compilation == independently_compiled.to_reference(),
          "overlay compiler reference differs from independent compilation")
    _need(overlay.inputs == _expected_header_inputs(prepared, node),
          "class decorators/bases/keywords are incomplete, reordered or mis-sourced")
    expected_statements = _expected_body_statements(prepared, node)
    _need(overlay.required_expansion.body_statements == expected_statements,
          "executed class-scope statement collection is incomplete or misordered")
    _need(overlay.required_expansion.normal_payload is normal_payload
          and overlay.required_expansion.compiler_stages == stages,
          "class normal return/cell protocol differs from the exact compiled CodeType")

    expected_cell_roles = tuple((name, index, {
        "__class__": ClassCompilerCellRole.CLASS_OBJECT,
        "__classdict__": ClassCompilerCellRole.CLASS_NAMESPACE,
    }.get(name, ClassCompilerCellRole.LOCAL)) for index, name in enumerate(code.co_cellvars))
    abi = overlay.interface
    _need(type(abi) is ClassFrameABI and abi.co_freevars == tuple(code.co_freevars)
          and abi.co_cellvars == tuple(code.co_cellvars)
          and tuple((cell.name, cell.position, cell.role) for cell in abi.compiler_cells)
              == expected_cell_roles
          and len(abi.mapping.closure_cells) == len(code.co_freevars),
          "class freevar entry or compiler-owned local-cell roles differ from compilation")
    _need(overlay.root_scope in {scope.id for scope in graph.control_scopes},
          "class frame root scope is missing")
    roots = [root for root in graph.frame_roots if root.scope == overlay.root_scope]
    _need(len(roots) == 1 and type(roots[0]) is SourceCompilationFrameRoot
          and roots[0].kind is FrameKind.CLASS and roots[0].entry == abi
          and roots[0].code == independently_compiled.to_reference(),
          "canonical root is not the original source-compiled CLASS frame ABI")
    scope = next(row for row in graph.control_scopes if row.id == overlay.root_scope)
    _need(scope.kind is ControlScopeKind.FRAME and scope.source == source
          and scope.region == graph.root and roots[0].code.source == source,
          "class FRAME scope/source/region does not retain the original ClassDef")

    require_valid(graph)
    _need(not control_errors(graph), "class frame root violates canonical control validation")
    _need(result.operations_emitted == overlay.operations_emitted == len(graph.operations)
          and len(graph.operations) <= max_operations and len(graph.operations) == 3,
          "required-expansion graph operation count differs from its bounded fragment")
    _need(not graph.environments,
          "class frame must not be represented by a function EnvironmentInterface")
    operations = {operation.id: operation for operation in graph.operations}
    body = operations.get(overlay.required_expansion.operation)
    world_type = ValueType(ValueKind.STATE, location=graph.locations[0].id)
    normal_payload_type = ValueType(ValueKind.REFERENCE)
    _need(type(body) is Operation and body.label == "required-class-body-expansion"
          and body.terminator is not None and body.terminator.kind is TerminatorKind.INVOKE
          and body.callee is None and body.effects_complete is False
          and set(body.behaviors) == {Behavior.CONTROL, Behavior.READ, Behavior.WRITE, Behavior.MEMORY}
          and body.completions == (
              CompletionSignature(ExitKind.NORMAL, (normal_payload_type, world_type)),
              CompletionSignature(ExitKind.RAISE, (ValueType(ValueKind.REFERENCE),
                  ValueType(ValueKind.REFERENCE), world_type))),
          "class body is not retained as an incomplete normal/raise expansion boundary")
    normal_block = next(edge.block for edge in body.terminator.successors if edge.kind is ExitKind.NORMAL)
    normal_block_record = next(block for region in graph.regions for block in region.blocks
                               if block.id == normal_block)
    normal_payload_id = normal_block_record.arguments[0]
    normal_payload_record = next(value for value in graph.values if value.id == normal_payload_id)
    if normal_payload is ClassNormalPayloadKind.CLASS_CELL:
        _need(type(normal_payload_record) is ReferenceValue
              and normal_payload_record.origin == BlockArgument(normal_block, 0),
              "compiled __class__ cell result is not modeled as a reference payload")
        _need(any(stage.role == "RETURN_CLASS_OBJECT_CELL"
                  for stage in overlay.required_expansion.compiler_stages),
              "class-cell reference lacks the compiler-verified return mode")
    else:
        _need(type(normal_payload_record) is ReferenceValue
              and normal_payload_record.origin == BlockArgument(normal_block, 0),
              "implicit None payload is not connected as a Python object reference")
        roles = tuple(stage.role for stage in overlay.required_expansion.compiler_stages)
        _need("LOAD_NONE_NORMAL_RESULT" in roles and "RETURN_NONE" in roles,
              "None reference lacks the compiler-verified singleton return constraint")
    operation_sources = {row.operation: row for row in metadata.operation_links}
    body_source = operation_sources.get(body.id)
    _need(type(body_source) is OperationSource and body_source.source == source
          and body_source.semantic_operation == definition and body_source.opcode is Opcode.OPAQUE,
          "required body boundary is not linked to the existing original class operation")
    expected_frontiers = {
        ClassFrontierKind.BODY_REQUIRED_EXPANSION,
        ClassFrontierKind.PARENT_CLASS_STATEMENT_UNCONNECTED,
        ClassFrontierKind.PREPARED_NAMESPACE_UNCONNECTED,
        ClassFrontierKind.METACLASS_SELECTION_AND_CALL_OPEN,
        ClassFrontierKind.BASE_MRO_ENTRIES_OPEN,
        ClassFrontierKind.DESCRIPTOR_AND_SUBCLASS_HOOKS_OPEN,
        ClassFrontierKind.EFFECTS_OPEN,
    }
    frontier_kinds = {frontier.kind for frontier in overlay.frontiers}
    _need(expected_frontiers <= frontier_kinds,
          "class construction or body incompleteness is not explicitly retained")
    if code.co_freevars:
        _need(ClassFrontierKind.OUTER_CLOSURE_UNCONNECTED in frontier_kinds,
              "compiler freevars lack a parent-closure frontier")
    if "__class__" in code.co_cellvars:
        _need(ClassFrontierKind.CLASSCELL_ACCEPTANCE_AND_FILL_UNPROVEN in frontier_kinds,
              "normal classcell output lacks an unproved parent-fill frontier")
    if node.decorator_list:
        _need(ClassFrontierKind.DECORATOR_APPLICATION_OPEN in frontier_kinds,
              "decorator application is not left open")
    _need(overlay.status == "STATIC_CLASS_FRAME_WITH_REQUIRED_BODY_EXPANSION"
          and overlay.required_expansion.status == "REQUIRED",
          "class lowerer may not report a complete body")
    return result


__all__ = ["require_valid_source_class_entry"]
