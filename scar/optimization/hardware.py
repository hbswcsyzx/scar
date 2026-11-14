"""Unranked CPU placement proposals from retained, typed hardware materials.

CPU masks constrain execution only. Naming a reachable host-memory domain does
not bind NUMA pages. Inventory capacity and declared allocation budgets remain
separate, and no bandwidth or runtime benefit is inferred from the topology.
"""

from dataclasses import replace
from hashlib import sha256
import os
from pathlib import Path

from scar.analysis.target_graph import TargetHardwareGraph, _resources
from scar.compiler.model import CpuPlacement, ExecutionPlan
from scar.compiler.validation import validate_plan, validate_resource_binding
from scar.ir.program import target_hardware as H
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import encode


def _artifact(path, schema):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return ProviderArtifact(str(path), sha256(raw).hexdigest(), len(raw), schema)


def _target_materials(target):
    path = target.path if isinstance(target, TargetHardwareGraph) else target
    snapshot = _artifact(Path(path) / "result.json", "scar.target-hardware-graph")
    graph = TargetHardwareGraph(path)
    resources, connections, paths = graph.resources(), graph.connections(), graph.paths()
    inventory = _artifact(graph.report["inventory"]["uri"], "scar.target-inventory")
    for source in graph.inventory["sources"]:
        text = source.get("text")
        if text is not None and sha256(text.encode()).hexdigest() != source["sha256"]:
            raise ValueError("retained target source receipt differs")
    # Reconstruct only compact descriptions from retained JSON. No hardware
    # probing, graph writing, source-program loading, or workload execution.
    expected_resources, expected_connections, expected_paths = _resources(graph.inventory, inventory)
    if (len({r.id for r in resources}) != len(resources)
            or {r.id: r for r in resources} != {r.id: r for r in expected_resources}
            or connections != tuple(expected_connections) or paths != tuple(expected_paths)):
        raise ValueError("target resources/topology differ from retained inventory")
    if snapshot != _artifact(graph.path / "result.json", snapshot.schema):
        raise ValueError("target snapshot changed while reading")
    return graph, snapshot, resources, connections


def _budget(value, label):
    if value is not None and (type(value) is not int or value < 0):
        raise ValueError(f"{label} must be a nonnegative integer or None")
    return value


def _effective_budget(*values):
    values = [value for value in values if value is not None]
    return min(values) if values else None


