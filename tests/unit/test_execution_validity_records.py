"""Strict support identities are a modeling trust boundary, never readiness."""
from dataclasses import FrozenInstanceError, replace

import pytest

from scar.ir.execution.coordinates import AccessRef
from scar.ir.execution.ids import ContributionSupportID, OutcomeProductionID, ValueOccurrenceID
from scar.ir.execution.validity import CompletedVisibility, ContributionSupport, LifetimeEventKind
from scar.ir.execution.validity_budget import ValidityBudget
from tests.fixtures.execution_validity_records import validity_record_model


def test_lifetime_and_establishment_keep_distinct_original_targets_and_points():
    model = validity_record_model()
    assert model.target_lifetime_events[0].kind is LifetimeEventKind.RETIRED
    assert model.target_lifetime_events[1].kind is LifetimeEventKind.LIVE
    assert model.target_lifetime_events[1].effect is None
    assert model.established_productions[0].write == model.writes[1].id
    assert model.established_productions[0].actual == model.writes[0].placement.selector
    assert model.contribution_supports[-1].production == model.established_productions[0].id
    assert not hasattr(model.contribution_supports[0], 'ready')


def test_none_means_pending_ordered_only_not_unknown_or_completed():
    model = validity_record_model()
    support = model.contribution_supports[0]
    with pytest.raises(ValueError, match='pending ordered'):
        replace(support, production=None)
    unknown = model.contribution_supports[-2]
    assert unknown.production is not None
    assert model.contribution_supports[-3].production is None


def test_nested_private_mutation_is_rechecked_and_subclasses_are_not_wire_types():
    model = validity_record_model()
    record = model.target_lifetime_events[0]
    class DerivedAccess(AccessRef):
        pass
    object.__setattr__(record, 'effect', DerivedAccess(record.effect.operation, 0))
    with pytest.raises(TypeError):
        record.__post_init__()
    class DerivedID(ContributionSupportID):
        pass
    with pytest.raises(TypeError):
        replace(model.contribution_supports[0], id=DerivedID('subclass'))
    class DerivedString(str):
        pass
    with pytest.raises(ValueError, match='exact string'):
        replace(model.contribution_supports[0], production=OutcomeProductionID(DerivedString('typed-but-noncanonical')))
    with pytest.raises(ValueError, match='exact string'):
        replace(model.established_productions[0], result=ValueOccurrenceID(DerivedString('typed-but-noncanonical')))


def test_records_frozen_slotted_and_strict_order_cannot_be_self_loop():
    model = validity_record_model()
    support = model.contribution_supports[0]
    with pytest.raises(FrozenInstanceError):
        support.production = None
    assert not hasattr(support, '__dict__')
    order = model.order_associations[0]
    with pytest.raises(ValueError, match='before itself'):
        replace(order, after=order.before)


@pytest.mark.parametrize('limit', (True, '4', 0, -1))
def test_shared_budget_rejects_invalid_limit_before_work(limit):
    with pytest.raises((ValueError, TypeError)):
        ValidityBudget(limit)


def test_one_budget_saturates_and_preserves_every_stage_cost_and_truncation():
    budget = ValidityBudget(7)
    assert budget.spend('source', 3)
    assert budget.spend('geometry', 2)
    assert not budget.spend('order', 3, 'read/order')
    assert budget.used == 7 and budget.remaining == 0 and budget.truncated
    assert budget.costs == dict(source=3, geometry=2, order=2)
    assert not budget.spend('invalidators', 1, 'read/stability')
    assert len(budget.gaps) == 2
    assert all(gap['code'] == 'validity_budget_exhausted' for gap in budget.gaps)
