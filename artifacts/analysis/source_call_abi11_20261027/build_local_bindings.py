from __future__ import annotations

import argparse
from collections import Counter, OrderedDict
import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from scar.analysis.call_operand_reader import _TYPES as OPERAND_TYPES
from scar.analysis.call_trace_reader import _decode_event as decode_frame_event
from scar.analysis.retained_source_call_ports import (
    _Inputs, _OperandBoundaryIndex, _selected_binding,
)
from scar.ir.program.call_edges import CallEdgeBudget, CallRecordAnchor, CodeCapture
from scar.ir.program.call_operands import OperandCollectionMetadata
from scar.ir.program.python_call_targets import PythonCallTarget, PythonEntryBinding, PythonSourcePortBinding
from scar.ir.record_codec import decode, encode

from read_issue_events import IndexedJsonl, canonical


def load_bound_bytes(path, expected_bytes, expected_sha256):
    p = Path(path).absolute()
    if p.is_symlink() or not p.is_file():
        raise ValueError(f"expected ordinary retained file: {p}")
    before = p.stat()
    if before.st_size != expected_bytes:
        raise ValueError(f"retained file size differs: {p}")
    raw = p.read_bytes()
    after = p.stat()
    if hashlib.sha256(raw).hexdigest() != expected_sha256 or len(raw) != expected_bytes:
        raise ValueError(f"retained file receipt differs: {p}")
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ):
        raise ValueError(f"retained file changed while reading: {p}")
    return raw


def read_index_range(reader, start_index, end_index):
    located = reader.locate(start_index)
    if located is None:
        raise ValueError(f"index {start_index} is absent from {reader.path}")
    offset, first, _ = located
    if first["index"] != start_index:
        raise ValueError("indexed seek did not land on the requested first event")
    reader.stream.seek(offset)
    rows = []
    expected = start_index
    while expected <= end_index:
        reader.read_calls += 1
        raw = reader.stream.readline(2_000_001)
        reader.returned_bytes += len(raw)
        if not raw or len(raw) > 2_000_000 or reader.returned_bytes > reader.max_returned_bytes:
            raise ValueError("bounded local JSONL read exceeded its byte/line ceiling")
        row = json.loads(raw.decode("utf-8"))
        reader.lines_examined += 1
        if type(row) is not dict or row.get("index") != expected:
            raise ValueError("local raw event indices are not a complete contiguous interval")
        rows.append((row, raw))
        expected += 1
    return rows


def read_through_handshake(reader, attempt_index, *, max_index_gap):
    located = reader.locate(attempt_index)
    if located is None or located[1].get("index") != attempt_index:
        raise ValueError("selected existing attempt is absent from the retained operand file")
    reader.stream.seek(located[0])
    rows = []
    expected = attempt_index
    handshake_found = False
    while expected <= attempt_index + max_index_gap:
        reader.read_calls += 1
        raw = reader.stream.readline(2_000_001)
        reader.returned_bytes += len(raw)
        if not raw or len(raw) > 2_000_000 or reader.returned_bytes > reader.max_returned_bytes:
            raise ValueError("bounded existing-call read exceeded its byte/line ceiling")
        row = json.loads(raw.decode("utf-8"))
        reader.lines_examined += 1
        if type(row) is not dict or row.get("index") != expected:
            raise ValueError("existing-call operand indices are not a contiguous local range")
        rows.append((row, raw))
        if row.get("kind") == "ENTRY_HANDSHAKE" and row.get("attempt_index") == attempt_index:
            handshake_found = True
            break
        expected += 1
    if not handshake_found:
        raise ValueError("selected existing attempt has no local entry handshake")
    return rows


def decode_operand_events(rows, path):
    events = []
    for row, raw in rows:
        kind = row.get("kind")
        event_type = OPERAND_TYPES.get(kind)
        if event_type is None:
            raise ValueError("unsupported retained operand event kind")
        index = row["index"]
        anchor = CallRecordAnchor(str(path), index, hashlib.sha256(raw).hexdigest(), index)
        wire = {**row, "anchor": encode(anchor)}
        events.append(decode(event_type, wire))
    return tuple(events)


