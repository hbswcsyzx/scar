"""Source-replayed identities for small, complete source statements.

This module identifies an exact source fragment for review and delta binding.
It does not decide whether moving that fragment is legal, and it never runs
target code.
"""
from __future__ import annotations

import ast
import hashlib
import tokenize

from scar.analysis.control_flow_v2 import validate_source_control_flow
from scar.analysis.source_semantics_v2 import validate_source_semantics
from scar.ir import semantics_v2 as sm
from scar.ir.control_flow_v2 import (
    ControlFlowBudget,
    ControlFlowNodeID,
    NodeKind,
    SourceControlFlowGraph,
)
from scar.ir.source_fragments_v2 import SourceFragment
from scar.ir.v2.semantic import SemanticGraph


_NESTED_SCOPE_EXPRESSIONS = tuple(item for item in (
    ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
    getattr(ast, "NamedExpr", None), getattr(ast, "Await", None),
    getattr(ast, "Yield", None), getattr(ast, "YieldFrom", None),
) if item is not None)
_CONDITIONAL_EXPRESSIONS = tuple(item for item in (
    ast.BoolOp, ast.IfExp,
) if item is not None)


class _Meter:
    def __init__(self, budget: ControlFlowBudget):
        self.budget = budget
        self.nodes = 0
        self.work = 0

    def step(self, amount: int = 1) -> None:
        self.work += amount
        if self.work > self.budget.max_build_work:
            raise ValueError("source fragment derivation work budget exceeded")

    def node(self) -> None:
        self.nodes += 1
        self.step()
        if self.nodes > self.budget.max_ast_nodes:
            raise ValueError("source fragment AST-node budget exceeded")


