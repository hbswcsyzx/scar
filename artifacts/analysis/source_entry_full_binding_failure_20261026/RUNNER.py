from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

TASK = Path(__file__).resolve().parent
SNAPSHOT = TASK / "source_snapshot"
RECEIPT_PATH = TASK / "SOURCE_SNAPSHOT_RECEIPTS.json"
PUBLICATION = Path("/home/zyf/AAA/scar-worktrees/source-entry-project/artifacts/experiments/source_entry_incremental35_continuation02_20261026/result/manifest.json")
PUBLICATION_SHA = "a124d78bb5e50e4ff96d1af2858357651cb9eda13918c328fd753a3a4bd4650b"
CAPTURE = Path("/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/first_stage_lewm_dispatch_20261023")
TRACE = CAPTURE / "trace"
EXPECTED_PID = 272038
EXPECTED_CALLS = 100438
EXPECTED_GROUPS = 817
OUT = TASK / "actual"
COORDINATE_OUT = TASK / "capture-coordinates.json"
STATUS = TASK / "RUN_STATUS.json"
TERMINAL = TASK / "ACTUAL_TERMINAL.json"


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _io_counters():
    result = {}
    try:
        for line in Path("/proc/self/io").read_text().splitlines():
            key, value = line.split(":", 1)
            result[key.strip()] = int(value.strip())
    except (OSError, ValueError):
        return None
    return result


def _write_json(path: Path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False).encode("utf-8") + b"\n")
    os.replace(temp, path)


started = time.time()
phase_started = started
state = {"schema": "scar.source-entry-full-binding-run-status.v1", "pid": os.getpid(),
         "source_snapshot_tree_sha256": None, "publication_uri": str(PUBLICATION),
         "publication_sha256_expected": PUBLICATION_SHA, "capture_uri": str(CAPTURE),
         "expected_capture_pid": EXPECTED_PID, "phase": "STARTED", "phase_started_utc_epoch": started,
         "elapsed_seconds": 0.0, "io_start": _io_counters()}

def phase(name, **extra):
    global phase_started
    now = time.time()
    state.update({"phase": name, "phase_started_utc_epoch": now,
                  "elapsed_seconds": now - started, **extra})
    _write_json(STATUS, state)
    print(json.dumps({"event": "phase", "phase": name, "elapsed_seconds": round(now - started, 3), **extra},
                     sort_keys=True, ensure_ascii=False), flush=True)
    phase_started = now


def _verify_snapshot():
    receipt = json.loads(RECEIPT_PATH.read_text())
    tree = hashlib.sha256()
    file_count = total_bytes = 0
    for row in receipt["files"]:
        path = SNAPSHOT / row["path"]
        raw = path.read_bytes()
        digest = _sha(raw)
        if len(raw) != row["bytes"] or digest != row["sha256"]:
            raise ValueError(f"snapshot receipt mismatch: {path}")
        tree.update(row["path"].encode()); tree.update(b"\0")
        tree.update(str(row["bytes"]).encode()); tree.update(b"\0")
        tree.update(row["sha256"].encode()); tree.update(b"\n")
        total_bytes += len(raw); file_count += 1
    if (file_count, total_bytes, tree.hexdigest()) != (receipt["file_count"], receipt["total_bytes"], receipt["tree_sha256"]):
        raise ValueError("snapshot root receipt mismatch")
    return receipt


sys.dont_write_bytecode = True
sys.path.insert(0, str(SNAPSHOT))

