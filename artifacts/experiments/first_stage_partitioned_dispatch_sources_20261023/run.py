"""One retained 272038 source-v2/dispatch association, without target execution."""
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import threading
import time

from scar.analysis.dispatch_sources import bind_dispatch_sources, query_dispatch_source
from scar.analysis.program_composition import CompositionIndex
from scar.trace.capture_coordinates import bind_capture_coordinates


BASE = Path(__file__).resolve().parent
REPO = BASE.parents[2]
EXPERIMENTS = BASE.parent
SOURCE = EXPERIMENTS / "first_stage_partitioned_composition_bindings_20261023"
BRIDGE = EXPERIMENTS / "first_stage_joined_dispatch_20261023/result/native/dispatch-bridge.json.gz"
CAPTURE = EXPERIMENTS / "first_stage_lewm_dispatch_20261023"
EXPECTED_RUN = "capture:91a2ed5e3f92817799bd02fb2453dadd65ad28fbf4361165c31b881c371c0c66"
START = time.monotonic()
PHASE = "startup"
STOP = threading.Event()
LOCK = threading.Lock()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def receipt(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while part := stream.read(1_048_576):
            size += len(part)
            digest.update(part)
    return {"path": str(path), "stored_sha256": digest.hexdigest(), "stored_bytes": size}


def log(event, **fields):
    row = {"event": event, "phase": PHASE, "elapsed_seconds": round(time.monotonic() - START, 6),
           "pid": os.getpid(), "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, **fields}
    with LOCK:
        with (BASE / "progress.jsonl").open("a") as output:
            output.write(json.dumps(row, sort_keys=True) + "\n")
    print(json.dumps(row, sort_keys=True), flush=True)


def heartbeat():
    while not STOP.wait(20):
        log("HEARTBEAT", meaning="phase liveness only, not a semantic coverage counter")


def main():
    global PHASE
    modules = ["scar/analysis/dispatch_sources.py", "scar/analysis/program_composition.py",
               "scar/analysis/source_invocations.py", "scar/analysis/inventory_partitions.py",
               "scar/trace/capture_coordinates.py", "scar/ir/record_codec.py"]
    source_report = json.loads((SOURCE / "bindings/report.json").read_bytes())
    producer = {"revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
                "pid": os.getpid(), "script": receipt(Path(__file__)),
                "modules": [receipt(REPO / name) for name in modules],
                "inputs": [receipt(SOURCE / "composition/index.json.gz"), receipt(SOURCE / "bindings/report.json"),
                           receipt(SOURCE / "bindings/bindings.json"), receipt(SOURCE / "bindings/invocations.jsonl.gz"),
                           receipt(BRIDGE)],
                "scope": "ONE original272038 capture, no target/native replay/source prepare", "first_stage_complete": False}
    assert producer["modules"][0]["stored_sha256"] == "d15b156047f5ef2d7ae7cf52e551ccc084f37453f2f203d994316c0825de69e5"
    assert source_report["schema_version"] == 2 and source_report["run"]["id"]["value"] == EXPECTED_RUN
    (BASE / "producer.json").write_bytes(canonical(producer))
    patch = subprocess.check_output(["git", "diff", "--", "scar/analysis/dispatch_sources.py", "docs/DISPATCH_SOURCES.md"], cwd=REPO)
    (BASE / "implementation.patch").write_bytes(patch)
    log("START", revision=producer["revision"], source_schema=2, capture_run=EXPECTED_RUN)
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        PHASE = "capture-coordinate-original-byte-verification"
        phase_start = time.monotonic()
        coordinate_path = BASE / "capture-coordinates.json"
        coordinates = bind_capture_coordinates(CAPTURE, max_bytes=2_000_000_000,
            max_lines=2_000_000, profile_uri=str(coordinate_path))
        coordinate_path.write_bytes(coordinates.payload)
        assert coordinates.run.id.value == EXPECTED_RUN
        log("PHASE_END", duration_seconds=time.monotonic() - phase_start,
            members=len(coordinates.report["membership"]), processes=len(coordinates.processes), threads=len(coordinates.threads))
        PHASE = "explicit-partitioned-composition-open"
        composition = CompositionIndex(SOURCE / "composition/index.json.gz")
        log("PHASE_END", source_files=composition.inventory_file_count)
        PHASE = "schema2-original-source-dispatch-association"
        phase_start = time.monotonic()
        report = bind_dispatch_sources(SOURCE / "bindings", BRIDGE, coordinates, BASE / "result",
                                      composition_index=composition)
        log("PHASE_END", duration_seconds=time.monotonic() - phase_start, summary=report["summary"],
            source_scope=report["partitioned_source_scope_audit"])
        PHASE = "published-output-denominators-and-local-queries"
        counts, statuses, phases = Counter(), Counter(), Counter()
        namespaces, invocations, activations, markers = set(), set(), set(), set()
        samples = {}
        with gzip.open(BASE / "result/associations.jsonl.gz", "rb") as stream:
            digest, raw_bytes = hashlib.sha256(), 0
            for raw in stream:
                digest.update(raw); raw_bytes += len(raw)
                row = json.loads(raw)
                counts["rows"] += 1
                counts["qualified_slot_path_indices"] += len(row["qualified_slot_path_indices"])
                statuses[row["status"]] += 1; phases[row["phase"]] += 1
                assert row["direct_callsite_established"] is False
                assert row["relationship"] == "RETAINED_ANCESTOR_CONTEXT"
                assert row["marker_instance"] not in markers
                markers.add(row["marker_instance"])
                if row["region_namespace"] is not None:
                    counts["rows_with_namespace"] += 1
                    namespaces.add(canonical(row["region_namespace"]))
                    assert row["body"] is not None and row["body"]["namespace"] == row["region_namespace"]
                if row["invocation"] is not None:
                    invocations.add(canonical(row["invocation"]))
                if row["region_activation"] is not None:
                    counts["rows_with_activation"] += 1
                    activations.add(canonical(row["region_activation"]))
                samples.setdefault(row["status"], row["marker_instance"])
                if counts["rows"] % 20_000 == 0:
                    log("OUTPUT_ROWS", rows=counts["rows"])
        assert counts["rows"] == report["observations"]["rows"] == 79_592
        assert counts["qualified_slot_path_indices"] == 109_288
        assert (digest.hexdigest(), raw_bytes) == (report["observations"]["raw_sha256"], report["observations"]["raw_bytes"])
        assert dict(statuses) == {key: value for key, value in report["summary"].items()
                                 if key in ("UNRESOLVED", "RETAINED_INVOCATION_LINKED", "RETAINED_SOURCE_LINKED", "RETAINED_BODY_LINKED")}
        queries = {}
        binding_table = json.loads((SOURCE / "bindings/bindings.json").read_bytes())["bindings"]
        for status, marker in sorted(samples.items()):
            row = query_dispatch_source(BASE / "result", marker)
            query = {"marker_instance": marker, "row": row, "selected_output_row_hash_verified": True}
            if row["source_binding_reference"] is not None:
                ordinal = int(row["source_binding_reference"]["locator"].split("/")[-1])
                binding = binding_table[ordinal]
                query["original_definition_locator"] = binding["definition_locator"]
                if row["definition"] is not None:
                    fi = row["definition"]["file_index"]
                    original = composition.inventory_file(fi)
                    found = [index for index, item in enumerate(original["definitions"])
                             if item["id"] == row["definition"]["identity"]]
                    assert len(found) == 1
                    assert binding["definition_locator"] == composition.inventory_file_locator(fi, "/definitions/" + str(found[0]))
                    query["original_source_definition_locator_verified"] = True
                if row["body"] is not None:
                    body = row["body"]; ref = body["reference"]
                    raw_body = composition.inventory_body(ref["file_index"], ref["body_index"])
                    locators = composition.inventory_body_locators(ref["file_index"], ref["body_index"], raw_body["graph"])
                    assert body["canonical_locator"] == locators["graph_locator"]
                    assert body["inventory_locator"] == locators["inventory_locator"]
                    assert body["metadata_locator"] == locators["metadata_locator"]
                    assert row["region_namespace"] == locators["namespace"]
                    query["original_checkpoint_source_shard_namespace_verified"] = True
            queries[status] = query
        (BASE / "query-results.json").write_bytes(canonical(queries))
        summary = {"status": "PASS", "run": EXPECTED_RUN, "target_process_id": 272038,
            "source_schema_version": 2, "association_schema_version": report["schema_version"],
            "counts": dict(counts), "statuses": dict(statuses), "phases": dict(phases),
            "unique_markers": len(markers), "unique_retained_invocation_keys": len(invocations),
            "unique_region_namespaces": len(namespaces), "unique_activations": len(activations),
            "source_invocation_denominators": source_report["summary"],
            "source_audit": report["source_audit"], "partitioned_source_scope_audit": report["partitioned_source_scope_audit"],
            "frontiers": report["frontiers"], "source_frontiers": report["source_frontiers"],
            "upstream_dispatch_gaps": report["upstream_dispatch_gaps"], "query_statuses": sorted(queries),
            "query_results": receipt(BASE / "query-results.json"), "report": receipt(BASE / "result/report.json"),
            "elapsed_seconds": time.monotonic() - START,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "source_recompiled": False, "native_graph_reimported": False, "target_executed": False,
            "direct_python_operator_correspondence_established": False, "first_stage_complete": False,
            "transformation_authorized": False}
        (BASE / "summary.json").write_bytes(canonical(summary))
        log("PASS", summary=summary)
    except BaseException as error:
        log("FAILED", error_type=type(error).__name__, detail=str(error))
        raise
    finally:
        STOP.set(); thread.join()


if __name__ == "__main__":
    main()
