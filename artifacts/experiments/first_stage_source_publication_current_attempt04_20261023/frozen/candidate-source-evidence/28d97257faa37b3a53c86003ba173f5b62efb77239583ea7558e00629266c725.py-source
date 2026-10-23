"""Ephemeral AST-to-CFG context links for source expressions.

This module derives structural statement context from already-built source
graphs. It does not add CFG nodes or certify expression execution. A linked
call still may be short-circuited, fail, suspend, or be skipped on another
path; every record therefore keeps ``execution_proven=False``.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import sys
import tokenize
from types import MappingProxyType
from typing import Mapping

from scar.ir.control_flow_v2 import (
    ControlFlowGap,
    ControlFlowNode,
    ControlFlowNodeID,
    NodeKind,
    SourceControlFlowGraph,
)
from scar.ir.semantics_v2 import Opcode, OperationSemantics, SourceSemanticsGraph, SourceSnapshot
from scar.ir.v2.ids import OperationDefinitionID
from scar.ir.v2.common import SourceReference
from scar.ir.v2.semantic import OperationKind, SemanticGraph, SourceAtom


_CONTROL_NODE_KINDS = frozenset({
    NodeKind.STATEMENT, NodeKind.BRANCH_TEST, NodeKind.LOOP_TEST, NodeKind.GAP,
})
_COMP_KINDS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_FUNCTION_KINDS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_PATH_TYPES = (ast.stmt, ast.expr, ast.arg, ast.keyword, ast.alias, ast.ExceptHandler)


@dataclass(frozen=True, slots=True)
class ASTFieldStep:
    """One parent field and optional list index on a statement-to-expression path."""

    field: str
    index: int | None = None

    def __post_init__(self) -> None:
        if type(self.field) is not str or not self.field:
            raise ValueError("AST field path requires a field name")
        if self.index is not None and (type(self.index) is not int or self.index < 0):
            raise ValueError("AST field path index must be a non-negative exact integer")


@dataclass(frozen=True, slots=True)
class SourceControlContext:
    """A source expression's structural path to its containing CFG statement."""

    operation: OperationDefinitionID | None
    scope: OperationDefinitionID | None
    expression_source: SourceReference
    statement_source: SourceReference | None
    control_nodes: tuple[ControlFlowNodeID, ...]
    control_gaps: tuple[ControlFlowGap, ...]
    field_path: tuple[ASTFieldStep, ...]
    boundaries: tuple[str, ...]
    gap: str | None = None
    execution_proven: bool = False

    def __post_init__(self) -> None:
        if self.operation is not None and type(self.operation) is not OperationDefinitionID:
            raise TypeError("context operation must be OperationDefinitionID or None")
        if self.scope is not None and type(self.scope) is not OperationDefinitionID:
            raise TypeError("context scope must be OperationDefinitionID or None")
        if type(self.expression_source) is not SourceReference:
            raise TypeError("expression_source must be SourceReference")
        if self.statement_source is not None and type(self.statement_source) is not SourceReference:
            raise TypeError("statement_source must be SourceReference or None")
        if type(self.execution_proven) is not bool or self.execution_proven:
            raise ValueError("structural source contexts never prove expression execution")


