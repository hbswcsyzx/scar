"""First compile/constructor + real ProgramGraph smoke; execution validator not yet present."""
import json

from scar.ir.program.validation import require_valid
from tests.fixtures.execution_resource_graphs import resource_execution_program

program, model = resource_execution_program()
require_valid(program)
assert len(model.activations) == len(model.resources) == 2
assert model.resources[0].id != model.resources[1].id
assert model.resources[0].origin.operation != model.resources[1].origin.operation
print(json.dumps({"stage": "canonical-program-and-execution-record-construction-only",
    "program_valid": True, "activations": len(model.activations), "resources": len(model.resources),
    "operations": len(model.operations), "uses": len(model.uses),
    "execution_validator_run": False}, sort_keys=True))
