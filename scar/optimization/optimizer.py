"""Conservative proof and resource planning for CPU 2D scalar DAGs."""

from dataclasses import replace
import os

from scar.compiler.model import ArrayRegion, ExecutionPlan, OPS
from .graph import numeric_value, ordered_nodes, simplify, value_kinds


_REQUIRED_ASSUMPTIONS = {
    "EXACT_NUMPY_NDARRAY_FLOAT64_CPU_2D", "FRESH_OUTPUT", "NO_INPUT_WRITES",
}
_ARITHMETIC = {"add", "sub", "mul", "div", "neg"}
_RUNTIME_GUARDS = [
    "EXACT_NUMPY_NDARRAY_FLOAT64_CPU_2D",
    "SUPPORTED_STRIDES_AND_UNIT_STEP_VIEWS",
    "EQUAL_ELEMENTWISE_OPERAND_SHAPES_NO_BROADCAST",
    "NO_INPUT_WRITES_FRESH_OUTPUT_EACH_CALL",
    "FLOAT_STATUS_CLEAR_OR_FALLBACK_TO_ORIGINAL",
    "SINGLE_PYTHON_THREAD",
]
_EXTERNAL_ASSUMPTIONS = ["NO_FOREIGN_CONCURRENT_INPUT_WRITERS", "SYNCHRONOUS_CPU_EXECUTION"]


def _profile_reasons(region, nodes):
    reasons = []
    if not _REQUIRED_ASSUMPTIONS.issubset(region.assumptions):
        reasons.append("missing_guarded_ndarray_profile_assumptions")
    if region.frontiers:
        reasons.append("unresolved_frontiers")
    if (not region.parameters or len(set(region.parameters)) != len(region.parameters)
            or any(not isinstance(p, str) or not p for p in region.parameters)):
        reasons.append("invalid_parameter_bindings")
    by_id = {node.id: node for node in nodes}
    input_parameters = []
    for node in nodes:
        if node.op not in OPS:
            reasons.append(f"unsupported_operator:{node.id}:{node.op}")
            continue
        if not isinstance(node.attrs, dict):
            reasons.append(f"unsupported_attributes:{node.id}")
            continue
        expected = ({"name"} if node.op == "input" else {"value"}
                    if node.op == "const" else {"bounds"}
                    if node.op == "slice" else set())
        accepted_input_attrs = (node.op == "input" and set(node.attrs) in
                                ({"name"}, {"name", "index"}))
        if set(node.attrs) != expected and not accepted_input_attrs:
            reasons.append(f"unsupported_attributes:{node.id}")
            continue
        if node.op == "input":
            name = node.attrs["name"]
            if name not in region.parameters or name in input_parameters:
                reasons.append(f"invalid_input_parameter:{node.id}")
            if "index" in node.attrs and (type(node.attrs["index"]) is not int
                    or name not in region.parameters
                    or node.attrs["index"] != region.parameters.index(name)):
                reasons.append(f"invalid_input_parameter_index:{node.id}")
            input_parameters.append(name)
        elif node.op == "const" and not numeric_value(node.attrs["value"]):
            reasons.append(f"unsupported_numeric_literal:{node.id}")
        elif node.op == "slice":
            bounds = node.attrs["bounds"]
            valid_bounds = (isinstance(bounds, (list, tuple)) and len(bounds) == 2
                            and all(isinstance(axis, (list, tuple)) and len(axis) == 2
                                    and all(v is None or (type(v) is int and abs(v) <= 2**63-1)
                                            for v in axis)
                                    for axis in bounds))
            if not valid_bounds:
                reasons.append(f"unsupported_view_bounds:{node.id}")
            if by_id[node.inputs[0]].op not in ("input", "slice"):
                reasons.append(f"view_of_computed_value:{node.id}")
    if set(input_parameters) != set(region.parameters):
        reasons.append("missing_parameter_input_bindings")
    return reasons


def _dependency_closure(nodes, output):
    by_id = {node.id: node for node in nodes}
    live, pending = set(), [output]
    while pending:
        node_id = pending.pop()
        if node_id not in live:
            live.add(node_id)
            pending.extend(by_id[node_id].inputs)
    return live


