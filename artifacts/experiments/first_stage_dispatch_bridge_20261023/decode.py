"""Decode one real CPU capture, then inspect its original marker tree."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from scar.trace.native_import import import_native_evidence
from scar.trace.dispatch_import import import_dispatch_bridge

root = Path(__file__).resolve().parent
raw = root / "raw"
one = lambda pattern: next(raw.glob(pattern))
native = import_native_evidence(one("execution-trace.*.json"), one("kineto.*.json"),
    provider_revision="cf30153c4c131c8164ee7798e5022d810682e2cb")
result = import_dispatch_bridge(native, one("dispatch-observations.*.jsonl"),
    one("dispatch-meta.*.json"), one("call-events.*.jsonl"), one("call-codes.*.jsonl"),
    one("call-meta.*.json"), native_manifest_path=one("execution-evidence.*.json"))
(root / "decoded.json").write_text(json.dumps(result.report["dispatch_bridge"], indent=2) + "\n")

# Inspect the raw provider and sidecar independently of the imported paths.
meta = json.loads(one("dispatch-meta.*.json").read_bytes())
payload = one("dispatch-observations.*.jsonl").read_bytes()
assert sha256(payload).hexdigest() == meta["file"]["raw_sha256"]
assert len(payload) == meta["file"]["raw_bytes"]
rows = [json.loads(line) for line in payload.splitlines()]
assert len(rows) == meta["file"]["lines"] == meta["events"]
eto = json.loads(one("execution-trace.*.json").read_bytes())
nodes = {row["id"]: row for row in eto["nodes"]}
names = {row["name"]: row for row in eto["nodes"]}
calls = [json.loads(line) for line in one("call-events.*.jsonl").read_text().splitlines()]
entries = {row["invocation_id"]: row for row in calls if row["kind"] == "call_enter"}
grouped, duplicate_slots, paths = {}, 0, []
for row in rows:
    grouped.setdefault(row["sequence"], {})[row["kind"]] = row
    if row["kind"] == "DISPATCH_END":
        continue
    observation = row["observation"]
    context = observation["context"]
    assert context["invocation"] in entries
    assert context["code"] == entries[context["invocation"]]["code"]
    assert context["bytecode_offset"] == context["site"]["offset"]
    node = names[row["marker"]]
    leaves, provider_values = observation["tensor_references"], node["inputs"]["values"]
    assert len(leaves) == len(provider_values)
    assert node["outputs"]["values"] == []
    seen = {}
    for leaf, descriptor in zip(leaves, provider_values, strict=True):
        if leaf["ref"] in seen:
            duplicate_slots += 1
            assert seen[leaf["ref"]] == descriptor
        seen[leaf["ref"]] = descriptor
    ancestry, current, visited = [], node, set()
    while current["id"] not in visited:
        visited.add(current["id"])
        ancestry.append({"id": current["id"], "name": current["name"]})
        if current["ctrl_deps"] == current["id"] or current["ctrl_deps"] not in nodes:
            break
        current = nodes[current["ctrl_deps"]]
    paths.append({"sequence": row["sequence"], "phase": row["kind"], "ancestry": ancestry})
outcomes = Counter()
for sequence, group in grouped.items():
    end = group["DISPATCH_END"]
    outcomes[end["outcome"]] += 1
    span = names[group["DISPATCH_BEGIN"]["marker"]]
    if end["outcome"] == "RAISED":
        assert "DISPATCH_OUTPUT" not in group and end["output_marker"] is None
    else:
        output = names[group["DISPATCH_OUTPUT"]["marker"]]
        assert output["ctrl_deps"] == span["id"]
assert duplicate_slots > 0 and outcomes["RAISED"] == 1
assert meta["errors"] == [] and meta["dropped_events"] == 0 and meta["mode_popped"] is True
assert result.report["dispatch_bridge"]["gaps"] == {}
report = {"schema": "scar.production-dispatch-independent-audit", "valid": True,
    "dispatches": len(grouped), "markers": len(paths), "duplicate_slots": duplicate_slots,
    "outcomes": dict(outcomes), "slot_associations": result.report["dispatch_bridge"]["slot_associations"],
    "actual_provider_paths": paths, "capture_membership_verified": False,
    "limits": ["bounded CPU capture only", "no OS process membership witness in this probe",
        "no foreign modes/subclasses/whole-thread coverage", "no content versions or effect/readiness proof"],
    "whole_model_established": False, "transformation_authorized": False}
(root / "audit-result.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({key: value for key, value in report.items() if key != "actual_provider_paths"}))
