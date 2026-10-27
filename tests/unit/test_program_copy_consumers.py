"""Public copy-consumer inventory over original CALL/INVOKE ports."""
import pytest

from scar.ir.program.ids import BlockID
from scar.ir.program.model import CompletionResult, ExitKind, InvokeLiteralResult
from scar.ir.program.protocols import OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid
from tests.fixtures.program_copy_consumer_graphs import (
    conditional_return_copy_consumer_program, distinct_payload_return_program,
    duplicate_actual_program, duplicate_formal_copy_consumer_program,
    duplicate_return_program, invoke_nr_copy_consumer_program,
    nested_copy_consumer_program, opaque_internal_consumer_program,
    recursive_copy_consumer_program, repeated_copy_consumer_program,
    source_in_shared_callee_program, swapped_shared_callee_program,
    with_incomplete_internal_consumer,
)


def _query(graph, source, *, budget=50000):
    require_valid(graph)
    return ProgramIndex(graph).copy_consumers(source, budget=budget)


def _frames(report):
    return {frame["key"]: frame for frame in report["frames"]}


def _consumer(frame, actual):
    return next((row for row in frame["consumers"] if row["actual"] == actual), None)


def _return(frame, actual):
    return next((row for row in frame["returns"] if row["actual"] == actual), None)


def _no_authority(report):
    assert report["source_runtime_verified"] is False
    assert report["runtime_identity_verified"] is False
    assert report["transformation_authorized"] is False


def test_swapped_two_argument_callers_keep_distinct_frames_and_exact_ordinals():
    graph, details = swapped_shared_callee_program()
    report = _query(graph, details["source"])
    frames = _frames(report)
    first, second = details["calls"]

    assert () in frames
    assert (first,) in frames and (second,) in frames
    first_frame, second_frame = frames[(first,)], frames[(second,)]
    assert first_frame["region"] == second_frame["region"] == details["helper"]

    for frame, call in ((first_frame, first), (second_frame, second)):
        inputs = frame["inputs"]
        assert tuple(item["ordinal"] for item in inputs) == (0, 1, 2)
        assert tuple(item["actual"] for item in inputs) == details["call_actuals"][call]
        assert len(inputs) == 3  # both payload positions and the original state port
        assert all(item["formal"].index == item["ordinal"] for item in inputs)

    left, right = details["inspect_uses"]
    first_left, first_right = _consumer(first_frame, left), _consumer(first_frame, right)
    second_left, second_right = _consumer(second_frame, left), _consumer(second_frame, right)
    assert first_left is not None and first_left["must"] is True
    assert second_right is not None and second_right["must"] is True
    assert first_right is None or first_right["must"] is not True
    assert second_left is None or second_left["must"] is not True
    _no_authority(report)


def test_duplicate_actuals_seed_both_formals_and_keep_distinct_internal_uses():
    graph, details = duplicate_actual_program()
    report = _query(graph, details["source"])
    call, = details["calls"]
    frame = _frames(report)[(call,)]
    inputs = frame["inputs"]

    assert len(inputs) == 3
    assert inputs[0]["actual"] != inputs[1]["actual"]
    operations = {row.id: row for row in graph.operations}
    actual_uses = [next(use for use in operations[call].uses if use.id == item["actual"].use)
                   for item in inputs[:2]]
    assert actual_uses[0].value == actual_uses[1].value
    assert len({inputs[0]["formal"], inputs[1]["formal"]}) == 2

    left, right = details["inspect_uses"]
    assert _consumer(frame, left)["must"] is True
    assert _consumer(frame, right)["must"] is True
    _no_authority(report)


def test_duplicate_return_payload_uses_keep_two_distinct_exit_slots():
    graph, details = duplicate_return_program()
    report = _query(graph, details["source"])
    call, = details["calls"]
    frame = _frames(report)[(call,)]
    first, second, _ = details["helper_return_uses"]
    first_row, second_row = _return(frame, first), _return(frame, second)

    assert first != second
    assert first_row is not None and second_row is not None
    assert first_row["kind"] is ExitKind.NORMAL and first_row["slot"] == 0
    assert second_row["kind"] is ExitKind.NORMAL and second_row["slot"] == 1
    assert first_row["must"] is True and second_row["must"] is True
    _no_authority(report)


def test_distinct_return_payloads_keep_the_original_value_to_slot_mapping():
    graph, details = distinct_payload_return_program()
    report = _query(graph, details["source"])
    call, = details["calls"]
    frame = _frames(report)[(call,)]
    first, second, _ = details["helper_return_uses"]
    first_row, second_row = _return(frame, first), _return(frame, second)

    assert first_row is not None and second_row is not None
    assert first_row["slot"] == 0 and first_row["must"] is True
    assert second_row["slot"] == 1 and second_row["must"] is not True
    _no_authority(report)


def test_nested_calls_have_full_static_frame_keys_and_exact_parent_links():
    graph, details = nested_copy_consumer_program()
    report = _query(graph, details["expected"])
    frames = _frames(report)
    outer, inner = details["calls"]

    assert () in frames
    assert (outer,) in frames
    assert (outer, inner) in frames
    assert frames[(outer, inner)]["parent_call"] == inner
    assert frames[(outer,)]["parent_call"] == outer
    assert report["inventory"]["known_inventory_complete"] is True
    _no_authority(report)


