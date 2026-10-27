"""Cross-layer connection obligations retain independent route denominators."""
from dataclasses import replace

import pytest

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.model import BlockArgument
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocol_connection_validation import common_connections
from scar.ir.program.protocol_connections import ProtocolOperationRef, RawOperandSource
from scar.ir.program.protocols import OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import validate
from tests.fixtures.program_connection_graphs import helper_diamond_program, merged_connection_program, nested_consumer_program
from tests.fixtures.program_request_helper_graphs import helper_request_program


def _view(graph, budget=100000):
    index = ProgramIndex(graph)
    return common_connections(ConnectionContext(graph, index=index, budget=ValidityBudget(budget)))


def test_two_incoming_tuples_remain_valid_through_a_later_jump():
    graph, _ = merged_connection_program()
    report = _view(graph)
    assert report["issues"] == ()
    inputs, = report["inputs"]
    assert inputs["status"] == "DECLARED"
    assert len(inputs["cases"]) == 2
    assert all(case["joint"] for case in inputs["cases"])
    assert all(binding["match"] is True for case in inputs["cases"] for binding in case["inputs"])
    assert report["source_runtime_verified"] is report["transformation_authorized"] is False


def test_receiver_and_argument_cannot_be_selected_from_different_incoming_routes():
    graph, _ = merged_connection_program(swap_argument=True)
    assert "protocol_input_source" in {issue.code for issue in validate(graph)}


def test_missing_incoming_case_keeps_an_obligation_instead_of_accepting_the_good_subset():
    graph, _ = merged_connection_program(omit_right=True)
    report = _view(graph)
    inputs, = report["inputs"]
    assert inputs["status"] == "PARTIAL"
    assert inputs["missing_incoming"]
    assert any(isinstance(gap, dict) and gap["code"] == "protocol_input_case_missing" for gap in inputs["gaps"])


def test_actual_result_uses_define_inventory_before_declared_targets_are_read():
    graph, details = merged_connection_program(omit_consumer=True)
    report = _view(graph)
    ledger, = report["consumers"]
    assert set(ledger["targets"]) == set(details["targets"])
    assert set(ledger["missing"]) == set(details["targets"][1:])
    assert ledger["status"] == "PARTIAL"


def test_removing_attachments_does_not_remove_input_or_result_use_denominators():
    graph, details = merged_connection_program(attach=False)
    report = _view(graph)
    assert report["inputs"][0]["status"] == "MISSING"
    assert set(report["consumers"][0]["missing"]) == set(details["targets"])


def test_opaque_consumer_is_retained_and_never_becomes_a_dead_work_proof():
    graph, details = merged_connection_program(opaque_consumer=True)
    ledger, = _view(graph)["consumers"]
    assert set(details["targets"]).issubset(ledger["targets"])
    assert any(isinstance(gap, dict) and gap["code"] == "consumer_escape_or_effects_unresolved" for gap in ledger["gaps"])


def test_invalid_call_input_foreign_key_is_a_structural_contradiction():
    graph, details = merged_connection_program()
    attachment, = graph.protocol_call_inputs
    bad_site = replace(details["site"], slot=999)
    bad = replace(graph, protocol_call_inputs=(replace(attachment, site=bad_site),))
    assert "protocol_connection_site" in {issue.code for issue in validate(bad)}


def test_formal_resolves_original_value_without_manufacturing_a_producer():
    graph, details = merged_connection_program()
    index = ProgramIndex(graph)
    ctx = ConnectionContext(graph, index=index)
    formal = BlockArgument(details["merge"], 0)
    port = ctx.port(formal)
    assert ctx.values[port.values[0]].origin == formal
    assert ctx.bind(formal, OwnedUse(details["call"].id, details["call"].uses[0].id))["match"] is True


def test_known_small_budget_stays_partial_and_preserves_fixed_call_inventory():
    graph, _ = merged_connection_program()
    report = _view(graph, budget=1)
    assert report["cursor"] and len(report["inputs"]) == len(report["consumers"]) == 1
    assert report["inputs"][0]["status"] == "PARTIAL"


def test_prepared_query_does_not_construct_a_second_program_index(monkeypatch):
    graph, _ = merged_connection_program()
    index = ProgramIndex(graph)
    def no_construction(*args, **kwargs):
        raise AssertionError("prepared connection query must reuse its validated index")
    monkeypatch.setattr(ProgramIndex, "__init__", no_construction)
    report = index.protocol_obligations(budget=100000)
    assert report["connections"]["issues"] == ()


