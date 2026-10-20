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
    relationships.append({"sequence": row["sequence"], "phase": row["phase"],
                          "parent_id": parent["id"], "parent_name": parent["name"],
                          "parent_rf_id": next(a["value"] for a in parent["attrs"] if a["name"] == "rf_id")})
assert len(contexts) == 1
entry = entries[next(iter(contexts))]
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
receipt = {"schema": "scar.marker-independent-audit", "valid": True,
           "whole_model_established": False, "markers": len(rows),
           "dispatch_calls": len(groups), "python_tensor_reference_tokens": len(token_map),
           "duplicated_input_slots": duplicate_slots, "exact_retained_contexts": len(contexts),
           "marker_pairs_with_same_actual_native_parent": len(groups),
           "relationships": relationships,
           "limits": ["CPU plain Tensor probe, not a production collector",
                      "no logical versions, storage generations, purity or ready established",
                      "no foreign modes, exceptions, subclasses or whole-thread coverage validated"]}
(root / "audit-result.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(receipt))
