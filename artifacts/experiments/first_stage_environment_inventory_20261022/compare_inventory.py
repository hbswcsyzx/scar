"""Independent stdlib recount; no SCAR import or graph supplied by this audit."""
import argparse
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path
import runpy


def read(path):
    with gzip.open(path, "rb") as stream:
        raw = stream.read(256_000_001)
    assert len(raw) <= 256_000_000
    return json.loads(raw)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    assert not args.out.exists()
    previous_auditor = Path(__file__).parents[1] / "first_stage_structured_inventory_20261022/compare_inventory.py"
    recount = runpy.run_path(str(previous_auditor))["recount"]
    old, new = read(args.baseline), read(args.inventory)
    assert old["schema_version"] == 7 and new["schema_version"] == 8
    assert new["profile"] == "STRUCTURED_ENV_V1" and "frames" not in new
    for field in ("discovery", "budget", "call_sources"):
        assert old[field] == new[field], field
    assert [(row["snapshot"], row["context"]) for row in old["files"]] == [
        (row["snapshot"], row["context"]) for row in new["files"]]
    old_report, old_bodies = recount(old)
    new_report, new_bodies = recount(new)
    assert set(old_bodies) == set(new_bodies)
    models = {model["definition"]["wire"]: model for model in new["structured"]}
    ports = {port["definition"]["wire"]: port for port in new["interfaces"]["bodies"]}
    successful = {key for key, (_, _, body) in new_bodies.items() if body["graph"] is not None}
    assert len(models) == len(new["structured"]) and set(models) == set(ports) == successful
    counts = Counter()
    for identifier in successful:
        graph = new_bodies[identifier][2]["graph"]
        environment, = graph["environments"]
        layout, = graph["function_entries"]
        assert layout["environment"] == environment["id"]
        assert layout["parameters"] == ports[identifier]["parameters"]
        assert models[identifier]["region"] == ports[identifier]["region"] == environment["region"] == graph["root"]
        roles = [member["role"] for member in environment["members"]]
        assert roles[:5] == ["FUNCTION_OBJECT", "GLOBALS_NAMESPACE", "BUILTINS_NAMESPACE", "DEFAULTS", "KEYWORD_DEFAULTS"]
        assert all(role == "CAPTURED_CELL" for role in roles[5:])
        counts.update(environments=1, captured_cell_ports=len(roles)-5,
                      address_refinements=len(graph.get("state_address_refinements", ())))
    old_environment_failures = []
    changed = []
    for identifier, (path, definition, body) in new_bodies.items():
        prior = old_bodies[identifier][2]
        record = {"path": path, "definition": definition["qualname"],
                  "old_status": prior["status"], "new_status": body["status"],
                  "next_reason": body["reason"], "environment_graph_persisted": identifier in successful}
        if "closure cell environment/state interface remains unconnected" in prior["reason"]:
            old_environment_failures.append(record)
        if prior["status"] != body["status"]:
            changed.append(record)
    assert len(old_environment_failures) == 45
    assert new["summary"]["whole_program_graph_established"] is False
    assert new["target_executed"] is new["transformation_authorized"] is False
    result = {"valid": True, "scope": "same-snapshot/raw/budget recount and declared environment ownership",
              "baseline_sha256": sha256(args.baseline.read_bytes()).hexdigest(),
              "inventory_sha256": sha256(args.inventory.read_bytes()).hexdigest(),
              "baseline": old_report, "environment": new_report, "environment_records": dict(counts),
              "changed_bodies": changed, "old_45_environment_failures": old_environment_failures,
              "old_call_source_scope": old["summary"]["call_source_scope"],
              "new_call_source_scope": new["summary"]["call_source_scope"],
              "same_source_contexts_raw_calls_and_budgets": True,
              "whole_program_graph_established": False, "runtime_environments_verified": False,
              "fine_grained_state_effects_established": False, "transformation_authorized": False}
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"valid": True, "baseline": old_report["statuses"], "environment": new_report["statuses"],
                      "environment_records": dict(counts), "changed_bodies": len(changed)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
