"""Original source queries must interpret the selected pending payload."""
import pytest

from scar.ir.program.control import PendingPayload
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_pending_payload_graphs import (
    pending_payload_helper_program,
    pending_payload_loop_program,
    pending_payload_program,
)


def _index(graph):
    require_valid(graph)
    return ProgramIndex(graph)


def _unproved(report):
    assert report["source_runtime_verified"] is False
    assert report["native_applicability_verified"] is False
    assert report["runtime_identity_verified"] is False
    assert report["transformation_authorized"] is False


def test_original_payload_source_survives_pending_merge_and_real_dispatch_projection():
    graph, details = pending_payload_program()
    require_valid(graph)
    assert type(details["projection"]) is PendingPayload
    assert len(details["definitions"]) == 2
    report = ProgramIndex(graph).source_binding(details["expected"], details["actual"])
    assert report["match"] is True
    assert report["native_applicability_verified"] is False
    assert report["runtime_identity_verified"] is False


@pytest.mark.parametrize("kind", ("return", "raise"))
def test_same_port_payloads_are_all_required_and_each_original_guard_is_separate(kind):
    graph, details = pending_payload_program(mixed=True, kind=kind)
    index = _index(graph)
    context = ConnectionContext(graph, index=index)
    unconditional = context.bind(details["expected"], details["actual"])
    a = context.bind(details["expected"], details["actual"], guard=details["guard_a"])
    b = context.bind(details["expected"], details["actual"], guard=details["guard_b"])
    assert unconditional["match"] is not True, unconditional
    assert a["match"] is True, a
    assert b["match"] is False, b
    # Querying A again after B cannot reuse B's selected token/cache facts.
    assert context.bind(details["expected"], details["actual"],
                        guard=details["guard_a"])["match"] is True


@pytest.mark.parametrize("kind", ("return", "raise"))
def test_other_ports_payload_does_not_poison_the_selected_dispatch_case(kind):
    graph, details = pending_payload_program(mixed=True, different_ports=True, kind=kind)
    assert len(details["dispatch"].terminator.successors) == 2
    assert len({definition.port for definition in details["definitions"]}) == 2
    index = _index(graph)
    report = index.source_binding(details["expected"], details["actual"])
    assert report["match"] is True, report
    _unproved(report)
    # B carries Q: the selected P consumer is unreachable under that branch.
    # The absence of a P payload must not become an empty AND proof.
    excluded = index.source_binding(details["expected"], details["actual"],
                                     guard=details["guard_b"])
    assert excluded["match"] is not True, excluded


@pytest.mark.parametrize("kind", ("return", "raise"))
def test_input_origins_of_selected_port_never_imports_another_ports_payload(kind):
    graph, details = pending_payload_program(mixed=True, different_ports=True, kind=kind)
    view = _index(graph).input_origins(details["actual"].operation, details["actual"].use)
    assert view["recipes"]
    assert {recipe["leaf"].id for recipe in view["recipes"]} == {details["branch"].uses[1].value}
    witnesses = tuple(step for recipe in view["recipes"] for step in recipe["path"]
                      if step["kind"] == "PENDING_PAYLOAD_PROJECTION")
    assert witnesses
    selected_port = details["dispatch"].terminator.successors[0].port
    assert {step["port"] for step in witnesses} == {selected_port}
    assert {step["pending_definition"].value for step in witnesses} == {
        details["constructors"][0].results[0]}
    assert all(step["selector"] == details["selector"] for step in witnesses)
    assert view["runtime_identity_verified"] is False


@pytest.mark.parametrize("active,dead,expected", (("good", "wrong", True), ("wrong", "good", False)))
def test_unused_constructor_neither_rescues_nor_poisons_the_actual_selected_token(active, dead, expected):
    graph, details = pending_payload_program(active=active, dead=dead)
    assert len(details["dead"]) == 2
    assert len(details["definitions"]) == 4
    selector_values = {use.value for use in details["dispatch"].uses}
    assert all(operation.results[0] not in selector_values for operation in details["dead"])
    report = _index(graph).source_binding(details["expected"], details["actual"])
    assert report["match"] is expected, report
    _unproved(report)


