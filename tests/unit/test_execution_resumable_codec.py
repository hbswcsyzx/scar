from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pytest

from scar.ir.execution.codec import SCHEMA_VERSION, dumps, from_dict, loads, to_dict
from scar.ir.execution.common import MissingEvidence, Unresolved
from scar.ir.execution.resumables import BodyActivationOrigin, BodyDriveExecution
from scar.ir.program.providers import ProviderFactReference
from tests.fixtures.execution_validity_records import validity_record_model

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _resumable_model():
    model = validity_record_model()
    gap = Unresolved("body entry/outcome was not captured", model.activations[0].entry)
    fact = ProviderFactReference(model.snapshot.artifact, "body-drive-link")
    drive = BodyDriveExecution(
        model.operations[0].id, model.activations[0].id, model.visits[0].id,
        gap, fact)
    origin = BodyActivationOrigin(
        model.activations[0].id, gap,
        MissingEvidence("creation preceded the captured interval"))
    return replace(model, body_drive_executions=(drive,),
                   body_activation_origins=(origin,))


def test_schema8_roundtrip_keeps_both_resumable_tables_and_unresolved_variants():
    model = _resumable_model()
    document = to_dict(model)
    assert SCHEMA_VERSION == document["schema_version"] == 8
    fields = document["model"]["fields"]
    assert len(fields["body_drive_executions"]) == 1
    assert len(fields["body_activation_origins"]) == 1
    restored = loads(dumps(model))
    assert restored == model
    assert dumps(restored) == dumps(model)
    drive, = restored.body_drive_executions
    origin, = restored.body_activation_origins
    assert type(drive) is BodyDriveExecution
    assert type(origin) is BodyActivationOrigin
    assert type(drive.entry).__name__ == "BlockVisitID"
    assert type(drive.outcome) is Unresolved
    assert type(origin.creation) is Unresolved
    assert type(origin.source) is MissingEvidence


@pytest.mark.parametrize("version", range(1, 8))
def test_independent_v1_to_v7_golden_bytes_and_empty_resumable_defaults_remain_exact(version):
    payload = (FIXTURES / f"execution_v{version}_frozen.json").read_bytes()
    model = loads(payload.decode("utf-8"))
    assert model.body_drive_executions == ()
    assert model.body_activation_origins == ()
    assert dumps(model, schema_version=version).encode("utf-8") == payload
    assert to_dict(model)["schema_version"] == version
    assert "body_drive_executions" not in to_dict(model)["model"]["fields"]
    assert "body_activation_origins" not in to_dict(model)["model"]["fields"]


def test_v7_golden_was_generated_by_the_immutable_old_codec_with_populated_calls():
    payload = (FIXTURES / "execution_v7_frozen.json").read_bytes()
    proof = json.loads((FIXTURES / "execution_v7_frozen.proof.json").read_text())
    assert proof["revision"] == "a740661bdf5ed34676d65e6c8eb5f15b890e0084"
    assert proof["schema_version"] == 7
    assert proof["encoder"] == "scar.ir.execution.codec.dumps(model, schema_version=7)"
    assert proof["call_activation_count"] == 2
    assert proof["call_activations"] == ["call1", "call2"]
    assert proof["codec_sha256"] == proof["immutable_blobs"]["scar/ir/execution/codec.py"]
    assert proof["fixture_sha256"] == proof["immutable_blobs"][proof["fixture_source"]]
    assert proof["payload_sha256"] == sha256(payload).hexdigest()
    assert proof["payload_bytes"] == len(payload)
    decoded = loads(payload.decode("utf-8"))
    assert len(decoded.call_activations) == 2
    assert all(type(row).__name__ == "CallActivation" for row in decoded.call_activations)
    assert decoded.body_drive_executions == ()
    assert decoded.body_activation_origins == ()


@pytest.mark.parametrize("version", range(1, 8))
def test_populated_resumable_capability_cannot_be_silently_downgraded(version):
    with pytest.raises(ValueError, match="resumable capability"):
        dumps(_resumable_model(), schema_version=version)


def test_explicit_empty_v8_roundtrips_but_automatic_selection_keeps_v7_capability():
    model = loads((FIXTURES / "execution_v7_frozen.json").read_text())
    document = to_dict(model, schema_version=8)
    assert document["schema_version"] == 8
    assert document["model"]["fields"]["body_drive_executions"] == []
    assert document["model"]["fields"]["body_activation_origins"] == []
    restored = from_dict(document)
    assert restored == model
    assert to_dict(restored)["schema_version"] == 7


@pytest.mark.parametrize("injection", ("table", "record-tag"))
@pytest.mark.parametrize("version", range(1, 8))
def test_pre_resumable_schemas_reject_new_tables_and_record_tags(version, injection):
    document = json.loads((FIXTURES / f"execution_v{version}_frozen.json").read_text())
    root = document["model"]["fields"]
    if injection == "table":
        root["body_drive_executions"] = []
    else:
        root["runs"][0]["fields"]["source"] = {
            "$record": "scar.ir.execution.resumables.BodyDriveExecution", "fields": {}}
    with pytest.raises(ValueError):
        from_dict(document)


@pytest.mark.parametrize("corruption", (
    "missing-table", "missing-endpoint", "extra-field", "wrong-endpoint-family",
    "wrong-origin-family", "wrong-source-family", "bool-identifier", "unknown-record-tag",
))
def test_schema8_rejects_malformed_resumable_record_shapes(corruption):
    document = to_dict(_resumable_model())
    root = document["model"]["fields"]
    drive = root["body_drive_executions"][0]
    drive_fields = drive["fields"]
    origin_fields = root["body_activation_origins"][0]["fields"]
    if corruption == "missing-table":
        del root["body_drive_executions"]
    elif corruption == "missing-endpoint":
        del drive_fields["entry"]
    elif corruption == "extra-field":
        drive_fields["runtime_verified"] = False
    elif corruption == "wrong-endpoint-family":
        drive_fields["entry"] = deepcopy(drive_fields["activation"])
    elif corruption == "wrong-origin-family":
        origin_fields["creation"] = deepcopy(drive_fields["activation"])
    elif corruption == "wrong-source-family":
        drive_fields["source"] = deepcopy(drive_fields["activation"])
    elif corruption == "bool-identifier":
        drive_fields["drive"]["value"] = True
    else:
        drive["$record"] = "untrusted.resumables.BodyDriveExecution"
    with pytest.raises(ValueError):
        from_dict(document)
