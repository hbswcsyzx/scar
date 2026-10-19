"""Exact native wrapper instances continue through the final E/(G)/F chain."""
import pytest

from scar.ir.execution.coordinates import InitialEntry, ResumeIngress, ValueOccurrence
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from scar.ir.program.model import CompletionResult, ExitKind, TerminatorKind
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_await_wrapper_final_graphs import await_wrapper_final_execution
from tests.fixtures.program_await_wrapper_final_graphs import await_wrapper_final_program


_BUDGET = 1_048_576
_FLAGS = ("source_runtime_verified", "runtime_identity_verified",
          "value_identity_verified", "transformation_authorized")
_CORNERS = ((True, 1, False), (True, 2, True), (False, 1, True), (False, 2, False))


def _index(program, model, details):
    require_valid(program)
    validation = validate(model, program, evidence_graphs=details["evidence_graphs"])
    assert validation.valid, validation.issues
    return ExecutionIndex(model, program, evidence_graphs=details["evidence_graphs"])


def _report(program, model, details, *, budget=_BUDGET):
    return _index(program, model, details).await_body_links(
        details["static"]["construction_scope"], budget=budget)


def _advance(report, example, ordinal):
    caller = example["wrapper_calls"][ordinal].caller
    occurrence, = tuple(occurrence for job in report["jobs"]
        for occurrence in job["occurrences"]
        if occurrence["advance"].id == caller and occurrence["advance_selected"] is True)
    return occurrence


def _consumer(report, details, example):
    definition, = tuple(row for row in report["outcomes"]
        if row["definition"]["source"] == details["static"]["source"]
        and row["definition"]["drive_outcome"] == details["drive_outcome"]
        and row["definition"]["advance_operation"] == details["static"]["advance_operation"])
    occurrence, = tuple(row for row in definition["occurrences"]
        if row["advance"].id == example["advance"]
        and row["drive"].id == example["body_drives"][-1].drive)
    consumer, = tuple(row for row in occurrence["consumers"]
        if row["definition"]["actual"] == details["static"]["extract_input"]
        and row["definition"]["requires_final_extraction"] is True)
    return occurrence, consumer


def _association(call):
    return call["association"] if isinstance(call, dict) else call


