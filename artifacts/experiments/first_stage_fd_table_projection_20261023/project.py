"""Bounded offline projection of the exact non-target OS artifact complement.

This is evidence, not an IR importer, FD-content interpreter or graph rewrite.
"""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import resource
import time

from scar.trace import os_resources as parser
from scar.trace.os_resources import OSInterfacePartitions


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXP = ROOT / "artifacts/experiments"
CAPTURE = EXP / "first_stage_lewm_physical_20261023"
R1 = EXP / "first_stage_os_interface_work_20261023"
MAX_BYTES, MAX_LINES, MAX_LINE_BYTES = 12_000_000, 200_000, 16_384
RELEVANT = frozenset(("execve", "execveat", "clone", "clone3", "fork", "vfork", "unshare", "close_range"))


def need(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    sha, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(65536), b""):
            sha.update(part)
            size += len(part)
    return {"path": str(path), "sha256": sha.hexdigest(), "bytes": size}


def document(path):
    need(path.stat().st_size <= 2_000_000, "metadata byte budget exceeded")
    return json.loads(path.read_text())


def write(name, value):
    with (HERE / name).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")


def progress(phase, **fields):
    print(json.dumps({"phase": phase, **fields}, sort_keys=True), flush=True)


def main():
    started = time.monotonic()
    inputs = {"archive": CAPTURE / "archive-index.json",
        "coordinates": R1 / "result/capture-coordinates.json",
        "manifest": R1 / "result/interfaces/manifest.json",
        "summary": R1 / "result/summary.json",
        "audit": R1 / "audit-attempt03-summary.json",
        "audit_producer": R1 / "audit-attempt03-producer.json",
        "r2": EXP / "first_stage_os_resource_refinement_20261023/gate-attempt01/result/manifest.json"}
    docs = {name: document(path) for name, path in inputs.items()}
    receipts = {name: digest(path) for name, path in inputs.items()}
    archive, coords, manifest, summary, audit = (docs[name] for name in ("archive", "coordinates", "manifest", "summary", "audit"))
    need(receipts["archive"]["sha256"] == coords["seed"]["archive_sha256"]
         == coords["retention"]["archive_sha256"] == docs["audit_producer"]["archive"]["stored_sha256"],
         "archive is not the original shared capture receipt")
    need(receipts["manifest"]["sha256"] == audit["manifest_receipt"]["physical_sha256"]
         and receipts["manifest"]["bytes"] == audit["manifest_receipt"]["physical_bytes"], "audit/base manifest differs")
    need(audit["status"] == "PASS" and audit["all_work_wire_local_evidence_links"] == "PASS", "prior full-scope audit not established")
    need(summary == manifest["summary"] and audit["interface_names"] == summary["interface_counts"], "full-scope count versions differ")
    need(audit["counts"]["observations"] == manifest["tables"]["observations"]["records"]
         == sum(summary["interface_counts"].values()), "full-scope call denominator differs")
    need(coords["run"]["id"] == docs["r2"]["run"]["id"], "R2 is from a different Run")
    parser_receipt = digest(Path(parser.__file__).resolve())
    need(parser_receipt["sha256"] == "c52f45a62693e3e78875b3a23b7c56e0a4cdb48862436981f8d98941a4900c1b", "frozen parser producer differs")
    need(coords["profile"] == "RETAINED_COLLECTOR_PROCESS_MEMBERSHIP_V1", "unsupported membership profile")
    entries = [row for row in archive["files"] if Path(row["logical_path"]).parent == CAPTURE / "os"]
    need(len(entries) == len({row["logical_path"] for row in entries}) == len({row["actual_path"] for row in entries}) == 253,
         "OS archive exact source scope is not 253 unique logical/local artifacts")
    for row in entries:
        need(re.fullmatch(r"syscalls\.[1-9][0-9]*", Path(row["logical_path"]).name)
             and Path(row["actual_path"]).parent == CAPTURE / "os", "unsupported OS artifact address")
    need({str(path) for path in (CAPTURE / "os").iterdir() if path.is_file()} == {row["actual_path"] for row in entries},
         "OS directory and retained exact archive scope differ")
    main_source = coords["seed"]["target_exec"]["artifact"]
    main_entry = [row for row in entries if row["logical_path"] == main_source["uri"]]
    need(len(main_entry) == 1 and (main_entry[0]["raw_sha256"], main_entry[0]["raw_bytes"])
         == (main_source["sha256"], main_source["size_bytes"]), "main source lacks exact original archive membership")
    main_entry = main_entry[0]
    selected = sorted([row for row in entries if row is not main_entry], key=lambda row: row["logical_path"])
    need(len(selected) == 252 and sum(row["raw_bytes"] for row in selected) == 9_264_445 <= MAX_BYTES,
         "non-main complement/budget differs")
    reader = OSInterfacePartitions(inputs["manifest"])
    artifact_rows = list(reader.iter_records("artifacts"))
    need(len(artifact_rows) == 253, "R1 artifact table denominator differs")
    by_actual = {row["actual_path"]: row for row in entries}
    for envelope in artifact_rows:
        fact = envelope["record"]
        need(fact["uri"] in by_actual, "R1 source lacks exact archive local URI")
        row = by_actual[fact["uri"]]
        need((fact["sha256"], fact["size_bytes"], fact["schema"]) ==
             (row["raw_sha256"], row["raw_bytes"], "strace.syscalls.text.v1"), "R1/archive source identity differs")
    memberships = {}
    for row in coords["membership"]:
        if row["artifact"]["schema"] == "strace.syscalls.text.v1":
            memberships.setdefault(row["artifact"]["uri"], []).append(row)
    unknown_actors = {row["tid"] for row in coords["open"] if row["code"] == "os_actor_not_connected_to_target_ancestry"}
    threads = {row["tid"]: row for row in coords["threads"]}
    processes = {row["id"]["wire"]: row for row in coords["processes"]}
    main_process = coords["target_process"]["wire"]
    all_counts, classes, events, frontiers, render_gaps, files = Counter(), Counter(), [], [], [], []
    total_bytes = total_lines = 0
    progress("SCOPE_VERIFIED", files=252, expected_decoded_bytes=9_264_445)
    for number, entry in enumerate(selected, 1):
        tid = int(Path(entry["logical_path"]).name.rsplit(".", 1)[1])
        members = memberships.get(entry["logical_path"], [])
        need(len(members) <= 1, "ambiguous coordinate actor membership")
        if members:
            member = members[0]
            need(member["local_path"] == entry["actual_path"]
                 and (member["artifact"]["sha256"], member["artifact"]["size_bytes"]) ==
                     (entry["raw_sha256"], entry["raw_bytes"]), "coordinate exact artifact receipt differs")
            need(tid in threads and member["thread"] == threads[tid]["id"]
                 and member["process"] == threads[tid]["process"], "coordinate native actor binding differs")
        else:
            need(tid in unknown_actors and tid == 369747, "arbitrary missing actor membership")
        stored = digest(Path(entry["actual_path"]))
        need((stored["sha256"], stored["bytes"]) == (entry["gzip_sha256"], entry["compressed_bytes"]), "compressed OS receipt differs")
        raw_sha, decoded, lines, calls = hashlib.sha256(), 0, 0, Counter()
        with gzip.open(entry["actual_path"], "rb") as stream:
            while True:
                raw = stream.readline(MAX_LINE_BYTES + 1)
                if not raw:
                    break
                need(len(raw) <= MAX_LINE_BYTES and raw.endswith(b"\n"), "single-line budget or line termination failed")
                total_lines += 1; lines += 1; total_bytes += len(raw); decoded += len(raw); raw_sha.update(raw)
                need(total_bytes <= MAX_BYTES and total_lines <= MAX_LINES, "projection byte/line budget exceeded")
                text = raw.decode("utf-8").rstrip("\r\n")
                source = {"artifact": {"uri": entry["logical_path"], "sha256": entry["raw_sha256"],
                    "size_bytes": entry["raw_bytes"], "schema": "strace.syscalls.text.v1"}, "locator": "#/lines/" + str(lines)}
                timed = parser._TIME.match(text)
                if timed is None:
                    classes["UNRECOGNIZED"] += 1
                    frontiers.append({"source": source, "reason": "missing_time_prefix", "rendering": text}); continue
                body = timed[1]
                if body.startswith("--- "):
                    classes["SIGNAL"] += 1; continue
                if body.startswith("+++ "):
                    classes["PROVIDER_CONTEXT_MARKER"] += 1
                    frontiers.append({"source": source, "reason": "exit_or_leader_migration_provider_marker", "rendering": text}); continue
                unfinished, resumed = parser._UNFINISHED.match(body), parser._RESUMED.match(body)
                if unfinished or resumed:
                    match = unfinished or resumed
                    classes["UNFINISHED" if unfinished else "RESUMED"] += 1
                    frontiers.append({"source": source, "reason": "unfinished_or_resumed_not_reassembled", "syscall": match[1], "rendering": text}); continue
                call = parser._CALL.match(body)
                if call is None:
                    classes["UNRECOGNIZED"] += 1
                    frontiers.append({"source": source, "reason": "unknown_completed_rendering", "rendering": text}); continue
                name, arguments, returned, tail = call.groups()
                classes["COMPLETED"] += 1; calls[name] += 1; all_counts[name] += 1
                if name not in RELEVANT:
                    continue
                result = parser._number(returned)
                try:
                    args = parser._arguments(arguments)
                    split = True
                except ValueError:
                    args, split = [], False
                flags = parser._clone_flags({"name": name, "args": args}) if name in parser._CLONE and split else None
                event = {"source": source, "tid": tid, "syscall": name, "result": result,
                    "result_rendering": returned, "arguments": args, "arguments_split": split,
                    "argument_rendering_complete": split and "..." not in arguments,
                    "clone_flags": flags, "rendering": text,
                    "coordinate_process": threads[tid]["process"] if tid in threads else None,
                    "actor_birth": threads[tid]["source"] if tid in threads else None}
                if not event["argument_rendering_complete"]:
                    render_gaps.append({"source": source, "syscall": name,
                        "flags_complete": flags is not None if name in parser._CLONE else None,
                        "result_known": result is not None})
                if not split or result is None or (name in parser._CLONE and result > 0 and flags is None):
                    frontiers.append({"source": source, "reason": "required_context_effect_field_incomplete", "event": event})
                if name in ("execve", "execveat") and result == 0:
                    if tid in threads:
                        process = processes[threads[tid]["process"]["wire"]]
                        event["coordinate_process_pid"] = process["pid"]
                        event["exec_affects_target_group"] = process["id"]["wire"] == main_process
                        event["leader_according_to_existing_birth_profile"] = process["pid"] == tid
                        if event["exec_affects_target_group"] or not event["leader_according_to_existing_birth_profile"]:
                            frontiers.append({"source": source, "reason": "exec_in_target_group_or_possible_leader_tid_migration", "event": event})
                    else:
                        event["exec_affects_target_group"] = "CONTEXT_ACTOR_AT_RECORDED_TARGET_BIRTH"
                        need(source == {"artifact": {"uri": entry["logical_path"], "sha256": entry["raw_sha256"],
                            "size_bytes": entry["raw_bytes"], "schema": "strace.syscalls.text.v1"}, "locator": "#/lines/1"},
                             "unbound actor exec is not the previously reviewed initial context exec")
                events.append(event)
        need((decoded, raw_sha.hexdigest()) == (entry["raw_bytes"], entry["raw_sha256"]), "raw OS receipt differs")
        files.append({"entry": entry, "lines": lines, "calls": dict(calls), "raw_and_stored_sha_verified": True,
                      "coordinate_membership": members[0] if members else None})
        if number % 32 == 0 or number == len(selected):
            progress("FILES_VERIFIED", files=number, lines=total_lines, decoded_bytes=total_bytes)
    full = Counter(summary["interface_counts"])
    need(set(all_counts) <= set(full) and all(all_counts[name] <= full[name] for name in all_counts), "complement count exceeds original full scope")
    need(total_bytes == 9_264_445 and len(files) == 252, "incomplete selected artifact complement")
    need(classes["COMPLETED"] == sum(all_counts.values()), "completed call conservation failed")
    subtraction = {name: full[name] - all_counts[name] for name in full}
    successful_exec = [event for event in events if event["syscall"] in ("execve", "execveat") and event["result"] == 0]
    failed_exec = [event for event in events if event["syscall"] in ("execve", "execveat") and event["result"] == -1]
    success_difference = summary["nonreturn_protocol_counts"]["EXEC_IMAGE_REPLACED"] - len(successful_exec)
    failure_difference = audit["failed_exec_receipts"] - len(failed_exec)
    table_switch_counts = {name: full.get(name, 0) for name in ("unshare", "close_range", "execveat")}
    proof = (not frontiers and subtraction.get("execve") == 1 and success_difference == 1
        and failure_difference == 0 and all(value == 0 for value in table_switch_counts.values()))
    need(digest(Path(parser.__file__).resolve()) == parser_receipt, "parser bytes changed during projection")
    write("file-receipts.json", files)
    write("context-events.json", events)
    report = {"schema": "scar.fd-table-complement-projection", "schema_version": 1,
        "status": "VERIFIED_RETAINED_SCOPE_PROJECTION", "main_context_continuity": "SUPPORTED_UNDER_CAPTURE_CONTRACT" if proof else "OPEN",
        "container_refinements_applied": 0, "currently_published_unresolved_containers": 35,
        "mechanically_bindable_selected_ports": 35 if proof else 4,
        "scope": {"exact_archive_os_files": 253, "excluded": main_entry, "verified_non_main_files": len(files),
            "lines": total_lines, "decoded_bytes": total_bytes, "calls": sum(all_counts.values()), "classifications": dict(classes)},
        "budgets": {"decoded_bytes": MAX_BYTES, "lines": MAX_LINES, "single_line_bytes": MAX_LINE_BYTES},
        "inputs": receipts, "parser": parser_receipt, "script": digest(Path(__file__)),
        "run": coords["run"], "full_scope_count_authority": "original R1 manifest + prior audit03, exact input SHA qualified",
        "non_main_interface_counts": dict(all_counts), "main_counts_by_exact_complement": subtraction,
        "non_main_successful_execs": len(successful_exec), "non_main_failed_execs": len(failed_exec),
        "main_successful_execs_by_complement": success_difference, "main_failed_execs_by_complement": failure_difference,
        "full_scope_table_switch_syscall_counts": table_switch_counts,
        "argument_rendering_frontiers": render_gaps, "blocking_frontiers": frontiers,
        "branch_notes": ["existing coordinate births, not numeric TID equality alone, qualify known process groups",
            "argument argv truncation remains explicit; successful exec table-unsharing effect needs actual result, not full argv",
            "CLONE_FILES retains the shared container; no FD contents, offsets or cross-thread total order inferred",
            "ImportedAt is observation, not physical allocation; no physical table created/freed/ready asserted"],
        "full_execution_model_semantics": "OPEN", "whole_model_established": False, "transformation_authorized": False,
        "elapsed_seconds": time.monotonic() - started, "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    write("summary.json", report)
    progress("COMPLETE", status=report["main_context_continuity"], ports=report["mechanically_bindable_selected_ports"],
             lines=total_lines, decoded_bytes=total_bytes, calls=sum(all_counts.values()), frontiers=len(frontiers))


if __name__ == "__main__":
    main()
