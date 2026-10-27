"""Independently check the graph delta and every provider scope association."""
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import sys


def read(path):
    path = Path(path)
    with (gzip.open(path, "rb") if path.suffix == ".gz" else path.open("rb")) as stream:
        raw = stream.read()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def main():
    previous, current, destination = map(Path, sys.argv[1:])
    if destination.exists():
        raise ValueError("audit output must be fresh")
    old, old_sha = read(previous / "evidence-bundle.json.gz")
    old_audit, _ = read(previous.parent / "lewm-audit.json")
    assert old_sha == old_audit["bundle_sha256"]
    new, new_sha = read(current / "evidence-bundle.json.gz")
    report, _ = read(current / "import-report.json.gz")
    for field in ("semantic", "values", "source_semantics", "optimization", "correspondence"):
        assert new[field] == old[field], field
    before, after = old["evidence"], new["evidence"]
    assert before["schema_version"] == 4 and after["schema_version"] == 5
    for field in ("instances", "provider_references", "observations", "measurements",
                  "control_events", "external_references"):
        assert before[field] == after[field], field
    old_edges = {row["edge_id"]: row for row in before["edges"]}
    additions = []
    for row in after["edges"]:
        if row["edge_id"] in old_edges:
            assert row == old_edges.pop(row["edge_id"])
        else:
            assert row["relation"] == "provider_scope_association"
            additions.append(row)
    assert not old_edges
    # The graph delta is only this association; every previously audited slot,
    # parent, resource edge and GPU correlation is unchanged.
    instances = {row["id"]["wire"]: row for row in after["instances"]}
    del old, new, before, after
    source = report["artifacts"]["kineto"]
    chrome, raw_sha = read(source["path"])
    assert raw_sha == source["sha256"]
    events, candidates = chrome["traceEvents"], defaultdict(list)
    def positive(value):
        return type(value) is int and value > 0
    for index, event in enumerate(events):
        external = event.get("args", {}).get("External id")
        if (event.get("ph") == "X" and event.get("cat") == "cpu_op"
                and type(event.get("pid")) is int and event["pid"] == report["pid"]
                and positive(external)):
            candidates[external].append(index)
    expected, checked, categories = Counter(), Counter(), Counter()
    for index, event in enumerate(events):
        if (event.get("ph") != "X" or event.get("cat") not in
                {"cuda_runtime", "cuda_driver", "kernel", "gpu_memcpy", "gpu_memset"}):
            continue
        if event["cat"] in {"cuda_runtime", "cuda_driver"}:
            assert type(event["pid"]) is int and event["pid"] == report["pid"]
        external = event.get("args", {}).get("External id")
        options = candidates.get(external, ()) if positive(external) else ()
        if len(options) == 1:
            expected[options[0], index] += 1
    prefix = "sha256:" + raw_sha + "#/traceEvents/"
    for edge in additions:
        owner = instances[edge["source"]["reference"]["wire"]]
        activity = instances[edge["target"]["reference"]["wire"]]
        owner_ref = owner["metadata"].get("kineto_reference", owner["metadata"]["raw_reference"])
        activity_ref = activity["metadata"]["raw_reference"]
        assert owner_ref.startswith(prefix) and activity_ref.startswith(prefix)
        owner_index, activity_index = int(owner_ref[len(prefix):]), int(activity_ref[len(prefix):])
        assert set(edge["evidence"]["references"]) == {owner_ref, activity_ref}
        assert edge["evidence"]["kind"] == "Inferred"
        checked[owner_index, activity_index] += 1
        categories[events[activity_index]["cat"]] += 1
    assert checked == expected
    assert len(additions) == report["provider_scope_matches"] == sum(expected.values())
    assert dict(categories) == report["provider_scope_matches_by_category"]
    assert not any(row.get("relation") == "happens_before" for row in additions)
    assert report["whole_model_established"] is False
    result = {"schema": "scar.native-scope-independent-audit", "valid": True,
              "whole_model_established": False, "previous_bundle_sha256": old_sha,
              "bundle_sha256": new_sha, "preserved_prior_edges": old_audit["relations"],
              "scope_associations_replayed": len(additions), "categories": dict(categories),
              "cpu_external_id_duplicates": sum(len(rows) > 1 for rows in candidates.values()),
              "new_canonical_content_or_order_claims": False}
    destination.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