def _assert_current_results(program, model, details, example, consumer):
    static = details["static"]
    implementation = consumer["implementation"]
    kind = example["implementation_kind"]
    expected_calls = (example["implementation_root_call"], *example["implementation_nested_calls"])
    assert len(implementation["frames"]) == len(implementation["stages"]) == static["depth"]
    for frame, expected, captured in zip(implementation["frames"], expected_calls,
                                        example["implementation_frames"], strict=True):
        assert _association(frame["call"]) == expected
        assert frame["entry"].id == captured["entry"]
        assert frame["completion"].id == captured["completion"]
    leaf, = tuple(stage for stage in implementation["stages"]
        if stage["occurrence"].operation == static["primitive"].id)
    assert leaf["occurrence"].id == example["implementation_frames"][-1]["operations"][static["primitive"].id]
    assert leaf["input_support"]["match"] is True
    blocks = {block.id: block for region in program.regions for block in region.blocks}
    uses = {(use.operation, use.use): use for use in model.uses}
    selected, = tuple(leg for leg in leaf["legs"] if leg["definition"]["kind"] is kind)
    assert selected["selected"] is True
    assert {result["definition"]["slot"] for result in selected["results"]} == {0, 1, 2}
    for leg in leaf["legs"]:
        if leg is selected:
            continue
        assert leg["selected"] is False
        assert all(result["value"] is None and all(path["status"] == "NOT_APPLICABLE"
            for path in result["paths"]) for result in leg["results"])
    for result in selected["results"]:
        slot = result["definition"]["slot"]
        assert isinstance(result["value"], ValueOccurrence)
        assert result["value"].value == static["stage_records"][-1]["landing_values"][kind][slot].id
        paths = tuple(path for path in result["paths"]
            if path["selected"] is True and path["binding"]["match"] is True
            and path["contribution"]["match"] is True)
        assert paths
        for path in paths:
            assert path["binding"]["match"] is True and path["contribution"]["match"] is True
            if kind is ExitKind.NORMAL and slot == 0:
                # The original Ref has no supplied ObjectIdentity. Its copy
                # path is proved while that independent identity stays open.
                assert path["status"] == "PARTIAL" and path["gaps"]
                assert all(getattr(gap, "code", gap) == "body_reference_identity_unproved"
                           for gap in path["gaps"])
            else:
                assert path["status"] == "DECLARED" and path["gaps"] == ()
            assert len(path["hops"]) == static["depth"]
            value = result["value"]
            for hop, number in zip(path["hops"], reversed(range(static["depth"]))):
                frame = example["implementation_frames"][number]
                owned = static["stage_records"][number]["terminal_uses"][kind][slot]
                assert hop["definition"]["terminal"] == owned
                assert _association(hop["call"]) == expected_calls[number]
                assert hop["terminal"].id == frame["completion"]
                assert hop["source_value"].id == value.id
                assert hop["use"] == uses[(frame["completion"], owned.use)]
                assert hop["terminal_value"].id == hop["use"].value
                assert hop["binding"]["match"] is True
                assert hop["post_binding"]["match"] is True
                parent = static["parent_call"] if number == 0 else static["stage_records"][number - 1]["operation"]
                port = hop["definition"]["caller_result"]
                edge = parent.terminator.successors[port.edge.successor_index]
                formal, = tuple(formal for actual, formal in zip(edge.arguments,
                    blocks[edge.block].arguments, strict=True)
                    if type(actual) is CompletionResult and actual.index == slot)
                assert hop["parent_value"].value == formal
                value = hop["parent_value"]
            assert path["interface_value"].id == value.id
            assert path["targets"]
            for target in path["targets"]:
                assert target["selected"] is True
                assert target["operation"].id == example["final"]
                assert target["binding"]["match"] is True
                assert target["use"].operation == example["final"]
                assert target["value"].id == target["use"].value
    assert len(implementation["outputs"]) == 6
    for output in implementation["outputs"]:
        if output["kind"] is not kind:
            assert output["selected"] is False and output["value"] is None
            assert output["status"] == "NOT_APPLICABLE"
            continue
        assert output["selected"] is True
        assert isinstance(output["value"], ValueOccurrence)
        assert output["terminals"]
        for terminal in output["terminals"]:
            assert terminal["selected"] is True and terminal["match"] is True
            assert terminal["occurrence"].id == example["implementation_frames"][0]["completion"]
            assert terminal["use"].value == terminal["value"].id
            assert any(path["contribution"]["match"] is True for path in terminal["witnesses"])
    final_leg, = tuple(leg for leg in consumer["legs"] if leg["definition"]["kind"] is kind)
    assert final_leg["selected"] is True and final_leg["own_value"] is not None
    assert final_leg["targets"] and final_leg["states"]
    for target in final_leg["targets"]:
        assert target["operation"].id == example["final"]
        assert target["binding"]["match"] is True
    for state in final_leg["states"]:
        assert state["binding"]["match"] is True
        owned = state["definition"]["target"]
        assert state["target"].id == uses[(example["final"], owned.use)].value
    assert all(implementation[flag] is False for flag in _FLAGS)
    return implementation


@pytest.mark.parametrize(("zero_cut", "depth", "child_raised"), _CORNERS,
    ids=("zero-E-N", "zero-EG-R", "two-cut-E-R", "two-cut-EG-N"))
