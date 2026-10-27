"""One fresh external snapshot revalidates every existing execution layer."""
from dataclasses import replace

import pytest

from scar.ir.execution.inventory import InventoryResolver
from scar.ir.execution.model import LegacyOperationRef, OccurrenceEvidenceBinding
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.production_query import production_shared
from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.execution.validation import refresh_external_context
from scar.ir.v2.ids import LogicalValueID
from scar.ir.v2.values import LogicalValue
from tests.fixtures.execution_content_graphs import content_connection_fixture
from tests.fixtures.execution_order_graphs import event_order_execution
from tests.fixtures.execution_resource_graphs import resource_execution_with_allocation
from tests.fixtures.execution_visibility_graphs import visibility_execution
from tests.fixtures.execution_work_graphs import ordinary_work_execution


@pytest.mark.parametrize('layer', ('resource', 'work'))
def test_refresh_rejects_changed_values_used_only_by_resource_or_work(layer):
    program, model, values = (resource_execution_with_allocation() if layer == 'resource'
                              else ordinary_work_execution(retained='materialization'))
    assert not model.content_reads and not model.writes and not model.denotations
    index = ExecutionIndex(model, program, value_graphs=values)
    original_report = index.report
    graph = next(iter(values.values()))
    graph.add_logical_value(LogicalValue(LogicalValueID('refresh.changed'), 'changed'))
    with pytest.raises(ValueError, match='external_snapshot'):
        refresh_external_context(index._ctx)
    # Query failure cannot mutate the construction context or its cached report.
    assert index.report == original_report and not index._ctx.issues


def test_refresh_rechecks_order_only_evidence_binding_catalog():
    program, model = event_order_execution()
    _, source_model, _, evidence, _ = content_connection_fixture()
    original = source_model.evidence_bindings[0]
    binding = OccurrenceEvidenceBinding(model.operations[0].id,
        LegacyOperationRef(original.legacy.artifact, original.legacy.instance), original.source)
    model = replace(model, evidence_bindings=(binding,))
    assert model.queue_order_profiles and not model.content_reads
    index = ExecutionIndex(model, program, evidence_graphs=evidence)
    original_steps = tuple(index._ctx.order_steps)
    next(iter(evidence.values())).instances.clear()
    with pytest.raises(ValueError, match='external_graph_invalid|external_snapshot'):
        refresh_external_context(index._ctx)
    assert tuple(index._ctx.order_steps) == original_steps and not index._ctx.issues


def test_missing_work_catalog_stays_a_gap_after_refresh_instead_of_old_cached_fact():
    program, model, values = ordinary_work_execution(retained='materialization')
    index = ExecutionIndex(model, program, value_graphs=values)
    old_gaps = tuple(index._ctx.gaps)
    values.clear()
    fresh = refresh_external_context(index._ctx)
    assert 'external_graph_unavailable' in {item.code for item in fresh.gaps}
    assert tuple(index._ctx.gaps) == old_gaps
    assert fresh.snapshots is not index._ctx.snapshots
    assert fresh.external_preparation['stage_calls'] == (
        'source_inventory', 'resource', 'work', 'order', 'evidence_bindings',
        'observation', 'content', 'source_bridge', 'write', 'produced', 'validity')


def test_refresh_keeps_canonical_and_external_gaps_without_sharing_mutable_derived_maps():
    program, model = event_order_execution()
    index = ExecutionIndex(model, program)
    fresh = refresh_external_context(index._ctx)
    assert {item.code for item in index._ctx.gaps} <= {item.code for item in fresh.gaps}
    assert fresh.external_preparation['canonical_flow_reused']
    assert fresh.resolved_call_activations is not index._ctx.resolved_call_activations
    occurrence = next(iter(fresh.before))
    fresh.before[occurrence].clear()
    assert index._ctx.before[occurrence]
    point = next(iter(fresh.order_adjacency))
    old_steps = tuple(index._ctx.order_adjacency[point])
    fresh.order_adjacency[point].clear()
    assert tuple(index._ctx.order_adjacency[point]) == old_steps


def test_prepared_context_replays_inventory_once_for_multiple_shared_reads(monkeypatch):
    program, model, values, payloads, details = visibility_execution()
    index = ExecutionIndex(model, program, value_graphs=values, artifact_bytes=payloads)
    calls = []
    original = InventoryResolver.resolve

    def counted(resolver, manifest, inventory_index):
        calls.append((manifest, inventory_index))
        return original(resolver, manifest, inventory_index)

    monkeypatch.setattr(InventoryResolver, 'resolve', counted)
    fresh = refresh_external_context(index._ctx)
    assert len(calls) == 1
    budget = ValidityBudget(16384)
    first = production_shared(fresh, details['read'], budget=budget)
    second = production_shared(fresh, details['read'], budget=budget)
    assert len(calls) == 1
    assert first['candidates'] and first['candidates'] == second['candidates']
    assert first['budget_used'] + second['budget_used'] == budget.used
    assert not fresh.issues