try:
    phase("VERIFY_SOURCE_SNAPSHOT")
    snapshot_receipt = _verify_snapshot()
    state["source_snapshot_tree_sha256"] = snapshot_receipt["tree_sha256"]
    state["source_snapshot_file_count"] = snapshot_receipt["file_count"]
    state["source_snapshot_total_bytes"] = snapshot_receipt["total_bytes"]
    if not PUBLICATION.is_file():
        raise FileNotFoundError(PUBLICATION)

    phase("VERIFY_PUBLICATION_RECEIPT")
    manifest_bytes = PUBLICATION.read_bytes()
    manifest_sha = _sha(manifest_bytes)
    manifest = json.loads(manifest_bytes)
    if manifest_sha != PUBLICATION_SHA:
        raise ValueError(f"publication SHA mismatch: {manifest_sha}")
    if manifest.get("schema") != "scar.source-entry-publication" or manifest.get("schema_version") != 3:
        raise ValueError("final publication is not schema v3")
    if type(manifest.get("bodies")) is not list or len(manifest["bodies"]) != 196:
        raise ValueError("final publication body denominator is not 196")
    archive_rows = manifest["catalog_inputs"]["archives"]
    archive_declarations = tuple((str(Path(row["path"]).parent), row["sha256"]) for row in archive_rows)
    state.update({"publication_sha256_actual": manifest_sha, "publication_bytes": len(manifest_bytes),
                  "publication_bodies": len(manifest["bodies"]), "archive_count": len(archive_rows),
                  "archive_paths": [row["path"] for row in archive_rows]})

    phase("COMPOSITION_PUBLIC_READER_STARTED", body_rows=196, archive_count=len(archive_rows),
          selected_decode_budget_bytes=8_000_000_000)
    from scar.analysis.compiler_witness_archives import CompilerArchiveBudget, CompilerWitnessArchives
    from scar.analysis.code_witness import CodeWitnessBudget
    from scar.analysis.program_composition import CompositionIndex
    from scar.analysis.source_attachments import SourceAttachmentBudget
    from scar.ir.program.call_edges import CallEdgeBudget

    archives = CompilerWitnessArchives(
        archive_declarations,
        store_budget=CodeWitnessBudget(max_compile_keys=1024, max_source_files=1024,
            max_source_bytes=16_000_000, max_module_bytes=16_000_000,
            max_archive_bytes=64_000_000, max_manifest_bytes=8_000_000,
            max_nested_codes=8192, max_depth=128),
        budget=CompilerArchiveBudget(max_archives=16, max_total_modules=1024,
                                     max_total_sources=1024, max_declared_payload_bytes=2_000_000_000))
    attachment_budget = SourceAttachmentBudget(max_report_bytes=64_000_000, max_files=512,
        max_codes=16_384, max_roots=16, max_artifact_bytes=2_200_000_000,
        max_record_bytes=256_000_000, cached_files=2)
    budget_values = {"max_input_bytes": 256_000_000, "max_record_bytes": 128_000_000,
        "max_programs": 196, "max_operations_per_body": 100_000,
        "max_catalog_groups": 100_000, "max_catalog_entries": 100_000,
        "max_selected_decode_bytes": 8_000_000_000, "max_parent_depth": 4}
    phase_start = time.time()
    composition = CompositionIndex.from_source_entry_publication(
        str(PUBLICATION), expected_sha256=PUBLICATION_SHA, archives=archives,
        attachment_budget=attachment_budget, **budget_values)
    composition_elapsed = time.time() - phase_start
    if not composition.has_source_entry_publication:
        raise ValueError("normal source-entry composition reader returned no publication")
    body_ref = composition.entry_publication_reference()
    if body_ref.get("sha256") != PUBLICATION_SHA:
        raise ValueError("composition reader returned a different source-entry root")

    call_budget = CallEdgeBudget(max_raw_bytes=256_000_000, max_lines=300_000,
        max_line_bytes=2_000_000, max_processes=128, max_codes=8192,
        max_events=250_000, max_source_files=256, max_source_bytes=16_000_000,
        max_references=2_000_000, max_path=128)
    from scar.analysis.call_seeds import CallSourceSeedReport
    seed_document = composition.inventory_component("call_sources")
    seed = CallSourceSeedReport._decode_replay_input(seed_document, verification_budget=call_budget)
    seed_model = seed
    seed_pids = sorted({group.process_id for group in seed_model.groups})
    seed_calls = sum(group.count for group in seed_model.groups)
    if seed_pids != [EXPECTED_PID] or seed_calls != EXPECTED_CALLS or len(seed_model.groups) != EXPECTED_GROUPS:
        raise ValueError(f"composition call-source seed scope mismatch: pids={seed_pids}, calls={seed_calls}, groups={len(seed_model.groups)}")
    if str(Path(seed_model.trace_directory).resolve()) != str(TRACE.resolve()):
        raise ValueError(f"composition seed trace differs: {seed_model.trace_directory}")
    state.update({"composition_elapsed_seconds": composition_elapsed,
        "composition_public_reader": "CompositionIndex.from_source_entry_publication -> read_source_entry_publication",
        "composition_publication_reference": body_ref,
        "seed_process_ids": seed_pids, "seed_entered_code_groups": len(seed_model.groups),
        "seed_entered_invocations": seed_calls, "seed_trace_directory": seed_model.trace_directory,
        "composition_reader_budget": budget_values,
        "archives_admitted": archives.receipts()})

    phase("CAPTURE_COORDINATES_STARTED", capture_bytes_limit=2_000_000_000, capture_line_limit=2_000_000)
    from scar.trace.capture_coordinates import bind_capture_coordinates
    coordinate_start = time.time()
    coordinates = bind_capture_coordinates(str(CAPTURE), max_bytes=2_000_000_000,
        max_lines=2_000_000, profile_uri=str(COORDINATE_OUT))
    coordinate_elapsed = time.time() - coordinate_start
    if coordinates.report["call_collector_declaration"].get("process_id") != EXPECTED_PID:
        raise ValueError("capture coordinates bind a different call collector PID")
    if coordinates.report["operand_collector_declaration"].get("process_id") != EXPECTED_PID:
        raise ValueError("capture coordinates bind a different operand collector PID")
    state.update({"coordinate_elapsed_seconds": coordinate_elapsed,
        "coordinate_artifact": {"uri": coordinates.artifact.uri, "sha256": coordinates.artifact.sha256,
                                 "bytes": coordinates.artifact.size_bytes},
        "coordinate_counts": coordinates.report["counts"],
        "coordinate_call_pid": coordinates.report["call_collector_declaration"]["process_id"],
        "coordinate_operand_pid": coordinates.report["operand_collector_declaration"]["process_id"],
        "coordinate_retention": coordinates.report["retention"]})

    phase("SOURCE_INVOCATION_BINDER_STARTED", witness_mode="same_capture", process_id=EXPECTED_PID,
          expected_calls=EXPECTED_CALLS, expected_groups=EXPECTED_GROUPS)
    from scar.analysis.source_invocations import bind_source_invocations
    binder_start = time.time()
    report = bind_source_invocations(composition, coordinates, str(TRACE), str(OUT),
        call_budget=call_budget, witness_mode="same_capture")
    binder_elapsed = time.time() - binder_start
    summary = report["summary"]
    if report.get("witness_mode") != "same_capture" or report.get("source_witness_raw_manifest_replayed") is not True:
        raise ValueError("binder did not complete exact same-capture replay")
    if summary.get("invocations") != EXPECTED_CALLS:
        raise ValueError(f"binder invocation count mismatch: {summary.get('invocations')}")

    output_files = []
    output_total = 0
    for path in sorted(OUT.iterdir()):
        if path.is_file():
            size = path.stat().st_size
            output_total += size
            output_files.append({"path": str(path), "bytes": size, "sha256": _sha(path.read_bytes())})
    phase_io = _io_counters()
    result = {"schema": "scar.source-entry-full-binding-actual-result.v1", "terminal": "PASS",
        "main_source_head": snapshot_receipt["source_git_head"],
        "source_snapshot": {"file_count": snapshot_receipt["file_count"], "bytes": snapshot_receipt["total_bytes"],
                            "tree_sha256": snapshot_receipt["tree_sha256"]},
        "publication": {"uri": str(PUBLICATION), "sha256": manifest_sha, "bytes": len(manifest_bytes),
                        "body_rows": len(manifest["bodies"])},
        "capture": {"root": str(CAPTURE), "trace": str(TRACE), "pid": EXPECTED_PID,
                    "seed_groups": len(seed_model.groups), "seed_invocations": seed_calls},
        "timing_seconds": {"composition_public_reader": composition_elapsed,
                           "capture_coordinates": coordinate_elapsed,
                           "source_invocation_binder": binder_elapsed,
                           "total": time.time() - started},
        "budgets": {"composition": budget_values, "call_edge": {k: getattr(call_budget, k) for k in call_budget.__dataclass_fields__}},
        "composition_publication_reference": body_ref,
        "binder": {"report": str(OUT / "report.json"), "schema_version": report["schema_version"],
            "witness_mode": report["witness_mode"], "summary": summary,
            "actual_call_scan": report.get("actual_call_scan"),
            "source_binding_statuses": summary.get("source_binding_statuses"),
            "invocation_statuses": summary.get("invocation_statuses"),
            "frontiers": summary.get("frontiers"),
            "whole_program_established": report.get("whole_program_graph_established"),
            "output_bytes": output_total, "output_files": output_files},
        "io_counters_self": {"start": state.get("io_start"), "end": phase_io,
            "delta": ({key: phase_io[key] - state["io_start"].get(key, 0)
                       for key in phase_io if state.get("io_start") is not None})},
        "limitations": ["196 admitted body rows are source-body denominator, not runtime binding count",
            "source binding statuses are code/source groups; invocation statuses are captured calls",
            "same_capture replay proves raw/source witness consistency within the retained trace, not callable environment, actual/formal routing, effects, or whole-program graph"]}
    _write_json(TASK / "ACTUAL_RESULT.json", result)
    _write_json(TERMINAL, {"exit_code": 0, "terminal": "PASS", "elapsed_seconds": time.time() - started,
                           "result": str(TASK / "ACTUAL_RESULT.json"), "binding_report": str(OUT / "report.json")})
    phase("PASS", result=str(TASK / "ACTUAL_RESULT.json"), binder_elapsed_seconds=binder_elapsed)
except BaseException as exc:
    terminal = {"exit_code": 1, "terminal": "FAIL", "phase": state.get("phase"),
        "elapsed_seconds": time.time() - started, "exception_type": type(exc).__name__,
        "exception": str(exc), "traceback": traceback.format_exc(), "status_path": str(STATUS),
        "io_end": _io_counters()}
    _write_json(TERMINAL, terminal)
    state.update({"phase": "FAIL", "elapsed_seconds": time.time() - started,
        "exception_type": type(exc).__name__, "exception": str(exc)})
    _write_json(STATUS, state)
    print(json.dumps(terminal, sort_keys=True, ensure_ascii=False), flush=True)
    raise
