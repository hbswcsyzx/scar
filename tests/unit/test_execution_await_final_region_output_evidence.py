"""Dynamic output receipts for the original final-extractor interface."""
from dataclasses import replace

import pytest

from scar.ir.execution.coordinates import OperationOccurrence, UseOccurrence, ValueOccurrence
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from scar.ir.program.model import ExitKind, StateVersionValue, ValueKind
from scar.ir.program.protocols import OwnedUse
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_await_final_region_graphs import await_final_region_execution


QUERY_BUDGET = 1_048_576


def _report(program, model, details):
    require_valid(program)
    validation = validate(model, program)
    assert validation.valid, validation.issues
    return ExecutionIndex(model, program).await_body_links(
        details["static"]["acquisition_scope"], budget=QUERY_BUDGET)


def _implementation(report, details, example):
    definitions = tuple(row for row in report["outcomes"]
        if row["definition"]["drive_outcome"] == details["drive_outcome"]
        and row["definition"]["advance_operation"] ==
            details["static"]["drivers"][-1]["caller_call"].id)
    assert len(definitions) == 1
    occurrences = tuple(row for row in definitions[0]["occurrences"]
        if row["advance"].id == example["advance"]
        and row["drive"].id == example["body_drives"][-1].drive)
    assert len(occurrences) == 1
    consumers = tuple(row for row in occurrences[0]["consumers"]
        if row["definition"]["actual"] == details["static"]["extract_input"]
        and row["definition"]["requires_final_extraction"] is True)
    assert len(consumers) == 1
    return consumers[0]["implementation"]


def _selected_state_outputs(implementation, kind):
    return tuple(output for output in implementation["outputs"]
        if output["kind"] is kind and output["type"].kind is ValueKind.STATE)


def _assert_state_output_has_dynamic_witness(implementation, kind):
    outputs = _selected_state_outputs(implementation, kind)
    assert outputs
    for output in outputs:
        assert output["selected"] is True
        assert isinstance(output["value"], ValueOccurrence)
        terminals = tuple(terminal for terminal in output["terminals"]
                          if terminal["selected"] is True)
        assert terminals
        for terminal in terminals:
            assert terminal["match"] is True
            assert isinstance(terminal["terminal"], OwnedUse)
            assert isinstance(terminal["occurrence"], OperationOccurrence)
            assert isinstance(terminal["use"], UseOccurrence)
            assert isinstance(terminal["value"], ValueOccurrence)
            assert terminal["terminal"].operation == terminal["occurrence"].operation
            assert terminal["terminal"].use == terminal["use"].use
            assert terminal["use"].operation == terminal["occurrence"].id
            assert terminal["use"].value == terminal["value"].id
            assert any(witness["contribution"]["match"] is True
                       and witness["binding"]["match"] is True
                       and witness["hops"]
                       for witness in terminal["witnesses"])


def _drop_first_state_terminal_use(program, model, details, example):
    kind = ExitKind.NORMAL
    stage = details["static"]["stage_records"][0]
    slot = next(number for number, value in enumerate(stage["landing_values"][kind])
                if isinstance(value, StateVersionValue))
    owned = stage["terminal_uses"][kind][slot]
    occurrence_id = example["implementation_frames"][0]["operations"][owned.operation]
    model = replace(model, uses=tuple(row for row in model.uses
        if (row.operation, row.use) != (occurrence_id, owned.use)))
    return program, model, slot


def test_complete_instances_report_actual_state_outputs_and_terminal_path_witnesses():
    program, model, details = await_final_region_execution(
        depth=1, instances=2, child_raised=False)
    report = _report(program, model, details)

    for example in details["implementation_instances"]:
        implementation = _implementation(report, details, example)
        _assert_state_output_has_dynamic_witness(implementation, ExitKind.NORMAL)


@pytest.mark.parametrize("missing", ("outer-return", "state-terminal-use"))
def test_missing_first_instance_output_never_borrows_sibling_witness(missing):
    if missing == "outer-return":
        program, model, details = await_final_region_execution(
            depth=1, instances=2, child_raised=False, missing_return=0)
        target_slot = None
    else:
        program, model, details = await_final_region_execution(
            depth=1, instances=2, child_raised=False)
        program, model, target_slot = _drop_first_state_terminal_use(
            program, model, details, details["implementation_instances"][0])

    report = _report(program, model, details)
    missing_example, sibling = details["implementation_instances"]
    missing_impl = _implementation(report, details, missing_example)
    outputs = _selected_state_outputs(missing_impl, ExitKind.NORMAL)
    assert outputs
    checked_outputs = tuple(output for output in outputs
        if target_slot is None or output["slot"] == target_slot)
    assert checked_outputs
    missing_terminals = tuple(terminal for output in checked_outputs
        for terminal in output["terminals"] if terminal["selected"] is not False)
    assert missing_terminals
    assert all(terminal["match"] is not True for terminal in missing_terminals)

    sibling_impl = _implementation(report, details, sibling)
    _assert_state_output_has_dynamic_witness(sibling_impl, ExitKind.NORMAL)

