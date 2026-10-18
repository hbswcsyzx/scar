"""Call activation records preserve typed identity without adding route tables."""
from dataclasses import FrozenInstanceError, replace

import pytest

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.common import MissingEvidence, Unresolved
from scar.ir.execution.ids import CallActivationID, OperationOccurrenceID
from scar.ir.execution.coordinates import BlockVisitID
from scar.ir.execution.model import TABLE_TYPES
from scar.ir.program.providers import ProviderFactReference
from tests.fixtures.execution_validity_records import validity_record_model


def _record(*, source=None):
    model = validity_record_model()
    return CallActivation(
        CallActivationID('records.call'),
        model.operations[0].id,
        model.activations[0].id,
        model.visits[0].id,
        model.operations[-1].id,
        model.runs[0].source if source is None else source,
    )


def test_call_activation_is_frozen_typed_identity_with_only_declared_endpoints():
    row = _record()
    assert type(row) is CallActivation
    assert tuple(row.__dataclass_fields__) == (
        'id', 'caller', 'activation', 'entry', 'completion', 'source')
    assert TABLE_TYPES['call_activations'] is CallActivation
    assert not hasattr(row, 'arguments') and not hasattr(row, 'results')
    assert not hasattr(row, 'runtime_verified')
    with pytest.raises(FrozenInstanceError):
        row.caller = OperationOccurrenceID('other')


def test_record_accepts_explicit_missing_endpoints_and_provider_fact_without_resolving_them():
    model = validity_record_model()
    missing = Unresolved('entry/completion were not retained', model.activations[0].entry)
    source = ProviderFactReference(model.snapshot.artifact, 'call-pairing-record')
    row = _record(source=source)
    row = replace(row, entry=missing, completion=missing)
    assert row.entry is missing and row.completion is missing
    assert row.source is source


@pytest.mark.parametrize('field,value', (
    ('id', OperationOccurrenceID('wrong.id.family')),
    ('caller', CallActivationID('wrong.caller.family')),
    ('activation', OperationOccurrenceID('wrong.activation.family')),
    ('entry', OperationOccurrenceID('wrong.entry.family')),
    ('completion', BlockVisitID('wrong.completion.family')),
    ('source', object()),
))
def test_constructor_rejects_wrong_nested_types(field, value):
    row = _record()
    with pytest.raises((TypeError, ValueError)):
        replace(row, **{field: value})


@pytest.mark.parametrize('field', ('id', 'caller', 'activation', 'entry', 'completion'))
def test_nested_identifier_mutation_is_rechecked(field):
    row = _record()
    object.__setattr__(getattr(row, field), 'value', True)
    with pytest.raises((TypeError, ValueError)):
        row.__post_init__()


def test_source_gap_is_explicit_and_does_not_turn_record_into_an_unresolved_call():
    row = _record(source=MissingEvidence('pairing provenance was not captured'))
    assert type(row.entry) is BlockVisitID
    assert type(row.completion) is OperationOccurrenceID
    assert type(row.source) is MissingEvidence
