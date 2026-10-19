"""Captured executions for source-owned and expanded await failure paths."""

from dataclasses import replace

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.ids import CallActivationID
from scar.ir.program.ids import BlockID
from tests.fixtures.execution_call_graphs import _model
from tests.fixtures.program_await_failure_graphs import await_failure_program
from tests.fixtures.program_await_outcome_failure_graphs import await_outcome_failure_program


_HELPER_PATHS = {
    "lookup_raise": (
        ("await.general.helper.entry", 1),
        ("await.general.helper.lookup.raise", None),
    ),
    "method_call_raise": (
        ("await.general.helper.entry", 0),
        ("await.general.helper.lookup.normal", 1),
        ("await.general.helper.call.raise", None),
    ),
    "qualification_reject": (
        ("await.general.helper.entry", 0),
        ("await.general.helper.lookup.normal", 0),
        ("await.general.helper.call.normal", 1),
        ("await.general.helper.rejected", None),
    ),
}


def await_outcome_failure_execution(
        stage="qualification_reject", *, capture_call=True,
        omit_source_raise_row=False):
    """Capture the exact parent GET RAISE and one selected helper failure.

    The parent path always ends in GET's own RAISE landing and caller
    terminal.  The optional missing CallActivation leaves those observations
    intact while removing only the declared parent-to-helper association.
    ``omit_source_raise_row`` removes the original GET RAISE protocol row and
    its receipt while preserving the rest of the static source inventory.
    """
    if omit_source_raise_row:
        program, static = await_outcome_failure_program(
            stage, omit_acquisition_raise_row=True)
    else:
        program, static = await_failure_program(stage)

    parent_path = (
        (BlockID("factory.entry"), 0),
        (BlockID("factory.created"), 1),
        (BlockID("factory.awaitable.failure"), None),
    )
    helper_path = tuple((BlockID(block), selected)
                        for block, selected in _HELPER_PATHS[stage])
    paths = (
        (program.root, parent_path, f"await.outcome.{stage}.parent"),
        (static["helper"].id, helper_path, f"await.outcome.{stage}.helper"),
    )
    model, scopes, source = _model(program, paths)
    parent, helper = scopes
    caller = parent[2][static["get"].id]
    completion = helper[2][static["failure_terminal"].id]
    association = CallActivation(
        CallActivationID(f"await.outcome.{stage}.get.helper"), caller,
        helper[0], helper[1][0], completion, source)
    model = replace(model, call_activations=(association,) if capture_call else ())

    return program, model, {
        **static,
        "source": source,
        "parent_activation": parent[0],
        "parent_visits": parent[1],
        "parent_operations": parent[2],
        "helper_activation": helper[0],
        "helper_visits": helper[1],
        "helper_operations": helper[2],
        "call_activation": association,
        "captured_call_activation": capture_call,
        "failure_stage_name": stage,
    }


__all__ = ["await_outcome_failure_execution"]
