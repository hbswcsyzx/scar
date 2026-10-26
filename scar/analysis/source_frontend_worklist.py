"""Mechanical source recovery tasks, separate from canonical program graphs.

Planning reads metadata only. Workers use existing immutable source graphs,
owned CodeWitnesses and ordinary source lowerers, without executing the target.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from hashlib import sha256
import inspect
import json
from pathlib import Path
import time
import tokenize
import traceback

from scar.analysis.call_compilation import compile_cache_key
from scar.analysis.code_witness import CodeWitnessStore
from scar.analysis.inventory_partitions import _read_receipt, _write_shard
from scar.analysis.program_composition import CompositionIndex
from scar.analysis.program_lowering import PreparedSource, SourceProgram, _symbol_tables
from scar.analysis.source_language import SourceCodeEvidence, SourceLanguageOptions
from scar.ir.program.call_edges import CapturedCode, CodeCapture, CodeSourceLink, CallLinkStatus
from scar.ir.program.compilation import CallCompilationProfile
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.program.inventory import DefinitionKind, DefinitionInventory, SourceContextDigest
from scar.ir.program.source_language import SourceLanguageCapability, encode_language_overlay
from scar.ir.record_codec import decode, encode
from scar.ir.semantics_v2 import SourceSnapshot


_SUSPENDED = inspect.CO_GENERATOR | inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR | inspect.CO_ITERABLE_COROUTINE
_TERMINAL = frozenset(("SUCCEEDED", "UNSUPPORTED", "FAILED", "CODE_WITNESS_UNAVAILABLE", "SOURCE_CONTEXT_UNAVAILABLE"))


def _need(condition, message):
    if not condition:
        raise ValueError("source frontend: " + message)


def _bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def _hash(value):
    return sha256(_bytes(value)).hexdigest()


def _receipt(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "sha256": sha256(raw).hexdigest(), "bytes": len(raw)}


def _producer():
    analysis = Path(__file__).resolve().parent
    names = ("source_frontend_worklist.py", "program_lowering.py", "structured_lowering.py",
        "environment_lowering.py", "source_language.py", "source_environment_layout.py",
        "function_interfaces.py", "program_composition.py", "inventory_partitions.py",
        "code_witness.py", "call_compilation.py")
    paths = {analysis / name for name in names}
    paths.update(analysis.glob('source_*_lowering.py'))
    paths.update(analysis.glob('source_*_validation.py'))
    # Canonical type/codec contracts affect source construction and its guards.
    paths.update((analysis.parent / 'ir').rglob('*.py'))
    paths.add(analysis.parent / 'trace/code_snapshot.py')
    return [_receipt(path) for path in sorted(paths)]


@dataclass(frozen=True)
class SourceFrontendBudget:
    max_catalog_files: int = 4096
    max_catalog_bodies: int = 100000
    max_catalog_groups: int = 100000
    max_dispatch_bodies: int = 128
    max_source_files: int = 64
    max_source_bytes: int = 16_000_000
    max_operations_per_body: int = 10000
    max_total_operations: int = 1_000_000
    max_record_bytes: int = 128_000_000
    max_output_bytes: int = 512_000_000
    max_elapsed_seconds: int = 900

    def __post_init__(self):
        _need(all(type(value) is int and value > 0 for value in asdict(self).values()), "budgets must be positive exact integers")
        _need(self.max_operations_per_body <= 100000, "per-body source lowerer ceiling exceeds its public API")


@dataclass(frozen=True)
class SourceFrontendPlan:
    composition: CompositionIndex
    document: dict
    bodies: tuple[dict, ...]
    groups: tuple[dict, ...]
    dispatch: tuple[dict, ...]
    digest: str

    def require_unchanged(self):
        _need(type(self.composition) is CompositionIndex and self.digest == _hash({
            "document": self.document, "bodies": self.bodies, "groups": self.groups, "dispatch": self.dispatch}),
            "worklist changed after planning")
        _need(self.document["composition_inputs"] == self.composition.source_inputs(), "composition inputs changed")


def _body_key(snapshot, context, definition):
    return _hash({"snapshot": snapshot, "context": context, "definition": definition})


def _module_variants(store, captured, link):
    found, frontiers = [], []
    for level in link.optimize_levels:
        try:
            key = compile_cache_key(Path(link.snapshot.path), link.snapshot.fingerprint,
                CallCompilationProfile.RECORDED_FUTURE_FLAGS, captured.flags, level,
                compile_filename=captured.filename)
        except ValueError as error:
            frontiers.append({'kind': 'COMPILER_CONTEXT_UNSUPPORTED', 'type': type(error).__name__, 'detail': str(error)})
            continue
        digest = _hash(encode(key))
        row = store.document["modules"].get(digest)
        if row is not None and row["compile_key"] == encode(key) and row["snapshot"] == encode(link.snapshot):
            found.append(digest)
    return found, frontiers


def _check_store(store):
    _need(type(store) is CodeWitnessStore and not store.writable and not store.compile_missing,
          "an explicit owned read-only CodeWitnessStore is required")
    return store.receipt()


def _write_rows(root, name, rows, limit):
    return _write_shard(root, name, {"schema": "scar.source-frontend-table", "schema_version": 1,
        "rows": list(rows)}, limit=limit)


def plan_source_frontend(composition, current_bindings, code_witnesses, *,
                         budget=SourceFrontendBudget(), capabilities=(
                             SourceLanguageCapability.FIXED_UNPACK,
                             SourceLanguageCapability.SLICE_KEYS,
                             SourceLanguageCapability.LEXICAL_LOCALS,
                             SourceLanguageCapability.CALL_KWARGS_314_V1),
                         eligible_body_keys=None, out_dir=None, progress=None):
    """Inventory every body/group, then bound metadata-only dispatch candidates.

    No reason text or name pattern participates in selection. A matching module
    entry is merely PENDING_CODE_RESOLVE, never a verified nested CodeType.
    Optional unique body keys narrow only the dispatch window; the full source
    and current-call catalogs remain intact. Explicit windows prioritize call
    counts; the worker retains its existing per-file context grouping.
    """
    _need(type(composition) is CompositionIndex and composition.partitioned, "a regular partitioned composition is required")
    _need(type(budget) is SourceFrontendBudget, "budget must be independently supplied")
    budget.__post_init__()
    SourceLanguageOptions(capabilities)  # Exact enum types and uniqueness, no I/O.
    if eligible_body_keys is not None:
        _need(type(eligible_body_keys) is tuple and bool(eligible_body_keys)
              and all(type(key) is str and bool(key) for key in eligible_body_keys)
              and len(set(eligible_body_keys)) == len(eligible_body_keys),
              "eligible_body_keys must be an explicit nonempty tuple of unique nonempty strings")
    store_receipt = _check_store(code_witnesses)
    root = Path(current_bindings).resolve()
    report_path = root / "report.json" if root.is_dir() else root
    report, report_receipt = _read_receipt(report_path, limit=budget.max_record_bytes)
    _need(report.get("schema") == "scar.source-invocations" and report.get("schema_version") in (2, 3)
          and report.get("current_capture_raw_scan_verified") is True
          and report.get("old_capture_dynamic_facts_used_for_current_run") is False,
          "current binding must retain its independently verified Run scope")
    inputs = composition.source_inputs()
    _need(report["inventory"] == composition.document["inventory"]
          and report["composition_canonical_sha256"] == inputs["composition_canonical_sha256"],
          "binding belongs to a different composition/inventory")
    declaration = report["bindings"]
    _need(declaration["path"] == "bindings.json", "binding table must be its fixed local artifact")
    bindings_path = report_path.parent / declaration["path"]
    bindings, bindings_receipt = _read_receipt(bindings_path, limit=budget.max_record_bytes)
    _need(bindings_receipt["physical_sha256"] == declaration["raw_sha256"]
          and bindings_receipt["physical_bytes"] == declaration["raw_bytes"]
          and bindings.get("schema") == "scar.source-invocation-bindings"
          and bindings["schema_version"] == report["schema_version"], "current binding receipt/schema differs")
    rows = bindings["bindings"]
    _need(len(rows) <= budget.max_catalog_groups and composition.inventory_file_count <= budget.max_catalog_files,
          "complete metadata catalog exceeds the independent ceiling")
    model = composition.inventory_component("call_sources")["model"]
    captures = {}
    for raw in model["codes"]:
        row = decode(CodeCapture, raw)
        _need(row.code.key not in captures or captures[row.code.key] == row.code, "conflicting complete code descriptors")
        captures[row.code.key] = row.code
    links = [(i, decode(CodeSourceLink, raw)) for i, raw in enumerate(model["code_links"])]
    variants = defaultdict(list)
    for index, link in links:
        if link.status is CallLinkStatus.VERIFIED and link.definition is not None and link.source is not None:
            captured = captures[link.code]
            variants[(link.snapshot.path, link.snapshot.fingerprint, link.definition.wire)].append((index, link, captured))
    bodies, by_key, by_source, by_element, status_counts = [], {}, {}, {}, Counter()
    for fi in range(composition.inventory_file_count):
        raw = composition.inventory_file(fi)  # Header/ref metadata, not body graphs.
        declarations = {row.id: row for row in decode(tuple[DefinitionInventory, ...], raw["definitions"])}
        declarations_by_wire = {identity.wire: row for identity, row in declarations.items()}
        snapshot = decode(SourceSnapshot, raw["snapshot"])
        context = decode(SourceContextDigest, raw["context"]) if raw["context"] is not None else None
        _need(len(declarations) == len(raw["definitions"]), "duplicate source definition metadata")
        for bi, old in enumerate(raw["bodies"]):
            definition = declarations_by_wire.get(old["definition"]["wire"])
            _need(definition is not None, "body has no original indexed definition")
            key = _body_key(raw["snapshot"], raw["context"], old["definition"])
            _need(key not in by_key, "duplicate fully qualified body")
            exact = [(i, link, code) for i, link, code in variants[(snapshot.path, snapshot.fingerprint, definition.id.wire)]
                     if link.snapshot == snapshot and link.source == definition.source]
            evidence = []
            for i, link, code in exact:
                module_variants, compiler_frontiers = _module_variants(code_witnesses, code, link)
                evidence.append({"captured": encode(code), "code_source_link": encode(link),
                    "code_source_locator": composition.inventory_component_locator("call_sources", f"/model/code_links/{i}"),
                    "module_variants": module_variants, "compiler_frontiers": compiler_frontiers})
            if old["status"] == "LOWERED_WITH_GAPS":
                category = "ALREADY_MODELED"
            elif context is None:
                category = "SOURCE_CONTEXT_UNAVAILABLE"
            elif definition.kind is not DefinitionKind.FUNCTION:
                category = "ENTRY_ADAPTER_MISSING:" + definition.kind.value
            elif not evidence:
                category = "CAPTURED_CODE_SOURCE_WITNESS_MISSING"
            elif len({row["captured"]["key"] for row in evidence}) != 1:
                category = "MULTIPLE_CODE_VARIANTS_REQUIRE_ENTRY_APPLICABILITY"
            elif evidence[0]["captured"]["flags"] & _SUSPENDED:
                category = "ENTRY_ADAPTER_MISSING:RESUMABLE_FUNCTION"
            elif evidence[0]["compiler_frontiers"] and not evidence[0]["module_variants"]:
                category = "COMPILER_CONTEXT_UNSUPPORTED"
            elif not evidence[0]["module_variants"]:
                category = "CODE_WITNESS_MODULE_VARIANT_MISSING"
            else:
                category = "PENDING_CODE_RESOLVE"
            item = {"body_key": key, "file_index": fi, "body_index": bi, "snapshot": raw["snapshot"],
                "context": raw["context"], "definition": encode(definition), "prior_status": old["status"],
                "metadata_status": category, "code_variants": evidence, "current_groups": [], "current_calls": 0,
                "body_locator": composition.inventory_file_locator(fi, f"/bodies/{bi}")}
            by_key[key] = item
            if context is not None:
                by_source[(snapshot.path, snapshot.fingerprint, context.namespace_root, definition.id.wire)] = item
            by_element[fi, definition.id.wire] = item
            bodies.append(item)
            status_counts[old["status"]] += 1
            _need(len(bodies) <= budget.max_catalog_bodies, "complete body catalog exceeds the independent ceiling")
        if progress is not None:
            progress({"stage": "frontend_catalog_file", "file_index": fi, "bodies": len(raw["bodies"])})
    groups, group_counts, call_counts, seen = [], Counter(), Counter(), set()
    for ordinal, binding in enumerate(rows):
        identity = binding["process_id"], binding["code"]
        capture = decode(CodeCapture, binding["code_capture"])
        _need(identity not in seen and binding["binding_index"] == ordinal
              and capture.process_id == identity[0] and capture.code.key == identity[1], "duplicate or inconsistent current group")
        seen.add(identity)
        reference = binding["definition"]
        item = None
        if reference is None:
            category = "SOURCE_DEFINITION_UNRESOLVED"
        elif report["schema_version"] == 3 and binding.get("composition_element") is None:
            category = "EXTERNAL_ENTRY_CATALOG_AND_ADMISSION_SCOPE_REQUIRED"
        else:
            if report["schema_version"] == 3:
                source_key = (reference["snapshot"]["path"], reference["snapshot"]["fingerprint"],
                              reference["context"]["namespace_root"], reference["definition"]["wire"])
                item = by_source.get(source_key)
            else:
                element = reference
                item = by_element.get((element["file_index"], element["identity"]["wire"]))
            _need(item is not None, "current project group has no exact original body metadata")
            _need(any(row["captured"] == encode(capture.code) for row in item["code_variants"]),
                  "current project descriptor has no exact original code/source match")
            category = "BODY_LINKED" if binding["body"] is not None else item["metadata_status"]
            item["current_groups"].append(ordinal)
            item["current_calls"] += binding["entered_invocations"]
        count = binding["entered_invocations"]
        _need(type(count) is int and count >= 1, "current group must retain its actual invocation count")
        group = {"binding_index": ordinal, "process_id": identity[0], "captured": encode(capture.code),
            "current_calls": count, "status": category, "body_key": item["body_key"] if item is not None else None,
            "binding_locator": {"artifact": {"uri": str(bindings_path), **bindings_receipt}, "pointer": f"#/bindings/{ordinal}"}}
        groups.append(group)
        group_counts[category] += 1
        call_counts[category] += count
    _need(len(groups) == report["summary"]["entered_code_groups"], "current group denominator differs")
    _need(sum(call_counts.values()) == report["summary"]["invocations"], "current call denominator differs")
    # Lexical metadata determines structural depth; no qualname/name rule.
    declarations = {(row["file_index"], row["definition"]["id"]["wire"]): row for row in bodies}
    def depth(item):
        count, seen = 0, set()
        parent = item["definition"]["lexical_owner"]
        while parent is not None:
            key = item["file_index"], parent["wire"]
            _need(key not in seen, "lexical metadata cycle")
            seen.add(key); count += 1
            owner = declarations.get(key)
            parent = owner["definition"]["lexical_owner"] if owner is not None else None
        return count
    candidates = [row for row in bodies if row["metadata_status"] == "PENDING_CODE_RESOLVE"]
    candidates.sort(key=lambda row: (not bool(row["current_groups"]), depth(row), -row["current_calls"], row["body_key"]))
    dispatch_candidates = candidates
    if eligible_body_keys is not None:
        eligible = frozenset(eligible_body_keys)
        _need(eligible.issubset(by_key), "eligible_body_keys contains an unknown qualified body key")
        dispatch_candidates = [row for row in candidates if row["body_key"] in eligible]
        dispatch_candidates.sort(key=lambda row: (-row["current_calls"], depth(row), row["body_key"]))
    dispatch, files = [], set()
    for item in dispatch_candidates:
        if len(dispatch) == budget.max_dispatch_bodies:
            break
        if item["file_index"] not in files and len(files) == budget.max_source_files:
            continue
        files.add(item["file_index"])
        dispatch.append({"body_key": item["body_key"], "file_index": item["file_index"], "body_index": item["body_index"],
                         "code_key": item["code_variants"][0]["captured"]["key"]})
    document = {"schema": "scar.source-frontend-worklist", "schema_version": 1,
        "composition_inputs": inputs, "code_source_origin": composition.original_code_source_origin(),
        "current_report": {"path": str(report_path), **report_receipt},
        "current_bindings": {"path": str(bindings_path), **bindings_receipt}, "run": report["run"],
        "code_witness_store": store_receipt, "capabilities": encode(capabilities), "profile": "STRUCTURED_ENV_V1",
        "budget": asdict(budget), "producer": _producer(),
        "summary": {"source_files": composition.inventory_file_count, "bodies": len(bodies),
            "body_statuses": dict(status_counts), "metadata_statuses": dict(Counter(row["metadata_status"] for row in bodies)),
            "current_groups": len(groups), "current_calls": sum(call_counts.values()),
            "group_statuses": dict(group_counts), "call_statuses": dict(call_counts),
            "metadata_candidates": len(candidates), "dispatched_bodies": len(dispatch), "dispatched_files": len(files)},
        "code_type_verified_during_planning": False, "target_executed": False, "first_stage_complete": False}
    if eligible_body_keys is not None:
        document["selection"] = {"kind": "EXPLICIT_QUALIFIED_BODY_KEYS",
            "eligible_body_keys": sorted(eligible_body_keys),
            "eligible_pending_candidates": len(dispatch_candidates),
            "dispatch_priority": "CURRENT_CALLS_DESC_THEN_LEXICAL_DEPTH_THEN_BODY_KEY",
            "worker_order": "EXISTING_PER_FILE_CONTEXT_GROUPING",
            "full_catalog_and_call_denominators_preserved": True}
    digest = _hash({"document": document, "bodies": bodies, "groups": groups, "dispatch": dispatch})
    plan = SourceFrontendPlan(composition, document, tuple(bodies), tuple(groups), tuple(dispatch), digest)
    if out_dir is not None:
        output = Path(out_dir).resolve()
        _need(not output.exists(), "plan output already exists")
        output.mkdir(parents=True, exist_ok=False)
        try:
            tables = {name: _write_rows(output, name + '.json.gz', values, budget.max_record_bytes)
                      for name, values in (("bodies", bodies), ("groups", groups), ("dispatch", dispatch))}
            (output / "manifest.json").write_text(json.dumps({
                "schema": "scar.source-frontend-worklist-partitions", "schema_version": 1,
                "document": document, "tables": tables, "plan_sha256": digest}, indent=2) + "\n")
        except BaseException as error:
            (output / 'failure.json').write_bytes(_bytes({'status': 'BUILDING_FAILED_RETAINED',
                'type': type(error).__name__, 'detail': str(error), 'plan_sha256': digest}) + b'\n')
            raise
    return plan


def _resume_records(paths, *, max_bytes):
    records = {}
    for path in paths:
        path = Path(path).resolve()
        index = path / "attempts.jsonl" if path.is_dir() else path
        _need(index.is_file() and not index.is_symlink() and index.stat().st_size <= max_bytes, "resume index is missing or oversized")
        with index.open() as stream:
            for line in stream:
                row = json.loads(line)
                _need(row.get("schema") == "scar.source-frontend-attempt" and row.get("schema_version") == 1,
                      "unknown resume attempt schema")
                if row["status"] not in _TERMINAL:
                    continue
                _need(row["work_key"] == _hash(row["work_input"]), "resume work key differs from its exact inputs")
                result_ref = row["result_artifact"]
                actual_result = _receipt(result_ref['path'])
                _need(actual_result == result_ref, "resume original terminal record SHA/size differs")
                original = json.loads(Path(result_ref['path']).read_text())
                _need(original == {key: value for key, value in row.items() if key != 'result_artifact'},
                      "resume index changed its original terminal record")
                if row["status"] == "SUCCEEDED":
                    artifact = row["program"]
                    actual = _receipt(artifact["uri"])
                    _need(actual["sha256"] == artifact["physical_sha256"] and actual["bytes"] == artifact["physical_bytes"],
                          "resumed successful source artifact changed")
                key = row["work_key"]
                _need(key not in records or records[key] == row, "conflicting resume results for one exact work key")
                records[key] = row
    return records


def run_source_frontend(plan, code_witnesses, out_dir, *, budget=SourceFrontendBudget(), resume_from=(), progress=None,
                        shared_context=False):
    """Run a bounded preplanned window, retaining every actual attempt.

    Same-input failures are skipped through explicit immutable resume indexes.
    Changed capabilities/compiler/source/producer/budget produce a different key.
    """
    if type(plan) is SourceEntryFrontendPlan:
        _need(not resume_from, "entry v2 resume requires a fresh explicit plan/attempt")
        _need(code_witnesses is plan.catalog.archives, "entry worker requires its explicitly admitted archives")
        return run_source_entries(plan, out_dir, budget=budget, progress=progress, shared_context=shared_context)
    _need(shared_context is False, 'shared context output requires the qualified entry worker')
    _need(type(plan) is SourceFrontendPlan and type(budget) is SourceFrontendBudget, "regular worklist and independent worker budget required")
    plan.require_unchanged()
    budget.__post_init__()
    requested = SourceFrontendBudget(**plan.document["budget"])
    _need(all(getattr(requested, name) <= getattr(budget, name) for name in asdict(budget)), "plan exceeds independent worker ceiling")
    _need(_check_store(code_witnesses) == plan.document["code_witness_store"], "owned witness archive differs from plan")
    _need(_producer() == plan.document["producer"], "frontend implementation changed; regenerate worklist")
    _need(len(plan.dispatch) <= requested.max_dispatch_bodies
          and len({row['file_index'] for row in plan.dispatch}) <= requested.max_source_files,
          "dispatch window exceeds independent worker ceilings")
    output = Path(out_dir).resolve()
    _need(not output.exists(), "worker output already exists")
    output.mkdir(parents=True, exist_ok=False)
    resumed = _resume_records(resume_from, max_bytes=requested.max_record_bytes)
    body_index = {row["body_key"]: row for row in plan.bodies}
    started, charged, source_bytes, output_bytes = time.perf_counter(), 0, 0, 0
    store_before = dict(code_witnesses.counts)
    counts, program_paths, file_stats = Counter(), [], {}
    index = (output / "attempts.jsonl").open('x', buffering=1)
    active_file = context = session = None
    source_failures = {}

    def persist(row):
        nonlocal output_bytes
        payload = _bytes(row) + b'\n'
        output_bytes += len(payload)
        index.write(payload.decode())
        index.flush()
        counts[row["status"]] += 1
        _need(output_bytes <= requested.max_output_bytes, "worker output byte budget exhausted; terminal record retained")
        if progress is not None:
            progress({"stage": "frontend_attempt", "status": row["status"], "body_key": row["body_key"]})

    try:
        # File grouping ensures one context/AST per admitted file without
        # retaining all source graphs at once. Initial priority orders files.
        grouped = defaultdict(list)
        for item in plan.dispatch:
            grouped[item["file_index"]].append(item)
        sequence, stopped = 0, False
        for fi, entries in grouped.items():
            for item in entries:
                if time.perf_counter() - started >= requested.max_elapsed_seconds or charged >= requested.max_total_operations:
                    counts["WINDOW_BUDGET_STOP"] += 1
                    stopped = True
                    break
                body = body_index[item["body_key"]]
                allocation = min(requested.max_operations_per_body, requested.max_total_operations - charged)
                work_input = {"snapshot": body["snapshot"], "context": body["context"],
                    "definition": body["definition"]["id"], "source": body["definition"]["source"],
                    "captured": body["code_variants"][0]["captured"], "capabilities": plan.document["capabilities"],
                    "profile": plan.document["profile"], "producer": plan.document["producer"],
                    "code_source_origin": plan.document["code_source_origin"],
                    "code_witness_store": plan.document["code_witness_store"], "operation_budget": allocation}
                key = _hash(work_input)
                if key in resumed:
                    counts["RESUMED_" + resumed[key]["status"]] += 1
                    if resumed[key]["status"] == "SUCCEEDED":
                        program_paths.append(resumed[key]["program"]["uri"])
                    continue
                sequence += 1
                attempt = output / f'attempt-{sequence:05d}'
                attempt.mkdir(exist_ok=False)
                row = {"schema": "scar.source-frontend-attempt", "schema_version": 1, "sequence": sequence,
                    "body_key": body["body_key"], "work_key": key, "work_input": work_input,
                    "body_locator": body["body_locator"], "status": "STARTED", "program": None,
                    "operations_emitted": None, "graph_operations": None, "budget_charge": None,
                    "construction_cost_known": False, "code_type_verified": False,
                    "target_executed": False, "first_stage_complete": False}
                (attempt / 'started.json').write_bytes(_bytes(row) + b'\n')
                tick, result, lower_started = time.perf_counter(), None, False
                try:
                    captured = decode(CapturedCode, work_input["captured"])
                    evidence = SourceCodeEvidence(code_witnesses, plan.composition, captured)
                    row['code_type_verified'] = True
                    row['code_witness'] = evidence.to_dict()
                    row['ready_state'] = 'READY_VERIFIED_CODE'
                    (attempt / 'ready.json').write_bytes(_bytes(row) + b'\n')
                    if active_file != fi:
                        _need(fi not in source_failures, "source context has a retained failure in this window: " + str(source_failures.get(fi)))
                        _need(len(file_stats) < requested.max_source_files, "worker source-file ceiling exceeded")
                        view = plan.composition.source(fi)
                        snapshot = decode(SourceSnapshot, body["snapshot"])
                        _need(view.snapshot == snapshot and encode(view.context) == body["context"], "cached source context differs")
                        text = code_witnesses.text(snapshot)
                        source_bytes += len(text.encode())
                        _need(source_bytes <= requested.max_source_bytes, "worker decoded source-byte budget exhausted")
                        tree = ast.parse(text, filename=snapshot.path)
                        context = PreparedSource(Path(snapshot.path), Path(view.context.namespace_root), text,
                            view.semantic, view.semantics, view.control, tree, _symbol_tables(text, snapshot.path))
                        session = context.seal_for_lowering()
                        active_file = fi
                        file_stats[str(fi)] = {"context_loads": 1, "ast_parses": 1, "symtable_parses": 1,
                            "source_prepare_attempts": 0, "decoded_source_bytes": len(text.encode())}
                    definition = decode(DefinitionInventory, body["definition"])
                    evidence.require_definition(decode(SourceSnapshot, body["snapshot"]), definition.id, definition.source)
                    options = SourceLanguageOptions(tuple(SourceLanguageCapability(value) for value in work_input["capabilities"]), evidence)
                    lower_started = True
                    result = session.lower(definition.qualname, source=definition.source,
                        max_operations=allocation, expand_candidates=False,
                        profile=BodyLoweringProfile.STRUCTURED_ENV, language_options=options)
                    row['operations_emitted'] = result.operations_emitted
                    row['construction_cost_known'] = True
                    row['budget_charge'] = result.operations_emitted
                    row['graph_operations'] = len(result.graph.operations) if result.graph is not None else 0
                    # Persist the actual lowerer-return metadata immediately,
                    # before any potentially large source-program serialization.
                    returned = {'schema': 'scar.source-frontend-lowered-return', 'schema_version': 1,
                        'metadata': encode(result.metadata), 'interface': encode(result.interface), 'frame': encode(result.frame),
                        'structured': encode(result.structured), 'language': encode_language_overlay(result.language) if result.language is not None else None,
                        'operations_emitted': result.operations_emitted, 'graph_present': result.graph is not None,
                        'graph_artifact': None, 'whole_program_established': False}
                    (attempt / 'returned-metadata.json').write_bytes(_bytes(returned) + b'\n')
                    if result.graph is None:
                        row['status'] = 'UNSUPPORTED'
                    else:
                        program = SourceProgram(result.graph, result.metadata, context.semantic, context.semantics,
                            context.control, BodyLoweringProfile.STRUCTURED_ENV, result.interface,
                            result.frame, result.structured, result.language)
                        ref = _write_shard(attempt, 'source-program5.json.gz', program.to_dict(), limit=requested.max_record_bytes)
                        ref = {**ref, 'uri': str(attempt / ref['uri']), 'external': True}
                        row['program'] = ref
                        output_bytes += ref['physical_bytes']
                        returned['graph_artifact'] = {'artifact': ref, 'pointer': '#/graph'}
                        (attempt / 'lowered-return.json').write_bytes(_bytes(returned) + b'\n')
                        row['status'] = 'SUCCEEDED'
                        program_paths.append(ref['uri'])
                except Exception as error:
                    row['status'] = 'FAILED'
                    if not row['code_type_verified']:
                        row['status'] = 'CODE_WITNESS_UNAVAILABLE'
                    elif context is None or active_file != fi:
                        row['status'] = 'SOURCE_CONTEXT_UNAVAILABLE'
                        source_failures.setdefault(fi, {'type': type(error).__name__, 'detail': str(error)})
                    row['error'] = {'type': type(error).__name__, 'detail': str(error), 'traceback': traceback.format_exc()}
                    if result is None:
                        row['budget_charge'] = allocation if lower_started else 0
                charged += row['budget_charge']
                row['elapsed_s'] = time.perf_counter() - tick
                (attempt / 'result.json').write_bytes(_bytes(row) + b'\n')
                persist({**row, 'result_artifact': _receipt(attempt / 'result.json')})
            active_file = context = session = None
            if stopped:
                break
        _need(_producer() == plan.document['producer'], "frontend source changed during worker")
        plan.require_unchanged()
        _need(_check_store(code_witnesses) == plan.document['code_witness_store'], "owned witness archive changed")
        summary = {'schema': 'scar.source-frontend-result', 'schema_version': 1, 'status': 'FINISHED_WITH_OPEN',
            'plan_sha256': plan.digest, 'counts': dict(counts), 'program_paths': program_paths,
            'original_static_bodies': len(plan.bodies), 'original_current_groups': len(plan.groups),
            'original_current_calls': plan.document['summary']['current_calls'],
            'source_files': file_stats, 'budget_operation_charge': charged, 'decoded_source_bytes': source_bytes,
            'code_witness_counts': {name: code_witnesses.counts[name] - store_before[name] for name in store_before},
            'elapsed_s': time.perf_counter() - started, 'source_prepare_attempts': 0, 'target_executed': False,
            'current_run_integrated': False, 'first_stage_complete': False}
        (output / 'manifest.json').write_bytes(_bytes(summary) + b'\n')
        return summary
    except BaseException as error:
        (output / 'failure.json').write_bytes(_bytes({'status': 'BUILDING_FAILED_RETAINED', 'type': type(error).__name__,
            'detail': str(error), 'traceback': traceback.format_exc(), 'plan_sha256': plan.digest}) + b'\n')
        raise
    finally:
        index.close()


def _entry_producer():
    result = _producer()
    directory = Path(__file__).resolve().parent
    return result + [_receipt(directory / name) for name in
                     ('source_entry_catalog.py', 'source_attachments.py', 'source_layers.py', 'compiler_witness_archives.py')] + [
                         _receipt(directory.parent / 'store/source_fragments.py')]


@dataclass(frozen=True)
class SourceEntryFrontendPlan:
    catalog: object
    document: dict
    entries: tuple[dict, ...]
    groups: tuple[dict, ...]
    dispatch: tuple[dict, ...]
    digest: str

    def require_unchanged(self):
        from scar.analysis.source_entry_catalog import SourceEntryCatalog
        _need(type(self.catalog) is SourceEntryCatalog and self.digest == _hash({
            'document': self.document, 'entries': self.entries, 'groups': self.groups, 'dispatch': self.dispatch}),
            'entry plan mutated')
        _need(self.catalog.inputs() == self.document['catalog_inputs'], 'entry source/archive inputs changed')


SOURCE_ENTRY_PROFILE_314_V2 = 'PYTHON_SOURCE_ENTRY_314_CAPS_V2'
SOURCE_ENTRY_PROFILE_314_V3 = 'PYTHON_SOURCE_ENTRY_314_CAPS_V3'
SOURCE_ENTRY_PROFILE_314_V4 = 'PYTHON_SOURCE_ENTRY_314_CAPS_V4'
SOURCE_ENTRY_PROFILE_314_V5 = 'PYTHON_SOURCE_ENTRY_314_CAPS_V5'
SOURCE_ENTRY_PROFILE_314_V6 = 'PYTHON_SOURCE_ENTRY_314_CAPS_V6'
SOURCE_ENTRY_PROFILE_314_V7 = 'PYTHON_SOURCE_ENTRY_314_CAPS_V7'
SOURCE_ENTRY_PROFILE_314_V8 = 'PYTHON_SOURCE_ENTRY_314_CAPS_V8'
SOURCE_ENTRY_PROFILE_314_V9 = 'PYTHON_SOURCE_ENTRY_314_CAPS_V9'
SOURCE_ENTRY_PROFILES = (SOURCE_ENTRY_PROFILE_314_V2, SOURCE_ENTRY_PROFILE_314_V3, SOURCE_ENTRY_PROFILE_314_V4, SOURCE_ENTRY_PROFILE_314_V5, SOURCE_ENTRY_PROFILE_314_V6, SOURCE_ENTRY_PROFILE_314_V7, SOURCE_ENTRY_PROFILE_314_V8,SOURCE_ENTRY_PROFILE_314_V9)
LATEST_SOURCE_ENTRY_PROFILE = SOURCE_ENTRY_PROFILE_314_V9


def plan_source_entries(catalog, *, budget=SourceFrontendBudget(), capabilities=(
        SourceLanguageCapability.FIXED_UNPACK, SourceLanguageCapability.SLICE_KEYS,
        SourceLanguageCapability.LEXICAL_LOCALS, SourceLanguageCapability.CALL_KWARGS_314_V1), out_dir=None,
        dispatch_order='CALL_WEIGHT_DESC_V1', eligible_entry_keys=None, automatic_function_try=False,
        automatic_call_expansion=False, automatic_nested_functions=False, source_entry_profile=None):
    """Select by call weight, optionally batch the selected entries by file.

    Batching changes only analysis scheduling. It preserves window membership,
    original entry identities and all ordinary source/compiler checks.
    Optional explicit ready-entry keys narrow only dispatch; the complete
    candidate/group catalogs and their denominators remain unchanged.
    The versioned V2 entry profile selects implemented Try, expanded-call,
    nested-function and import capabilities from the exact original function
    AST during the worker, after normal entry/readonly CodeWitness resolution.
    It is a selection policy, not a source/runtime proof. None preserves the
    historical plan fields and capability-selection behavior.
    V3 also selects synchronous With; V4 additionally selects the existing
    generator-expression capability, whose consumer/propagation limits remain.
    V5 selects independent generator creation instead of the fixed-unpack
    drive policy; unknown consumers remain ordinary incomplete world calls.
    V6 additionally selects ordered non-starred set display construction and
    the existing function protocol for AugAssign (heap targets stay unsupported).
    V7 additionally connects fixed unpack results to original heap/cell targets.
    V8 additionally selects original Lambda creation/expression-body Regions and
    witnessed non-scalar code constants from the exact definition-time AST.
    """
    from scar.analysis.source_entry_catalog import SourceEntryCatalog
    _need(type(catalog) is SourceEntryCatalog and type(budget) is SourceFrontendBudget,
          'original entry catalog and independent frontend budget required')
    _need(type(dispatch_order) is str and dispatch_order in ('CALL_WEIGHT_DESC_V1', 'FILE_GROUPED_V1'),
          'unsupported source-entry analysis dispatch order')
    budget.__post_init__()
    _need(type(automatic_function_try) is bool, 'automatic_function_try must be an explicit bool')
    _need(type(automatic_call_expansion) is bool, 'automatic_call_expansion must be an explicit bool')
    _need(type(automatic_nested_functions) is bool, 'automatic_nested_functions must be an explicit bool')
    _need(source_entry_profile is None or type(source_entry_profile) is str
          and source_entry_profile in SOURCE_ENTRY_PROFILES, 'unknown versioned source-entry profile')
    SourceLanguageOptions(capabilities)
    if eligible_entry_keys is not None:
        _need(type(eligible_entry_keys) is tuple and bool(eligible_entry_keys)
              and all(type(key) is str and bool(key) for key in eligible_entry_keys)
              and len(set(eligible_entry_keys)) == len(eligible_entry_keys),
              'eligible_entry_keys must be an explicit nonempty tuple of unique nonempty strings')
    metadata = catalog.metadata()
    entries, groups = tuple(metadata['candidates']), tuple(metadata['groups'])
    _need(len(entries) <= budget.max_catalog_bodies and len(groups) <= budget.max_catalog_groups,
          'full entry catalog exceeds budget')
    eligible = None
    if eligible_entry_keys is not None:
        eligible = frozenset(eligible_entry_keys)
        ready_keys = {entry['entry_key'] for entry in entries
                      if entry['status'] == 'CANDIDATE_SOURCE_GRAPH_UNVERIFIED'}
        _need(eligible.issubset(ready_keys),
              'eligible_entry_keys contains an unknown or non-ready qualified entry key')
    dispatch, files = [], set()
    for entry in entries:
        if entry['status'] != 'CANDIDATE_SOURCE_GRAPH_UNVERIFIED':
            continue
        if eligible is not None and entry['entry_key'] not in eligible:
            continue
        if len(dispatch) >= budget.max_dispatch_bodies:
            break
        if entry['file_key'] not in files and len(files) >= budget.max_source_files:
            continue
        dispatch.append(entry)
        files.add(entry['file_key'])
    if dispatch_order == 'FILE_GROUPED_V1':
        by_file = {}
        for entry in dispatch:
            by_file.setdefault(entry['file_key'], []).append(entry)
        dispatch = [entry for group in by_file.values() for entry in group]
    document = {'schema': 'scar.source-frontend-plan', 'schema_version': 2,
        'catalog_inputs': catalog.inputs(), 'budget': asdict(budget), 'producer': _entry_producer(),
        'profile': BodyLoweringProfile.STRUCTURED_ENV.value, 'capabilities': [x.value for x in capabilities],
        'selection': 'qualified original entry candidates, actual call weight descending; bounded window',
        'summary': {'candidate_entries': len(entries), 'current_groups': len(groups),
                    'current_calls': metadata['entered_invocations'], 'dispatch_entries': len(dispatch)},
        'source_body_publication': 'NOT_RUN', 'runtime_binding': 'NOT_RUN', 'first_stage_complete': False}
    if automatic_function_try:
        document['function_try_policy'] = 'AUTOMATIC_ORIGINAL_FUNCTION_AST_314_V1'
    if automatic_call_expansion:
        document['call_expansion_policy'] = 'AUTOMATIC_ORIGINAL_CALL_EXPANSION_AST_314_V1'
    if automatic_nested_functions:
        document['nested_function_policy'] = 'AUTOMATIC_ORIGINAL_FUNCTION_DEFINITION_AST_314_V1'
    if source_entry_profile is not None:
        document['source_entry_profile'] = source_entry_profile
    if dispatch_order == 'FILE_GROUPED_V1':
        document['dispatch_order'] = dispatch_order
    if eligible_entry_keys is not None:
        keys = sorted(eligible_entry_keys)
        document['selection'] = {'kind': 'EXPLICIT_QUALIFIED_ENTRY_KEYS',
            'eligible_entry_keys': keys, 'eligible_entry_keys_sha256': _hash(keys),
            'eligible_ready_candidates': len(keys), 'dispatch_priority': 'CALL_WEIGHT_DESC_V1',
            'dispatch_order': dispatch_order, 'full_catalog_and_call_denominators_preserved': True}
    digest = _hash({'document': document, 'entries': entries, 'groups': groups, 'dispatch': tuple(dispatch)})
    result = SourceEntryFrontendPlan(catalog, document, entries, groups, tuple(dispatch), digest)
    if out_dir is not None:
        root = Path(out_dir).resolve()
        _need(not root.exists(), 'entry plan output must be fresh')
        root.mkdir(parents=True)
        for name, rows in (('entries', entries), ('groups', groups), ('dispatch', dispatch)):
            _write_rows(root, name + '.json.gz', rows, budget.max_record_bytes)
        (root / 'plan.json').write_bytes(_bytes({**document, 'plan_sha256': digest}) + b'\n')
    return result


def _entry_language_capabilities(plan, entry, context, capabilities):
    policy=plan.document.get('function_try_policy')
    call_policy=plan.document.get('call_expansion_policy')
    nested_policy=plan.document.get('nested_function_policy')
    profile=plan.document.get('source_entry_profile')
    _need(profile is None or type(profile) is str and profile in SOURCE_ENTRY_PROFILES,
          'unknown versioned source-entry profile')
    automatic=profile in SOURCE_ENTRY_PROFILES
    if policy is None and call_policy is None and nested_policy is None and not automatic:
        return capabilities
    _need(policy in(None,'AUTOMATIC_ORIGINAL_FUNCTION_AST_314_V1')
          and call_policy in(None,'AUTOMATIC_ORIGINAL_CALL_EXPANSION_AST_314_V1')
          and nested_policy in(None,'AUTOMATIC_ORIGINAL_FUNCTION_DEFINITION_AST_314_V1'),
          'unknown automatic source capability policy')
    import ast
    source=entry.reference.source
    span=(source.start_line,source.end_line,source.start_column,source.end_column)
    nodes=[n for n in ast.walk(context.tree)if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))
        and(n.lineno,n.end_lineno,n.col_offset,n.end_col_offset)==span]
    _need(len(nodes)==1,'automatic function policy needs the exact original function AST')
    definitions=[]
    def own_nodes(node):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            definitions.append(node)
            for child in (*node.decorator_list,*node.args.defaults,*(x for x in node.args.kw_defaults if x is not None)):
                yield from own_nodes(child)
            return
        if isinstance(node,ast.Lambda):
            if profile in (SOURCE_ENTRY_PROFILE_314_V8,SOURCE_ENTRY_PROFILE_314_V9):
                yield node
                for value in (*node.args.defaults,*(v for v in node.args.kw_defaults if v is not None)):
                    yield from own_nodes(value)
            return
        if isinstance(node,ast.ClassDef):return
        yield node
        for child in ast.iter_child_nodes(node):yield from own_nodes(child)
    own=tuple(n for root in nodes[0].body for n in own_nodes(root))
    with_scope=profile in (SOURCE_ENTRY_PROFILE_314_V3,SOURCE_ENTRY_PROFILE_314_V4,SOURCE_ENTRY_PROFILE_314_V5,SOURCE_ENTRY_PROFILE_314_V6,SOURCE_ENTRY_PROFILE_314_V7,SOURCE_ENTRY_PROFILE_314_V8,SOURCE_ENTRY_PROFILE_314_V9) and any(isinstance(n,ast.With)for n in own)
    augmented_scope=profile in (SOURCE_ENTRY_PROFILE_314_V6,SOURCE_ENTRY_PROFILE_314_V7,SOURCE_ENTRY_PROFILE_314_V8,SOURCE_ENTRY_PROFILE_314_V9) and any(isinstance(n,ast.AugAssign)for n in own)
    if ((automatic or policy is not None) and (any(isinstance(n,ast.Try)for n in own)or with_scope or augmented_scope)
            and SourceLanguageCapability.FUNCTION_TRY_314_V1 not in capabilities):
        capabilities+=(SourceLanguageCapability.FUNCTION_TRY_314_V1,)
    if ((automatic or call_policy is not None) and any(isinstance(n,ast.Call)and(
            any(isinstance(a,ast.Starred)for a in n.args)or any(k.arg is None for k in n.keywords))for n in own)
            and SourceLanguageCapability.CALL_EXPANSION_314_V1 not in capabilities):
        capabilities+=(SourceLanguageCapability.CALL_EXPANSION_314_V1,)
    if (automatic or nested_policy is not None) and definitions and SourceLanguageCapability.NESTED_FUNCTION_314_V1 not in capabilities:
        capabilities+=(SourceLanguageCapability.NESTED_FUNCTION_314_V1,)
    if automatic and any(isinstance(n,(ast.Import,ast.ImportFrom))for n in own) and SourceLanguageCapability.FUNCTION_IMPORT_314_V1 not in capabilities:
        capabilities+=(SourceLanguageCapability.FUNCTION_IMPORT_314_V1,)
    if with_scope and SourceLanguageCapability.FUNCTION_WITH_314_V1 not in capabilities:
        capabilities+=(SourceLanguageCapability.FUNCTION_WITH_314_V1,)
    if profile == SOURCE_ENTRY_PROFILE_314_V4 and any(isinstance(n,ast.GeneratorExp)for n in own) and SourceLanguageCapability.GENEXPR_314_V1 not in capabilities:
        capabilities+=(SourceLanguageCapability.GENEXPR_314_V1,)
    if profile in (SOURCE_ENTRY_PROFILE_314_V5,SOURCE_ENTRY_PROFILE_314_V6,SOURCE_ENTRY_PROFILE_314_V7,SOURCE_ENTRY_PROFILE_314_V8,SOURCE_ENTRY_PROFILE_314_V9) and any(isinstance(n,ast.GeneratorExp)for n in own) and SourceLanguageCapability.GENEXPR_CREATION_314_V1 not in capabilities:
        capabilities+=(SourceLanguageCapability.GENEXPR_CREATION_314_V1,)
    if profile in (SOURCE_ENTRY_PROFILE_314_V6,SOURCE_ENTRY_PROFILE_314_V7,SOURCE_ENTRY_PROFILE_314_V8,SOURCE_ENTRY_PROFILE_314_V9) and any(isinstance(n,ast.Set)for n in own) and SourceLanguageCapability.SET_DISPLAY_314_V1 not in capabilities:
        capabilities+=(SourceLanguageCapability.SET_DISPLAY_314_V1,)
    if profile in (SOURCE_ENTRY_PROFILE_314_V7,SOURCE_ENTRY_PROFILE_314_V8,SOURCE_ENTRY_PROFILE_314_V9) and any(isinstance(n,(ast.Tuple,ast.List))and isinstance(n.ctx,ast.Store)for n in own) and SourceLanguageCapability.UNPACK_TARGETS_314_V1 not in capabilities:
        capabilities+=(SourceLanguageCapability.UNPACK_TARGETS_314_V1,)
    if profile in (SOURCE_ENTRY_PROFILE_314_V8,SOURCE_ENTRY_PROFILE_314_V9) and any(isinstance(n,ast.Lambda)for n in own) and SourceLanguageCapability.LAMBDA_EXPRESSION_314_V1 not in capabilities:
        capabilities+=(SourceLanguageCapability.LAMBDA_EXPRESSION_314_V1,)
    if profile in (SOURCE_ENTRY_PROFILE_314_V8,SOURCE_ENTRY_PROFILE_314_V9):
        from scar.analysis.source_constant_lowering import needs_code_constant
        if (any(needs_code_constant(node) for node in own)
                and SourceLanguageCapability.CODE_CONSTANTS_314_V1 not in capabilities):
            capabilities += (SourceLanguageCapability.CODE_CONSTANTS_314_V1,)
    if (profile == SOURCE_ENTRY_PROFILE_314_V9 and any(isinstance(n,(ast.ListComp,ast.SetComp,ast.DictComp))for n in own)
            and SourceLanguageCapability.COMPREHENSION_314_V1 not in capabilities):
        capabilities += (SourceLanguageCapability.COMPREHENSION_314_V1,)
    return capabilities


_OWNED_ENTRY_RETURN = object()


class _OwnedEntryReturn:
    """Live worker provenance; JSON is never accepted as its constructor input."""
    def __init__(self, seal, entry, context, result, evidence, work_key):
        _need(seal is _OWNED_ENTRY_RETURN, 'owned return is minted only at the worker lower call')
        self.entry, self.context, self.result, self.evidence, self.work_key = entry, context, result, evidence, work_key
        self._objects = tuple(getattr(result, name) for name in ('graph', 'metadata', 'interface', 'frame', 'structured', 'language'))
        self._cost = result.operations_emitted
        self._seal = seal
        self.program_reference = None
        self._bound_reference_json = None
        self._program_digest = None

    def require_unchanged(self):
        _need(self._seal is _OWNED_ENTRY_RETURN and all(getattr(self.result, name) is original for name, original in
              zip(('graph', 'metadata', 'interface', 'frame', 'structured', 'language'), self._objects))
              and type(self.result.operations_emitted) is int and self.result.operations_emitted == self._cost,
              'actual lowerer-return object identity/cost changed')
        self.entry._owner.require_entry(self.entry)
        _need(self._bound_reference_json is None or self._bound_reference_json == _bytes(self.program_reference),
              'owned original artifact reference changed')
        if self._program_digest is not None:
            _need(_hash(self.program().to_dict()) == self._program_digest, 'owned return fields changed after serialization')

    def program(self):
        r = self.result
        return SourceProgram(r.graph, r.metadata, self.context.semantic, self.context.semantics,
            self.context.control, BodyLoweringProfile.STRUCTURED_ENV, r.interface, r.frame, r.structured, r.language)

    def record(self):
        self.require_unchanged()
        r = self.result
        return {'schema': 'scar.source-frontend-lowered-return', 'schema_version': 2,
            'entry_reference': encode(self.entry.reference), 'code_source_origin': self.entry.origin,
            'work_key': self.work_key, 'metadata': encode(r.metadata), 'interface': encode(r.interface),
            'frame': encode(r.frame), 'structured': encode(r.structured), 'language': encode_language_overlay(r.language) if r.language is not None else None,
            'operations_emitted': r.operations_emitted, 'graph_present': r.graph is not None,
            'graph_artifact': self.program_reference, 'live_owner_restored_by_record': False,
            'normal_publication_checkpoint': 'CP2_UNKNOWN_COST_NOT_YET_PUBLISHED', 'whole_program_established': False}


def _lower_and_capture_entry(session, entry, context, evidence, capabilities, allocation, work_key):
    # The result is produced here. There is deliberately no input accepting a
    # purported LoweredSourceBody, serialized success flag or materialized CP1.
    evidence.require_definition(entry.reference.snapshot, entry.reference.definition, entry.reference.source)
    options = SourceLanguageOptions(capabilities, evidence)
    result = session.lower(entry.captured.qualname.replace('.<locals>.', '.'), source=entry.reference.source,
        max_operations=allocation, expand_candidates=False, profile=BodyLoweringProfile.STRUCTURED_ENV,
        language_options=options)
    _need(type(result.operations_emitted) is int and 0 <= result.operations_emitted <= allocation
          and result.metadata.source == entry.reference.snapshot, 'actual return source/cost differs')
    if result.graph is not None:
        _need(result.interface is not None and result.interface.definition == entry.reference.definition
              and result.structured is not None and result.structured.source == entry.reference.source,
              'actual return has a different original definition/source')
    return _OwnedEntryReturn(_OWNED_ENTRY_RETURN, entry, context, result, evidence, work_key)


@dataclass(frozen=True)
class SourceEntryFrontendResult:
    document: dict
    owned_returns: tuple[object, ...]
    digest: str

    def require_unchanged(self):
        _need(self.digest == _hash(self.document), 'entry result accounting mutated')
        for item in self.owned_returns:
            _need(type(item) is _OwnedEntryReturn, 'result contains a foreign owned return')
            item.require_unchanged()


class _EntryProgramArchive:
    """Storage adapter only: original public SP5 receipts remain reconstructible."""
    def __init__(self, directory, budget):
        from scar.store.source_fragments import SourceFragmentBudget, SourceFragmentWriter
        self.directory = Path(directory).resolve()
        self.writer = SourceFragmentWriter(self.directory, budget=SourceFragmentBudget(
            max_stored_input_bytes=budget.max_output_bytes * 2,
            max_decoded_input_bytes=budget.max_record_bytes * budget.max_dispatch_bodies,
            max_record_bytes=budget.max_record_bytes, max_output_bytes=budget.max_output_bytes,
            max_contexts=budget.max_source_files, max_operations=budget.max_operations_per_body,
            seconds=budget.max_elapsed_seconds))
        self.originals = []

    def publish(self, reference, *, namespace_root=None):
        from scar.ir.program.providers import ProviderArtifact
        from scar.ir.program.source_references import SourceArtifactLocator
        _need(reference.get('representation') == 'scar.source-program/5' and reference.get('external') is True,
              'shared entry storage requires the original exact SP5 receipt')
        original = SourceArtifactLocator(ProviderArtifact(reference['uri'], reference['physical_sha256'],
            reference['physical_bytes'], reference['representation']), reference['decoded_sha256'],
            reference['decoded_bytes'], 'gzip-canonical-json' if Path(reference['uri']).suffix == '.gz' else 'canonical-json')
        fragment = self.writer.write(original, namespace_root=namespace_root)
        self.originals.append(original)
        return {'uri': fragment.artifact.uri, 'external': True, 'representation': fragment.artifact.schema,
            'physical_sha256': fragment.artifact.sha256, 'physical_bytes': fragment.artifact.size_bytes,
            'decoded_sha256': fragment.decoded_sha256, 'decoded_bytes': fragment.decoded_bytes}

    def finish(self, *, retire_fresh_originals=False):
        costs = self.writer.finish()
        # Never retire prior inputs. Only this new worker's exact attempt files
        # may be removed after all original receipt/EOF/input guards pass.
        if retire_fresh_originals:
            for original in self.originals:
                path = Path(original.artifact.uri)
                _need(path.parent.parent == self.directory.parent and path.name == 'source-program5.json.gz'
                      and path.parent.name.startswith('attempt-'), 'cannot retire an existing external SP5 input')
            for original in self.originals:
                Path(original.artifact.uri).unlink()
        return {**costs, 'original_sp5_records': len(self.originals),
                'fresh_sp5_copies_retired': len(self.originals) if retire_fresh_originals else 0,
                'qualification': 'same SP5 receipt reconstructed by fragment plus context; no new graph authority'}


def run_source_entries(plan, out_dir, *, budget=SourceFrontendBudget(), progress=None, shared_context=False):
    """Normal sealed lowering and ordinary SP5/code readback, no publication."""
    from scar.analysis.code_witness import CodeWitnessUnavailable
    from scar.analysis.structured_lowering import require_valid_structured_body
    _need(type(plan) is SourceEntryFrontendPlan and type(budget) is SourceFrontendBudget,
          'entry v2 plan and independent worker budget required')
    _need(type(shared_context) is bool, 'shared context output must be an explicit bool')
    plan.require_unchanged()
    budget.__post_init__()
    requested = SourceFrontendBudget(**plan.document['budget'])
    _need(all(getattr(requested, key) <= getattr(budget, key) for key in asdict(budget)), 'entry plan exceeds worker ceilings')
    _need(_entry_producer() == plan.document['producer'], 'entry worker producer changed')
    root = Path(out_dir).resolve()
    _need(not root.exists(), 'entry worker output must be fresh')
    root.mkdir(parents=True)
    started, charged, source_bytes, output_bytes = time.perf_counter(), 0, 0, 0
    owned_returns, rows, file_stats = [], [], {}
    archive = _EntryProgramArchive(root / 'source-fragments', requested) if shared_context else None
    capabilities = tuple(SourceLanguageCapability(x) for x in plan.document['capabilities'])
    active_file = context = session = None
    index = (root / 'attempts.jsonl').open('x', buffering=1)
    try:
        for ordinal, candidate in enumerate(plan.dispatch, 1):
            if charged >= requested.max_total_operations or time.perf_counter() - started >= requested.max_elapsed_seconds:
                break
            allocation = min(requested.max_operations_per_body, requested.max_total_operations - charged)
            folder = root / f'attempt-{ordinal:05d}'
            folder.mkdir()
            row = {'schema': 'scar.source-frontend-attempt', 'schema_version': 2,
                'entry_key': candidate['entry_key'], 'source_calls': candidate['calls'], 'status': 'STARTED',
                'program': None, 'operations_emitted': None, 'budget_charge': 0, 'construction_cost_known': False,
                'public_structure_reader': False, 'independent_code_reader': False, 'publication': 'NOT_RUN',
                'target_executed': False, 'first_stage_complete': False}
            work = {'plan': plan.digest, 'entry': candidate, 'allocation': allocation}
            if shared_context:
                work['program_storage'] = 'SHARED_SOURCE_CONTEXT_V1'
                row['program_storage'] = 'SHARED_SOURCE_CONTEXT_V1'
            row['work_key'] = _hash(work)
            (folder / 'started.json').write_bytes(_bytes(row) + b'\n')
            lower_started, owned = False, None
            try:
                entry = plan.catalog.resolve(candidate['entry_key'])
                evidence = SourceCodeEvidence.from_entry(plan.catalog, entry)
                row['code_witness'] = evidence.to_dict()
                if active_file != entry.file_key:
                    _need(len(file_stats) < requested.max_source_files, 'worker source-file ceiling exceeded')
                    context = plan.catalog.prepare(entry)
                    source_bytes += len(context.text.encode())
                    _need(source_bytes <= requested.max_source_bytes, 'worker decoded source-byte ceiling exceeded')
                    session = context.seal_for_lowering()
                    active_file = entry.file_key
                    file_stats[active_file] = {'context_builds': 1, 'sealed_sessions': 1,
                        'source_prepare_attempts': 0, 'decoded_source_bytes': len(context.text.encode())}
                active_capabilities=_entry_language_capabilities(plan,entry,context,capabilities)
                if any(plan.document.get(field) is not None for field in ('function_try_policy','call_expansion_policy','nested_function_policy','source_entry_profile')):
                    row['active_capabilities']=[c.value for c in active_capabilities]
                lower_started = True
                owned = _lower_and_capture_entry(session, entry, context, evidence, active_capabilities, allocation, row['work_key'])
                owned_returns.append(owned)
                owned._attempt_directory = folder
                row.update(operations_emitted=owned.result.operations_emitted, budget_charge=owned.result.operations_emitted,
                           construction_cost_known=True, entry_reference=encode(entry.reference))
                (folder / 'returned-metadata.json').write_bytes(_bytes(owned.record()) + b'\n')
                if owned.result.graph is None:
                    row['status'] = 'UNSUPPORTED'
                else:
                    document = owned.program().to_dict()
                    owned._program_digest = _hash(document)
                    ref = _write_shard(folder, 'source-program5.json.gz', document, limit=requested.max_record_bytes)
                    ref = {**ref, 'uri': str(folder / ref['uri']), 'external': True}
                    owned.program_reference = {'artifact': ref, 'pointer': '#/graph'}
                    owned._bound_reference_json = _bytes(owned.program_reference)
                    row['program'] = ref
                    output_bytes += ref['physical_bytes']
                    (folder / 'lowered-return.json').write_bytes(_bytes(owned.record()) + b'\n')
                    # Ordinary reader, not another lowering. The code proof is
                    # independently resolved again from the admitted archive.
                    restored, _physical = _read_receipt(ref['uri'], limit=requested.max_record_bytes)
                    _need(all(_physical[name] == ref[name] for name in
                              ('physical_sha256', 'physical_bytes', 'decoded_sha256', 'decoded_bytes')),
                          'ordinary reader consumed a different original body artifact')
                    checked = SourceProgram.read_structure(restored, max_operations=allocation,
                        source_texts={entry.reference.snapshot.path: context.text})
                    independent = SourceCodeEvidence.from_entry(plan.catalog, entry)
                    require_valid_structured_body(checked.structured, checked.graph, checked.interface, checked.metadata,
                        semantic=checked.semantic, control=checked.control, language=checked.language,
                        source_tree=context.tree, language_options=SourceLanguageOptions(active_capabilities, independent))
                    owned.require_unchanged()
                    if archive is not None:
                        before_output = archive.writer.counts['stored_output_bytes']
                        fragment_ref = archive.publish(ref, namespace_root=entry.reference.context.namespace_root)
                        output_bytes += archive.writer.counts['stored_output_bytes'] - before_output
                        owned.program_reference = {'artifact': fragment_ref, 'pointer': '#/program/graph'}
                        owned._bound_reference_json = _bytes(owned.program_reference)
                        row.update(program=fragment_ref, original_program=ref,
                            storage_qualification='original public SP5/code checks; archive split only, not CP2 admission')
                        (folder / 'lowered-return.json').write_bytes(_bytes(owned.record()) + b'\n')
                    row.update(status='SUCCEEDED', public_structure_reader=True, independent_code_reader=True)
            except CodeWitnessUnavailable as error:
                row.update(status='CODE_WITNESS_UNAVAILABLE', error={'type': type(error).__name__, 'detail': str(error)})
            except Exception as error:
                row.update(status='FAILED', error={'type': type(error).__name__, 'detail': str(error),
                                                  'traceback': traceback.format_exc()})
            if owned is None and lower_started:
                row['budget_charge'] = allocation
            charged += row['budget_charge']
            row['elapsed_s'] = time.perf_counter() - started
            (folder / 'result.json').write_bytes(_bytes(row) + b'\n')
            index.write((_bytes(row) + b'\n').decode())
            index.flush()
            rows.append(row)
            output_bytes += len(_bytes(row)) + 1
            _need(output_bytes <= requested.max_output_bytes, 'worker output byte ceiling exceeded')
            if progress is not None:
                progress({'stage': 'source_entry_attempt', 'entry_key': row['entry_key'], 'status': row['status']})
        plan.require_unchanged()
        _need(_entry_producer() == plan.document['producer'], 'entry worker producer changed during construction')
        counts = Counter(x['status'] for x in rows)
        summary = {'schema': 'scar.source-frontend-result', 'schema_version': 2, 'status': 'FINISHED_WITH_OPEN',
            'plan_sha256': plan.digest, 'counts': dict(counts), 'actual_lower_returns': len(owned_returns),
            'original_candidate_entries': len(plan.entries), 'original_current_groups': len(plan.groups),
            'original_current_calls': plan.document['summary']['current_calls'], 'window': len(plan.dispatch),
            'unattempted_window_entries': len(plan.dispatch) - len(rows), 'budget_operation_charge': charged,
            'decoded_source_bytes': source_bytes, 'source_files': file_stats, 'catalog_measurements': plan.catalog.measurements(),
            'source_prepare_attempts': 0, 'target_executed': False, 'publication': 'NOT_RUN', 'runtime_binding': 'NOT_RUN',
            'first_stage_complete': False, 'elapsed_s': time.perf_counter() - started}
        if archive is not None:
            summary['program_storage'] = 'SHARED_SOURCE_CONTEXT_V1'
            summary['source_fragment_costs'] = archive.finish(retire_fresh_originals=True)
        (root / 'manifest.json').write_bytes(_bytes(summary) + b'\n')
        return SourceEntryFrontendResult(summary, tuple(owned_returns), _hash(summary))
    except BaseException as error:
        (root / 'failure.json').write_bytes(_bytes({'status': 'BUILDING_FAILED_RETAINED', 'type': type(error).__name__,
            'detail': str(error), 'plan_sha256': plan.digest}) + b'\n')
        raise
    finally:
        index.close()


__all__ = ['SourceFrontendBudget', 'SourceFrontendPlan', 'plan_source_frontend', 'run_source_frontend',
           'SourceEntryFrontendPlan', 'SourceEntryFrontendResult', 'plan_source_entries', 'run_source_entries',
           'SOURCE_ENTRY_PROFILE_314_V2', 'SOURCE_ENTRY_PROFILE_314_V3', 'SOURCE_ENTRY_PROFILE_314_V4',
           'SOURCE_ENTRY_PROFILE_314_V5', 'SOURCE_ENTRY_PROFILE_314_V6', 'SOURCE_ENTRY_PROFILE_314_V7', 'SOURCE_ENTRY_PROFILE_314_V8', 'SOURCE_ENTRY_PROFILE_314_V9', 'SOURCE_ENTRY_PROFILES', 'LATEST_SOURCE_ENTRY_PROFILE']


def module_entry_catalog(composition, *, max_files=4096):
    """Independent original MODULE roots, without changing function eligibility.

    This is a metadata candidate catalog, not CodeType, activation or namespace
    proof. Normal lower_entry must resolve the exact readonly exec-root witness.
    It deliberately does not add MODULE to DefinitionKind or invent bodies.
    """
    from scar.ir.program.module_entries import ModuleCatalogEntry, ModuleUnitSource
    from scar.ir.v2.ids import OperationDefinitionID
    _need(type(composition) is CompositionIndex and type(max_files) is int and max_files > 0
          and composition.inventory_file_count <= max_files, 'module metadata catalog ceiling exceeded')
    result, seen = [], set()
    for fi, file in enumerate(composition.document['files']):
        raw = composition.inventory_file(fi)
        snapshot = decode(SourceSnapshot, raw['snapshot'])
        _need(raw['context'] is not None, 'module catalog requires exact original source context')
        context = decode(SourceContextDigest, raw['context'])
        for wire in file['module_roots']:
            _need(type(wire) is str and wire.startswith('opdef:'), 'invalid original MODULE identity')
            initializer = OperationDefinitionID(wire[len('opdef:'):])
            _need(initializer.wire == wire, 'module root wire identity differs')
            unit = ModuleUnitSource(snapshot, context.namespace_root, initializer)
            key = _hash(encode(unit))
            _need(key not in seen, 'duplicate fully qualified module source unit')
            seen.add(key)
            result.append(ModuleCatalogEntry(unit, context, fi))
    return tuple(result)
