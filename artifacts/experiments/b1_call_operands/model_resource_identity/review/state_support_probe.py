"""Isolated same-activation stale support with an unobserved current formal."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

from scar.ir.execution.common import Unresolved
from scar.ir.execution.ids import RealizationID, ResourceAccessID, ResourceBindingID, ResourceInstanceID, ValueOccurrenceID
from scar.ir.execution.resources import (
    ImplicitBinding, ImportedAt, InstanceTarget, ProcessRealm, RequirementBinding,
    ResourceAccessBinding, ResourceInstance, ResourceRealization,
)
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.validation import validate
from scar.ir.program.ids import BlockID, LocationID, OperationID, ResourceDefinitionID, ResourceRequirementID
from scar.ir.program.providers import ProviderFactReference
from scar.ir.program.resources import ExternalResource, ResourceDefinition, ResourceKind, ResourceLocation, ResourceRequirement, ResourceRole, ResourceUse
from tests.fixtures.execution_paths import declared_path
from tests.fixtures.program_graphs import loop_state_program


files = tuple(f"scar/ir/execution/{name}.py" for name in ("validation", "flow", "resource_validation"))
hashes = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in files}
program = loop_state_program()
definition = ResourceDefinition(ResourceDefinitionID("executor"), ResourceKind.CPU, ResourceRole.EXECUTOR,
                                ExternalResource(program.root, "external-executor"))
requirement = ResourceRequirement(ResourceRequirementID("executor"), program.root,
                                 ResourceKind.CPU, ResourceRole.EXECUTOR)
program = replace(program, resources=(definition,), resource_requirements=(requirement,),
    resource_uses=(ResourceUse(OperationID("read.counter"), requirement.id, definition.id),),
    resource_locations=(ResourceLocation(LocationID("counter"), definition.id),))
model = declared_path(program, [(BlockID(name), edge) for name, edge in (
    ("loop.entry", 0), ("header", 0), ("body", 0), ("header", 0),
    ("body", 0), ("header", 1), ("exit", None))])
point = model.activations[0].entry
source = model.runs[0].source
instance = ResourceInstance(ResourceInstanceID("executor"), ResourceKind.CPU, ResourceRole.EXECUTOR,
                            ProcessRealm(model.processes[0].id), ImportedAt(point), source)
target = InstanceTarget(instance.id)
realization = ResourceRealization(RealizationID("executor"), definition.id, model.activations[0].id, target, source)
binding = RequirementBinding(ResourceBindingID("executor"), requirement.id, model.activations[0].id, target, source)
operation = next(row.id for row in model.operations if row.id.value == "5.read.counter")
fact = ProviderFactReference(model.snapshot.artifact, "selection-rule")


def report(changed):
    result = validate(changed, program)
    return {"valid": result.valid, "issues": [row.code for row in result.issues],
            "gaps": sorted({row.code for row in result.gaps})}


def with_access(current):
    support = (ValueOccurrenceID(current),)
    access = ResourceAccessBinding(ResourceAccessID("access"), operation, binding.id,
        ImplicitBinding(fact, support), support, (), source)
    return replace(model, resources=(instance,), realizations=(realization,),
                   requirements=(binding,), accesses=(access,))


baseline = with_access("5.header.state")
stale = with_access("3.header.state")
known_stale = report(stale)
missing_formal = ValueOccurrenceID("5.header.state")
stale = replace(stale, values=tuple(row for row in stale.values if row.id != missing_formal),
    uses=tuple(replace(row, value=Unresolved("current formal not captured", point))
               if row.value == missing_formal else row for row in stale.uses))
result = {"python": sys.version, "source_hashes": hashes,
          "baseline": report(baseline), "known_current_stale": known_stale,
          "unobserved_current_with_old_support": report(stale), "torch_imported": "torch" in sys.modules}
result["source_hashes_after"] = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in files}
text = json.dumps(result, indent=2, sort_keys=True) + "\n"
Path(__file__).with_name("state_support_results.json").write_text(text)
print(text, end="")