@dataclass(frozen=True, slots=True)
class SourceControlContextIndex:
    """A bounded lookup of expression source to statement-level CFG context."""

    source_path: str
    fingerprint: str
    contexts: tuple[SourceControlContext, ...]
    gaps: tuple[str, ...]
    ast_nodes: int
    work: int
    known_scopes: frozenset[OperationDefinitionID]
    _by_source: Mapping[SourceReference, tuple[SourceControlContext, ...]] = field(
        init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        rows: dict[SourceReference, list[SourceControlContext]] = {}
        for context in self.contexts:
            rows.setdefault(context.expression_source, []).append(context)
        object.__setattr__(self, "_by_source", MappingProxyType(
            {source: tuple(items) for source, items in rows.items()}))

    def query(
        self,
        source: SourceReference,
        scope: OperationDefinitionID | None = None,
    ) -> tuple[SourceControlContext, ...]:
        """Return exact source-reference contexts, optionally for one lexical owner."""
        if type(source) is not SourceReference:
            raise TypeError("source query requires SourceReference")
        if scope is not None and type(scope) is not OperationDefinitionID:
            raise TypeError("scope query requires OperationDefinitionID or None")
        if source.path != self.source_path or source.fingerprint != self.fingerprint:
            raise ValueError("source query differs from indexed source snapshot")
        rows = self._by_source.get(source, ())
        if scope is None:
            if rows:
                return rows
            return (SourceControlContext(
                None, None, source, None, (), (), (), (),
                "SOURCE_REFERENCE_HAS_NO_CONTEXT_RECORD", False),)
        matching = tuple(item for item in rows if item.scope == scope)
        if matching:
            return matching
        actual_scopes = {item.scope for item in rows}
        actual_scope = next(iter(actual_scopes)) if len(actual_scopes) == 1 else None
        reason = ("QUERY_SCOPE_NOT_IN_SEMANTIC_GRAPH" if scope not in self.known_scopes
                  else "SOURCE_CONTEXT_NOT_FOUND_IN_REQUESTED_SCOPE")
        if rows:
            return tuple(SourceControlContext(
                None, item.scope, source, item.statement_source, (), item.control_gaps,
                item.field_path, item.boundaries,
                "; ".join(part for part in (item.gap, reason) if part), False)
                for item in rows)
        return (SourceControlContext(
            None, actual_scope, source, None, (), (), (), (), reason, False),)


@dataclass(frozen=True, slots=True)
class _NodeInfo:
    scope: OperationDefinitionID | None
    statement: ast.stmt | None
    boundaries: tuple[str, ...]
    gaps: tuple[str, ...]


class _Meter:
    def __init__(self, max_work: int):
        self.limit = max_work
        self.work = 0

    def step(self, amount: int = 1) -> None:
        if type(amount) is not int or amount < 0:
            raise ValueError("source context work increment is invalid")
        self.work += amount
        if self.work > self.limit:
            raise ValueError("source control-context work budget exceeded")


def _span_key(kind: str, reference: SourceReference) -> tuple:
    return (kind, reference.start_line, reference.end_line,
            reference.start_column, reference.end_column)


def _node_span(node: ast.AST) -> tuple | None:
    line = getattr(node, "lineno", None)
    end_line = getattr(node, "end_lineno", None)
    column = getattr(node, "col_offset", None)
    end_column = getattr(node, "end_col_offset", None)
    if (type(line) is not int or type(end_line) is not int
            or type(column) is not int or type(end_column) is not int):
        return None
    return (type(node).__name__, line, end_line, column, end_column)


def _append_once(values: tuple[str, ...], value: str) -> tuple[str, ...]:
    return values if value in values else (*values, value)


def _read_source(path: str, source_text: str | None, max_source_bytes: int) -> str:
    if source_text is not None:
        if type(source_text) is not str:
            raise TypeError("source_text must be decoded text or None")
        text = source_text
    else:
        chunks: list[str] = []
        size = 0
        try:
            with tokenize.open(path) as stream:
                while True:
                    chunk = stream.read(256 * 1024)
                    if not chunk:
                        break
                    size += len(chunk.encode("utf-8", errors="strict"))
                    if size > max_source_bytes:
                        raise ValueError("source control-context source-byte budget exceeded")
                    chunks.append(chunk)
        except (OSError, UnicodeError, LookupError, SyntaxError) as error:
            raise ValueError("cannot read decoded source snapshot: " + str(error)) from error
        text = "".join(chunks)
    try:
        size = len(text.encode("utf-8", errors="strict"))
    except UnicodeError as error:
        raise ValueError("source text is not valid UTF-8 encodable text") from error
    if size > max_source_bytes:
        raise ValueError("source control-context source-byte budget exceeded")
    return text


def _module_snapshot(semantic: SemanticGraph, semantics: SourceSemanticsGraph,
                     control: SourceControlFlowGraph, path: str) -> SourceSnapshot:
    modules = [item for item in semantic.modules.values()
               if item.path == path and item.initializer is not None]
    if len(modules) != 1:
        raise ValueError("source path must identify exactly one local semantic module")
    snapshot = semantics.sources.get(path)
    version = control.sources.get(path)
    module = modules[0]
    if type(snapshot) is not SourceSnapshot or version is None:
        raise ValueError("source path is missing from a source overlay")
    if (module.fingerprint != snapshot.fingerprint
            or version.path != path or version.fingerprint != snapshot.fingerprint):
        raise ValueError("semantic module/source overlay fingerprints differ")
    current_python = f"{sys.version_info.major}.{sys.version_info.minor}"
    if snapshot.python_version != current_python:
        raise ValueError("source snapshot Python major/minor differs from current runtime")
    return snapshot


def _validate_graphs(semantic: SemanticGraph, semantics: SourceSemanticsGraph,
                     control: SourceControlFlowGraph, meter: _Meter) -> None:
    if type(semantic) is not SemanticGraph or type(semantics) is not SourceSemanticsGraph:
        raise TypeError("source context indexing requires exact SemanticGraph and SourceSemanticsGraph")
    if type(control) is not SourceControlFlowGraph:
        raise TypeError("source context indexing requires exact SourceControlFlowGraph")
    graph_items = (
        len(semantic.packages) + len(semantic.modules) + len(semantic.source_atoms)
        + len(semantic.definitions) + len(semantic.slots) + len(semantic.controls)
        + len(semantic.edges) + len(semantic.effects) + len(semantic.contracts)
        + len(semantic.resources) + len(semantics.sources) + len(semantics.operations)
        + len(semantics.values) + len(semantics.bindings) + len(semantics.uses)
        + len(semantics.gaps) + len(semantics.boundaries) + len(control.sources)
        + len(control.suites) + len(control.nodes) + len(control.edges)
        + len(control.insertions) + len(control.gaps))
    meter.step(graph_items * 8)
    semantic.assert_valid()
    semantics.assert_valid(semantic)
    control.assert_valid(semantic, semantics)


def _function_scopes(semantic: SemanticGraph, node_refs: Mapping[ast.AST, SourceReference],
                     path: str, meter: _Meter) -> dict[ast.AST, OperationDefinitionID | None]:
    by_atom: dict[object, list] = {}
    for definition in semantic.definitions.values():
        meter.step()
        if (definition.source_file == path and definition.kind in
                {OperationKind.FUNCTION, OperationKind.METHOD}
                and definition.metadata.get("phase") == "call_time"):
            for atom in definition.source_atoms:
                meter.step()
                by_atom.setdefault(atom, []).append(definition)
    result = {}
    for node, reference in node_refs.items():
        meter.step()
        if not isinstance(node, _FUNCTION_KINDS):
            continue
        atom_candidates = by_atom.get(reference.atom_id, ())
        meter.step(len(atom_candidates))
        candidates = [item for item in atom_candidates
                      if item.source_start == getattr(node, "lineno", None)
                      and item.source_end == getattr(node, "end_lineno", None)]
        result[node] = candidates[0].id if len(candidates) == 1 else None
    return result


def _index_ast(tree: ast.Module, semantic: SemanticGraph, semantics: SourceSemanticsGraph,
               control: SourceControlFlowGraph, path: str, meter: _Meter,
               max_ast_nodes: int):
    atoms_by_span: dict[tuple, list[SourceAtom]] = {}
    for atom in semantic.source_atoms.values():
        meter.step()
        reference = atom.reference
        if reference.path == path:
            atoms_by_span.setdefault(_span_key(atom.kind, reference), []).append(atom)

    parents: dict[ast.AST, tuple[ast.AST, str, int | None]] = {}
    parent_assigned: set[int] = set()
    node_refs: dict[ast.AST, SourceReference] = {}
    seen: set[int] = set()
    stack = [tree]
    ast_count = 0
    while stack:
        node = stack.pop()
        identity = id(node)
        if identity in seen:
            # CPython reuses singleton operator/context nodes. Their repeated
            # parent edges are irrelevant to positioned source anchors.
            continue
        seen.add(identity)
        ast_count += 1
        meter.step()
        if ast_count > max_ast_nodes:
            raise ValueError("source control-context AST-node budget exceeded")
        span = _node_span(node)
        if span is not None:
            candidates = atoms_by_span.get(span, ())
            if len(candidates) == 1 and candidates[0].kind == type(node).__name__:
                node_refs[node] = candidates[0].reference
        for field_name, value in reversed(list(ast.iter_fields(node))):
            meter.step()
            if isinstance(value, ast.AST):
                if id(value) not in parent_assigned:
                    parents[value] = (node, field_name, None)
                    parent_assigned.add(id(value))
                stack.append(value)
            elif isinstance(value, list):
                for index in range(len(value) - 1, -1, -1):
                    child = value[index]
                    meter.step()
                    if isinstance(child, ast.AST):
                        if id(child) not in parent_assigned:
                            parents[child] = (node, field_name, index)
                            parent_assigned.add(id(child))
                        stack.append(child)

    function_scopes = _function_scopes(semantic, node_refs, path, meter)
    semantics_by_source: dict[SourceReference, list[OperationSemantics]] = {}
    for operation in semantics.operations.values():
        meter.step()
        if operation.source.path == path:
            semantics_by_source.setdefault(operation.source, []).append(operation)

    class_scopes: dict[ast.AST, OperationDefinitionID | None] = {}
    for node, reference in node_refs.items():
        if not isinstance(node, ast.ClassDef):
            continue
        operations_at_source = semantics_by_source.get(reference, ())
        meter.step(len(operations_at_source))
        candidates = [item for item in operations_at_source
                      if item.opcode is Opcode.OPAQUE]
        class_scopes[node] = candidates[0].operation if len(candidates) == 1 else None

    info: dict[ast.AST, _NodeInfo] = {}
    module = next(item for item in semantic.modules.values()
                  if item.path == path and item.initializer is not None)
    # Store node context once during the AST walk. Parent links separately
    # retain exact field names/indices without copying full paths per node.
    stack_info = [(tree, module.initializer, (), (), None)]
    info_seen: set[int] = set()
    while stack_info:
        node, scope, boundaries, gaps, nearest_statement = stack_info.pop()
        if id(node) in info_seen:
            continue
        info_seen.add(id(node))
        meter.step()
        if isinstance(node, ast.stmt):
            nearest_statement = node
        local_boundaries = boundaries
        local_gaps = gaps
        if isinstance(node, ast.BoolOp):
            local_boundaries = _append_once(local_boundaries, "BOOLEAN_SHORT_CIRCUIT")
        elif isinstance(node, ast.IfExp):
            local_boundaries = _append_once(local_boundaries, "CONDITIONAL_EXPRESSION")
        elif isinstance(node, ast.Compare) and len(node.ops) > 1:
            local_boundaries = _append_once(local_boundaries, "CHAINED_COMPARISON_SHORT_CIRCUIT")
        elif isinstance(node, (ast.Await, ast.Yield, ast.YieldFrom)):
            local_boundaries = _append_once(local_boundaries, type(node).__name__.upper() + "_SUSPENSION")
        elif isinstance(node, ast.Starred):
            local_boundaries = _append_once(local_boundaries, "STARRED_ITERATION_OR_EXPANSION")
        elif isinstance(node, ast.Assert):
            local_boundaries = _append_once(
                local_boundaries, "ASSERT_ENABLED_BY_OPTIMIZATION_MODE_AND_MAY_RAISE")
        elif isinstance(node, _COMP_KINDS):
            local_boundaries = _append_once(local_boundaries, "COMPREHENSION_IMPLICIT_FRAME")
            local_gaps = _append_once(local_gaps, "COMPREHENSION_FRAME_HAS_NO_RELIABLE_CFG_SCOPE")
        elif isinstance(node, ast.Lambda):
            local_boundaries = _append_once(local_boundaries, "LAMBDA_BODY_FRAME")
        elif isinstance(node, ast.Call) and any(keyword.arg is None for keyword in node.keywords):
            local_boundaries = _append_once(local_boundaries, "CALL_KEYWORD_UNPACK_MAY_MUTATE_OR_RAISE")
        if isinstance(node, _PATH_TYPES):
            info[node] = _NodeInfo(scope, nearest_statement, local_boundaries, local_gaps)

        for field_name, value in reversed(list(ast.iter_fields(node))):
            meter.step()
            children = ([(index, child) for index, child in enumerate(value)
                         if isinstance(child, ast.AST)] if isinstance(value, list)
                        else [(None, value)] if isinstance(value, ast.AST) else [])
            if isinstance(value, list):
                meter.step(len(value))
            for index, child in reversed(children):
                child_scope = scope
                child_boundaries = local_boundaries
                child_gaps = local_gaps
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if field_name == "body":
                        child_scope = function_scopes.get(node)
                        # A called function has its own lexical execution
                        # scope. Definition-time class/with/try gaps must not
                        # leak from the suite that merely creates the function.
                        child_boundaries = ("DEFERRED_FUNCTION_BODY",)
                        child_gaps = (() if child_scope is not None else
                                      ("FUNCTION_BODY_SCOPE_NOT_UNIQUE",))
                    elif field_name == "decorator_list":
                        child_boundaries = _append_once(child_boundaries, "FUNCTION_DECORATOR_DEFINITION_TIME")
                    elif field_name == "args":
                        child_boundaries = _append_once(child_boundaries, "FUNCTION_ARGUMENT_HEADER")
                    elif field_name in {"returns", "type_params"}:
                        child_boundaries = _append_once(child_boundaries, "FUNCTION_ANNOTATION_OR_TYPE_PARAMETER")
                        child_gaps = _append_once(child_gaps, "ANNOTATION_EXECUTION_TIMING_OR_SCOPE_UNRESOLVED")
                elif isinstance(node, ast.arguments):
                    if field_name in {"defaults", "kw_defaults"}:
                        child_boundaries = _append_once(child_boundaries, "FUNCTION_DEFAULT_DEFINITION_TIME")
                    elif field_name in {"posonlyargs", "args", "kwonlyargs", "vararg", "kwarg"}:
                        child_boundaries = _append_once(child_boundaries, "FUNCTION_PARAMETER_HEADER")
                elif isinstance(node, ast.arg) and field_name == "annotation":
                    child_boundaries = _append_once(child_boundaries, "PARAMETER_ANNOTATION")
                    child_gaps = _append_once(child_gaps, "ANNOTATION_EXECUTION_TIMING_OR_SCOPE_UNRESOLVED")
                elif isinstance(node, ast.ClassDef):
                    if field_name == "body":
                        child_scope = class_scopes.get(node)
                        child_boundaries = _append_once(child_boundaries, "CLASS_NAMESPACE_BODY")
                        child_gaps = _append_once(child_gaps, "CLASS_NAMESPACE_HAS_NO_RELIABLE_CFG_SUITE")
                    elif field_name == "decorator_list":
                        child_boundaries = _append_once(child_boundaries, "CLASS_DECORATOR_DEFINITION_TIME")
                    elif field_name == "bases":
                        child_boundaries = _append_once(child_boundaries, "CLASS_BASE_EVALUATION")
                    elif field_name == "keywords":
                        child_boundaries = _append_once(child_boundaries, "CLASS_KEYWORD_EVALUATION")
                elif isinstance(node, ast.Lambda) and field_name == "body":
                    child_scope = function_scopes.get(node)
                    child_boundaries = ("LAMBDA_BODY_FRAME",)
                    child_gaps = ("LAMBDA_BODY_HAS_NO_RELIABLE_CFG_SUITE",)
                elif isinstance(node, ast.Assert) and field_name == "msg":
                    child_boundaries = _append_once(child_boundaries, "ASSERT_MESSAGE_CONDITIONAL")
                if isinstance(node, ast.comprehension):
                    parent_edge = parents.get(node)
                    generator_index = (parent_edge[2] if parent_edge is not None
                                       and parent_edge[1] == "generators" else None)
                    if generator_index == 0 and field_name == "iter":
                        child_scope = scope
                        child_boundaries = tuple(
                            item for item in child_boundaries
                            if item != "COMPREHENSION_IMPLICIT_FRAME")
                        child_boundaries = _append_once(
                            child_boundaries, "COMPREHENSION_FIRST_ITER_OUTER_SCOPE")
                        child_gaps = tuple(
                            item for item in child_gaps
                            if item != "COMPREHENSION_FRAME_HAS_NO_RELIABLE_CFG_SCOPE")
                    else:
                        child_scope = None
                        child_boundaries = _append_once(
                            child_boundaries, "COMPREHENSION_IMPLICIT_FRAME")
                        child_gaps = _append_once(
                            child_gaps, "COMPREHENSION_FRAME_OWNER_NOT_UNIQUE")
                elif isinstance(node, ast.If) and field_name == "test":
                    child_boundaries = _append_once(child_boundaries, "IF_BRANCH_TEST")
                elif isinstance(node, ast.While) and field_name == "test":
                    child_boundaries = _append_once(child_boundaries, "WHILE_LOOP_TEST")
                elif isinstance(node, (ast.For, ast.AsyncFor)) and field_name == "iter":
                    child_boundaries = _append_once(child_boundaries, "FOR_ITERATION_MAY_RAISE_OR_CALL_USER_CODE")
                elif isinstance(node, ast.Try) and field_name in {"body", "handlers", "orelse", "finalbody"}:
                    child_boundaries = _append_once(child_boundaries, "TRY_EXCEPTIONAL_CONTROL")
                elif isinstance(node, (ast.With, ast.AsyncWith)):
                    child_boundaries = _append_once(child_boundaries, "WITH_FINALIZER_OR_RESOURCE_BOUNDARY")
                    child_gaps = _append_once(child_gaps, "WITH_CONTROL_HAS_NO_RELIABLE_SOURCE_CONTEXT")
                if isinstance(node, _COMP_KINDS):
                    child_gaps = _append_once(child_gaps, "COMPREHENSION_FRAME_HAS_NO_RELIABLE_CFG_SCOPE")
                    if field_name != "generators":
                        child_scope = None
                        child_boundaries = _append_once(
                            child_boundaries, "COMPREHENSION_IMPLICIT_FRAME")
                        child_gaps = _append_once(
                            child_gaps, "COMPREHENSION_FRAME_OWNER_NOT_UNIQUE")
                if id(child) not in info_seen:
                    stack_info.append((child, child_scope, child_boundaries, child_gaps,
                                       nearest_statement))

    nodes_by_scope_atom: dict[tuple[OperationDefinitionID, object], list[ControlFlowNode]] = {}
    for node in control.nodes.values():
        meter.step()
        if node.kind in _CONTROL_NODE_KINDS and node.source is not None and node.source.path == path:
            nodes_by_scope_atom.setdefault((node.scope, node.source.atom_id), []).append(node)
    gaps_by_scope_atom: dict[tuple[OperationDefinitionID, object], list[ControlFlowGap]] = {}
    for gap in control.gaps:
        meter.step()
        if gap.source is not None and gap.source.path == path:
            gaps_by_scope_atom.setdefault((gap.scope, gap.source.atom_id), []).append(gap)

    nodes_by_source: dict[SourceReference, list[ast.AST]] = {}
    for node, reference in node_refs.items():
        meter.step()
        nodes_by_source.setdefault(reference, []).append(node)

    return (node_refs, parents, info, semantics_by_source,
            nodes_by_scope_atom, gaps_by_scope_atom, ast_count, nodes_by_source)


def _path_from_statement(node: ast.AST, statement: ast.stmt | None,
                         parents: Mapping[ast.AST, tuple[ast.AST, str, int | None]],
                         meter: _Meter) -> tuple[ASTFieldStep, ...] | None:
    if statement is None:
        return None
    current = node
    reverse: list[ASTFieldStep] = []
    while current is not statement:
        meter.step()
        parent = parents.get(current)
        if parent is None:
            return None
        current, field_name, index = parent
        reverse.append(ASTFieldStep(field_name, index))
    return tuple(reversed(reverse))


def index_source_control_contexts(
    semantic: SemanticGraph,
    semantics: SourceSemanticsGraph,
    control: SourceControlFlowGraph,
    *,
    source_path: str | Path,
    source_text: str | None = None,
    max_source_bytes: int = 4_000_000,
    max_ast_nodes: int = 200_000,
    max_work: int = 2_000_000,
) -> SourceControlContextIndex:
    """Index expression-to-containing-statement structure for one source file.

    The CFG remains statement-grained. Exact source atoms identify expressions;
    their parent field path identifies the nearest statement; only an exact
    same-scope statement source anchor can link to the existing CFG. Calls
    missing from ``semantics.operations`` are still indexed with
    ``operation=None`` so callers can query CallInventory source references
    without inventing semantic values or operations.
    """
    for name, value in (("max_source_bytes", max_source_bytes),
                        ("max_ast_nodes", max_ast_nodes), ("max_work", max_work)):
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be a positive exact integer")
    if not isinstance(source_path, (str, Path)):
        raise TypeError("source_path must be str or Path")
    path = str(Path(source_path).resolve(strict=False))
    meter = _Meter(max_work)
    _validate_graphs(semantic, semantics, control, meter)
    snapshot = _module_snapshot(semantic, semantics, control, path)
    text = _read_source(path, source_text, max_source_bytes)
    fingerprint = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    if fingerprint != snapshot.fingerprint:
        raise ValueError("source text fingerprint differs from semantic/source/control overlays")
    try:
        tree = ast.parse(text, filename=path, type_comments=True)
    except (SyntaxError, ValueError, RecursionError) as error:
        raise ValueError("source control-context AST parse failed") from error

    (node_refs, parents, info, semantics_by_source, nodes_by_scope_atom,
     gaps_by_scope_atom, ast_nodes, nodes_by_source) = _index_ast(
        tree, semantic, semantics, control, path, meter, max_ast_nodes)

    contexts: list[SourceControlContext] = []
    index_gaps: list[str] = []

    def make_context(operation_id: OperationDefinitionID | None,
                     expected_scope: OperationDefinitionID | None,
                     expression_source: SourceReference,
                     node: ast.AST | None) -> SourceControlContext:
        reasons: list[str] = []
        node_info = info.get(node) if node is not None else None
        statement = node_info.statement if node_info is not None else None
        statement_source = node_refs.get(statement) if statement is not None else None
        field_path = _path_from_statement(node, statement, parents, meter) if node is not None else None
        boundaries = node_info.boundaries if node_info is not None else ()
        context_scope = expected_scope
        if node is None or node_info is None:
            reasons.append("SOURCE_ATOM_HAS_NO_UNAMBIGUOUS_POSITIONED_AST_NODE")
        elif node_info.scope is None:
            context_scope = None
            reasons.append("AST_LEXICAL_SCOPE_NOT_UNIQUE")
        elif node_info.scope != expected_scope:
            context_scope = node_info.scope
            reasons.append("AST_SCOPE_DIFFERS_FROM_SOURCE_SEMANTICS_SCOPE")
        if statement is None:
            reasons.append("NO_ENCLOSING_AST_STATEMENT")
        elif statement_source is None:
            reasons.append("ENCLOSING_STATEMENT_HAS_NO_EXACT_SOURCE_ATOM")
        if field_path is None and node is not None and statement is not None:
            reasons.append("STATEMENT_TO_EXPRESSION_FIELD_PATH_IS_INCOMPLETE")
        if node_info is not None and node_info.gaps:
            reasons.extend(node_info.gaps)
        candidates: list[ControlFlowNode] = []
        matching_gaps: list[ControlFlowGap] = []
        unavailable = bool(node_info and node_info.gaps)
        if (not unavailable and context_scope is not None and statement_source is not None
                and field_path is not None):
            available_nodes = nodes_by_scope_atom.get(
                (context_scope, statement_source.atom_id), ())
            available_gaps = gaps_by_scope_atom.get(
                (context_scope, statement_source.atom_id), ())
            meter.step(len(available_nodes) + len(available_gaps))
            candidates = [item for item in available_nodes
                if item.scope == context_scope and item.source == statement_source]
            matching_gaps = [item for item in available_gaps
                if item.scope == context_scope and item.source == statement_source]
            if not candidates:
                reasons.append("NO_SAME_SCOPE_STATEMENT_CONTROL_NODE")
        elif context_scope is None:
            reasons.append("LEXICAL_SCOPE_IS_NOT_UNAMBIGUOUS")
        if matching_gaps:
            reasons.extend("CONTROL_FLOW_GAP: " + gap.reason for gap in matching_gaps)
        if any(item.kind is NodeKind.GAP for item in candidates):
            reasons.append("CONTROL_FLOW_GAP_NODE")
        ordered_nodes = tuple(item.id for item in sorted(
            candidates, key=lambda item: (item.ordinal, item.id.wire)))
        ordered_gaps = tuple(sorted(matching_gaps,
                                    key=lambda item: (item.kind.value, item.reason)))
        return SourceControlContext(
            operation=operation_id,
            scope=context_scope,
            expression_source=expression_source,
            statement_source=statement_source,
            control_nodes=ordered_nodes,
            control_gaps=ordered_gaps,
            field_path=field_path or (),
            boundaries=boundaries,
            gap="; ".join(dict.fromkeys(reasons)) if reasons else None,
            execution_proven=False)

    # Preserve every source-semantics operation, including opaque operations;
    # source/control gaps remain visible instead of being discarded.
    for operation in semantics.operations.values():
        meter.step()
        if operation.source.path != path:
            continue
        snapshot_for_op = semantics.sources.get(operation.source.path)
        if snapshot_for_op is None or operation.source.fingerprint != fingerprint:
            raise ValueError("source operation reference differs from selected snapshot")
        atom = semantic.source_atoms.get(operation.source.atom_id)
        if atom is None or atom.reference != operation.source:
            raise ValueError("source operation reference does not match its SemanticGraph atom")
        candidates = nodes_by_source.get(operation.source, ())
        meter.step(len(candidates))
        node = candidates[0] if len(candidates) == 1 else None
        context = make_context(operation.operation, operation.scope,
                               operation.source, node)
        contexts.append(context)

    # Index Call ASTs even where legacy call inventory has no semantic
    # operation. SourceReference remains the identity; no synthetic ID is made.
    for node, reference in node_refs.items():
        if not isinstance(node, ast.Call):
            continue
        operations = [item for item in semantics_by_source.get(reference, ())
                      if item.opcode is Opcode.CALL]
        meter.step(len(semantics_by_source.get(reference, ())))
        if operations:
            continue
        node_info = info.get(node)
        scope = node_info.scope if node_info is not None else None
        contexts.append(make_context(None, scope, reference, node))

    # Keep work and output deterministic, including same-line sibling calls.
    meter.step(len(contexts) * max(1, len(contexts).bit_length()))
    contexts.sort(key=lambda item: (
        item.expression_source.start_line, item.expression_source.start_column,
        item.expression_source.end_line,
        item.expression_source.end_column if item.expression_source.end_column is not None else -1,
        item.expression_source.atom_id.wire,
        item.operation.wire if item.operation is not None else ""))
    known_scopes: set[OperationDefinitionID] = set()
    for definition in semantic.definitions.values():
        meter.step()
        known_scopes.add(definition.id)
    for module in semantic.modules.values():
        meter.step()
        if module.initializer is not None:
            known_scopes.add(module.initializer)
    for operation in semantics.operations.values():
        meter.step()
        if operation.scope is not None:
            known_scopes.add(operation.scope)
    meter.step(len(contexts))
    return SourceControlContextIndex(
        path, fingerprint, tuple(contexts), tuple(dict.fromkeys(index_gaps)),
        ast_nodes, meter.work, frozenset(known_scopes))


__all__ = [
    "ASTFieldStep", "SourceControlContext", "SourceControlContextIndex",
    "index_source_control_contexts",
]
