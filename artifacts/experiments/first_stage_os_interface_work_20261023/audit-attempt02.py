"""Attempt02 continuation: exact archived unbound-actor exception; producer unchanged."""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import resource
import time

from scar.ir.execution.common import EvidencePoint, Unresolved
from scar.ir.execution.coordinates import ExecutionRun, HostThreadInstance, ProcessInstance
from scar.ir.execution.resources import EndedAt, HandleBinding, ResourceInstance
from scar.ir.execution.validity import TargetLifetimeEvent
from scar.ir.execution.work import DirectExecution, ExternalWorkSource, ResourceOutcome, WorkOutcomeKind, WorkSubmission
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import decode, encode
from scar.ir.v2.common import Completeness
from scar.trace.os_resources import OSInterfacePartitions

BASE = Path(__file__).resolve().parent
RESULT = BASE / "result"
CAPTURE = BASE.parent / "first_stage_lewm_physical_20261023"
START = time.monotonic()


def write(name, value):
    (BASE / name).write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def log(event, **fields):
    row = {"event": event, "elapsed_seconds": time.monotonic() - START,
           "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, **fields}
    with (BASE / "audit-attempt02.progress.jsonl").open("a") as stream:
        stream.write(json.dumps(row, sort_keys=True) + "\n")
    print(json.dumps(row, sort_keys=True), flush=True)


def exhausted(iterator, label):
    try:
        next(iterator)
    except StopIteration:
        return
    raise AssertionError(label + " has extra records")


def fact(artifacts, selector):
    return ProviderFactReference(artifacts[selector["artifact"]], "#/lines/" + str(selector["line"]))


def main():
    def receipt(path):
        raw = path.read_bytes()
        return {"path": str(path), "stored_sha256": hashlib.sha256(raw).hexdigest(), "stored_bytes": len(raw)}
    repo = BASE.parents[2]
    audit_producer = {"scope": "ONE bounded audit, no target or importer replay", "script": receipt(Path(__file__)),
        "manifest": receipt(RESULT / "interfaces/manifest.json"),
        "modules": [receipt(repo / name) for name in ("scar/trace/os_resources.py", "scar/store/bundle_partitions.py",
            "scar/ir/record_codec.py", "scar/ir/execution/work.py", "scar/ir/execution/resources.py")],
        "first_stage_complete": False, "transformation_authorized": False,
        "continuation_of": {"script": receipt(BASE / "audit.py"), "failure_log": receipt(BASE / "audit.stderr.txt"),
            "diagnosis": receipt(BASE / "audit-membership-diagnosis.json")},
        "archive": receipt(CAPTURE / "archive-index.json")}
    assert audit_producer["modules"][0]["stored_sha256"] == "c52f45a62693e3e78875b3a23b7c56e0a4cdb48862436981f8d98941a4900c1b"
    with (BASE / "audit-attempt02-producer.json").open("x") as stream:
        stream.write(json.dumps(audit_producer, sort_keys=True, indent=2) + "\n")
    reader = OSInterfacePartitions(RESULT / "interfaces/manifest.json")
    manifest, counts, table_receipts = reader.manifest, Counter(), {}
    summary = manifest["summary"]
    coordinates = json.loads((RESULT / "capture-coordinates.json").read_bytes())
    assert encode(decode(ProviderArtifact, manifest["protocol_artifact"])) == manifest["protocol_artifact"]
    assert manifest["run"] == coordinates["run"]
    run_id = decode(ExecutionRun, manifest["run"]).id
    assert manifest["validation"]["quiescence_records_created"] == summary["quiescence_records"] == 0
    assert summary["physical_lines"] == 1_067_773 and summary["tid_artifacts"] == 253
    assert summary["legacy_syscall_observations"] == 915_204
    assert summary["legacy_outside_fd_profile_count"] == 152_564
    assert len(summary["legacy_outside_fd_profile_by_syscall"]) == 40
    original_frontiers = json.loads((BASE.parent / "first_stage_joined_physical_20261023/resource-frontiers.json").read_bytes())
    expected_outside = {row["syscall"]: row["count"] for row in original_frontiers["outside_fd_profile"]}
    assert expected_outside == summary["legacy_outside_fd_profile_by_syscall"]
    artifacts, processes, threads, resources, handles = [], {}, {}, {}, {}
    gap_groups, gap_occurrences = Counter(), Counter()
    fd_argument_gap_sources = set()
    line_reasons, classifications = Counter(), Counter()
    types = {"artifacts": ProviderArtifact, "processes": ProcessInstance, "threads": HostThreadInstance,
             "resources": ResourceInstance, "handles": HandleBinding, "target_lifetime_events": TargetLifetimeEvent}
    # These eight tables are consumed once in full through the public reader.
    for table in ("artifacts", "processes", "threads", "resources", "handles", "target_lifetime_events", "gaps", "line_classifications"):
        log("TABLE_BEGIN", table=table)
        for envelope in reader.iter_records(table):
            counts[table] += 1
            row = envelope["record"]
            if table in types:
                typed = decode(types[table], row)
                assert encode(typed) == row
            if table == "artifacts":
                artifacts.append(typed)
            elif table == "processes":
                assert typed.run == run_id
                assert row in coordinates["processes"]
                processes[typed.id.wire] = typed
            elif table == "threads":
                assert typed.process.wire in processes and row in coordinates["threads"]
                threads[typed.tid] = typed
            elif table == "resources":
                assert typed.id.wire not in resources
                resources[typed.id.wire] = typed
            elif table == "handles":
                assert typed.target.instance.wire in resources
                assert typed.id.wire not in handles
                handles[typed.id.wire] = typed
            elif table == "target_lifetime_events":
                assert typed.target.instance.wire in resources
            elif table == "gaps":
                gap_groups[row["code"]] += 1; gap_occurrences[row["code"]] += row["occurrences"]
                if row["code"] == "fd_argument_open":
                    fd_argument_gap_sources.add(json.dumps(row["source"], sort_keys=True))
            else:
                classifications[row[2]] += 1
                if row[4] is not None:
                    line_reasons[row[4]] += 1
            table_receipts.setdefault(table, {"first": envelope["locator"], "last": None})["last"] = envelope["locator"]
            if counts[table] % 200_000 == 0:
                log("TABLE_ROWS", table=table, records=counts[table])
        assert counts[table] == manifest["tables"][table]["records"]
        log("TABLE_END", table=table, records=counts[table])
    assert dict(classifications) == summary["classification_counts"]
    assert line_reasons["outside_fd_profile"] == 152_564
    assert sum(gap_groups.values()) == summary["gap_groups"]
    assert sum(gap_occurrences.values()) == summary["gap_occurrences"]
    # Match only the exact logical/retained physical path plus decoded receipt.
    # A hash or bare PID alone never establishes artifact/process membership.
    archive_payload = (CAPTURE / "archive-index.json").read_bytes()
    archive = json.loads(archive_payload)
    assert archive["schema"] == "scar.lossless-capture-archive" and archive["schema_version"] == 1
    assert archive["verified_roundtrip"] is True
    assert hashlib.sha256(archive_payload).hexdigest() == coordinates["seed"]["archive_sha256"]
    assert hashlib.sha256(archive_payload).hexdigest() == coordinates["retention"]["archive_sha256"]
    profile = manifest["protocol_document"]
    assert profile["schema"] == "scar.os-resource-profile" and profile["schema_version"] == 2
    artifact_process, unbound_archive_receipts = {}, []
    for index, artifact in enumerate(artifacts):
        members = [row for row in coordinates["membership"]
                   if artifact.uri in (row["artifact"]["uri"], row.get("local_path"))
                   and (artifact.sha256, artifact.size_bytes, artifact.schema)
                       == (row["artifact"]["sha256"], row["artifact"]["size_bytes"], row["artifact"]["schema"])]
        assert len(members) <= 1
        if members:
            member_process = members[0]["process"]
            artifact_process[index] = member_process["wire"] if member_process is not None else None
        else:
            # Not a generic missing-member fallback. Exact retained/local and
            # logical archive receipt, OS schema and original actor declaration
            # must all identify the same explicitly OPEN actor.
            entries = [entry for entry in archive["files"]
                       if entry["actual_path"] == artifact.uri
                       and (entry["raw_sha256"], entry["raw_bytes"]) == (artifact.sha256, artifact.size_bytes)]
            declarations = [entry for entry in profile["contract"]["artifacts"] if entry["artifact"] == encode(artifact)]
            assert len(entries) == len(declarations) == 1
            entry, declaration = entries[0], declarations[0]
            assert artifact.schema == "strace.syscalls.text.v1"
            assert Path(entry["logical_path"]).parent == Path(coordinates["original_root"]) / "os"
            assert Path(entry["actual_path"]).parent == CAPTURE / "os"
            tid = declaration["tid"]
            assert Path(entry["logical_path"]).name == "syscalls." + str(tid)
            assert {"code": "os_actor_not_connected_to_target_ancestry", "tid": tid} in coordinates["open"]
            assert not [thread for thread in coordinates["threads"] if thread["tid"] == tid]
            assert not [member for member in coordinates["membership"]
                        if entry["logical_path"] in (member["logical_path"], member["artifact"]["uri"])]
            artifact_process[index] = None
            unbound_archive_receipts.append({"artifact_index": index, "artifact": encode(artifact),
                "archive_entry": entry, "tid": tid, "process": None,
                "basis": "exact archive SHA/path/raw receipt plus explicitly unconnected actor, never PID equality"})
    write("audit-attempt02-unbound-archive-receipts.json", unbound_archive_receipts)
    submissions = iter(reader.iter_records("submissions"))
    outcomes = iter(reader.iter_records("outcomes"))
    names, outside, nonreturns = Counter(), Counter(), Counter()
    examples, ports, process_open, failed_exec = {}, [], 0, 0
    last_entry = {}
    log("ALL_TYPED_WORK_CODEC_BEGIN")
    for envelope in reader.iter_records("observations"):
        row = envelope["record"]; counts["observations"] += 1
        assert row.get("interface_record") is True
        artifact_index = row["source"]["artifact"]
        assert row["process"] == artifact_process[artifact_index]
        process = processes[row["process"]].id if row["process"] is not None else None
        if process is None:
            process_open += 1
        assert row["canonical_stage"] == row["canonical_effect"] == "OPEN"
        assert row["dependency_coverage"] == row["effects_coverage"] == row["retention_coverage"] == "UNKNOWN"
        assert "receipt_timestamp" not in row and "return_timestamp" not in row and "end_ns" not in row
        assert "PRINTLEADER" in row["provider_line_point_kind"]
        for index in row["payload_argument_indices_omitted"]:
            assert row["arguments"][index] is None
        first = row["entry_source"]["line"]
        assert first > last_entry.get(artifact_index, 0)  # actual capture has only COMPLETED lines
        last_entry[artifact_index] = first
        sub_envelope = next(submissions); counts["submissions"] += 1
        sub = decode(WorkSubmission, sub_envelope["record"])
        assert encode(sub) == sub_envelope["record"]
        assert sub.id.value == row["work_ticket"]
        assert type(sub.origin) is ExternalWorkSource
        assert sub.origin.point == EvidencePoint(run_id, process, fact(artifacts, row["entry_source"]))
        assert sub.origin.source == sub.origin.point.source
        assert type(sub.scheduling) is DirectExecution
        if row["tid"] in threads:
            assert sub.scheduling.thread == threads[row["tid"]].id
        else:
            assert type(sub.scheduling.thread) is Unresolved
        assert type(sub.executor) is Unresolved and type(sub.retention) is Unresolved
        assert sub.dependencies == sub.effects == sub.materializations == ()
        assert sub.dependencies_coverage is sub.effects_coverage is sub.materializations_coverage is Completeness.UNKNOWN
        assert sub.source == fact(artifacts, row["source"])
        if row["ordinary_return"]:
            out_envelope = next(outcomes); counts["outcomes"] += 1
            out = decode(ResourceOutcome, out_envelope["record"])
            assert encode(out) == out_envelope["record"]
            assert out.ticket == sub.id
            assert out.observed_at == EvidencePoint(run_id, process, fact(artifacts, row["return_source"]))
            assert out.protocol_result == out.source == fact(artifacts, row["source"])
            assert out.kind is (WorkOutcomeKind.FAILED if row["result"] == -1 else WorkOutcomeKind.COMPLETED)
            assert out.effect_frontier == () and out.frontier_coverage is Completeness.UNKNOWN
            assert type(out.quiescence) is Unresolved
        else:
            nonreturns[row["nonreturn_protocol"]] += 1
            assert row["return_source"] is None
            assert row["syscall"] in ("exit", "exit_group", "execve", "execveat") or row["result"] is None
        names[row["syscall"]] += 1
        if row["legacy_outside_fd_profile"]:
            outside[row["syscall"]] += 1
        if row["syscall"] in ("execve", "execveat") and row["result"] == -1:
            failed_exec += 1
            assert row["fd_relation_status"] == "NOT_A_DESCRIPTOR_ARGUMENT_INTERFACE"
            assert json.dumps(encode(fact(artifacts, row["source"])), sort_keys=True) not in fd_argument_gap_sources
            examples.setdefault("failed_exec", {"observation": row, "locator": envelope["locator"]})
        created = row.get("created_handles", [])
        if created:
            targets = [item["target"] for item in created]
            assert len(targets) == len(set(targets))
            for item in created:
                assert item["target"] in resources and item["binding"] in handles
                assert handles[item["binding"]].target.instance.wire == item["target"]
            if row["syscall"] in ("pipe", "pipe2"):
                assert len(created) == 2 and [item["port"] for item in created] == ["read_end", "write_end"]
                assert created[0]["fd"] != created[1]["fd"]
            ports.extend({"syscall": row["syscall"], "source": row["source"], **item} for item in created)
        if row["syscall"] in ("pipe2", "eventfd2", "epoll_create1", "stat", "mmap", "poll", "exit_group"):
            examples.setdefault(row["syscall"], {"observation": row, "locator": envelope["locator"]})
        for table, selected_envelope in (("observations", envelope), ("submissions", sub_envelope)):
            table_receipts.setdefault(table, {"first": selected_envelope["locator"], "last": None})["last"] = selected_envelope["locator"]
        if row["ordinary_return"]:
            table_receipts.setdefault("outcomes", {"first": out_envelope["locator"], "last": None})["last"] = out_envelope["locator"]
        if counts["observations"] % 10_000 == 0:
            log("TYPED_WORK_ROWS", observations=counts["observations"], submissions=counts["submissions"], outcomes=counts["outcomes"])
    exhausted(submissions, "submissions"); exhausted(outcomes, "outcomes")
    for table in manifest["tables"]:
        assert counts[table] == manifest["tables"][table]["records"], table
    assert names == Counter(summary["interface_counts"]) and outside == Counter(expected_outside)
    assert nonreturns == Counter(summary["nonreturn_protocol_counts"])
    assert process_open == summary["process_coordinate_open"]
    assert len(ports) == summary["actual_fd_producer_ports"]
    # Read only a few selected original source lines, not another full raw scan.
    requested = {}
    for name, example in examples.items():
        selector = example["observation"]["source"]
        requested.setdefault(selector["artifact"], {}).setdefault(selector["line"], []).append(name)
    for index, line_names in requested.items():
        path = Path(artifacts[index].uri)
        assert path.parent == CAPTURE / "os" and path.is_file() and not path.is_symlink()
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rb") as stream:
            for number, raw in enumerate(stream, 1):
                if number in line_names:
                    for name in line_names[number]:
                        example = examples[name]
                        assert (example["observation"]["syscall"] + "(").encode() in raw
                        example["raw_line_sha256"] = hashlib.sha256(raw).hexdigest()
                        example["original_artifact"] = encode(artifacts[index])
                        example["original_line"] = number
                        example["raw_line_rendering"] = raw.decode().rstrip()[:1600]
                if number >= max(line_names):
                    break
    write("audit-attempt02-query-results.json", examples)
    write("audit-attempt02-table-receipts.json", table_receipts)
    write("audit-attempt02-producer-ports.json", ports)
    final = {"status": "PASS", "scope": "all11 tables bytes/counts + all typed work codecs/local references",
             "counts": dict(counts), "byte_receipts": "PASS: every published chunk fully verified before yield",
             "all_typed_work_public_codecs": "PASS", "typed_work_local_evidence_links": "PASS",
             "full_execution_model_semantics": "OPEN, not performed or inferred",
             "legacy_outside": dict(outside), "interface_names": dict(names), "nonreturn_protocols": dict(nonreturns),
             "gap_groups": dict(gap_groups), "gap_occurrences": dict(gap_occurrences),
             "failed_exec_receipts": failed_exec, "producer_ports": len(ports), "process_coordinate_open": process_open,
             "legacy_process_coordinate_open": summary["legacy_process_coordinate_open"],
             "manifest_receipt": reader.manifest_receipt, "source_summary": summary,
             "unbound_archive_receipts": unbound_archive_receipts,
             "audit_attempt": 2, "attempt01_failed_and_preserved": True,
             "elapsed_seconds": time.monotonic() - START,
             "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
             "quiescence_records": 0, "whole_model_established": False,
             "first_stage_complete": False, "transformation_authorized": False}
    write("audit-attempt02-summary.json", final)
    log("PASS", summary=final)


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        log("FAILED", error_type=type(error).__name__, detail=str(error))
        raise
