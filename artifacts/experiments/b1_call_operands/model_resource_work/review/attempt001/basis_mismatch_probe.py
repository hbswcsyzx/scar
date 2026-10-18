from dataclasses import replace

from scar.ir.execution.coordinates import UseRef
from scar.ir.execution.ids import ResourceAccessID
from scar.ir.execution.validation import validate
from tests.fixtures.execution_work_graphs import ordinary_work_execution

program, model, values = ordinary_work_execution(retained='handle')
retention = model.retentions[0]
handle = next(row for row in model.handles if row.id == retention.target.binding)
print('handle_target=', handle.target)
print('handle_endpoint=', handle.handle)
print('declared_basis=', retention.basis)
base = validate(model, program, value_graphs=values)
print('base_issues=', [(row.code, row.path) for row in base.issues])

other_use = next(row.use for row in model.uses
                 if row.operation == retention.basis.operation
                 and row.use.value.endswith('.fd'))
other_use_value = next(row.value for row in model.uses
                       if row.operation == retention.basis.operation and row.use == other_use)
wrong_use_model = replace(
    model,
    retentions=(replace(retention, basis=UseRef(retention.basis.operation, other_use)),),
)
wrong_use_report = validate(wrong_use_model, program, value_graphs=values)
print('wrong_use=', other_use, 'bound_value=', other_use_value)
print('wrong_use_issues=', [(row.code, row.path) for row in wrong_use_report.issues])
print('wrong_use_retention_gaps=', [row.code for row in wrong_use_report.gaps
                                   if row.code.startswith('work_retention')])

wrong_access = ResourceAccessID('work.queue.' + retention.start.operation.value)
wrong_access_model = replace(
    model,
    retentions=(replace(retention, basis=wrong_access),),
)
wrong_access_report = validate(wrong_access_model, program, value_graphs=values)
wrong_access_row = next(row for row in model.accesses if row.id == wrong_access)
wrong_access_binding = next(row for row in model.requirements
                            if row.id == wrong_access_row.requirement)
print('wrong_access=', wrong_access, 'target=', wrong_access_binding.target)
print('wrong_access_issues=', [(row.code, row.path) for row in wrong_access_report.issues])
print('wrong_access_retention_gaps=', [row.code for row in wrong_access_report.gaps
                                      if row.code.startswith('work_retention')])
