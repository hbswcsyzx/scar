"""The self-await graph keeps original CREATE/GET/CALL ports and slots."""
from scar.ir.program.model import BlockArgument, CompletionResult, ExitKind
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid
from tests.fixtures.program_await_pipeline_graphs import await_self_pipeline_program


def test_self_await_keeps_create_get_and_driver_call_as_one_original_graph():
    graph, details = await_self_pipeline_program()
    require_valid(graph)

    factory_created = next(block for region in graph.regions for block in region.blocks
                           if block.id.value == "factory.created")
    awaitable = next(block for region in graph.regions for block in region.blocks
                     if block.id.value == "factory.awaitable")
    get, call = details["get"], details["call"]
    assert details["create"].body == details["body"].region
    assert get.uses[0].value == factory_created.arguments[0]
    assert type(details["get_rows"][0].contract.expected) is BlockArgument
    assert details["get_rows"][0].contract.expected.block == factory_created.id
    assert details["get_rows"][0].contract.expected.index == 0
    assert call.uses[0].value == awaitable.arguments[0]

    assert tuple(edge.kind for edge in get.terminator.successors) == (
        ExitKind.NORMAL, ExitKind.RAISE)
    assert tuple(edge.kind for edge in call.terminator.successors) == (
        ExitKind.NORMAL, ExitKind.RAISE)
    assert {row.slot for row in details["get_rows"]} == {0, 1}
    assert {row.slot for row in details["call_rows"]} == {0, 1}
    assert all(isinstance(edge.arguments[0], CompletionResult)
               for edge in get.terminator.successors)

    await_report = ProgramIndex(graph).protocol_obligations(
        details["acquisition_scope"], budget=65536)["connections"]["families"]["await"]
    assert await_report["inventory"]["source_count"] == 1
    assert any(job["source_operation"] == get.id
               and job["advance_operation"] == call.id
               for job in await_report["inventory"]["jobs"])
    assert await_report["source_runtime_verified"] is False
    assert await_report["transformation_authorized"] is False
