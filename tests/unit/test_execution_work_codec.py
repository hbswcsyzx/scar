"""Execution wire v2 is explicit; old resource-only bytes and identities persist.

Codec assertions cover local record shape, not the truth of physical work or
full execution-graph validation. Fixtures are declared IR, not collected runs.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from scar.ir.execution.codec import SCHEMA_VERSION, dumps, from_dict, loads, to_dict
from scar.ir.execution.common import Unresolved
from scar.ir.execution.work import (
    DirectExecution, ExternalWorkSource, InvokeBoundaryStateEffect,
    Queued, WorkOutcomeKind,
)
from tests.fixtures.execution_resource_graphs import resource_execution_program
from tests.fixtures.execution_work_graphs import ordinary_work_execution, invoke_work_execution


WORK_FIELDS = ("submissions", "outcomes", "quiescences", "retentions", "queue_prefixes")
FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture(scope="module")
def queued():
    return ordinary_work_execution(queued=True, two_tickets=True, retained="allocation")[1]


def _fields(document):
    return document["model"]["fields"]


def test_frozen_v1_is_independent_and_current_default_preserves_exact_bytes():
    payload = (FIXTURES / "execution_v1_frozen.json").read_bytes()
    proof = json.loads((FIXTURES / "execution_v1_frozen.proof.json").read_text())
    assert proof["source_revision"] == "6fcac0f778d56d7fe4fdb90e546b23e545f86f96"
    assert proof["codec_schema_version"] == proof["wire_schema_version"] == 1
    assert proof["payload_sha256"] == hashlib.sha256(payload).hexdigest()
    assert proof["payload_size_bytes"] == len(payload)
    assert proof["historical_codec_sha256"] == "9fe67ab00091d1477c71baa3259394d8f2062d9c3deb93bdf3c318f9faaf37bd"
    model = loads(payload.decode())
    assert SCHEMA_VERSION >= 5
    assert all(getattr(model, field) == () for field in WORK_FIELDS)
    assert dumps(model).encode() == payload
    assert dumps(model, schema_version=1).encode() == payload
    # This additionally guards changes to the current native-handle fixture.
    assert dumps(resource_execution_program(native_handles=True)[1]).encode() == payload


def test_explicit_v2_accepts_empty_work_tables_without_inventing_work_evidence():
    model = resource_execution_program(activations=1)[1]
    default = to_dict(model)
    explicit = to_dict(model, schema_version=2)
    assert default["schema_version"] == 1
    assert not (set(WORK_FIELDS) & set(_fields(default)))
    assert explicit["schema_version"] == 2
    assert all(_fields(explicit)[field] == [] for field in WORK_FIELDS)
    assert from_dict(explicit) == model
    assert dumps(from_dict(explicit), schema_version=2) == dumps(model, schema_version=2)
    assert dumps(from_dict(explicit)) == dumps(model)


@pytest.mark.parametrize("field", WORK_FIELDS)
def test_each_new_table_alone_selects_v2_and_cannot_be_forced_into_v1(queued, field):
    # Deliberately isolate one table: this is a capability/record contract,
    # not a claim that the isolated foreign references form a valid graph.
    model = replace(queued, **{name: getattr(queued, name) if name == field else ()
                              for name in WORK_FIELDS})
    assert getattr(model, field)
    assert to_dict(model)["schema_version"] == 2
    assert loads(dumps(model)) == model
    with pytest.raises(ValueError, match="work capability"):
        dumps(model, schema_version=1)


@pytest.mark.parametrize("options", [
    {"retained": "handle"}, {"retained": "allocation"},
    {"retained": "materialization"},
    {"queued": True, "two_tickets": True},
    {"kind": WorkOutcomeKind.CANCELLED, "quiescent": False},
])
def test_deep_work_scheduling_retention_and_outcome_variants_roundtrip(options):
    _, model, _ = ordinary_work_execution(**options)
    restored = loads(dumps(model))
    assert restored == model
    assert type(restored.submissions[0].scheduling) is (Queued if options.get("queued") else DirectExecution)
    assert type(restored.outcomes[0].kind) is WorkOutcomeKind
    assert dumps(restored) == dumps(model)
    assert type(restored.retentions[0].target) is type(model.retentions[0].target)


@pytest.mark.parametrize("raised", (False, True))
def test_invoke_completion_frontier_keeps_typed_result_indices_and_original_formal(raised):
    _, model, _ = invoke_work_execution(raised=raised, queued=True)
    restored = loads(dumps(model))
    assert restored == model
    effect, = restored.submissions[0].effects
    assert type(effect) is InvokeBoundaryStateEffect
    assert effect.post.successor_index == int(raised)
    assert effect.post.formal == model.submissions[0].effects[0].post.formal
    assert restored.outcomes[0].kind is (WorkOutcomeKind.FAILED if raised else WorkOutcomeKind.COMPLETED)


def test_explicit_gaps_external_origin_and_protocol_result_variants_are_not_empty_evidence(queued):
    point = queued.activations[0].entry
    gap = Unresolved("not captured", point)
    first = queued.submissions[0]
    for scheduling in (DirectExecution(gap, first.source), gap):
        submission = replace(first, origin=ExternalWorkSource(point, first.source),
                             executor=gap, scheduling=scheduling, retention=gap)
        for result in (queued.values[0].id, first.protocol, gap):
            outcome = replace(queued.outcomes[0], protocol_result=result, quiescence=gap)
            model = replace(queued, submissions=(submission,), outcomes=(outcome,))
            assert loads(dumps(model)) == model

    _, model, _ = invoke_work_execution(raised=True)
    original = model.submissions[0].effects[0]
    effect = replace(original, post=gap)
    model = replace(model, submissions=(replace(model.submissions[0], effects=(effect,)),),
                    outcomes=(replace(model.outcomes[0], effect_frontier=(effect,)),))
    assert type(loads(dumps(model)).submissions[0].effects[0].post) is Unresolved


@pytest.mark.parametrize("field", WORK_FIELDS)
def test_v1_rejects_even_empty_new_fields_and_v2_requires_every_new_table(queued, field):
    v1 = json.loads((FIXTURES / "execution_v1_frozen.json").read_text())
    _fields(v1)[field] = []
    with pytest.raises(ValueError, match="fields"):
        from_dict(v1)
    v2 = to_dict(queued)
    del _fields(v2)[field]
    with pytest.raises(ValueError, match="fields"):
        from_dict(v2)


def test_v1_cannot_launder_a_known_new_tag_through_an_old_same_concept_union(queued):
    document = json.loads((FIXTURES / "execution_v1_frozen.json").read_text())
    _fields(document)["resources"][0]["fields"]["origin"] = deepcopy(
        _fields(to_dict(queued))["submissions"][0]["fields"]["origin"])
    with pytest.raises(ValueError, match="unknown type tag"):
        from_dict(document)


@pytest.mark.parametrize("mutation", [
    "extra-proof", "raw-outcome", "wrong-union", "bool-index", "wrong-work-id",
    "missing-empty-field", "resource-instance-as-queue-access",
])
def test_v2_nested_wire_is_strict_for_work_variants_and_original_id_namespaces(queued, mutation):
    document = to_dict(queued)
    fields = _fields(document)
    submission = fields["submissions"][0]["fields"]
    if mutation == "extra-proof":
        submission["verified"] = True
    elif mutation == "raw-outcome":
        fields["outcomes"][0]["fields"]["kind"] = "COMPLETED"
    elif mutation == "wrong-union":
        submission["origin"] = deepcopy(submission["scheduling"])
    elif mutation == "bool-index":
        submission["effects"][0]["fields"]["index"] = True
    elif mutation == "wrong-work-id":
        submission["id"]["kind"] = "exec_operation_occurrence"
    elif mutation == "missing-empty-field":
        del submission["dependencies"]
    else:
        # QueuePrefix owns a queue *instance*, whereas Queued owns the access.
        submission["scheduling"]["fields"]["queue_access"] = deepcopy(
            fields["queue_prefixes"][0]["fields"]["queue"])
    with pytest.raises(ValueError):
        from_dict(document)


@pytest.mark.parametrize("mutation", ("false-like-table", "nested-index", "nested-artifact"))
def test_encoder_rechecks_mutation_before_capability_omission_or_nested_encoding(queued, mutation):
    model = deepcopy(queued)
    if mutation == "false-like-table":
        model = resource_execution_program(activations=1)[1]
        object.__setattr__(model, "submissions", [])
    elif mutation == "nested-index":
        object.__setattr__(model.submissions[0].effects[0], "index", True)
    else:
        object.__setattr__(model.retentions[0].target.artifact, "size_bytes", True)
    with pytest.raises(ValueError):
        dumps(model)


@pytest.mark.parametrize("version", (True, 0, 3, "2", 4, 5, 6, 7, 8, 9))
def test_schema_versions_are_exact_supported_integers(queued, version):
    if type(version) is int and version in (3, 4, 5, 6, 7, 8):
        # Preserve old case identities as their versions become supported;
        # an explicit newer version with empty capability adds no evidence.
        assert loads(dumps(queued, schema_version=version)) == queued
        return
    with pytest.raises(ValueError, match="schema_version"):
        dumps(queued, schema_version=version)
    document = to_dict(queued)
    document["schema_version"] = version
    with pytest.raises(ValueError, match="schema_version"):
        from_dict(document)
