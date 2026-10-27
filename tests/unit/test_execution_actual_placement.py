"""Unknown native protocol cannot waive known physical placement constraints."""
from dataclasses import replace

import pytest

from scar.ir.execution.coverage import RegionRef
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.snapshot import external_artifact
from scar.ir.execution.validation import validate
from scar.ir.execution.work import MaterializationRef
from scar.ir.v2.ids import StorageAllocationID
from scar.ir.v2.values import StorageAllocation
from tests.fixtures.execution_produced_graphs import produced_execution


def _alter(case):
    program, model, values = produced_execution()
    original = model.writes[0].placement.materialization.artifact
    graph = values[original.sha256]
    actual = model.produced[0].actual.region
    if case == 'allocation':
        allocation = StorageAllocationID('different.actual.incarnation')
        graph.add_allocation(StorageAllocation(allocation, 'cpu', 32))
        graph.regions[actual] = replace(graph.regions[actual], allocation=allocation)
    elif case == 'outside':
        graph.regions[actual] = replace(graph.regions[actual], offset=8)
    elif case == 'scope':
        graph.allocations[next(iter(graph.allocations))].metadata['other-snapshot'] = True
    artifact = external_artifact(graph)
    if case == 'scope':
        _, _, original_values = produced_execution()
        catalogs = {**original_values, artifact.sha256:graph}
    else:
        write = model.writes[0]
        placement = replace(write.placement,
            materialization=MaterializationRef(artifact, write.placement.materialization.materialization),
            selector=RegionRef(artifact, write.placement.selector.region))
        model = replace(model, writes=(replace(write, placement=placement),))
        catalogs = {artifact.sha256:graph}
    model = replace(model, produced=(replace(model.produced[0], actual=RegionRef(artifact, actual)),))
    return program, model, catalogs


@pytest.mark.parametrize('case,code', (('allocation','production_selector_allocation'),
    ('outside','production_actual_outside'), ('scope','production_selector_scope')))
def test_unknown_rule_does_not_authorize_cross_allocation_scope_or_outside_mat(case, code):
    program, model, values = _alter(case)
    report = validate(model, program, value_graphs=values)
    assert not report.valid
    assert any(row.code == code for row in report.issues), report


def test_consistent_partial_actual_with_unknown_rule_retains_exact_mat_match_but_no_native_proof():
    program, model, values = produced_execution()
    index = ExecutionIndex(model, program, value_graphs=values)
    result = index.outcome_production(model.produced[0].id)
    assert result['placement_match'] is True
    assert result['actual'].shape == (4,)
    assert result['requested'] is None
    assert any(row.code == 'production_rule_unresolved' for row in result['validation_gaps'])
    assert not result['source_runtime_verified'] and not result['transformation_authorized']
