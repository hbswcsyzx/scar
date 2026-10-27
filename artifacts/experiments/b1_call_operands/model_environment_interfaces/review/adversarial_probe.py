"""Tiny in-memory adversarial checks for the environment review artifact."""
from __future__ import annotations

import json
from pathlib import Path

from scar.ir.program import ProgramGraph
from scar.ir.program.model import StateVersionValue
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid
from tests.unit.test_program_environments import _environment_graph


def rejected_after_mutation(name, mutate):
    graph = _environment_graph()
    mutate(graph)
    try:
        require_valid(graph)
    except (TypeError, ValueError):
        return {"name": name, "result": "REJECTED"}
    return {"name": name, "result": "ACCEPTED_UNEXPECTEDLY"}


results = []


def set_formal_to_environment_reference(graph):
    port = graph.function_entries[0].parameters[0]
    object.__setattr__(port, "value", graph.environments[0].members[0].reference)


def set_cell_position_to_bool(graph):
    cell = graph.environments[0].members[-1]
    object.__setattr__(cell, "cell_position", False)


results.append(rejected_after_mutation("nested_formal_env_overlap", set_formal_to_environment_reference))
results.append(rejected_after_mutation("nested_cell_position_bool", set_cell_position_to_bool))

graph = _environment_graph(alias_actuals=True)
derived = ProgramIndex(graph).environment_call(next(
    operation.id for operation in graph.operations if operation.callee is not None
))
results.append({
    "name": "aliased_actuals_keep_distinct_port_occurrences",
    "result": "PASS" if (
        derived.status.value == "DECLARED"
        and len({item.actual.use.id for item in derived.arguments}) == len(derived.arguments)
        and len({item.actual.use.value for item in derived.arguments}) == 1
        and len({item.actual.use.id for item in derived.parameters}) == len(derived.parameters)
    ) else "FAIL",
    "status": derived.status.value,
    "environment_actual_uses": len(derived.arguments),
    "environment_actual_values": len({item.actual.use.value for item in derived.arguments}),
    "formal_actual_uses": len(derived.parameters),
})

graph = _environment_graph()
physical_entry = next(block for block in graph.regions[-1].blocks
                      if block.id == graph.regions[-1].entry)
results.append({
    "name": "fixture_has_typed_state_entry_port",
    "result": "PASS" if any(
        isinstance(value, StateVersionValue) for value in graph.values
        if value.id in physical_entry.arguments
    ) else "FAIL",
    "entry_argument_count": len(physical_entry.arguments),
})

output = Path(__file__).with_name("adversarial_probe.json")
output.write_text(json.dumps({"results": results}, sort_keys=True, indent=2) + "\n")
print(json.dumps({"results": results}, sort_keys=True))