def _fingerprint(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _module_texts(semantic: SemanticGraph, supplied, budget: ControlFlowBudget):
    modules = [item for item in semantic.modules.values()
               if item.path and item.fingerprint]
    modules.sort(key=lambda item: (item.path, item.id.wire))
    paths = [item.path for item in modules]
    if len(paths) != len(set(paths)):
        raise ValueError("semantic graph has duplicate source paths")
    if supplied is not None:
        if (type(supplied) is not dict
                or any(type(path) is not str or type(text) is not str
                       for path, text in supplied.items())):
            raise ValueError("sources must map paths to decoded text")
        if set(supplied) != set(paths):
            raise ValueError("sources must exactly cover source-versioned modules")

    result = {}
    total_bytes = 0
    for module in modules:
        if supplied is None:
            try:
                with tokenize.open(module.path) as handle:
                    text = handle.read(budget.max_source_bytes + 1)
            except (OSError, UnicodeError, LookupError) as error:
                raise ValueError("cannot read source snapshot " + module.path + ": " + str(error)) from error
        else:
            text = supplied[module.path]
        if type(text) is not str:
            raise ValueError("source snapshot is not text: " + module.path)
        size = len(text.encode("utf-8"))
        total_bytes += size
        if size > budget.max_source_bytes or total_bytes > budget.max_source_bytes:
            raise ValueError("source fragment source-byte budget exceeded")
        fingerprint = _fingerprint(text)
        if fingerprint != module.fingerprint:
            raise ValueError("source fingerprint mismatch: " + module.path)
        # The source overlay is checked by the caller; this local check binds
        # every selected source to the same fingerprint before any AST use.
        result[module.path] = text
    return result


def _point(reference):
    if reference.end_column is None:
        raise ValueError("source fragment anchor has no exact end column")
    return (reference.start_line, reference.start_column,
            reference.end_line, reference.end_column)


def _ast_point(node):
    fields = (getattr(node, "lineno", None), getattr(node, "col_offset", None),
              getattr(node, "end_lineno", None), getattr(node, "end_col_offset", None))
    if any(type(item) is not int for item in fields):
        return None
    return fields


def _ordered_span(reference):
    return (reference.start_line, reference.start_column,
            reference.end_line, reference.end_column)


def _contained(reference, outer):
    if (reference.path != outer.path or reference.fingerprint != outer.fingerprint
            or reference.end_column is None or outer.end_column is None):
        return False
    start = (reference.start_line, reference.start_column)
    end = (reference.end_line, reference.end_column)
    outer_start = (outer.start_line, outer.start_column)
    outer_end = (outer.end_line, outer.end_column)
    return outer_start <= start and end <= outer_end


def _overlaps(reference, outer):
    if reference.path != outer.path or reference.fingerprint != outer.fingerprint:
        return False
    if reference.end_column is None or outer.end_column is None:
        return True
    start = (reference.start_line, reference.start_column)
    end = (reference.end_line, reference.end_column)
    outer_start = (outer.start_line, outer.start_column)
    outer_end = (outer.end_line, outer.end_column)
    return start < outer_end and outer_start < end


def _walk_ast(tree, meter: _Meter):
    pending = [(tree, 0)]
    result = []
    while pending:
        current, depth = pending.pop()
        meter.node()
        if depth > meter.budget.max_nesting:
            raise ValueError("source fragment AST nesting budget exceeded")
        result.append(current)
        children = list(ast.iter_child_nodes(current))
        meter.step(len(children))
        pending.extend((child, depth + 1) for child in reversed(children))
    return result


def _source_operation_ids(semantic, source_semantics, node, reference, meter):
    owned = set(node.operations)
    positions = {}

    # The SG's source atoms identify every modeled operation in the statement,
    # including the statement owner and expression/read/binding definitions.
    for definition in semantic.definitions.values():
        meter.step()
        if definition.parent_id != node.scope:
            continue
        references = []
        for atom_id in definition.source_atoms:
            meter.step()
            atom = semantic.source_atoms.get(atom_id)
            if atom is None:
                raise ValueError("source fragment operation references a missing source atom")
            references.append(atom.reference)
        overlapping = [item for item in references if _overlaps(item, reference)]
        if not overlapping:
            continue
        if not all(_contained(item, reference) for item in references):
            raise ValueError("semantic operation spans outside the selected source statement")
        owned.add(definition.id)
        for item in references:
            position = _ordered_span(item)
            previous = positions.get(position)
            if previous is not None and previous != definition.id:
                raise ValueError("distinct semantic operations have a duplicate source position")
            positions[position] = definition.id

    # Every source-semantics operation in the physical statement must be
    # accounted for, and nested lexical operations are not flattened into the
    # fragment's owner scope.
    for operation in source_semantics.operations.values():
        meter.step()
        if not _overlaps(operation.source, reference):
            continue
        if not _contained(operation.source, reference):
            raise ValueError("source-semantics operation crosses the selected statement boundary")
        if operation.scope != node.scope:
            raise ValueError("nested-scope operation occurs inside the selected statement")
        if operation.operation not in semantic.definitions:
            raise ValueError("source-semantics operation has no SG definition")
        owned.add(operation.operation)
        position = _ordered_span(operation.source)
        previous = positions.get(position)
        if previous is not None and previous != operation.operation:
            raise ValueError("distinct operations have a duplicate source position")
        positions[position] = operation.operation

    if not owned:
        raise ValueError("source fragment contains no semantic operations")
    if len(owned) > meter.budget.max_nodes:
        raise ValueError("source fragment operation count exceeds node budget")
    return tuple(sorted(owned, key=lambda item: item.wire))


def _reject_duplicate_statement_positions(control_flow):
    seen = {}
    statement_kinds = {NodeKind.STATEMENT, NodeKind.BRANCH_TEST,
                       NodeKind.LOOP_TEST, NodeKind.GAP}
    for node in control_flow.nodes.values():
        if node.kind not in statement_kinds or node.source is None:
            continue
        source = node.source
        key = (node.suite, source.path, source.fingerprint,
               source.start_line, source.start_column,
               source.end_line, source.end_column)
        previous = seen.get(key)
        if previous is not None and previous != node.id:
            raise ValueError("control-flow graph has duplicate statement source positions")
        seen[key] = node.id


def _derive(semantic, source_semantics, control_flow, statement, *, sources, budget):
    if type(semantic) is not SemanticGraph:
        raise TypeError("semantic must be SemanticGraph")
    if type(source_semantics) is not sm.SourceSemanticsGraph:
        raise TypeError("source_semantics must be SourceSemanticsGraph")
    if type(control_flow) is not SourceControlFlowGraph:
        raise TypeError("control_flow must be SourceControlFlowGraph")
    if type(statement) is not ControlFlowNodeID:
        raise TypeError("statement must be ControlFlowNodeID")
    if type(budget) is not ControlFlowBudget:
        raise TypeError("verification_budget must be ControlFlowBudget")
    budget.__post_init__()

    semantic.assert_valid()
    source_semantics.assert_valid(semantic)
    _reject_duplicate_statement_positions(control_flow)
    texts = _module_texts(semantic, sources, budget)
    replay = validate_source_semantics(source_semantics, semantic, sources=texts)
    if not replay["valid"]:
        raise ValueError("source-semantics replay failed: " + "; ".join(replay["errors"]))

    cfg_sources = {module.path: texts[module.path]
                   for module in semantic.modules.values()
                   if module.path and module.fingerprint and module.initializer is not None}
    cfg_replay = validate_source_control_flow(control_flow, semantic, source_semantics,
        sources=cfg_sources, verification_budget=budget)
    if not cfg_replay["valid"]:
        raise ValueError("control-flow replay failed: " + "; ".join(cfg_replay["errors"]))

    node = control_flow.nodes.get(statement)
    if node is None:
        raise ValueError("source fragment statement node is absent from the control-flow graph")
    if node.kind is not NodeKind.STATEMENT:
        raise ValueError("source fragment requires one complete simple statement node")
    if node.source is None:
        raise ValueError("source fragment statement has no unique source anchor")
    suite = control_flow.suites.get(node.suite)
    if suite is None or suite.scope != node.scope:
        raise ValueError("source fragment statement has a missing or mismatched suite")
    version = control_flow.sources.get(node.source.path)
    if (version is None or version.fingerprint != node.source.fingerprint
            or suite.version != version):
        raise ValueError("source fragment statement has a stale source version")
    if len(node.operations) != 1:
        raise ValueError("source fragment statement has non-unique SG operation ownership")
    owner = semantic.definitions.get(node.operations[0])
    if (owner is None or owner.parent_id != node.scope
            or node.source.atom_id not in owner.source_atoms):
        raise ValueError("source fragment node is not bound to its exact SG statement owner")

    source_atom = semantic.source_atoms.get(node.source.atom_id)
    if source_atom is None or source_atom.reference != node.source:
        raise ValueError("source fragment anchor differs from the SG source atom")

    text = texts.get(node.source.path)
    if text is None:
        raise ValueError("source fragment path has no caller-owned source snapshot")
    tree = ast.parse(text, filename=node.source.path, type_comments=True)
    meter = _Meter(budget)
    ast_nodes = _walk_ast(tree, meter)
    wanted = _point(node.source)
    matching = [item for item in ast_nodes
                if isinstance(item, ast.stmt) and _ast_point(item) == wanted]
    if len(matching) != 1:
        raise ValueError("source fragment anchor does not identify one unique AST statement")
    statement_node = matching[0]
    if source_atom.kind != type(statement_node).__name__:
        raise ValueError("source fragment AST statement kind differs from its SG source atom")
    if not isinstance(statement_node, ast.Assign):
        raise ValueError("source fragment v1 supports only a simple Assign statement")
    if len(statement_node.targets) != 1 or not isinstance(statement_node.targets[0], ast.Name):
        raise ValueError("source fragment v1 rejects chained, unpacking or non-name assignment targets")
    nested = [item for item in ast_nodes if item is not statement_node
              and isinstance(item, _NESTED_SCOPE_EXPRESSIONS + _CONDITIONAL_EXPRESSIONS)
              and _contained_ast(item, wanted)]
    if nested:
        raise ValueError("source fragment v1 rejects nested-scope or conditional expression regions")

    _validate_physical_statement_span(text, statement_node)

    segment = ast.get_source_segment(text, statement_node)
    if type(segment) is not str or not segment:
        raise ValueError("source fragment AST has no complete source text segment")
    digest = _fingerprint(segment)
    operation_ids = _source_operation_ids(
        semantic, source_semantics, node, node.source, meter)
    return SourceFragment(node.id, node.suite, node.scope, node.source,
                          version, operation_ids, digest)


def _contained_ast(node, outer):
    point = _ast_point(node)
    if point is None:
        return False
    start = (point[0], point[1])
    end = (point[2], point[3])
    return ((outer[0], outer[1]) <= start and end <= (outer[2], outer[3]))


def _validate_physical_statement_span(text, node):
    """Reject statement spans sharing a physical line with trivia/code edits."""
    point = _ast_point(node)
    if point is None:
        raise ValueError("source fragment AST statement has no complete span")
    lines = text.splitlines(keepends=True)
    start_line, start_column, end_line, end_column = point
    if end_line > len(lines):
        raise ValueError("source fragment AST span exceeds its source snapshot")
    try:
        prefix = lines[start_line - 1].encode("utf-8")[:start_column].decode("utf-8")
        suffix = lines[end_line - 1].encode("utf-8")[end_column:].decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("source fragment AST columns split a UTF-8 source character") from error
    if prefix.strip() or suffix.strip():
        raise ValueError("source fragment v1 requires a standalone statement without inline comments or semicolons")


def derive_source_fragment(semantic, source_semantics, control_flow, statement, *,
                           sources=None,
                           verification_budget=ControlFlowBudget()) -> SourceFragment:
    """Derive one exact, source-replayed simple statement fragment.

    The function parses and validates caller-owned source but never evaluates
    imports, expressions, descriptors, or user code.
    """
    return _derive(semantic, source_semantics, control_flow, statement,
                   sources=sources, budget=verification_budget)


def validate_source_fragment(fragment, semantic, source_semantics, control_flow, *,
                             sources=None,
                             verification_budget=ControlFlowBudget()):
    """Independently rederive fragment identity and complete operation membership."""
    from scar.ir.v2._validation import record_errors

    try:
        if type(fragment) is not SourceFragment:
            raise TypeError("fragment must be SourceFragment")
        errors = record_errors(fragment, SourceFragment, "source_fragment")
        if errors:
            raise ValueError("invalid source fragment: " + "; ".join(errors))
        expected = _derive(semantic, source_semantics, control_flow,
                           fragment.statement, sources=sources,
                           budget=verification_budget)
        if fragment != expected:
            return {"valid": False,
                    "errors": ["source fragment differs from source replay and complete operation membership"]}
    except (ValueError, TypeError, KeyError, AttributeError, OSError, UnicodeError,
            SyntaxError, RecursionError) as error:
        return {"valid": False, "errors": [str(error)]}
    return {"valid": True, "errors": []}


__all__ = ["derive_source_fragment", "validate_source_fragment"]
