"""Source-replayed bounded structured control flow for candidate placement.

The graph is an AST-derived control skeleton, not a Python interpreter or a
MOVE approval. Unsupported constructs keep explicit gaps and do not become
ordinary sequence edges. Query reports are recomputed from this graph and are
only structural candidates.
"""
from __future__ import annotations

import ast
from collections import defaultdict, deque
from dataclasses import replace
import hashlib
import json
import tokenize
from typing import Any

from scar.ir.control_flow_v2 import (
    ControlFlowBudget, ControlFlowEdge, ControlFlowEdgeID, ControlFlowGap,
    ControlFlowNode, ControlFlowNodeID, ControlFlowSuite, ControlFlowSuiteID,
    DominanceReport, DominanceRequest, EdgeKind, GapKind, InsertionKind,
    InsertionPoint, InsertionPointID, MustExecuteReport, MustExecuteRequest,
    NodeKind, QueryMode, QueryStatus, ReachabilityReport, ReachabilityRequest,
    SourceControlFlowGraph, SourceVersion, SuiteKind,
)
from scar.ir.v2._validation import record_errors
from scar.ir.v2.ids import OperationDefinitionID
from scar.ir.v2.semantic import OperationKind, SemanticGraph


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _key(*parts: Any) -> str:
    return hashlib.sha256("\x00".join(str(part) for part in parts).encode("utf-8")).hexdigest()


class _Meter:
    def __init__(self, budget: ControlFlowBudget):
        self.budget = budget
        self.ast_nodes = 0
        self.nodes = 0
        self.edges = 0
        self.build_work = 0

    def step(self, amount: int = 1) -> None:
        self.build_work += amount
        if self.build_work > self.budget.max_build_work:
            raise ValueError("source control-flow construction work budget exceeded")

    def ast_node(self) -> None:
        self.ast_nodes += 1
        self.step()
        if self.ast_nodes > self.budget.max_ast_nodes:
            raise ValueError("source control-flow AST-node budget exceeded")


