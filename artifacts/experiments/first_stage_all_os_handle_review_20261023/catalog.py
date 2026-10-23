"""Read all existing small handle/resource tables, not million work tables."""
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import re
import resource
import subprocess
import time

from scar.trace.os_resources import OSInterfacePartitions


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXP = ROOT / "artifacts/experiments"


def digest(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def write(name, value):
    with (HERE / name).open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def progress(phase, **fields):
    print(json.dumps({"phase": phase, **fields}, sort_keys=True), flush=True)


def main():
    started = time.monotonic()
    r1 = EXP / "first_stage_os_interface_work_20261023/result"
    paths = {"r1": r1 / "interfaces/manifest.json", "coordinates": r1 / "capture-coordinates.json",
        "archive": EXP / "first_stage_lewm_physical_20261023/archive-index.json",
        "contexts": EXP / "first_stage_os_source_lookup_20261023/gate-attempt01/result/manifest.json",
        "events": EXP / "first_stage_fd_table_projection_20261023/context-events.json"}
    docs = {name: json.loads(path.read_text()) for name, path in paths.items()}
    receipts = {name: digest(path) for name, path in paths.items()}
    write("producer.json", {"script": digest(Path(__file__)), "inputs": receipts,
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "scope": "all original handles/resources public bytes and explicit wire source joins; not full codec/model validation"})
    reader = OSInterfacePartitions(paths["r1"])
    manifest, coords, contexts = docs["r1"], docs["coordinates"], docs["contexts"]
    assert docs["archive"] and receipts["archive"]["sha256"] == coords["seed"]["archive_sha256"]
    assert contexts["base"]["sha256"] == receipts["r1"]["sha256"]
    actual = {row["actual_path"]: row for row in docs["archive"]["files"]}
    native = {}
    artifacts = list(reader.iter_records("artifacts"))
    for envelope in artifacts:
        source = envelope["record"]; entry = actual[source["uri"]]
        assert (source["sha256"], source["size_bytes"], source["schema"]) == (entry["raw_sha256"], entry["raw_bytes"], "strace.syscalls.text.v1")
        native[source["uri"]] = {"artifact_index": envelope["ordinal"], "entry": entry,
            "native_tid": int(re.fullmatch(r"syscalls\.([1-9][0-9]*)", Path(entry["logical_path"]).name)[1])}
    threads = {row["tid"]: row for row in coords["threads"]}
    selected = {row["replacement"]["id"]["wire"]: row["replacement"] for row in contexts["handle_refinements"]}
    assert len(selected) == 35
    context_proofs = contexts["context_proofs"]
    registry, resource_kinds, resources_by_actor = {}, Counter(), Counter()
    for envelope in reader.iter_records("resources"):
        row = envelope["record"]; source = row["source"]; actor = native[source["artifact"]["uri"]]
        assert source["artifact"]["sha256"] == actor["entry"]["raw_sha256"]
        assert row["id"]["wire"] not in registry
        registry[row["id"]["wire"]] = {"ordinal": envelope["ordinal"], "source": source,
            "native_tid": actor["native_tid"], "kind": row["kind"], "role": row["role"]}
        resource_kinds[(row["kind"], row["role"])] += 1; resources_by_actor[actor["native_tid"]] += 1
        if len(registry) % 4000 == 0:progress("RESOURCES", records=len(registry))
    assert len(registry) == manifest["tables"]["resources"]["records"] == 12683
    summaries, statuses, source_bins, target_uses = {}, Counter(), Counter(), Counter()
    ended, targets_same_source, source_actor_unknown = 0, 0, 0
    raw_sha, raw_bytes, written = hashlib.sha256(), 0, 0
    chunk_lookup = {row["uri"]: i for i, row in enumerate(manifest["tables"]["handles"]["chunks"])}
    with (HERE / "handles.jsonl.gz").open("xb") as raw_output:
        with gzip.GzipFile(fileobj=raw_output, mode="wb", filename="", mtime=0) as output:
            for envelope in reader.iter_records("handles"):
                row = envelope["record"]; source = row["source"]; actor = native[source["artifact"]["uri"]]
                line = int(re.fullmatch(r"#/lines/([1-9][0-9]*)", source["locator"])[1])
                assert source["artifact"]["sha256"] == actor["entry"]["raw_sha256"]
                target = registry[row["target"]["instance"]["wire"]]
                tid = actor["native_tid"]; thread = threads.get(tid)
                expected_process = thread["process"] if thread is not None else None
                assert row["start"]["process"] == expected_process and row["start"]["run"] == contexts["run"]["id"]
                logical = actor["entry"]["logical_path"]
                group = summaries.setdefault(tid, {"native_tid": tid, "logical_source": logical, "handles": 0,
                    "min_line": line, "max_line": line, "coordinate_process_known": thread is not None,
                    "container_statuses": Counter(), "ended": 0, "source_differs_from_target_origin": 0})
                group["handles"] += 1; group["min_line"] = min(group["min_line"], line); group["max_line"] = max(group["max_line"], line)
                known = selected.get(row["id"]["wire"])
                candidate = [proof for proof in context_proofs if proof["interval"]["artifact"]["uri"] == logical
                    and proof["interval"]["first_selected_line"] <= line <= proof["interval"]["last_selected_line"]]
                assert len(candidate) <= 1
                if known is not None:
                    status = "TYPED_CONTAINER_CONNECTED"
                    container = known["handle"]["container"]["instance"]
                elif candidate:
                    status = "WITHIN_EXISTING_PROOF_INTERVAL_NOT_CONNECTED"
                    container = None
                else:
                    status = "OUTSIDE_EXISTING_SELECTED_PROOF_INTERVAL"
                    container = None
                statuses[status] += 1; group["container_statuses"][status] += 1
                is_ended = "reason" not in row["end"]
                ended += is_ended; group["ended"] += is_ended
                same_source = source == target["source"]
                targets_same_source += same_source
                group["source_differs_from_target_origin"] += not same_source
                source_actor_unknown += thread is None
                source_bins[(tid, (line//10000)*10000)] += 1
                target_uses[row["target"]["instance"]["wire"]] += 1
                item = {"handle_ordinal": envelope["ordinal"], "id": row["id"],
                    "original_locator": {"table": "handles", "chunk": chunk_lookup[envelope["locator"]["artifact"]["uri"]],
                        "line": envelope["locator"]["line"], "pointer_within_line": "/record"},
                    "source": {"artifact_index": actor["artifact_index"], "physical_line": line},
                    "native_actor": tid, "coordinate_process": expected_process,
                    "target_resource_ordinal": target["ordinal"], "target_origin_actor": target["native_tid"],
                    "container_status": status, "selected_container": container,
                    "within_existing_interval_resource": candidate[0]["resource"] if candidate else None,
                    "observed_handle_end": is_ended, "target_origin_same_source": same_source,
                    "original_endpoint_kind": "UNRESOLVED_HANDLE" if "gap" in row["handle"] else "OTHER"}
                payload = (json.dumps(item, sort_keys=True, separators=(",",":"), ensure_ascii=False)+"\n").encode()
                assert len(payload) <= 16384 and raw_bytes+len(payload) <= 20_000_000
                output.write(payload); raw_sha.update(payload); raw_bytes += len(payload); written += 1
                if written % 4000 == 0:progress("HANDLES", records=written)
    assert written == manifest["tables"]["handles"]["records"] == 12684
    assert ended == manifest["summary"]["observed_handle_ends"]
    report = {"schema":"scar.all-os-handle-read-review","schema_version":1,"status":"READ_ONLY_SMALL_TABLE_WIRE_CATALOG",
        "resources":len(registry),"handles":written,"native_actor_groups":len(summaries),
        "resource_kinds":[{"kind":k,"role":r,"count":n} for (k,r),n in resource_kinds.items()],
        "resources_by_actor":dict(resources_by_actor),"handles_by_actor":list(summaries.values()),
        "container_statuses":dict(statuses),"observed_ends":ended,"unresolved_ends":written-ended,
        "coordinate_process_unresolved_handles":source_actor_unknown,
        "handle_source_same_as_target_origin":targets_same_source,
        "existing_resources_with_multiple_handles":sum(n>1 for n in target_uses.values()),
        "source_bins":[{"native_tid":tid,"first_line":line,"last_line":line+9999,"handles":n} for (tid,line),n in sorted(source_bins.items())],
        "catalog":{"receipt":digest(HERE/'handles.jsonl.gz'),"decoded_bytes":raw_bytes,"decoded_sha256":raw_sha.hexdigest(),"lines":written},
        "validation_scope":"all small table public chunk hashes/ordinals + explicit wire source/process/target joins; not full public codecs/model",
        "handles_resources_decoded_bytes":sum(c['decoded_bytes'] for t in ['handles','resources'] for c in manifest['tables'][t]['chunks']),
        "observations_or_work_table_scanned":False,"main_raw_read":False,"production_changed":False,
        "full_execution_model_semantics":"OPEN","first_stage_complete":False,
        "elapsed_seconds":time.monotonic()-started,"peak_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    write("summary.json",report)
    progress("COMPLETE", handles=written,resources=len(registry),groups=len(summaries),statuses=dict(statuses))


if __name__ == '__main__':
    main()
