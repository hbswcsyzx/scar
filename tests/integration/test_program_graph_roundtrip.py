"""Strict persisted manual IR, with full validation before and after decoding."""
import json

import pytest

from scar.ir.program.codec import dumps, loads
from scar.ir.program.ids import OperationID, ValueID
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import validate
from tests.fixtures.program_graphs import (
    branch_state_program, loop_state_program, save_payload_program,
    shared_body_calls_program,
)


@pytest.mark.parametrize("build", (
    branch_state_program, loop_state_program, shared_body_calls_program, save_payload_program,
), ids=lambda function: function.__name__)
def test_complete_program_roundtrip_keeps_types_uses_and_state_interfaces(build):
    graph = build()
    payload = dumps(graph)
    recovered = loads(payload)
    assert recovered == graph
    assert validate(recovered) == ()
    assert dumps(recovered) == payload
    before, after = ProgramIndex(graph), ProgramIndex(recovered)
    for value in graph.values:
        assert before.producer(value.id) == after.producer(value.id)
        assert before.consumers(value.id) == after.consumers(value.id)


def test_roundtrip_preserves_two_call_results_instead_of_merging_shared_body():
    index = ProgramIndex(loads(dumps(shared_body_calls_program())))
    assert index.producer(ValueID("call1.result")).operation == OperationID("call1")
    assert index.producer(ValueID("call2.result")).operation == OperationID("call2")
    assert len(index.consumers(ValueID("body.input"))) == 2


def test_loading_revalidates_state_progression_not_only_json_types():
    document = json.loads(dumps(branch_state_program()))
    done = next(item for item in document["operations"] if item["id"]["value"] == "done")
    stale = next(item for item in document["values"] if item["id"]["value"] == "buffer.normal")
    next(item for item in done["uses"] if item["id"]["value"] == "done.buffer")["value"] = stale["id"]
    with pytest.raises(ValueError):
        loads(json.dumps(document))


def test_tuple_registry_duplicate_is_rejected_instead_of_overwritten():
    document = json.loads(dumps(branch_state_program()))
    document["values"].append(document["values"][0])
    with pytest.raises(ValueError):
        loads(json.dumps(document))


@pytest.mark.parametrize("change", ("unknown_field", "wrong_namespace", "duplicate_json_field", "wrong_version"))
def test_wire_data_cannot_add_fields_change_typed_ids_or_shadow_keys(change):
    payload = dumps(save_payload_program())
    document = json.loads(payload)
    if change == "unknown_field":
        document["operations"][0]["proof"] = "PROVEN"
    elif change == "wrong_namespace":
        document["operations"][0]["id"] = document["values"][0]["id"]
    elif change == "duplicate_json_field":
        with pytest.raises(ValueError):
            loads('{"schema": "shadowed",' + payload[1:])
        return
    else:
        document["schema_version"] = True
    with pytest.raises(ValueError):
        loads(json.dumps(document))
