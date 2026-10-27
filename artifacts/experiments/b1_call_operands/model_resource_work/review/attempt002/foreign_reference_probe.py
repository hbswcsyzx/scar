from dataclasses import replace

from scar.ir.execution.common import ProviderFactReference
from scar.ir.execution.ids import (
    ResourceAccessID, ResourceInstanceID, ValueOccurrenceID,
)
from scar.ir.execution.resources import InstanceTarget, ProcessRealm, ResourceInstance
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.validation import validate
from tests.fixtures.execution_work_graphs import ordinary_work_execution

program, model, values = ordinary_work_execution(queued=True)
base = validate(model, program, value_graphs=values)
print('base_valid=', base.valid)

bad_executor = replace(model, submissions=(replace(
    model.submissions[0], executor=ResourceAccessID('missing-access')),*model.submissions[1:]))
report = validate(bad_executor, program, value_graphs=values)
print('missing_executor_crashed=False', 'issues=', [row.code for row in report.issues])

bad_result = replace(model, outcomes=(replace(
    model.outcomes[0], protocol_result=ValueOccurrenceID('missing-value')),*model.outcomes[1:]))
report = validate(bad_result, program, value_graphs=values)
print('missing_result_crashed=False', 'issues=', [row.code for row in report.issues])

bad_target = replace(model, retentions=(replace(
    model.retentions[0], target=InstanceTarget(ResourceInstanceID('missing-instance'))),*model.retentions[1:]))
report = validate(bad_target, program, value_graphs=values)
print('missing_retention_instance_crashed=False', 'issues=', [row.code for row in report.issues])

bad_resource = ResourceInstance(
    ResourceInstanceID('foreign-process-resource'),
    model.resources[0].kind, model.resources[0].role,
    ProcessRealm(type(model.processes[0].id)('missing-process')),
    model.resources[0].origin, model.resources[0].source,
)
bad_realm = replace(model, resources=(*model.resources, bad_resource), retentions=(replace(
    model.retentions[0], target=InstanceTarget(bad_resource.id)), *model.retentions[1:]))
report = validate(bad_realm, program, value_graphs=values)
print('missing_process_crashed=False', 'issues=', [row.code for row in report.issues])
