"""Exact symbolic work and logical payload demand, without hardware timing.

Counts describe the guarded scalar DAG and eager/fused array models. They do
not describe cache misses, DRAM traffic, compiler instruction counts or time.
"""
from __future__ import annotations

from collections import Counter

from scar.compiler.provenance import graph_value_sources
from scar.compiler.validation import validate_region
from .graph import value_kinds
from .optimizer import _ARITHMETIC, _classify, _cost


_ORDER = ('add', 'sub', 'mul', 'div', 'neg')
_BASELINE_FIELDS = (
    'baseline_array_allocations', 'baseline_view_descriptors',
    'baseline_allocation_bytes_per_output_element',
    'baseline_array_reads_per_output_element', 'baseline_array_writes_per_output_element',
    'baseline_traffic_bytes_per_output_element',
    'baseline_peak_live_bytes_per_output_element_upper_bound',
)
_FUSED_FIELDS = (
    'proposed_array_allocations', 'proposed_view_descriptors',
    'proposed_allocation_bytes_per_output_element',
    'proposed_array_reads_per_output_element', 'proposed_array_writes_per_output_element',
    'proposed_traffic_bytes_per_output_element',
)


def _unknown(reason, unit=None):
    result = dict(status='UNKNOWN', value=None, reason=reason)
    if unit is not None:
        result['unit'] = unit
    return result


def _quantity(coefficient, unit):
    return dict(per_output_element=coefficient, total=f'{coefficient} * output_elements', unit=unit)


