"""True completion subsets preserve original results, state and wire boundaries."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from scar.ir.program import (
    BlockArgument, CompletionResult, CompletionSignature, CompletionSuccessor,
    ExitKind, NormalResultPort, Terminator, TerminatorKind, ValueID,
)
from scar.ir.program import codec
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_admission_graphs import admission_program
from tests.fixtures.program_invoke_subset_graphs import (
    final_gate_subset_program, invoke_subset_program,
)


SUBSETS = ((ExitKind.RAISE,), (ExitKind.NORMAL,), (ExitKind.NORMAL, ExitKind.RAISE))


def _operation(graph, identity):
    return next(op for op in graph.operations if op.id == identity)


def _replace_operation(graph, identity, **changes):
    return replace(graph, operations=tuple(replace(op, **changes) if op.id == identity else op
                                           for op in graph.operations))


@pytest.mark.parametrize("kinds", SUBSETS)
def test_known_callee_has_exact_actual_completion_subset_and_current_produced_ports(kinds):
    graph, details = invoke_subset_program(kinds)
    require_valid(graph)
    index = ProgramIndex(graph)
    invoke = _operation(graph, details["invoke"])
    callee = next(region for region in graph.regions if region.id == details["callee"])
    callee_ids = {identity for block in callee.blocks for identity in block.operations}
    actual_kinds = {op.terminator.kind for op in graph.operations if op.id in callee_ids
                    and op.terminator is not None and op.terminator.kind in
                    (TerminatorKind.RETURN, TerminatorKind.RAISE)}
    assert actual_kinds == {TerminatorKind.RETURN if kind is ExitKind.NORMAL
                            else TerminatorKind.RAISE for kind in kinds}
    assert {port.kind for port in callee.exits} == set(kinds)
    assert {signature.kind for signature in invoke.completions} == set(kinds)
    assert {edge.kind for edge in invoke.terminator.successors} == set(kinds)
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    for edge in invoke.terminator.successors:
        landing = blocks[edge.block]
        assert edge.arguments == (CompletionResult(1), CompletionResult(0))
        state, result = (index.values[value] for value in landing.arguments)
        assert state.origin == BlockArgument(landing.id, 0)
        assert result.origin == BlockArgument(landing.id, 1)
        terminal = _operation(graph, details["terminals"][edge.kind])
        assert terminal.uses[0].value == result.id
        assert terminal.uses[1].value == state.id != details["before"]
        # The caller genuinely handles the exception; the only-RAISE callee
        # itself has no fabricated RETURN site or NORMAL exit interface.
        assert terminal.terminator.kind is TerminatorKind.RETURN


@pytest.mark.parametrize("kinds", SUBSETS)
def test_unknown_effects_require_current_poststate_on_every_available_completion(kinds):
    graph, details = invoke_subset_program(kinds)
    terminal = _operation(graph, details["terminals"][kinds[-1]])
    graph = _replace_operation(graph, terminal.id, uses=tuple(
        replace(use, value=details["before"]) if index == 1 else use
        for index, use in enumerate(terminal.uses)))
    assert "stale_state" in {issue.code for issue in validate(graph)}


@pytest.mark.parametrize("kinds", SUBSETS)
def test_result_slot_cannot_be_duplicated_or_substituted_for_current_poststate(kinds):
    graph, details = invoke_subset_program(kinds)
    invoke = _operation(graph, details["invoke"])
    first, *others = invoke.terminator.successors
    first = replace(first, arguments=(CompletionResult(0), CompletionResult(0)))
    graph = _replace_operation(graph, invoke.id,
        terminator=replace(invoke.terminator, successors=(first, *others)))
    codes = {issue.code for issue in validate(graph)}
    assert {"completion_slots", "edge_type"} & codes, codes


@pytest.mark.parametrize("kinds", SUBSETS)
def test_known_callee_with_genuine_different_exit_set_is_rejected(kinds):
    graph, details = invoke_subset_program(kinds, alternate_callee=True)
    require_valid(graph)
    changed = _replace_operation(graph, details["invoke"], callee=details["alternate"])
    assert "invoke_callee_exits" in {issue.code for issue in validate(changed)}


@pytest.mark.parametrize("mutation", ("empty", "missing", "duplicate", "extra", "wrong-kind"))
def test_signature_kind_set_must_match_exact_actual_edge_set(mutation):
    graph, details = invoke_subset_program((ExitKind.NORMAL, ExitKind.RAISE))
    invoke = _operation(graph, details["invoke"])
    normal, raised = invoke.completions
    if mutation == "empty":
        signatures, edges = (), invoke.terminator.successors
    elif mutation == "missing":
        signatures, edges = (normal,), invoke.terminator.successors
    elif mutation == "duplicate":
        signatures, edges = (normal, normal), invoke.terminator.successors
    elif mutation == "extra":
        signatures, edges = (normal, raised), (invoke.terminator.successors[0],)
    else:
        signatures, edges = (raised,), (invoke.terminator.successors[0],)
    with pytest.raises(ValueError, match="completion signatures"):
        replace(invoke, completions=signatures,
                terminator=replace(invoke.terminator, successors=edges))


@pytest.mark.parametrize("mutation", ("empty", "duplicate-kind", "same-target"))
def test_completion_edges_are_nonempty_unique_kinds_and_private_targets(mutation):
    graph, details = invoke_subset_program((ExitKind.NORMAL, ExitKind.RAISE))
    invoke = _operation(graph, details["invoke"])
    normal, raised = invoke.terminator.successors
    edges = (() if mutation == "empty" else
             (normal, replace(raised, kind=ExitKind.NORMAL)) if mutation == "duplicate-kind" else
             (normal, replace(raised, block=normal.block)))
    with pytest.raises(ValueError):
        Terminator(TerminatorKind.INVOKE, edges)


def test_only_raise_normal_result_is_explicit_valueerror_not_stopiteration():
    graph, details = invoke_subset_program()
    index = ProgramIndex(graph)
    with pytest.raises(ValueError, match="actual NORMAL completion"):
        index.normal_result(details["invoke"], NormalResultPort(0))


def test_only_normal_query_keeps_result_index_separate_from_physical_landing_position():
    graph, details = invoke_subset_program((ExitKind.NORMAL,))
    index = ProgramIndex(graph)
    landing = details["landings"][ExitKind.NORMAL]
    assert index.normal_result(details["invoke"], NormalResultPort(0)).origin == BlockArgument(landing, 1)
    assert index.normal_result(details["invoke"], NormalResultPort(1)).origin == BlockArgument(landing, 0)
    with pytest.raises(IndexError):
        index.normal_result(details["invoke"], NormalResultPort(2))


@pytest.mark.parametrize("kind", (ExitKind.NORMAL, ExitKind.RAISE))
def test_final_body_gate_still_requires_both_completions_and_reports_driver_issue(kind):
    graph, _ = final_gate_subset_program(kind)
    issues = validate(graph)
    codes = {issue.code for issue in issues}
    # These rows are deliberately invalid D1 metadata over real core paths.
    # A core error would hide the missing specialized-gate guard.
    assert codes == {"driver_gate_completions"}, issues


@pytest.mark.parametrize("kinds", ((ExitKind.NORMAL,), (ExitKind.RAISE,)))
def test_single_completion_codec_auto_selects_v18_without_other_new_capability(kinds):
    graph, _ = invoke_subset_program(kinds)
    assert not graph.protocol_operations
    payload = codec.dumps(graph)
    assert json.loads(payload)["schema_version"] == 18
    assert codec.loads(payload) == graph
    assert codec.dumps(codec.loads(payload)) == payload


@pytest.mark.parametrize("version", range(1, 18))
def test_single_completion_invoke_cannot_be_forced_into_old_wire(version):
    graph, _ = invoke_subset_program()
    document = json.loads(codec.dumps(graph))
    document["schema_version"] = version
    with pytest.raises(ValueError):
        codec.loads(json.dumps(document))


def test_dual_invoke_keeps_historical_v2_auto_profile():
    graph, _ = invoke_subset_program((ExitKind.NORMAL, ExitKind.RAISE))
    payload = codec.dumps(graph)
    assert json.loads(payload)["schema_version"] == 2
    assert codec.loads(payload) == graph
    assert codec.dumps(codec.loads(payload)) == payload


def test_existing_admission_capability_remains_v18_and_roundtrips_without_partial_invoke():
    graph, _ = admission_program()
    require_valid(graph)
    assert all(len(op.terminator.successors) == 2 for op in graph.operations
               if op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE)
    payload = codec.dumps(graph)
    assert json.loads(payload)["schema_version"] == 18
    assert codec.loads(payload) == graph
    assert codec.dumps(codec.loads(payload)) == payload


@pytest.mark.parametrize("version", (2, 17))
def test_old_frozen_profiles_keep_original_payload_bytes(version):
    payload = (Path(__file__).parents[1] / "fixtures" / f"program_graph_v{version}_frozen.json").read_text()
    if version == 2:
        assert payload.endswith("\n") and not payload.endswith("\n\n")
        payload = payload[:-1]
    assert codec.dumps(codec.loads(payload)) == payload
