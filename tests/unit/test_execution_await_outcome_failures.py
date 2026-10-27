"""D5 joins source-owned await failures to exact captured call occurrences."""

import pytest

from scar.ir.execution.coordinates import OperationOccurrence, UseOccurrence, ValueOccurrence
from scar.ir.execution.query import ExecutionIndex
from scar.ir.program.model import CompletionResult
from scar.ir.program.ids import OperationID
from scar.ir.program.protocols import HostTerminal
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_await_outcome_failure_graphs import (
    await_outcome_failure_execution,
)


_STAGES = (
    ("lookup_raise", "LOOKUP", "await.general.helper.lookup"),
    ("method_call_raise", "METHOD_CALL", "await.general.helper.call"),
    ("qualification_reject", "QUALIFICATION_REJECT", "await.general.helper.qualify.branch"),
)


def _stage_name(value):
    return getattr(value, "value", value)


def _static_definition(path):
    definition = path["definition"]
    assert type(definition) is dict
    return definition


def _paths(view, source):
    rows = []
    for item in view["failure_paths"]:
        for occurrence in item["occurrences"]:
            if occurrence["source"] == source:
                rows.append({**item, **occurrence, "definition": item["definition"],
                             "static_item": item})
    return tuple(rows)


def _stage_path(view, source, stage):
    matches = tuple(path for path in _paths(view, source)
        if _stage_name(_static_definition(path)["stage"]) == stage)
    assert len(matches) == 1
    return matches[0]


def _parent_raise_values(program, model, details):
    """Return this Get R edge's actual packet and state landing values."""
    get_occurrence_id = details["parent_operations"][details["get"].id]
    get_occurrence, = tuple(row for row in model.operations
                            if row.id == get_occurrence_id)
    transfer, = tuple(row for row in model.transfers if row.operation == get_occurrence.id)
    assert transfer.successor_index == 1
    edge = details["get"].terminator.successors[1]
    landing = next(block for region in program.regions for block in region.blocks
                   if block.id == edge.block)
    landing_position = next(position for position, argument in enumerate(edge.arguments)
                            if type(argument) is CompletionResult and argument.index == 0)
    packet_formal = landing.arguments[landing_position]
    packet_value, = tuple(row for row in model.values
        if row.origin == transfer.target and row.value == packet_formal)

    state_values = {}
    for position, argument in enumerate(edge.arguments):
        if type(argument) is CompletionResult:
            slot = argument.index
            if slot == 0:
                continue
            formal = landing.arguments[position]
            value, = tuple(row for row in model.values
                if row.origin == transfer.target and row.value == formal)
            state_values[slot] = value
    return get_occurrence, packet_value, state_values


def _operation_occurrence(model, operation_id):
    matches = tuple(row for row in model.operations if row.id == operation_id)
    assert len(matches) == 1
    return matches[0]


def _terminal_state_values(model, occurrence, operation, slots):
    result = {}
    for slot in slots:
        use_id = operation.terminator.values[slot]
        use, = tuple(row for row in model.uses
            if row.operation == occurrence.id and row.use == use_id)
        value, = tuple(row for row in model.values if row.id == use.value)
        result[slot] = value
    return result


def _dynamic_terminal(path, terminal_id):
    matches = tuple(row for row in path["terminals"]
        if _static_definition(row)["terminal"] == HostTerminal(terminal_id))
    assert len(matches) == 1
    return matches[0]


def _consumer_terminal(terminal, host):
    matches = []
    for row in terminal["consumers"]:
        definition = row.get("definition", {})
        actual = definition.get("actual") if type(definition) is dict else None
        if actual == host or row.get("actual") == host or row.get("target") == host:
            matches.append(row)
    assert len(matches) == 1
    return matches[0]


def _static_await(graph, scope):
    return ProgramIndex(graph).protocol_obligations(scope, budget=65536)[
        "connections"]["families"]["await"]


