"""One exact model, its dependency lowering, and incompatible constraints."""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from scar.analysis.target_graph import build_target_graph
from scar.codegen.timed import admit_timed_plan
from scar.compiler.model import ArrayRegion, Expr, SourceRef
from scar.optimization import bind_cpu_placement, optimize_region, propose_cpu_placements
from scar.optimization.resource_solver import (
    hardware_model_skeleton, semantic_sha256, solve_resource_schedule,
)
from scar.optimization.schedule import build_region_schedule, Task, TaskKind


def test_fixed_cpu_timed_admission_checks_receipts_resources_and_lifetimes(tmp_path, monkeypatch):
    monkeypatch.setattr("os.sched_getaffinity", lambda _: {0}, raising=False)
    inventory = {
        "schema": "scar.target-inventory", "schema_version": 1,
        "sources": [], "diagnostics": [], "dram": {"memory_total_bytes": 1024},
        "cpu": {"processors": [{"cpu_id": 0, "package_id": 0, "core_id": 0}],
                "online_cpu_ids": [0], "model_names": ["fixture CPU"],
                "numa_nodes": [{"node_id": 0, "cpu_ids": [0], "memory_total_bytes": 1024}]},
        "gpus": [], "paths": [], "storage": {"disks": [], "block_devices": []},
    }
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(json.dumps(inventory))
    target = tmp_path / "target"
    build_target_graph(target, inventory=inventory_path)
    region = ArrayRegion("timed-region", SourceRef(str(tmp_path / "f.py"), "0" * 64,
                                                  "f", 1, 0, "f:v1"), ("x",), (
        Expr("x", "input", attrs={"name": "x"}),
        Expr("view", "slice", ("x",), {"bounds": [[1, -1], [None, -1]]}),
        Expr("a", "add", ("view", "view")), Expr("b", "mul", ("a", "view")),
    ), "b")
    initial = optimize_region(region, memory_budget_bytes=128)
    binding = propose_cpu_placements(initial, target, max_threads=1)[0]
    plan = bind_cpu_placement(initial, binding)
    schedule = build_region_schedule(plan, target)
    skeleton = hardware_model_skeleton(plan, schedule, input_shapes={"x": [4, 4]})
    # Explicit caller-declared model inputs. No task kind supplies a duration.
    result = solve_resource_schedule(schedule,
        task_costs={"allocate:output": 3, "compute:region": 11, "export:output": 2},
        **{key: skeleton[key] for key in (
            "task_placements", "resource_capacities", "memory_capacities",
            "materialization_sizes", "memory_locations", "model_instantiation")})
    assert result["status"] == "OPTIMAL_WITHIN_MODEL"
    admitted = admit_timed_plan(plan, schedule, result)
    assert admitted["dependency_order"] == ["allocate:output", "compute:region", "export:output"]
    assert admitted["model_makespan_ticks"] == 16
    assert admitted["must_guard"]["input_shapes"] == {"x": [4, 4]}
    assert admitted["must_guard"]["output_shape"] == [2, 3]
    assert admitted["must_guard"]["output_nbytes"] == 48
    assert admitted["lowering"][1]["resources"] == {binding.executor_id: 1}
    assert not admitted["execution_linked"] and not admitted["deployment_authorized"]
    assert not admitted["physical_optimality_proven"] and admitted["memory_policy"] == "UNBOUND"

    changed = deepcopy(result)
    changed["schedule_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="schedule receipt"):
        admit_timed_plan(plan, schedule, changed)
    changed = deepcopy(result)
    changed["physical_optimality_proven"] = True
    with pytest.raises(ValueError, match="physical"):
        admit_timed_plan(plan, schedule, changed)
    changed = deepcopy(result)
    changed["deadline_ticks"] = 5
    with pytest.raises(ValueError, match="additional solver constraints"):
        admit_timed_plan(plan, schedule, changed)
    changed = deepcopy(result)
    del changed["model"]["instantiation"]
    changed["model_sha256"] = semantic_sha256(changed["model"])
    with pytest.raises(ValueError, match="shape instantiation"):
        admit_timed_plan(plan, schedule, changed)
    changed = deepcopy(result)
    changed["model"]["instantiation"]["output_shape"] = [4, 4]
    changed["model_sha256"] = semantic_sha256(changed["model"])
    with pytest.raises(ValueError, match="shape/source receipt"):
        admit_timed_plan(plan, schedule, changed)
    changed = deepcopy(result)
    changed["model"]["resource_demands"]["compute:region"] = {"unimplemented-gpu": 1}
    changed["model"]["resource_capacities"]["unimplemented-gpu"] = 1
    changed["model_sha256"] = semantic_sha256(changed["model"])
    with pytest.raises(ValueError, match="resource_demands"):
        admit_timed_plan(plan, schedule, changed)
    changed = deepcopy(result)
    task = next(row for row in changed["solution"]["tasks"] if row["task"] == "compute:region")
    task.update(start_ticks=0, end_ticks=11)
    with pytest.raises(ValueError, match="dependency"):
        admit_timed_plan(plan, schedule, changed)
    changed = deepcopy(result)
    changed["solution"]["allocation_lifetimes"][0]["end_ticks"] = 0
    with pytest.raises(ValueError, match="allocation lifetime"):
        admit_timed_plan(plan, schedule, changed)
    waiting = Task("unsupported-wait", TaskKind.WAIT, depends_on=("compute:region",))
    with pytest.raises(ValueError, match="COPY/WAIT"):
        admit_timed_plan(plan, replace(schedule, tasks=(*schedule.tasks, waiting)), result)