def analyze_region_demand(plan) -> dict:
    """Expose per-element work, per-call setup and missing hardware cost facts.

    Reuse optimizer._cost as the authority for logical loads, allocations and
    transfers. Retained plan.cost supplies the pre-optimization eager baseline;
    without it, the baseline explicitly means eager evaluation of this current
    region DAG. Neither baseline is a prediction of physical memory transfers.
    """
    validate_region(plan.region)
    region, nodes = plan.region, plan.region.nodes
    kinds = value_kinds(nodes)
    by_id = {node.id: node for node in nodes}
    arithmetic = Counter(node.op for node in nodes if node.op in _ARITHMETIC and kinds[node.id] == 'array')
    scalar_arithmetic = Counter(node.op for node in nodes if node.op in _ARITHMETIC and kinds[node.id] == 'scalar')
    classified = _classify(nodes)
    loads = tuple(classified['body_load_nodes'])
    input_loads = tuple(key for key in loads if by_id[key].op == 'input')
    view_loads = tuple(key for key in loads if by_id[key].op == 'slice')

    # The eager baseline of the current DAG and the fused quantities share the
    # exact counting implementation used by optimize_region; no second traffic
    # or allocation estimator is introduced here.
    current = _cost(nodes, nodes, region.output, plan.cost.get('memory_budget_bytes'))
    for field in _FUSED_FIELDS:
        if field in plan.cost and plan.cost[field] != current[field]:
            raise ValueError('retained optimizer cost differs from current fused DAG: '+field)
    if len(loads) != current['proposed_array_reads_per_output_element']:
        raise ValueError('optimizer load classification and logical traffic count differ')
    retained = all(field in plan.cost for field in _BASELINE_FIELDS)
    baseline = plan.cost if retained else current
    if any(type(baseline[field]) is not int or baseline[field] < 0 for field in _BASELINE_FIELDS):
        raise ValueError('baseline payload counts must be nonnegative exact integers')
    allocations = baseline['baseline_array_allocations']
    if allocations < 1:
        raise ValueError('fresh array computation requires at least one eager output allocation')

    provenance = graph_value_sources(plan)
    operations = [dict(expression=node.id, op=node.op, operands=list(node.inputs),
        frequency='PER_OUTPUT_ELEMENT' if kinds[node.id] == 'array' else 'PER_CALL_SETUP',
        source_graph=provenance[node.id]) for node in nodes if node.op in _ARITHMETIC]
    required = {}
    for op in _ORDER:
        if arithmetic[op] or scalar_arithmetic[op]:
            required[f'fp64.{op}.throughput_per_worker'] = _unknown(
                'No executor/compiler-specific effective operation throughput is present in the plan.',
                'operations/second')
            required[f'fp64.{op}.dependency_latency'] = _unknown(
                'Source DAG dependencies do not establish machine instruction latency.', 'seconds')
    for field, unit, reason in (
        ('execution.vectorization', 'float64 elements/instruction',
            'The scalar DAG does not establish compiler SIMD width or emitted instructions.'),
        ('execution.parallel_scaling', 'dimensionless',
            'Requested CPU workers do not establish realized concurrency or throughput scaling.'),
        ('memory.effective_read_bandwidth', 'bytes/second',
            'Logical load bytes and inventory capacity do not establish effective transfer bandwidth.'),
        ('memory.effective_write_bandwidth', 'bytes/second',
            'Logical output stores do not establish write allocation or physical write traffic.'),
        ('memory.cache_line_and_residency_model', None,
            'Input addresses, strides, cache residency and cross-element reuse are not established.'),
        ('allocation.fresh_output_cost', 'seconds/call',
            'Fresh output bytes do not establish allocator latency or success.'),
        ('execution.dispatch_and_worker_setup', 'seconds/call',
            'The plan does not contain dispatch, thread setup, guard or scheduling costs.'),
    ):
        required[field] = _unknown(reason, unit)

    return dict(
        schema='scar.region-demand', schema_version=1, region_id=region.id,
        status='EXACT_SYMBOLIC_WORK_HARDWARE_COSTS_UNRESOLVED',
        symbols=dict(output_elements='output.shape[0] * output.shape[1]', element_bytes=8,
            scalar_type='float64', shape=_unknown('Output extents are determined by guarded call inputs.', 'elements')),
        assumptions=list(region.assumptions),
        loop_axes=[dict(variable=axis.variable,extent=axis.extent) for axis in plan.schedule],
        requested_cpu_threads=plan.cpu_threads,
        per_output_element=dict(arithmetic={op:arithmetic[op] for op in _ORDER},
            input_loads=len(input_loads), view_loads=len(view_loads),
            total_array_loads=len(loads), output_stores=1),
        total_work=dict(arithmetic={op:_quantity(arithmetic[op], 'operations') for op in _ORDER},
            array_loads=_quantity(len(loads), 'float64 loads'),
            output_stores=_quantity(1, 'float64 stores')),
        per_call_setup=dict(input_bindings=sum(node.op=='input' for node in nodes),
            view_descriptors=sum(node.op=='slice' for node in nodes),
            view_axis_normalizations=2*sum(node.op=='slice' for node in nodes),
            scalar_constants=sum(node.op=='const' for node in nodes),
            scalar_arithmetic={op:scalar_arithmetic[op] for op in _ORDER},
            logical_output_allocations=1, region_invocations=1,
            scope='Logical binding/descriptor/scalar setup; machine instructions and setup time remain unknown.'),
        baseline=dict(reference='RETAINED_OPTIMIZER_SOURCE_DAG' if retained else 'CURRENT_REGION_DAG_EAGER_MODEL',
            accounting_authority='optimizer._cost', array_allocations_per_call=allocations,
            view_descriptors_per_call=baseline['baseline_view_descriptors'],
            cumulative_array_allocation_bytes=_quantity(baseline['baseline_allocation_bytes_per_output_element'], 'bytes'),
            cumulative_intermediate_allocation_bytes=_quantity(8*(allocations-1), 'bytes'),
            logical_array_reads=_quantity(baseline['baseline_array_reads_per_output_element'], 'float64 loads'),
            logical_array_writes=_quantity(baseline['baseline_array_writes_per_output_element'], 'float64 stores'),
            logical_payload_transfer_bytes=_quantity(baseline['baseline_traffic_bytes_per_output_element'], 'bytes'),
            peak_payload_bytes_upper_bound=_quantity(baseline['baseline_peak_live_bytes_per_output_element_upper_bound'], 'bytes'),
            actual_peak_payload_bytes=_unknown('Original intermediate lifetimes are not retained.', 'bytes'),
            allocation_scope='Cumulative intermediate allocation excludes the final fresh output and existing inputs; it is not peak live memory.'),
        fused=dict(accounting_authority='optimizer._cost',
            fresh_output_bytes=_quantity(current['proposed_allocation_bytes_per_output_element'], 'bytes'),
            private_full_array_intermediate_bytes=_quantity(0, 'bytes'),
            logical_payload_transfer_bytes=_quantity(current['proposed_traffic_bytes_per_output_element'], 'bytes'),
            input_load_expressions=list(input_loads), view_load_expressions=list(view_loads),
            load_semantics='One logical load per distinct consumed input/view descriptor per output element; overlap does not merge value versions.'),
        operations=operations,
        source_provenance=dict(by_optimized_expression=provenance,
            inferred_content_versions=False, traversal_origins_are_work=False),
        required_hardware_cost_fields=required,
        unknown=dict(actual_dram_read_bytes=_unknown('Logical loads are not cache misses or physical DRAM transfers.', 'bytes'),
            actual_dram_write_bytes=_unknown('Logical stores do not establish physical write traffic.', 'bytes'),
            cache_misses=_unknown('No cache or address/residency model is supplied.', 'misses'),
            duration_seconds=_unknown('Arithmetic counts and logical bytes are demands, not durations.', 'seconds')),
        timing_prediction_available=False, target_executed=False,
    )


__all__ = ['analyze_region_demand']