@pytest.mark.parametrize("mixed", (False, True))
def test_original_input_origins_retains_pack_projection_witnesses_and_every_payload_leaf(mixed):
    graph, details = pending_payload_program(mixed=mixed)
    view = _index(graph).input_origins(details["actual"].operation, details["actual"].use)
    recipes = view["recipes"]
    assert recipes
    expected_leaves = {details["branch"].uses[1].value, details["branch"].uses[3].value}
    assert {recipe["leaf"].id for recipe in recipes} == expected_leaves
    steps = tuple(step for recipe in recipes for step in recipe["path"])
    witnesses = tuple(step for step in steps if step["kind"] == "PENDING_PAYLOAD_PROJECTION")
    assert witnesses
    assert any(step["kind"] == "CFG_COPY" for step in steps)
    assert {step["pending_definition"].value for step in witnesses} == {
        definition.value for definition in graph.pending_completions}
    constructors = {operation.id: operation for operation in details["constructors"]}
    for step in witnesses:
        definition = step["pending_definition"]
        assert step["selector"] == details["selector"]
        assert step["port"] == definition.port
        assert step["argument_index"] == 0
        assert step["formal"].id == details["terminal"].uses[0].value
        constructor = step["constructor"]
        assert constructor is constructors[constructor.id]
        assert constructor.results == (definition.value,)
        assert step["payload"].operation == constructor.id
        assert step["payload"].use == definition.payload
        assert step["token_match"] in (True, False, None)
    assert all(type(recipe["origin"]) is not PendingPayload for recipe in recipes)
    assert view["runtime_identity_verified"] is False


def test_bare_projection_marker_is_not_an_owned_independent_source():
    graph, details = pending_payload_program()
    with pytest.raises(TypeError):
        _index(graph).source_binding(PendingPayload(), details["actual"])


@pytest.mark.parametrize("stale", (False, True))
def test_reexecuted_source_and_constructor_do_not_make_a_carried_old_token_current(stale):
    graph, details = pending_payload_loop_program(stale=stale)
    report = _index(graph).source_binding(details["expected"], details["actual"], budget=50000)
    if stale:
        assert report["match"] is not True, report
    else:
        assert report["match"] is True, report
    _unproved(report)


def test_unseeded_pending_cycle_is_rejected_by_the_existing_core_before_any_source_query():
    graph, details = pending_payload_loop_program(unseeded=True)
    assert not graph.pending_completions
    assert details["unseeded"] is not None
    assert "pending_origin" in {issue.code for issue in validate(graph)}


def test_reexecuting_a_constructor_does_not_erase_the_payload_of_an_old_carried_token():
    graph, details = pending_payload_loop_program(stale=True, fresh_source=False)
    report = _index(graph).source_binding(details["expected"], details["actual"], budget=50000)
    assert report["match"] is True, report
    _unproved(report)


@pytest.mark.parametrize("wrong_actual", (False, True))
def test_projected_payload_returns_and_then_enters_the_actual_second_known_helper(wrong_actual):
    graph, details = pending_payload_helper_program(wrong_actual=wrong_actual)
    index = _index(graph)
    first, second = details["first_call"], details["second_call"]
    assert first.callee != second.callee
    report = index.source_binding(details["expected"], details["actual"], budget=50000)
    assert report["match"] is (False if wrong_actual else True), report
    _unproved(report)


def test_projection_budget_exhaustion_preserves_unknown_and_a_cursor():
    graph, details = pending_payload_program(mixed=True)
    report = _index(graph).source_binding(details["expected"], details["actual"], budget=1)
    assert report["match"] is None
    assert report["budget"]["truncated"] is True
    assert report["budget"]["used"] <= 1
    assert report["cursor"]
    _unproved(report)


def test_projection_input_origins_budget_cannot_turn_missing_payload_routes_into_an_empty_success():
    graph, details = pending_payload_program(mixed=True)
    view = _index(graph).input_origins(details["actual"].operation, details["actual"].use, budget=1)
    assert view["cursor"]
    assert view["status"] != "DERIVED"
    assert view["runtime_identity_verified"] is False
