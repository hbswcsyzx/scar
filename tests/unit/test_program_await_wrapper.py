"""Native wrapper construction keeps W/B as distinct original ports."""
from dataclasses import replace

import pytest

from scar.ir.program.ids import BlockID
from scar.ir.program.model import BlockArgument, OperationResult
from scar.ir.program.protocol_await_records import CoroutineAwaitWrapper, WrapperHeldBody
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.resumption import ResumableKind, SuspendTerminator, SuspensionFlavor
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_await_wrapper_graphs import await_wrapper_program


def test_native_wrapper_has_real_constructor_getter_and_nested_driver_ports():
    program, details = await_wrapper_program()
    require_valid(program)
    assert details["body"].kind is ResumableKind.COROUTINE
    assert all(op.terminator.flavor is SuspensionFlavor.AWAIT for op in program.operations
               if type(op.terminator) is SuspendTerminator)
    assert all(type(row.contract) is CoroutineAwaitWrapper
               for row in details["constructor_rows"])
    assert type(details["constructor_rows"][0].contract.expected_body) is BlockArgument
    assert details["call"].callee == details["wrapper_region"].id
    assert details["inner_call"].callee == details["driver"].region
    assert details["inner_call"].uses[0].value == details["read_body"]
    assert details["read"].uses[0].value != details["read_body"]
    assert type(details["projection"]) is WrapperHeldBody
    assert details["projection"].body_result == OperationResult(details["read"].id, 0)
    assert details["read"].accesses[0].reference is None
    report = ProgramIndex(program).protocol_obligations(
        details["construction_scope"], budget=65536)["connections"]["families"]["await"]
    assert report["inventory"]["source_count"] == 1
    assert any(job["source_operation"] == details["constructor"].id
               and job["drive"] == details["drive"].operation
               for job in report["inventory"]["jobs"])
    assert report["source_runtime_verified"] is False


def test_deleting_wrapper_link_preserves_source_and_advance_obligations():
    program, details = await_wrapper_program(attach_link=False)
    require_valid(program)
    report = ProgramIndex(program).protocol_obligations(
        details["construction_scope"], budget=65536)["connections"]["families"]["await"]
    assert report["inventory"]["source_count"] == 1
    assert len(report["inventory"]["jobs"]) == 2
    assert all(job["links"] == () for job in report["inventory"]["jobs"])
    assert report["transformation_authorized"] is False


def test_second_create_has_a_distinct_normal_handle_and_latest_state_ports():
    program, details = await_wrapper_program(second_create=True)
    require_valid(program)
    first, second = details["create"], details["second_create"]
    assert first.body == second.body
    assert first.operation != second.operation
    operations = {op.id: op for op in program.operations}
    assert operations[first.operation].uses[0].value == operations[second.operation].uses[0].value
    assert details["constructor_rows"][0].contract.expected_body == BlockArgument(
        BlockID("factory.second.created"), 0)


@pytest.mark.parametrize("defect,code", (
    ("constructor_raise", "protocol_await_wrapper_constructor"),
    ("foreign_result", "protocol_await_wrapper_read"),
    ("missing_state", "protocol_await_wrapper_state"),
    ("no_projection", "protocol_await_wrapper_projection"),
))
def test_wrapper_projection_cannot_switch_original_constructor_getter_or_state(defect, code):
    program, details = await_wrapper_program()
    require_valid(program)
    projection = details["projection"]
    if defect == "constructor_raise":
        projection = replace(projection, constructor=replace(projection.constructor, slot=1))
    elif defect == "foreign_result":
        projection = replace(projection, body_result=details["constructor_rows"][0].contract.result)
    elif defect == "missing_state":
        projection = replace(projection, state_sites=())
    else:
        projection = None
    changed = replace(program, protocol_bindings=tuple(replace(row, projection=projection)
        if row in details["links"] else row for row in program.protocol_bindings))
    assert code in {issue.code for issue in validate(changed)}
