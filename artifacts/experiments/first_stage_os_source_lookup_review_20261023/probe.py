"""Read-only bounded positive lookup; no manual actor or ordinal input."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import resource
import subprocess
import time

from scar.ir.execution.resources import ProviderHandle
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import decode, encode
from scar.trace.os_resource_refinement import OSResourceBase, OSResourceRefinement
from scar.trace.os_resources import _clone_flags


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXP = ROOT / "artifacts/experiments"
MAX_LOOKUP_QUERIES = 4


def digest(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def write(name, value):
    with (HERE / name).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, ensure_ascii=False)
        stream.write("\n")


def main():
    started = time.monotonic()
    capture = EXP / "first_stage_lewm_physical_20261023"
    r1 = EXP / "first_stage_os_interface_work_20261023/result"
    paths = {"archive": capture / "archive-index.json", "coords": r1 / "capture-coordinates.json",
        "r1": r1 / "interfaces/manifest.json",
        "r2": EXP / "first_stage_os_resource_refinement_20261023/gate-attempt01/result/manifest.json",
        "context_events": EXP / "first_stage_fd_table_projection_20261023/context-events.json"}
    inputs = {name: json.loads(path.read_text()) for name, path in paths.items()}
    receipts = {name: digest(path) for name, path in paths.items()}
    write("producer.json", {"revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "script": digest(Path(__file__)), "inputs": receipts, "budget_lookup_queries": MAX_LOOKUP_QUERIES,
        "source_order_hint": digest(ROOT / "scar/trace/os_resources.py"), "no_manual_actor_or_ordinal_arguments": True})
    archive, coords = inputs["archive"], inputs["coords"]
    assert receipts["archive"]["sha256"] == coords["seed"]["archive_sha256"]
    assert coords["run"] == inputs["r1"]["run"] == inputs["r2"]["run"]
    binding = inputs["r1"]["protocol_document"]["contract"]["coordinate_binding"]
    assert (binding["uri"], binding["sha256"], binding["size_bytes"]) == (receipts["coords"]["path"], receipts["coords"]["sha256"], receipts["coords"]["bytes"])
    entries = {row["logical_path"]: row for row in archive["files"]}
    by_actual = {row["actual_path"]: row for row in archive["files"]}
    base = OSResourceBase(paths["r1"], cached_chunks=2)
    r2 = OSResourceRefinement.read(base, paths["r2"])
    artifacts = [decode(ProviderArtifact, row["record"]) for row in base.reader.iter_records("artifacts")]
    by_logical, actual_to_index = {}, {}
    for index, artifact in enumerate(artifacts):
        entry = by_actual[artifact.uri]
        assert (artifact.sha256, artifact.size_bytes, artifact.schema) == (entry["raw_sha256"], entry["raw_bytes"], "strace.syscalls.text.v1")
        assert entry["logical_path"] not in by_logical
        by_logical[entry["logical_path"]] = (index, entry)
        actual_to_index[artifact.uri] = index
    threads = {row["tid"]: row for row in coords["threads"]}
    membership = {row["artifact"]["uri"]: row for row in coords["membership"] if row["artifact"]["schema"] == "strace.syscalls.text.v1"}
    groups, anchors = {}, defaultdict(set)
    for identity, (ordinal, handle) in r2.handles.items():
        assert type(handle.handle) is ProviderHandle
        index = actual_to_index[handle.source.artifact.uri]
        entry = by_actual[handle.source.artifact.uri]
        line = int(re.fullmatch(r"#/lines/([1-9][0-9]*)", handle.source.locator)[1])
        native_tid = int(re.fullmatch(r"syscalls\.([1-9][0-9]*)", Path(entry["logical_path"]).name)[1])
        if native_tid in threads:
            member = membership[entry["logical_path"]]
            assert member["local_path"] == entry["actual_path"] and member["thread"] == threads[native_tid]["id"]
            assert member["process"] == threads[native_tid]["process"]
            assert (member["artifact"]["sha256"], member["artifact"]["size_bytes"]) == (entry["raw_sha256"], entry["raw_bytes"])
            assert handle.start.process.wire == member["process"]["wire"]
        group = groups.setdefault(entry["logical_path"], {"native_tid": native_tid, "source": entry,
            "handles": [], "first_selected_line": line, "last_selected_line": line})
        group["handles"].append(encode(identity)); group["first_selected_line"] = min(group["first_selected_line"], line)
        group["last_selected_line"] = max(group["last_selected_line"], line)
        anchors[index].add((line, handle.handle.selector.ordinal))
    needs, frontiers = [], []
    for logical, group in sorted(groups.items()):
        thread = threads.get(group["native_tid"])
        if thread is None:
            frontiers.append({"group": logical, "reason": "NO_OWN_BIRTH_COORDINATE", "scope": "creator context remains separately qualified"})
            continue
        source = thread["source"]
        index, entry = by_logical[source["artifact"]["uri"]]
        assert source["artifact"] == {"uri": entry["logical_path"], "sha256": entry["raw_sha256"], "size_bytes": entry["raw_bytes"], "schema": "strace.syscalls.text.v1"}
        line = int(re.fullmatch(r"#/lines/([1-9][0-9]*)", source["locator"])[1])
        prior_execs = [row["source"] for row in inputs["context_events"] if row["syscall"] in ("execve", "execveat")
            and row["result"] == 0 and row["source"]["artifact"]["uri"] == logical
            and int(row["source"]["locator"].rsplit("/", 1)[1]) < group["first_selected_line"]]
        target_exec = coords["seed"]["target_exec"]
        if target_exec["artifact"]["uri"] == logical and int(target_exec["locator"].rsplit("/", 1)[1]) < group["first_selected_line"]:
            prior_execs.append(target_exec)
        needs.append({"group": logical, "child_thread": thread, "birth_source": source,
            "source_artifact_index": index, "source_line": line,
            "consumer_need": "POST_EXEC_ANCHOR_ALREADY_AVAILABLE" if prior_execs else "PRE_EXEC_BIRTH_REQUIRED"})
    queries, matches = [], []
    for need in needs:
        candidates = anchors[need["source_artifact_index"]]
        if not candidates:
            frontiers.append({"group": need["group"], "reason": "NO_SPARSE_ANCHOR_IN_BIRTH_SOURCE_ARTIFACT"}); continue
        anchor_line, anchor_ordinal = min(candidates, key=lambda pair: abs(pair[0]-need["source_line"]))
        candidate = anchor_ordinal + need["source_line"] - anchor_line
        if not 0 <= candidate < base.manifest["tables"]["observations"]["records"] or len(queries) >= MAX_LOOKUP_QUERIES:
            frontiers.append({"group": need["group"], "reason": "QUERY_BUDGET_OR_CANDIDATE_RANGE"}); continue
        selector = base.selector("observations", candidate)
        resolved = base.resolve(selector)
        row = resolved["record"]
        exact = row.get("source") == {"artifact": need["source_artifact_index"], "line": need["source_line"]}
        queries.append({"need": need["birth_source"], "hint_anchor": {"source_line": anchor_line, "observation_ordinal": anchor_ordinal},
            "candidate_selector": encode(selector), "exact_source_match": exact, "actual_source": row.get("source"),
            "locator": resolved["locator"], "row_sha256": resolved["row_sha256"]})
        if not exact:
            frontiers.append({"group": need["group"], "reason": "HEURISTIC_MISS_NOT_PROOF_OF_ABSENCE"}); continue
        assert row["syscall"] in ("clone", "clone3", "fork", "vfork") and row["result"] == need["child_thread"]["tid"]
        assert row["argument_rendering_complete"] is True
        flags = _clone_flags({"name": row["syscall"], "args": [str(value) for value in row["arguments"]]})
        assert flags is not None
        matches.append({"need": need, "selector": encode(selector), "record": row,
            "row_sha256": resolved["row_sha256"], "locator": resolved["locator"], "clone_flags": flags,
            "verification": resolved["verification"], "global_observation_source_uniqueness": "NOT_CLAIMED"})
    write("needs.json", needs); write("queries.json", queries); write("matches.json", matches)
    write("frontiers.json", frontiers)
    required = [need for need in needs if need["consumer_need"] == "PRE_EXEC_BIRTH_REQUIRED"]
    report = {"schema": "scar.os-source-lookup-read-review", "schema_version": 1, "status": "READ_ONLY_POSITIVE_LOOKUP",
        "selected_ports": len(r2.handles), "groups": len(groups), "generated_birth_needs": len(needs),
        "preexec_birth_needs": len(required), "positive_exact_matches": len(matches), "lookup_queries": len(queries),
        "query_budget": MAX_LOOKUP_QUERIES, "frontiers": frontiers,
        "max_unique_lookup_chunks": len({entry["candidate_selector"]["chunk"]["locator"] for entry in queries}),
        "manual_actor_or_ordinal_input": False, "global_source_order_or_uniqueness_proved": False,
        "consumer_v1_admits_at_most_one_preexec_child": True, "old_contexts_or_production_changed": False,
        "full_execution_model_semantics": "OPEN", "first_stage_complete": False,
        "elapsed_seconds": time.monotonic()-started, "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    write("summary.json", report)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
