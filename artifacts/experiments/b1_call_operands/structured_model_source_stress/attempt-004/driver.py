#!/usr/bin/env python3
"""Stress the structured source lowerer against an existing inventory index.

The inventory is used only to select attempted definitions. Every selected
definition is checked against one freshly prepared source context before its
body is lowered. This driver does not import or execute target source.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time
import traceback


MAX_BODIES = 256
TOTAL_OPERATION_BUDGET = 50_000
PER_BODY_OPERATION_BUDGET = 10_000
EXPECTED_SCAR_REVISION = "dcd498699e0cd1331cf496158b29575c3fc2c536"
EXPECTED_SCAR_FINGERPRINT = "bf7ccd18b51b843c53b6b49f290c5f7368c397f394209991eb1f13a1f313bf05"


def _run_git(root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(root), *args],
                                       stderr=subprocess.STDOUT, text=True).strip()
    except Exception as error:
        return f"UNAVAILABLE: {type(error).__name__}: {error}"


def _scar_fingerprint(root: Path) -> tuple[str, dict[str, str]]:
    paths = [*root.joinpath("scar").rglob("*.py"),
             *root.joinpath("tests").rglob("*.py"),
             *root.joinpath("scripts").rglob("*.py"),
             *root.joinpath("gates").glob("*.json"), root / "pyproject.toml"]
    if (root / "sitecustomize.py").is_file():
        paths.append(root / "sitecustomize.py")
    digests = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in sorted(paths)}
    combined = hashlib.sha256(json.dumps(digests, sort_keys=True).encode()).hexdigest()
    return combined, digests


def _tracked_python_hash(root: Path) -> tuple[str | None, int, str | None]:
    try:
        raw = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z", "--", "*.py"])
        names = sorted(item for item in raw.split(b"\0") if item)
        digest = hashlib.sha256()
        for name in names:
            path = root / os.fsdecode(name)
            content_hash = hashlib.sha256(path.read_bytes()).digest()
            digest.update(len(name).to_bytes(8, "big"))
            digest.update(name)
            digest.update(content_hash)
        return digest.hexdigest(), len(names), None
    except Exception as error:
        return None, 0, f"{type(error).__name__}: {error}"


def _environment_snapshot(scar_root: Path, project_root: Path) -> dict:
    scar_fingerprint, _ = _scar_fingerprint(scar_root)
    target_python_hash, target_python_count, target_python_error = _tracked_python_hash(project_root)
    return {
        "utc": datetime.now(timezone.utc).isoformat(),
        "scar_revision": _run_git(scar_root, "rev-parse", "HEAD"),
        "scar_status": _run_git(scar_root, "status", "--porcelain", "--untracked-files=no"),
        "scar_source_fingerprint": scar_fingerprint,
        "project_revision": _run_git(project_root, "rev-parse", "HEAD"),
        "project_status": _run_git(project_root, "status", "--porcelain", "--untracked-files=no"),
        "project_tracked_python_sha256": target_python_hash,
        "project_tracked_python_count": target_python_count,
        "project_tracked_python_error": target_python_error,
        "python": sys.version,
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "max_rss_platform_units": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "max_rss_units": "KiB on Linux",
    }


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _load_inventory(path: Path) -> dict:
    opener = __import__("gzip").open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        document = json.load(stream)
    if type(document) is not dict or type(document.get("files")) is not list:
        raise ValueError("inventory candidate index has no files array")
    return document


def _candidate_rows(document: dict) -> tuple[list[dict], dict]:
    rows = []
    eligible = 0
    malformed = []
    for file_index, file_row in enumerate(document["files"]):
        if type(file_row) is not dict:
            malformed.append({"file_index": file_index, "reason": "file row is not an object"})
            continue
        bodies = file_row.get("bodies", [])
        definitions = file_row.get("definitions", [])
        if type(bodies) is not list or type(definitions) is not list:
            malformed.append({"file_index": file_index, "reason": "definitions/bodies is not an array"})
            continue
        body_by_definition = {}
        for body_index, body in enumerate(bodies):
            if type(body) is not dict or type(body.get("definition")) is not dict:
                continue
            wire = body["definition"].get("wire")
            if type(wire) is str:
                if wire in body_by_definition:
                    malformed.append({"file_index": file_index, "reason": "duplicate body definition key",
                                      "definition": wire})
                else:
                    body_by_definition[wire] = (body_index, body)
        for definition_index, definition in enumerate(definitions):
            if type(definition) is not dict:
                continue
            if definition.get("kind") not in ("FUNCTION", "ASYNC_FUNCTION"):
                continue
            identifier = definition.get("id")
            wire = identifier.get("wire") if type(identifier) is dict else None
            pair = body_by_definition.get(wire)
            if pair is None or pair[1].get("status") == "NOT_ATTEMPTED":
                continue
            eligible += 1
            if len(rows) < MAX_BODIES:
                body_index, body = pair
                rows.append({"file_index": file_index, "definition_index": definition_index,
                             "body_index": body_index, "file_row": file_row,
                             "definition_row": definition, "body_row": body})
    return rows, {"eligible_attempted_function_bodies": eligible,
                  "selected": len(rows), "limit": MAX_BODIES,
                  "truncated": max(0, eligible - len(rows)), "inventory_shape_issues": malformed}


def _span_key(node: ast.AST) -> tuple | None:
    if not all(hasattr(node, name) for name in
               ("lineno", "end_lineno", "col_offset", "end_col_offset")):
        return None
    return (type(node).__name__, node.lineno, node.end_lineno,
            node.col_offset, node.end_col_offset)


def _source_indexes(context):
    by_span = {}
    by_reference = {}
    for atom in context.semantic.source_atoms.values():
        ref = atom.reference
        key = (atom.kind, ref.start_line, ref.end_line, ref.start_column, ref.end_column)
        by_span.setdefault(key, []).append(ref)
        by_reference.setdefault(ref, []).append(atom)
    nodes = {}
    duplicate_spans = set()
    for node in ast.walk(context.tree):
        key = _span_key(node)
        if key is None:
            continue
        refs = by_span.get(key, ())
        if len(refs) == 1:
            nodes.setdefault(refs[0], []).append(node)
        elif len(refs) > 1:
            duplicate_spans.add(key)
    call_operations = [operation for operation in context.semantics.operations.values()
                       if operation.opcode.value == "call"]
    calls_by_scope = {}
    call_by_source = {}
    for operation in call_operations:
        calls_by_scope.setdefault(operation.scope, []).append(operation)
        call_by_source.setdefault(operation.source, operation)
    return by_span, by_reference, nodes, duplicate_spans, calls_by_scope, call_by_source


def _candidate_check(context, source_snapshot, definition, indexes):
    by_span, by_reference, nodes, duplicate_spans = indexes[:4]
    errors = []
    current = context.semantics.sources.get(str(context.path))
    if current != source_snapshot:
        errors.append("current prepared SourceSnapshot differs from inventory snapshot")
    ref = definition.source
    if ref.path != source_snapshot.path or ref.fingerprint != source_snapshot.fingerprint:
        errors.append("definition SourceReference path/fingerprint differs from inventory snapshot")
    atoms = by_reference.get(ref, ())
    if len(atoms) != 1 or atoms[0].reference != ref:
        errors.append("definition does not resolve to one current semantic source atom")
    semantic_definition = context.semantic.definitions.get(definition.id)
    if semantic_definition is None:
        errors.append("inventory definition ID is absent from current semantic model")
    else:
        if semantic_definition.code_id != ref.atom_id.wire:
            errors.append("current semantic definition code ID differs from source atom")
        if semantic_definition.metadata.get("phase") != "call_time":
            errors.append("current semantic definition is not a call-time function body")
        if semantic_definition.source_file != source_snapshot.path:
            errors.append("current semantic definition source file differs")
    candidates = [node for node in nodes.get(ref, ())
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if len(candidates) != 1:
        errors.append(f"exact SourceReference maps to {len(candidates)} current function definitions")
        node = None
    else:
        node = candidates[0]
        atom = atoms[0] if len(atoms) == 1 else None
        expected_kind = "FunctionDef" if definition.kind.value == "FUNCTION" else "AsyncFunctionDef"
        if atom is None or atom.kind != expected_kind:
            errors.append("current atom kind differs from candidate function kind")
        if type(node).__name__ != expected_kind:
            errors.append("AST function kind differs from candidate kind")
        if node.name != definition.name:
            errors.append("AST function name differs from candidate record")
        if _span_key(node) in duplicate_spans:
            errors.append("candidate SourceReference span is ambiguous in current source")
    return node, errors


def _ref_document(ref):
    if ref is None:
        return None
    return {"path": ref.path, "fingerprint": ref.fingerprint,
            "atom_id": ref.atom_id.wire, "start": [ref.start_line, ref.start_column],
            "end": [ref.end_line, ref.end_column]}


def _call_nodes_for_body(context, definition_id, node, indexes):
    by_span, _, nodes, _, calls_by_scope, all_call_operations = indexes
    records = {}
    for operation in calls_by_scope.get(definition_id, ()):
        records.setdefault(operation.source, {"operation": operation, "node": None})
    # The semantic call inventory supplies execution-scope identities. AST
    # walking independently catches nested-expression calls and exposes any
    # scope/body candidates that cannot be lowered as this function's body.
    lexical = set()

    def walk_body(current):
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in (*current.decorator_list, *current.args.defaults,
                          *(value for value in current.args.kw_defaults if value is not None)):
                walk_body(child)
            return
        if isinstance(current, ast.Lambda):
            for child in current.args.defaults:
                walk_body(child)
            return
        if isinstance(current, ast.ClassDef):
            for child in (*current.decorator_list, *current.bases,
                          *(keyword.value for keyword in current.keywords)):
                walk_body(child)
            for statement in current.body:
                walk_body(statement)
            return
        if isinstance(current, ast.Call):
            lexical.add(current)
        for child in ast.iter_child_nodes(current):
            walk_body(child)

    for statement in node.body:
        walk_body(statement)
    lexical_refs = {}
    for call in lexical:
        key = _span_key(call)
        refs = () if key is None else by_span.get(key, ())
        if len(refs) == 1:
            lexical_refs[refs[0]] = call
    for ref, record in records.items():
        choices = nodes.get(ref, ())
        ast_calls = [item for item in choices if isinstance(item, ast.Call)]
        record["node"] = ast_calls[0] if len(ast_calls) == 1 else lexical_refs.get(ref)
        record["scope_kind"] = "FUNCTION_SCOPE"
    for ref, call in lexical_refs.items():
        operation = all_call_operations.get(ref)
        records.setdefault(ref, {"operation": operation, "node": call,
                                 "scope_kind": ("FUNCTION_SCOPE" if operation is not None
                                                and operation.scope == definition_id
                                                else "NESTED_OR_UNRESOLVED_SCOPE")})
    rows = list(records.items())
    rows.sort(key=lambda pair: (pair[0].start_line, pair[0].start_column,
                                pair[0].end_line, pair[0].end_column or -1,
                                pair[0].atom_id.wire))
    return rows


def _expr_nodes(root):
    result = []
    stack = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.expr):
            result.append(node)
        if node is not root and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                                   ast.Lambda, ast.ClassDef)):
            continue
        stack.extend(reversed(tuple(ast.iter_child_nodes(node))))
    return result


def _value_origin(value):
    origin = getattr(value, "origin", None)
    if origin is None:
        return None
    operation = getattr(origin, "operation", None)
    block = getattr(origin, "block", None)
    return {"kind": type(origin).__name__,
            "operation": getattr(operation, "wire", None),
            "block": getattr(block, "wire", None),
            "index": getattr(origin, "index", None)}


def _graph_projection_index(graph, metadata):
    if graph is None or metadata is None:
        return None
    links_by_source = {}
    for link in metadata.operation_links:
        links_by_source.setdefault(link.source, []).append(link)
    uses_by_operation = {}
    for link in metadata.use_links:
        uses_by_operation.setdefault(link.operation, {}).setdefault(link.use, []).append(link)
    connected = {item.source for item in metadata.operation_links}
    connected.update(item.source for item in metadata.value_links)
    return {"graph": graph, "metadata": metadata,
            "operations": {operation.id: operation for operation in graph.operations},
            "values": {value.id: value for value in graph.values},
            "operation_links_by_source": links_by_source,
            "use_links_by_operation": uses_by_operation,
            "connected_sources": connected}


def _call_graph_projection(projection, ref, node, indexes):
    if projection is None or node is None:
        return {"operation_count": 0, "linked": False, "core_covered": False,
                "reason": "graph, metadata, or exact AST call is absent", "operation": None,
                "ordered_use_endpoints": [], "subtree_expression_count": 0,
                "subtree_unlinked_expression_count": None}
    operation_links = projection["operation_links_by_source"].get(ref, ())
    call_links = [link for link in operation_links if link.opcode is not None and link.opcode.value == "call"]
    if len(call_links) != 1:
        return {"operation_count": len(call_links), "linked": False, "core_covered": False,
                "reason": f"expected one source-linked CALL operation; found {len(call_links)}",
                "operation": None, "ordered_use_endpoints": [], "subtree_expression_count": 0,
                "subtree_unlinked_expression_count": None}
    link = call_links[0]
    operation = projection["operations"].get(link.operation)
    if operation is None:
        return {"operation_count": 1, "linked": False, "core_covered": False,
                "reason": "source-linked CALL operation is absent from graph", "operation": link.operation.wire,
                "ordered_use_endpoints": [], "subtree_expression_count": 0,
                "subtree_unlinked_expression_count": None}
    values = projection["values"]
    uses_by_id = projection["use_links_by_operation"].get(operation.id, {})
    endpoint_rows = []
    for position, use in enumerate(operation.uses):
        candidates = uses_by_id.get(use.id, ())
        use_link = candidates[0] if len(candidates) == 1 else None
        value = values.get(use.value)
        endpoint_rows.append({
            "position": position,
            "use": use.id.wire,
            "value": use.value.wire,
            "use_role": use.role.value,
            "source": _ref_document(use_link.source) if use_link else None,
            "source_role": use_link.role if use_link else None,
            "source_index": use_link.index if use_link else None,
            "semantic_value": use_link.semantic_value.wire if use_link and use_link.semantic_value else None,
            "value_record": type(value).__name__ if value is not None else None,
            "value_origin": _value_origin(value) if value is not None else None,
            "source_link_unique": use_link is not None,
        })
    children = [node.func, *node.args, *(keyword.value for keyword in node.keywords)]
    expected_refs = []
    child_errors = []
    for child_index, child in enumerate(children):
        child_ref = _context_source(child, indexes)
        if child_ref is None:
            child_errors.append(f"child {child_index} has no unique current SourceReference")
        else:
            expected_refs.append(child_ref)
    direct_rows = [row for row in endpoint_rows
                   if row["source"] is not None and row["source"].get("atom_id") != ref.atom_id.wire]
    actual_refs = [row["source"] for row in direct_rows]
    expected_wire = [_ref_document(child_ref) for child_ref in expected_refs]
    endpoints_match = (not child_errors and actual_refs == expected_wire
                       and all(row["source_link_unique"] for row in direct_rows)
                       and len(direct_rows) == len(children))
    if len(endpoint_rows) != len(operation.uses) or any(row["source"] is None for row in endpoint_rows):
        endpoints_match = False

    connected = projection["connected_sources"]
    unresolved = []
    expression_count = 0
    for child in children:
        for expression in _expr_nodes(child):
            expression_count += 1
            expression_ref = _context_source(expression, indexes)
            if expression_ref is None or expression_ref not in connected:
                unresolved.append(_ref_document(expression_ref) if expression_ref else {
                    "ast_kind": type(expression).__name__, "line": getattr(expression, "lineno", None),
                    "column": getattr(expression, "col_offset", None)})
    subtree_complete = not unresolved
    covered = endpoints_match and subtree_complete
    reasons = []
    if not endpoints_match:
        reasons.append("ordered direct AST operands do not each map to one ordered operation Use")
    if not subtree_complete:
        reasons.append("one or more operand-subtree expressions lack a core source link")
    return {"operation_count": 1, "linked": True, "core_covered": covered,
            "reason": "; ".join(reasons) if reasons else None,
            "operation": operation.id.wire, "operation_source": _ref_document(link.source),
            "opcode": link.opcode.value, "ordered_use_endpoints": endpoint_rows,
            "expected_direct_operand_sources": expected_wire,
            "direct_operand_endpoint_count": len(direct_rows),
            "direct_operand_endpoint_match": endpoints_match,
            "subtree_expression_count": expression_count,
            "subtree_linked_expression_count": expression_count - len(unresolved),
            "subtree_unlinked_expression_count": len(unresolved),
            "subtree_unlinked_expressions": unresolved[:64]}


def _context_source(node, indexes):
    key = _span_key(node)
    if key is None:
        return None
    matches = indexes[0].get(key, ())
    return matches[0] if len(matches) == 1 else None


def _body_result(context, source_ref, source_snapshot, definition, old_body,
                 indexes, budget, charged_before):
    from scar.ir.program.functions import BodyLoweringProfile
    from scar.ir.program.source import GapKind

    row = {
        "definition_id": definition.id.wire,
        "definition_name": definition.name,
        "definition_kind": definition.kind.value,
        "definition_source": _ref_document(definition.source),
        "old": {"status": old_body.status.value, "construction_operations": old_body.construction_operations,
                "graph_present": old_body.graph is not None,
                "metadata_gap_count": len(old_body.metadata.gaps) if old_body.metadata else None,
                "reason": old_body.reason},
        "new": None,
        "source_calls": [],
        "operation_budget": {"charged_before": charged_before, "limit": budget,
                              "charged": 0, "cost_known": True},
        "source_validation": "PENDING",
    }
    node, source_errors = _candidate_check(context, source_snapshot, definition, indexes)
    row["source_validation"] = "VALID" if not source_errors else "REJECTED"
    row["source_validation_errors"] = source_errors
    if node is None or source_errors:
        row["new"] = {"status": "SOURCE_CANDIDATE_REJECTED", "graph_present": False,
                       "operations_emitted": 0, "errors": source_errors}
        return row, 0
    if budget < 1:
        row["new"] = {"status": "AGGREGATE_BUDGET_BLOCKED", "graph_present": False,
                       "operations_emitted": 0, "errors": ["no aggregate operation budget remains"]}
        return row, 0
    try:
        lowered = context.lower(node.name, source=source_ref, max_operations=budget,
                                expand_candidates=False,
                                profile=BodyLoweringProfile.STRUCTURED_BODY)
        emitted = lowered.operations_emitted
        if type(emitted) is not int or emitted < 0 or emitted > budget:
            raise RuntimeError(f"lowerer returned invalid operation charge {emitted!r} for budget {budget}")
        gaps = lowered.metadata.gaps
        gap_counts = Counter(gap.kind.value for gap in gaps)
        budget_gap = any(gap.kind is GapKind.BUDGET for gap in gaps)
        if lowered.graph is None:
            status = "BUDGET_BLOCKED" if budget_gap else "UNSUPPORTED"
        elif budget_gap:
            status = "GRAPH_WITH_BUDGET_GAP"
        elif gaps:
            status = "GRAPH_WITH_GAPS"
        else:
            status = "GRAPH"
        structured = lowered.structured
        row["new"] = {
            "status": status,
            "graph_present": lowered.graph is not None,
            "operations_emitted": emitted,
            "operation_links": len(lowered.metadata.operation_links),
            "value_links": len(lowered.metadata.value_links),
            "use_links": len(lowered.metadata.use_links),
            "gaps": [{"kind": gap.kind.value, "detail": gap.detail,
                      "source": _ref_document(gap.source)} for gap in gaps],
            "gap_counts": dict(sorted(gap_counts.items())),
            "graph_shape_counts": ({
                "regions": len(lowered.graph.regions),
                "blocks": sum(len(region.blocks) for region in lowered.graph.regions),
                "operations": len(lowered.graph.operations),
                "values": len(lowered.graph.values),
                "uses": sum(len(operation.uses) for operation in lowered.graph.operations),
                "binding_definitions": len(lowered.graph.binding_definitions),
                "binding_reads": len(lowered.graph.binding_reads),
                "loop_interfaces": len(structured.loops) if structured else 0,
                "typed_protocols": len(structured.protocols) if structured else 0,
                "incomplete_effect_operations": sum(not op.effects_complete for op in lowered.graph.operations),
            } if lowered.graph is not None else None),
            "authority": {"runtime_target_verified": False, "effects_proved": False,
                          "transformation_authorized": False},
        }
        row["operation_budget"]["charged"] = emitted
        calls = _call_nodes_for_body(context, definition.id, node, indexes)
        old_projection_index = _graph_projection_index(old_body.graph, old_body.metadata)
        new_projection_index = _graph_projection_index(lowered.graph, lowered.metadata)
        for call_ref, record in calls:
            call_node = record["node"]
            old_projection = _call_graph_projection(old_projection_index, call_ref, call_node, indexes)
            new_projection = _call_graph_projection(new_projection_index, call_ref, call_node, indexes)
            semop = record["operation"]
            if record.get("scope_kind") != "FUNCTION_SCOPE" and new_projection.get("core_covered"):
                new_projection["core_covered"] = False
                new_projection["reason"] = "call belongs to a nested/deferred source scope, not the selected function body"
            row["source_calls"].append({
                "source": _ref_document(call_ref),
                "scope": semop.scope.wire if semop is not None else None,
                "scope_kind": record.get("scope_kind", "FUNCTION_SCOPE"),
                "current_source_semantic_call": semop is not None,
                "callee_source_shape": (ast.dump(call_node.func, include_attributes=False)
                                        if call_node is not None else None),
                "old": old_projection,
                "new": new_projection,
            })
        return row, emitted
    except Exception as error:
        # A thrown lower() call has no trustworthy emitted-operation count.
        # Charge its complete per-attempt ceiling and prevent later attempts
        # from reusing capacity that may already have been consumed.
        row["operation_budget"].update({"charged": budget, "cost_known": False})
        row["new"] = {"status": "ERROR_COST_UNKNOWN", "graph_present": False,
                       "operations_emitted": None,
                       "errors": [f"{type(error).__name__}: {error}"],
                       "traceback": "".join(traceback.format_exception_only(type(error), error)).strip()}
        return row, budget


def _inventory_rows(path: Path):
    from scar.ir.program.codec import loads as load_graph
    from scar.ir.program.inventory import BodyInventory, BodyStatus, DefinitionInventory
    from scar.ir.program.source import LoweringMetadata
    from scar.ir.record_codec import decode
    from scar.ir.semantics_v2 import SourceSnapshot
    from scar.ir.v2.ids import OperationDefinitionID
    document = _load_inventory(path)
    candidates, selection = _candidate_rows(document)
    decoded = []
    decode_errors = []
    for row in candidates:
        try:
            snapshot = decode(SourceSnapshot, row["file_row"]["snapshot"])
            definition = decode(DefinitionInventory, row["definition_row"])
            raw_body = row["body_row"]
            body_id = decode(OperationDefinitionID, raw_body["definition"])
            status = BodyStatus(raw_body["status"])
            reason = raw_body.get("reason")
            if type(reason) is not str:
                reason = "old inventory body reason is malformed"
            cost = raw_body.get("construction_operations", 0)
            if type(cost) is not int or cost < 0:
                cost = 0
            metadata = None
            graph = None
            old_decode_issues = []
            if raw_body.get("metadata") is not None:
                try:
                    metadata = decode(LoweringMetadata, raw_body["metadata"])
                except Exception as error:
                    old_decode_issues.append(f"old metadata decode: {type(error).__name__}: {error}")
            if raw_body.get("graph") is not None:
                try:
                    graph = load_graph(json.dumps(raw_body["graph"], ensure_ascii=False,
                                                   sort_keys=True, separators=(",", ":")))
                except Exception as error:
                    old_decode_issues.append(f"old graph decode: {type(error).__name__}: {error}")
            body = BodyInventory(body_id, status, graph, metadata, reason, cost)
            if definition.id != body.definition:
                raise ValueError("body and definition IDs differ")
            decoded.append({**row, "snapshot": snapshot, "definition": definition, "body": body,
                            "decode_error": None,
                            "old_decode_issues": old_decode_issues})
        except Exception as error:
            issue = {"file_index": row["file_index"],
                     "definition_index": row["definition_index"],
                     "definition": row["definition_row"].get("name"),
                     "reason": f"{type(error).__name__}: {error}"}
            decode_errors.append(issue)
            decoded.append({**row, "snapshot": None, "definition": None, "body": None,
                            "decode_error": issue["reason"], "old_decode_issues": []})
    selection["selected_records_decoded"] = len(decoded) - len(decode_errors)
    selection["selected_record_decode_errors"] = decode_errors
    return document, decoded, selection


def _safe_source_path(snapshot, project_root: Path) -> tuple[Path | None, str | None]:
    raw = Path(snapshot.path)
    if not raw.is_absolute():
        return None, "inventory source path is not absolute"
    try:
        root = project_root.resolve(strict=True)
        resolved = raw.resolve(strict=True)
    except Exception as error:
        return None, f"source path/root is unavailable: {type(error).__name__}: {error}"
    if resolved != raw:
        return None, "source path is noncanonical or traverses a symlink"
    try:
        raw.relative_to(root)
    except ValueError:
        return None, "source path is outside project root"
    current = raw
    while current != root:
        if current.is_symlink():
            return None, "source path traverses a symlink"
        current = current.parent
    if not raw.is_file():
        return None, "source path is not a regular file"
    return raw, None


def _json_write(path: Path, document):
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(document, stream, sort_keys=True, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--scar-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    inventory_path = args.inventory.absolute()
    project_root = args.project_root.resolve()
    scar_root = args.scar_root.resolve()
    output_root = args.out.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(scar_root))

    before = _environment_snapshot(scar_root, project_root)
    if before["scar_revision"] != EXPECTED_SCAR_REVISION:
        raise RuntimeError(f"frozen source revision differs: {before['scar_revision']}")
    if before["scar_source_fingerprint"] != EXPECTED_SCAR_FINGERPRINT:
        raise RuntimeError(f"frozen source fingerprint differs: {before['scar_source_fingerprint']}")
    input_hash, input_bytes = _sha256_file(inventory_path)
    started_utc = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    document, candidates, selection = _inventory_rows(inventory_path)
    if selection["selected_record_decode_errors"]:
        raise ValueError("candidate identity records failed strict decode: " +
                         json.dumps(selection["selected_record_decode_errors"], sort_keys=True))
    if selection["inventory_shape_issues"]:
        raise ValueError("candidate inventory shape is malformed: " +
                         json.dumps(selection["inventory_shape_issues"], sort_keys=True))
    _json_write(output_root / "manifest.json", {
        "schema": "scar.structured-source-stress-run", "schema_version": 1,
        "command": sys.argv, "command_display": " ".join(sys.argv),
        "started_utc": started_utc, "python": sys.version,
        "inventory": {"path": str(inventory_path), "sha256": input_hash, "bytes": input_bytes,
                      "schema": document.get("schema"), "schema_version": document.get("schema_version"),
                      "candidate_summary": selection},
        "budgets": {"max_bodies": MAX_BODIES, "total_operations": TOTAL_OPERATION_BUDGET,
                    "per_body_operations": PER_BODY_OPERATION_BUDGET,
                    "charging": "known operations_emitted per lower attempt; full per-body ceiling on thrown/unknown-cost lower"},
        "before": before,
        "notes": ["Candidate inventory does not authorize facts; current source snapshot/definition is independently checked.",
                  "No target module is imported or executed.",
                  "Root component/full regressions and old source-link analysis may run concurrently; elapsed time can include host contention."],
    })

    from scar.analysis.program_lowering import prepare_source
    from scar.ir.program.functions import BodyLoweringProfile

    progress_path = output_root / "progress.jsonl"
    results = []
    total_charged = 0
    prepared_paths = {}
    preparation_errors = {}
    indexes_by_path = {}
    preparation_counts = Counter()
    remaining_by_path = Counter()
    candidate_paths = []
    for candidate in candidates:
        snapshot_row = candidate.get("file_row", {}).get("snapshot")
        raw_path = snapshot_row.get("path") if type(snapshot_row) is dict else None
        path_key = Path(raw_path) if type(raw_path) is str else None
        candidate_paths.append(path_key)
        if path_key is not None:
            remaining_by_path[path_key] += 1
    persisted = 0

    def persist(row, path_key):
        nonlocal persisted
        results.append(row)
        progress.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        progress.flush()
        persisted += 1
        if persisted % 16 == 0:
            os.fsync(progress.fileno())
        if path_key is not None:
            remaining_by_path[path_key] -= 1
            if remaining_by_path[path_key] <= 0:
                prepared_paths.pop(path_key, None)
                preparation_errors.pop(path_key, None)
                indexes_by_path.pop(path_key, None)

    with progress_path.open("w", encoding="utf-8") as progress:
        for candidate_index, candidate in enumerate(candidates):
            candidate_path_key = candidate_paths[candidate_index]
            if candidate.get("decode_error") is not None:
                row = {"candidate_index": candidate_index,
                       "file_index": candidate["file_index"],
                       "definition_index": candidate["definition_index"],
                       "body_index": candidate["body_index"],
                       "definition_name": candidate["definition_row"].get("name"),
                       "source_validation": "CANDIDATE_RECORD_ERROR",
                       "new": {"status": "CANDIDATE_RECORD_ERROR", "graph_present": False,
                               "errors": [candidate["decode_error"]]},
                       "operation_budget": {"charged_before": total_charged, "limit": 0,
                                             "charged": 0, "cost_known": True}}
                persist(row, candidate_path_key)
                continue
            definition = candidate["definition"]
            source_snapshot = candidate["snapshot"]
            old_body = candidate["body"]
            row_base = {"candidate_index": candidate_index,
                        "file_index": candidate["file_index"],
                        "definition_index": candidate["definition_index"],
                        "body_index": candidate["body_index"],
                        "path": source_snapshot.path,
                        "definition_id": definition.id.wire,
                        "definition_name": definition.name,
                        "definition_source": _ref_document(definition.source),
                        "old_status": old_body.status.value}
            remaining = TOTAL_OPERATION_BUDGET - total_charged
            if remaining < 1:
                row = {**row_base, "source_validation": "NOT_CHECKED_BUDGET_EXHAUSTED",
                       "new": {"status": "AGGREGATE_BUDGET_BLOCKED", "graph_present": False,
                               "errors": ["fixed aggregate operation budget is exhausted"]},
                       "operation_budget": {"charged_before": total_charged, "limit": 0,
                                             "charged": 0, "cost_known": True}}
                persist(row, candidate_path_key)
                continue
            source_path, path_error = _safe_source_path(source_snapshot, project_root)
            if path_error:
                row = {**row_base, "source_validation": "REJECTED_PATH",
                       "source_validation_errors": [path_error],
                       "new": {"status": "SOURCE_PATH_REJECTED", "graph_present": False,
                               "errors": [path_error]},
                       "operation_budget": {"charged_before": total_charged, "limit": 0,
                                             "charged": 0, "cost_known": True}}
                persist(row, candidate_path_key)
                continue
            context = prepared_paths.get(source_path)
            if context is None and source_path in preparation_errors:
                reason = preparation_errors[source_path]
                row = {**row_base, "source_validation": "PREPARE_FAILED",
                       "source_validation_errors": [reason],
                       "new": {"status": "PREPARE_ERROR", "graph_present": False,
                               "errors": [reason]},
                       "operation_budget": {"charged_before": total_charged, "limit": 0,
                                             "charged": 0, "cost_known": True}}
                persist(row, candidate_path_key)
                continue
            if context is None:
                try:
                    context = prepare_source(source_path, project_root=project_root)
                    prepared_paths[source_path] = context
                    preparation_counts[str(source_path)] += 1
                except Exception as error:
                    reason = f"{type(error).__name__}: {error}"
                    preparation_errors[source_path] = reason
                    row = {**row_base, "source_validation": "PREPARE_FAILED",
                           "source_validation_errors": [reason],
                           "new": {"status": "PREPARE_ERROR", "graph_present": False,
                                   "errors": [reason]},
                           "operation_budget": {"charged_before": total_charged, "limit": 0,
                                                 "charged": 0, "cost_known": True}}
                    persist(row, candidate_path_key)
                    continue
            source_ref = definition.source
            indexes = indexes_by_path.get(source_path)
            if indexes is None:
                indexes = _source_indexes(context)
                indexes_by_path[source_path] = indexes
            node, source_errors = _candidate_check(context, source_snapshot, definition, indexes)
            if node is None or source_errors:
                row = {**row_base, "source_validation": "REJECTED",
                       "source_validation_errors": source_errors,
                       "new": {"status": "SOURCE_CANDIDATE_REJECTED", "graph_present": False,
                               "operations_emitted": 0, "errors": source_errors},
                       "operation_budget": {"charged_before": total_charged, "limit": 0,
                                             "charged": 0, "cost_known": True}}
            else:
                body_budget = min(PER_BODY_OPERATION_BUDGET, remaining)
                row, charged = _body_result(context, source_ref, source_snapshot, definition,
                                            old_body, indexes, body_budget, total_charged)
                row.update({"candidate_index": candidate_index,
                            "file_index": candidate["file_index"],
                            "definition_index": candidate["definition_index"],
                            "body_index": candidate["body_index"],
                            "path": source_snapshot.path,
                            "operation_budget": {**row["operation_budget"],
                                                  "charged_before": total_charged,
                                                  "limit": body_budget}})
                total_charged += charged
            persist(row, candidate_path_key)
            if (candidate_index + 1) % 16 == 0:
                print(f"completed {candidate_index + 1}/{len(candidates)} candidates; "
                      f"operation budget {total_charged}/{TOTAL_OPERATION_BUDGET}", flush=True)

    with progress_path.open("a", encoding="utf-8") as progress:
        progress.flush()
        os.fsync(progress.fileno())
    after = _environment_snapshot(scar_root, project_root)
    final_status_counts = Counter(row.get("new", {}).get("status", "UNKNOWN") for row in results)
    old_status_counts = Counter(row.get("old", {}).get("status", row.get("old_status", "UNKNOWN"))
                                for row in results)
    source_calls = [call for row in results for call in row.get("source_calls", [])]
    old_covered = sum(bool(call.get("old", {}).get("core_covered")) for call in source_calls)
    new_covered = sum(bool(call.get("new", {}).get("core_covered")) for call in source_calls)
    final = {
        "schema": "scar.structured-source-stress-report", "schema_version": 1,
        "command": sys.argv, "command_display": " ".join(sys.argv),
        "started_utc": started_utc, "finished_utc": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(time.monotonic() - started, 3),
        "python": sys.version, "platform": platform.platform(),
        "rss": {"before_maxrss_platform_units": rss_before,
                "after_maxrss_platform_units": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "units": "KiB on Linux"},
        "inventory": {"path": str(inventory_path), "sha256": input_hash, "bytes": input_bytes,
                      "schema": document.get("schema"), "schema_version": document.get("schema_version"),
                      "candidate_summary": selection},
        "frozen_source": {"expected_revision": EXPECTED_SCAR_REVISION,
                          "expected_fingerprint": EXPECTED_SCAR_FINGERPRINT,
                          "before": before, "after": after,
                          "unchanged": before["scar_revision"] == after["scar_revision"] and
                                      before["scar_source_fingerprint"] == after["scar_source_fingerprint"]},
        "project": {"root": str(project_root), "before": {
                        "revision": before["project_revision"], "status": before["project_status"],
                        "tracked_python_sha256": before["project_tracked_python_sha256"],
                        "tracked_python_count": before["project_tracked_python_count"]},
                    "after": {"revision": after["project_revision"], "status": after["project_status"],
                        "tracked_python_sha256": after["project_tracked_python_sha256"],
                        "tracked_python_count": after["project_tracked_python_count"]},
                    "unchanged": before["project_revision"] == after["project_revision"] and
                                 before["project_tracked_python_sha256"] == after["project_tracked_python_sha256"]},
        "budgets": {"max_bodies": MAX_BODIES, "total_operations": TOTAL_OPERATION_BUDGET,
                    "per_body_operations": PER_BODY_OPERATION_BUDGET,
                    "charged": total_charged, "remaining": max(0, TOTAL_OPERATION_BUDGET - total_charged)},
        "summary": {"selected_candidates": len(candidates), "prepared_file_paths": len(preparation_counts),
                    "prepare_calls_by_path": dict(preparation_counts),
                    "old_body_statuses": dict(sorted(old_status_counts.items())),
                    "new_body_statuses": dict(sorted(final_status_counts.items())),
                    "source_calls": len(source_calls),
                    "old_core_covered_calls": old_covered,
                    "new_core_covered_calls": new_covered,
                    "old_call_endpoint_total": sum(len(call.get("old", {}).get("ordered_use_endpoints", []))
                                                    for call in source_calls),
                    "new_call_endpoint_total": sum(len(call.get("new", {}).get("ordered_use_endpoints", []))
                                                    for call in source_calls)},
        "scope": {"whole_program_coverage_established": False,
                  "source_call_coverage_is_not_dispatch_or_effect_proof": True,
                  "unresolved_operand_subtrees_are_not_core_covered": True,
                  "target_execution": False, "transformation_authorized": False},
        "body_results": results,
        "notes": ["The old inventory is a candidate index and old-state comparison input, not a fact source.",
                  "Core-covered means a current exact call source link, an ordered Use for each direct AST operand, and source links for every expression in those operand subtrees.",
                  "Counts of graph nodes/operations indicate structure built, not semantic understanding or effect completeness.",
                  "Root component/full regression and older source-link jobs may have run concurrently."],
    }
    _json_write(output_root / "report.json", final)
    print(json.dumps({"report": str(output_root / "report.json"),
                      "selected": len(candidates), "charged": total_charged,
                      "new_statuses": dict(sorted(final_status_counts.items())),
                      "source_calls": len(source_calls), "new_core_covered_calls": new_covered,
                      "duration_seconds": final["duration_seconds"]}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
