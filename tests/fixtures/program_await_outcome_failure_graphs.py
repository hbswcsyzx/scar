"""Core-legal variants for the await failure-path outcome view."""

from dataclasses import replace

from scar.ir.program.protocol_await_records import AwaitBodyLink
from scar.ir.program.protocol_connections import ProtocolOperationRef
from scar.ir.program.protocols import ProtocolClause
from tests.fixtures.program_await_failure_graphs import await_failure_program
from tests.fixtures.program_await_wrapper_graphs import await_wrapper_program


def await_outcome_failure_program(
        stage="qualification_reject", *, omit_parent_raise_consumer=False,
        omit_acquisition_raise_row=False, remove_success_metadata=False,
        wrong_parent_packet_slot=False):
    """Return the real split-await graph, with optional metadata-only defects.

    The graph's operations, blocks, values, CFG and state SSA stay unchanged.
    The switches remove or corrupt only protocol declarations so tests can
    distinguish missing inventory from known bad port selection.
    """
    graph, details = await_failure_program(stage)
    get = details["get"]
    site = ProtocolOperationRef(details["acquisition_scope"],
        ProtocolClause.AWAIT_ACQUISITION, get.id, 1)

    if omit_parent_raise_consumer:
        graph = replace(graph, protocol_result_consumers=tuple(
            row for row in graph.protocol_result_consumers if row.site != site))

    if omit_acquisition_raise_row:
        graph = replace(graph, protocol_operations=tuple(
            row for row in graph.protocol_operations
            if not (row.scope == details["acquisition_scope"]
                    and row.operation == get.id and row.slot == 1)))
        graph = replace(graph, protocol_result_consumers=tuple(
            row for row in graph.protocol_result_consumers if row.site != site))

    if remove_success_metadata:
        graph = replace(graph, protocol_call_inputs=(), protocol_bindings=tuple(
            row for row in graph.protocol_bindings
            if type(row) is not AwaitBodyLink))

    if wrong_parent_packet_slot:
        from scar.ir.program.model import CompletionResult, InvokeLiteralResult
        from scar.ir.program.structured import ControlEdgeReference

        rows = []
        for row in graph.protocol_operations:
            if row == details["get_rows"][1]:
                contract = replace(row.contract, result=InvokeLiteralResult(
                    ControlEdgeReference(get.id, 1), CompletionResult(1)))
                row = replace(row, contract=contract)
            rows.append(row)
        graph = replace(graph, protocol_operations=tuple(rows))

    return graph, details


def await_wrapper_outcome_failure_program(*, attach_link=False):
    """Use the existing real constructor INVOKE, optionally without Drive link."""
    return await_wrapper_program(attach_link=attach_link)


__all__ = ["await_outcome_failure_program", "await_wrapper_outcome_failure_program"]
