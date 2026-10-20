"""Replay existing real CPU observations; no target, Torch or GPU execution."""
import gzip
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

from scar.ir.v2 import canonical_json
from scar.trace.reference_import import import_reference_bridge, RESEARCH_PROFILE

root = Path(__file__).resolve().parent
source = root.parent / "first_stage_marker_probe_20261020"
raw = source / "raw"
started = perf_counter()
result = import_reference_bridge(raw / "execution-trace.json", source / "markers.json",
    next(raw.glob("call-events.*.jsonl")), next(raw.glob("call-codes.*.jsonl")),
    next(raw.glob("call-meta.*.json")), reference_profile=RESEARCH_PROFILE,
    provider_revision="cf30153c4c131c8164ee7798e5022d810682e2cb")
document = result.bundle.to_dict()
for name, value in (("evidence-bundle", document), ("import-report", result.report)):
    output = root / (name + ".json.gz")
    with output.open("xb") as stream:
        stream.write(gzip.compress(canonical_json(value).encode(), mtime=0))
receipt = {"schema": "scar.object-reference-replay", "valid": True,
    "whole_model_established": False, "production_collector_validated": False,
    "source_capture": str(source), "objects": len(result.bundle.values.objects),
    "markers": result.report["reference_bridge"]["markers"],
    "slot_associations": result.report["reference_bridge"]["slot_associations"],
    "logical_versions": len(result.bundle.values.versions),
    "allocations": len(result.bundle.values.allocations),
    "state_effects_established": False, "direct_python_operator_correspondence_established": False,
    "evidence_schema": document["evidence"]["schema_version"],
    "values_schema": document["values"]["schema_version"],
    "bundle_sha256": sha256(canonical_json(document).encode()).hexdigest(),
    "adapter_and_serialization_wall_seconds": perf_counter() - started,
    "target_rerun": False, "tensor_contents_saved": False}
(root / "replay-result.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(receipt))
