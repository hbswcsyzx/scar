from dataclasses import FrozenInstanceError, fields, replace

import pytest

from scar.ir.execution.common import MissingEvidence, Unresolved
from scar.ir.execution.coordinates import BlockVisitID, OperationOccurrenceID, RegionActivationID
from scar.ir.execution.model import TABLE_TYPES
from scar.ir.execution.resumables import BodyActivationOrigin, BodyDriveExecution
from scar.ir.program.providers import ProviderFactReference
from tests.fixtures.execution_validity_records import validity_record_model


def _rows(source=None):
    model = validity_record_model()
    source = model.runs[0].source if source is None else source
    drive = BodyDriveExecution(
        model.operations[0].id,
        model.activations[0].id,
        model.visits[0].id,
        model.operations[-1].id,
        source,
    )
    origin = BodyActivationOrigin(
        model.activations[0].id,
        model.operations[0].id,
        source,
    )
    return model, drive, origin


def test_resumable_records_are_frozen_exact_routes_without_new_identity_ids():
    model, drive, origin = _rows()
    assert tuple(field.name for field in fields(drive)) == (
        "drive", "activation", "entry", "outcome", "source")
    assert tuple(field.name for field in fields(origin)) == (
        "activation", "creation", "source")
    assert not hasattr(drive, "id") and not hasattr(origin, "id")
    assert TABLE_TYPES["body_drive_executions"] is BodyDriveExecution
    assert TABLE_TYPES["body_activation_origins"] is BodyActivationOrigin
    assert model.body_drive_executions == ()
    assert model.body_activation_origins == ()
    with pytest.raises(FrozenInstanceError):
        drive.activation = RegionActivationID("replacement")


def test_missing_endpoints_and_evidence_sources_remain_explicit_records():
    model = validity_record_model()
    gap = Unresolved("body visit or outcome not captured", model.activations[0].entry)
    fact = ProviderFactReference(model.snapshot.artifact, "body-drive-observation")
    drive = BodyDriveExecution(
        model.operations[0].id, model.activations[0].id, gap, gap, fact)
    origin = BodyActivationOrigin(model.activations[0].id, gap,
                                  MissingEvidence("creation was outside the captured run"))
    assert drive.entry is gap and drive.outcome is gap and drive.source is fact
    assert origin.creation is gap
    assert type(origin.source) is MissingEvidence


@pytest.mark.parametrize(("field", "value"), (
    ("drive", RegionActivationID("wrong.drive.family")),
    ("activation", OperationOccurrenceID("wrong.activation.family")),
    ("entry", OperationOccurrenceID("wrong.entry.family")),
    ("outcome", BlockVisitID("wrong.outcome.family")),
    ("source", object()),
))
def test_body_drive_execution_rejects_wrong_nested_record_types(field, value):
    _, drive, _ = _rows()
    with pytest.raises((TypeError, ValueError)):
        replace(drive, **{field: value})


@pytest.mark.parametrize(("field", "value"), (
    ("activation", OperationOccurrenceID("wrong.activation.family")),
    ("creation", BlockVisitID("wrong.creation.family")),
    ("source", True),
))
def test_body_activation_origin_rejects_wrong_nested_record_types(field, value):
    _, _, origin = _rows()
    with pytest.raises((TypeError, ValueError)):
        replace(origin, **{field: value})


@pytest.mark.parametrize(("record", "attribute"), (
    ("drive", "drive"), ("drive", "activation"),
    ("origin", "activation"), ("origin", "creation"),
))
def test_nested_identifier_values_are_rechecked(record, attribute):
    _, drive, origin = _rows()
    row = drive if record == "drive" else origin
    value = getattr(row, attribute)
    object.__setattr__(value, "value", True)
    with pytest.raises((TypeError, ValueError)):
        row.__post_init__()


def test_execution_model_rechecks_exact_resumable_table_tuples():
    model, drive, origin = _rows()
    populated = replace(model, body_drive_executions=(drive,),
                        body_activation_origins=(origin,))
    populated.__post_init__()
    object.__setattr__(populated, "body_drive_executions", [drive])
    with pytest.raises(TypeError, match="body_drive_executions"):
        populated.__post_init__()
