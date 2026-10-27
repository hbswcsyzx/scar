from dataclasses import FrozenInstanceError, fields

import pytest

import scar.ir.program as program
from scar.ir.program.cleanup import HandledContextRead
from scar.ir.program.drivers import (
    DriverRule, DriverRuleProfile, NormalResultPort, ResumableCreate,
)
from scar.ir.program.ids import BlockID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.lifecycle import (
    BodyOutcomeCommit, CreatedCloseTest, DriveOutcomeRef, DriverLifecycle, NoBodyFinish,
)
from scar.ir.program.model import Behavior, Block, Operation, ProgramGraph, Region
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.structured import ControlEdgeReference


def _created_close(tag="test", *, session=None):
    return CreatedCloseTest(
        OperationID(f"created-close.{tag}"),
        UseID(f"instance.{tag}"),
        UseID(f"scheduler.{tag}"),
        UseID(f"effective.{tag}"),
        UseID(f"session.{tag}") if session is True else session,
        ValueID(f"result.{tag}"),
    )


def _no_body(tag="finish", *, edge=0):
    return NoBodyFinish(
        OperationID(f"no-body.{tag}"),
        ControlEdgeReference(OperationID(f"branch.{tag}"), edge),
        UseID(f"instance.{tag}"),
    )


def _rule():
    implementation = ProviderFactReference(
        ProviderArtifact("unopened://no-body/rule", "c" * 64, 0, "driver-rule.v1"),
        "/rules/python-resumption-v1",
    )
    return DriverRule(DriverRuleProfile.PYTHON_RESUMPTION_V1, implementation)


def _graph(*, operations=(), driver_lifecycles=(), body_outcome_commits=(),
           created_close_tests=(), no_body_finishes=(), resumable_creates=(),
           handled_context_reads=()):
    root = RegionID("root")
    operation_ids = tuple(operation.id for operation in operations)
    entry = Block(BlockID("root.entry"), (), operation_ids)
    region = Region(root, "root", entry.id, (entry,), ())
    return ProgramGraph(
        root, (region,), tuple(operations), (),
        driver_lifecycles=tuple(driver_lifecycles),
        body_outcome_commits=tuple(body_outcome_commits),
        created_close_tests=tuple(created_close_tests),
        no_body_finishes=tuple(no_body_finishes),
        resumable_creates=tuple(resumable_creates),
        handled_context_reads=tuple(handled_context_reads),
    )


def test_no_body_records_are_public_frozen_and_have_only_contract_fields():
    body = _created_close("body")
    async_request = _created_close("async", session=True)
    finish = _no_body("body")

    assert program.CreatedCloseTest is CreatedCloseTest
    assert program.NoBodyFinish is NoBodyFinish
    assert tuple(field.name for field in fields(CreatedCloseTest)) == (
        "operation", "instance", "scheduler_request", "effective_request", "session", "result")
    assert tuple(field.name for field in fields(NoBodyFinish)) == (
        "operation", "precondition", "instance")
    assert len({body.instance, body.scheduler_request, body.effective_request}) == 3
    assert async_request.session is not None
    assert len({async_request.instance, async_request.scheduler_request,
                async_request.effective_request, async_request.session}) == 4
    assert not hasattr(body, "__dict__")
    assert not hasattr(finish, "__dict__")
    with pytest.raises(FrozenInstanceError):
        body.result = ValueID("replacement")
    with pytest.raises(FrozenInstanceError):
        finish.instance = UseID("replacement")


def test_created_close_roles_require_distinct_exact_uses_but_do_not_store_values():
    # Roles are separate occurrences. Their referenced ValueIDs are joined by
    # the graph validator, so this record does not impose value inequality.
    assert _created_close("same-object").instance != _created_close("same-object").scheduler_request
    with pytest.raises(ValueError, match="UseIDs must be distinct"):
        CreatedCloseTest(
            OperationID("created-close.duplicate"), UseID("same"), UseID("same"),
            UseID("effective"), None, ValueID("result"),
        )
    with pytest.raises(ValueError, match="UseIDs must be distinct"):
        CreatedCloseTest(
            OperationID("created-close.duplicate-session"), UseID("instance"),
            UseID("scheduler"), UseID("effective"), UseID("scheduler"), ValueID("result"),
        )
    with pytest.raises(TypeError, match="exact UseID"):
        CreatedCloseTest(
            OperationID("created-close.bad"), ValueID("wrong"), UseID("scheduler"),
            UseID("effective"), None, ValueID("result"),
        )