def test_invoke_returns_preserve_exit_kind_result_slot_and_landing_position():
    graph, details = invoke_nr_copy_consumer_program(two_callers=False)
    report = _query(graph, details["source"])
    call = details["callers"]["a"]["operation"].id
    frame = _frames(report)[(call,)]
    returns = frame["returns"]
    normal_reference = details["callers"]["a"]["normal_reference"]
    raise_packet = InvokeLiteralResult(ControlEdgeReference(call, 0), CompletionResult(1))
    normal_row = next(row for row in returns
                      if row["kind"] is ExitKind.NORMAL and row["caller_result"] == normal_reference)
    raise_row = next(row for row in returns
                     if row["kind"] is ExitKind.RAISE and row["caller_result"] == raise_packet)

    assert normal_row["slot"] == 0 and normal_row["landing_position"] == 2
    assert raise_row["slot"] == 1 and raise_row["landing_position"] == 3
    # The helper's RAISE packet is a new protocol value, not a copy of x.
    assert raise_row["must"] is not True
    _no_authority(report)


def test_state_write_is_a_consumer_but_its_new_poststate_is_not_old_copy():
    graph, details = invoke_nr_copy_consumer_program(normal_write=True)
    report = _query(graph, details["world_source"])
    frame = _frames(report)[(details["callers"]["a"]["operation"].id,)]
    writer = details["normal_writer"]
    writer_use = OwnedUse(writer.id, writer.uses[0].id)
    state_consumer = _consumer(frame, writer_use)

    assert state_consumer is not None and state_consumer["must"] is True
    return_state = _return(frame, OwnedUse(details["normal_return"].id,
                                          details["normal_return"].uses[1].id))
    assert return_state is not None
    assert return_state["slot"] == 1
    assert return_state["must"] is not True
    _no_authority(report)


def test_mixed_return_paths_keep_both_original_exit_uses_and_conditionality():
    graph, details = conditional_return_copy_consumer_program()
    report = _query(graph, details["expected"])
    frame = _frames(report)[(details["calls"][0],)]
    expected_uses = {
        OwnedUse(operation.id, operation.uses[0].id)
        for operation in graph.operations if operation.id in details["terminals"]
    }
    rows = [row for row in frame["returns"] if row["actual"] in expected_uses]

    assert {row["actual"] for row in rows} == expected_uses
    assert {row["slot"] for row in rows} == {0}
    assert any(row["must"] is True for row in rows)
    assert any(row["must"] is not True for row in rows)
    _no_authority(report)


@pytest.mark.parametrize("stale", (False, True))
def test_loop_reexecution_does_not_turn_carried_previous_result_into_current_copy(stale):
    graph, details = repeated_copy_consumer_program(stale=stale)
    report = _query(graph, details["expected"])
    target = details["actual"]
    rows = [row for frame in report["frames"] for row in frame["consumers"]
            if row["actual"] == target]

    if stale:
        assert not rows or all(row["must"] is not True for row in rows)
    else:
        assert rows and any(row["must"] is True for row in rows)
    _no_authority(report)


def test_recursive_call_is_kept_as_an_unresolved_original_boundary():
    graph, details = recursive_copy_consumer_program()
    report = _query(graph, details["expected"])
    recursive_call = details["calls"][1]
    assert any(call["operation"] == recursive_call
               for frame in report["frames"] for call in frame["calls"])
    assert report["inventory"]["known_inventory_complete"] is False
    assert report["gaps"] or report["cursor"] is not None
    _no_authority(report)


def test_incomplete_internal_effects_keep_visible_copy_but_not_closed_inventory():
    graph, details = opaque_internal_consumer_program()
    report = _query(graph, details["source"])
    frame = _frames(report)[(details["calls"][0],)]
    visible = _consumer(frame, details["inspect_uses"][0])

    assert visible is not None and visible["must"] is True
    assert report["inventory"]["known_inventory_complete"] is False
    assert report["gaps"]
    _no_authority(report)


def test_source_inside_shared_callee_preserves_all_original_caller_boundaries():
    graph, details = source_in_shared_callee_program()
    source = details["helper_sources"][0]
    report = _query(graph, source)
    root_frame = _frames(report)[()]

    assert root_frame["region"] != graph.root
    assert len(root_frame["boundaries"]) == 2
    assert report["inventory"]["known_inventory_complete"] is False
    assert report["gaps"] or report["cursor"] is not None
    _no_authority(report)


def test_budget_cursor_and_detached_results_preserve_pending_inventory():
    graph, details = swapped_shared_callee_program()
    limited = _query(graph, details["source"], budget=1)
    assert limited["inventory"]["known_inventory_complete"] is False
    assert limited["cursor"] is not None
    assert limited["frames"]
    assert limited["inventory"]["frames_total"] is None

    full = _query(graph, details["source"])
    original_keys = tuple(frame["key"] for frame in full["frames"])
    full["frames"] = ()
    again = _query(graph, details["source"])
    assert tuple(frame["key"] for frame in again["frames"]) == original_keys
    _no_authority(again)