def test_native_wrapper_two_instances_reach_their_own_current_final_ports(zero_cut, depth, child_raised):
    program, model, details = await_wrapper_final_execution(
        zero_cut=zero_cut, depth=depth, child_raised=child_raised, instances=2)
    index = _index(program, model, details)
    report = index.await_body_links(details["static"]["construction_scope"], budget=_BUDGET)
    assert report["issues"] == ()
    assert report["inventory"]["source_count"] == 1
    assert report["job_count"] == len(details["static"]["call_rows"])
    assert len({example["body_activation"] for example in details["instances"]}) == 2
    segments = {segment.id: segment for segment in model.segments}
    operations = {operation.id: operation for operation in program.operations}
    expected = 1 if zero_cut else 3
    for example in details["instances"]:
        assert example["wrapper_object"] != example["body_object"]
        assert len(example["body_segments"]) == len(example["body_drives"]) == expected
        assert len({call.id for call in example["call_activations"]}) == expected * 2
        assert example["creation"] == example["expected_creation"] != example["decoy_creation"]
        assert {drive.activation for drive in example["body_drives"]} == {example["body_activation"]}
        for ordinal, association in enumerate(example["body_drives"]):
            segment = segments[example["body_segments"][ordinal]]
            assert segment.activation == example["body_activation"]
            if ordinal == 0:
                assert type(segment.ingress) is InitialEntry
            else:
                assert type(segment.ingress) is ResumeIngress
                assert segment.ingress.suspension == example["body_drives"][ordinal - 1].outcome
            drive = index.drive_execution(association.drive, budget=65536)
            assert drive["association"] == association
            assert drive["activation"].id == example["body_activation"]
            assert drive["entry"].id == example["body_entries"][ordinal]
            assert drive["instance"]["creation_handle"] is not None
            advance = _advance(report, example, ordinal)
            assert {row["occurrence"].id for row in advance["matched_sources"]} == {example["constructor"]}
            route, = advance["routes"]
            assert tuple(_association(row) for row in route["call_chain"]) == (
                example["wrapper_calls"][ordinal], example["driver_calls"][ordinal])
            assert route["drive_occurrence"].id == association.drive
            projection, = route["projections"]
            assert projection["constructor"].id == example["constructor"]
            assert projection["distinctness"]["status"] == "DECLARED_DISTINCT_OBJECTS"
            bindings = {row["role"]: row for row in projection["bindings"]}
            for role in ("wrapper_input", "getter_to_drive"):
                assert bindings[role]["original_copy"] is True
            for role in ("native_held_body", "held_body_origin"):
                assert bindings[role]["original_copy"] is None
                assert bindings[role]["conditional_native_projection"] is True
                assert bindings[role]["compatibility"]["status"] == "DECLARED_SAME_OBJECT"
        body_terminal = operations[details["static"]["drivers"][-1]["outcome_source"]]
        assert body_terminal.terminator.kind is TerminatorKind.RETURN
        occurrence, consumer = _consumer(report, details, example)
        assert occurrence["body_outcome"].id == example["body_outcome"]
        assert consumer["operation"].id == example["extraction"]
        _assert_current_results(program, model, details, example, consumer)
    assert all(report[flag] is False for flag in _FLAGS)


@pytest.mark.parametrize(("same_object", "other_body", "code"),
    ((True, None, "body_reference_distinct_conflict"), (False, 0, "await_wrapper_body_source")),
    ids=("W-is-B", "getter-decoy-Create"))
def test_wrapper_identity_conflicts_do_not_rebind_expected_b(same_object, other_body, code):
    program, model, details = await_wrapper_final_execution(
        zero_cut=False, depth=2, same_object=same_object, other_body=other_body)
    report = _report(program, model, details)
    assert report["status"] == "CONTRADICTED"
    assert code in {issue.code for issue in report["issues"]}
    assert report["job_count"] == len(details["static"]["call_rows"])
    first = details["instances"][0]
    if other_body is not None:
        assert first["creation"] == first["decoy_creation"] != first["expected_creation"]
        assert first["actual_body_object"] != first["body_object"]
    assert all(report[flag] is False for flag in _FLAGS)


