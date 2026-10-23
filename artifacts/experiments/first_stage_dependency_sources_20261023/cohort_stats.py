"""Read-only continuation sizing; no SCAR import, source compile or prepare."""
import base64
import hashlib
from io import BytesIO, TextIOWrapper
import json
from pathlib import Path
import statistics
import tokenize


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def canonical(document):
    return json.dumps(document, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


root = Path(__file__).resolve().parent
report_path = root / "result/admissions.json"
report_raw = report_path.read_bytes()
report = json.loads(report_raw)
roots = {row["id"]: row for row in report["source_roots"]}
missing_snapshots, missing_graphs, complete = [], [], []
guards = []
for row in report["source_files"]:
    path = Path(row["path"])
    raw = path.read_bytes()
    encoding, _ = tokenize.detect_encoding(BytesIO(raw).readline)
    with TextIOWrapper(BytesIO(raw), encoding=encoding, newline=None) as stream:
        text = stream.read()
    fingerprint = "sha256:" + sha(text.encode("utf-8"))
    guard = {"path": str(path), "raw_sha256_matches": sha(raw) == row["raw_sha256"],
             "raw_bytes_match": len(raw) == row["raw_bytes"],
             "decoded_fingerprint_matches": fingerprint == row["fingerprint"]}
    guards.append(guard)
    entry = {"path": str(path), "source_root": row["source_root"],
             "raw_bytes": row["raw_bytes"], "raw_sha256": row["raw_sha256"],
             "fingerprint": row["fingerprint"]}
    if row["snapshot_artifact"] is None:
        namespace = roots[row["source_root"]]
        document = {
            "schema": "scar.dependency-source-snapshot", "schema_version": 1,
            "source_root": row["source_root"], "namespace_root": namespace["namespace_root"],
            "original_uri": str(path), "raw_sha256": row["raw_sha256"], "raw_bytes": len(raw),
            "raw_base64": base64.b64encode(raw).decode("ascii"),
            "decoded_text": text, "fingerprint": fingerprint,
            "python_version": "3.14", "code_source_match_established": False,
        }
        payload = canonical(document)
        entry["source_snapshot_canonical_bytes"] = len(payload)
        entry["source_snapshot_canonical_sha256"] = sha(payload)
        missing_snapshots.append(entry)
    elif row["source_graph_artifact"] is None:
        missing_graphs.append(entry)
    else:
        entry["graph_canonical_bytes"] = row["source_graph_artifact"]["canonical_bytes"]
        entry["graph_bytes_per_raw_byte"] = entry["graph_canonical_bytes"] / row["raw_bytes"]
        complete.append(entry)

ratios = sorted(row["graph_bytes_per_raw_byte"] for row in complete)
quantiles = statistics.quantiles(ratios, n=10, method="inclusive")
incomplete_bytes = sum(row["raw_bytes"] for row in missing_snapshots + missing_graphs)
weighted_ratio = sum(row["graph_canonical_bytes"] for row in complete) / sum(row["raw_bytes"] for row in complete)
summary = {
    "schema": "scar.dependency-source-continuation-sizing", "schema_version": 1,
    "parent_report_raw_sha256": sha(report_raw),
    "source_files_guarded": len(guards),
    "all_current_raw_and_decoded_fingerprints_match": all(
        row["raw_sha256_matches"] and row["raw_bytes_match"] and row["decoded_fingerprint_matches"]
        for row in guards),
    "complete_graph_files": len(complete),
    "complete_graph_source_bytes": sum(row["raw_bytes"] for row in complete),
    "complete_graph_canonical_bytes": sum(row["graph_canonical_bytes"] for row in complete),
    "missing_snapshot_files": len(missing_snapshots),
    "missing_snapshot_source_bytes": sum(row["raw_bytes"] for row in missing_snapshots),
    "missing_snapshot_exact_canonical_bytes": sum(row["source_snapshot_canonical_bytes"] for row in missing_snapshots),
    "missing_graph_only_files": len(missing_graphs),
    "missing_graph_only_source_bytes": sum(row["raw_bytes"] for row in missing_graphs),
    "incomplete_total_source_bytes": incomplete_bytes,
    "observed_graph_bytes_per_raw_byte": {
        "weighted_ratio": weighted_ratio, "minimum": ratios[0],
        "p10_inclusive": quantiles[0], "median": statistics.median(ratios),
        "p90_inclusive": quantiles[8], "maximum": ratios[-1]},
    "inferred_graph_bytes_for_27_files_not_bound": {
        "weighted_ratio": round(incomplete_bytes * weighted_ratio),
        "p10_ratio": round(incomplete_bytes * quantiles[0]),
        "median_ratio": round(incomplete_bytes * statistics.median(ratios)),
        "p90_ratio": round(incomplete_bytes * quantiles[8]),
        "maximum_observed_ratio": round(incomplete_bytes * ratios[-1])},
    "current_source_guards": guards,
    "missing_snapshots": missing_snapshots,
    "missing_graphs": missing_graphs,
    "complete_graphs": complete,
    "prepared_or_compiled_sources": False,
    "continuation_executed": False,
}
(root / "cohort_stats.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({key: value for key, value in summary.items()
                  if key not in ("current_source_guards", "missing_snapshots", "missing_graphs", "complete_graphs")}, indent=2))
