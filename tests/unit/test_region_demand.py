"""Symbolic demand counts remain separate from physical hardware costs."""
from dataclasses import replace

import pytest

from scar.compiler.model import ArrayRegion, ExecutionPlan, Expr, SourceRef
from scar.optimization.optimizer import optimize_region
from scar.optimization.demand import analyze_region_demand


def _region():
    nodes=(Expr('a','input',attrs={'name':'a'}),
        Expr('view','slice',('a',),{'bounds':[[None,None],[None,None]]}),
        Expr('two','const',attrs={'value':2}),
        Expr('left','add',('view','two')),Expr('right','add',('view','two')),
        Expr('out','mul',('left','right')))
    origins=tuple(dict(kind='original_f4',expression=key,unit='original-unit',
        template={'occurrence':41,'purpose':'VALUE'},region='original-region',step='step-'+key)
        for key in ('left','right','out'))
    source=SourceRef('/original.py','a'*64,'arbitrary',1,0,'pycode-v2:'+'b'*64,origins)
    return ArrayRegion('region',source,('a',),nodes,'out')


def test_exact_cse_work_and_retained_eager_baseline_do_not_predict_dram_or_time():
    plan=optimize_region(_region())
    demand=analyze_region_demand(plan)
    assert demand['per_output_element']==dict(arithmetic=dict(add=1,sub=0,mul=1,div=0,neg=0),
        input_loads=0,view_loads=1,total_array_loads=1,output_stores=1)
    assert demand['total_work']['arithmetic']['add']['total']=='1 * output_elements'
    assert demand['baseline']['reference']=='RETAINED_OPTIMIZER_SOURCE_DAG'
    assert demand['baseline']['array_allocations_per_call']==3
    assert demand['baseline']['cumulative_intermediate_allocation_bytes']['per_output_element']==16
    assert demand['baseline']['logical_payload_transfer_bytes']['per_output_element']==56
    assert demand['fused']['logical_payload_transfer_bytes']['per_output_element']==16
    assert demand['fused']['fresh_output_bytes']['per_output_element']==8
    assert demand['fused']['private_full_array_intermediate_bytes']['per_output_element']==0
    setup=demand['per_call_setup']
    assert (setup['input_bindings'],setup['view_descriptors'],setup['view_axis_normalizations'],
        setup['scalar_constants'],setup['logical_output_allocations'])==(1,1,2,1,1)
    assert demand['loop_axes']==[dict(variable='row',extent='output.shape[0]'),
        dict(variable='col',extent='output.shape[1]')]
    assert [row['expression'] for row in demand['source_provenance']['by_optimized_expression']['left']]==['left','right']
    assert not demand['source_provenance']['inferred_content_versions']
    for field in ('actual_dram_read_bytes','actual_dram_write_bytes','cache_misses','duration_seconds'):
        assert demand['unknown'][field]['value'] is None
    assert demand['required_hardware_cost_fields']['fp64.add.throughput_per_worker']['status']=='UNKNOWN'
    assert 'fp64.div.throughput_per_worker' not in demand['required_hardware_cost_fields']
    assert not demand['timing_prediction_available']


def test_without_retained_cost_baseline_is_explicitly_the_current_eager_dag():
    plan=ExecutionPlan(_region())
    demand=analyze_region_demand(plan)
    assert demand['baseline']['reference']=='CURRENT_REGION_DAG_EAGER_MODEL'
    assert demand['per_output_element']['arithmetic']['add']==2
    assert demand['baseline']['array_allocations_per_call']==3


def test_conflicting_retained_fused_cost_is_rejected():
    plan=optimize_region(_region())
    corrupted=replace(plan,cost={**plan.cost,'proposed_array_reads_per_output_element':99})
    with pytest.raises(ValueError,match='retained optimizer cost differs'):
        analyze_region_demand(corrupted)
