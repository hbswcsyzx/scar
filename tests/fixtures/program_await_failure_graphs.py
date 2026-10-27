"""Three real failure routes through a split general-await implementation."""

from scar.ir.program.resumption import ResumableKind
from tests.fixtures.program_await_general_graphs import await_general_program


_FAILURE_TERMINALS = {
    "lookup_raise": "helper_lookup_raise",
    "method_call_raise": "helper_call_raise",
    "qualification_reject": "helper_type_error",
}


def await_failure_program(stage):
    """Return the unchanged general-await graph and a selected failure target."""
    if type(stage) is not str or stage not in _FAILURE_TERMINALS:
        raise ValueError(f"unsupported await failure stage: {stage!r}")
    result_kind = (ResumableKind.GENERATOR_COROUTINE if stage == "qualification_reject"
                   else ResumableKind.GENERATOR)
    graph, details = await_general_program(result_kind=result_kind)
    return graph, {
        **details,
        "failure_stage": stage,
        "failure_terminal": details[_FAILURE_TERMINALS[stage]],
    }


__all__ = ["await_failure_program"]
