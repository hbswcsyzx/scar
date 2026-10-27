"""Bounded read-only IR review; does not import torch or execute a workload."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

from scar.ir.execution.common import Unresolved
from scar.ir.execution.coordinates import (
    BlockVisit, OperationOccurrence, ProcessInstance, UnresolvedHostThread,
    UseOccurrence, ValueOccurrence,
)
from scar.ir.execution.ids import (
    BlockVisitID, OperationOccurrenceID, ProcessInstanceID, ValueOccurrenceID,
)
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from scar.ir.program.ids import BlockID, UseID
from tests.fixtures.execution_paths import declared_path
from tests.fixtures.program_graphs import loop_state_program
from tests.fixtures.execution_resource_graphs import resource_execution_with_allocation


ROOT = Path.cwd()
OUTPUT = Path(__file__).with_name("results.json")
FILES = tuple(f"scar/ir/execution/{name}.py" for name in (
    "model", "snapshot", "validation", "flow", "query", "resource_validation"))
results = {"python": sys.version, "source_hashes": {
    name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in FILES}, "cases": {}}


def observe(name, function):
    try:
        value = function()
    except Exception as error:
        value = {"exception": type(error).__name__, "message": str(error)}
    results["cases"][name] = value


def summarize(model, program, **kwargs):
    report = validate(model, program, **kwargs)
    return {"valid": report.valid, "issues": [row.code for row in report.issues],
            "gaps": sorted({row.code for row in report.gaps})}


program = loop_state_program()
path = [(BlockID(name), edge) for name, edge in (
    ("loop.entry", 0), ("header", 0), ("body", 0), ("header", 0),
    ("body", 0), ("header", 1), ("exit", None))]
model = declared_path(program, path)
observe("baseline", lambda: summarize(model, program))
assert results["cases"]["baseline"]["valid"]

other = ProcessInstance(ProcessInstanceID("other-process"), model.runs[0].id,
                        22, model.runs[0].source)
foreign_point = replace(model.activations[0].entry, process=other.id)
foreign_ingress = replace(model.segments[0].ingress, source=foreign_point)
observe("same_run_foreign_process_ingress", lambda: summarize(replace(model,
    processes=(*model.processes, other),
    segments=(replace(model.segments[0], ingress=foreign_ingress),)), program))
observe("same_run_foreign_process_unresolved_thread_point", lambda: summarize(replace(model,
    processes=(*model.processes, other),
    segments=(replace(model.segments[0],
        host_thread=UnresolvedHostThread("thread not captured", foreign_point)),)), program))

first_visit = model.visits[0]
second_visit = BlockVisit(BlockVisitID("second-entry"), first_visit.segment, first_visit.block)
first_occurrence = next(row for row in model.operations if row.visit == first_visit.id)
second_occurrence = OperationOccurrence(OperationOccurrenceID("second-entry.enter"),
                                        second_visit.id, first_occurrence.operation)
original_formals = [row for row in model.values if row.origin == first_visit.id]
copied = {row.id: ValueOccurrenceID("second-entry." + row.value.value) for row in original_formals}
new_values = tuple(ValueOccurrence(copied[row.id], row.value, second_visit.id)
                   for row in original_formals)
new_uses = tuple(UseOccurrence(second_occurrence.id, row.use, copied[row.value])
                 for row in model.uses if row.operation == first_occurrence.id)
observe("second_initial_entry_root_same_activation", lambda: summarize(replace(model,
    visits=(*model.visits, second_visit), operations=(*model.operations, second_occurrence),
    values=(*model.values, *new_values), uses=(*model.uses, *new_uses)), program))

missing = OperationOccurrenceID("5.read.counter")
gap = Unresolved("current read was not observed", model.activations[0].entry)
changed_uses = []
for row in model.uses:
    if row.operation == missing:
        continue
    if row.operation == OperationOccurrenceID("5.compare") and row.use == UseID("compare.counter"):
        row = replace(row, value=gap)
    elif row.operation == OperationOccurrenceID("6.loop.done") and row.use == UseID("loop.done.value"):
        row = replace(row, value=ValueOccurrenceID("3.counter.value"))
    changed_uses.append(row)
observe("old_result_after_new_defining_visit_but_missing_producer", lambda: summarize(replace(model,
    operations=tuple(row for row in model.operations if row.id != missing),
    values=tuple(row for row in model.values if row.origin != missing), uses=tuple(changed_uses)), program))

observe("unknown_transfer_source", lambda: summarize(replace(model, transfers=(
    replace(model.transfers[0], operation=OperationOccurrenceID("absent")), *model.transfers[1:])), program))
observe("unknown_transfer_target", lambda: summarize(replace(model, transfers=(
    replace(model.transfers[0], target=BlockVisitID("absent")), *model.transfers[1:])), program))
index = ExecutionIndex(model, program)
observe("query_bad_point_type", lambda: index.state_at(None))
link = index.definition_for_use(OperationOccurrenceID("3.compare"), UseID("compare.counter"))
results["cases"]["definition_link_field_types"] = {
    name: type(getattr(link, name)).__module__ + "." + type(getattr(link, name)).__name__
    for name in ("operation", "use", "definition", "occurrence", "origin")}

allocation_program, allocation_model, catalog = resource_execution_with_allocation()
observe("allocation_baseline", lambda: summarize(allocation_model, allocation_program, value_graphs=catalog))
placement, = allocation_model.placements
metadata = replace(placement.allocation.artifact, size_bytes=placement.allocation.artifact.size_bytes + 1)
observe("allocation_metadata_mismatch", lambda: summarize(replace(allocation_model,
    placements=(replace(placement, allocation=replace(placement.allocation, artifact=metadata)),)),
    allocation_program, value_graphs=catalog))
observe("allocation_missing_catalog", lambda: summarize(allocation_model, allocation_program))
observe("allocation_invalid_catalog_type", lambda: summarize(allocation_model, allocation_program, value_graphs=[]))

results["torch_imported"] = "torch" in sys.modules
results["source_hashes_after"] = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in FILES}
OUTPUT.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
print(json.dumps(results, indent=2, sort_keys=True))
