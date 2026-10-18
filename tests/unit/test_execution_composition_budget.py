"""P/V shared entry points retain one budget and one final detach boundary."""
from dataclasses import replace

import pytest

from scar.ir.execution.ids import ContentReadID, ContributionSupportID
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.production_query import production, production_shared
from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.execution.validity_query import validity, validity_shared
from scar.ir.execution.validation import refresh_external_context
from tests.fixtures.execution_visibility_graphs import visibility_execution


def _prepared(*, two_reads=False):
    program, model, values, payloads, details = visibility_execution()
    if two_reads:
        another = ContentReadID('composition.second')
        model = replace(model, content_reads=(*model.content_reads, replace(model.content_reads[0], id=another)),
            contribution_supports=(*model.contribution_supports,
                *(replace(row, id=ContributionSupportID('second.' + row.id.value), read=another)
                  for row in model.contribution_supports)))
    index = ExecutionIndex(model, program, value_graphs=values, artifact_bytes=payloads)
    return refresh_external_context(index._ctx), details['read']


def test_shared_validity_does_not_call_public_production_or_detach_intermediate_views(monkeypatch):
    import scar.ir.execution.production_query as p_module
    import scar.ir.execution.validity_query as v_module

    ctx, read = _prepared()

    def forbidden(*args, **kwargs):
        raise AssertionError('internal shared queries must not call public wrappers or detach')

    monkeypatch.setattr(p_module, 'production', forbidden)
    monkeypatch.setattr(p_module, 'deepcopy', forbidden)
    monkeypatch.setattr(v_module, 'deepcopy', forbidden)
    budget = ValidityBudget(4096)
    result = validity_shared(ctx, read, budget=budget)
    assert result['conditional_support']['status'] == 'MATCHED'
    assert result['read'] is ctx.resolved_content_reads[read]['read']
    assert result['budget_used'] == budget.used <= 4096
    assert sum(result['budget_costs'].values()) == budget.used
    assert 'source_runtime_unverified' not in {row['code'] for row in result['gaps']}
    assert 'source_runtime_unverified' not in {
        row['code'] for row in result['source_universe']['gaps']}


def test_multiple_real_read_obligations_share_total_budget_without_reset():
    ctx, first_read = _prepared(two_reads=True)
    second_read = next(identity for identity in ctx.resolved_content_reads if identity != first_read)
    first_single = validity(ctx, first_read)
    second_single = validity(ctx, second_read)
    assert first_single['conditional_support']['status'] == second_single['conditional_support']['status'] == 'MATCHED'
    limit = first_single['budget_used'] + max(1, second_single['budget_used'] // 2)
    budget = ValidityBudget(limit)
    first = validity_shared(ctx, first_read, budget=budget)
    second = validity_shared(ctx, second_read, budget=budget)
    assert first['conditional_support']['status'] == 'MATCHED'
    assert second['conditional_support']['status'] == 'TRUNCATED'
    assert first['budget_used'] + second['budget_used'] == budget.used == limit
    assert sum(budget.costs.values()) == budget.used
    assert second['source_reconciliation']['known_joins'] == 'TRUNCATED'
    assert second['read'].id == second_read


def test_no_remaining_budget_is_truncated_not_reset_to_a_new_per_read_allowance():
    ctx, read = _prepared()
    budget = ValidityBudget(1)
    assert budget.spend('earlier_obligation')
    result = validity_shared(ctx, read, budget=budget)
    assert result['conditional_support']['status'] == 'TRUNCATED'
    assert result['budget_used'] == 0 and budget.used == 1
    assert result['source_universe']['pending_sources']
    assert not result['contributions']


def test_shared_p_budget_is_charged_once_and_does_not_reset_before_v():
    ctx, read = _prepared()
    single = production(ctx, read)
    budget = ValidityBudget(single['budget_used'] + 16)
    p = production_shared(ctx, read, budget=budget)
    assert p['budget_used'] == single['budget_used'] == budget.used
    v = validity_shared(ctx, read, budget=budget)
    assert v['truncated'] and budget.remaining == 0
    assert p['budget_used'] + v['budget_used'] == budget.used


@pytest.mark.parametrize('query', (production, validity))
def test_legacy_public_queries_still_detach_and_include_context_gaps(query):
    ctx, read = _prepared()
    result = query(ctx, read)
    assert result['read'] == ctx.resolved_content_reads[read]['read']
    assert result['read'] is not ctx.resolved_content_reads[read]['read']
    assert 'source_runtime_unverified' in {row['code'] for row in result['gaps']}
    assert result['budget_used'] > 0 and not result['truncated']
    assert not result['transformation_authorized']


@pytest.mark.parametrize('query', (production, validity))
@pytest.mark.parametrize('budget,exception', ((0, ValueError), (True, TypeError)))
def test_legacy_public_budget_guards_remain(query, budget, exception):
    ctx, read = _prepared()
    with pytest.raises(exception):
        query(ctx, read, budget=budget)
