"""Recount provider/OS records without inventing logical values or a model.

The caller supplies a completed trace directory. No target is imported or run.
"""
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys


def read(path):
    path = Path(path)
    actual = path if path.exists() else Path(str(path) + ".gz")
    opener = gzip.open if actual.suffix == ".gz" else open
    with opener(actual, "rb") as stream:
        raw = stream.read(512_000_001)
    if len(raw) > 512_000_000:
        raise ValueError("artifact exceeds audit byte ceiling: " + str(actual))
    return json.loads(raw), {"logical_path": str(path), "actual_path": str(actual),
                             "raw_sha256": hashlib.sha256(raw).hexdigest(), "raw_bytes": len(raw)}


def main():
    root, output = map(Path, sys.argv[1:])
    if output.exists():
        raise ValueError("audit output must be fresh")
    run, run_source = read(root / "trace/run.json")
    manifest_path, = (root / "trace").glob("execution-evidence.*.json")
    manifest, manifest_source = read(manifest_path)
    pid = manifest["pid"]
    calls, calls_source = read(root / f"trace/call-meta.{pid}.json")
    operands, operands_source = read(root / f"trace/call-operand-meta.{pid}.json")
    et, et_source = read(manifest["artifacts"]["execution_trace"]["path"])
    chrome, chrome_source = read(manifest["artifacts"]["kineto"]["path"])
    if et["pid"] != pid or calls["process_id"] != pid or operands["process_id"] != pid:
        raise ValueError("provider process scopes disagree")
    et_ids, chrome_ids = defaultdict(list), defaultdict(list)
    for node in et["nodes"]:
        attrs = {attr["name"]: attr["value"] for attr in node["attrs"]}
        rf = attrs.get("rf_id")
        if type(rf) is int and rf > 0:
            et_ids[rf].append(node["name"])
    categories, activities, runtimes, resource_tuples = Counter(), [], defaultdict(list), set()
    for event in chrome["traceEvents"]:
        category, args = event.get("cat", ""), event.get("args", {})
        categories[category] += 1
        if category == "cpu_op":
            rf = args.get("Record function id")
            if type(rf) is int and rf > 0:
                chrome_ids[rf].append(event["name"])
        if event.get("ph") != "X":
            continue
        correlation = args.get("correlation")
        if category in ("cuda_runtime", "cuda_driver") and type(correlation) is int and correlation > 0:
            runtimes[correlation].append(event["name"])
        if category in ("kernel", "gpu_memcpy", "gpu_memset"):
            activities.append((category, correlation))
            if all(key in args for key in ("device", "context", "stream")):
                resource_tuples.add(tuple(args[key] for key in ("device", "context", "stream")))
    matches = [rf for rf in et_ids.keys() & chrome_ids.keys()
               if len(et_ids[rf]) == len(chrome_ids[rf]) == 1 and et_ids[rf][0] == chrome_ids[rf][0]]
    correlation_status = Counter()
    for category, correlation in activities:
        count = len(runtimes.get(correlation, ())) if type(correlation) is int and correlation > 0 else 0
        correlation_status[(category, "unique" if count == 1 else "ambiguous" if count > 1 else "missing")] += 1
    syscall_counts, unparsed, lines, os_files = Counter(), Counter(), 0, []
    expression = re.compile(r"^\d+\.\d+\s+([A-Za-z0-9_]+)\(")
    for path in sorted((root / "os").glob("syscalls.*")):
        opener = gzip.open if path.suffix == ".gz" else open
        digest, count = hashlib.sha256(), 0
        with opener(path, "rb") as stream:
            for raw in stream:
                digest.update(raw)
                count += 1
                text = raw.decode("utf-8", errors="replace")
                match = expression.match(text)
                if match:
                    syscall_counts[match[1]] += 1
                elif "resumed>" in text:
                    unparsed["resumed"] += 1
                elif "--- SIG" in text or "+++" in text:
                    unparsed["signal_or_exit"] += 1
                else:
                    unparsed["other"] += 1
        lines += count
        os_files.append({"path": str(path), "raw_sha256": digest.hexdigest(), "lines": count})
    result = {
        "schema": "scar.first-stage-capture-audit", "schema_version": 1,
        "scope": "raw evidence recount and conditional within-window provider joins, not a canonical program model",
        "whole_model_established": False, "canonical_graph_imported": False,
        "run": run, "manifest_status": manifest["status"], "manifest_failures": manifest["failures"],
        "pid": pid, "eto_schema": et["schema"], "eto_nodes": len(et["nodes"]),
        "eto_positive_rf_ids": len(et_ids), "kineto_positive_cpu_rf_ids": len(chrome_ids),
        "unique_same_id_name_matches": len(matches),
        "duplicate_eto_rf_ids": sum(len(rows) > 1 for rows in et_ids.values()),
        "duplicate_kineto_cpu_rf_ids": sum(len(rows) > 1 for rows in chrome_ids.values()),
        "eto_positive_rf_ids_not_uniquely_matched": len(et_ids) - len(matches),
        "kineto_event_categories": dict(sorted(categories.items())),
        "gpu_activity_runtime_correlation": [{"category": category, "status": status, "count": count}
                                             for (category, status), count in sorted(correlation_status.items())],
        "observed_device_context_stream_tuples": sorted(resource_tuples),
        "calls": calls, "operands": operands,
        "os": {"files": os_files, "lines": lines, "syscall_name_counts": dict(sorted(syscall_counts.items())),
               "non_call_entry_lines": dict(unparsed), "resource_lifecycles_recovered": False},
        "sources": [run_source, manifest_source, calls_source, operands_source, et_source, chrome_source],
        "gaps": ["same RF ID/name is a scoped provider correspondence, not logical content identity",
                 "CUDA correlation alone does not identify the copied logical tensor",
                 "Python-to-Torch occurrence and OS causal mappings are not established",
                 "OS syscall counts/file list do not recover resource lifecycles or all hardware activity"],
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"out": str(output), "returncode": run["returncode"], "status": manifest["status"],
                      "eto_nodes": len(et["nodes"]), "unique_rf_matches": len(matches),
                      "categories": dict(sorted(categories.items())), "os_files": len(os_files),
                      "whole_model_established": False}))


if __name__ == "__main__":
    main()