def test_no_body_finish_revalidates_exact_control_edge_without_interpreting_its_index():
    edge = ControlEdgeReference(OperationID("branch"), 1)
    finish = NoBodyFinish(OperationID("finish"), edge, UseID("instance"))
    assert finish.precondition is edge
    # The record accepts a typed edge reference; the graph validator owns the
    # requirement that this particular no-body mark is on BRANCH edge zero.
    with pytest.raises(ValueError, match="nonnegative"):
        ControlEdgeReference(OperationID("branch"), True)

    object.__setattr__(edge, "operation", "corrupt")
    with pytest.raises(TypeError, match="control edge needs its terminating operation"):
        finish.__post_init__()


def test_program_graph_stores_lifecycle_tables_and_requires_unique_operation_keys():
    lifecycle = DriverLifecycle(RegionID("root"))
    commit = BodyOutcomeCommit(
        OperationID("commit"),
        DriveOutcomeRef(OperationID("drive"), OperationID("source")),
        UseID("commit.instance"),
    )
    created = _created_close("unique")
    finish = _no_body("unique")
    graph = _graph(
        driver_lifecycles=(lifecycle,),
        body_outcome_commits=(commit,),
        created_close_tests=(created,),
        no_body_finishes=(finish,),
    )
    assert graph.created_close_tests == (created,)
    assert graph.no_body_finishes == (finish,)

    with pytest.raises(ValueError, match="created_close_tests operations"):
        _graph(created_close_tests=(_created_close("duplicate"),
                                    _created_close("duplicate")))
    with pytest.raises(ValueError, match="no_body_finishes operations"):
        _graph(no_body_finishes=(_no_body("duplicate"), _no_body("duplicate")))

    class DerivedCreatedCloseTest(CreatedCloseTest):
        __slots__ = ()

    derived = DerivedCreatedCloseTest(
        OperationID("created-close.derived"), UseID("i"), UseID("s"),
        UseID("e"), None, ValueID("r"),
    )
    with pytest.raises(TypeError, match="exact typed records"):
        _graph(created_close_tests=(derived,))


def test_lifecycle_action_operations_cannot_overlap_each_other_or_prior_publication():
    created = _created_close("shared")
    finish = NoBodyFinish(created.operation, ControlEdgeReference(OperationID("branch"), 0),
                          UseID("instance.finish"))
    with pytest.raises(ValueError, match="lifecycle action operation IDs"):
        _graph(created_close_tests=(created,), no_body_finishes=(finish,))

    commit = BodyOutcomeCommit(
        OperationID("shared.commit"),
        DriveOutcomeRef(OperationID("drive"), OperationID("source")),
        UseID("instance.commit"),
    )
    finish_on_commit = NoBodyFinish(
        commit.operation, ControlEdgeReference(OperationID("branch"), 0), UseID("instance"))
    with pytest.raises(ValueError, match="lifecycle action operation IDs"):
        _graph(body_outcome_commits=(commit,), no_body_finishes=(finish_on_commit,))


def test_created_close_operation_cannot_reuse_d1_driver_role():
    operation_id = OperationID("shared.create")
    operation = Operation(operation_id, "shared", (Behavior.CONTROL,))
    create = ResumableCreate(
        operation_id, RegionID("body"), UseID("function"), (),
        NormalResultPort(0), _rule(),
    )
    created = CreatedCloseTest(
        operation_id, UseID("instance"), UseID("scheduler"), UseID("effective"),
        None, ValueID("bool"),
    )
    with pytest.raises(ValueError, match="lifecycle action operation conflicts"):
        _graph(operations=(operation,), resumable_creates=(create,),
               created_close_tests=(created,))


def test_no_body_operation_cannot_reuse_context_protocol_role():
    operation_id = OperationID("shared.context")
    operation = Operation(operation_id, "shared", (Behavior.CONTROL,))
    context_read = HandledContextRead(operation_id, ValueID("exception"))
    finish = NoBodyFinish(
        operation_id, ControlEdgeReference(OperationID("branch"), 0), UseID("instance"))
    with pytest.raises(ValueError, match="lifecycle action operation conflicts"):
        _graph(operations=(operation,), handled_context_reads=(context_read,),
               no_body_finishes=(finish,))
