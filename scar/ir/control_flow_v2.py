"""Typed, source-versioned structured control-flow records.

This overlay describes a bounded AST control skeleton.  It is construction
evidence only: it does not certify Python effects, path feasibility, or MOVE
legality.  Graphs must be replayed against their semantic/source inputs before
their structural facts are reused.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from typing import Any

from .record_codec import decode, encode, loads
from .v2._validation import cycle_errors, mapping_errors, record_errors
from .v2.common import SourceReference
from .v2.ids import Identifier, OperationDefinitionID, ControlRegionID


class ControlFlowSuiteID(Identifier):
    prefix = "source_suite"


class ControlFlowNodeID(Identifier):
    prefix = "source_cfg_node"


class ControlFlowEdgeID(Identifier):
    prefix = "source_cfg_edge"


class InsertionPointID(Identifier):
    prefix = "source_insertion"


class SuiteKind(str, Enum):
    MODULE = "module"
    FUNCTION = "function"
    IF_TRUE = "if_true"
    IF_FALSE = "if_false"
    WHILE_BODY = "while_body"
    WHILE_ELSE = "while_else"
    FOR_BODY = "for_body"
    FOR_ELSE = "for_else"
    OPAQUE = "opaque"


class NodeKind(str, Enum):
    SCOPE_ENTRY = "scope_entry"
    SUITE_ENTRY = "suite_entry"
    STATEMENT = "statement"
    BRANCH_TEST = "branch_test"
    LOOP_TEST = "loop_test"
    INSERTION = "insertion"
    NORMAL_EXIT = "normal_exit"
    EXCEPTION_EXIT = "exception_exit"
    GAP = "gap"


class EdgeKind(str, Enum):
    SEQUENCE = "sequence"
    ENTER_SUITE = "enter_suite"
    IF_TRUE = "if_true"
    IF_FALSE = "if_false"
    LOOP_BODY = "loop_body"
    LOOP_BACKEDGE = "loop_backedge"
    LOOP_ZERO_EXIT = "loop_zero_exit"
    LOOP_ELSE = "loop_else"
    BREAK = "break"
    CONTINUE = "continue"
    RETURN = "return"
    RAISE = "raise"
    MAY_RAISE = "may_raise"
    EXCEPTION_PROPAGATION = "exception_propagation"
    UNKNOWN_CONTINUATION = "unknown_continuation"


class GapKind(str, Enum):
    MISSING_SOURCE_OPERATION = "missing_source_operation"
    AMBIGUOUS_SOURCE_OPERATION = "ambiguous_source_operation"
    TRY_SEMANTICS = "try_semantics"
    WITH_SEMANTICS = "with_semantics"
    ASYNC_SEMANTICS = "async_semantics"
    YIELD_SEMANTICS = "yield_semantics"
    USER_ITERATION = "user_iteration"
    UNSUPPORTED_CONTROL = "unsupported_control"
    DEFERRED_SCOPE = "deferred_scope"
    CLASS_NAMESPACE = "class_namespace"
    BRANCH_FEASIBILITY = "branch_feasibility"
    LOOP_FEASIBILITY = "loop_feasibility"
    BUDGET = "budget"


class InsertionKind(str, Enum):
    ENTRY = "entry"
    BEFORE = "before"
    AFTER = "after"


class QueryMode(str, Enum):
    NORMAL = "normal"
    ALL_PATHS = "all_paths"


class QueryStatus(str, Enum):
    CANDIDATE = "candidate"
    REACHABLE = "reachable"
    NOT_REACHABLE = "not_reachable"
    NOT_DOMINATED = "not_dominated"
    NOT_MUST_EXECUTE = "not_must_execute"
    UNREACHABLE = "unreachable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SourceVersion:
    path: str
    fingerprint: str

    def __post_init__(self) -> None:
        if not self.path or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.fingerprint):
            raise ValueError("source version requires a path and canonical SHA256 fingerprint")


@dataclass(frozen=True, slots=True)
class ControlFlowBudget:
    max_source_bytes: int = 4_000_000
    max_ast_nodes: int = 200_000
    max_nodes: int = 300_000
    max_edges: int = 600_000
    max_build_work: int = 2_000_000
    max_query_work: int = 1_000_000
    max_nesting: int = 256

    def __post_init__(self) -> None:
        for name in ("max_source_bytes", "max_ast_nodes", "max_nodes", "max_edges",
                     "max_build_work", "max_query_work", "max_nesting"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class ControlFlowSuite:
    id: ControlFlowSuiteID
    scope: OperationDefinitionID
    kind: SuiteKind
    parent: ControlFlowSuiteID | None
    owner: OperationDefinitionID | None
    source: SourceReference | None
    entry: ControlFlowNodeID
    normal_exit: ControlFlowNodeID
    exception_exit: ControlFlowNodeID
    version: SourceVersion
    complete: bool = True


@dataclass(frozen=True, slots=True)
class ControlFlowNode:
    id: ControlFlowNodeID
    kind: NodeKind
    scope: OperationDefinitionID
    suite: ControlFlowSuiteID
    operations: tuple[OperationDefinitionID, ...] = ()
    source: SourceReference | None = None
    ordinal: int = 0
    label: str = ""

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("control-flow node ordinal must be non-negative")


@dataclass(frozen=True, slots=True)
class ControlFlowEdge:
    id: ControlFlowEdgeID
    source: ControlFlowNodeID
    target: ControlFlowNodeID
    kind: EdgeKind
    operation: OperationDefinitionID | None = None


@dataclass(frozen=True, slots=True)
class ControlFlowGap:
    kind: GapKind
    scope: OperationDefinitionID
    suite: ControlFlowSuiteID
    source: SourceReference | None
    operation: OperationDefinitionID | None
    reason: str

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("control-flow gap requires a reason")


@dataclass(frozen=True, slots=True)
class InsertionPoint:
    id: InsertionPointID
    suite: ControlFlowSuiteID
    kind: InsertionKind
    node: ControlFlowNodeID
    anchor: ControlFlowNodeID | None
    source: SourceReference | None
    version: SourceVersion

    def __post_init__(self) -> None:
        if self.kind is InsertionKind.ENTRY and (self.anchor is not None or self.source is not None):
            raise ValueError("suite-entry insertion cannot name a statement anchor")
        if self.kind is not InsertionKind.ENTRY and (self.anchor is None or self.source is None):
            raise ValueError("before/after insertion requires a source statement anchor")


@dataclass(frozen=True, slots=True)
class DominanceRequest:
    suite: ControlFlowSuiteID
    entry: ControlFlowNodeID
    dominator: ControlFlowNodeID
    node: ControlFlowNodeID
    mode: QueryMode


@dataclass(frozen=True, slots=True)
class DominanceReport:
    request: DominanceRequest
    status: QueryStatus
    work: int
    reason: str = ""
    gaps: tuple[str, ...] = ()
    bypass: tuple[ControlFlowNodeID, ...] = ()


@dataclass(frozen=True, slots=True)
class ReachabilityRequest:
    suite: ControlFlowSuiteID
    source: ControlFlowNodeID
    target: ControlFlowNodeID
    mode: QueryMode


@dataclass(frozen=True, slots=True)
class ReachabilityReport:
    request: ReachabilityRequest
    status: QueryStatus
    work: int
    reason: str = ""
    gaps: tuple[str, ...] = ()
    path: tuple[ControlFlowNodeID, ...] = ()


@dataclass(frozen=True, slots=True)
class MustExecuteRequest:
    suite: ControlFlowSuiteID
    node: ControlFlowNodeID
    mode: QueryMode


@dataclass(frozen=True, slots=True)
class MustExecuteReport:
    request: MustExecuteRequest
    status: QueryStatus
    work: int
    reason: str = ""
    gaps: tuple[str, ...] = ()
    bypass_exit: ControlFlowNodeID | None = None


@dataclass(slots=True)
class SourceControlFlowGraph:
    sources: dict[str, SourceVersion] = field(default_factory=dict)
    suites: dict[ControlFlowSuiteID, ControlFlowSuite] = field(default_factory=dict)
    nodes: dict[ControlFlowNodeID, ControlFlowNode] = field(default_factory=dict)
    edges: dict[ControlFlowEdgeID, ControlFlowEdge] = field(default_factory=dict)
    insertions: dict[InsertionPointID, InsertionPoint] = field(default_factory=dict)
    gaps: tuple[ControlFlowGap, ...] = ()
    semantic_digest: str = ""
    source_semantics_digest: str = ""

    SCHEMA = "scar.source-control-flow.v2"
    SCHEMA_VERSION = 1

    def validate(self, semantic=None, source_semantics=None) -> dict[str, Any]:
        errors = record_errors(self, SourceControlFlowGraph, "source_control_flow")
        if errors:
            return {"valid": False, "errors": sorted(set(errors))}
        errors.extend(mapping_errors(self.sources, str, SourceVersion, "sources", "path"))
        errors.extend(mapping_errors(self.suites, ControlFlowSuiteID, ControlFlowSuite,
                                     "suites", "id"))
        errors.extend(mapping_errors(self.nodes, ControlFlowNodeID, ControlFlowNode,
                                     "nodes", "id"))
        errors.extend(mapping_errors(self.edges, ControlFlowEdgeID, ControlFlowEdge,
                                     "edges", "id"))
        errors.extend(mapping_errors(self.insertions, InsertionPointID, InsertionPoint,
                                     "insertions", "id"))
        errors.extend(cycle_errors(((item.parent, item.id) for item in self.suites.values()
                                    if item.parent is not None), "source control-flow suite hierarchy"))
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.semantic_digest):
            errors.append("semantic digest is missing or malformed")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.source_semantics_digest):
            errors.append("source-semantics digest is missing or malformed")
        if len({(item.kind, item.scope, item.suite, item.source, item.operation, item.reason)
                for item in self.gaps}) != len(self.gaps):
            errors.append("duplicate control-flow gap")
        root_scopes = set()
        for suite in self.suites.values():
            if suite.parent is None:
                if suite.scope in root_scopes:
                    errors.append(f"scope {suite.scope.wire} has multiple control-flow roots")
                root_scopes.add(suite.scope)
            if semantic is not None and suite.scope not in semantic.definitions:
                errors.append(f"suite {suite.id.wire} references unknown scope")
            if suite.parent is not None and suite.parent not in self.suites:
                errors.append(f"suite {suite.id.wire} references missing parent suite")
            if suite.parent == suite.id:
                errors.append(f"suite {suite.id.wire} cannot parent itself")
            if suite.owner is not None and semantic is not None and suite.owner not in semantic.definitions:
                errors.append(f"suite {suite.id.wire} references unknown owner operation")
            if suite.version.path not in self.sources or self.sources.get(suite.version.path) != suite.version:
                errors.append(f"suite {suite.id.wire} references unknown source version")
            entry_kind = (NodeKind.SCOPE_ENTRY if suite.parent is None
                          or (suite.parent in self.suites
                              and self.suites[suite.parent].scope != suite.scope)
                          else NodeKind.SUITE_ENTRY)
            for role, node_id, kind in (("entry", suite.entry, entry_kind),
                                        ("normal exit", suite.normal_exit, NodeKind.NORMAL_EXIT),
                                        ("exception exit", suite.exception_exit, NodeKind.EXCEPTION_EXIT)):
                node = self.nodes.get(node_id)
                if node is None or node.suite != suite.id or node.scope != suite.scope or node.kind is not kind:
                    errors.append(f"suite {suite.id.wire} has invalid {role}")
            if suite.source is not None:
                version = self.sources.get(suite.source.path)
                if version is None or version.fingerprint != suite.source.fingerprint:
                    errors.append(f"suite {suite.id.wire} source version mismatch")
                if semantic is not None and suite.owner is not None:
                    owner = semantic.definitions.get(suite.owner)
                    if owner is not None and suite.source.atom_id not in owner.source_atoms:
                        errors.append(f"suite {suite.id.wire} owner does not own its source anchor")
        suite_children: dict[ControlFlowSuiteID, list[ControlFlowSuiteID]] = {}
        for suite in self.suites.values():
            if suite.parent in self.suites:
                suite_children.setdefault(suite.parent, []).append(suite.id)
        suite_tin: dict[ControlFlowSuiteID, int] = {}
        suite_tout: dict[ControlFlowSuiteID, int] = {}
        clock = 0
        roots = [suite.id for suite in self.suites.values()
                 if suite.parent is None or suite.parent not in self.suites]
        for root in roots + [suite.id for suite in self.suites.values()
                             if suite.id not in suite_tin]:
            if root in suite_tin:
                continue
            stack = [(root, False)]
            while stack:
                current, closing = stack.pop()
                if closing:
                    suite_tout[current] = clock
                    clock += 1
                    continue
                if current in suite_tin:
                    continue
                suite_tin[current] = clock
                clock += 1
                stack.append((current, True))
                for child in reversed(suite_children.get(current, ())):
                    if child not in suite_tin:
                        stack.append((child, False))

        def suite_is_ancestor(ancestor, descendant):
            return (ancestor in suite_tin and descendant in suite_tin
                    and suite_tin[ancestor] <= suite_tin[descendant]
                    and suite_tout[descendant] <= suite_tout[ancestor])
        for node in self.nodes.values():
            suite = self.suites.get(node.suite)
            if suite is None:
                errors.append(f"node {node.id.wire} references missing suite")
            elif node.scope != suite.scope:
                errors.append(f"node {node.id.wire} scope differs from suite")
            if semantic is not None and any(operation not in semantic.definitions
                                            for operation in node.operations):
                errors.append(f"node {node.id.wire} references unknown operation")
            if semantic is not None and node.source is not None:
                for operation in node.operations:
                    definition = semantic.definitions.get(operation)
                    if definition is not None and node.source.atom_id not in definition.source_atoms:
                        errors.append(f"node {node.id.wire} operation does not own its source anchor")
            if node.source is not None:
                version = self.sources.get(node.source.path)
                if version is None or version.fingerprint != node.source.fingerprint:
                    errors.append(f"node {node.id.wire} source version mismatch")
                if semantic is not None:
                    atom = semantic.source_atoms.get(node.source.atom_id)
                    if atom is None or atom.reference != node.source:
                        errors.append(f"node {node.id.wire} source differs from SemanticGraph")
        for edge in self.edges.values():
            source = self.nodes.get(edge.source)
            target = self.nodes.get(edge.target)
            if source is None or target is None:
                errors.append(f"edge {edge.id.wire} has a missing endpoint")
            else:
                if source.scope != target.scope:
                    errors.append(f"edge {edge.id.wire} crosses lexical scopes")
                source_suite = self.suites.get(source.suite)
                target_suite = self.suites.get(target.suite)
                if source_suite is not None and target_suite is not None:
                    same_suite = source.suite == target.suite
                    if same_suite and edge.kind in {
                        EdgeKind.IF_TRUE, EdgeKind.IF_FALSE, EdgeKind.LOOP_BODY,
                        EdgeKind.LOOP_ZERO_EXIT, EdgeKind.LOOP_BACKEDGE,
                        EdgeKind.LOOP_ELSE, EdgeKind.BREAK, EdgeKind.CONTINUE,
                        EdgeKind.EXCEPTION_PROPAGATION,
                    }:
                        errors.append(f"edge {edge.id.wire} has an invalid same-suite boundary kind")
                    if not same_suite:
                        if edge.kind in {EdgeKind.IF_TRUE, EdgeKind.IF_FALSE}:
                            expected_kind = (SuiteKind.IF_TRUE if edge.kind is EdgeKind.IF_TRUE
                                             else SuiteKind.IF_FALSE)
                            if (source.kind is not NodeKind.BRANCH_TEST
                                    or target != self.nodes.get(target_suite.entry)
                                    or target_suite.parent != source.suite
                                    or target_suite.kind is not expected_kind):
                                errors.append(f"edge {edge.id.wire} has an invalid branch-suite boundary")
                        elif edge.kind in {EdgeKind.LOOP_BODY, EdgeKind.LOOP_ZERO_EXIT}:
                            is_body = edge.kind is EdgeKind.LOOP_BODY
                            valid_suite_kind = (target_suite.kind in {SuiteKind.WHILE_BODY, SuiteKind.FOR_BODY}
                                if is_body else target_suite.kind in {SuiteKind.WHILE_ELSE, SuiteKind.FOR_ELSE})
                            if (source.kind is not NodeKind.LOOP_TEST
                                    or target != self.nodes.get(target_suite.entry)
                                    or target_suite.parent != source.suite or not valid_suite_kind):
                                errors.append(f"edge {edge.id.wire} has an invalid loop-suite boundary")
                        elif edge.kind is EdgeKind.SEQUENCE:
                            if not (source.kind is NodeKind.NORMAL_EXIT
                                    and target.kind is NodeKind.INSERTION
                                    and source_suite.parent == target.suite):
                                errors.append(f"edge {edge.id.wire} has an invalid cross-suite sequence")
                        elif edge.kind is EdgeKind.LOOP_BACKEDGE:
                            if not (source.kind is NodeKind.NORMAL_EXIT
                                    and source_suite.parent == target.suite
                                    and target.kind is NodeKind.LOOP_TEST
                                    and source_suite.kind in {SuiteKind.WHILE_BODY, SuiteKind.FOR_BODY}):
                                errors.append(f"edge {edge.id.wire} has an invalid loop backedge")
                        elif edge.kind is EdgeKind.LOOP_ELSE:
                            if not (source.kind is NodeKind.NORMAL_EXIT
                                    and source_suite.parent == target.suite
                                    and source_suite.kind in {SuiteKind.WHILE_ELSE, SuiteKind.FOR_ELSE}
                                    and target.kind is NodeKind.INSERTION):
                                errors.append(f"edge {edge.id.wire} has an invalid loop-else boundary")
                        elif edge.kind in {EdgeKind.BREAK, EdgeKind.CONTINUE}:
                            correct_target = (suite_is_ancestor(target.suite, source.suite)
                                and (target.kind is NodeKind.INSERTION if edge.kind is EdgeKind.BREAK
                                     else target.kind is NodeKind.LOOP_TEST))
                            if not correct_target:
                                errors.append(f"edge {edge.id.wire} has an invalid loop-control boundary")
                        elif edge.kind is EdgeKind.RETURN:
                            if not (target.kind is NodeKind.NORMAL_EXIT
                                    and suite_is_ancestor(target.suite, source.suite)
                                    and target_suite.kind in {SuiteKind.FUNCTION, SuiteKind.MODULE}):
                                errors.append(f"edge {edge.id.wire} has an invalid return boundary")
                        elif edge.kind is EdgeKind.EXCEPTION_PROPAGATION:
                            if not (source.kind is NodeKind.EXCEPTION_EXIT
                                    and target.kind is NodeKind.EXCEPTION_EXIT
                                    and source_suite.parent == target.suite):
                                errors.append(f"edge {edge.id.wire} has an invalid exception boundary")
                        else:
                            errors.append(f"edge {edge.id.wire} has an unsupported cross-suite kind")
                    if edge.kind in {EdgeKind.MAY_RAISE, EdgeKind.RAISE,
                                     EdgeKind.UNKNOWN_CONTINUATION} and same_suite:
                        if edge.kind in {EdgeKind.MAY_RAISE, EdgeKind.RAISE}:
                            if target.kind is not NodeKind.EXCEPTION_EXIT:
                                errors.append(f"edge {edge.id.wire} does not target an exception exit")
                        elif target.kind not in {NodeKind.NORMAL_EXIT, NodeKind.INSERTION,
                                                 NodeKind.EXCEPTION_EXIT}:
                            errors.append(f"edge {edge.id.wire} has an invalid unknown continuation target")
            if edge.operation is not None and semantic is not None and edge.operation not in semantic.definitions:
                errors.append(f"edge {edge.id.wire} references unknown operation")
        entry_point_counts: dict[ControlFlowSuiteID, int] = {}
        anchored_points: dict[tuple[ControlFlowSuiteID, ControlFlowNodeID, InsertionKind], int] = {}
        insertion_nodes = set()
        for insertion in self.insertions.values():
            suite = self.suites.get(insertion.suite)
            node = self.nodes.get(insertion.node)
            if suite is None or node is None or node.suite != insertion.suite:
                errors.append(f"insertion {insertion.id.wire} has a missing or foreign suite/node")
            if insertion.node in insertion_nodes:
                errors.append(f"insertion node {insertion.node.wire} is reused")
            insertion_nodes.add(insertion.node)
            if suite is not None and insertion.version != suite.version:
                errors.append(f"insertion {insertion.id.wire} source version differs from suite")
            if insertion.kind is InsertionKind.ENTRY:
                entry_point_counts[insertion.suite] = entry_point_counts.get(insertion.suite, 0) + 1
                if (suite is not None and insertion.node != suite.entry) or insertion.anchor is not None:
                    errors.append(f"insertion {insertion.id.wire} is not anchored at suite entry")
            else:
                if insertion.anchor is not None:
                    key = (insertion.suite, insertion.anchor, insertion.kind)
                    anchored_points[key] = anchored_points.get(key, 0) + 1
                if node is not None and node.kind is not NodeKind.INSERTION:
                    errors.append(f"insertion {insertion.id.wire} target is not an insertion node")
            if insertion.anchor is not None:
                anchor = self.nodes.get(insertion.anchor)
                if (anchor is None or anchor.suite != insertion.suite
                        or anchor.kind not in {NodeKind.STATEMENT, NodeKind.BRANCH_TEST,
                                               NodeKind.LOOP_TEST, NodeKind.GAP}):
                    errors.append(f"insertion {insertion.id.wire} references a non-statement anchor")
                elif insertion.source != anchor.source:
                    errors.append(f"insertion {insertion.id.wire} source differs from anchor")
                if insertion.source is not None:
                    version = self.sources.get(insertion.source.path)
                    if version is None or version.fingerprint != insertion.source.fingerprint:
                        errors.append(f"insertion {insertion.id.wire} source fingerprint mismatch")
        for suite in self.suites:
            if entry_point_counts.get(suite, 0) != 1:
                errors.append(f"suite {suite.wire} must have exactly one entry insertion point")
        for node in self.nodes.values():
            if node.kind not in {NodeKind.STATEMENT, NodeKind.BRANCH_TEST,
                                 NodeKind.LOOP_TEST, NodeKind.GAP}:
                continue
            if node.source is None:
                continue
            for kind in (InsertionKind.BEFORE, InsertionKind.AFTER):
                if anchored_points.get((node.suite, node.id, kind), 0) != 1:
                    errors.append(f"statement node {node.id.wire} must have one {kind.value} insertion point")
        for (suite_id, anchor_id, kind), count in anchored_points.items():
            if count != 1:
                errors.append(f"statement anchor {anchor_id.wire} has duplicate {kind.value} insertion points")
        for gap in self.gaps:
            suite = self.suites.get(gap.suite)
            if suite is None or suite.scope != gap.scope:
                errors.append("control-flow gap has unknown suite or mismatched scope")
            if gap.operation is not None and semantic is not None and gap.operation not in semantic.definitions:
                errors.append("control-flow gap references unknown operation")
            if gap.source is not None:
                version = self.sources.get(gap.source.path)
                if version is None or version.fingerprint != gap.source.fingerprint:
                    errors.append("control-flow gap source fingerprint mismatch")
        if semantic is not None:
            if self.semantic_digest != _digest(semantic.to_dict()):
                errors.append("semantic graph digest differs")
        if source_semantics is not None:
            if self.source_semantics_digest != _digest(source_semantics.to_dict()):
                errors.append("source-semantics graph digest differs")
        return {"valid": not errors, "errors": sorted(set(errors)),
                "counts": {"sources": len(self.sources), "suites": len(self.suites),
                           "nodes": len(self.nodes), "edges": len(self.edges),
                           "insertions": len(self.insertions), "gaps": len(self.gaps)}}

    def assert_valid(self, semantic=None, source_semantics=None) -> dict[str, Any]:
        report = self.validate(semantic, source_semantics)
        if not report["valid"]:
            raise ValueError("invalid source control-flow graph: " + "; ".join(report["errors"]))
        return report

    def summary(self) -> dict[str, Any]:
        edge_counts: dict[str, int] = {}
        for edge in self.edges.values():
            edge_counts[edge.kind.value] = edge_counts.get(edge.kind.value, 0) + 1
        scope_count = len({suite.scope for suite in self.suites.values()})
        unsupported: dict[str, int] = {}
        for gap in self.gaps:
            unsupported[gap.kind.value] = unsupported.get(gap.kind.value, 0) + 1
        reasons: dict[str, int] = {}
        for gap in self.gaps:
            reasons[gap.reason] = reasons.get(gap.reason, 0) + 1
        return {"schema": self.SCHEMA, "schema_version": self.SCHEMA_VERSION,
                "status": "CONSTRUCTION_ONLY",
                "sources": len(self.sources), "suites": len(self.suites),
                "nodes": len(self.nodes), "edges": len(self.edges),
                "insertions": len(self.insertions), "scopes": scope_count,
                "gaps": len(self.gaps), "edge_kinds": dict(sorted(edge_counts.items())),
                "gap_kinds": dict(sorted(unsupported.items())),
                "unsupported_reasons": dict(sorted(reasons.items()))}

    def to_dict(self) -> dict[str, Any]:
        self.assert_valid()
        return {"schema": self.SCHEMA, "schema_version": self.SCHEMA_VERSION,
                "graph": {
                    "sources": encode(self.sources),
                    "suites": [encode(item) for _, item in sorted(
                        self.suites.items(), key=lambda pair: pair[0].wire)],
                    "nodes": [encode(item) for _, item in sorted(
                        self.nodes.items(), key=lambda pair: pair[0].wire)],
                    "edges": [encode(item) for _, item in sorted(
                        self.edges.items(), key=lambda pair: pair[0].wire)],
                    "insertions": [encode(item) for _, item in sorted(
                        self.insertions.items(), key=lambda pair: pair[0].wire)],
                    "gaps": encode(self.gaps),
                    "semantic_digest": self.semantic_digest,
                    "source_semantics_digest": self.source_semantics_digest,
                }}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)

    @classmethod
    def from_dict(cls, document: Any) -> "SourceControlFlowGraph":
        if (type(document) is not dict or set(document) != {"schema", "schema_version", "graph"}
                or document["schema"] != cls.SCHEMA
                or type(document["schema_version"]) is not int
                or document["schema_version"] != cls.SCHEMA_VERSION):
            raise ValueError("unsupported source control-flow schema or fields")
        payload = document["graph"]
        expected = {"sources", "suites", "nodes", "edges", "insertions", "gaps",
                    "semantic_digest", "source_semantics_digest"}
        if type(payload) is not dict or set(payload) != expected:
            raise ValueError("source control-flow graph fields mismatch")
        if type(payload["sources"]) is not dict:
            raise ValueError("source control-flow sources must be an object")
        if any(type(path) is not str for path in payload["sources"]):
            raise ValueError("source control-flow source paths must be strings")
        sources = decode(dict[str, SourceVersion], payload["sources"])

        def registry(name, record_type):
            rows = payload[name]
            if type(rows) is not list:
                raise ValueError(f"source control-flow {name} must be an array")
            result = {}
            for row in rows:
                item = decode(record_type, row)
                key = item.id
                if key in result:
                    raise ValueError(f"duplicate source control-flow {name} ID")
                result[key] = item
            return result

        result = cls(
            sources=sources,
            suites=registry("suites", ControlFlowSuite),
            nodes=registry("nodes", ControlFlowNode),
            edges=registry("edges", ControlFlowEdge),
            insertions=registry("insertions", InsertionPoint),
            gaps=decode(tuple[ControlFlowGap, ...], payload["gaps"]),
            semantic_digest=decode(str, payload["semantic_digest"]),
            source_semantics_digest=decode(str, payload["source_semantics_digest"]))
        result.assert_valid()
        return result

    @classmethod
    def from_json(cls, payload: str) -> "SourceControlFlowGraph":
        return cls.from_dict(loads(payload))


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "ControlFlowSuiteID", "ControlFlowNodeID", "ControlFlowEdgeID", "InsertionPointID",
    "SuiteKind", "NodeKind", "EdgeKind", "GapKind", "InsertionKind", "QueryMode",
    "QueryStatus", "SourceVersion", "ControlFlowBudget", "ControlFlowSuite",
    "ControlFlowNode", "ControlFlowEdge", "ControlFlowGap", "InsertionPoint",
    "DominanceRequest", "DominanceReport", "ReachabilityRequest", "ReachabilityReport",
    "MustExecuteRequest", "MustExecuteReport", "SourceControlFlowGraph",
]