def _assert_parent_raise_terminal(terminal, *, operation, packet_value,
                                  parent_packet_value, expected_state_sources,
                                  expected_state_targets):
    assert type(terminal["operation"]) is OperationOccurrence
    assert terminal["operation"] == operation
    assert type(terminal["packet_use"]) is UseOccurrence
    assert type(terminal["packet_value"]) is ValueOccurrence
    assert terminal["packet_value"] == packet_value
    assert type(terminal["parent_value"]) is ValueOccurrence
    assert terminal["parent_value"] == parent_packet_value
    assert terminal["binding"]["match"] is True

    slots = {}
    for row in terminal["states"]:
        definition = row["definition"]
        slot = definition["slot"]
        assert type(row["source"]) is ValueOccurrence
        assert type(row["target"]) is ValueOccurrence
        assert row["source"] == expected_state_sources[slot]
        assert row["target"] == expected_state_targets[slot]
        assert row["binding"]["match"] is True
        slots[slot] = row
    assert set(slots) == set(expected_state_sources) == set(expected_state_targets)


@pytest.mark.parametrize(("failure_stage", "selected_stage", "stage_operation"), _STAGES)
def test_expanded_failure_uses_exact_helper_completion_parent_raise_and_consumers(
        failure_stage, selected_stage, stage_operation):
    program, model, details = await_outcome_failure_execution(failure_stage)
    require_valid(program)
    index = ExecutionIndex(model, program)
    source, parent_packet, parent_states = _parent_raise_values(program, model, details)
    view = index.await_body_links(details["acquisition_scope"], budget=65536)
    assert view["source_runtime_verified"] is False
    assert view["runtime_identity_verified"] is False
    assert view["transformation_authorized"] is False

    # The static D4 paths remain the denominator of the occurrence join.
    static = _static_await(program, details["acquisition_scope"])
    static_keys = {row["key"] for row in static["failure_paths"]}
    dynamic = _paths(view, source)
    assert { _static_definition(row)["key"] for row in dynamic } == static_keys

    own = _stage_path(view, source, "ACQUISITION_RAISE")
    assert own["stage"] == source
    assert own["source"] == source
    own_terminal = _dynamic_terminal(own, details["get_failure"].id)
    host_occurrence = _operation_occurrence(
        model, details["parent_operations"][details["get_failure"].id])
    host_use_id = details["get_failure"].terminator.values[0]
    host_use, = tuple(row for row in model.uses
        if row.operation == host_occurrence.id and row.use == host_use_id)
    host_packet, = tuple(row for row in model.values if row.id == host_use.value)
    _assert_parent_raise_terminal(own_terminal, operation=host_occurrence,
        packet_value=host_packet, parent_packet_value=parent_packet,
        expected_state_sources=parent_states,
        expected_state_targets=_terminal_state_values(model, host_occurrence,
            details["get_failure"], parent_states))
    own_host_consumer = _consumer_terminal(own_terminal, HostTerminal(details["get_failure"].id))
    assert own_host_consumer["operation"] == host_occurrence
    assert own_host_consumer["binding"]["match"] is True
    assert model.body_drive_executions == ()

    selected = _stage_path(view, source, selected_stage)
    helper_operation = _operation_occurrence(
        model, details["helper_operations"][OperationID(stage_operation)])
    assert selected["source"] == source
    assert selected["stage"] == helper_operation
    assert selected["selected"] is True
    call_chain = selected["call_chain"]
    assert len(call_chain) == 1
    association = call_chain[0].get("association", call_chain[0])
    assert association == details["call_activation"]
    helper_completion_id = details["helper_operations"][details["failure_terminal"].id]
    helper_completion = _operation_occurrence(model, helper_completion_id)
    assert association.completion == helper_completion.id

    expected_prefix = {
        "lookup_raise": (),
        "method_call_raise": ((details["helper_lookup"].id, 0),),
        "qualification_reject": ((details["helper_lookup"].id, 0),
                                  (details["helper_call"].id, 0)),
    }[failure_stage]
    prefix = {(row["edge"].operation, row["edge"].successor_index): row
              for row in selected["prefix"]}
    assert set(prefix) == set(expected_prefix)
    for edge, row in prefix.items():
        assert row["selected"] is True
        assert row["occurrence"].id == details["helper_operations"][edge[0]]
        transfer = next(item for item in model.transfers
                        if item.operation == row["occurrence"].id)
        assert transfer.successor_index == edge[1]

    expanded_terminal = _dynamic_terminal(selected, details["failure_terminal"].id)
    helper_packet_use_id = details["failure_terminal"].terminator.values[0]
    helper_use, = tuple(row for row in model.uses
        if row.operation == helper_completion.id and row.use == helper_packet_use_id)
    helper_packet, = tuple(row for row in model.values if row.id == helper_use.value)
    _assert_parent_raise_terminal(expanded_terminal, operation=helper_completion,
        packet_value=helper_packet, parent_packet_value=parent_packet,
        expected_state_sources=_terminal_state_values(model, helper_completion,
            details["failure_terminal"], parent_states),
        expected_state_targets=parent_states)
    host_consumer = _consumer_terminal(
        expanded_terminal, HostTerminal(details["get_failure"].id))
    assert host_consumer["operation"] == host_occurrence
    assert host_consumer["binding"]["match"] is True

    other_stages = {"LOOKUP", "METHOD_CALL", "QUALIFICATION_REJECT"} - {selected_stage}
    for stage in other_stages:
        other = _stage_path(view, source, stage)
        assert other["status"] == "NOT_APPLICABLE"
        assert other["stage"] is None


