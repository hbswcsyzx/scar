from dataclasses import replace

from scar.ir.execution.coordinates import OccurrencePhase, OccurrencePoint
from scar.ir.execution.ids import OperationOccurrenceID, QueuePrefixID, WorkTicketID
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.validation import validate
from scar.ir.execution.work import Queued
from scar.ir.program.codec import dumps as program_dumps
from tests.fixtures.execution_work_graphs import ordinary_work_execution


def activation_for(model, operation):
    occurrence = next(row for row in model.operations if row.id == operation)
    visit = next(row for row in model.visits if row.id == occurrence.visit)
    segment = next(row for row in model.segments if row.id == visit.segment)
    return segment.activation


def validate_and_print(label, program, model, **kwargs):
    report = validate(model, program, **kwargs)
    print(label, "valid=", report.valid)
    print("issues=", [(row.code, row.path) for row in report.issues])
    print("gaps=", [(row.code, row.path) for row in report.gaps if "order" in row.code or "scope" in row.code or "ticket" in row.code])
    return report


# Same run/process, but an observation occurrence in activation 1 is attached
# to work submitted inside activation 0.  No total order is established between
# these activation-local points.
program, model, _ = ordinary_work_execution(activations=2)
work = model.submissions[0]
owner_activation = activation_for(model, work.origin.operation)
other_occurrence = next(row for row in model.operations if activation_for(model, row.id) != owner_activation)
updated_outcome = replace(model.outcomes[0], observed_at=OccurrencePoint(other_occurrence.id, OccurrencePhase.BEFORE))
changed = replace(model, outcomes=(updated_outcome, *model.outcomes[1:]))
report = validate_and_print("cross_activation_outcome_observation", program, changed)
print("outcome_owner_activation=", owner_activation)
print("outcome_observed_activation=", activation_for(changed, other_occurrence.id))
print("has_unresolved_outcome_order_gap=", any(row.code == "work_observation_order_unresolved" for row in report.gaps))

# A known but absent dependency ticket must be a structured issue, not a crash.
program, model, _ = ordinary_work_execution()
work = model.submissions[0]
changed_work = replace(work, dependencies=(WorkTicketID("missing.ticket"),))
changed = replace(model, submissions=(changed_work, *model.submissions[1:]))
validate_and_print("missing_dependency_ticket", program, changed)

# A queue prefix with a missing predecessor is another work-side foreign key.
program, model, _ = ordinary_work_execution(queued=True)
prefix = model.queue_prefixes[0]
changed_prefix = replace(prefix, previous=QueuePrefixID("missing.prefix"))
changed = replace(model, queue_prefixes=(changed_prefix, *model.queue_prefixes[1:]))
validate_and_print("missing_queue_prefix_fk", program, changed)

# Remove a static requirement referenced by resource bindings, updating the
# canonical program snapshot. Resource validation should report the broken FK
# before work_validation's requirement lookup is reached.
program, model, _ = ordinary_work_execution()
requirement_ids = {row.requirement for row in model.requirements}
program = replace(program, resource_requirements=tuple(row for row in program.resource_requirements if row.id not in requirement_ids))
model = replace(model, snapshot=snapshot_for(program))
validate_and_print("missing_static_requirement_fk", program, model)

# A missing enclosing operation in an internal retention start must also be
# diagnostic, not a KeyError while checking support/intervals.
program, model, _ = ordinary_work_execution(retained="resource")
retention = model.retentions[0]
changed_retention = replace(retention, start=replace(retention.start, operation=OperationOccurrenceID("missing.operation")))
changed = replace(model, retentions=(changed_retention, *model.retentions[1:]))
validate_and_print("missing_within_operation_fk", program, changed)
