"""Bounded, read-only source CALL resolution through the common graph."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

from scar.ir.program.ids import OperationID
from scar.ir.record_codec import encode


def _positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return number


def _operation(value):
    prefix, separator, identity = value.partition(":")
    if prefix != OperationID.prefix or not separator or not identity:
        raise argparse.ArgumentTypeError("expected a complete original OperationID wire")
    return OperationID(identity)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode() + b"\n"


def _atomic(path, value):
    handle, temporary = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(_json(value))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _now():
    return datetime.now(timezone.utc).isoformat()


class _Task:
    def __init__(self, out, model, budget):
        from scar.analysis.static_jobs import _process
        status, identity = _process(os.getpid())
        if status != "LIVE":
            raise RuntimeError("cannot establish this analyzer process identity")
        self.path, self.started, self.last_write = out / "task.json", time.monotonic(), float("-inf")
        self.record = {"schema": "scar.contextual-call-task", "schema_version": 1,
            "process": identity, "model": str(model), "out": str(out),
            "state": "RUNNING", "stage": "OPENING_SOURCE_MODEL", "started_at": _now(),
            "budget": asdict(budget), "target_executed": False}
        self.write(force=True)

    def write(self, *, force=False, **values):
        self.record.update(values)
        current = time.monotonic()
        if force or current - self.last_write >= 1:
            self.record.update(updated_at=_now(), elapsed_seconds=current - self.started)
            _atomic(self.path, self.record)
            self.last_write = current

    def activity(self, event):
        self.write(activity=dict(event))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="artifacts/current/static")
    parser.add_argument("--file")
    parser.add_argument("--name")
    parser.add_argument("--kind")
    parser.add_argument("--out", required=True, help="new or empty canonical output directory")
    parser.add_argument("--call-line", type=_positive, help="exact original CALL SourceReference.start_line")
    parser.add_argument("--operation", action="append", type=_operation, default=[])
    parser.add_argument("--limit", type=_positive, default=20, help="maximum selected canonical caller bodies")
    parser.add_argument("--max-calls", type=_positive, default=100)
    parser.add_argument("--max-seconds", type=_positive, default=180)
    parser.add_argument("--max-input-bytes", type=_positive, default=1024 ** 3)
    parser.add_argument("--max-cached-bytes", type=_positive, default=512 * 1024 ** 2)
    args = parser.parse_args(argv)

    from scar.analysis.static_calls import StaticCallBudget, StaticCallSession
    model, out = Path(args.model).absolute(), Path(args.out).absolute()
    if (out.resolve() != out or out.is_symlink()
            or out.exists() and (not out.is_dir() or any(out.iterdir()))):
        raise FileExistsError("contextual output must be a new or empty canonical directory")
    out.mkdir(parents=True, exist_ok=True)
    budget = replace(StaticCallBudget(), max_calls=args.max_calls, max_seconds=args.max_seconds,
        max_input_bytes=args.max_input_bytes, max_cached_bytes=args.max_cached_bytes)
    task = _Task(out, model, budget)
    owner = resolver = None
    callers, artifacts, issues = [], [], []
    frontiers, interfaces = Counter(), Counter()
    requested, found_operations = frozenset(args.operation), set()
    calls = targets = output_bytes = selected_calls = 0
    receiver_queries = receiver_edges = 0
    class_sources_count = class_invocations_count = class_interface_edges = 0
    matched_bodies = eligible_bodies = processed_bodies = 0
    scope_complete, inputs_stable, state = False, False, "FAILED"
    error = None
    measurements = {}

    def issue(kind, detail):
        issues.append({"kind": kind, "detail": detail})

    def persist_document(document, relative, schema, **metadata):
        nonlocal output_bytes
        raw = _json(document)
        if len(raw) > budget.max_record_bytes:
            raise OverflowError("contextual result decoded record exceeds its byte ceiling")
        stored = gzip.compress(raw, compresslevel=3, mtime=0)
        if owner.output_bytes + output_bytes + len(stored) > budget.max_output_bytes:
            raise OverflowError("contextual result output-byte budget exhausted")
        path = out / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(stored)
        output_bytes += len(stored)
        descriptor = {"path": relative, "bytes": len(stored),
            "sha256": hashlib.sha256(stored).hexdigest(), "decoded_bytes": len(raw),
            "decoded_sha256": hashlib.sha256(raw).hexdigest(),
            "schema": schema, **metadata}
        artifacts.append(descriptor)
        return descriptor

    def persist(resolution, caller_number, call_number):
        from scar.analysis.contextual_call_export import export_contextual_call
        edges = tuple(edge for target in resolution.targets for edge in target.dependency_edges())
        descriptor = persist_document(export_contextual_call(resolution),
            f"callers/{caller_number:06d}/{call_number:06d}.json.gz", "scar.contextual-calls/2",
            call=resolution.call.node.wire, targets=len(resolution.targets), interface_edges=len(edges))
        interfaces.update(edge.kind.value for edge in edges)
        return descriptor

    def persist_receiver(evidence, resolution, caller_number, call_number, lookup_number):
        nonlocal receiver_queries, receiver_edges
        from scar.analysis.program_dependency_export import export_dependency_walk
        lookup, walk = evidence.lookup, evidence.walk
        document = {"schema": "scar.attribute-receiver-query", "schema_version": 1,
            "call_operation": resolution.call.node.wire,
            "lookup_operation": lookup.operation.wire,
            "lookup_source": encode(lookup.source), "source_spelling": lookup.field,
            "graph": export_dependency_walk(walk),
            "target_executed": False, "whole_program_complete": False}
        descriptor = persist_document(document,
            f"receivers/{caller_number:06d}/{call_number:06d}/{lookup_number:06d}.json.gz",
            "scar.attribute-receiver-query/1", call_operation=resolution.call.node.wire,
            lookup_operation=lookup.operation.wire, receiver_edges=len(walk.edges))
        receiver_queries += 1
        receiver_edges += len(walk.edges)
        return descriptor

    def persist_classes(resolution, caller_number, call_number):
        nonlocal class_sources_count, class_invocations_count, class_interface_edges
        from scar.analysis.program_dependency_export import _Tables
        sources = resolver.class_sources(resolution.call)
        invocations = resolver.class_invocations(resolution.call)
        if sources is None or invocations is None:
            issue('CLASS_INVOCATION_EPHEMERAL_UNAVAILABLE',
                'The completed call has no matching class-source/implementation scope.')
            return None
        if not sources and not invocations:
            return None
        table = _Tables()
        record = {'schema': 'scar.contextual-class-invocations', 'schema_version': 1,
            'call': table.point(resolution.call), 'sources': [table.pack(source) for source in sources],
            'invocations': [table.pack(invocation) for invocation in invocations],
            'frontiers': [table.frontier(frontier) for frontier in resolver.type_calls.frontiers_for(resolution.call)],
            'target_executed': False, 'runtime_dispatch_verified': False,
            'physical_abi_mapping_complete': False, 'python_callbacks_connected': False,
            'whole_program_complete': False, 'transformation_authorized': False}
        record.update(table.tables)
        count = sum(len(invocation.edges) for invocation in invocations)
        descriptor = persist_document(record,
            f'class-invocations/{caller_number:06d}/{call_number:06d}.json.gz',
            'scar.contextual-class-invocations/1', class_sources=len(sources),
            class_invocations=len(invocations), implementation_interface_edges=count)
        class_sources_count += len(sources)
        class_invocations_count += len(invocations)
        class_interface_edges += count
        return descriptor

    try:
        owner = StaticCallSession(model, out=out / "source-basis", budget=budget, activity=task.activity)
        resolver = owner.contextual_resolver()
        task.write(force=True, stage="SELECTING_ORIGINAL_BODIES", input_manifest_sha256=owner.manifest_sha256)
        locations = resolver.session.body_locations(file=args.file, entry=args.name, kind=args.kind)
        matched_bodies = len(locations)
        eligible, unsupported = [], Counter()
        for number, position in locations:
            row = owner.units[number]["bodies"][position]
            if row.get("status") == "LOWERED_WITH_GAPS":
                eligible.append((number, position))
            else:
                unsupported[row.get("status", "STATUS_ABSENT")] += 1
        eligible_bodies = len(eligible)
        if unsupported:
            issue("SELECTED_BODY_SCOPE_UNSUPPORTED", str(dict(unsupported)))
        if not locations:
            issue("NO_MATCHING_ORIGINAL_BODY", "The saved model has no body artifact matching the requested selector.")
        if eligible_bodies > args.limit:
            issue("CALLER_BODY_LIMIT", f"Selected {args.limit} of {eligible_bodies} eligible original bodies.")
        stopped = False
        for caller_number, (number, position) in enumerate(eligible[:args.limit]):
            owner._check()
            unit, row = owner.units[number], owner.units[number]["bodies"][position]
            task.write(force=True, stage="LOADING_ORIGINAL_CALLER", source=unit["path"], entry=row["entry_key"])
            namespaces = tuple(resolver.session.select_bodies(file=unit["path"], entry=row["entry_key"], kind=row["kind"]))
            matching = [namespace for namespace in namespaces
                if namespace.graph.artifact.uri == str(owner.logical_root / row["artifact"]["path"])]
            if len(matching) != 1:
                raise ValueError("original body selector did not retain its exact artifact owner")
            body = resolver._body(matching[0])
            original_calls = resolver._calls(body)
            operations = tuple(operation for operation, link in original_calls.items()
                if (not requested or operation in requested)
                and (args.call_line is None or link.source.start_line == args.call_line))
            found_operations.update(operations)
            selected_calls += len(operations)
            receipts, receiver_receipts = [], []
            caller = {"source": unit["path"], "entry_key": row["entry_key"],
                "caller_graph": encode(body.namespace.graph), "matched_calls": len(operations),
                "artifacts": receipts, "receiver_artifacts": receiver_receipts, 'class_invocation_artifacts': []}
            callers.append(caller)
            for operation in operations:
                if calls >= args.max_calls:
                    issue("SELECTED_CALL_LIMIT", "More selected original CALLs remain after the --max-calls prefix.")
                    stopped = True
                    break
                task.write(force=True, stage="RESOLVING_ORIGINAL_CALL", operation=operation.wire,
                    calls_persisted=calls, targets_persisted=targets)
                # Invoke the public owner consumer. No hand-built target,
                # SourceDefinitionReference, factory list or injected proof.
                for resolution in owner.resolve_contextual_calls(body, operations=(operation,), context=None):
                    call_number = len(receipts)
                    descriptor = persist(resolution, caller_number, call_number)
                    receipts.append(descriptor["path"])
                    calls += 1
                    targets += len(resolution.targets)
                    class_descriptor = persist_classes(resolution, caller_number, call_number)
                    if class_descriptor is not None:
                        caller['class_invocation_artifacts'].append(class_descriptor['path'])
                    # Read the just-completed scope before any later resolve
                    # can replace its ephemeral receiver evidence. Its graph
                    # is independent evidence, never a callee identity path.
                    receivers = resolver.receiver_evidence(resolution.call)
                    if receivers is None:
                        issue("ATTRIBUTE_RECEIVER_EPHEMERAL_UNAVAILABLE",
                            "The completed CALL " + resolution.call.node.wire
                            + " has no matching completed receiver-evidence scope; it is not an analyzed empty receiver set.")
                    else:
                        for lookup_number, evidence in enumerate(receivers):
                            receiver_descriptor = persist_receiver(evidence, resolution,
                                caller_number, call_number, lookup_number)
                            receiver_receipts.append(receiver_descriptor["path"])
                    frontiers.update(frontier.kind for frontier in resolution.frontiers)
                    task.write(force=True, calls_persisted=calls, targets_persisted=targets,
                        receiver_queries=receiver_queries, receiver_edges=receiver_edges)
                    if any("BUDGET" in frontier.kind for frontier in resolution.frontiers):
                        issue("CONTEXTUAL_RESOLUTION_BUDGET", "The saved typed result retains the accepted prefix and its specific budget frontiers.")
                        stopped = True
                if stopped:
                    break
            processed_bodies += 1
            if stopped:
                break
        if requested - found_operations and not stopped and eligible_bodies <= args.limit:
            issue("SELECTED_OPERATION_UNAVAILABLE", ", ".join(sorted(operation.wire for operation in requested - found_operations)))
        scope_complete = not issues and processed_bodies == eligible_bodies
        state = ("BUDGET_EXHAUSTED" if any("BUDGET" in row["kind"] for row in issues)
            else "COMPLETED_WITH_FRONTIERS" if scope_complete else "PARTIAL_SELECTION")
    except (OverflowError, TimeoutError) as caught:
        state, error = "BUDGET_EXHAUSTED", {"type": type(caught).__name__, "message": str(caught), "stage": task.record["stage"]}
    except KeyboardInterrupt as caught:
        state, error = "INTERRUPTED", {"type": type(caught).__name__, "message": str(caught), "stage": task.record["stage"]}
    except Exception as caught:
        state, error = "FAILED", {"type": type(caught).__name__, "message": str(caught), "stage": task.record["stage"]}
    finally:
        if resolver is not None:
            measurements = resolver.measurements()
            measurements["module_index"] = dict(resolver.modules.index_metrics)
        if owner is not None:
            measurements.update(input_bytes=owner.input_bytes,
                reader_cache_accounted_bytes=owner._cache_bytes + owner._environment_facts.bytes,
                source_basis_output_bytes=owner.output_bytes,
                contextual_output_bytes=output_bytes, analyzer_counts=dict(owner.counts))
            task.write(force=True, stage="CHECKING_ORIGINAL_INPUT_STABILITY")
            try:
                owner.close()
                inputs_stable = True
            except Exception as caught:
                state, scope_complete = "FAILED", False
                error = {"type": type(caught).__name__, "message": str(caught), "stage": task.record["stage"]}

    summary = {"schema": "scar.contextual-call-summary", "schema_version": 1,
        "state": state, "model": str(model), "input_manifest_sha256": owner.manifest_sha256 if owner else None,
        "input_receipts_stable_at_close": inputs_stable, "selection": {
            "file": args.file, "name": args.name, "kind": args.kind, "call_line": args.call_line,
            "call_line_meaning": "exact original CALL SourceReference.start_line",
            "operations": sorted(operation.wire for operation in requested),
            "matched_body_artifacts": matched_bodies, "eligible_canonical_bodies": eligible_bodies,
            "processed_caller_bodies": processed_bodies, "calls_matched_in_processed_bodies": selected_calls,
            "calls_persisted": calls, "selected_call_enumeration_complete": scope_complete},
        "target_alternatives": targets, "interface_edges": dict(interfaces),
        "receiver_queries": receiver_queries, "receiver_edges": receiver_edges,
        'class_statement_sources': class_sources_count, 'class_invocations': class_invocations_count,
        'class_implementation_interface_edges': class_interface_edges,
        "argument_edges": interfaces.get("ARGUMENT", 0),
        "normal_return_edges": interfaces.get("COMPLETION", 0),
        "frontier_counts": dict(frontiers), "issues": issues, "error": error,
        "callers": callers, "artifacts": artifacts,
        "source_basis": ({"artifact": encode(owner.basis), "descriptor": owner.artifacts[0],
            "path": "source-basis/basis.json.gz"} if owner else None),
        "budget": asdict(budget), "measurements": measurements,
        "analyzer_seconds": time.monotonic() - task.started,
        "timing_meaning": "static analyzer and result serialization time; no target performance measurement",
        "target_executed": False, "target_resolution_complete": False, "first_stage_complete": False,
        "saved_call_publication_used": False, "saved_call_publication_updated": False,
        "qualification": "Conditional source interfaces over the shared original graph; None/Open contexts and every premise remain in typed records. This is not a CALL publication or a whole-program completion claim."}
    _atomic(out / "summary.json", summary)
    task.write(force=True, state=state, stage="TERMINAL", ended_at=_now(), error=error,
        calls_persisted=calls, targets_persisted=targets, selected_call_enumeration_complete=scope_complete,
        receiver_queries=receiver_queries, receiver_edges=receiver_edges,
        first_stage_complete=False, summary="summary.json")
    print(json.dumps({"state": state, "out": str(out), "calls": calls, "targets": targets,
        'class_sources': class_sources_count, 'class_invocations': class_invocations_count,
        "interface_edges": dict(interfaces), "analyzer_seconds": summary["analyzer_seconds"],
        "summary": str(out / "summary.json")}, ensure_ascii=False, sort_keys=True))
    return 0 if scope_complete else 130 if state == "INTERRUPTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
