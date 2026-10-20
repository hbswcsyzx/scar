"""Replay exact collector markers and original call reference tokens."""
from collections import defaultdict
import json
from pathlib import Path

root = Path(__file__).resolve().parent
rows = json.loads((root / "markers.json").read_text())
eto = json.loads((root / "raw/execution-trace.json").read_text())
nodes = {node["id"]: node for node in eto["nodes"]}
markers = {node["name"]: node for node in eto["nodes"]}
call_path, = (root / "raw").glob("call-events.*.jsonl")
calls = [json.loads(line) for line in call_path.read_text().splitlines()]
entries = {row["invocation_id"]: row for row in calls if row["kind"] == "call_enter"}
code_path, = (root / "raw").glob("call-codes.*.jsonl")
codes = {row["key"]: row for line in code_path.read_text().splitlines() if (row := json.loads(line))}
token_map, groups, contexts, relationships = defaultdict(set), defaultdict(dict), set(), []
for row in rows:
    node = markers[row["name"]]
    context = row["context"]
    assert context["invocation"] in entries
    entry = entries[context["invocation"]]
    assert context["code"] == entry["code"]
    contexts.add(context["invocation"])
    assert len(node["inputs"]["values"]) == len(row["tensor_references"])
    for leaf, descriptor in zip(row["tensor_references"], node["inputs"]["values"], strict=True):
        assert leaf["ref"].startswith("weak:")
        assert len(descriptor) == 6
        token_map[leaf["ref"]].add(descriptor[0])
    groups[row["sequence"]][row["phase"]] = (row, node)
    parent = nodes[node["ctrl_deps"]]
    ancestry, current, visited = [], parent, set()
    while current["id"] not in visited:
        visited.add(current["id"])
        ancestry.append({"id": current["id"], "name": current["name"]})
        if current["ctrl_deps"] == current["id"] or current["ctrl_deps"] not in nodes:
            break
        current = nodes[current["ctrl_deps"]]
    relationships.append({"sequence": row["sequence"], "phase": row["phase"],
                          "parent_id": parent["id"], "parent_name": parent["name"],
                          "parent_rf_id": next(a["value"] for a in parent["attrs"] if a["name"] == "rf_id"),
                          "actual_provider_ancestry": ancestry})
entry, = [row for row in entries.values()
          if codes[row["code"]]["filename"] == str(root / "case/app.py")
          and codes[row["code"]]["qualname"] == "run"]
for invocation in contexts:
    visited = set()
    while invocation != entry["invocation_id"]:
        assert invocation not in visited and invocation in entries
        visited.add(invocation)
        parent = entries[invocation]
        assert parent["path_complete"]
        invocation = parent["caller_invocation_id"] or parent["ancestor_invocation_id"]
parameters = {row["name"]: row["ref"] for row in entry["parameters"]}
assert parameters["x"] in token_map and parameters["g"] in token_map
assert all(len(tokens) == 1 for tokens in token_map.values())
duplicate_slots = 0
for pair in groups.values():
    input_row, input_node = pair["input"]
    output_row, output_node = pair["output"]
    assert input_node["ctrl_deps"] == output_node["ctrl_deps"]
    refs = input_row["tensor_references"]
    for first, second in zip(refs, refs[1:]):
        if first["ref"] == second["ref"]:
            duplicate_slots += 1
# Application-return locals must agree with the dispatch observation tokens.
exit_row, = [row for row in calls if row["kind"] == "call_exit"
             and row["invocation_id"] == entry["invocation_id"]]
locals_at_exit = {row["name"]: row["ref"] for row in exit_row["locals"]}
assert all(locals_at_exit[name] in token_map for name in ("view", "result", "loss"))
first_input = groups[1]["input"][1]["inputs"]["values"][0]
first_output = groups[1]["output"][1]["inputs"]["values"][0]
assert first_input[0] != first_output[0] and first_input[1] == first_output[1]
third_input = groups[3]["input"][1]["inputs"]["values"][0]
third_output = groups[3]["output"][1]["inputs"]["values"][0]
assert third_input[0] == third_output[0]
receipt = {"schema": "scar.marker-independent-audit", "valid": True,
           "whole_model_established": False, "markers": len(rows),
           "dispatch_calls": len(groups), "python_tensor_reference_tokens": len(token_map),
           "duplicated_input_slots": duplicate_slots, "retained_ancestor_contexts": len(contexts),
           "application_calls_reached_via_recorded_ancestry": 1,
           "marker_pairs_with_same_actual_provider_parent": len(groups),
           "view_has_distinct_tensor_token_shared_storage_map_token": True,
           "inplace_has_same_tensor_token_without_content_identity_claim": True,
           "relationships": relationships,
           "limits": ["CPU plain Tensor probe, not a production collector",
                      "no logical versions, storage generations, purity or ready established",
                      "no foreign modes, exceptions, subclasses or whole-thread coverage validated"]}
(root / "audit-result.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(receipt))