def _affinity(affinity):
    current = (set(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None)
    if affinity is None:
        if current is None:
            raise ValueError("CPU affinity is unavailable; an explicit CPU-ID mask is required")
        return tuple(sorted(current)), "process_affinity"
    try:
        requested = tuple(affinity)
    except TypeError as error:
        raise ValueError("affinity must contain nonnegative integer CPU IDs") from error
    if any(type(cpu) is not int or cpu < 0 for cpu in requested):
        raise ValueError("affinity must contain nonnegative integer CPU IDs")
    mask = set(requested)
    if current is not None:
        mask &= current
    return tuple(sorted(mask)), ("process_affinity_and_requested_mask" if current is not None
                                 else "caller_supplied_affinity")


def _thread_counts(limit):
    result, count = [], 1
    while count <= limit:
        result.append(count)
        count *= 2
    if limit and limit not in result:
        result.append(limit)
    return result


def _record_evidence(graph, snapshot, row, ordinal):
    family = type(row).__name__
    return {"kind": "cpu_executor" if isinstance(row, H.CpuExecutor) else "memory_domain",
            "target": encode(H.TargetResourceRef(snapshot, row.id)),
            "table_locator": "#/nodes/" + family,
            "table_receipt": dict(graph.report["nodes"][family]),
            "record_index": ordinal,
            "record": encode(row, record_tags=H.TARGET_RECORD_TAGS)}


def _connection_evidence(graph, snapshot, connection, ordinal):
    return {"kind": "memory_access", "snapshot": encode(snapshot),
            "table_locator": "#/connections",
            "table_receipt": dict(graph.report["connections"]),
            "record_index": ordinal, "record": encode(connection)}


def _indexed_resources(resources):
    counts, result = {}, {}
    for row in resources:
        family = type(row).__name__
        ordinal = counts.get(family, 0)
        counts[family] = ordinal + 1
        result[str(row.id)] = (row, ordinal)
    return result


def _accesses(executor, memory, connection):
    return (connection.kind is H.ConnectionKind.MEMORY_ACCESS
            and ((connection.source == executor.id and connection.target == memory.id)
                 or (connection.bidirectional and connection.target == executor.id
                     and connection.source == memory.id)))


def _boundaries(resources, connections):
    return {"kind": "unsupported_boundaries",
            "resource_ids": sorted(str(r.id) for r in resources
                                   if not isinstance(r, H.CpuExecutor)
                                   and not (isinstance(r, H.MemoryDomain)
                                            and r.kind is H.MemoryKind.HOST)),
            "connection_kinds": sorted({c.kind.value for c in connections
                                        if c.kind is not H.ConnectionKind.MEMORY_ACCESS}),
            "scope": "Accelerators, device memory and storage are retained boundaries; "
                     "no GPU execution, transfer or storage scheduling is proposed."}


def propose_cpu_placements(plan, target, *, affinity=None, memory_budget_bytes=None,
                           max_threads=None) -> tuple[CpuPlacement, ...]:
    """Enumerate deterministic executor/host-memory/CPU-mask candidates.

    Each CPU set is an executor's original CPU IDs intersected with the current
    process affinity and optional requested mask. Thread counts include one,
    powers of two, and the cap. Ordering is deterministic and is not a ranking.
    Unknown available memory remains unknown; explicit budgets become output
    allocation guards. Reported physical capacity is never used as a budget.
    """
    _budget(memory_budget_bytes, "memory_budget_bytes")
    if max_threads is not None and (type(max_threads) is not int or max_threads < 1):
        raise ValueError("max_threads must be a positive integer or None")
    if not isinstance(plan, ExecutionPlan):
        raise ValueError("ExecutionPlan required")
    if target is None:
        return ()
    if (plan.proof.get("supported") is not True or plan.proof.get("legal") is not True
            or plan.proof.get("lowering_eligible") is not True):
        return ()
    validate_plan(plan)
    plan_budget = _budget(plan.cost.get("memory_budget_bytes"), "plan memory budget")
    allowed, affinity_origin = _affinity(affinity)
    graph, snapshot, resources, connections = _target_materials(target)
    indexed = _indexed_resources(resources)
    executors = sorted((r for r in resources if isinstance(r, H.CpuExecutor)), key=lambda r: str(r.id))
    memories = sorted((r for r in resources if isinstance(r, H.MemoryDomain)
                       and r.kind is H.MemoryKind.HOST), key=lambda r: str(r.id))
    boundary = _boundaries(resources, connections)
    proposals = []
    for executor in executors:
        cpus = sorted(set(executor.cpu_ids) & set(allowed))
        limit = min(len(cpus), max_threads) if max_threads is not None else len(cpus)
        if not limit:
            continue
        # UNBOUND memory produces the same CPU implementation for each domain.
        # Keep one reachable declaration, preferring explicitly local topology,
        # rather than benchmarking duplicate CPU masks as separate executions.
        executor_memories = sorted(memories, key=lambda memory: (
            not any(_accesses(executor, memory, c) and c.locality == "local"
                    for c in connections), str(memory.id)))
        for memory in executor_memories:
            domain_budget = _budget(memory.budget_bytes, "reported domain budget")
            budget = _effective_budget(memory_budget_bytes, plan_budget, domain_budget)
            if budget is not None and budget < 8:
                continue
            links = [(i, c) for i, c in enumerate(connections) if _accesses(executor, memory, c)]
            if not links:
                continue
            # Multiple original access declarations remain explicit evidence;
            # they do not multiply an otherwise identical placement proposal.
            evidence = (
                {"kind": "target_snapshot", "artifact": encode(snapshot)},
                _record_evidence(graph, snapshot, executor, indexed[str(executor.id)][1]),
                _record_evidence(graph, snapshot, memory, indexed[str(memory.id)][1]),
                *(_connection_evidence(graph, snapshot, c, i) for i, c in links),
                {"kind": "planning_constraints", "affinity_cpu_ids": list(allowed),
                 "affinity_origin": affinity_origin, "max_threads": max_threads,
                 "caller_memory_budget_bytes": memory_budget_bytes,
                 "plan_memory_budget_bytes": plan_budget,
                 "reported_domain_budget_bytes": domain_budget,
                 "reported_capacity_bytes": memory.capacity_bytes,
                 "available_budget_established": domain_budget is not None,
                 "selection": "UNRANKED_UNMEASURED",
                 "memory_policy": "UNBOUND",
                 "runtime_guards": ["CPU_IDS_WITHIN_CURRENT_PROCESS_AFFINITY",
                                    "ORIGINAL_TARGET_SNAPSHOT_MATCHES",
                                    "TARGET_MEMORY_ACCESS_CONDITIONS_HOLD",
                                    "ALLOCATION_SUCCEEDS_WITHIN_DECLARED_BUDGET"],
                 "scope": "CPU pinning does not establish NUMA page placement or residency; "
                          "capacity is not an available budget, and topology is not measured bandwidth."},
                boundary,
            )
            for count in _thread_counts(limit):
                proposals.append(CpuPlacement(str(graph.path), snapshot.sha256, str(executor.id),
                                              tuple(cpus[:count]), str(memory.id), budget,
                                              executor.numa_node, "UNBOUND", evidence))
            break
    return tuple(proposals)


def validate_cpu_placement(binding) -> dict:
    """Check structure and retained receipts, without asserting live availability.

    Installation must separately check that all requested CPUs remain in the
    current process affinity. This validation performs no affinity changes and
    does not establish physical memory use or a NUMA binding.
    """
    validate_resource_binding(binding)
    graph, snapshot, resources, connections = _target_materials(binding.target_path)
    if snapshot.sha256 != binding.target_sha256:
        raise ValueError("placement target snapshot receipt differs")
    indexed = _indexed_resources(resources)
    cpu_row = indexed.get(binding.executor_id)
    memory_row = indexed.get(binding.memory_domain_id)
    if cpu_row is None or not isinstance(cpu_row[0], H.CpuExecutor):
        raise ValueError("placement executor does not reference an original CPU executor")
    if memory_row is None or not isinstance(memory_row[0], H.MemoryDomain) or memory_row[0].kind is not H.MemoryKind.HOST:
        raise ValueError("placement memory does not reference an original host domain")
    executor, memory = cpu_row[0], memory_row[0]
    if not set(binding.cpu_ids).issubset(executor.cpu_ids) or binding.numa_node != executor.numa_node:
        raise ValueError("placement CPUs or NUMA identity differ from the original executor")
    links = [(i, c) for i, c in enumerate(connections) if _accesses(executor, memory, c)]
    if not links:
        raise ValueError("placement has no original CPU/host MEMORY_ACCESS connection")
    if memory.budget_bytes is not None and (binding.memory_budget_bytes is None
                                           or binding.memory_budget_bytes > memory.budget_bytes):
        raise ValueError("placement exceeds the reported domain budget")
    required = (
        {"kind": "target_snapshot", "artifact": encode(snapshot)},
        _record_evidence(graph, snapshot, executor, cpu_row[1]),
        _record_evidence(graph, snapshot, memory, memory_row[1]),
        *(_connection_evidence(graph, snapshot, c, i) for i, c in links),
    )
    if any(reference not in binding.evidence for reference in required):
        raise ValueError("placement lacks original snapshot/resource/connection evidence")
    return {"target_sha256": snapshot.sha256, "executor_id": binding.executor_id,
            "memory_domain_id": binding.memory_domain_id, "cpu_threads": len(binding.cpu_ids),
            "memory_policy": "UNBOUND", "physical_memory_placement_proven": False,
            "installation_guard": "CPU_IDS_WITHIN_CURRENT_PROCESS_AFFINITY"}


def bind_cpu_placement(plan, binding) -> ExecutionPlan:
    """Attach one caller-chosen, unmeasured proposal without choosing an optimum."""
    validate_plan(plan)
    if plan.proof.get("supported") is not True or plan.proof.get("legal") is not True:
        raise ValueError("a supported, conditionally legal plan is required")
    validation = validate_cpu_placement(binding)
    old_budget = plan.cost.get("memory_budget_bytes")
    if old_budget is not None and (binding.memory_budget_bytes is None
                                   or binding.memory_budget_bytes > old_budget):
        raise ValueError("placement cannot relax the existing output memory budget")
    count = len(binding.cpu_ids)
    cost = {**plan.cost, "status": "ESTIMATED", "cpu_threads": count,
            "memory_budget_bytes": binding.memory_budget_bytes,
            "memory_guard_required": binding.memory_budget_bytes is not None,
            "placement_selection": "CALLER_CHOSEN_UNRANKED_CANDIDATE",
            "measurement": "This exact resource binding requires measured validation; "
                           "no optimum, bandwidth or runtime benefit is inferred."}
    guards = list(plan.proof.get("runtime_guards", ()))
    for guard in ("CPU_IDS_WITHIN_CURRENT_PROCESS_AFFINITY", "ORIGINAL_TARGET_SNAPSHOT_MATCHES",
                  "TARGET_MEMORY_ACCESS_CONDITIONS_HOLD"):
        if guard not in guards:
            guards.append(guard)
    if binding.memory_budget_bytes is not None and "OUTPUT_NBYTES_WITHIN_MEMORY_BUDGET" not in guards:
        guards.append("OUTPUT_NBYTES_WITHIN_MEMORY_BUDGET")
    allocation = {**plan.proof.get("resource_allocation", {}), "status": "PROPOSED",
                  "cpu_threads": count, "cpu_ids": list(binding.cpu_ids),
                  "executor_id": binding.executor_id, "memory_domain_id": binding.memory_domain_id,
                  "memory_budget_bytes": binding.memory_budget_bytes, "memory_policy": "UNBOUND",
                  "target_sha256": binding.target_sha256,
                  "parallel_axis": "row" if count > 1 else None,
                  "partition_policy": "disjoint_output_rows" if count > 1 else "serial",
                  "physical_memory_placement_proven": False}
    proof = {**plan.proof, "selected": False, "runtime_guards": guards,
             "resource_allocation": allocation, "resource_binding_validation": validation}
    result = replace(plan, schema_version=2, resource_binding=binding,
                     cpu_threads=count, cost=cost, proof=proof)
    validate_plan(result)
    return result
