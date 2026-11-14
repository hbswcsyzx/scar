"""Bounded exact scheduling for an explicit, fixed-placement discrete model.

No timings are sampled and no costs are inferred from operation names. Durations
are caller-declared integer ticks; executor/channel capacities and incremental
allocation budgets must also be explicit. Optimality refers only to this model,
not to physical hardware, unmodeled transfers, or a production implementation.
"""

from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
import json

from .schedule import ResourceSchedule, TaskKind, schedule_document, validate_schedule


_MODEL_ASSUMPTIONS = [
    "EXPLICIT_INTEGER_TIME_TICKS_AND_FIXED_NONPREEMPTIVE_TASK_DURATIONS",
    "FIXED_TASK_PLACEMENT_AND_CONSTANT_RENEWABLE_RESOURCE_CAPACITIES",
    "TASK_PLACEMENTS_ARE_INPUTS_NOT_JOINTLY_SOLVED",
    "RESOURCE_CAPACITY_ONE_MEANS_EXCLUSIVE_EXECUTOR_OR_CHANNEL",
    "ALLOCATION_RESERVES_BYTES_AT_START_RELEASE_RETURNS_BYTES_AT_COMPLETION",
    "INCREMENTAL_MEMORY_BUDGET_EXCLUDES_EXTERNALLY_OWNED_INPUT_ALLOCATIONS",
    "UNRELEASED_AND_ESCAPING_STORAGE_REMAINS_LIVE_THROUGH_MAKESPAN",
    "NO_UNMODELED_CONTENTION_TRANSFER_LATENCY_OR_DYNAMIC_ALLOCATION_COST",
    "OPTIMALITY_IS_ONLY_WITHIN_THE_GIVEN_DISCRETE_MODEL",
]


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def semantic_sha256(document) -> str:
    """Digest canonical semantic JSON, independently of any raw-file receipt."""
    return sha256(json.dumps(document, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


def _shape_instantiation(plan, input_shapes):
    unknown = object()
    issues, declared = [], {}
    if isinstance(input_shapes, (list, tuple)):
        requested = {parameter: input_shapes for parameter in plan.region.parameters}
    elif isinstance(input_shapes, Mapping):
        requested = input_shapes
    else:
        requested = {}
    for parameter in plan.region.parameters:
        shape = requested.get(parameter)
        if not (isinstance(shape, (tuple, list)) and len(shape) == 2
                and all(_integer(axis) and axis <= 2**63 - 1 for axis in shape)):
            issues.append({"field": f"input_shapes.{parameter}",
                           "reason": "explicit rank-two nonnegative shape required for byte instantiation"})
        else:
            declared[parameter] = tuple(shape)
    shapes = {}
    for node in plan.region.nodes:
        if node.op == "input":
            shapes[node.id] = declared.get(node.attrs["name"], unknown)
        elif node.op == "const":
            shapes[node.id] = None
        elif node.op == "slice":
            parent = shapes[node.inputs[0]]
            shapes[node.id] = (unknown if parent is unknown else
                               tuple(max(0, stop - start) for start, stop, _ in
                                     (slice(*bounds).indices(extent) for bounds, extent in
                                      zip(node.attrs["bounds"], parent))))
        else:
            operands = [shapes[key] for key in node.inputs]
            if any(shape is unknown for shape in operands):
                shapes[node.id] = unknown
                continue
            arrays = [shape for shape in operands if shape is not None]
            if any(shape != arrays[0] for shape in arrays[1:]):
                issues.append({"field": f"input_shapes.operation.{node.id}",
                               "reason": "array operand shapes differ; the ABI does not broadcast arrays"})
                shapes[node.id] = unknown
            else:
                shapes[node.id] = arrays[0] if arrays else None
    output = shapes[plan.region.output]
    if output is unknown or output is None:
        return declared, None, issues
    return declared, output, issues


def hardware_model_skeleton(plan, schedule, *, input_shapes=None) -> dict:
    """Derive known fixed-CPU constraints, leaving costs and budgets unknown.

    Shapes are instantiated by the original DAG's unit-step slice rules. The
    host pool is an incremental process-address-space budget, never a claim of
    NUMA page placement. This helper does not jointly optimize placements.
    """
    from scar.compiler.model import document
    from scar.compiler.validation import validate_plan
    from scar.ir.record_codec import encode
    from .hardware import validate_cpu_placement

    validate_plan(plan)
    validate_schedule(schedule)
    if schedule.region_id != plan.region.id or schedule.loop_axes != plan.schedule:
        raise ValueError("model skeleton schedule differs from plan region or loop axes")
    unresolved = []
    binding = plan.resource_binding
    if binding is None:
        unresolved.append({"field": "plan.resource_binding", "reason": "recorded CPU IDs required; CPU count is not a placement"})
    else:
        validate_cpu_placement(binding)
    capacities, placements, memory_caps, sizes, locations = {}, {}, {}, {}, {}
    if binding is not None:
        capacities[binding.executor_id] = len(binding.cpu_ids)
    for task in schedule.tasks:
        unresolved.append({"field": f"task_costs.{task.id}.duration_ticks",
                           "reason": "hardware topology and work counts do not establish task duration"})
        if task.kind in (TaskKind.ALLOCATION, TaskKind.EXPORT):
            placements[task.id] = {}
        elif task.kind is TaskKind.COMPUTE and binding is not None:
            if (task.attrs.get("region_id") != plan.region.id
                    or task.attrs.get("cpu_threads") != plan.cpu_threads
                    or task.attrs.get("executor_id") != binding.executor_id
                    or semantic_sha256(task.attrs.get("nodes")) != semantic_sha256([encode(n) for n in plan.region.nodes])):
                unresolved.append({"field": f"task_placements.{task.id}",
                                   "reason": "compute payload or executor differs from fixed region binding"})
            else:
                placements[task.id] = {binding.executor_id: plan.cpu_threads}
        else:
            unresolved.append({"field": f"task_placements.{task.id}",
                               "reason": "COPY/WAIT/RELEASE or unbound task placement is not inferred or implemented"})
    declared_shapes, output_shape, shape_issues = _shape_instantiation(plan, input_shapes)
    unresolved.extend(shape_issues)
    output_elements = output_shape[0] * output_shape[1] if output_shape is not None else None
    budget = plan.cost.get("memory_budget_bytes")
    for material in schedule.materializations:
        if material.ownership != "SCHEDULE" or material.allocated_by is None:
            continue
        if material.location != "host-address-space:$CALL_PROCESS":
            unresolved.append({"field": f"memory_locations.{material.id}",
                               "reason": "device/NUMA physical pools are not derived from UNBOUND host policy"})
            continue
        pool = material.location
        locations[material.id] = pool
        if budget is None:
            unresolved.append({"field": f"memory_capacities.{pool}",
                               "reason": "available incremental budget is unknown; reported total capacity is not a budget"})
        else:
            memory_caps[pool] = budget
        if material.bytes_expr == "8 * output_elements" and output_elements is not None:
            sizes[material.id] = 8 * output_elements
        else:
            unresolved.append({"field": f"materialization_sizes.{material.id}",
                               "reason": "symbolic bytes need supported expression and an instantiated output shape"})
    schedule_hash = semantic_sha256(schedule_document(schedule))
    instantiation = {
        "region_id": plan.region.id, "plan_sha256": semantic_sha256(document(plan)),
        "schedule_sha256": schedule_hash,
        "input_shapes": {parameter: list(shape) for parameter, shape in declared_shapes.items()},
        "output_shape": list(output_shape) if output_shape is not None else None,
        "output_elements": output_elements,
        "output_bytes": 8 * output_elements if output_elements is not None else None,
        "shape_rule": "EXACT_SCALAR_DAG_UNIT_STEP_SLICE_SHAPES_NO_BROADCAST",
        "shape_authority": "CALLER_DECLARED_INPUT_SHAPES_WITH_EXACT_DAG_SLICE_RULES",
        "complete": not shape_issues and output_shape is not None,
    }
    return {
        "schema": "scar.resource-model-skeleton", "schema_version": 1,
        "status": "PARTIAL_MODEL", "placement_optimization": "FIXED_INPUT_PLACEMENTS_NOT_JOINT",
        "schedule_sha256": schedule_hash, "task_costs": {}, "task_placements": placements,
        "resource_capacities": capacities, "memory_capacities": memory_caps,
        "materialization_sizes": sizes, "memory_locations": locations,
        "model_instantiation": instantiation, "unresolved": unresolved,
        "provenance": {"input_shapes": instantiation["input_shapes"],
                       "output_shape": instantiation["output_shape"],
                       "shape_authority": instantiation["shape_authority"],
                       "plan_sha256": instantiation["plan_sha256"],
                       "schedule_sha256": schedule_hash},
        "resource_evidence": {
            "target_path": binding.target_path if binding else None,
            "target_sha256": binding.target_sha256 if binding else None,
            "executor_id": binding.executor_id if binding else None,
            "cpu_ids": list(binding.cpu_ids) if binding else [],
            "cpu_capacity_basis": "BOUND_CPU_IDS_COUNT_ONLY",
            "memory_policy": "UNBOUND", "memory_pool_scope": "HOST_PROCESS_INCREMENTAL_ALLOCATIONS",
            "numa_residency_proven": False, "costs_inferred": False,
        },
    }


def _problem(schedule, task_costs, task_placements, resource_capacities,
             memory_capacities, materialization_sizes, memory_locations):
    unresolved = []

    def missing(field, reason):
        unresolved.append({"field": field, "reason": reason})

    def mapping(value, field):
        if not isinstance(value, Mapping):
            missing(field, "explicit mapping required")
            return {}
        return value

    costs = mapping(task_costs, "task_costs")
    placements = mapping(task_placements, "task_placements")
    capacities = mapping(resource_capacities, "resource_capacities")
    memory_caps = {} if memory_capacities is None else mapping(memory_capacities, "memory_capacities")
    sizes = {} if materialization_sizes is None else mapping(materialization_sizes, "materialization_sizes")
    locations = {} if memory_locations is None else mapping(memory_locations, "memory_locations")
    for resource, capacity in capacities.items():
        if not isinstance(resource, str) or not resource or not _integer(capacity, 1):
            missing(f"resource_capacities.{resource}", "resource names and positive integer capacities required")
    for pool, budget in memory_caps.items():
        if not isinstance(pool, str) or not pool or not _integer(budget):
            missing(f"memory_capacities.{pool}", "pool names and nonnegative incremental budgets required")
    durations, demands = {}, {}
    for task in schedule.tasks:
        raw = costs.get(task.id)
        duration = raw.get("duration_ticks") if isinstance(raw, Mapping) else raw
        if isinstance(raw, Mapping) and raw.get("status") in ("UNKNOWN", "UNRESOLVED"):
            missing(f"task_costs.{task.id}.status", "declared cost remains unknown")
        if not _integer(duration):
            missing(f"task_costs.{task.id}.duration_ticks", "nonnegative integer ticks required; unknown is not zero")
        else:
            durations[task.id] = duration
        raw = placements.get(task.id)
        if isinstance(raw, (list, tuple)) and all(isinstance(r, str) and r for r in raw):
            if len(set(raw)) != len(raw):
                missing(f"task_placements.{task.id}", "resource IDs must be unique")
                continue
            raw = {r: 1 for r in raw}
        if not isinstance(raw, Mapping):
            missing(f"task_placements.{task.id}", "explicit resource demands required; use {} for control-only tasks")
            continue
        demands[task.id] = {}
        for resource, units in raw.items():
            if not isinstance(resource, str) or not resource or not _integer(units, 1):
                missing(f"task_placements.{task.id}.{resource}", "nonempty resource ID and positive integer demand required")
                continue
            capacity = capacities.get(resource)
            if not _integer(capacity, 1):
                missing(f"resource_capacities.{resource}", "explicit positive integer capacity required")
            demands[task.id][resource] = units
    allocations = {m.id: m for m in schedule.materializations
                   if m.ownership == "SCHEDULE" and m.allocated_by is not None}
    allocation_model = {}
    for key, material in allocations.items():
        size, location = sizes.get(key), locations.get(key)
        if not _integer(size):
            missing(f"materialization_sizes.{key}", "explicit nonnegative byte size required; symbolic bytes need instantiation")
        if not isinstance(location, str) or not location:
            missing(f"memory_locations.{key}", "explicit budget pool required; UNBOUND is not a NUMA placement")
        elif not _integer(memory_caps.get(location)):
            missing(f"memory_capacities.{location}", "explicit incremental byte budget required; total capacity is not free budget")
        if _integer(size) and isinstance(location, str) and location and _integer(memory_caps.get(location)):
            allocation_model[key] = (location, size)
    return durations, demands, dict(capacities), dict(memory_caps), allocation_model, unresolved


def solve_resource_schedule(schedule: ResourceSchedule, *, task_costs=None,
                            task_placements=None, resource_capacities=None,
                            memory_capacities=None, materialization_sizes=None,
                            memory_locations=None, model_instantiation=None,
                            search_budget=100000) -> dict:
    """Minimize makespan in a declared task/resource/allocation model.

    task_costs maps task IDs to nonnegative integer durations (or records with
    duration_ticks). task_placements maps IDs to resource->units records, or
    lists of exclusive resource names. Every task needs both fields, including
    explicit zero-duration/control-only tasks. Each owned allocation also needs
    instantiated bytes, a memory pool, and that pool's incremental byte budget.

    Search enumerates eligible task starts and advances to completion events.
    For constant, nonpreemptive durations/resources and allocation lifetimes,
    a feasible schedule can be left-shifted to these events without increasing
    makespan. Memoization merges identical running/completed/live-storage
    states; critical-path and resource-work lower bounds prune worse branches.
    """
    validate_schedule(schedule)
    if not _integer(search_budget, 1):
        raise ValueError("search_budget must be a positive integer state budget")
    durations, demands, capacities, memory_caps, allocation_model, unresolved = _problem(
        schedule, task_costs, task_placements, resource_capacities,
        memory_capacities, materialization_sizes, memory_locations)
    if model_instantiation is not None:
        if not isinstance(model_instantiation, Mapping):
            unresolved.append({"field": "model_instantiation", "reason": "explicit shape/source receipt must be a mapping"})
        else:
            try:
                semantic_sha256(dict(model_instantiation))
            except (TypeError, ValueError):
                unresolved.append({"field": "model_instantiation", "reason": "receipt must be finite semantic JSON"})
    result = {
        "schema": "scar.resource-solver", "schema_version": 1,
        "region_id": schedule.region_id, "objective": "MINIMIZE_MAKESPAN",
        "placement_optimization": "FIXED_INPUT_PLACEMENTS_NOT_JOINT",
        "schedule_sha256": semantic_sha256(schedule_document(schedule)), "model_sha256": None,
        "time_unit": "CALLER_DECLARED_TICKS", "status": "UNRESOLVED",
        "optimality": "NOT_ESTABLISHED", "physical_optimality_proven": False,
        "model_assumptions": list(_MODEL_ASSUMPTIONS),
        "unresolved": unresolved, "execution_unresolved": list(schedule.unresolved),
        "source_schedule_executable": schedule.executable, "target_program_executed": False,
        "solution": None, "lower_bound_ticks": None, "gap_ticks": None,
        "relative_gap": None, "states_explored": 0, "search_budget": search_budget,
    }
    if unresolved:
        return result
    result["model"] = {"task_durations_ticks": durations, "resource_demands": demands,
                       "resource_capacities": capacities, "memory_capacities": memory_caps,
                       "allocation_bytes_and_pools": {key: {"memory_pool": pool, "bytes": size}
                                                      for key, (pool, size) in allocation_model.items()}}
    if model_instantiation is not None:
        result["model"]["instantiation"] = deepcopy(dict(model_instantiation))
    result["model_sha256"] = semantic_sha256(result["model"])
    tasks = {task.id: task for task in schedule.tasks}
    order = validate_schedule(schedule)["topological_order"]
    ids = tuple(sorted(tasks))
    dependencies = {key: set(tasks[key].depends_on) for key in ids}
    allocation_writes = {key: tuple(m for m in tasks[key].writes if m in allocation_model)
                         if tasks[key].kind is TaskKind.ALLOCATION else () for key in ids}
    release_reads = {key: tasks[key].reads if tasks[key].kind is TaskKind.RELEASE else () for key in ids}

    def lower_bound(time, completed, running):
        remaining_finish = {}
        for key in order:
            if key in completed:
                remaining_finish[key] = 0
            elif key in running:
                remaining_finish[key] = running[key] - time
            else:
                remaining_finish[key] = durations[key] + max(
                    (remaining_finish[d] for d in dependencies[key]), default=0)
        bound = max(remaining_finish.values(), default=0)
        remaining_work = {}
        for key in ids:
            if key in completed:
                continue
            duration = running[key] - time if key in running else durations[key]
            for resource, units in demands[key].items():
                remaining_work[resource] = remaining_work.get(resource, 0) + duration * units
        for resource, work in remaining_work.items():
            bound = max(bound, (work + capacities[resource] - 1) // capacities[resource])
        return time + bound

    initial_lower_bound = lower_bound(0, frozenset(), {})
    result["lower_bound_ticks"] = initial_lower_bound
    violations = []
    for key in ids:
        for resource, units in demands[key].items():
            if units > capacities[resource]:
                violations.append({"field": f"task_placements.{key}.{resource}",
                                   "reason": "task demand exceeds fixed capacity"})
    for key, (location, size) in allocation_model.items():
        if size > memory_caps[location]:
            violations.append({"field": f"materialization_sizes.{key}",
                               "reason": "allocation exceeds explicit pool budget"})
    if violations:
        result.update(status="INFEASIBLE_WITHIN_MODEL", optimality="INFEASIBILITY_ESTABLISHED",
                      constraint_violations=violations)
        return result

    best_time, best_starts = None, None
    explored, exhausted = 0, False
    visited = set()

    frontier = [(0, frozenset(), {}, frozenset(), {})]
    while frontier:
        if explored >= search_budget:
            exhausted = True
            break
        time, completed, running, live, starts = frontier.pop()
        signature = (time, tuple(sorted(completed)), tuple(sorted(running.items())), tuple(sorted(live)))
        if signature in visited:
            continue
        visited.add(signature)
        explored += 1
        bound = lower_bound(time, completed, running)
        if best_time is not None and bound >= best_time:
            continue
        if len(completed) == len(tasks):
            best_time, best_starts = time, dict(starts)
            if best_time == initial_lower_bound:
                break  # Matching global lower/upper bounds already prove model optimality.
            continue
        used_resources = {}
        for key in running:
            for resource, units in demands[key].items():
                used_resources[resource] = used_resources.get(resource, 0) + units
        used_memory = {}
        for material in live:
            location, size = allocation_model[material]
            used_memory[location] = used_memory.get(location, 0) + size
        successors = []
        for key in ids:
            if key in completed or key in running or not dependencies[key].issubset(completed):
                continue
            if any(used_resources.get(r, 0) + units > capacities[r] for r, units in demands[key].items()):
                continue
            extra = {}
            for material in allocation_writes[key]:
                location, size = allocation_model[material]
                extra[location] = extra.get(location, 0) + size
            if any(used_memory.get(pool, 0) + size > memory_caps[pool] for pool, size in extra.items()):
                continue
            next_live = live | set(allocation_writes[key])
            next_starts = {**starts, key: time}
            if durations[key] == 0:
                next_live -= set(release_reads[key])
                successors.append((time, completed | {key}, running, next_live, next_starts))
            else:
                successors.append((time, completed, {**running, key: time + durations[key]}, next_live, next_starts))
        # Deliberate idling is necessary for exact search. A ready allocation or
        # executor task may otherwise block a shorter critical chain later.
        if running:
            next_time = min(running.values())
            finishing = {key for key, end in running.items() if end == next_time}
            next_live = set(live)
            for key in finishing:
                next_live -= set(release_reads[key])
            successors.append((next_time, completed | finishing,
                               {key: end for key, end in running.items() if key not in finishing},
                               next_live, starts))
        frontier.extend(reversed(successors))
    result.update(states_explored=explored,
                  search_budget_exhausted=exhausted,
                  status="SEARCH_BUDGET_EXHAUSTED" if exhausted else
                         "OPTIMAL_WITHIN_MODEL" if best_time is not None else "INFEASIBLE_WITHIN_MODEL",
                  optimality="NOT_ESTABLISHED" if exhausted else
                             "MODEL_OPTIMUM_ESTABLISHED" if best_time is not None else "INFEASIBILITY_ESTABLISHED")
    if best_time is None:
        return result
    if not exhausted:
        result["lower_bound_ticks"] = best_time
    timed = [{"task": key, "kind": tasks[key].kind.value, "start_ticks": best_starts[key],
              "end_ticks": best_starts[key] + durations[key], "resources": demands[key]}
             for key in sorted(ids, key=lambda key: (best_starts[key], key))]
    release_task = {material: key for key in ids for material in release_reads[key]}
    lifetimes = []
    for material, (pool, size) in allocation_model.items():
        allocation = next(m.allocated_by for m in schedule.materializations if m.id == material)
        release = release_task.get(material)
        lifetimes.append({"materialization": material, "memory_pool": pool, "bytes": size,
                          "start_ticks": best_starts[allocation],
                          "end_ticks": best_starts[release] + durations[release] if release else best_time,
                          "retained_through_makespan": release is None})
    gap = best_time - result["lower_bound_ticks"]
    result.update(solution={"makespan_ticks": best_time, "tasks": timed,
                            "allocation_lifetimes": lifetimes}, gap_ticks=gap,
                  relative_gap=gap / best_time if best_time else 0.0)
    return result


__all__ = ["solve_resource_schedule", "hardware_model_skeleton", "semantic_sha256"]
