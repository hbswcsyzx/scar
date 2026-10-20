"""Independent stdlib replay of each exact marker argument and owned endpoint."""
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path

root = Path(__file__).resolve().parent
source = root.parent / "first_stage_marker_probe_20261020"
raw = source / "raw"
bundle_bytes = gzip.decompress((root / "evidence-bundle.json.gz").read_bytes())
bundle = json.loads(bundle_bytes)
report = json.loads(gzip.decompress((root / "import-report.json.gz").read_bytes()))
receipt = json.loads((root / "replay-result.json").read_text())
assert sha256(bundle_bytes).hexdigest() == receipt["bundle_sha256"]
markers = json.loads((source / "markers.json").read_text())
eto_bytes = (raw / "execution-trace.json").read_bytes()
eto = json.loads(eto_bytes)
eto_sha = sha256(eto_bytes).hexdigest()
marker_sha = sha256((source / "markers.json").read_bytes()).hexdigest()
objects = {obj["id"]["wire"]: obj for obj in bundle["values"]["objects"]}
references = {ref["reference_id"]: ref for ref in bundle["evidence"]["provider_references"]}
instances = {instance["metadata"]["node_id"]: instance for instance in bundle["evidence"]["instances"]}
by_name = {}
for number, node in enumerate(eto["nodes"]):
    by_name.setdefault(node["name"], []).append((number, node))
edges = {edge["edge_id"]: edge for edge in bundle["evidence"]["edges"]
         if edge["relation"] == "object_reference_association"}
object_by_weak = {obj["metadata"]["weak_token"]: obj for obj in objects.values()}
seen_edges, seen_objects, duplicates = set(), set(), 0
scope = report["reference_bridge"]["scope"]
for number, row in enumerate(markers):
    (node_number, node), = by_name[row["name"]]
    weak_counts = Counter(leaf["ref"] for leaf in row["tensor_references"])
    duplicates += sum(count - 1 for count in weak_counts.values())
    for ordinal, (leaf, descriptor) in enumerate(zip(row["tensor_references"], node["inputs"]["values"], strict=True)):
        edge = edges[scope + f":marker:{number}:slot:{ordinal}"]
        seen_edges.add(edge["edge_id"])
        obj = object_by_weak[leaf["ref"]]
        seen_objects.add(obj["id"]["wire"])
        assert edge["source"] == {"kind": "object", "reference": obj["id"]}
        ref = references[edge["target"]["reference"]]
        assert edge["target"]["kind"] == "provider_reference"
        assert ref["token"] == descriptor[0]
        assert edge["evidence"]["kind"] == "Inferred" and edge["evidence"]["assumptions"]
        assert f"sha256:{marker_sha}#/{number}/tensor_references/{ordinal}" in edge["evidence"]["references"]
        locator = f"sha256:{eto_sha}#/nodes/{node_number}/inputs/values/{ordinal}"
        assert locator in edge["evidence"]["references"]
        instance = instances[node["id"]]
        slot, = [slot for slot in instance["metadata"]["tensor_slots"]
                 if slot["role"] == "inputs" and slot["ordered_path"] == [ordinal]]
        assert slot["provider_reference"] == ref["reference_id"] and slot["raw_reference"] == locator
assert seen_edges == set(edges) and seen_objects == set(objects)
external = {(row["kind"], row["wire"]) for row in bundle["evidence"]["external_references"]}
assert {("object", wire) for wire in objects} <= external
for key in ("logical_values", "versions", "bindings", "allocations", "regions", "materializations", "provenance"):
    assert bundle["values"][key] == []
relations = Counter(edge["relation"] for edge in bundle["evidence"]["edges"])
assert not {"aliases", "produces", "happens_before", "materializes", "observed_write"} & set(relations)
audit = {"schema": "scar.object-reference-independent-audit", "valid": True,
    "objects": len(objects), "ordered_slot_associations": len(edges),
    "duplicate_argument_slots_retained": duplicates,
    "all_exact_raw_locators_replayed": True, "all_endpoints_owned": True,
    "invented_content_or_allocation_records": 0,
    "whole_model_established": False, "production_collector_validated": False,
    "source_capture": str(source), "bundle_sha256": sha256(bundle_bytes).hexdigest(),
    "relations": dict(relations)}
(root / "audit-result.json").write_text(json.dumps(audit, indent=2) + "\n")
print(json.dumps(audit))