def _classify(nodes):
    kinds = value_kinds(nodes)
    setup, body, descriptors, loads = [], [], [], []
    consumers = {i for n in nodes if n.op in _ARITHMETIC for i in n.inputs}
    for node in nodes:
        if kinds[node.id] == "scalar" or node.op in ("input", "slice"):
            setup.append(node.id)
        if node.op in ("input", "slice"):
            descriptors.append(node.id)
            if node.id in consumers:
                loads.append(node.id)
        elif kinds[node.id] == "array":
            body.append(node.id)
    return {
        "setup_nodes": setup,
        "body_nodes": body,
        "body_load_nodes": loads,
        "view_and_input_descriptor_nodes": descriptors,
        "variant_array_nodes": [n.id for n in nodes if kinds[n.id] == "array"],
        "setup_semantics": "Scalar values, input bindings, and view bounds only; "
                           "array contents are loaded again for every call and element.",
        "body_semantics": "One shared scalar DAG evaluated by the row and col loops; "
                          "no cached input values or cached output arrays.",
    }


def _cost(original, optimized, output, memory_budget):
    original_kinds = value_kinds(original)
    optimized_kinds = value_kinds(optimized)
    array_ops = [n for n in original if n.op in _ARITHMETIC
                 and original_kinds[n.id] == "array"]
    baseline_reads = sum(original_kinds[i] == "array"
                         for n in array_ops for i in n.inputs)
    by_id = {n.id: n for n in optimized}
    loads = {i for n in optimized if n.op in _ARITHMETIC
             and optimized_kinds[n.id] == "array" for i in n.inputs
             if by_id[i].op in ("input", "slice")}
    if by_id[output].op in ("input", "slice"):
        loads.add(output)
    allocations = len(array_ops)
    resource_benefit = allocations > 1
    can_fit_nonempty = memory_budget is None or memory_budget >= 8
    decision = ("proposed" if resource_benefit and can_fit_nonempty
                else "not_profitable")
    reasons = (["fewer_full_array_allocations_and_elementwise_intermediate_transfers"]
               if resource_benefit else ["no_full_array_intermediate_to_eliminate"])
    if not can_fit_nonempty:
        reasons.append("memory_budget_cannot_fit_one_nonempty_float64_output")
    return {
        "status": "ESTIMATED", "decision": decision,
        "implementation": "cpu_2d_scalar_dag" if decision == "proposed" else "original",
        "reason": reasons,
        "baseline_array_allocations": allocations,
        "proposed_array_allocations": 1,
        "baseline_view_descriptors": sum(n.op == "slice" for n in original),
        "proposed_view_descriptors": sum(n.op == "slice" for n in optimized),
        "baseline_allocation_bytes_per_output_element": 8 * allocations,
        "proposed_allocation_bytes_per_output_element": 8,
        "baseline_array_reads_per_output_element": baseline_reads,
        "proposed_array_reads_per_output_element": len(loads),
        "baseline_array_writes_per_output_element": allocations,
        "proposed_array_writes_per_output_element": 1,
        "baseline_traffic_bytes_per_output_element": 8 * (baseline_reads + allocations),
        "proposed_traffic_bytes_per_output_element": 8 * (len(loads) + 1),
        "baseline_peak_live_bytes_per_output_element_upper_bound": 8 * allocations,
        "required_memory_bytes": "8 * output_elements",
        "memory_budget_bytes": memory_budget,
        "memory_guard_required": memory_budget is not None,
        "scope": "Array payload allocation and logical element transfers, excluding "
                 "existing inputs, descriptor/setup overhead, allocator overhead, caches "
                 "and compilation. Equal array extents are runtime guarded; peak baseline "
                 "liveness is an upper bound because source lifetime data is unavailable.",
        "measurement": "No measured runtime or speedup; backend selection is a proposal "
                       "requiring clean-process A/B validation.",
    }


def _unsupported(region, reasons, *, retained=(), cpu_threads=1, cpu_capacity=None):
    return ExecutionPlan(region=region, cpu_threads=cpu_threads, proof={
        "supported": False, "legal": False, "selected": False,
        "decision": "unsupported", "reasons": reasons,
        "frontiers": list(region.frontiers),
        "source_operation_map": {
            node.id: {"source_op": node.op, "optimized_node": node.id,
                      "reason": "preserved_unsupported_profile"} for node in region.nodes},
        "eliminated_nodes": [], "setup_nodes": [], "body_nodes": [],
        "retained_constant_operations": list(retained),
        "resource_allocation": {"status": "REQUESTED_UNSUPPORTED",
                                "cpu_threads": cpu_threads,
                                "available_cpu_affinity": cpu_capacity},
    }, cost={"status": "ESTIMATED", "decision": "unsupported",
             "implementation": "original", "reason": reasons,
             "cpu_threads": cpu_threads, "available_cpu_affinity": cpu_capacity})


