"""Call-scoped values, storage and readiness for resource-task scheduling.

This IR separates allocation from value production. Its implemented lowering is
synchronous CPU computation; explicit copy routes are future, non-executable
proposals. A retained inventory connection alone never authorizes a transfer.
"""

from collections import deque
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from scar.compiler.model import ExecutionPlan, LoopAxis
from scar.compiler.validation import validate_plan
from scar.ir.program import target_hardware as H
from scar.ir.record_codec import decode, encode
from .hardware import _boundaries, _target_materials, validate_cpu_placement


class TaskKind(str, Enum):
    ALLOCATION = "ALLOCATION"
    COPY = "COPY"
    COMPUTE = "COMPUTE"
    WAIT = "WAIT"
    RELEASE = "RELEASE"
    EXPORT = "EXPORT"


@dataclass(frozen=True)
class LogicalValue:
    id: str
    producer: str | None = None
    escape: bool = False
    call_scope: str = "$CALL_INSTANCE"
    source_nodes: tuple[str, ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Materialization:
    id: str
    value: str
    location: str
    resource_refs: tuple[dict[str, Any], ...] = ()
    ready_task: str | None = None
    external_ready: bool = False
    allocated_by: str | None = None
    ownership: str = "SCHEDULE"
    bytes_expr: str | None = None


@dataclass(frozen=True)
class Task:
    id: str
    kind: TaskKind
    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    resource_refs: tuple[dict[str, Any], ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResourceSchedule:
    region_id: str
    values: tuple[LogicalValue, ...]
    materializations: tuple[Materialization, ...]
    tasks: tuple[Task, ...]
    loop_axes: tuple[LoopAxis, ...] = ()
    call_scope: str = "$CALL_INSTANCE"
    proof: dict[str, Any] = field(default_factory=dict)
    unresolved: tuple[dict[str, Any], ...] = ()
    executable: bool = False


@dataclass(frozen=True)
class CopyLink:
    """An explicit transport declaration, separate from inventory reachability."""
    id: str
    source_location: str
    target_location: str
    evidence: tuple[dict[str, Any], ...] = ()
    copy_contract: dict[str, Any] = field(default_factory=dict)
    cost: dict[str, Any] | None = None
    bidirectional: bool = False


@dataclass(frozen=True)
class ConnectionResult:
    materialization: Materialization
    tasks: tuple[Task, ...] = ()
    unresolved: tuple[dict[str, Any], ...] = ()
    executable: bool = False


def schedule_document(schedule) -> dict:
    return {"schema": "scar.resource-schedule", "schema_version": 1, **encode(schedule)}


def schedule_from_dict(document) -> ResourceSchedule:
    document = dict(document)
    if (document.pop("schema", None), document.pop("schema_version", None)) != ("scar.resource-schedule", 1):
        raise ValueError("unsupported resource schedule schema")
    result = decode(ResourceSchedule, document)
    validate_schedule(result)
    return result


def _unique(records, label):
    result = {}
    for record in records:
        if not isinstance(record.id, str) or not record.id or record.id in result:
            raise ValueError(f"invalid or duplicate {label} ID")
        result[record.id] = record
    return result


def validate_schedule(schedule) -> dict:
    """Validate causality, ownership and escaping storage, not just tuple order."""
    if not isinstance(schedule, ResourceSchedule):
        raise ValueError("ResourceSchedule required")
    values = _unique(schedule.values, "logical value")
    materials = _unique(schedule.materializations, "materialization")
    tasks = _unique(schedule.tasks, "task")
    if not schedule.call_scope or any(v.call_scope != schedule.call_scope for v in values.values()):
        raise ValueError("logical values must belong to this invocation scope")
    if schedule.executable and schedule.unresolved:
        raise ValueError("unresolved schedules cannot be executable")
    indegrees, users = {}, {key: [] for key in tasks}
    for task in tasks.values():
        if not isinstance(task.kind, TaskKind):
            raise ValueError("typed task kind required")
        if len(set(task.depends_on)) != len(task.depends_on) or any(d not in tasks for d in task.depends_on):
            raise ValueError("dangling or duplicate task dependency")
        if any(m not in materials for m in task.reads + task.writes):
            raise ValueError("dangling task materialization reference")
        indegrees[task.id] = len(task.depends_on)
        for dependency in task.depends_on:
            users[dependency].append(task.id)
        if task.kind is TaskKind.ALLOCATION and (task.reads or not task.writes):
            raise ValueError("allocation prepares storage only")
        if task.kind is TaskKind.COPY and (len(task.reads) != 1 or len(task.writes) != 1):
            raise ValueError("copy requires one source and one destination")
        if task.kind in (TaskKind.RELEASE, TaskKind.EXPORT) and (not task.reads or task.writes):
            raise ValueError("release/export requires existing storage references")
        if schedule.executable and (task.attrs.get("non_executable") or
                                    task.kind in (TaskKind.COPY, TaskKind.WAIT)):
            raise ValueError("COPY/WAIT lowering is not implemented")

    ready = deque(key for key in tasks if indegrees[key] == 0)
    order, ancestors = [], {}
    while ready:
        key = ready.popleft()
        task = tasks[key]
        ancestors[key] = set(task.depends_on)
        for dependency in task.depends_on:
            ancestors[key].update(ancestors[dependency])
        order.append(key)
        for user in users[key]:
            indegrees[user] -= 1
            if indegrees[user] == 0:
                ready.append(user)
    if len(order) != len(tasks):
        raise ValueError("task dependency graph contains a cycle")

    for value in values.values():
        if value.producer is not None and (value.producer not in tasks or
                                           tasks[value.producer].kind is not TaskKind.COMPUTE):
            raise ValueError("logical value producer must name a compute task")
    for material in materials.values():
        if material.value not in values or not material.location:
            raise ValueError("dangling value or missing materialization location")
        if material.ownership not in ("EXTERNAL", "SCHEDULE"):
            raise ValueError("unknown materialization ownership")
        if material.external_ready:
            if (material.ready_task is not None or material.allocated_by is not None
                    or material.ownership != "EXTERNAL" or values[material.value].producer is not None):
                raise ValueError("external readiness cannot claim a scheduled producer/allocation")
        elif material.ready_task is not None:
            if material.ready_task not in tasks or tasks[material.ready_task].kind not in (
                    TaskKind.COMPUTE, TaskKind.COPY, TaskKind.WAIT):
                raise ValueError("storage allocation does not establish value readiness")
            if material.id not in tasks[material.ready_task].writes:
                raise ValueError("ready task does not produce this materialization")
            if material.allocated_by is None:
                raise ValueError("scheduled materialization needs an explicit allocation")
            producer = values[material.value].producer
            if producer is not None and producer != material.ready_task and producer not in ancestors[material.ready_task]:
                raise ValueError("materialization readiness precedes its logical value producer")
        if material.allocated_by is not None:
            allocation = tasks.get(material.allocated_by)
            if (allocation is None or allocation.kind is not TaskKind.ALLOCATION
                    or material.id not in allocation.writes or material.ownership != "SCHEDULE"):
                raise ValueError("invalid storage allocation reference")

    released = {}
    exported = set()
    writers = {key: [] for key in materials}
    for task in tasks.values():
        for material_id in task.writes:
            material = materials[material_id]
            if task.kind is TaskKind.ALLOCATION:
                if material.allocated_by != task.id:
                    raise ValueError("allocation/materialization ownership mismatch")
            elif task.kind in (TaskKind.COMPUTE, TaskKind.COPY):
                writers[material_id].append(task.id)
                if material.ownership == "EXTERNAL":
                    raise ValueError("external input storage cannot be overwritten")
            elif task.kind is not TaskKind.WAIT:
                raise ValueError("task kind cannot write materialized values")
        for material_id in set(task.reads + task.writes):
            material = materials[material_id]
            if material.allocated_by is not None and task.kind is not TaskKind.ALLOCATION:
                if material.allocated_by not in ancestors[task.id]:
                    raise ValueError("storage used before its allocation dependency")
        for material_id in task.reads:
            material = materials[material_id]
            if task.kind is not TaskKind.RELEASE and not material.external_ready:
                if material.ready_task is None or material.ready_task not in ancestors[task.id]:
                    raise ValueError("value read before its readiness dependency")
            if task.kind is TaskKind.RELEASE:
                if material.ownership != "SCHEDULE" or material_id in released:
                    raise ValueError("external or already released storage cannot be released")
                released[material_id] = task.id
            elif task.kind is TaskKind.EXPORT:
                if not values[material.value].escape:
                    raise ValueError("exported logical values must declare escape")
                exported.add(material_id)
        if task.kind is TaskKind.COPY:
            source, destination = (materials[task.reads[0]], materials[task.writes[0]])
            if source.value != destination.value:
                raise ValueError("copy must preserve logical value identity")
    for key, material_writers in writers.items():
        if len(material_writers) > 1:
            raise ValueError("materialization has multiple value-producing writers")
        material = materials[key]
        if material.ready_task is not None and not material_writers:
            raise ValueError("readiness requires actual value production, not allocation/wait alone")
        if material.ready_task is not None and material_writers:
            writer = material_writers[0]
            if writer != material.ready_task and writer not in ancestors[material.ready_task]:
                raise ValueError("readiness does not follow value production")
    for material_id, release in released.items():
        if material_id in exported:
            raise ValueError("escaping output storage cannot be released")
        for task in tasks.values():
            if task.id != release and material_id in task.reads + task.writes and task.id not in ancestors[release]:
                raise ValueError("storage use is after or unordered with its release")
    escaping_values = {v.id for v in values.values() if v.escape}
    if not escaping_values.issubset({materials[key].value for key in exported}):
        raise ValueError("escaping logical value has no retained export")
    return {"tasks": len(tasks), "materializations": len(materials),
            "topological_order": order, "executable": schedule.executable,
            "escape_storage_retained": True}


def build_region_schedule(plan: ExecutionPlan, target) -> ResourceSchedule:
    """Lower one region to explicit synchronous CPU allocation/data dependencies."""
    from scar.compiler.provenance import graph_value_sources

    validate_plan(plan)
    if plan.proof.get("supported") is not True or plan.proof.get("legal") is not True:
        raise ValueError("a supported, conditionally legal region plan is required")
    binding = plan.resource_binding
    if target is None and binding is not None:
        target = binding.target_path
    unresolved = []
    snapshot_refs, cpu_refs, memory_refs, boundary = (), (), (), {}
    if target is None:
        unresolved.append({"reason": "TARGET_HARDWARE_MATERIAL_UNAVAILABLE",
                           "scope": "No hardware snapshot or executor binding is invented."})
    else:
        graph, snapshot, resources, connections = _target_materials(target)
        if binding is not None:
            validate_cpu_placement(binding)
            if snapshot.sha256 != binding.target_sha256:
                raise ValueError("schedule target differs from the bound original snapshot")
        snapshot_refs = ({"kind": "target_snapshot", "artifact": encode(snapshot)},)
        cpus = [r for r in resources if isinstance(r, H.CpuExecutor)
                and (binding is None or str(r.id) == binding.executor_id)]
        memories = [r for r in resources if isinstance(r, H.MemoryDomain)
                    and r.kind is H.MemoryKind.HOST]
        cpu_refs = ({"kind": "cpu_executor_binding" if binding else "cpu_executor_candidates",
                     "refs": [encode(H.TargetResourceRef(snapshot, r.id)) for r in cpus],
                     "cpu_ids": list(binding.cpu_ids) if binding else [],
                     "selection": "EXPLICIT_BINDING" if binding else "UNBOUND"},)
        memory_refs = ({"kind": "host_memory_candidates",
                        "refs": [encode(H.TargetResourceRef(snapshot, r.id)) for r in memories],
                        "planning_domain_id": binding.memory_domain_id if binding else None,
                        "placement": "UNBOUND", "physical_residency_proven": False},)
        boundary = _boundaries(resources, connections)
    location = "host-address-space:$CALL_PROCESS"
    source_graph = graph_value_sources(plan)
    values, materials = [], []
    input_ids = []
    nodes_by_id = {node.id: node for node in plan.region.nodes}
    live, pending = set(), [plan.region.output]
    while pending:
        node_id = pending.pop()
        if node_id not in live:
            live.add(node_id)
            pending.extend(nodes_by_id[node_id].inputs)
    for index, parameter in enumerate(plan.region.parameters):
        value_id, material_id = f"parameter:{index}", f"host:parameter:{index}"
        source_nodes = tuple(n.id for n in plan.region.nodes if n.op == "input" and n.attrs["name"] == parameter)
        values.append(LogicalValue(value_id, source_nodes=source_nodes,
                                   attrs={"parameter": parameter,
                                          "identity": f"$CALL_INSTANCE:parameter:{index}",
                                          "dtype": "float64", "rank": 2,
                                          "source_graph": [record for node_id in source_nodes
                                                           for record in source_graph.get(node_id, ())]}))
        materials.append(Materialization(material_id, value_id, location,
                                         snapshot_refs + memory_refs, external_ready=True,
                                         ownership="EXTERNAL", bytes_expr=f"parameter[{index}].nbytes"))
        if any(node_id in live for node_id in source_nodes):
            input_ids.append(material_id)
    values.append(LogicalValue("output", "compute:region", True,
                               source_nodes=(plan.region.output,),
                               attrs={"identity": "$CALL_INSTANCE:output", "fresh_each_call": True,
                                      "source_graph": list(source_graph.get(plan.region.output, ()))}))
    output = Materialization("host:output", "output", location, snapshot_refs + memory_refs,
                             ready_task="compute:region", allocated_by="allocate:output",
                             bytes_expr="8 * output_elements")
    materials.append(output)
    budget = plan.cost.get("memory_budget_bytes")
    tasks = (
        Task("allocate:output", TaskKind.ALLOCATION, writes=(output.id,),
             resource_refs=output.resource_refs,
             attrs={"bytes_expr": output.bytes_expr, "memory_budget_bytes": budget,
                    "memory_policy": "UNBOUND", "establishes_value_ready": False,
                    "runtime_guards": ["ALLOCATION_SUCCEEDS"] +
                                      (["OUTPUT_NBYTES_WITHIN_MEMORY_BUDGET"] if budget is not None else [])}),
        Task("compute:region", TaskKind.COMPUTE, tuple(input_ids), (output.id,), ("allocate:output",),
             snapshot_refs + cpu_refs,
             {"region_id": plan.region.id, "cpu_threads": plan.cpu_threads,
              "executor_id": binding.executor_id if binding else None,
              "bytes_expr": output.bytes_expr, "shared_scalar_dag": True,
              "nodes": [encode(n) for n in plan.region.nodes], "output_node": plan.region.output,
              "backend_support": "SYNCHRONOUS_CPU_ARRAY_REGION", "non_executable": False}),
        Task("export:output", TaskKind.EXPORT, (output.id,), depends_on=("compute:region",),
             attrs={"ownership": "CALLER", "escape": True, "release": False}),
    )
    schedule = ResourceSchedule(plan.region.id, tuple(values), tuple(materials), tasks,
                                loop_axes=plan.schedule,
                                proof={"status": "PROPOSED", "selected": False,
                                       "value_identity_scope": "CALL_INSTANCE",
                                       "input_readiness": "EXTERNAL_AT_INVOCATION_UNDER_ARRAY_GUARDS",
                                       "memory_policy": "UNBOUND", "numa_residency_proven": False,
                                       "bytes_expr": output.bytes_expr, "memory_budget_bytes": budget,
                                       "capacity_is_available_budget": False,
                                       "runtime_guards": list(plan.proof.get("runtime_guards", ())),
                                       "external_assumptions": list(plan.proof.get("legality", {}).get("external_assumptions", ())),
                                       "target_refs": list(snapshot_refs), "unsupported_boundaries": boundary,
                                       "loop_representation": "SHARED_SCALAR_DAG_NO_UNROLL",
                                       "transfer_cost": "NO_COPY_REQUIRED_IN_HOST_ADDRESS_SPACE",
                                       "optimality_proven": False},
                                unresolved=tuple(unresolved), executable=not unresolved)
    validate_schedule(schedule)
    return schedule


def _contract_supported(contract):
    return (isinstance(contract, dict) and contract.get("value_preserving") is True
            and isinstance(contract.get("evidence"), (list, tuple)) and bool(contract["evidence"]))


def connect_materialization(value, src, dst, topology, *, contract=None, cost=None) -> ConnectionResult:
    """Reuse storage or propose an explicit, non-executable copy route.

    topology is an iterable of CopyLink declarations. Raw hardware inventory
    links are not copy contracts. Unknown costs remain UNKNOWN, and this helper
    chooses the first deterministic legal path without claiming an optimum.
    COPY/WAIT backends are not implemented, so even a valid route is unresolved
    for execution until a backend admits that exact transport contract.
    """
    if src.value != value.id or dst.value != value.id:
        raise ValueError("materialization connection must preserve logical value identity")
    if not src.external_ready and src.ready_task is None:
        return ConnectionResult(dst, unresolved=({"reason": "SOURCE_VALUE_NOT_READY"},))
    if src.location == dst.location:
        return ConnectionResult(src, executable=True)
    try:
        links = tuple(topology)
    except TypeError:
        return ConnectionResult(dst, unresolved=({"reason": "NO_EXPLICIT_COPY_TOPOLOGY_OR_CONTRACT"},))
    if any(not isinstance(link, CopyLink) for link in links):
        return ConnectionResult(dst, unresolved=({"reason": "INVENTORY_REACHABILITY_IS_NOT_A_COPY_CONTRACT"},))
    outgoing = {}
    for link in sorted(links, key=lambda link: link.id):
        if not link.evidence or not _contract_supported(link.copy_contract or contract):
            continue
        outgoing.setdefault(link.source_location, []).append((link.target_location, link))
        if link.bidirectional:
            outgoing.setdefault(link.target_location, []).append((link.source_location, link))
    pending, seen, route = deque([(src.location, ())]), {src.location}, None
    while pending:
        location, path = pending.popleft()
        if location == dst.location:
            route = path
            break
        for destination, link in outgoing.get(location, ()):
            if destination not in seen:
                seen.add(destination)
                pending.append((destination, path + (link,)))
    if route is None:
        return ConnectionResult(dst, unresolved=({"reason": "NO_LEGAL_COPY_PATH_WITH_CONTRACT_EVIDENCE",
                                                  "source": src.location, "target": dst.location},))
    allocation_id, copy_id = f"allocate:{dst.id}", f"copy:{src.id}:{dst.id}"
    if dst.allocated_by is not None or dst.ready_task is not None or dst.external_ready:
        return ConnectionResult(dst, unresolved=({"reason": "DESTINATION_STORAGE_STATE_REQUIRES_EXPLICIT_INTEGRATION"},))
    result = replace(dst, ready_task=copy_id, allocated_by=allocation_id, ownership="SCHEDULE")
    dependencies = (allocation_id,) + ((src.ready_task,) if src.ready_task is not None else ())
    refs = tuple(reference for link in route for reference in link.evidence)
    tasks = (
        Task(allocation_id, TaskKind.ALLOCATION, writes=(dst.id,), resource_refs=dst.resource_refs,
             attrs={"bytes_expr": dst.bytes_expr, "establishes_value_ready": False,
                    "non_executable": True}),
        Task(copy_id, TaskKind.COPY, (src.id,), (dst.id,), dependencies, refs,
             {"route": [encode(link) for link in route],
              "contract": contract or {"status": "PER_LINK_DECLARATIONS"},
              "cost": cost if cost is not None else {"status": "UNKNOWN", "per_link": [link.cost for link in route]},
              "path_selection": "FIRST_DECLARED_LEGAL_PATH_NOT_OPTIMAL",
              "non_executable": True, "backend_support": "UNIMPLEMENTED"}),
    )
    return ConnectionResult(result, tasks,
                            ({"reason": "COPY_BACKEND_NOT_IMPLEMENTED", "task": copy_id},), False)
