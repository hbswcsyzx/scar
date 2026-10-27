"""The completed F/H Reference continues through P's own later cleanup cuts."""
import pytest

from scar.ir.program.model import ExitKind, InvokeLiteralResult, ProtocolValue
from scar.ir.program.protocols import HostTerminal, OwnedUse, ProtocolProfile
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.resumption import SuspendTerminator
from scar.ir.program.validation import require_valid
from tests.fixtures.program_await_parent_post_cleanup_graphs import await_parent_post_cleanup_program


_FLAGS = ("source_runtime_verified", "runtime_identity_verified",
          "value_identity_verified", "transformation_authorized")


@pytest.mark.parametrize(("depth", "helper_zero_cut"), ((1, True), (2, False)),
                         ids=("E-zero-B", "EG-two-cut-B"))
def test_completed_await_helper_reference_reaches_parent_return_only_across_parent_resumes(
        depth, helper_zero_cut):
    program, details = await_parent_post_cleanup_program(depth=depth, helper_zero_cut=helper_zero_cut)
    require_valid(program)
    parent = details["parent"]
    helper = details["helper"]
    call = details["parent_helper_call"]
    assert call.callee == helper["caller"].id
    assert {body.region for body in program.resumable_bodies} == {parent.id, helper["body"].id}
    assert call.callee not in {body.region for body in program.resumable_bodies}
    own = details["source"]
    assert type(own) is InvokeLiteralResult
    assert own == helper["stage_records"][-1]["own_results"][ExitKind.NORMAL]
    assert own.edge.operation == helper["primitive"].id
    assert own != helper["root_source"]
    actuals = set(call.invoke_arguments)
    values = {value.id: value for value in program.values}
    private = tuple(use for use in call.uses if type(values[use.value]) is ProtocolValue)
    assert len(private) == 2 and len({use.id for use in private}) == 2
    attach = next(operation for operation in program.operations if operation.id.value == "finally.attach")
    assert {use.value for use in private} == {attach.results[0]}
    assert all(use.id not in actuals for use in private)
    assert tuple(edge.arguments[0] for edge in call.terminator.successors) == tuple(
        use.id for use in private)
    assert {edge.kind for edge in call.terminator.successors} == {ExitKind.NORMAL, ExitKind.RAISE}
    parent_operations = {identity for block in parent.blocks for identity in block.operations}
    suspends = tuple(operation for operation in program.operations
                     if operation.id in parent_operations and type(operation.terminator) is SuspendTerminator)
    assert {operation.id for operation in suspends} == set(details["parent_cuts"])
    assert all(record["call"].callee == record["region"].id
               for record in details["outer_drivers"])
    outer_regions = {record["region"].id for record in details["outer_drivers"]}
    assert all(scope.profile is ProtocolProfile.GENERATOR_BODY_V1
        for scope in program.protocol_scopes
        if getattr(scope.subject, "interface_region", None) in outer_regions)

    index = ProgramIndex(program)
    stopped = index.completion_continuations(own, start=details["start"],
        choices=details["choices"], cross_resume=False, budget=1_048_576)
    assert not any(row["terminal"] == HostTerminal(details["parent_return"].id)
                   for row in stopped["terminals"])
    assert any(row["kind"] == "SUSPENSION"
        and row["operation"].id == details["parent_cuts"][0] for row in stopped["boundaries"])
    continued = index.completion_continuations(own, start=details["start"],
        choices=details["choices"], cross_resume=True, budget=1_048_576)
    final = details["parent_pending"]["actual"]
    receipts = tuple(row for row in continued["terminals"]
                     if row["terminal"] == HostTerminal(details["parent_return"].id))
    assert receipts
    for receipt in receipts:
        assert receipt["actual"] == final
        assert receipt["root_source"] == own
        assert receipt["role"] == "reference"
        assert receipt["root_binding"]["match"] is True
        assert receipt["binding"]["match"] is True
        assert receipt["root_preserved"] is True
        assert receipt["crossed_suspend"] is True
    assert {row["operation"].id for row in continued["suspensions"]} == set(details["parent_cuts"])
    assert final in continued["targets"]
    assert continued["overrides"] == ()
    assert all(report[name] is False for report in (stopped, continued) for name in _FLAGS)
