"""Admit only resource-task plans this synchronous CPU boundary executes."""
from dataclasses import asdict
import json

from scar.compiler.validation import validate_plan
from scar.optimization.schedule import (
    ResourceSchedule,TaskKind,build_region_schedule,schedule_document,schedule_from_dict,validate_schedule,
)

def _wire(value):return json.loads(json.dumps(value,allow_nan=False))

def admit_schedule(plan,schedule):
    """Reject unimplemented scheduling actions instead of dropping them.

    Python prepares a fresh output allocation and exports its handle. Native
    code executes the shared loop body and synchronously joins its workers.
    This admission does not implement a general task interpreter or transfers.
    """
    validate_plan(plan)
    if isinstance(schedule,dict):schedule=schedule_from_dict(schedule)
    if not isinstance(schedule,ResourceSchedule):raise ValueError('typed resource schedule required')
    validate_schedule(schedule)
    if not schedule.executable or schedule.unresolved:
        raise ValueError('unresolved resource schedules cannot be lowered')
    if schedule.region_id!=plan.region.id or schedule.loop_axes!=plan.schedule:
        raise ValueError('resource schedule refers to a different region or loop domain')
    if schedule.call_scope!='$CALL_INSTANCE':raise ValueError('resource schedule must be invocation scoped')
    by_kind={kind:[] for kind in TaskKind}
    for task in schedule.tasks:by_kind[task.kind].append(task)
    required=(TaskKind.ALLOCATION,TaskKind.COMPUTE,TaskKind.EXPORT)
    if len(schedule.tasks)!=3 or any(len(by_kind[k])!=1 for k in required):
        raise ValueError('backend supports only synchronous allocation, compute and export')
    allocation,compute,export=(by_kind[k][0] for k in required)
    if (allocation.id not in compute.depends_on or compute.id not in export.depends_on
            or len(compute.writes)!=1 or allocation.writes!=compute.writes or export.reads!=compute.writes):
        raise ValueError('backend storage and execution dependencies differ from resource schedule')
    binding=plan.resource_binding
    if binding is None:raise ValueError('resource-task lowering requires an explicit recorded CPU binding')
    expected_executor=None if binding is None else binding.executor_id
    attrs=compute.attrs
    if (attrs.get('region_id')!=plan.region.id or attrs.get('cpu_threads')!=plan.cpu_threads
            or attrs.get('executor_id')!=expected_executor or attrs.get('shared_scalar_dag') is not True
            or attrs.get('output_node')!=plan.region.output
            or _wire(attrs.get('nodes'))!=_wire([asdict(n) for n in plan.region.nodes])):
        raise ValueError('compute task differs from the exact admitted scalar DAG or executor')
    if (allocation.attrs.get('memory_budget_bytes')!=plan.cost.get('memory_budget_bytes')
            or allocation.attrs.get('memory_policy')!='UNBOUND'
            or allocation.attrs.get('establishes_value_ready') is not False):
        raise ValueError('allocation budget or readiness differs from backend policy')
    values={v.id:v for v in schedule.values};materials={m.id:m for m in schedule.materializations}
    output=materials[compute.writes[0]]
    if (output.allocated_by!=allocation.id or output.ready_task!=compute.id
            or output.bytes_expr!='8 * output_elements' or output.ownership!='SCHEDULE'
            or values[output.value].source_nodes!=(plan.region.output,)
            or not values[output.value].escape or values[output.value].producer!=compute.id):
        raise ValueError('fresh output, readiness and escape contract differ')
    if allocation.attrs.get('bytes_expr')!=output.bytes_expr or compute.attrs.get('bytes_expr')!=output.bytes_expr:
        raise ValueError('allocation and compute size expressions differ from output storage')
    if export.attrs.get('ownership')!='CALLER' or export.attrs.get('release') is not False:
        raise ValueError('export must retain ownership for the caller')
    parameters={n.id for n in plan.region.nodes if n.op=='input'}
    external=[m for m in schedule.materializations if m.external_ready]
    if (len(external)!=len(parameters) or set(materials)!={m.id for m in external}|{output.id}
            or any(not m.external_ready for m in external)
            or any(len(values[m.value].source_nodes)!=1 or values[m.value].source_nodes[0] not in parameters for m in external)
            or {values[m.value].source_nodes[0] for m in external}!=parameters
            or not set(compute.reads)<={m.id for m in external}):
        raise ValueError('resource inputs do not match original guarded ndarray parameters')
    # Every live input must be read. Unused parameters can still have metadata
    # admission without becoming fabricated array-content dependencies.
    nodes={n.id:n for n in plan.region.nodes};live=set();pending=[plan.region.output]
    while pending:
        key=pending.pop()
        if key not in live:live.add(key);pending.extend(nodes[key].inputs)
    read_inputs={values[materials[mid].value].source_nodes[0] for mid in compute.reads}
    if read_inputs!=parameters&live:raise ValueError('resource schedule omits or invents array data reads')
    if any(m.location!='host-address-space:$CALL_PROCESS' for m in schedule.materializations):
        raise ValueError('device or NUMA-specific materialization is not implemented')
    if any(ref.get('kind')=='host_memory_candidates' and ref.get('placement')!='UNBOUND'
           for m in schedule.materializations for ref in m.resource_refs):
        raise ValueError('backend does not implement NUMA page placement')
    # The current backend implements exactly one closed task profile. Original
    # resource receipts and all task constraints must agree with its producer;
    # additional timing/placement attributes cannot be silently ignored.
    expected=build_region_schedule(plan,binding.target_path)
    if _wire(schedule_document(schedule))!=_wire(schedule_document(expected)):
        raise ValueError('resource references or task constraints differ from supported CPU lowering')
    return schedule_document(schedule)
