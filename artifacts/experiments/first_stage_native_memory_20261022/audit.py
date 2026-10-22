#!/usr/bin/env python3
"""Independent standard-library audit of the saved native-memory experiment.

Usage:
  python audit.py --kineto RAW.json.gz --result result --out audit-result.json

No SCAR modules, target imports, Tensor reads, or evidence-bundle loading.  Raw
provider indices decide receipt order; timestamps are never used for pairing.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sys


PROFILE = "TORCH_KINETO_ALLOCATOR_V1"
REVISION = "cf30153c4c131c8164ee7798e5022d810682e2cb"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError("nonfinite JSON constant: " + value)


def stream(path):
    path = Path(path)
    return gzip.open(path, "rb") if path.suffix == ".gz" else path.open("rb")


def document(path):
    with stream(path) as source:
        payload = source.read()
    digest, size = sha256(payload).hexdigest(), len(payload)
    value = json.loads(payload, object_pairs_hook=pairs, parse_constant=invalid_constant)
    require(type(value) is dict, "artifact is not a JSON object: " + str(path))
    return value, digest, size


def hash_source(path):
    digest, size = sha256(), 0
    with stream(path) as source:
        while data := source.read(1024 * 1024):
            digest.update(data)
            size += len(data)
    return digest.hexdigest(), size


def canonical_digest(value):
    digest, size = sha256(), 0
    encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    for part in encoder.iterencode(value):
        payload = part.encode("utf-8")
        digest.update(payload)
        size += len(payload)
    return digest.hexdigest(), size


def integer(value, minimum=None):
    return type(value) is int and (minimum is None or value >= minimum)


def typed_id(value, kind):
    require(type(value) is dict and set(value) == {"kind", "value", "wire"}, "invalid typed ID fields")
    require(value["kind"] == kind and type(value["value"]) is str
            and value["wire"] == kind + ":" + value["value"], "typed ID namespace/wire mismatch")
    return value["value"]


def artifact(value, schema, digest, size):
    require(type(value) is dict and set(value) == {"uri", "schema", "sha256", "size_bytes"},
            "invalid ProviderArtifact fields")
    require(value["schema"] == schema and value["sha256"] == digest
            and type(value["size_bytes"]) is int and value["size_bytes"] == size,
            "artifact schema, exact SHA256 or decompressed/canonical byte count differs")


def raw_receipts(raw):
    selected, event_indices, counts = [], Counter(), Counter()
    for index, event in enumerate(raw["traceEvents"]):
        if type(event) is not dict or event.get("name") != "[memory]":
            continue
        counts["memory_records"] += 1
        args = event.get("args")
        if type(args) is dict and integer(args.get("Ev Idx"), 0):
            event_indices[args["Ev Idx"]] += 1
        if type(args) is not dict or event.get("ph") != "i" or event.get("cat") != "cpu_instant_event":
            counts["invalid_records"] += 1
            continue
        amount = args.get("Bytes")
        if type(amount) is int and amount == 0:
            counts["zero_records"] += 1
            continue
        row = {"index": index, "amount": amount, "pid": event.get("pid"), "tid": event.get("tid"),
               "address": args.get("Addr"), "type": args.get("Device Type"), "device": args.get("Device Id"),
               "order": args.get("Ev Idx") if integer(args.get("Ev Idx"), 0) else None}
        if not (type(amount) is int and amount != 0 and integer(row["pid"], 1)
                and integer(row["tid"], 1) and integer(row["address"], 1)
                and integer(row["type"], 0) and integer(row["device"])):
            counts["invalid_records"] += 1
            continue
        selected.append(row)
        counts["positive_receipts" if amount > 0 else "negative_receipts"] += 1
        counts["cpu_receipts" if (row["type"], row["device"]) == (0, -1)
               else "cuda_receipts" if row["type"] == 1 and row["device"] >= 0 else "other_device_receipts"] += 1
    return selected, event_indices, counts


def replay(receipts, all_indices):
    """Independent address histories; reject an entire contradictory history."""
    histories = defaultdict(list)
    for row in receipts:
        histories[row["pid"], row["type"], row["device"], row["address"]].append(row)
    expected, summary = {}, Counter()
    for history in histories.values():
        summary["address_slots"] += 1
        births = [row for row in history if row["amount"] > 0]
        summary["reused_address_slots"] += len(births) > 1
        reasons = set()
        if len({row["tid"] for row in history}) != 1:
            reasons.add("multiple_host_threads")
        if any(row["order"] is None for row in history):
            reasons.add("missing_or_invalid_event_index")
        if any(row["order"] is not None and all_indices[row["order"]] != 1 for row in history):
            reasons.add("nonunique_event_index")
        ordered = sorted(history, key=lambda row: row["order"]) if not reasons else history
        matches, pending, retired_before = {}, None, False
        if not reasons:
            for row in ordered:
                if row["amount"] > 0:
                    if pending is not None:
                        reasons.add("overlapping_positive_receipts")
                    pending = row
                elif pending is not None:
                    if row["amount"] + pending["amount"]:
                        reasons.add("free_size_mismatch")
                    else:
                        matches[pending["index"]] = row
                        pending, retired_before = None, True
                elif retired_before:
                    reasons.add("duplicate_or_unobserved_free")
                else:
                    summary["prehistory_free_receipts"] += 1
        if reasons:
            summary["ambiguous_slots"] += 1
            matches.clear()
        ordinal = 0
        for row in ordered:
            if row["amount"] < 0:
                continue
            free = matches.get(row["index"])
            expected[row["index"]] = {"birth": row, "free": free, "ambiguous": bool(reasons),
                "generation": row["index"] if reasons else ordinal, "reasons": sorted(reasons)}
            ordinal += 1
            summary["matched_frees"] += free is not None
            summary["open_at_capture_end"] += not reasons and free is None
            summary["unresolved_births"] += bool(reasons)
    summary["unmatched_frees"] = sum(row["amount"] < 0 for row in receipts) - summary["matched_frees"]
    return expected, summary


def audit(args):
    result_dir = Path(args.result)
    raw, raw_hash, raw_size = document(args.kineto)
    receipts, event_indices, counts = raw_receipts(raw)
    del raw
    require(counts["memory_records"] == args.expected_memory_records, "raw memory-record denominator differs")
    epochs, history = replay(receipts, event_indices)
    receipt_by_index = {row["index"]: row for row in receipts}
    report, _, _ = document(result_dir / "import-report.json.gz")
    fragment, _, _ = document(result_dir / "native-memory-lifetimes.json.gz")
    values, _, _ = document(result_dir / "native-memory-values.json.gz")
    profile, profile_hash, profile_size = document(result_dir / "native-memory-profile.json")
    require(report["schema"] == "scar.native-evidence-import" and report["schema_version"] == 1,
            "unexpected import report schema")
    contract, scope, pid = profile["contract"], report["scope"], report["pid"]
    require(profile["schema"] == "scar.native-memory-profile" and profile["schema_version"] == 1,
            "unexpected memory profile schema")
    require(contract["scope"] == scope and contract["pid"] == pid
            and contract["provider_revision"] == report["provider_revision"] == REVISION,
            "profile does not bind the imported process/provider/scope")
    artifact(contract["kineto"], "pytorch.kineto.chrome-trace.v1", raw_hash, raw_size)
    require(report["artifacts"]["kineto"]["sha256"] == raw_hash
            and report["artifacts"]["kineto"]["size_bytes"] == raw_size, "raw Kineto report hash differs")
    eto_hash, eto_size = hash_source(report["artifacts"]["eto"]["path"])
    require((eto_hash, eto_size) == (report["artifacts"]["eto"]["sha256"],
                                   report["artifacts"]["eto"]["size_bytes"]), "raw ETO report hash differs")
    scope_hash, _ = canonical_digest({"eto": eto_hash, "kineto": raw_hash, "revision": REVISION, "pid": pid})
    require(scope == "native:" + scope_hash, "capture scope differs from exact raw artifacts")
    values_hash, values_size = canonical_digest(values)
    artifact(fragment["values_artifact"], "scar.ir.v2.values", values_hash, values_size)
    artifact(fragment["kineto_artifact"], "pytorch.kineto.chrome-trace.v1", raw_hash, raw_size)
    artifact(fragment["profile_artifact"], "scar.native-memory-profile", profile_hash, profile_size)
    require(values["schema"] == "scar.ir.v2.values" and values["validation"]["valid"] is True,
            "final ValueGraph does not report a valid expected schema")
    for family in ("logical_values", "versions", "provenance", "regions", "materializations", "bindings", "objects"):
        require(not values.get(family), "allocator import invented " + family)
    allocations = {}
    for allocation in values["allocations"]:
        name = typed_id(allocation["id"], "alloc")
        require(name not in allocations, "duplicate allocation ID")
        allocations[name] = allocation
    require(len(allocations) == len(epochs) == counts["positive_receipts"], "positive receipt/allocation denominator differs")
    prefix = scope + ":allocation:kineto:"
    require(set(allocations) == {prefix + str(index) for index in epochs},
            "allocation IDs do not identify exactly the original positive event indices")
    locator = lambda index: "sha256:" + raw_hash + "#/traceEvents/" + str(index)
    for index, epoch in epochs.items():
        birth, free = epoch["birth"], epoch["free"]
        allocation = allocations[prefix + str(index)]
        native = allocation["metadata"]["native_memory"]
        expected = {"profile": PROFILE, "birth_index": index, "birth_ev_idx": birth["order"],
            "free_index": free["index"] if free else None, "free_ev_idx": free["order"] if free else None,
            "address": birth["address"], "process": birth["pid"], "thread": birth["tid"],
            "device_type": birth["type"], "device_id": birth["device"], "generation": epoch["generation"],
            "birth_reference": locator(index), "free_reference": locator(free["index"]) if free else None,
            "ordering_status": "UNRESOLVED" if epoch["ambiguous"] else "PROVIDER_THREAD_ORDER",
            "lifetime_status": "UNRESOLVED" if epoch["ambiguous"] else "MATCHED_PROFILER_FREE" if free else "OPEN_AT_CAPTURE_END"}
        require(native == expected and all(type(native[key]) is type(value) for key, value in expected.items()),
                "allocation metadata contradicts raw replay at birth " + str(index))
        device = ("cpu" if (birth["type"], birth["device"]) == (0, -1) else "cuda:" + str(birth["device"])
                  if birth["type"] == 1 and birth["device"] >= 0 else "provider-device:" + str(birth["type"]) + ":" + str(birth["device"]))
        require(allocation["nbytes"] == birth["amount"] and allocation["device"] == device
                and allocation["allocator_token"] == "kineto-addr:" + str(birth["address"])
                and allocation["lifetime_scope"] == scope, "allocation extent/device/address/scope differs")
        require(allocation["metadata"]["birth_reference"] == locator(index), "birth raw reference missing")
    validation = fragment["validation"]
    require(fragment["schema"] == "scar.native-memory-execution-fragment" and fragment["schema_version"] == 1,
            "unexpected lifetime fragment schema")
    require(report["memory"]["lifetime_binding"] == validation, "report and exported lifetime validation disagree")
    run, process = fragment["runs"], fragment["processes"]
    require(len(run) == len(process) == 1 and process[0]["pid"] == pid, "fragment process/run denominator differs")
    run_id, process_id = run[0]["id"], process[0]["id"]
    typed_id(run_id, "exec_run"); typed_id(process_id, "exec_process_instance")
    require(process[0]["run"] == run_id, "process belongs to another run")
    rows, observed = fragment["target_lifetime_events"], Counter()
    seen_ids, seen_points = set(), set()
    wanted = {("live", index): prefix + str(index) for index in epochs}
    wanted.update({("retired", epoch["free"]["index"]): prefix + str(index)
                   for index, epoch in epochs.items() if epoch["free"]})
    for row in rows:
        identity = typed_id(row["id"], "exec_target_lifetime_event")
        require(identity not in seen_ids, "duplicate lifetime row ID")
        seen_ids.add(identity)
        target = row["target"]
        require(set(target) == {"artifact", "allocation"} and target["artifact"] == fragment["values_artifact"],
                "lifetime target does not reference the final typed ValueGraph artifact")
        allocation_name = typed_id(target["allocation"], "alloc")
        fact = row["source"]
        require(fact["artifact"] == fragment["kineto_artifact"] and fact["locator"].startswith("#/traceEvents/"),
                "lifetime row has no exact raw receipt source")
        index_text = fact["locator"][len("#/traceEvents/"):]
        require(index_text.isdecimal(), "raw receipt locator is not an original integer index")
        index = int(index_text)
        key = row["kind"], index
        require(key not in seen_points and wanted.get(key) == allocation_name and index in receipt_by_index,
                "LIVE/RETIRED source or allocation is absent, duplicated, zero, unmatched or mismatched")
        seen_points.add(key); observed[row["kind"]] += 1
        require(row["at"] == {"run": run_id, "process": process_id, "source": fact},
                "lifetime EvidencePoint changes its raw source/process/run")
        require(row["protocol"] == {"artifact": fragment["profile_artifact"], "locator": "#/contract"},
                "lifetime row protocol is not the exact profile contract")
        for field in ("stage", "effect"):
            require(set(row[field]) == {"reason", "point"} and row[field]["reason"]
                    and row[field]["point"] == row["at"], "canonical stage/effect gap was replaced by a fabricated connection")
    require(seen_points == set(wanted) and len(rows) == validation["rows"], "lifetime row denominator differs")
    capture = contract["capture_manifest"]
    adjust = contract["adjust_timestamps"]
    if capture is not None:
        capture_document, capture_hash, capture_size = document(capture["uri"])
        artifact(capture, "scar.execution-evidence-collection", capture_hash, capture_size)
        require(fragment["capture_manifest_artifact"] == capture and capture_document["pid"] == pid,
                "capture manifest does not match fragment/process")
        recorded = capture_document.get("configuration", {}).get("experimental_config", {}).get("adjust_timestamps")
        require(type(recorded) is type(adjust) and recorded == adjust, "timestamp-adjustment declaration was changed")
    else:
        require(adjust is None, "timestamp-adjustment qualification has no capture receipt")
    require(not validation["issues"] and not validation["status_counts"].get("MISMATCH"), "production reported a source contradiction")
    if counts["invalid_records"] == 0 and history["ambiguous_slots"] == 0:
        require(validation["flags"]["birth_verified"] == len(rows), "not all exact raw birth associations were checked")
        if adjust is None:
            require(validation["status_counts"] == {"CONDITIONAL": len(rows)}
                    and validation["flags"]["matched"] == len(rows)
                    and validation["flags"]["ordering_qualified"] == 0
                    and "provider_adjust_timestamps_must_be_disabled" in validation["conditions"],
                    "unknown timestamp adjustment was silently accepted as disabled")
            require(validation["flags"]["free_verified"] == observed["retired"], "retired receipt validation denominator differs")
    for flag in ("whole_model_established", "canonical_program_graph_imported", "execution_model_imported",
                 "logical_versions_established", "state_effects_established", "resource_readiness_established",
                 "python_correspondence_established", "transformation_authorized"):
        require(report.get(flag) is False, "import report raises unsupported authority: " + flag)
    require(fragment["whole_model_established"] is False, "fragment claims a complete program model")
    for flag in ("canonical_stages_connected", "canonical_effects_connected", "physical_allocation_established",
                 "execution_model_imported", "transformation_authorized"):
        require(validation.get(flag) is False, "lifetime summary raises unsupported authority: " + flag)
    memory = report["memory"]
    require(memory["profile"] == PROFILE and memory["physical_cuda_allocation_established"] is False
            and memory["logical_content_established"] is False and memory["open_epochs_are_leaks"] is False,
            "profiler epochs were promoted to physical/content/leak claims")
    require(len(memory["records"]) == counts["memory_records"], "raw memory diagnostic inventory lost records")
    retained_indices = set()
    for retained in memory["records"]:
        require(integer(retained["index"], 0) and retained["index"] not in retained_indices
                and retained["reference"] == locator(retained["index"]),
                "retained memory diagnostic has a duplicate index or changed raw reference")
        retained_indices.add(retained["index"])
    if counts["invalid_records"] == counts["zero_records"] == 0:
        require(retained_indices == set(receipt_by_index), "retained memory diagnostics omit or invent original receipts")
    for key in ("memory_records", "positive_receipts", "negative_receipts", "zero_records", "invalid_records"):
        require(memory["counts"].get(key, 0) == counts[key], "import raw count differs for " + key)
    return {"valid": True, "audit": "independent stdlib raw/ValueGraph/lifetime correspondence",
        "raw_counts": dict(counts), "address_history": dict(history), "allocation_epochs": len(epochs),
        "lifetime_rows": dict(observed), "lifetime_status_counts": validation["status_counts"],
        "adjust_timestamps": adjust, "raw_kineto_sha256": raw_hash, "raw_eto_sha256": eto_hash,
        "final_values_canonical_sha256": values_hash, "final_values_canonical_bytes": values_size,
        "full_evidence_bundle_loaded": False, "timestamp_order_used": False,
        "whole_model_established": False, "physical_allocation_established": False,
        "open_epochs_are_leaks": False, "transformation_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kineto", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--expected-memory-records", type=int, default=70872)
    args = parser.parse_args()
    result = audit(args)
    with Path(args.out).open("x", encoding="utf-8") as destination:
        json.dump(result, destination, sort_keys=True, indent=2, allow_nan=False)
        destination.write("\n")
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