def decode_frame_entries(rows, path, code_map):
    entries = {}
    for row, raw in rows:
        if row.get("kind") != "call_enter":
            continue
        index = row["index"]
        anchor = CallRecordAnchor(str(path), index, hashlib.sha256(raw).hexdigest(), index)
        kind, decoded_index, entry, _ = decode_frame_event(row, anchor, row["process_id"],
            index - 1, code_map, CallEdgeBudget())
        if kind != "call_enter" or decoded_index != index or entry is None:
            raise ValueError("retained frame entry failed exact typed decode")
        if entry.invocation.invocation_id in entries:
            raise ValueError("duplicate local invocation entry")
        entries[entry.invocation.invocation_id] = entry
    return entries


def load_prior_binding(manifest_path, manifest, attempt_index):
    matches = [shard for shard in manifest["shards"]
        if attempt_index in shard["candidate_scope"]["accepted_attempt_indices"]]
    if len(matches) != 1:
        raise ValueError("selected prior attempt does not belong to one existing closed shard")
    shard = matches[0]
    shard_path = Path(manifest_path).absolute().parent / shard["path"]
    stored = load_bound_bytes(shard_path, shard["stored_bytes"], shard["stored_sha256"])
    if shard.get("representation") != "gzip-json-mtime0-v1":
        raise ValueError("prior selected shard has an unsupported retained representation")
    decoded = gzip.decompress(stored)
    if len(decoded) != shard["decoded_bytes"] or hashlib.sha256(decoded).hexdigest() != shard["decoded_sha256"]:
        raise ValueError("prior selected shard decoded receipt differs")
    document = json.loads(decoded.decode("utf-8"))
    if document.get("schema") != "scar.python-source-port-bindings" or document.get("schema_version") != 2:
        raise ValueError("prior selected shard has an unexpected source-port model")
    bindings = [decode(PythonSourcePortBinding, value) for value in document["bindings"]
        if value.get("target", {}).get("attempt_index") == attempt_index]
    if len(bindings) != 1:
        raise ValueError("prior selected shard does not contain one exact typed binding")
    binding, = bindings
    if binding.target.receiver is None or binding.target.receiver.explicit_positional <= 0:
        raise ValueError("selected prior binding does not exercise an explicit positional receiver")
    return binding, {"path": str(shard_path), "stored_sha256": shard["stored_sha256"],
        "decoded_sha256": shard["decoded_sha256"], "stored_bytes": shard["stored_bytes"],
        "decoded_bytes": shard["decoded_bytes"], "shard_index": shard["shard_index"]}