class _Builder:
    def __init__(self, semantic, source_semantics, texts, versions, budget):
        self.semantic = semantic
        self.source_semantics = source_semantics
        self.texts = texts
        self.versions = versions
        self.budget = budget
        self.meter = _Meter(budget)
        self.nodes = {}
        self.edges = {}
        self.suites = {}
        self.insertions = {}
        self.gaps = []
        self.atom_by_span = defaultdict(list)
        self.definitions_by_atom = defaultdict(list)
        self._node_ordinals = defaultdict(int)
        self._edge_seen = set()
        self._gap_seen = set()
        self._registered_function_scopes = set()
        self._suite_complete = {}
        for atom in semantic.source_atoms.values():
            ref = atom.reference
            self.atom_by_span[(ref.path, atom.kind, ref.start_line, ref.end_line,
                               ref.start_column, ref.end_column)].append(atom)
        for definition in semantic.definitions.values():
            for atom in definition.source_atoms:
                self.definitions_by_atom[atom].append(definition)

    def _node(self, suite, kind, *, operations=(), source=None, label="", identity=None):
        self.meter.step()
        self.meter.nodes += 1
        if self.meter.nodes > self.budget.max_nodes:
            raise ValueError("source control-flow node budget exceeded")
        ordinal = self._node_ordinals[suite]
        self._node_ordinals[suite] += 1
        token = identity if identity is not None else _key(
            suite.wire, kind.value, source.atom_id.wire if source else "",
            tuple(item.wire for item in operations), label, ordinal)
        node_id = ControlFlowNodeID(token)
        self.nodes[node_id] = ControlFlowNode(
            node_id, kind, self.suites[suite].scope if suite in self.suites else self._suite_scopes[suite],
            suite, tuple(operations), source, ordinal, label)
        return node_id

    def _edge(self, source, target, kind, operation=None):
        identity = (source, target, kind, operation)
        if identity in self._edge_seen:
            return
        self.meter.step()
        self.meter.edges += 1
        if self.meter.edges > self.budget.max_edges:
            raise ValueError("source control-flow edge budget exceeded")
        self._edge_seen.add(identity)
        edge_id = ControlFlowEdgeID(_key(
            source.wire, target.wire, kind.value,
            operation.wire if operation is not None else ""))
        self.edges[edge_id] = ControlFlowEdge(edge_id, source, target, kind, operation)

    def _gap(self, kind, suite, source, operation, reason):
        self.meter.step()
        record = ControlFlowGap(kind, self.suites[suite].scope, suite,
                                source, operation, reason)
        if record not in self._gap_seen:
            self._gap_seen.add(record)
            self.gaps.append(record)
        if kind not in {GapKind.BRANCH_FEASIBILITY, GapKind.DEFERRED_SCOPE}:
            self._suite_complete[suite] = False

    def _suite(self, scope, kind, parent, owner, source, version, *, complete=True):
        suite_id = ControlFlowSuiteID(_key(
            "suite", scope.wire, kind.value, parent.wire if parent else "root",
            owner.wire if owner else "", source.atom_id.wire if source else version.path,
            version.fingerprint))
        if suite_id in self.suites:
            return suite_id
        self._suite_scopes[suite_id] = scope
        self._suite_complete[suite_id] = complete
        parent_scope = self.suites[parent].scope if parent in self.suites else None
        entry_kind = (NodeKind.SCOPE_ENTRY if parent is None or parent_scope != scope
                      else NodeKind.SUITE_ENTRY)
        entry = self._node(suite_id, entry_kind, source=source,
                           label="scope entry" if parent is None else "suite entry")
        normal_exit = self._node(suite_id, NodeKind.NORMAL_EXIT, source=source,
                                 label="normal exit")
        exception_exit = self._node(suite_id, NodeKind.EXCEPTION_EXIT, source=source,
                                    label="exception exit")
        self.suites[suite_id] = ControlFlowSuite(
            suite_id, scope, kind, parent, owner, source, entry, normal_exit,
            exception_exit, version, complete)
        self._insertion(suite_id, InsertionKind.ENTRY, entry, None, None, version)
        return suite_id

    def _insertion(self, suite, kind, node, anchor, source, version):
        self.meter.step()
        point_id = InsertionPointID(_key(
            "insertion", suite.wire, kind.value, node.wire,
            anchor.wire if anchor else "", version.path, version.fingerprint))
        self.insertions[point_id] = InsertionPoint(
            point_id, suite, kind, node, anchor, source, version)
        return point_id

    @staticmethod
    def _span(node):
        return (type(node).__name__, getattr(node, "lineno", None),
                getattr(node, "end_lineno", None), getattr(node, "col_offset", None),
                getattr(node, "end_col_offset", None))

    def _source_ref(self, node, path):
        _, start, end, column, end_column = self._span(node)
        if start is None:
            return None, None
        candidates = self.atom_by_span.get((path, type(node).__name__, start, end,
                                            column, end_column), ())
        if len(candidates) != 1:
            return None, None
        atom = candidates[0]
        return atom.reference, atom

    def _statement_operations(self, node, scope, path):
        reference, atom = self._source_ref(node, path)
        if atom is None:
            return (), reference, GapKind.MISSING_SOURCE_OPERATION
        candidates = [item for item in self.definitions_by_atom.get(atom.id, ())
                      if item.parent_id == scope
                      and item.source_file == path
                      and item.source_start == getattr(node, "lineno", None)
                      and item.source_end == getattr(node, "end_lineno", None)]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            expected_label = "define " + node.name
            candidates = [item for item in candidates
                          if item.kind is OperationKind.OPERATOR and item.label == expected_label]
        elif isinstance(node, ast.ClassDef):
            candidates = [item for item in candidates
                          if item.kind is OperationKind.OPAQUE and item.label == "class " + node.name]
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            candidates = [item for item in candidates if item.kind is OperationKind.IMPORT]
        elif isinstance(node, (ast.If,)):
            candidates = [item for item in candidates if item.kind is OperationKind.BRANCH]
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            candidates = [item for item in candidates if item.kind is OperationKind.LOOP]
        elif isinstance(node, (ast.Try, getattr(ast, "TryStar", ast.Try))):
            candidates = [item for item in candidates if item.kind is OperationKind.REGION]
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            candidates = [item for item in candidates if item.kind is OperationKind.OPAQUE]
        elif isinstance(node, ast.Return):
            candidates = [item for item in candidates
                          if item.kind in {OperationKind.OPERATOR, OperationKind.OPAQUE}
                          and item.label == "return"]
        else:
            candidates = [item for item in candidates if item.label == type(node).__name__]
        candidates.sort(key=lambda item: item.id.wire)
        if not candidates:
            return (), reference, GapKind.MISSING_SOURCE_OPERATION
        if len(candidates) > 1 and not isinstance(node, (ast.Import, ast.ImportFrom)):
            return tuple(item.id for item in candidates), reference, GapKind.AMBIGUOUS_SOURCE_OPERATION
        return tuple(item.id for item in candidates), reference, None

    def _body_scope(self, node, parent_scope, path, reference, version):
        _, atom = self._source_ref(node, path)
        if atom is None:
            return None
        expected = {OperationKind.FUNCTION, OperationKind.METHOD}
        candidates = [item for item in self.definitions_by_atom.get(atom.id, ())
                      if item.kind in expected and item.parent_id == parent_scope
                      and item.source_file == path
                      and item.source_start == getattr(node, "lineno", None)
                      and item.source_end == getattr(node, "end_lineno", None)]
        candidates.sort(key=lambda item: item.id.wire)
        return candidates[0].id if len(candidates) == 1 else None

    def _has_direct_yield_or_await(self, statement):
        pending = [statement]
        first = True
        while pending:
            self.meter.step()
            current = pending.pop()
            if not first and isinstance(current, (ast.stmt, ast.FunctionDef,
                                                   ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            first = False
            if isinstance(current, (ast.Yield, ast.YieldFrom, ast.Await)):
                return current
            children = list(ast.iter_child_nodes(current))
            self.meter.step(len(children))
            pending.extend(children)
        return None

    def _new_statement(self, suite, statement, scope, path, version):
        operations, source, gap = self._statement_operations(statement, scope, path)
        kind = NodeKind.STATEMENT
        if isinstance(statement, ast.If):
            kind = NodeKind.BRANCH_TEST
        elif isinstance(statement, (ast.For, ast.While, ast.AsyncFor)):
            kind = NodeKind.LOOP_TEST
        elif gap is not None:
            kind = NodeKind.GAP
        node = self._node(suite, kind, operations=operations, source=source,
                          label=type(statement).__name__)
        before = self._node(suite, NodeKind.INSERTION, source=source,
                            label="before " + type(statement).__name__)
        after = self._node(suite, NodeKind.INSERTION, source=source,
                           label="after " + type(statement).__name__)
        if source is not None:
            # An insertion is a source edit location, so it requires a unique
            # AST atom. Keep the CFG statement and its gap even when SCAR has
            # no trustworthy source anchor, but never advertise that node as
            # an insertion point.
            self._insertion(suite, InsertionKind.BEFORE, before, node, source, version)
            self._insertion(suite, InsertionKind.AFTER, after, node, source, version)
        operation = operations[0] if len(operations) == 1 else None
        if gap is not None:
            gap_kind = gap
            reason = ("No unique fingerprinted SemanticGraph operation owns this source statement."
                      if gap is GapKind.MISSING_SOURCE_OPERATION else
                      "Multiple candidate operations prevent a unique source statement join.")
            if len(operations) > 1:
                gap_kind = GapKind.AMBIGUOUS_SOURCE_OPERATION
            self._gap(gap_kind, suite, source, operation, reason)
        return node, before, after, operations, source

    def _compile_suite(self, suite_id, statements, *, path, version,
                       return_target, loop_stack=(), depth=0):
        if depth > self.budget.max_nesting:
            raise ValueError("source control-flow nesting budget exceeded")
        suite = self.suites[suite_id]
        next_node = suite.normal_exit
        for statement in reversed(statements):
            self.meter.step()
            next_node = self._compile_statement(
                statement, suite_id, next_node, path=path, version=version,
                return_target=return_target, loop_stack=loop_stack, depth=depth)
        self._edge(suite.entry, next_node, EdgeKind.SEQUENCE)

    def _add_exception(self, node, suite, operation=None):
        self._edge(node, self.suites[suite].exception_exit, EdgeKind.MAY_RAISE, operation)

    def _child_suite(self, parent_suite, scope, kind, owner, source, version, statements,
                     *, return_target, loop_stack, depth):
        child = self._suite(scope, kind, parent_suite, owner, source, version)
        self._compile_suite(child, statements, path=version.path, version=version,
                            return_target=return_target, loop_stack=loop_stack,
                            depth=depth + 1)
        self._edge(self.suites[child].exception_exit,
                   self.suites[parent_suite].exception_exit,
                   EdgeKind.EXCEPTION_PROPAGATION, owner)
        return child

    def _register_function_body(self, statement, parent_suite, parent_scope,
                                source, path, version, depth):
        if depth + 1 > self.budget.max_nesting:
            raise ValueError("source control-flow nesting budget exceeded")
        body_scope = self._body_scope(statement, parent_scope, path, source, version)
        operations, _, _ = self._statement_operations(statement, parent_scope, path)
        operation = operations[0] if len(operations) == 1 else None
        if body_scope is None:
            self._gap(GapKind.AMBIGUOUS_SOURCE_OPERATION, parent_suite, source, operation,
                      "Function body has no unique source-matched lexical scope.")
            return
        if body_scope in self._registered_function_scopes:
            return
        self._registered_function_scopes.add(body_scope)
        is_async = isinstance(statement, ast.AsyncFunctionDef)
        generator = (not is_async and _contains_yield(statement.body, self.meter))
        opaque = is_async or generator
        suite = self._suite(body_scope,
            SuiteKind.OPAQUE if opaque else SuiteKind.FUNCTION,
            parent_suite, body_scope, source, version, complete=not opaque)
        self._gap(GapKind.DEFERRED_SCOPE, parent_suite, source, operation,
                  "Function execution is deferred; no call edge is inferred from its declaration.")
        if is_async:
            self._gap(GapKind.ASYNC_SEMANTICS, suite, source, body_scope,
                      "Async function scheduling and suspension points are not modeled.")
            self._preserve_nested_definitions(statement.body, suite, body_scope,
                                              path, version, depth + 1)
        elif generator:
            self._gap(GapKind.YIELD_SEMANTICS, suite, source, body_scope,
                      "Generator suspension/resumption order is not modeled.")
            self._preserve_nested_definitions(statement.body, suite, body_scope,
                                              path, version, depth + 1)
        else:
            self._compile_suite(suite, statement.body, path=path, version=version,
                                return_target=self.suites[suite].normal_exit,
                                loop_stack=(), depth=depth + 1)

    def _preserve_nested_definitions(self, statements, parent_suite, lexical_scope,
                                     path, version, depth):
        """Retain detached function/class scopes below an opaque statement."""
        pending = list(statements)
        while pending:
            self.meter.step()
            node = pending.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                source, _ = self._source_ref(node, path)
                self._register_function_body(node, parent_suite, lexical_scope,
                                             source, path, version, depth + 1)
                continue
            if isinstance(node, ast.ClassDef):
                source, _ = self._source_ref(node, path)
                self._preserve_class_methods(node, parent_suite, lexical_scope,
                                             source, path, version, depth + 1)
                continue
            children = list(ast.iter_child_nodes(node))
            self.meter.step(len(children))
            pending.extend(children)

    def _preserve_class_methods(self, statement, parent_suite, parent_scope,
                                source, path, version, depth):
        if depth + 1 > self.budget.max_nesting:
            raise ValueError("source control-flow nesting budget exceeded")
        operations, _, _ = self._statement_operations(statement, parent_scope, path)
        class_operation = operations[0] if len(operations) == 1 else None
        if class_operation is None:
            self._gap(GapKind.CLASS_NAMESPACE, parent_suite, source, None,
                      "Class declaration has no unique source-matched namespace operation.")
            return
        class_suite = self._suite(class_operation, SuiteKind.OPAQUE, parent_suite,
                                  class_operation, source, version, complete=False)
        self._gap(GapKind.CLASS_NAMESPACE, class_suite, source, class_operation,
                  "Class-body execution and custom namespace semantics are not modeled.")
        # The class suite records lexical containment only. It deliberately has
        # no execution edge from the class statement or to any method entry.
        self._preserve_nested_definitions(statement.body, class_suite,
                                          class_operation, path, version, depth + 1)

    def _compile_statement(self, statement, suite_id, next_node, *, path, version,
                           return_target, loop_stack, depth):
        suite = self.suites[suite_id]
        statement_node, before, after, operations, source = self._new_statement(
            suite_id, statement, suite.scope, path, version)
        operation = operations[0] if len(operations) == 1 else None
        self._edge(after, next_node, EdgeKind.SEQUENCE, operation)

        if isinstance(statement, (ast.Try, getattr(ast, "TryStar", ast.Try))):
            self._edge(before, statement_node, EdgeKind.SEQUENCE, operation)
            self._edge(statement_node, after, EdgeKind.UNKNOWN_CONTINUATION, operation)
            self._add_exception(statement_node, suite_id, operation)
            self._gap(GapKind.TRY_SEMANTICS, suite_id, source, operation,
                      "Try/except/else/finally dispatch and exception state are not modeled; continuation is unknown.")
            self._preserve_nested_definitions([statement], suite_id, suite.scope,
                                              path, version, depth)
            return before
        if isinstance(statement, (ast.With, ast.AsyncWith)):
            self._edge(before, statement_node, EdgeKind.SEQUENCE, operation)
            self._edge(statement_node, after, EdgeKind.UNKNOWN_CONTINUATION, operation)
            self._add_exception(statement_node, suite_id, operation)
            kind = GapKind.ASYNC_SEMANTICS if isinstance(statement, ast.AsyncWith) else GapKind.WITH_SEMANTICS
            self._gap(kind, suite_id, source, operation,
                      "Context manager enter/exit, suppression and exceptional control are not modeled.")
            self._preserve_nested_definitions([statement], suite_id, suite.scope,
                                              path, version, depth)
            return before
        if isinstance(statement, ast.ClassDef):
            self._edge(before, statement_node, EdgeKind.SEQUENCE, operation)
            self._edge(statement_node, after, EdgeKind.UNKNOWN_CONTINUATION, operation)
            self._add_exception(statement_node, suite_id, operation)
            self._gap(GapKind.CLASS_NAMESPACE, suite_id, source, operation,
                      "Class-body execution and custom namespace semantics are not modeled as a suite.")
            self._preserve_class_methods(statement, suite_id, suite.scope,
                                         source, path, version, depth)
            return before
        dynamic = self._has_direct_yield_or_await(statement)
        if dynamic is not None:
            self._edge(before, statement_node, EdgeKind.SEQUENCE, operation)
            self._edge(statement_node, after, EdgeKind.UNKNOWN_CONTINUATION, operation)
            self._add_exception(statement_node, suite_id, operation)
            kind = GapKind.ASYNC_SEMANTICS if isinstance(dynamic, ast.Await) else GapKind.YIELD_SEMANTICS
            self._gap(kind, suite_id, source, operation,
                      "Yield/await suspension and resumption order are not modeled.")
            return before
        if isinstance(statement, (ast.AsyncFor,)):
            self._edge(before, statement_node, EdgeKind.SEQUENCE, operation)
            self._edge(statement_node, after, EdgeKind.UNKNOWN_CONTINUATION, operation)
            self._add_exception(statement_node, suite_id, operation)
            self._gap(GapKind.ASYNC_SEMANTICS, suite_id, source, operation,
                      "Async iteration and suspension points are not modeled.")
            self._preserve_nested_definitions([statement], suite_id, suite.scope,
                                              path, version, depth)
            return before
        if isinstance(statement, ast.If):
            true_suite = self._child_suite(suite_id, suite.scope, SuiteKind.IF_TRUE,
                operation, source, version, statement.body,
                return_target=return_target, loop_stack=loop_stack, depth=depth)
            false_suite = self._child_suite(suite_id, suite.scope, SuiteKind.IF_FALSE,
                operation, source, version, statement.orelse,
                return_target=return_target, loop_stack=loop_stack, depth=depth)
            self._edge(before, statement_node, EdgeKind.SEQUENCE, operation)
            self._edge(statement_node, self.suites[true_suite].entry, EdgeKind.IF_TRUE, operation)
            self._edge(statement_node, self.suites[false_suite].entry, EdgeKind.IF_FALSE, operation)
            self._edge(self.suites[true_suite].normal_exit, after, EdgeKind.SEQUENCE, operation)
            self._edge(self.suites[false_suite].normal_exit, after, EdgeKind.SEQUENCE, operation)
            self._add_exception(statement_node, suite_id, operation)
            self._gap(GapKind.BRANCH_FEASIBILITY, suite_id, source, operation,
                      "Predicate truth is not evaluated; both branches remain possible, including literal True/False.")
            return before
        if isinstance(statement, (ast.For, ast.While)):
            body_kind = SuiteKind.FOR_BODY if isinstance(statement, ast.For) else SuiteKind.WHILE_BODY
            else_kind = SuiteKind.FOR_ELSE if isinstance(statement, ast.For) else SuiteKind.WHILE_ELSE
            context = (after, statement_node)
            child_stack = loop_stack + (context,)
            body_suite = self._child_suite(suite_id, suite.scope, body_kind,
                operation, source, version, statement.body,
                return_target=return_target, loop_stack=child_stack, depth=depth)
            else_suite = self._child_suite(suite_id, suite.scope, else_kind,
                operation, source, version, statement.orelse,
                return_target=return_target, loop_stack=loop_stack, depth=depth)
            self._edge(before, statement_node, EdgeKind.SEQUENCE, operation)
            self._edge(statement_node, self.suites[body_suite].entry, EdgeKind.LOOP_BODY, operation)
            self._edge(statement_node, self.suites[else_suite].entry, EdgeKind.LOOP_ZERO_EXIT, operation)
            self._edge(self.suites[body_suite].normal_exit, statement_node,
                       EdgeKind.LOOP_BACKEDGE, operation)
            self._edge(self.suites[else_suite].normal_exit, after, EdgeKind.LOOP_ELSE, operation)
            self._add_exception(statement_node, suite_id, operation)
            if isinstance(statement, ast.For):
                self._gap(GapKind.USER_ITERATION, suite_id, source, operation,
                          "Iterator construction/next may run user code, raise, or have side effects.")
            else:
                self._gap(GapKind.LOOP_FEASIBILITY, suite_id, source, operation,
                          "Loop predicate truth and iteration count are not evaluated; zero-trip remains possible.")
            return before
        if isinstance(statement, ast.Break):
            self._edge(before, statement_node, EdgeKind.SEQUENCE, operation)
            if loop_stack:
                break_target, _ = loop_stack[-1]
                self._edge(statement_node, break_target, EdgeKind.BREAK, operation)
            else:
                self._edge(statement_node, suite.exception_exit, EdgeKind.UNKNOWN_CONTINUATION, operation)
                self._gap(GapKind.UNSUPPORTED_CONTROL, suite_id, source, operation,
                          "Break has no modeled enclosing loop.")
            return before
        if isinstance(statement, ast.Continue):
            self._edge(before, statement_node, EdgeKind.SEQUENCE, operation)
            if loop_stack:
                _, continue_target = loop_stack[-1]
                self._edge(statement_node, continue_target, EdgeKind.CONTINUE, operation)
            else:
                self._edge(statement_node, suite.exception_exit, EdgeKind.UNKNOWN_CONTINUATION, operation)
                self._gap(GapKind.UNSUPPORTED_CONTROL, suite_id, source, operation,
                          "Continue has no modeled enclosing loop.")
            return before
        if isinstance(statement, ast.Return):
            self._edge(before, statement_node, EdgeKind.SEQUENCE, operation)
            self._edge(statement_node, return_target, EdgeKind.RETURN, operation)
            if statement.value is not None:
                self._add_exception(statement_node, suite_id, operation)
            return before
        if isinstance(statement, ast.Raise):
            self._edge(before, statement_node, EdgeKind.SEQUENCE, operation)
            self._edge(statement_node, suite.exception_exit, EdgeKind.RAISE, operation)
            if statement.exc is not None or statement.cause is not None:
                self._add_exception(statement_node, suite_id, operation)
            return before

        modeled_simple = isinstance(statement, (
            ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Expr, ast.Pass,
            ast.Global, ast.Nonlocal, ast.Assert, ast.Delete, ast.Import,
            ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef,
        ))
        if not modeled_simple:
            self._edge(before, statement_node, EdgeKind.SEQUENCE, operation)
            self._edge(statement_node, after, EdgeKind.UNKNOWN_CONTINUATION, operation)
            self._add_exception(statement_node, suite_id, operation)
            self._gap(GapKind.UNSUPPORTED_CONTROL, suite_id, source, operation,
                      "This Python statement form is outside the modeled structured CFG subset.")
            self._preserve_nested_definitions([statement], suite_id, suite.scope,
                                              path, version, depth)
            return before

        self._edge(before, statement_node, EdgeKind.SEQUENCE, operation)
        if not isinstance(statement, (ast.Pass, ast.Global, ast.Nonlocal)):
            self._add_exception(statement_node, suite_id, operation)
        else:
            self._edge(statement_node, after, EdgeKind.SEQUENCE, operation)

        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._register_function_body(statement, suite_id, suite.scope,
                                         source, path, version, depth)
            # The definition statement can raise while evaluating defaults or decorators.
            self._edge(statement_node, after, EdgeKind.SEQUENCE, operation)
        else:
            self._edge(statement_node, after, EdgeKind.SEQUENCE, operation)
            if any(isinstance(item, ast.Lambda)
                   for item in _direct_expression_nodes(statement, self.meter)):
                self._gap(GapKind.DEFERRED_SCOPE, suite_id, source, operation,
                          "Lambda body execution is deferred and has no source-order edge.")
        return before

    def build(self):
        self._suite_scopes = {}
        module_rows = sorted((module for module in self.semantic.modules.values()
                              if module.path and module.fingerprint and module.initializer is not None),
                             key=lambda item: (item.path, item.id.wire))
        seen_paths = set()
        source_versions = {}
        trees = {}
        for module in module_rows:
            self.meter.step()
            if module.path in seen_paths:
                raise ValueError("source path has multiple module identities")
            seen_paths.add(module.path)
            text = self.texts[module.path]
            fingerprint = _fingerprint(text)
            if fingerprint != module.fingerprint:
                raise ValueError("source fingerprint differs from SemanticGraph module: " + module.path)
            overlay_source = self.source_semantics.sources.get(module.path)
            if overlay_source is None or overlay_source.fingerprint != fingerprint:
                raise ValueError("source semantics snapshot differs from control-flow source: " + module.path)
            version = SourceVersion(module.path, fingerprint)
            source_versions[module.path] = version
            try:
                tree = ast.parse(text, filename=module.path, type_comments=True)
            except (SyntaxError, ValueError, TypeError) as exc:
                raise ValueError("source parse failed for " + module.path + ": " + str(exc)) from exc
            nodes = _count_ast(tree, self.meter)
            trees[module.path] = (module, tree, nodes, version)

        module_suites = {}
        for path in sorted(trees):
            module, tree, _, version = trees[path]
            suite_id = self._suite(module.initializer, SuiteKind.MODULE, None,
                                   module.initializer, None, version)
            module_suites[path] = suite_id
            self._compile_suite(suite_id, tree.body, path=path, version=version,
                                return_target=self.suites[suite_id].normal_exit,
                                loop_stack=())

        graph = SourceControlFlowGraph(
            sources=source_versions,
            suites={key: replace(value, complete=self._suite_complete[key])
                    for key, value in self.suites.items()},
            nodes=self.nodes,
            edges=self.edges, insertions=self.insertions,
            gaps=tuple(sorted(self.gaps, key=_gap_key)),
            semantic_digest=_digest(self.semantic.to_dict()),
            source_semantics_digest=_digest(self.source_semantics.to_dict()))
        graph.assert_valid(self.semantic, self.source_semantics)
        return graph


def _fingerprint(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _count_ast(tree, meter):
    count = 0
    pending = [tree]
    while pending:
        current = pending.pop()
        meter.ast_node()
        count += 1
        children = list(ast.iter_child_nodes(current))
        meter.step(len(children))
        pending.extend(children)
    return count


def _contains_yield(statements, meter):
    pending = list(statements)
    while pending:
        meter.step()
        current = pending.pop()
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(current, (ast.Yield, ast.YieldFrom)):
            return True
        children = list(ast.iter_child_nodes(current))
        meter.step(len(children))
        pending.extend(children)
    return False


def _direct_expression_nodes(statement, meter):
    pending = [statement]
    first = True
    while pending:
        meter.step()
        current = pending.pop()
        if not first and isinstance(current, ast.stmt):
            continue
        if not first and isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef,
                                               ast.ClassDef, ast.Lambda)):
            continue
        first = False
        yield current
        children = list(ast.iter_child_nodes(current))
        meter.step(len(children))
        pending.extend(children)


def _gap_key(item):
    return (item.scope.wire, item.suite.wire, item.kind.value,
            item.source.path if item.source else "",
            item.source.start_line if item.source else 0,
            item.operation.wire if item.operation else "", item.reason)


def _load_source_texts(semantic, source_semantics, sources, budget):
    modules_by_path = {}
    for module in semantic.modules.values():
        if module.path and module.fingerprint and module.initializer is not None:
            if module.path in modules_by_path:
                raise ValueError("source path has multiple module identities")
            modules_by_path[module.path] = module
    paths = sorted(modules_by_path)
    if sources is not None and (type(sources) is not dict
            or any(type(path) is not str or type(text) is not str
                   for path, text in sources.items())):
        raise ValueError("sources must map source paths to decoded text")
    if sources is not None and set(sources) != set(paths):
        raise ValueError("sources must exactly cover local module paths")
    result = {}
    total_bytes = 0
    for path in paths:
        if sources is None:
            try:
                with tokenize.open(path) as file:
                    text = file.read(budget.max_source_bytes + 1)
            except (OSError, UnicodeError, LookupError) as exc:
                raise ValueError("cannot read source snapshot " + path + ": " + str(exc)) from exc
        else:
            text = sources[path]
        if type(text) is not str:
            raise ValueError("decoded source must be text: " + path)
        size = len(text.encode("utf-8"))
        total_bytes += size
        if size > budget.max_source_bytes or total_bytes > budget.max_source_bytes:
            raise ValueError("source control-flow source-byte budget exceeded")
        snapshot = source_semantics.sources.get(path)
        module = modules_by_path[path]
        fingerprint = _fingerprint(text)
        if snapshot is None or snapshot.fingerprint != fingerprint or module.fingerprint != fingerprint:
            raise ValueError("source fingerprint mismatch: " + path)
        result[path] = text
    return result


def build_source_control_flow(semantic: SemanticGraph, source_semantics,
                              *, sources: dict[str, str] | None = None,
                              budget: ControlFlowBudget = ControlFlowBudget()) -> SourceControlFlowGraph:
    """Replay bounded Python AST control structure into a typed candidate CFG.

    ``sources`` may provide caller-owned decoded source. When omitted, local
    module files are read with Python's encoding-cookie handling. No source is
    executed. Repeated module/SG scans are indexed once, and all AST/CFG work
    is metered by ``budget``.
    """
    from scar.analysis.source_semantics_v2 import validate_source_semantics
    from scar.ir.semantics_v2 import SourceSemanticsGraph

    if type(semantic) is not SemanticGraph or type(source_semantics) is not SourceSemanticsGraph:
        raise TypeError("control-flow construction requires SemanticGraph and SourceSemanticsGraph")
    if type(budget) is not ControlFlowBudget:
        raise TypeError("budget must be ControlFlowBudget")
    budget.__post_init__()
    semantic.assert_valid()
    source_semantics.assert_valid(semantic)
    texts = _load_source_texts(semantic, source_semantics, sources, budget)
    source_report = validate_source_semantics(source_semantics, semantic, sources=texts)
    if not source_report["valid"]:
        raise ValueError("source semantics replay failed: " + "; ".join(source_report["errors"]))
    builder = _Builder(semantic, source_semantics, texts,
                       {path: SourceVersion(path, _fingerprint(text)) for path, text in texts.items()},
                       budget)
    try:
        return builder.build()
    except RecursionError as exc:
        raise ValueError("source control-flow nesting exceeds interpreter construction limit") from exc


def validate_source_control_flow(graph: SourceControlFlowGraph, semantic: SemanticGraph,
                                 source_semantics, *, sources: dict[str, str] | None = None,
                                 verification_budget: ControlFlowBudget = ControlFlowBudget()) -> dict[str, Any]:
    """Strictly recompute the graph from source, SG and source-semantics inputs."""
    try:
        if type(verification_budget) is not ControlFlowBudget:
            raise TypeError("verification_budget must be ControlFlowBudget")
        verification_budget.__post_init__()
        validation_work = _graph_validation_work(graph)
        if validation_work > verification_budget.max_build_work:
            return {"valid": False,
                    "errors": ["control-flow verification budget exceeded during graph validation"]}
        if type(graph) is not SourceControlFlowGraph:
            raise TypeError("expected SourceControlFlowGraph")
        graph.assert_valid(semantic, source_semantics)
        remaining_work = verification_budget.max_build_work - validation_work
        if remaining_work < 1:
            return {"valid": False,
                    "errors": ["control-flow verification budget exhausted before source replay"]}
        expected = build_source_control_flow(
            semantic, source_semantics, sources=sources,
            budget=replace(verification_budget, max_build_work=remaining_work))
        if graph.to_dict() != expected.to_dict():
            return {"valid": False, "errors": ["control-flow graph differs from source replay"]}
    except (ValueError, TypeError, KeyError, AttributeError, OSError, SyntaxError) as exc:
        return {"valid": False, "errors": [str(exc)]}
    return {"valid": True, "errors": [], "summary": graph.summary()}


def _node_maps(graph, max_work):
    edge_count = len(graph.edges)
    if edge_count > max_work:
        return None, edge_count, "query work budget exceeded while indexing edges"
    outgoing = defaultdict(list)
    for edge in graph.edges.values():
        outgoing[edge.source].append(edge)
    work = edge_count
    sort_estimate = sum(size * size.bit_length()
                        for size in (len(items) for items in outgoing.values()) if size > 1)
    if work + sort_estimate > max_work:
        return None, work, "query work budget exceeded while ordering adjacency"
    for edges in outgoing.values():
        edges.sort(key=lambda item: (item.kind.value, item.target.wire, item.id.wire))
    return outgoing, work + sort_estimate, ""


def _included(edge, mode):
    if mode is QueryMode.ALL_PATHS:
        return True
    return edge.kind not in {EdgeKind.RAISE, EdgeKind.MAY_RAISE,
                             EdgeKind.EXCEPTION_PROPAGATION}


def _uncertain_edge(kind):
    return kind in {EdgeKind.IF_TRUE, EdgeKind.IF_FALSE,
                    EdgeKind.LOOP_BODY, EdgeKind.LOOP_BACKEDGE,
                    EdgeKind.LOOP_ZERO_EXIT, EdgeKind.LOOP_ELSE,
                    EdgeKind.MAY_RAISE, EdgeKind.UNKNOWN_CONTINUATION}


def _path(outgoing, start, target, mode, max_work, *, forbidden=None):
    queue = deque([start])
    parent = {start: (None, None)}
    work = 0
    while queue:
        node = queue.popleft()
        work += 1
        if work > max_work:
            return None, work, "query work budget exceeded"
        if node == target:
            break
        for edge in outgoing.get(node, ()):
            work += 1
            if work > max_work:
                return None, work, "query work budget exceeded"
            if not _included(edge, mode) or edge.target == forbidden or edge.target in parent:
                continue
            parent[edge.target] = (node, edge)
            queue.append(edge.target)
    if target not in parent:
        return (), work, ""
    nodes = [target]
    edges = []
    current = target
    while parent[current][0] is not None:
        previous, edge = parent[current]
        edges.append(edge)
        nodes.append(previous)
        current = previous
    nodes.reverse()
    edges.reverse()
    return (tuple(nodes), tuple(edges)), work, ""


def _query_inputs(graph, suite_id, *nodes):
    suite = graph.suites.get(suite_id)
    if suite is None:
        raise ValueError("unknown control-flow suite")
    if any(node not in graph.nodes for node in nodes):
        raise ValueError("query references an unknown control-flow node")
    if any(graph.nodes[node].scope != suite.scope for node in nodes):
        raise ValueError("query node belongs to another source scope")
    return suite


def _relevant_gap_strings(graph, suite_id, max_work):
    minimum_work = len(graph.suites) + len(graph.gaps)
    if minimum_work > max_work:
        return (), minimum_work, "query work budget exceeded while indexing gaps"
    suite = graph.suites[suite_id]
    descendants = {suite_id}
    pending = [suite_id]
    children = defaultdict(list)
    for record in graph.suites.values():
        if record.parent is not None:
            children[record.parent].append(record.id)
    work = len(graph.suites)
    while pending:
        current = pending.pop()
        work += 1
        if work > max_work:
            return (), work, "query work budget exceeded while walking suite hierarchy"
        for child in children.get(current, ()):
            work += 1
            if work > max_work:
                return (), work, "query work budget exceeded while walking suite hierarchy"
            if child not in descendants:
                descendants.add(child)
                pending.append(child)
    reasons = set()
    for gap in graph.gaps:
        work += 1
        if work > max_work:
            return (), work, "query work budget exceeded while scanning gaps"
        if gap.suite in descendants:
            reasons.add(gap.reason)
    return tuple(sorted(reasons)), work, ""


def _query_preflight(graph, budget):
    # Graph records are mutable, so each query validates their structure first.
    # Bound that validation pass using an upper estimate from registry sizes.
    work = _graph_validation_work(graph)
    if work > budget.max_query_work:
        return work, "query work budget exceeded during graph validation"
    graph.assert_valid()
    return work, ""


def _graph_validation_work(graph):
    if type(graph) is not SourceControlFlowGraph:
        raise TypeError("expected SourceControlFlowGraph")
    # One recursive typed-record pass, registry checks and the graph's direct
    # reference checks are charged. Suite hierarchy validation builds one
    # cycle check and one iterative parent index, so its cost stays O(S+E)
    # even for deeply nested scopes; it never walks every ancestor per edge.
    work = (3 * len(graph.nodes) + 4 * len(graph.edges) + 10 * len(graph.suites)
            + 4 * len(graph.insertions) + 3 * len(graph.gaps) + 3 * len(graph.sources))
    operation_refs = 0
    for node in graph.nodes.values():
        operation_refs += 2 * len(node.operations)
    return work + operation_refs


def query_reachability(graph: SourceControlFlowGraph, suite: ControlFlowSuiteID,
                       source: ControlFlowNodeID, target: ControlFlowNodeID, *,
                       mode: QueryMode = QueryMode.NORMAL,
                       budget: ControlFlowBudget = ControlFlowBudget()) -> ReachabilityReport:
    """Return a bounded path candidate; never an optimization approval."""
    if type(mode) is not QueryMode:
        mode = QueryMode(mode)
    if type(budget) is not ControlFlowBudget:
        raise TypeError("budget must be ControlFlowBudget")
    budget.__post_init__()
    validation_work, error = _query_preflight(graph, budget)
    request = ReachabilityRequest(suite, source, target, mode)
    if error:
        return ReachabilityReport(request, QueryStatus.UNKNOWN, validation_work, error)
    suite_record = _query_inputs(graph, suite, source, target)
    gaps, gap_work, error = _relevant_gap_strings(
        graph, suite, budget.max_query_work - validation_work)
    total_work = validation_work + gap_work
    if error:
        return ReachabilityReport(request, QueryStatus.UNKNOWN, total_work, error)
    if source == target:
        return ReachabilityReport(request, QueryStatus.REACHABLE, total_work,
                                  "same node is a structural path candidate",
                                  gaps)
    outgoing, index_work, error = _node_maps(graph, budget.max_query_work - total_work)
    total_work += index_work
    if error:
        return ReachabilityReport(request, QueryStatus.UNKNOWN, total_work, error, gaps)
    result, path_work, error = _path(outgoing, source, target, mode,
                                     budget.max_query_work - total_work)
    total_work += path_work
    if error:
        return ReachabilityReport(request, QueryStatus.UNKNOWN, total_work, error, gaps)
    if result:
        nodes, edges = result
        uncertain = any(_uncertain_edge(edge.kind) for edge in edges)
        return ReachabilityReport(request, QueryStatus.REACHABLE, total_work,
            "path exists in the reconstructed CFG" + ("; feasibility is unresolved" if uncertain else ""),
            gaps, nodes)
    if not suite_record.complete or gaps:
        status, reason = QueryStatus.UNKNOWN, "no path in the represented edges; source has unresolved control gaps"
    else:
        status, reason = QueryStatus.NOT_REACHABLE, "no path exists in the reconstructed CFG"
    return ReachabilityReport(request, status, total_work, reason, gaps)


def query_dominance(graph: SourceControlFlowGraph, suite: ControlFlowSuiteID,
                    dominator: ControlFlowNodeID, node: ControlFlowNodeID, *,
                    mode: QueryMode = QueryMode.NORMAL,
                    budget: ControlFlowBudget = ControlFlowBudget()) -> DominanceReport:
    """Check one pair by a bounded bypass search (O(V+E) per request).

    The result is named CANDIDATE rather than PROVEN because this graph is a
    bounded AST skeleton and has no MOVE authority. Use explicit NORMAL or
    ALL_PATHS mode; NORMAL excludes typed exception edges.
    """
    if type(mode) is not QueryMode:
        mode = QueryMode(mode)
    if type(budget) is not ControlFlowBudget:
        raise TypeError("budget must be ControlFlowBudget")
    budget.__post_init__()
    suite_record = _query_inputs(graph, suite, dominator, node)
    request = DominanceRequest(suite, suite_record.entry, dominator, node, mode)
    work, error = _query_preflight(graph, budget)
    if error:
        return DominanceReport(request, QueryStatus.UNKNOWN, work, error)
    gaps, gap_work, error = _relevant_gap_strings(
        graph, suite, budget.max_query_work - work)
    work += gap_work
    if error:
        return DominanceReport(request, QueryStatus.UNKNOWN, work, error, gaps)
    outgoing, index_work, error = _node_maps(graph, budget.max_query_work - work)
    work += index_work
    if error:
        return DominanceReport(request, QueryStatus.UNKNOWN, work, error, gaps)
    entry_path, path_work, error = _path(outgoing, suite_record.entry, node, mode,
                                         budget.max_query_work - work)
    work += path_work
    if error:
        return DominanceReport(request, QueryStatus.UNKNOWN, work, error, gaps)
    if not entry_path:
        status = QueryStatus.UNKNOWN if not suite_record.complete or gaps else QueryStatus.UNREACHABLE
        return DominanceReport(request, status, work,
            "queried node is unreachable from suite entry" if status is QueryStatus.UNREACHABLE
            else "reachability is incomplete because of source control gaps", gaps)
    if dominator == suite_record.entry:
        return DominanceReport(request, QueryStatus.CANDIDATE, work,
            "suite entry precedes every represented path; this is not a MOVE proof", gaps)
    bypass, bypass_work, error = _path(outgoing, suite_record.entry, node, mode,
        budget.max_query_work - work, forbidden=dominator)
    total_work = work + bypass_work
    if error:
        return DominanceReport(request, QueryStatus.UNKNOWN, total_work, error, gaps)
    if bypass:
        path_nodes, path_edges = bypass
        uncertain = (not suite_record.complete or bool(gaps)
                     or any(_uncertain_edge(edge.kind) for edge in path_edges))
        return DominanceReport(request,
            QueryStatus.UNKNOWN if uncertain else QueryStatus.NOT_DOMINATED,
            total_work,
            "a bypass path is possible but depends on unresolved control"
            if uncertain else "a represented path reaches the node without the candidate dominator",
            gaps, path_nodes)
    if not suite_record.complete:
        return DominanceReport(request, QueryStatus.UNKNOWN, total_work,
                               "suite contains unsupported control-flow gaps", gaps)
    return DominanceReport(request, QueryStatus.CANDIDATE, total_work,
        "dominates in this reconstructed CFG only; this is not a MOVE proof", gaps)


def query_must_execute(graph: SourceControlFlowGraph, suite: ControlFlowSuiteID,
                       node: ControlFlowNodeID, *, mode: QueryMode = QueryMode.ALL_PATHS,
                       budget: ControlFlowBudget = ControlFlowBudget()) -> MustExecuteReport:
    """Check whether a node lies on every represented route to selected exits."""
    if type(mode) is not QueryMode:
        mode = QueryMode(mode)
    if type(budget) is not ControlFlowBudget:
        raise TypeError("budget must be ControlFlowBudget")
    budget.__post_init__()
    suite_record = _query_inputs(graph, suite, node)
    request = MustExecuteRequest(suite, node, mode)
    work, error = _query_preflight(graph, budget)
    if error:
        return MustExecuteReport(request, QueryStatus.UNKNOWN, work, error)
    exits = [suite_record.normal_exit]
    if mode is QueryMode.ALL_PATHS:
        exits.append(suite_record.exception_exit)
    gaps, gap_work, error = _relevant_gap_strings(
        graph, suite, budget.max_query_work - work)
    work += gap_work
    if error:
        return MustExecuteReport(request, QueryStatus.UNKNOWN, work, error)
    outgoing, index_work, error = _node_maps(graph, budget.max_query_work - work)
    work += index_work
    if error:
        return MustExecuteReport(request, QueryStatus.UNKNOWN, work, error, gaps)
    if node == suite_record.entry:
        return MustExecuteReport(request, QueryStatus.CANDIDATE, work,
            "suite entry precedes every represented path; this is not a MOVE proof", gaps)
    reachable_exits = []
    for exit_node in exits:
        result, used, error = _path(outgoing, suite_record.entry, exit_node, mode,
                                    budget.max_query_work - work)
        work += used
        if error or work > budget.max_query_work:
            return MustExecuteReport(request, QueryStatus.UNKNOWN, work,
                                     error or "query work budget exceeded", gaps)
        if result:
            reachable_exits.append(exit_node)
    if not reachable_exits:
        status = QueryStatus.UNKNOWN if not suite_record.complete or gaps else QueryStatus.UNREACHABLE
        return MustExecuteReport(request, status, work,
            "no selected exit is reachable from suite entry" if status is QueryStatus.UNREACHABLE
            else "selected exit reachability is incomplete because of source gaps", gaps)
    maybe_bypass = None
    for exit_node in reachable_exits:
        result, used, error = _path(outgoing, suite_record.entry, exit_node, mode,
                                    budget.max_query_work - work, forbidden=node)
        work += used
        if error or work > budget.max_query_work:
            return MustExecuteReport(request, QueryStatus.UNKNOWN, work,
                                     error or "query work budget exceeded", gaps)
        if result:
            path_nodes, path_edges = result
            if any(_uncertain_edge(edge.kind) for edge in path_edges):
                maybe_bypass = exit_node
                continue
            return MustExecuteReport(request, QueryStatus.NOT_MUST_EXECUTE, work,
                "a represented exit path bypasses the queried node", gaps, exit_node)
    if maybe_bypass is not None or not suite_record.complete:
        return MustExecuteReport(request, QueryStatus.UNKNOWN, work,
            "an unresolved branch/loop/exception path may bypass the queried node", gaps,
            maybe_bypass)
    return MustExecuteReport(request, QueryStatus.CANDIDATE, work,
        "node lies on every represented path to the selected exits; this is not a MOVE proof",
        gaps)


def validate_dominance_query(graph, report, *, budget=ControlFlowBudget()):
    """Recompute a serialized/received dominance report; statuses are not trusted."""
    try:
        errors = record_errors(report, DominanceReport, "dominance_report")
        if errors:
            return {"valid": False, "errors": errors}
        expected = query_dominance(graph, report.request.suite,
            report.request.dominator, report.request.node,
            mode=report.request.mode, budget=budget)
        if report != expected:
            return {"valid": False, "errors": ["dominance report differs from query recomputation"]}
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return {"valid": False, "errors": [str(exc)]}
    return {"valid": True, "errors": []}


def validate_reachability_query(graph, report, *, budget=ControlFlowBudget()):
    try:
        errors = record_errors(report, ReachabilityReport, "reachability_report")
        if errors:
            return {"valid": False, "errors": errors}
        expected = query_reachability(graph, report.request.suite,
            report.request.source, report.request.target,
            mode=report.request.mode, budget=budget)
        if report != expected:
            return {"valid": False, "errors": ["reachability report differs from query recomputation"]}
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return {"valid": False, "errors": [str(exc)]}
    return {"valid": True, "errors": []}


def validate_must_execute_query(graph, report, *, budget=ControlFlowBudget()):
    try:
        errors = record_errors(report, MustExecuteReport, "must_execute_report")
        if errors:
            return {"valid": False, "errors": errors}
        expected = query_must_execute(graph, report.request.suite,
            report.request.node, mode=report.request.mode, budget=budget)
        if report != expected:
            return {"valid": False, "errors": ["must-execute report differs from query recomputation"]}
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return {"valid": False, "errors": [str(exc)]}
    return {"valid": True, "errors": []}


__all__ = [
    "build_source_control_flow", "validate_source_control_flow", "query_reachability",
    "query_dominance", "query_must_execute", "validate_dominance_query",
    "validate_reachability_query", "validate_must_execute_query",
]