def test_reference_only_helper_routes_retain_both_callers_and_the_raw_anchor():
    graph, details = helper_request_program(depth=2)
    index = ProgramIndex(graph)
    ctx = ConnectionContext(graph, index=index, budget=ValidityBudget(50000))
    result = ctx.bind(RawOperandSource(details["raw"]["left"], 0), details["inputs"][0])
    assert len(result["routes"]) == 1
    assert result["routes"][0]["context"][0][0] == details["calls"]["left"].id
    assert result["routes"][0]["request_binding"]["raw"] == details["raw"]["left"]


def test_cross_function_wrong_reference_does_not_match_equal_none_content():
    graph, details = helper_request_program(depth=2)
    index = ProgramIndex(graph)
    ctx = ConnectionContext(graph, index=index)
    source = OwnedUse(details["calls"]["left"].id, details["calls"]["left"].call_arguments[1])
    result = ctx.bind(source, details["inputs"][0])
    assert result["match"] is False
    assert not any(route["match"] is True for route in result["routes"])


def test_an_intermediate_formal_can_be_the_source_of_a_deeper_helper_input():
    graph, details = helper_request_program(depth=2)
    intermediate = next(op for op in graph.operations if op.id.value == "helper.level.0.call")
    anchor = OwnedUse(intermediate.id, intermediate.call_arguments[0])
    ctx = ConnectionContext(graph, index=ProgramIndex(graph))
    result = ctx.bind(anchor, details["inputs"][0])
    assert result["match"] is True
    assert len(result["routes"]) == 2
    assert all(route["match"] is True for route in result["routes"])


def test_another_intermediate_formal_cannot_replace_the_deeper_helpers_actual_ordinal():
    graph, details = helper_request_program(depth=2)
    intermediate = next(op for op in graph.operations if op.id.value == "helper.level.0.call")
    ctx = ConnectionContext(graph, index=ProgramIndex(graph))
    result = ctx.bind(OwnedUse(intermediate.id, intermediate.call_arguments[1]), details["inputs"][0])
    assert result["match"] is False


def test_an_anchor_observed_after_the_call_cannot_prove_the_earlier_child_input():
    from scar.ir.program.ids import OperationID, UseID
    from scar.ir.program.model import Behavior, Operation
    graph, details = helper_request_program(depth=2)
    intermediate = next(op for op in graph.operations if op.id.value == "helper.level.0.call")
    original = intermediate.uses[0]
    late_use = replace(original, id=UseID("helper.late.anchor.use"))
    late = Operation(OperationID("helper.late.anchor"), "a later observation", (Behavior.COMPUTE,),
                     (late_use,), effects_complete=True)
    regions = []
    for region in graph.regions:
        blocks = []
        for block in region.blocks:
            if intermediate.id in block.operations:
                position = block.operations.index(intermediate.id) + 1
                block = replace(block, operations=(*block.operations[:position], late.id, *block.operations[position:]))
            blocks.append(block)
        regions.append(replace(region, blocks=tuple(blocks)))
    graph = replace(graph, regions=tuple(regions), operations=(*graph.operations, late))
    ctx = ConnectionContext(graph, index=ProgramIndex(graph))
    assert ctx.bind(OwnedUse(late.id, late_use.id), details["inputs"][0])["match"] is False


@pytest.mark.parametrize("late", (False, True))
def test_trigger_availability_crosses_a_reference_only_helper_without_a_fake_raw_formal(late):
    graph, details = helper_request_program(depth=2, late_pack=late)
    ctx = ConnectionContext(graph, index=ProgramIndex(graph))
    report = ctx.available(details["raw"]["left"], details["inputs"][0].operation)
    assert report["match"] is (False if late else True)
    assert report["routes"]
    assert {route["context"][0][0] for route in report["routes"]} == {
        details["calls"]["left"].id, details["calls"]["right"].id}
    assert all(route["source_current_before_call"] is (False if late else True) for route in report["routes"])
    assert "availability does not prove native request selection" in report["conditions"]


@pytest.mark.parametrize("late", (False, True))
def test_projection_source_context_can_extend_to_an_independently_selected_helper_caller(late):
    graph, details = helper_request_program(depth=2, late_pack=late)
    ctx = ConnectionContext(graph, index=ProgramIndex(graph))
    anchor = details["raw"]["left"]
    source = ctx.origins(anchor)["recipes"][0]
    target = next(recipe for recipe in ctx.origins(details["inputs"][0])["recipes"]
        if ctx.recipe_context(recipe)["context"][0][0] == details["calls"]["left"].id)
    extended = ctx.extend_context(source, anchor, target)
    assert extended["match"] is (False if late else True)
    assert len(extended["context"]) == 2
    assert extended["transformation_authorized"] is False


def test_raw_operand_binding_retains_the_callers_it_cannot_cover_as_partial():
    graph, details = helper_request_program(depth=2)
    ctx = ConnectionContext(graph, index=ProgramIndex(graph))
    report = ctx.bind(RawOperandSource(details["raw"]["left"], 0), details["inputs"][0])
    # The helper has a second known caller with another pack. A good left
    # binding must not make the complete helper input inventory verified.
    assert report["match"] is None and report["routes"]