def test_missing_first_wrapper_call_keeps_its_obligation_and_cannot_borrow_another_instance():
    program, model, details = await_wrapper_final_execution(
        zero_cut=False, depth=2, missing_wrapper_call=(0, 0))
    report = _report(program, model, details)
    missing, sibling = details["instances"]
    occurrence = _advance(report, missing, 0)
    assert occurrence["routes"] == ()
    assert report["job_count"] == len(details["static"]["call_rows"])
    for ordinal in range(3):
        route, = _advance(report, sibling, ordinal)["routes"]
        assert route["drive"]["activation"].id == sibling["body_activation"]
    _, consumer = _consumer(report, details, sibling)
    _assert_current_results(program, model, details, sibling, consumer)
    assert report["status"] == "PARTIAL"


def test_missing_child_call_retains_exact_frame_and_sibling_final_chain():
    program, model, details = await_wrapper_final_execution(
        zero_cut=False, depth=2, missing_child_call=(0, 0))
    report = _report(program, model, details)
    missing, sibling = details["instances"]
    _, consumer = _consumer(report, details, missing)
    implementation = consumer["implementation"]
    assert len(implementation["frames"]) == 2
    assert implementation["frames"][0]["call"] is not None
    assert implementation["frames"][1]["call"] is None
    assert implementation["status"] == "PARTIAL"
    selected_outputs = tuple(row for row in implementation["outputs"] if row["selected"] is True)
    assert len(selected_outputs) == 3
    assert all(terminal["match"] is not True for row in selected_outputs for terminal in row["terminals"])
    _, consumer = _consumer(report, details, sibling)
    _assert_current_results(program, model, details, sibling, consumer)


@pytest.mark.parametrize("slot", (0, 1), ids=("payload", "current-state"))
def test_missing_leaf_terminal_use_cannot_borrow_sibling_payload_or_state(slot):
    program, model, details = await_wrapper_final_execution(
        zero_cut=False, depth=2, child_raised=True, missing_terminal_use=(0, 1, slot))
    report = _report(program, model, details)
    missing, sibling = details["instances"]
    _, consumer = _consumer(report, details, missing)
    implementation = consumer["implementation"]
    output, = tuple(row for row in implementation["outputs"]
                    if row["kind"] is ExitKind.RAISE and row["slot"] == slot)
    assert output["selected"] is True
    assert all(row["match"] is not True for row in output["terminals"])
    assert implementation["status"] == "PARTIAL"
    _, consumer = _consumer(report, details, sibling)
    _assert_current_results(program, model, details, sibling, consumer)


def test_old_child_input_state_does_not_match_its_new_own_result():
    program, model, details = await_wrapper_final_execution(
        zero_cut=False, depth=2)
    _index(program, model, details)
    invalid_program, invalid_static = await_wrapper_final_program(
        zero_cut=False, depth=2, stale_child_state=True)
    # The canonical program is checked before snapshot/occurrence joins. The
    # first-red query expectation was at the wrong layer: this state cannot
    # acquire an ExecutionIndex or borrow another captured instance's state.
    report = validate(model, invalid_program, evidence_graphs=details["evidence_graphs"])
    assert report.valid is False
    assert len(report.issues) == 1 and report.issues[0].code == "record_or_program"
    assert "stale_state" in report.issues[0].message
    for kind in (ExitKind.NORMAL, ExitKind.RAISE):
        owned = invalid_static["stage_records"][-1]["terminal_uses"][kind][1]
        assert str(owned.use) in report.issues[0].message
    with pytest.raises(ValueError, match="stale_state"):
        ExecutionIndex(model, invalid_program, evidence_graphs=details["evidence_graphs"])


def test_budget_one_keeps_native_source_original_jobs_and_no_derived_authority():
    program, model, details = await_wrapper_final_execution(zero_cut=False, depth=2)
    report = _report(program, model, details, budget=1)
    assert report["inventory"]["source_count"] == 1
    assert report["job_count"] >= 1
    assert report["budget"]["used"] <= 1 and report["budget"]["truncated"] is True
    assert report["cursor"] is not None and report["status"] == "PARTIAL"
    assert all(occurrence["matched_sources"] == () for job in report["jobs"]
               for occurrence in job["occurrences"])
    assert all(report[flag] is False for flag in _FLAGS)
