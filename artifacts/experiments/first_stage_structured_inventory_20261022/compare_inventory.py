"""Independent old/new inventory recount and ownership comparison, not a proof."""
import argparse
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path


def read(path):
    with gzip.open(path, "rb") as source:
        data = source.read(256_000_001)
    assert len(data) <= 256_000_000
    return json.loads(data)


def key(identifier):
    return identifier["wire"]


def recount(document):
    counts, statuses, unsupported, reasons, atoms = Counter(), Counter(), Counter(), Counter(), Counter()
    body_by_definition = {}
    for file in document["files"]:
        definitions = {key(item["id"]): item for item in file["definitions"]}
        assert len(definitions) == len(file["definitions"])
        counts.update(files=1, definitions=len(definitions), source_calls=len(file["calls"]),
                      source_atoms=len(file["coverage"]))
        atoms.update(row["status"] for row in file["coverage"])
        for body in file["bodies"]:
            identifier = key(body["definition"])
            assert identifier not in body_by_definition and identifier in definitions
            body_by_definition[identifier] = (file["snapshot"]["path"], definitions[identifier], body)
            statuses[body["status"]] += 1
            if body["graph"] is None:
                assert body["status"] != "LOWERED_WITH_GAPS"
                reasons[(body["status"], body["reason"])] += 1
                if body["status"] == "UNSUPPORTED":
                    candidates = [gap for gap in (body["metadata"] or {}).get("gaps", ())
                                  if gap["kind"] in {"UNSUPPORTED_SYNTAX", "UNSUPPORTED_SIGNATURE", "SOURCE_MAPPING", "BUDGET"}]
                    if candidates:
                        unsupported[candidates[-1]["detail"]] += 1
                continue
            assert body["status"] == "LOWERED_WITH_GAPS"
            graph = body["graph"]
            counts.update(core_operations=len(graph["operations"]), core_values=len(graph["values"]))
            linked = {link["source"]["atom_id"]["wire"] for category in
                      ("operation_links", "value_links", "use_links") for link in body["metadata"][category]}
            for row in file["coverage"]:
                if row["status"] == "CONNECTED" and row["owner"] == body["definition"]:
                    assert row["source"]["atom_id"]["wire"] in linked
    assert statuses == Counter(document["summary"]["body_statuses"])
    assert atoms == Counter(document["summary"]["coverage_statuses"])
    for actual, published in (("files", "source_files"), ("definitions", "definitions"),
                              ("source_calls", "source_calls"), ("source_atoms", "coverage_atoms"),
                              ("core_operations", "core_operations"), ("core_values", "core_values")):
        assert counts[actual] == document["summary"][published]
    return {"counts": dict(counts), "statuses": dict(statuses), "coverage": dict(atoms),
            "unsupported_terminal_details": dict(unsupported),
            "not_lowered_reasons": [{"status": status, "reason": reason, "count": count}
                                    for (status, reason), count in reasons.most_common()]}, body_by_definition


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    assert not args.out.exists()
    old, new = read(args.baseline), read(args.inventory)
    assert old["schema_version"] == 6 and new["schema_version"] == 7
    assert new["profile"] == "STRUCTURED_BODY_V1" and "frames" not in new
    assert old["budget"] == new["budget"] and old["discovery"] == new["discovery"]
    assert old["call_sources"] == new["call_sources"]
    assert [(file["snapshot"], file["context"]) for file in old["files"]] == [(file["snapshot"], file["context"]) for file in new["files"]]
    old_report, old_bodies = recount(old)
    new_report, new_bodies = recount(new)
    assert set(old_bodies) == set(new_bodies)
    successful = {identifier: body for identifier, (_, _, body) in new_bodies.items() if body["graph"] is not None}
    models = {key(model["definition"]): model for model in new["structured"]}
    ports = {key(port["definition"]): port for port in new["interfaces"]["bodies"]}
    assert len(models) == len(new["structured"]) and len(ports) == len(new["interfaces"]["bodies"])
    assert set(models) == set(ports) == set(successful)
    for identifier, body in successful.items():
        model, port = models[identifier], ports[identifier]
        assert model["region"] == port["region"] == body["graph"]["root"]
        assert model["source"] == new_bodies[identifier][1]["source"]
        assert port["profile"] == "STRUCTURED_BODY_V1"
        operations = {key(operation["id"]) for operation in body["graph"]["operations"]}
        assert all(key(protocol["operation"]) in operations for protocol in model["protocols"])
    changed = [{"source": path, "definition": definition["qualname"],
                "old_status": old_bodies[identifier][2]["status"], "new_status": body["status"]}
               for identifier, (path, definition, body) in new_bodies.items()
               if body["status"] != old_bodies[identifier][2]["status"]]
    assert new["target_executed"] is new["transformation_authorized"] is False
    assert new["summary"]["whole_program_graph_established"] is False
    report = {"valid": True, "scope": "same-source/raw-input/budget comparison and declared graph ownership; not dependency truth",
              "baseline_raw_sha256": sha256(args.baseline.read_bytes()).hexdigest(),
              "inventory_raw_sha256": sha256(args.inventory.read_bytes()).hexdigest(),
              "baseline": old_report, "structured": new_report, "changed_bodies": changed,
              "structured_models": len(models), "loops": sum(len(model["loops"]) for model in models.values()),
              "old_call_source_scope": old["summary"]["call_source_scope"],
              "new_call_source_scope": new["summary"]["call_source_scope"],
              "same_source_contexts_raw_calls_and_budgets": True,
              "whole_program_graph_established": False, "dynamic_dependencies_established": False,
              "transformation_authorized": False}
    with args.out.open("x") as destination:
        json.dump(report, destination, indent=2, ensure_ascii=False)
        destination.write("\n")
    print(json.dumps({"valid": True, "baseline": old_report["statuses"],
                      "structured": new_report["statuses"], "changed_bodies": changed,
                      "terminal_details": new_report["unsupported_terminal_details"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
