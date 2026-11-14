"""CPU proposals consume retained topology, not machine-count heuristics."""

from dataclasses import replace
import json

import pytest

from scar.analysis.target_graph import build_target_graph
from scar.compiler.model import ArrayRegion, Expr, SourceRef
from scar.compiler.validation import validate_plan
from scar.optimization import (bind_cpu_placement, optimize_region,
                               propose_cpu_placements, validate_cpu_placement)
from scar.optimization.schedule import (
    CopyLink, LogicalValue, Materialization, ResourceSchedule, Task, TaskKind,
    build_region_schedule, connect_materialization, schedule_document,
    schedule_from_dict, validate_schedule,
)


@pytest.fixture
def hardware(tmp_path, monkeypatch):
    monkeypatch.setattr("os.sched_getaffinity", lambda pid: set(range(8)))
    inventory = {
        "schema": "scar.target-inventory", "schema_version": 1, "sources": [],
        "diagnostics": [], "dram": {"memory_total_bytes": 2 * 2**20},
        "cpu": {"processors": [{"cpu_id": i, "package_id": i // 4, "core_id": i % 4}
                                for i in range(8)],
                "online_cpu_ids": list(range(8)), "model_names": ["fixture CPU"],
                "numa_nodes": [{"node_id": n, "cpu_ids": list(range(n * 4, n * 4 + 4)),
                                "memory_total_bytes": 2**20} for n in range(2)]},
        "gpus": [], "paths": [],
        "storage": {"disks": [{"kname": "fixture", "size_bytes": 2**20,
                               "transport": "fixture", "media_kind": "unknown"}],
                    "block_devices": []},
    }
    source = tmp_path / "inventory.json"
    source.write_text(json.dumps(inventory))
    target = tmp_path / "target"
    build_target_graph(target, inventory=source)
    return target


def plan():
    source = SourceRef("/tmp/placement.py", "0" * 64, "f", 1, 0, "f:v1")
    region = ArrayRegion("r", source, ("x",), (
        Expr("x", "input", attrs={"name": "x"}),
        Expr("a", "add", ("x", "x")), Expr("b", "mul", ("a", "x"))), "b")
    return optimize_region(region)


def test_retained_numa_access_and_affinity_define_unranked_candidates(hardware):
    original = plan()
    candidates = propose_cpu_placements(original, hardware, affinity=(0, 1, 2, 4),
                                        max_threads=3, memory_budget_bytes=128)
    assert [(c.numa_node, c.cpu_ids) for c in candidates] == [
        (0, (0,)), (0, (0, 1)), (0, (0, 1, 2)), (1, (4,))]
    assert all(c.memory_policy == "UNBOUND" and c.memory_budget_bytes == 128 for c in candidates)
    assert all(c.memory_domain_id.endswith("numa" + str(c.numa_node)) for c in candidates)
    evidence = {e["kind"]: e for e in candidates[1].evidence}
    assert evidence["memory_access"]["record"]["locality"] == "local"
    assert evidence["cpu_executor"]["table_receipt"]["sha256"]
    assert evidence["unsupported_boundaries"]["resource_ids"] == ["target_resource:storage/fixture"]

    bound = bind_cpu_placement(original, candidates[1])
    validate_plan(bound)
    assert bound.schema_version == 2 and bound.cpu_threads == 2
    assert bound.cost["memory_budget_bytes"] == 128 and bound.cost["status"] == "ESTIMATED"
    assert bound.proof["selected"] is False
    assert "CPU_IDS_WITHIN_CURRENT_PROCESS_AFFINITY" in bound.proof["runtime_guards"]
    assert bound.region is original.region
    assert validate_cpu_placement(candidates[1])["physical_memory_placement_proven"] is False
    assert original.resource_binding is None and original.cpu_threads == 1


def test_unknown_budget_stays_unknown_and_missing_materials_never_create_binding(hardware):
    candidates = propose_cpu_placements(plan(), hardware, max_threads=1)
    assert all(c.memory_budget_bytes is None for c in candidates)
    assert propose_cpu_placements(plan(), None) == ()
    assert propose_cpu_placements(plan(), hardware, memory_budget_bytes=7) == ()
    with pytest.raises(ValueError, match="snapshot receipt"):
        validate_cpu_placement(replace(candidates[0], target_sha256="0" * 64))
    with pytest.raises(ValueError, match="evidence"):
        validate_cpu_placement(replace(candidates[0], evidence=()))


def test_cpu_schedule_separates_storage_readiness_and_retains_escape(hardware):
    original = plan()
    binding = propose_cpu_placements(original, hardware, max_threads=2, memory_budget_bytes=128)[1]
    bound = bind_cpu_placement(original, binding)
    schedule = build_region_schedule(bound, hardware)
    restored = schedule_from_dict(json.loads(json.dumps(schedule_document(schedule))))
    assert restored == schedule and restored.executable
    assert [task.kind for task in schedule.tasks] == [TaskKind.ALLOCATION, TaskKind.COMPUTE, TaskKind.EXPORT]
    output = schedule.materializations[-1]
    assert output.allocated_by == "allocate:output" and output.ready_task == "compute:region"
    assert output.location == "host-address-space:$CALL_PROCESS"
    assert output.bytes_expr == "8 * output_elements"
    assert schedule.values[0].attrs["identity"].startswith("$CALL_INSTANCE:")
    assert schedule.proof["numa_residency_proven"] is False
    assert schedule.loop_axes == bound.schedule
    with pytest.raises(ValueError, match="readiness"):
        validate_schedule(replace(schedule, tasks=schedule.tasks[:2] +
                                  (replace(schedule.tasks[-1], depends_on=("allocate:output",)),)))
    free = Task("free", TaskKind.RELEASE, (output.id,), depends_on=("export:output",))
    with pytest.raises(ValueError, match="escaping output"):
        validate_schedule(replace(schedule, tasks=schedule.tasks + (free,)))


def test_copy_helper_requires_transport_evidence_and_never_enables_future_backend():
    value = LogicalValue("v")
    source = Materialization("source", "v", "host", external_ready=True, ownership="EXTERNAL")
    destination = Materialization("destination", "v", "device", bytes_expr="v.nbytes")
    assert connect_materialization(value, source, replace(destination, location="host"), ()).materialization is source
    allocated_only = replace(source, external_ready=False, ownership="SCHEDULE", allocated_by="allocation")
    unready = connect_materialization(value, allocated_only, replace(destination, location="host"), ())
    assert not unready.executable and unready.unresolved[0]["reason"] == "SOURCE_VALUE_NOT_READY"
    missing = connect_materialization(value, source, destination, ())
    assert not missing.tasks and missing.unresolved
    declaration = {"value_preserving": True, "evidence": [{"receipt": "explicit-copy-contract"}]}
    link = CopyLink("route", "host", "device", ({"receipt": "explicit-link"},), declaration)
    proposed = connect_materialization(value, source, destination, (link,))
    assert [task.kind for task in proposed.tasks] == [TaskKind.ALLOCATION, TaskKind.COPY]
    assert proposed.materialization.ready_task == proposed.tasks[1].id
    assert proposed.tasks[1].attrs["cost"]["status"] == "UNKNOWN"
    assert proposed.unresolved and not proposed.executable
    schedule = ResourceSchedule("copy", (value,), (source, proposed.materialization),
                                proposed.tasks, unresolved=proposed.unresolved)
    validate_schedule(schedule)
    with pytest.raises(ValueError, match="unresolved"):
        validate_schedule(replace(schedule, executable=True))
