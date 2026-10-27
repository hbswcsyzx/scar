"""Independent stdlib replay of saved observations against retained raw bytes.

This checks imported facts and conservation, not missing semantic relationships.
It does not import SCAR, Torch or the target, or grant transformation authority.
"""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import sys


def read(path):
    path = Path(path)
    if not path.exists():
        path = Path(str(path) + ".gz")
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as stream:
        raw = stream.read()
    return json.loads(raw), raw


def main():
    root, destination = map(Path, sys.argv[1:])
    if destination.exists():
        raise ValueError("audit requires fresh output")
    report, _ = read(root / "import-report.json")
    bundle, wire = read(root / "evidence-bundle.json.gz")
    documents = {}
    for artifact in report["artifacts"].values():
        document, payload = read(artifact["path"])
        assert len(payload) == artifact["size_bytes"]
        assert hashlib.sha256(payload).hexdigest() == artifact["sha256"]
        documents[artifact["sha256"]] = document
    def resolve(reference):
        source, _, pointer = reference.partition("#/")
        document = documents[source.removeprefix("sha256:")]
        for part in pointer.split("/"):
            document = document[int(part)] if isinstance(document, list) else document[part]
        return document

    graph = bundle["evidence"]
    instances = {row["id"]["wire"]: row for row in graph["instances"]}
    refs = {row["reference_id"]: row for row in graph["provider_references"]}
    assert len(instances) == len(graph["instances"])
    assert len(refs) == len(graph["provider_references"])
    eto = documents[report["artifacts"]["eto"]["sha256"]]
    chrome = documents[report["artifacts"]["kineto"]["sha256"]]
    categories = Counter(event.get("cat", "") for event in chrome["traceEvents"])
    assert dict(categories) == report["category_counts"]
    duration_count = sum(event.get("ph") == "X" for event in chrome["traceEvents"])
    assert len(instances) == len(eto["nodes"]) + duration_count - report["cpu_rf_matches"]
    assert report["inventory"]["retained_non_duration_events"] + duration_count == len(chrome["traceEvents"])
    assert len(report["retained_events"]) == report["inventory"]["retained_non_duration_events"]
    eto_instances, rf_matches, slot_claims = {}, 0, Counter()
    for row in instances.values():
        metadata = row["metadata"]
        raw = resolve(metadata["raw_reference"])
        if metadata.get("provider") == "ETO":
            eto_instances[raw["id"]] = row
            if "kineto_reference" in metadata:
                cpu = resolve(metadata["kineto_reference"])
                attrs = {entry["name"]: entry["value"] for entry in raw["attrs"]}
                assert attrs["rf_id"] == cpu["args"]["Record function id"] > 0
                assert raw["name"] == cpu["name"]
                assert cpu["pid"] == eto["pid"]
                rf_matches += 1
        for slot in metadata.get("tensor_slots", []):
            original = resolve(slot["raw_reference"])
            reference = refs[slot["provider_reference"]]
            descriptor = next(item for item in reference["metadata"]["descriptors"]
                              if item["descriptor_id"] == slot["descriptor_id"])
            assert descriptor["tensor_tuple"] == original
            assert len(original) == 6 and reference["token"] == original[0]
            key = row["id"]["wire"], slot["role"], slot["raw_reference"]
            slot_claims[key] += 1
    assert len(eto_instances) == len(eto["nodes"])
    for raw in eto["nodes"]:
        row = eto_instances[raw["id"]]
        if row["metadata"].get("structural_root_sentinel"):
            assert raw["id"] == raw["ctrl_deps"] == 1 and row["parent"] is None
        elif raw["ctrl_deps"] in eto_instances:
            assert row["parent"]["wire"] == eto_instances[raw["ctrl_deps"]]["id"]["wire"]
    assert rf_matches == report["cpu_rf_matches"]
    edge_slots, relations, submission_matches = Counter(), Counter(), 0
    for edge in graph["edges"]:
        relation = edge["relation"]
        relations[relation] += 1
        source = instances[edge["source"]["reference"]["wire"]]
        if relation in ("input_reference", "output_reference"):
            role = "inputs" if relation == "input_reference" else "outputs"
            pointer, = edge["evidence"]["references"]
            assert edge["target"]["reference"] in refs
            edge_slots[source["id"]["wire"], role, pointer] += 1
        elif relation == "submits_work":
            target = instances[edge["target"]["reference"]["wire"]]
            runtime = resolve(source["metadata"]["raw_reference"])
            work = resolve(target["metadata"]["raw_reference"])
            assert runtime["cat"] in ("cuda_runtime", "cuda_driver")
            assert runtime["pid"] == eto["pid"]
            assert work["cat"] in ("kernel", "gpu_memcpy", "gpu_memset")
            assert runtime["args"]["correlation"] == work["args"]["correlation"] > 0
            submission_matches += 1
    assert slot_claims == edge_slots
    assert submission_matches == report["runtime_gpu_matches"]
    assert not any(relations[key] for key in ("happens_before", "produces", "aliases", "overwrites"))
    assert not graph["observations"] and not bundle["values"]["versions"]
    assert bundle["optimization"] is None and bundle["source_semantics"] is None
    assert report["whole_model_established"] is False
    result = {"schema": "scar.native-import-independent-audit", "valid": True,
              "whole_model_established": False, "bundle_sha256": hashlib.sha256(wire).hexdigest(),
              "eto_nodes_replayed": len(eto_instances), "cpu_rf_matches_replayed": rf_matches,
              "runtime_gpu_matches_replayed": submission_matches,
              "tensor_slots_replayed": sum(slot_claims.values()),
              "relations": dict(relations), "operation_instances": len(instances),
              "provider_references": len(refs), "resource_observations": len(bundle["semantic"]["resources"]),
              "limits": ["checks represented observations, not complete logical or state modeling",
                         "does not recover omitted literal ports, source paths, lifetimes or OS effects"]}
    destination.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