def test_parent_own_raise_is_kept_without_a_call_activation_or_body_advance():
    program, model, details = await_outcome_failure_execution(
        "qualification_reject", capture_call=False)
    require_valid(program)
    index = ExecutionIndex(model, program)
    source, parent_packet, parent_states = _parent_raise_values(program, model, details)
    view = index.await_body_links(details["acquisition_scope"], budget=65536)

    own = _stage_path(view, source, "ACQUISITION_RAISE")
    assert own["source"] == source
    assert own["stage"] == source
    terminal = _dynamic_terminal(own, details["get_failure"].id)
    host_occurrence = _operation_occurrence(
        model, details["parent_operations"][details["get_failure"].id])
    host_use_id = details["get_failure"].terminator.values[0]
    host_use, = tuple(row for row in model.uses
        if row.operation == host_occurrence.id and row.use == host_use_id)
    host_packet, = tuple(row for row in model.values if row.id == host_use.value)
    _assert_parent_raise_terminal(terminal, operation=host_occurrence,
        packet_value=host_packet, parent_packet_value=parent_packet,
        expected_state_sources=parent_states,
        expected_state_targets=_terminal_state_values(model, host_occurrence,
            details["get_failure"], parent_states))
    assert model.call_activations == ()
    assert model.body_drive_executions == ()

    expanded = _stage_path(view, source, "QUALIFICATION_REJECT")
    assert expanded["stage"] is None
    assert expanded["call_chain"] == ()
    assert expanded["status"] == "PARTIAL"
    assert expanded["gaps"]
    assert any("call" in str(gap).lower() or "activation" in str(gap).lower()
               for gap in expanded["gaps"])


def test_deleted_source_raise_row_and_receipt_do_not_delete_its_dynamic_obligation():
    program, model, details = await_outcome_failure_execution(
        "qualification_reject", omit_source_raise_row=True)
    require_valid(program)
    static = _static_await(program, details["acquisition_scope"])
    index = ExecutionIndex(model, program)
    source, parent_packet, parent_states = _parent_raise_values(program, model, details)
    view = index.await_body_links(details["acquisition_scope"], budget=65536)

    own = _stage_path(view, source, "ACQUISITION_RAISE")
    definition = _static_definition(own)
    assert definition["acquisition"] is None
    assert "await_failure_source_row_missing" in definition["gaps"]
    assert own["source"] == source
    assert own["status"] != "DECLARED"
    # The declaration was removed, but its source-first path key remains.
    assert definition["key"] in {row["key"] for row in static["failure_paths"]}
    assert any(_static_definition(path)["key"] == definition["key"]
        for path in _paths(view, source))
    assert model.body_drive_executions == ()
    assert parent_packet is not None and parent_states


def test_budget_cut_keeps_static_failure_denominator_and_cursor():
    program, model, details = await_outcome_failure_execution("qualification_reject")
    require_valid(program)
    static = _static_await(program, details["acquisition_scope"])
    index = ExecutionIndex(model, program)
    view = index.await_body_links(details["acquisition_scope"], budget=1)

    inventory = view["failure_path_inventory"]
    assert inventory["enumerated_count"] == len(static["failure_paths"])
    assert inventory["known_inventory_complete"] is False
    assert inventory["jobs_total"] is None
    assert inventory["pending_count"] is None
    assert inventory["cursor"] is not None
    assert len(view["failure_paths"]) == len(static["failure_paths"])
    assert view["status"] == "PARTIAL"
    assert view["source_runtime_verified"] is False
    assert view["transformation_authorized"] is False