def build(args):
    result_path = Path(args.result).absolute()
    manifest_path = Path(args.manifest).absolute()
    result = json.loads(result_path.read_text())
    manifest_raw = manifest_path.read_bytes()
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    if manifest_sha != args.expected_manifest_sha256 or result.get("manifest_sha256") != manifest_sha:
        raise ValueError("candidate publication manifest receipt differs")
    manifest = json.loads(manifest_raw.decode("utf-8"))
    issue_summary_path = Path(args.issue_summary).absolute()
    issue_summary = json.loads(issue_summary_path.read_text())
    if issue_summary.get("manifest_sha256") != manifest_sha or issue_summary.get("issue_count") != 11:
        raise ValueError("targeted raw-row receipt differs from the full candidate manifest")
    issues = sorted(issue_summary["issues"], key=lambda item: item["attempt"]["index"])
    wanted = {item["attempt"]["index"] for item in issues}
    if len(wanted) != 11:
        raise ValueError("expected eleven distinct retained attempts")
    prior_binding, prior_shard_receipt = load_prior_binding(
        manifest_path, manifest, args.prior_positional_attempt_index)

    source_report_ref = manifest["shared_inputs"]["source_report"]
    bindings_ref = manifest["shared_inputs"]["bindings"]
    inputs = _Inputs(source_report_ref["path"], bindings_ref["path"],
        source_report_ref["sha256"], bindings_ref["sha256"])
    pid = inputs.process_id(272038)
    operand_refs = manifest["shared_inputs"]["trace_file_receipts"]["operand_files"]
    frame_refs = manifest["shared_inputs"]["trace_file_receipts"]["frame_files"]
    operand_ref, = [item for item in operand_refs
        if item["family"] == "operands" and item["process_id"] == pid]
    operand_meta_ref, = [item for item in operand_refs
        if item["family"] == "operand-meta" and item["process_id"] == pid]
    frame_event_ref, = [item for item in frame_refs
        if item["family"] == "events" and item["process_id"] == pid]
    frame_meta_ref, = [item for item in frame_refs
        if item["family"] == "meta" and item["process_id"] == pid]

    operand_meta_raw = load_bound_bytes(operand_meta_ref["path"], operand_meta_ref["raw_bytes"],
        operand_meta_ref["raw_sha256"])
    operand_meta = decode(OperandCollectionMetadata, json.loads(operand_meta_raw.decode("utf-8")))
    if (operand_meta.process_id != pid or operand_meta.events != operand_meta.event_attempts
            or operand_meta.events != operand_ref["lines"] or operand_meta.bytes != operand_ref["raw_bytes"]
            or operand_meta.dropped_events or operand_meta.errors or operand_meta.io_failed
            or operand_meta.previous_profile):
        raise ValueError("retained operand process metadata is not clean/complete")
    frame_meta_raw = load_bound_bytes(frame_meta_ref["path"], frame_meta_ref["raw_bytes"],
        frame_meta_ref["raw_sha256"])
    frame_meta = json.loads(frame_meta_raw.decode("utf-8"))
    if (frame_meta.get("events") != frame_event_ref["lines"]
            or frame_meta.get("event_attempts", frame_meta.get("events")) != frame_meta.get("events")
            or frame_meta.get("dropped_events") or frame_meta.get("dropped_codes")
            or frame_meta.get("open_invocations") or frame_meta.get("errors")):
        raise ValueError("retained frame process metadata is not clean/complete")

    first_operand = min(wanted)
    last_handshake_event = max(item["handshake"]["index"] for item in issues)
    operand_reader = IndexedJsonl(operand_ref["path"], expected_bytes=operand_ref["raw_bytes"],
        expected_lines=operand_ref["lines"], prior_sha256=operand_ref["raw_sha256"],
        max_returned_bytes=4_000_000)
    operand_rows = read_index_range(operand_reader, first_operand, last_handshake_event)
    operand_events = decode_operand_events(operand_rows, operand_ref["path"])
    attempts = {event.index: event for event in operand_events
        if event.kind.value == "CALL_ATTEMPT" and event.index in wanted}
    handshakes = {event.attempt_index: event for event in operand_events
        if event.kind.value == "ENTRY_HANDSHAKE" and event.attempt_index in wanted}
    if set(attempts) != wanted or set(handshakes) != wanted:
        raise ValueError("targeted typed attempt/handshake rows are incomplete")
    boundary_index = _OperandBoundaryIndex(SimpleNamespace(events=operand_events, issues=()))

    prior_operand_reader = IndexedJsonl(operand_ref["path"], expected_bytes=operand_ref["raw_bytes"],
        expected_lines=operand_ref["lines"], prior_sha256=operand_ref["raw_sha256"],
        max_returned_bytes=2_000_000)
    prior_operand_rows = read_through_handshake(prior_operand_reader,
        args.prior_positional_attempt_index, max_index_gap=1024)
    prior_operand_events = decode_operand_events(prior_operand_rows, operand_ref["path"])
    prior_attempts = [event for event in prior_operand_events
        if event.kind.value == "CALL_ATTEMPT" and event.index == args.prior_positional_attempt_index]
    prior_handshakes = [event for event in prior_operand_events
        if event.kind.value == "ENTRY_HANDSHAKE" and event.attempt_index == args.prior_positional_attempt_index]
    if len(prior_attempts) != 1 or len(prior_handshakes) != 1:
        raise ValueError("selected prior attempt did not decode as one exact attempt/handshake pair")
    prior_attempt, = prior_attempts
    prior_handshake, = prior_handshakes
    if (prior_attempt.invocation != prior_binding.entry.caller
            or prior_handshake.invocation != prior_binding.entry.callee
            or prior_binding.target_anchor.index != prior_attempt.index
            or prior_binding.entry_anchor.index != prior_handshake.entry_index
            or prior_binding.call.site != prior_attempt.site):
        raise ValueError("prior closed binding does not identify the local raw attempt/entry")
    prior_boundary = _OperandBoundaryIndex(SimpleNamespace(events=prior_operand_events, issues=()))

    caller_ids = {item["attempt"]["invocation_id"] for item in issues}
    callee_ids = {item["handshake"]["invocation_id"] for item in issues}
    wanted_invocations = caller_ids | callee_ids
    frame_seek_index = min(item["attempt"]["frame_index"] for item in issues) - args.frame_lookback
    frame_seek_index = max(1, frame_seek_index)
    frame_end_index = max(item["entry"]["index"] for item in issues)
    frame_reader = IndexedJsonl(frame_event_ref["path"], expected_bytes=frame_event_ref["raw_bytes"],
        expected_lines=frame_event_ref["lines"], prior_sha256=frame_event_ref["raw_sha256"],
        max_returned_bytes=4_000_000)
    frame_rows = read_index_range(frame_reader, frame_seek_index, frame_end_index)
    prior_frame_start = max(1, prior_attempt.frame_index - args.prior_frame_lookback)
    prior_frame_reader = IndexedJsonl(frame_event_ref["path"], expected_bytes=frame_event_ref["raw_bytes"],
        expected_lines=frame_event_ref["lines"], prior_sha256=frame_event_ref["raw_sha256"],
        max_returned_bytes=4_000_000)
    prior_frame_rows = read_index_range(prior_frame_reader, prior_frame_start,
        prior_handshake.entry_index)
    code_map = {}
    all_codes = ({item["attempt"]["site"]["code"] for item in issues}
        | {item["attempt"]["dispatch"]["code"] for item in issues}
        | {prior_attempt.site.code, prior_attempt.dispatch.code})
    for code in all_codes:
        group_row = inputs.by_group[pid, code]
        capture = decode(CodeCapture, group_row["code_capture"])
        if capture.process_id != pid or capture.code.key != code:
            raise ValueError("retained source group has a different complete code capture")
        code_map[code] = capture.code
    entries = decode_frame_entries(frame_rows, frame_event_ref["path"], code_map)
    if not wanted_invocations <= set(entries):
        raise ValueError("local frame window did not contain all referenced exact entries")
    prior_entries = decode_frame_entries(prior_frame_rows, frame_event_ref["path"], code_map)
    if not {prior_attempt.invocation.invocation_id, prior_handshake.invocation.invocation_id} <= set(prior_entries):
        raise ValueError("local prior frame window did not contain both exact call entries")

    template_cache, source_tree_cache = OrderedDict(), OrderedDict()
    prior_caller_entry = prior_entries[prior_attempt.invocation.invocation_id]
    prior_callee_entry = prior_entries[prior_handshake.invocation.invocation_id]
    prior_caller_row = inputs.by_group[pid, prior_caller_entry.code]
    prior_callee_row = inputs.by_group[pid, prior_callee_entry.code]
    prior_target, prior_entry, rebuilt_prior_binding = _selected_binding(inputs, (operand_meta,),
        prior_boundary, template_cache, pid, prior_attempt, prior_handshake,
        prior_caller_entry, prior_callee_entry, prior_caller_row, prior_callee_row,
        source_tree_cache)
    if (prior_target, prior_entry, rebuilt_prior_binding) != (
            prior_binding.target, prior_binding.entry, prior_binding):
        raise ValueError("existing explicit-positional receiver binding changed under the updated producer")
    prior_binding_back = decode(PythonSourcePortBinding, encode(rebuilt_prior_binding))
    if prior_binding_back != rebuilt_prior_binding:
        raise ValueError("existing positional receiver binding did not codec-roundtrip exactly")
    prior_recheck = {
        "attempt_index": prior_attempt.index,
        "call_opcode": prior_attempt.site.opname,
        "source_call_position": list(prior_attempt.site.position),
        "receiver_explicit_positional": prior_target.receiver.explicit_positional,
        "argument_ports": [{"index": port.index, "formal_name": port.formal_name,
            "actual_use": encode(port.actual_use), "formal_slot": encode(port.formal_slot)}
            for port in rebuilt_prior_binding.arguments],
        "original_call_operation": encode(rebuilt_prior_binding.call.core_operation),
        "matches_prior_closed_binding": True,
        "codec_roundtrip": True,
        "prior_shard": prior_shard_receipt,
    }
    output = []
    for issue in issues:
        attempt_index = issue["attempt"]["index"]
        attempt = attempts[attempt_index]
        handshake = handshakes[attempt_index]
        caller_entry = entries[attempt.invocation.invocation_id]
        callee_entry = entries[handshake.invocation.invocation_id]
        if (attempt.anchor.index != attempt_index or handshake.attempt_index != attempt_index
                or handshake.entry_index != callee_entry.anchor.index):
            raise ValueError("raw attempt/handshake/entry indices disagree")
        caller_row = inputs.by_group[pid, caller_entry.code]
        callee_row = inputs.by_group[pid, callee_entry.code]
        target, entry, binding = _selected_binding(inputs, (operand_meta,), boundary_index,
            template_cache, pid, attempt, handshake, caller_entry, callee_entry,
            caller_row, callee_row, source_tree_cache)
        target_raw = encode(target)
        entry_raw = encode(entry)
        binding_raw = encode(binding)
        target_back = decode(PythonCallTarget, target_raw)
        entry_back = decode(PythonEntryBinding, entry_raw)
        binding_back = decode(PythonSourcePortBinding, binding_raw)
        if (target_back, entry_back, binding_back) != (target, entry, binding):
            raise ValueError("typed source-call relation did not codec-roundtrip exactly")
        signature = inputs.signature(binding.callee_body.definition)
        assigned_slots = {port.formal_slot for port in binding.arguments}
        if binding.receiver is not None:
            assigned_slots.add(binding.receiver.formal_slot)
        output.append({
            "candidate_ordinal": issue["candidate_ordinal"],
            "attempt_index": attempt_index,
            "call_opcode": attempt.site.opname,
            "source_call_position": list(attempt.site.position),
            "caller_code": caller_entry.code,
            "caller_invocation_id": caller_entry.invocation.invocation_id,
            "callee_code": callee_entry.code,
            "callee_invocation_id": callee_entry.invocation.invocation_id,
            "target_kind": target.kind.value,
            "receiver_parameter_index": entry.receiver_parameter_index,
            "receiver_ref_matches_first_formal": binding.receiver is not None,
            "receiver_port": None if binding.receiver is None else {
                "callable_use": encode(binding.receiver.callable_use),
                "callable_value": encode(binding.receiver.callable_value),
                "formal_name": binding.receiver.formal_name,
                "formal_slot": encode(binding.receiver.formal_slot),
                "formal_value": encode(binding.receiver.formal_value),
            },
            "explicit_argument_count": len(binding.arguments),
            "explicit_arguments": [{
                "index": port.index, "formal_name": port.formal_name,
                "route_origin": port.parameter.origin.value,
                "actual_source": encode(port.actual_source),
                "actual_use": encode(port.actual_use),
                "actual_value": encode(port.actual_value),
                "formal_slot": encode(port.formal_slot),
                "formal_value": encode(port.formal_value),
            } for port in binding.arguments],
            "omitted_declared_defaults": [parameter.name for parameter in signature.parameters
                if binding.receiver is not None and parameter.slot not in assigned_slots
                and parameter.default_source is not None],
            "original_call_use": encode(binding.call.callee_use),
            "original_call_operation": encode(binding.call.core_operation),
            "original_call_source": encode(binding.call.source),
            "candidate_status": None if binding.candidate is None else binding.candidate.status.value,
            "codec_roundtrip": True,
        })

    operand_receipt = operand_reader.close_and_check()
    frame_receipt = frame_reader.close_and_check()
    prior_operand_receipt = prior_operand_reader.close_and_check()
    prior_frame_receipt = prior_frame_reader.close_and_check()
    payload = {
        "schema": "scar.retained-source-call-abi11-local-bindings",
        "schema_version": 1,
        "status": "PASS_LOCAL_TYPED_READBACK",
        "candidate_manifest_sha256": manifest_sha,
        "candidate_total": result["totals"]["direct_candidate_pairs_total"],
        "candidate_selected_before_fix": result["totals"]["selected_calls"],
        "candidate_open_issue_total": len(issues),
        "local_bindings": output,
        "prior_explicit_receiver_recheck": prior_recheck,
        "summary": {
            "issue_count": len(issues),
            "typed_bindings": len(output),
            "prior_explicit_receiver_rechecks": 1,
            "prior_explicit_receiver_roundtrip_and_equality": True,
            "call_opcode_counts": dict(Counter(item["call_opcode"] for item in output)),
            "target_kind_counts": dict(Counter(item["target_kind"] for item in output)),
            "explicit_argument_ports": sum(item["explicit_argument_count"] for item in output),
            "receiver_ports": sum(item["receiver_parameter_index"] is not None for item in output),
            "all_codec_roundtrips": all(item["codec_roundtrip"] for item in output),
            "whole_201_reader_rerun": False,
            "whole_operand_sha_rehashed": False,
            "whole_frame_sha_rehashed": False,
            "full_attempt_denominator_connected": False,
            "receiver_identity_established": False,
            "normal_return_or_ready_established": False,
            "default_runtime_values_established": False,
            "proof_owner_restored": False,
        },
        "local_read_receipts": {
            "operand": operand_receipt,
            "frame": frame_receipt,
            "prior_operand": prior_operand_receipt,
            "prior_frame": prior_frame_receipt,
            "operand_metadata": {"path": operand_meta_ref["path"],
                "sha256": operand_meta_ref["raw_sha256"], "bytes": len(operand_meta_raw)},
            "frame_metadata": {"path": frame_meta_ref["path"],
                "sha256": frame_meta_ref["raw_sha256"], "bytes": len(frame_meta_raw)},
        },
        "normal_source_inputs": {
            "source_report": {"path": str(inputs.report_path), "sha256": inputs.report_sha256},
            "bindings": {"path": str(inputs.bindings_path), "sha256": inputs.binding_sha256},
            "source_body_reads": dict(inputs.stats),
        },
        "scope_note": "Only the eleven prior open candidates plus one receipt-selected prior explicit-receiver binding and their local intervals were reread."
    }
    out = Path(args.output).absolute()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("xb") as stream:
        stream.write(canonical(payload) + b"\n")
    print(json.dumps({"status": payload["status"], "bindings": len(output),
        "operand_read_bytes": operand_receipt["bounded_returned_bytes"],
        "frame_read_bytes": frame_receipt["bounded_returned_bytes"],
        "output": str(out), "output_sha256": hashlib.sha256(out.read_bytes()).hexdigest()},
        sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", default="/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/analysis/source_call_port_all_20261027/RESULT.json")
    parser.add_argument("--manifest", default="/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/analysis/source_call_port_all_20261027/publication/manifest.json")
    parser.add_argument("--expected-manifest-sha256", default="867a8fa08f97977ccf8aba2add85cd2544691f8aff1c61bcc685dc61160bfb8d")
    parser.add_argument("--issue-summary", default=str(Path(__file__).with_name("issue-event-summary.json")))
    parser.add_argument("--frame-lookback", type=int, default=1024)
    parser.add_argument("--prior-positional-attempt-index", type=int, default=59197)
    parser.add_argument("--prior-frame-lookback", type=int, default=1024)
    parser.add_argument("--output", default=str(Path(__file__).with_name("local-bindings-replay.json")))
    args = parser.parse_args()
    if args.frame_lookback < 1 or args.frame_lookback > 8192:
        raise ValueError("frame lookback must remain a small bounded local window")
    if (args.prior_positional_attempt_index < 1 or args.prior_frame_lookback < 1
            or args.prior_frame_lookback > 8192):
        raise ValueError("prior selected record and frame lookback must remain positive and bounded")
    build(args)


if __name__ == "__main__":
    main()
