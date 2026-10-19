"""A parent GET_AWAITABLE enters the actual general-method helper."""

from scar.ir.program.model import BlockArgument, ExitKind
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.resumption import ResumableKind
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_await_general_graphs import await_general_program


def test_general_await_expands_real_lookup_call_qualification_and_iterator_return():
    graph, details = await_general_program()
    require_valid(graph)

    get = details["get"]
    helper_lookup = details["helper_lookup"]
    helper_call = details["helper_call"]
    assert get.callee == details["helper"].id
    created = next(block for region in graph.regions for block in region.blocks
                   if block.id.value == "factory.created")
    assert get.uses[0].value == created.arguments[0]
    assert details["A"] == BlockArgument(created.id, 0)
    assert helper_lookup.uses[0].value == details["helper_entry_values"][0].id

    assert tuple(edge.kind for edge in get.terminator.successors) == (
        ExitKind.NORMAL, ExitKind.RAISE)
    assert tuple(edge.kind for edge in helper_lookup.terminator.successors) == (
        ExitKind.NORMAL, ExitKind.RAISE)
    assert tuple(edge.kind for edge in helper_call.terminator.successors) == (
        ExitKind.NORMAL, ExitKind.RAISE)
    assert details["helper_create"].operation == helper_call.id
    assert details["helper_create"].handle_result.index == 0
    assert details["helper_create"].function_object == details["function_capture_use"].id
    assert details["function_capture_use"].value == details["bound_method_value"]
    assert details["B"] == BlockArgument(details["helper_call_normal"], 0)
    assert details["A"] != details["B"]

    report = ProgramIndex(graph).protocol_obligations(
        details["acquisition_scope"], budget=65536)["connections"]["families"]["await"]
    assert report["inventory"]["source_count"] == 2
    acquisition_jobs = tuple(job for job in report["jobs"]
                             if job["scope"] == details["acquisition_scope"])
    assert len({job["source"] for job in acquisition_jobs}) == 1
    assert {job["advance"].slot for job in acquisition_jobs} == {0, 1}
    acquisition = next(row for row in report["acquisitions"]
                       if row["record"].operation == get.id)
    assert acquisition["expansion"]["stages"] == (
        details["method_lookup_rows"][0], details["method_call_rows"][0],
        details["qualification_row"])
    assert report["source_runtime_verified"] is False
    assert report["transformation_authorized"] is False


def test_general_await_source_inventory_survives_a_missing_body_link():
    graph, details = await_general_program(attach_link=False)
    require_valid(graph)

    report = ProgramIndex(graph).protocol_obligations(
        details["acquisition_scope"], budget=65536)["connections"]["families"]["await"]
    assert report["inventory"]["source_count"] == 2
    assert any(job["source_operation"] == details["get"].id
               for job in report["inventory"]["jobs"])
    assert all(job["links"] == () for job in report["inventory"]["jobs"])
    assert any("await_body_link_missing" in job["gaps"]
               for job in report["inventory"]["jobs"])


def test_general_await_known_generator_coroutine_cannot_continue_as_iterator():
    # D3: preserve this unqualified-return rejection; a correctly guarded CFG
    # keeps both syntactic legs and is tested separately from actual acceptance.
    from tests.fixtures.program_await_qualification_graphs import unqualified_general_program
    graph, details = unqualified_general_program()
    # The graph is structurally valid; the selected general-method result is
    # known to be the wrong resumable kind for the subsequent iterator call.
    assert "protocol_await_return_qualification" in {
        issue.code for issue in validate(graph)
    }
    assert details["helper_create"].body == details["body"].region