def optimize_region(region: ArrayRegion, *, memory_budget_bytes=None,
                    cpu_threads=1) -> ExecutionPlan:
    """Propose guarded region coalescing; never infer purity from a function name.

    Malformed DAGs raise ValueError. Unknown semantics and open frontiers yield an
    explicit unchanged unsupported plan. Positive memory budgets become runtime
    output-allocation guards because shapes are not known at planning time.
    CPU threads are an explicit allocation bounded by this process's affinity;
    the planner never changes global environment variables or thread pools.
    """
    if memory_budget_bytes is not None and (type(memory_budget_bytes) is not int
                                           or memory_budget_bytes < 0):
        raise ValueError("memory_budget_bytes must be a nonnegative integer or None")
    cpu_capacity = (len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity")
                    else os.cpu_count() or 1)
    if type(cpu_threads) is not int or not 1 <= cpu_threads <= cpu_capacity:
        raise ValueError("cpu_threads must be a positive integer within available CPU affinity")
    nodes = ordered_nodes(region)
    reasons = _profile_reasons(region, nodes)
    if reasons:
        return _unsupported(region, reasons, cpu_threads=cpu_threads, cpu_capacity=cpu_capacity)
    kinds = value_kinds(nodes)
    output_op = next(node.op for node in nodes if node.id == region.output)
    if kinds[region.output] != "array" or output_op in ("input", "slice"):
        return _unsupported(region, ["fresh_array_computation_output_required"],
                            cpu_threads=cpu_threads, cpu_capacity=cpu_capacity)
    live = _dependency_closure(nodes, region.output)
    dead_array_ops = [n.id for n in nodes if n.id not in live
                      and n.op in _ARITHMETIC and kinds[n.id] == "array"]
    if dead_array_ops:
        return _unsupported(region, ["dead_array_arithmetic_may_warn:" + node_id
                                     for node_id in dead_array_ops],
                            cpu_threads=cpu_threads, cpu_capacity=cpu_capacity)

    graph = simplify(nodes, region.output)
    if graph.retained_constant_operations:
        return _unsupported(region, ["unlowerable_constant_operation:" + item["id"]
                                     for item in graph.retained_constant_operations],
                            retained=graph.retained_constant_operations,
                            cpu_threads=cpu_threads, cpu_capacity=cpu_capacity)
    optimized = replace(region, nodes=graph.nodes, output=graph.output)
    cost = _cost(nodes, graph.nodes, graph.output, memory_budget_bytes)
    cost.update(cpu_threads=cpu_threads, available_cpu_affinity=cpu_capacity,
                thread_overhead="Unmeasured; no speedup is inferred from worker count.")
    guards = list(_RUNTIME_GUARDS)
    if memory_budget_bytes is not None:
        guards.append("OUTPUT_NBYTES_WITHIN_MEMORY_BUDGET")
    proof = {
        "supported": True, "legal": True,
        "selected": False,
        "lowering_eligible": cost["decision"] == "proposed",
        "decision": cost["decision"], "reasons": [],
        "legality": {
            "status": "CONDITIONAL",
            "evidence": "All nodes belong to the closed pure operator profile; "
                        "exact ndarray/layout/shape guards and floating-status fallback "
                        "are obligations of the backend boundary. Foreign-writer absence "
                        "is an external contract, not inferred from ndarray types.",
            "external_assumptions": list(_EXTERNAL_ASSUMPTIONS),
        },
        "effects": {"input_writes": False, "output_policy": "fresh_each_call",
                    "output_cache": False, "purity_basis": "closed_operator_semantics"},
        "runtime_guards": guards, "frontiers": [],
        "resource_allocation": {
            "status": "PROPOSED", "cpu_threads": cpu_threads,
            "available_cpu_affinity": cpu_capacity,
            "parallel_axis": "row" if cpu_threads > 1 else None,
            "partition_policy": "disjoint_output_rows" if cpu_threads > 1 else "serial",
            "output_allocations": 1, "private_full_array_buffers": 0,
            "memory_budget_bytes": memory_budget_bytes,
        },
        "arithmetic_order": "Original operand order and scalar DAG dependencies retained; "
                            "no reassociation, commutation, fast math, or contraction.",
        "source_operation_map": graph.source_operation_map,
        "eliminated_nodes": graph.eliminated_nodes,
        "folded_nodes": graph.folded_nodes,
        "retained_constant_operations": graph.retained_constant_operations,
        **_classify(graph.nodes),
    }
    return ExecutionPlan(region=optimized, cpu_threads=cpu_threads,
                         passes=("constant_folding", "common_subexpression_elimination",
                                 "dead_code_elimination", "invariant_setup_classification",
                                 "elementwise_region_coalescing", "resource_planning"),
                         proof=proof, cost=cost)
