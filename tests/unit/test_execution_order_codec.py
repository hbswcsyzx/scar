"""Strict v3 order wire, with independently frozen v1/v2 compatibility.

The order helper below is a constructor/serialization example. It does not
claim source/runtime correspondence, FIFO applicability or graph-level order.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from scar.ir.execution.codec import SCHEMA_VERSION, dumps, from_dict, loads, to_dict
from scar.ir.execution.common import Unresolved
from scar.ir.execution.coordinates import OccurrencePhase, OccurrencePoint, UseRef
from scar.ir.execution.ids import (
    EventRecordID, QueueOrderProfileID, QueueWaitID, ResourceInstanceID,
)
from scar.ir.execution.order import EventRecord, QueueOrderProfile, QueueWait, RecordedPrefix
from scar.ir.execution.resources import ImportedAt, ProcessRealm, ResourceInstance
from scar.ir.execution.work import InvokeBoundaryStateEffect, QueueStart
from scar.ir.program.providers import ProviderFactReference
from scar.ir.program.resources import ResourceKind, ResourceRole
from tests.fixtures.execution_resource_graphs import resource_execution_program
from tests.fixtures.execution_work_graphs import ordinary_work_execution, invoke_work_execution


ORDER_FIELDS = ("queue_order_profiles", "event_records", "queue_waits")
FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture(scope="module")
def ordered():
    program, model, _ = ordinary_work_execution(queued=True, two_tickets=True)
    first, second = model.submissions
    initial = model.activations[0].entry
    gap = Unresolved("physical relation not collected", initial)
    source = model.runs[0].source
    protocol = ProviderFactReference(model.snapshot.artifact, "declared-order-rule")
    queue = model.queue_prefixes[0].queue
    event = ResourceInstance(ResourceInstanceID("order.event"), ResourceKind.OTHER,
        ResourceRole.OPAQUE_RESOURCE, ProcessRealm(model.processes[0].id), ImportedAt(initial), source)
    profile = QueueOrderProfile(QueueOrderProfileID("order.profile"), queue,
                                model.queue_prefixes[-1].id, protocol, source)
    records = tuple(EventRecord(EventRecordID("record." + str(index)), event.id, gap, gap,
        RecordedPrefix(queue, prefix.id), submission.effects[0],
        OccurrencePoint(submission.origin.operation, OccurrencePhase.AFTER), protocol, source)
        for index, (prefix, submission) in enumerate(zip(model.queue_prefixes, model.submissions, strict=True)))
    core = next(row for row in program.operations if row.id == next(
        row.operation for row in model.operations if row.id == second.origin.operation))
    wait = QueueWait(QueueWaitID("wait.r1"), second.id, records[0].id, gap,
        UseRef(second.origin.operation, core.accesses[0].before),
        OccurrencePoint(second.origin.operation, OccurrencePhase.BEFORE), protocol, source)
    return replace(model, resources=(*model.resources, event),
        queue_order_profiles=(profile,), event_records=records, queue_waits=(wait,))


def _fields(document):
    return document["model"]["fields"]


def test_immutable_v2_native_work_fixture_is_independent_and_byte_exact():
    payload = (FIXTURES / "execution_v2_frozen.json").read_bytes()
    proof = json.loads((FIXTURES / "execution_v2_frozen.proof.json").read_text())
    assert proof["source_revision"] == "bb1b402b498e9ce80a701658a59c1471e8ec32ce"
    assert proof["codec_schema_version"] == proof["wire_schema_version"] == 2
    assert proof["payload_sha256"] == hashlib.sha256(payload).hexdigest()
    assert proof["payload_size_bytes"] == len(payload)
    assert proof["historical_source_hashes"]["scar/ir/execution/codec.py"] == (
        "b9df39823e351e855702a8bdb324cb637da1431fd55b5a5bc1a3c3310e0fd890")
    model = loads(payload.decode())
    assert SCHEMA_VERSION == 3
    assert all(getattr(model, field) == () for field in ORDER_FIELDS)
    assert dumps(model).encode() == payload
    assert dumps(model, schema_version=2).encode() == payload
    current = ordinary_work_execution(queued=True, two_tickets=True, retained="allocation")[1]
    assert dumps(current).encode() == payload
    old = (FIXTURES / "execution_v1_frozen.json").read_bytes()
    assert dumps(loads(old.decode())).encode() == old


def test_order_roundtrip_preserves_exact_generations_and_wait_does_not_select_latest(ordered):
    restored = loads(dumps(ordered))
    assert restored == ordered
    assert to_dict(restored)["schema_version"] == 3
    assert restored.event_records[0].event == restored.event_records[1].event
    assert restored.event_records[0].id != restored.event_records[1].id
    assert restored.event_records[0].captured.prefix != restored.event_records[1].captured.prefix
    assert restored.queue_waits[0].record == restored.event_records[0].id
    reversed_records = replace(ordered, event_records=tuple(reversed(ordered.event_records)))
    assert loads(dumps(reversed_records)).queue_waits[0].record == ordered.event_records[0].id


@pytest.mark.parametrize("field", ORDER_FIELDS)
def test_each_order_table_alone_selects_v3_and_cannot_be_dropped_on_downgrade(ordered, field):
    model = replace(ordered, **{name: getattr(ordered, name) if name == field else () for name in ORDER_FIELDS})
    assert to_dict(model)["schema_version"] == 3
    assert loads(dumps(model)) == model
    for version in (1, 2):
        with pytest.raises(ValueError, match="order capability"):
            dumps(model, schema_version=version)


@pytest.mark.parametrize("with_work", (False, True))
def test_explicit_v3_empty_order_tables_is_only_a_wire_upgrade(with_work):
    model = (ordinary_work_execution()[1] if with_work else
             resource_execution_program(activations=1)[1])
    default = to_dict(model)
    explicit = to_dict(model, schema_version=3)
    assert default["schema_version"] == (2 if with_work else 1)
    assert all(_fields(explicit)[field] == [] for field in ORDER_FIELDS)
    assert from_dict(explicit) == model
    assert dumps(from_dict(explicit)) == dumps(model)
    assert dumps(from_dict(explicit), schema_version=3) == dumps(model, schema_version=3)


def test_prefix_start_and_unknown_frontier_or_selection_are_explicit_variants(ordered):
    point = ordered.activations[0].entry
    gap = Unresolved("generation not captured", point)
    record = ordered.event_records[0]
    for prefix in (QueueStart(record.source), gap):
        changed = replace(record, captured=RecordedPrefix(record.captured.queue, prefix), generation=gap)
        wait = replace(ordered.queue_waits[0], record=gap, selection=gap)
        model = replace(ordered, event_records=(changed,), queue_waits=(wait,))
        restored = loads(dumps(model))
        assert restored == model
        assert type(restored.event_records[0].captured.prefix) is type(prefix)
        assert type(restored.queue_waits[0].record) is Unresolved


def test_invoke_generation_retains_original_completion_state_mapping(ordered):
    _, invoked, _ = invoke_work_execution(raised=True, queued=True)
    effect = invoked.submissions[0].effects[0]
    model = replace(ordered, event_records=(replace(ordered.event_records[0], generation=effect),))
    restored = loads(dumps(model))
    generation = restored.event_records[0].generation
    assert type(generation) is InvokeBoundaryStateEffect
    assert generation == effect
    assert generation.post.successor_index == 1


@pytest.mark.parametrize("version", (1, 2))
@pytest.mark.parametrize("field", ORDER_FIELDS)
def test_legacy_schema_rejects_even_empty_new_order_fields(version, field):
    document = json.loads((FIXTURES / f"execution_v{version}_frozen.json").read_text())
    _fields(document)[field] = []
    with pytest.raises(ValueError, match="fields"):
        from_dict(document)


@pytest.mark.parametrize("field", ORDER_FIELDS)
def test_v3_requires_all_order_fields_even_if_they_would_be_empty(ordered, field):
    document = to_dict(ordered)
    del _fields(document)[field]
    with pytest.raises(ValueError, match="fields"):
        from_dict(document)


@pytest.mark.parametrize("version", (1, 2))
def test_legacy_closed_vocabulary_rejects_new_order_tag_in_an_old_union(ordered, version):
    document = json.loads((FIXTURES / f"execution_v{version}_frozen.json").read_text())
    _fields(document)["resources"][0]["fields"]["origin"] = deepcopy(
        _fields(to_dict(ordered))["event_records"][0])
    with pytest.raises(ValueError, match="unknown type tag"):
        from_dict(document)


@pytest.mark.parametrize("mutation", [
    "extra-proof", "wrong-record-id", "wrong-queue-id", "wrong-union", "missing-selection",
    "bool-generation-index", "unknown-query-point-tag", "null-record", "raw-generation",
])
def test_v3_order_wire_rejects_tag_id_union_and_field_forgery(ordered, mutation):
    document = to_dict(ordered)
    fields = _fields(document)
    record = fields["event_records"][0]["fields"]
    wait = fields["queue_waits"][0]["fields"]
    if mutation == "extra-proof":
        record["completed"] = True
    elif mutation == "wrong-record-id":
        wait["record"]["$id"] = "scar.ir.execution.ids.ResourceInstanceID"
    elif mutation == "wrong-queue-id":
        fields["queue_order_profiles"][0]["fields"]["queue"] = deepcopy(record["id"])
    elif mutation == "wrong-union":
        record["generation"] = deepcopy(wait["selection"])
    elif mutation == "missing-selection":
        del wait["selection"]
    elif mutation == "bool-generation-index":
        record["generation"]["fields"]["index"] = True
    elif mutation == "unknown-query-point-tag":
        record["marker"] = {"$record":"scar.ir.execution.order.WorkEnd", "fields":{}}
    elif mutation == "null-record":
        wait["record"] = None
    else:
        record["generation"] = "record-1"
    with pytest.raises(ValueError):
        from_dict(document)


@pytest.mark.parametrize("mutation", ("false-like-table", "nested-generation", "nested-source"))
def test_encoder_rechecks_order_records_before_capability_selection(ordered, mutation):
    model = deepcopy(ordered)
    if mutation == "false-like-table":
        model = resource_execution_program(activations=1)[1]
        object.__setattr__(model, "queue_waits", [])
    elif mutation == "nested-generation":
        object.__setattr__(model.event_records[0].generation, "index", True)
    else:
        object.__setattr__(model.event_records[0].protocol.artifact, "size_bytes", True)
    with pytest.raises(ValueError):
        dumps(model)


def test_unknown_versions_remain_rejected_after_adding_v3(ordered):
    for version in (True, 0, 4, "3"):
        with pytest.raises(ValueError, match="schema_version"):
            dumps(ordered, schema_version=version)
        document = to_dict(ordered)
        document["schema_version"] = version
        with pytest.raises(ValueError, match="schema_version"):
            from_dict(document)
