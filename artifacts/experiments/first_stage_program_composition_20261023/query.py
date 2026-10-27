"""One actual reference/query receipt over the automatically selected source scope."""
import json
from pathlib import Path

from scar.analysis.program_composition import CompositionIndex, ElementReference
from scar.ir.v2.ids import OperationDefinitionID


base = Path(__file__).resolve().parent
model = CompositionIndex(base / "result/index.json.gz")
rows = model.document["files"]
body_file, body_index, body = next((file_index, body_index, body)
    for file_index, row in enumerate(rows) for body_index, body in enumerate(row["bodies"])
    if body["root"] is not None)
definition = ElementReference(body_file, OperationDefinitionID(body["definition"].split(":", 1)[1]))
expanded_definition = model.expand(definition)
root = next(ref for ref in expanded_definition["typed_regions"] if ref.body_index == body_index)
expanded_root = model.expand(root)
graph, metadata = model.typed_body(body_file, body_index)
operation_id = max(graph.operations, key=lambda operation: len(operation.uses)).id
operation_ref = ElementReference(body_file, operation_id, body_index)
dependencies = model.dependencies(operation_ref)
if dependencies["ordered_uses"] != next(operation.uses for operation in graph.operations if operation.id == operation_id):
    raise ValueError("query copied or changed canonical ordered uses")
target_example = None
cross_calls = [(file_index, call) for file_index, row in enumerate(rows) for call in row["calls"]
               if any(target["file_index"] != file_index for target in call["target_definitions"])]
cross_calls.sort(key=lambda item: not any(body["root"] is not None and body["definition"] == target["definition"]
    for target in item[1]["target_definitions"] for body in rows[target["file_index"]]["bodies"]))
for file_index, call in cross_calls:
            reference = ElementReference(file_index, OperationDefinitionID(call["operation"].split(":", 1)[1]))
            queried = model.dependencies(reference)
            if not queried["conditional_target_regions"]:
                raise ValueError("cross-file conditional source target vanished")
            if any(target["actual_formal_return_connected"] for target in queried["conditional_target_regions"]):
                raise ValueError("source candidates incorrectly established runtime bindings")
            target_example = {"file_index": file_index, "operation": call["operation"],
                              "targets": len(queried["conditional_target_regions"]),
                              "canonical_regions": sum(len(target["canonical_regions"]) for target in queried["conditional_target_regions"]),
                              "actual_formal_return_connected": False}
            break
result = {
    "schema": "scar.program-composition-query-receipt", "schema_version": 1,
    "source_file": rows[body_file]["snapshot"]["path"], "definition": body["definition"],
    "body_root": root.identity.wire, "canonical_child_operations": len(expanded_root["children"]),
    "definition_source_atoms": len(expanded_definition["source_atoms"]),
    "operation": operation_id.wire, "ordered_uses": len(dependencies["ordered_uses"]),
    "state_accesses": len(dependencies["state_accesses"]),
    "effects_complete": dependencies["effects_complete"],
    "original_ordered_uses_preserved": True,
    "cross_file_conditional_call": target_example,
    "first_stage_complete": False,
}
(base / "query-result.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
print(json.dumps(result, sort_keys=True))