def test_branch_raw_ordinals_use_the_same_original_merge_guard_as_the_receiver():
    graph, _ = merged_connection_program(raw_operands=True)
    report = _view(graph)
    assert not report["issues"]
    assert report["inputs"][0]["status"] == "DECLARED"
    assert all(case["correlation"]["match"] is True for case in report["inputs"][0]["cases"])


def test_wrong_branch_raw_ordinal_is_a_known_mismatch_instead_of_a_missing_binding():
    graph, _ = merged_connection_program(raw_operands=True, swap_argument=True)
    assert "protocol_input_source" in {issue.code for issue in validate(graph)}


def test_a_wrong_host_terminal_is_a_known_mismatch_even_when_its_foreign_key_is_valid():
    from scar.ir.program.protocols import HostTerminal
    graph, _ = merged_connection_program()
    attachment, = graph.protocol_result_consumers
    wrong = next(op for op in graph.operations if op.id.value == "merge.raised.return")
    bad = replace(graph, protocol_result_consumers=(replace(attachment,
        targets=(*attachment.targets, HostTerminal(wrong.id))),))
    assert "protocol_result_consumer" in {issue.code for issue in validate(bad)}


def test_nested_conditional_consumers_are_kept_when_no_single_guard_is_a_must_proof():
    graph, details = nested_consumer_program()
    ctx = ConnectionContext(graph, index=ProgramIndex(graph))
    actual = details["observers"][0]
    assert ctx.bind(details["source"], actual)["match"] is False
    assert all(ctx.bind(details["source"], actual, guard=guard)["match"] is False
               for guard in details["guards"])
    assert ctx.may_forwards(details["source"], actual) is True
    ledger, = common_connections(ctx)["consumers"]
    assert set(ledger["targets"]) == set(details["targets"])
    assert set(ledger["missing"]) == set(details["targets"][1:])
    assert any(isinstance(gap, dict) and gap["code"] == "consumer_condition_correlation_unresolved"
               for gap in ledger["gaps"])


def test_joint_original_choices_prove_a_nested_copy_without_using_the_may_inventory():
    graph, details = nested_consumer_program()
    ctx = ConnectionContext(graph, index=ProgramIndex(graph))
    keeps = tuple(edge for edge in details["guards"] if ".keep." in edge.operation.value)
    result = ctx.bind(details["source"], details["observers"][0], choices=keeps)
    assert result["match"] is True
    assert result["runtime_identity_verified"] is result["transformation_authorized"] is False


def test_two_incoming_visits_of_one_merge_cannot_be_flattened_into_one_static_choice():
    graph, details = nested_consumer_program()
    ctx = ConnectionContext(graph, index=ProgramIndex(graph))
    result = ctx.bind(details["source"], details["observers"][0], choices=details["guards"][:2])
    assert result["match"] is None
    assert "selected_merge_visits_require_occurrence_context" in result["gaps"]


def test_cross_region_availability_does_not_pick_the_last_of_two_conflicting_helper_merge_visits():
    graph, details = helper_diamond_program()
    ctx = ConnectionContext(graph, index=ProgramIndex(graph))
    result = ctx.available(details["raw"]["left"], details["inputs"][0].operation,
                           guard=details["helper_guards"])
    assert result["match"] is None
    assert "selected_merge_visits_require_occurrence_context" in result["gaps"]


def test_source_queries_keep_conflicting_helper_incoming_visits_unresolved():
    graph, details = helper_diamond_program()
    ctx = ConnectionContext(graph, index=ProgramIndex(graph))
    origin = ctx.origins(details["inputs"][0], guard=details["helper_guards"])
    assert not origin["recipes"]
    assert any(gap["code"] == "selected_merge_visits_require_occurrence_context" for gap in origin["gaps"])
    binding = ctx.request_binding(details["raw"]["left"], details["inputs"][0], guard=details["helper_guards"])
    assert not binding["bindings"]


def test_a_static_recursive_recipe_cannot_be_relabelled_as_a_complete_call_context():
    from tests.fixtures.program_input_origin_graphs import input_origin_program
    graph, details = input_origin_program(loop=True, recursive=True, second_caller=False)
    ctx = ConnectionContext(graph, index=ProgramIndex(graph))
    original = ctx.origins(OwnedUse(details["driver_consumer"], details["driver_consumer_use"]))
    cycle = next(recipe for recipe in original["recipes"] if recipe["kind"] == "STATIC_CYCLE")
    context = ctx.recipe_context(cycle)
    assert context["match"] is None
    assert "static_caller_or_cfg_visit_context_unresolved" in context["gaps"]
