"""Mechanical admission of one fixed-placement, synchronous CPU timed plan.

This module does not run tasks, sleep until predicted ticks, or infer durations.
It proves that a solver result can be lowered to the existing allocation,
compute and export dependencies. The shape/resource guards it returns still
need an execution bridge; admission alone never authorizes deployment.
"""

from __future__ import annotations

import json
import sys

from scar.compiler.model import document
from scar.optimization import resource_solver as solver
from scar.optimization.schedule import (
    TaskKind, schedule_document, schedule_from_dict,
)

from .schedule import admit_schedule


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _same(left, right):
    # Semantic JSON equality keeps booleans distinct from integer capacities.
    return solver.semantic_sha256(left) == solver.semantic_sha256(right)


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def admit_timed_plan(plan, resource_schedule, solver_result) -> dict:
    """Validate a complete solver model against this CPU boundary's actions.

    Only the exact resource schedule accepted by admit_schedule is eligible.
    Its explicit input-shape receipt is mandatory. The solver model must use
    the recorded executor in CPU-worker units, the host process's incremental
    allocation budget, and no unimplemented resource demands. Three dependent
    tasks have an independent makespan lower bound equal to the sum of their
    declared durations; matching that bound proves optimality in this model.
    """
    admitted = admit_schedule(plan, resource_schedule)
    schedule = schedule_from_dict(admitted)
    _require(type(solver_result) is dict, "solver result must be a JSON object")
    try:
        result_digest = solver.semantic_sha256(solver_result)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("solver result must contain finite semantic JSON") from error
    result = solver_result
    _require(result.get("schema") == "scar.resource-solver" and
             type(result.get("schema_version")) is int and result["schema_version"] == 1,
             "unsupported solver result schema")
    result_fields = {
        "schema", "schema_version", "region_id", "objective", "placement_optimization",
        "schedule_sha256", "model_sha256", "time_unit", "status", "optimality",
        "physical_optimality_proven", "model_assumptions", "unresolved", "execution_unresolved",
        "source_schedule_executable", "target_program_executed", "solution", "lower_bound_ticks",
        "gap_ticks", "relative_gap", "states_explored", "search_budget", "model",
        "search_budget_exhausted", "constraint_violations",
    }
    _require(not set(result) - result_fields,
             "additional solver constraints or result fields are not supported")
    _require(result.get("region_id") == plan.region.id, "solver result refers to a different region")
    _require(result.get("status") == "OPTIMAL_WITHIN_MODEL" and
             result.get("optimality") == "MODEL_OPTIMUM_ESTABLISHED",
             "a complete model-optimal solver result is required")
    _require(result.get("physical_optimality_proven") is False,
             "model optimality cannot claim physical hardware optimality")
    _require(result.get("placement_optimization") == "FIXED_INPUT_PLACEMENTS_NOT_JOINT",
             "joint placement or another scheduling model is not implemented")
    _require(result.get("objective") == "MINIMIZE_MAKESPAN" and
             result.get("time_unit") == "CALLER_DECLARED_TICKS",
             "only declared-tick makespan models are supported")
    _require(result.get("unresolved") == [] and result.get("execution_unresolved") == [] and
             result.get("source_schedule_executable") is True,
             "unresolved solver or execution constraints cannot be lowered")
    _require(result.get("target_program_executed") is False and
             result.get("search_budget_exhausted", False) is False and
             result.get("constraint_violations", []) == [],
             "solver result is not an unexecuted, completed feasible model proof")
    _require(_integer(result.get("states_explored"), 1) and
             _integer(result.get("search_budget"), 1) and
             result["states_explored"] <= result["search_budget"],
             "solver search accounting is incomplete or exceeds its state budget")
    _require(_same(result.get("model_assumptions"), solver._MODEL_ASSUMPTIONS),
             "solver model assumptions differ from the supported discrete model")

    schedule_digest = solver.semantic_sha256(schedule_document(schedule))
    _require(result.get("schedule_sha256") == schedule_digest,
             "solver source schedule receipt differs from the admitted schedule")
    model = result.get("model")
    fields = {"task_durations_ticks", "resource_demands", "resource_capacities",
              "memory_capacities", "allocation_bytes_and_pools", "instantiation"}
    _require(type(model) is dict and set(model) == fields,
             "complete supported solver model and shape instantiation are required")
    model_digest = solver.semantic_sha256(model)
    _require(result.get("model_sha256") == model_digest,
             "solver model receipt differs from the declared model")
    instantiation = model["instantiation"]
    _require(type(instantiation) is dict and instantiation.get("complete") is True,
             "a complete source and input/output shape receipt is required")
    input_shapes = instantiation.get("input_shapes")
    _require(type(input_shapes) is dict and set(input_shapes) == set(plan.region.parameters),
             "input-shape receipt must cover every original parameter exactly")
    for shape in input_shapes.values():
        _require(type(shape) is list and len(shape) == 2 and
                 all(_integer(extent) and extent <= sys.maxsize for extent in shape) and
                 shape[0] * shape[1] * 8 <= sys.maxsize,
                 "modeled input shapes must be representable rank-two float64 shapes")

    # This authority derives shapes from the same scalar DAG and original
    # unit-step slice rules. It also establishes the exact CPU-unit and host
    # pool mapping; arbitrary resource strings are not silently discarded.
    skeleton = solver.hardware_model_skeleton(plan, schedule, input_shapes=input_shapes)
    expected_instantiation = skeleton["model_instantiation"]
    _require(expected_instantiation.get("complete") is True and
             _same(instantiation, expected_instantiation),
             "shape/source receipt differs from the exact admitted scalar DAG")
    output_bytes = instantiation["output_bytes"]
    _require(_integer(output_bytes) and output_bytes <= sys.maxsize,
             "modeled output byte size exceeds the host allocation profile")
    tasks = {task.id: task for task in schedule.tasks}
    allocation = next(task for task in schedule.tasks if task.kind is TaskKind.ALLOCATION)
    compute = next(task for task in schedule.tasks if task.kind is TaskKind.COMPUTE)
    export = next(task for task in schedule.tasks if task.kind is TaskKind.EXPORT)
    ordered = (allocation, compute, export)
    durations = model["task_durations_ticks"]
    _require(type(durations) is dict and set(durations) == set(tasks) and
             all(_integer(value) for value in durations.values()),
             "every task needs its own explicit nonnegative integer duration")
    unresolved_cost_fields = {f"task_costs.{task.id}.duration_ticks" for task in ordered}
    _require(all(issue.get("field") in unresolved_cost_fields for issue in skeleton["unresolved"]),
             "resource or memory constraints remain unresolved in the CPU model")
    expected_constraints = {
        "resource_demands": skeleton["task_placements"],
        "resource_capacities": skeleton["resource_capacities"],
        "memory_capacities": skeleton["memory_capacities"],
        "allocation_bytes_and_pools": {
            key: {"memory_pool": skeleton["memory_locations"][key], "bytes": size}
            for key, size in skeleton["materialization_sizes"].items()
        },
    }
    for field, expected in expected_constraints.items():
        _require(_same(model[field], expected),
                 f"{field} differ from the recorded CPU workers or host allocation policy")
    budget = plan.cost.get("memory_budget_bytes")
    _require(_integer(budget, 8) and output_bytes <= budget,
             "modeled output must fit an explicit incremental allocation budget")

    solution = result.get("solution")
    _require(type(solution) is dict and set(solution) ==
             {"makespan_ticks", "tasks", "allocation_lifetimes"},
             "complete task timing and allocation lifetimes are required")
    records = solution["tasks"]
    row_fields = {"task", "kind", "start_ticks", "end_ticks", "resources"}
    _require(type(records) is list and len(records) == len(tasks) and
             all(type(row) is dict and set(row) == row_fields and
                 type(row.get("task")) is str for row in records),
             "timed task records must cover only the supported tasks and fields")
    timed = {row["task"]: row for row in records}
    _require(len(timed) == len(tasks) and set(timed) == set(tasks),
             "timed solution omits or duplicates resource tasks")
    for task in ordered:
        row = timed[task.id]
        _require(row["kind"] == task.kind.value and
                 _integer(row["start_ticks"]) and _integer(row["end_ticks"]) and
                 row["end_ticks"] - row["start_ticks"] == durations[task.id],
                 "timed task kind or duration differs from the authoritative model")
        _require(_same(row["resources"], model["resource_demands"][task.id]),
                 "timed resource demands differ from the authoritative model")
        _require(all(row["start_ticks"] >= timed[dependency]["end_ticks"]
                     for dependency in task.depends_on),
                 "timed task starts before an original dependency completes")

    # In this closed three-task chain no task can overlap or begin before the
    # preceding completion. This is an independent optimum proof, not merely
    # acceptance of a solver status string or a predicted wall-clock duration.
    expected_end = 0
    for task in ordered:
        _require(timed[task.id]["start_ticks"] == expected_end,
                 "three-task model optimum has an unexplained idle interval")
        expected_end += durations[task.id]
    makespan = solution["makespan_ticks"]
    _require(_integer(makespan) and makespan == expected_end and
             _integer(result.get("lower_bound_ticks")) and
             result["lower_bound_ticks"] == makespan and
             type(result.get("gap_ticks")) is int and result["gap_ticks"] == 0 and
             type(result.get("relative_gap")) in (int, float) and result["relative_gap"] == 0,
             "solver makespan, lower bound or optimality gap contradict the complete chain")
    output = allocation.writes[0]
    pool = "host-address-space:$CALL_PROCESS"
    expected_lifetimes = [{"materialization": output, "memory_pool": pool,
                           "bytes": output_bytes, "start_ticks": 0,
                           "end_ticks": makespan, "retained_through_makespan": True}]
    _require(_same(solution["allocation_lifetimes"], expected_lifetimes),
             "output allocation lifetime differs from readiness and caller escape")

    actions = {TaskKind.ALLOCATION: "PYTHON_FRESH_NUMPY_ALLOCATION",
               TaskKind.COMPUTE: "CPP_SYNCHRONOUS_ROW_COMPUTE_AND_JOIN",
               TaskKind.EXPORT: "PYTHON_EXPORT_FRESH_NDARRAY_HANDLE"}
    binding = plan.resource_binding
    admission = {
        "schema": "scar.timed-plan-admission", "schema_version": 1,
        "status": "ADMITTED_FOR_DEPENDENCY_LOWERING",
        "region_id": plan.region.id,
        "plan_sha256": solver.semantic_sha256(document(plan)),
        "schedule_sha256": schedule_digest, "model_sha256": model_digest,
        "solver_result_sha256": result_digest,
        "profile": "SYNCHRONOUS_CPU_ALLOCATION_COMPUTE_EXPORT",
        "execution_linked": False, "deployment_authorized": False,
        "physical_optimality_proven": False,
        "optimality_scope": "FIXED_PLACEMENT_DECLARED_DISCRETE_MODEL_ONLY",
        "cost_authority": "solver_result.model.task_durations_ticks",
        "timing_policy": "DEPENDENCY_ORDER_ONLY_NO_PREDICTED_TICK_SLEEP",
        "dependency_order": [task.id for task in ordered],
        "lowering": [{"task": task.id, "kind": task.kind.value,
                      "depends_on": list(task.depends_on), "action": actions[task.kind],
                      "resources": model["resource_demands"][task.id],
                      "modeled_start_ticks": timed[task.id]["start_ticks"],
                      "modeled_end_ticks": timed[task.id]["end_ticks"]} for task in ordered],
        "model_makespan_ticks": makespan,
        "model_optimum_proof": {"method": "DECLARED_CHAIN_DURATIONS_CRITICAL_PATH",
                                "lower_bound_ticks": makespan, "feasible_makespan_ticks": makespan},
        "resource_constraints": expected_constraints,
        "must_guard": {
            "input_shapes": input_shapes, "output_shape": instantiation["output_shape"],
            "output_nbytes": output_bytes, "memory_budget_bytes": budget,
            "cpu_ids": list(binding.cpu_ids), "executor_id": binding.executor_id,
            "source_version": {"path": plan.region.source.path,
                               "sha256": plan.region.source.sha256,
                               "code_key": plan.region.source.code_key},
            "target_snapshot": {"path": binding.target_path, "sha256": binding.target_sha256},
            "input_contract": "EXACT_NATIVE_FLOAT64_RANK2_NDARRAY_NO_ARRAY_BROADCAST",
            "completion": "NATIVE_SUCCESS_AFTER_WORKER_JOIN_FENV_AND_AFFINITY_RESTORATION",
        },
        "resource_scope": "ONE_INVOCATION_NO_GLOBAL_RESOURCE_RESERVATION_OR_OTHER_WORKLOAD_SCHEDULING",
        "memory_pool": pool, "allocation_lifetimes": expected_lifetimes,
        "output_ownership": "CALLER_AFTER_EXPORT_NO_IMPLICIT_RELEASE",
        "memory_policy": "UNBOUND", "numa_page_binding": False,
        "unimplemented_actions": ["COPY", "WAIT", "RELEASE", "ASYNCHRONOUS_TRANSFER",
                                  "MULTIPLE_COMPUTE_TASKS", "JOINT_PLACEMENT_OPTIMIZATION"],
    }
    return json.loads(json.dumps(admission, allow_nan=False))


__all__ = ["admit_timed_plan"]
