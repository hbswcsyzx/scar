"""The general ``__await__`` call returns an iterator to the existing advance."""
from dataclasses import replace

from scar.ir.program.drivers import NormalResultPort
from scar.ir.program.model import ExitKind
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.resumption import ResumableKind
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_await_acquisition_graphs import await_acquisition_program


def _without_protocol_records(graph):
    return replace(graph, protocol_scopes=(), protocol_operations=(),
                   protocol_call_inputs=(), protocol_result_consumers=())


def _codes(graph):
    return {issue.code for issue in validate(graph)}


def test_general_await_normal_result_can_be_a_known_generator_iterator():
    graph, details = await_acquisition_program(result_kind=ResumableKind.GENERATOR)
    require_valid(_without_protocol_records(graph))
    require_valid(graph)

    call = details["await_call"]["operation"]
    create = details["create"]
    assert create.operation == call.id
    assert create.handle_result == NormalResultPort(0)
    assert create.body == details["created_body"].region
    assert details["advance_receiver"].value == details["iterator_value"]
    assert details["advance_receiver"].value == ProgramIndex(graph).normal_result(
        call.id, NormalResultPort(0)).id
    assert tuple(edge.kind for edge in call.terminator.successors) == (
        ExitKind.NORMAL, ExitKind.RAISE)

    report = ProgramIndex(graph).protocol_obligations(details["lookup_scope"], budget=65536)
    continuation = report["connections"]["families"]["continuations"]
    assert continuation["issues"] == ()
    assert report["source_runtime_verified"] is False
    assert report["transformation_authorized"] is False


def test_general_await_cannot_return_a_known_generator_coroutine_handle():
    graph, details = await_acquisition_program(
        result_kind=ResumableKind.GENERATOR_COROUTINE)
    require_valid(_without_protocol_records(graph))

    call = details["await_call"]["operation"]
    assert details["create"].operation == call.id
    assert details["create"].handle_result == NormalResultPort(0)
    assert details["advance_receiver"].value == details["iterator_value"]

    assert "protocol_await_return_qualification" in _codes(graph)
