from dataclasses import FrozenInstanceError, fields

import pytest

import scar.ir.program as program
from scar.ir.program.drivers import (
    DriverRule, DriverRuleProfile, NormalResultPort, ResumableCreate,
)
from scar.ir.program.ids import BlockID, OperationID, RegionID, UseID
from scar.ir.program.lifecycle import BodyOutcomeCommit, DriveOutcomeRef, DriverLifecycle
from scar.ir.program.model import Behavior, Block, Operation, ProgramGraph, Region
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference


def _outcome(tag="first"):
    return DriveOutcomeRef(OperationID(f"drive.{tag}"), OperationID(f"source.{tag}"))


def _commit(tag="first"):
    return BodyOutcomeCommit(OperationID(f"commit.{tag}"), _outcome(tag), UseID(f"instance.{tag}"))


def _rule():
    implementation = ProviderFactReference(
        ProviderArtifact("unopened://lifecycle/rule", "b" * 64, 0, "driver-rule.v1"),
        "/rules/python-resumption-v1",
    )
    return DriverRule(DriverRuleProfile.PYTHON_RESUMPTION_V1, implementation)


def _graph(*, operations=(), driver_lifecycles=(), body_outcome_commits=(),
           resumable_creates=()):
    region_id = RegionID("root")
    operation_ids = tuple(operation.id for operation in operations)
    block = Block(BlockID("root.entry"), (), operation_ids)
    region = Region(region_id, "root", block.id, (block,), ())
    return ProgramGraph(
        region_id, (region,), tuple(operations), (),
        driver_lifecycles=tuple(driver_lifecycles),
        body_outcome_commits=tuple(body_outcome_commits),
        resumable_creates=tuple(resumable_creates),
    )


def test_lifecycle_records_are_public_frozen_and_have_only_contract_fields():
    lifecycle = DriverLifecycle(RegionID("driver"))
    outcome = _outcome()
    commit = _commit()

    assert program.DriverLifecycle is DriverLifecycle
    assert program.DriveOutcomeRef is DriveOutcomeRef
    assert program.BodyOutcomeCommit is BodyOutcomeCommit
    assert tuple(field.name for field in fields(DriverLifecycle)) == ("region",)
    assert tuple(field.name for field in fields(DriveOutcomeRef)) == ("drive", "source")
    assert tuple(field.name for field in fields(BodyOutcomeCommit)) == (
        "operation", "outcome", "instance")
    assert not hasattr(lifecycle, "__dict__")
    assert not hasattr(outcome, "__dict__")
    assert not hasattr(commit, "__dict__")
    with pytest.raises(FrozenInstanceError):
        lifecycle.region = RegionID("other")
    with pytest.raises(FrozenInstanceError):
        commit.instance = UseID("other")


def test_records_require_exact_identifiers_and_exact_nested_record():
    class DerivedRegionID(RegionID):
        pass

    class DerivedOutcomeRef(DriveOutcomeRef):
        __slots__ = ()

    with pytest.raises(TypeError, match="exact RegionID"):
        DriverLifecycle(DerivedRegionID("driver"))
    with pytest.raises(TypeError, match="exact OperationID"):
        DriveOutcomeRef(RegionID("wrong"), OperationID("source"))
    with pytest.raises(TypeError, match="exact DriveOutcomeRef"):
        BodyOutcomeCommit(
            OperationID("commit"),
            DerivedOutcomeRef(OperationID("drive"), OperationID("source")),
            UseID("instance"),
        )


def test_nested_outcome_is_revalidated_when_commit_is_revalidated():
    commit = _commit()
    object.__setattr__(commit.outcome, "source", "corrupted")

    with pytest.raises(TypeError, match="exact OperationID"):
        commit.__post_init__()


def test_program_graph_accepts_typed_lifecycle_rows_without_reinterpreting_d1():
    lifecycle = DriverLifecycle(RegionID("root"))
    commit = _commit()
    graph = _graph(
        driver_lifecycles=(lifecycle,),
        body_outcome_commits=(commit,),
    )

    assert graph.driver_lifecycles == (lifecycle,)
    assert graph.body_outcome_commits == (commit,)
    assert graph.resumable_creates == ()


def test_program_graph_requires_unique_lifecycle_regions_and_commit_operations():
    with pytest.raises(ValueError, match="driver lifecycle regions"):
        _graph(driver_lifecycles=(
            DriverLifecycle(RegionID("root")),
            DriverLifecycle(RegionID("root")),
        ))

    first = _commit("same")
    second = BodyOutcomeCommit(
        first.operation,
        DriveOutcomeRef(OperationID("drive.other"), OperationID("source.other")),
        UseID("instance.other"),
    )
    with pytest.raises(ValueError, match="body outcome commit operations"):
        _graph(body_outcome_commits=(first, second))


def test_body_outcome_commit_cannot_reuse_a_d1_operation_role():
    operation_id = OperationID("shared.operation")
    operation = Operation(operation_id, "shared", (Behavior.CONTROL,))
    create = ResumableCreate(
        operation_id, RegionID("body"), UseID("function"), (),
        NormalResultPort(0), _rule(),
    )
    commit = BodyOutcomeCommit(
        operation_id,
        DriveOutcomeRef(OperationID("drive"), OperationID("source")),
        UseID("instance"),
    )

    with pytest.raises(ValueError, match="driver operation IDs|conflicts with another typed"):
        _graph(operations=(operation,), resumable_creates=(create,),
               body_outcome_commits=(commit,))
