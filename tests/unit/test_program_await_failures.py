"""General-await failures retain their source-stage and consumer inventory."""

from scar.ir.program.model import ExitKind, TerminatorKind
from scar.ir.program.protocols import ProtocolClause
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid
from tests.fixtures.program_await_failure_graphs import await_failure_program


def test_lookup_raise_keeps_call_and_qualification_stages_in_the_graph():
    graph, details = await_failure_program("lookup_raise")
    require_valid(graph)

    assert tuple(row.slot for row in details["get_rows"]) == (0, 1)
    assert tuple(row.slot for row in details["method_lookup_rows"]) == (0, 1)
    assert tuple(row.slot for row in details["method_call_rows"]) == (0, 1)
    assert details["qualification_row"].clause is ProtocolClause.AWAIT_ITERATOR_QUALIFICATION
    assert details["failure_terminal"].terminator.kind is TerminatorKind.RAISE
    assert tuple(edge.kind for edge in details["get"].terminator.successors) == (
        ExitKind.NORMAL, ExitKind.RAISE)

    report = ProgramIndex(graph).protocol_obligations(
        details["acquisition_scope"], budget=65536)["connections"]["families"]["await"]
    assert report["inventory"]["source_count"] == 2
    acquisition_jobs = tuple(job for job in report["jobs"]
                             if job["scope"] == details["acquisition_scope"])
    assert {job["advance"].slot for job in acquisition_jobs} == {0, 1}


def test_method_call_raise_has_its_own_completion_consumer():
    graph, details = await_failure_program("method_call_raise")
    require_valid(graph)

    call_failure = details["helper_call_raise"]
    assert call_failure is details["failure_terminal"]
    assert any(row.operation == details["helper_call"].id and row.slot == 1
               for row in details["method_call_rows"])
    assert any(row.contract.result.edge.operation == details["helper_call"].id
               and row.contract.result.edge.successor_index == 1
               for row in details["method_call_rows"])


def test_known_generator_coroutine_rejection_keeps_the_normal_cfg_alternative():
    graph, details = await_failure_program("qualification_reject")
    require_valid(graph)

    assert details["helper_create"].body == details["body"].region
    rejected_edge = details["rejected_edge"]
    rejected_block = details["qualification_branch"].terminator.successors[
        rejected_edge.successor_index].block
    assert any(block.id == rejected_block
               and details["helper_type_error"].id in block.operations
               for block in details["helper"].blocks)
    assert details["failure_terminal"] is details["helper_type_error"]
    assert tuple(edge.kind for edge in details["helper_call"].terminator.successors) == (
        ExitKind.NORMAL, ExitKind.RAISE)
