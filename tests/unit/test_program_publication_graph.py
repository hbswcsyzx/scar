"""D2.1 source/owner/state wiring, without native or runtime authority."""
from dataclasses import replace

import pytest

from scar.ir.program.ids import LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.lifecycle import DriverLifecycle, DriveOutcomeRef
from scar.ir.program.model import (
    AccessMode, Behavior, DataValue, Operation, OperationResult,
    StateVersionValue, TerminatorKind, Use, UseRole,
)
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_driver_graphs import driver_program
from tests.fixtures.program_publication_graphs import publication_program


def operation(graph, identity):
    return next(item for item in graph.operations if item.id == identity)


def change(graph, replacement):
    return replace(graph, operations=tuple(replacement if item.id == replacement.id else item
                                           for item in graph.operations))


def codes(graph):
    return {issue.code for issue in validate(graph)}


@pytest.mark.parametrize("target", ("start", "value", "packet"))
@pytest.mark.parametrize("direct", (False, True))
def test_real_suspend_return_raise_sources_and_direct_or_forwarded_owner(target, direct):
    graph = publication_program(target=target, direct_owner=direct)
    require_valid(graph)
    row, = graph.body_outcome_commits
    source = operation(graph, row.outcome.source)
    assert source.terminator.kind is {
        "start": TerminatorKind.SUSPEND, "value": TerminatorKind.RETURN,
        "packet": TerminatorKind.RAISE}[target]
    # No writable phase/FINISHED field can contradict this real source.
    assert not hasattr(row, "post") and not hasattr(row, "session")


def test_write_subset_lifecycle_subset_driver_and_untouched_current_state():
    graph = publication_program(strict_subset=True, create=True)
    require_valid(graph)
    interface, = graph.driver_interfaces
    row, = graph.body_outcome_commits
    commit = operation(graph, row.operation)
    writes = {access.location for access in commit.accesses if access.mode is AccessMode.READ_WRITE}
    reads = {access.location for access in commit.accesses if access.mode is AccessMode.READ}
    assert writes < set(interface.lifecycle) and reads == set(interface.lifecycle) - writes
    assert len(commit.results) == 1 and all(access.reference is None for access in commit.accesses)
    # Coarse owner precision is not invented to make a complete metadata op pass.
    owner = next(use.value for use in commit.uses if use.id == row.instance)
    reference = next(value for value in graph.values if value.id == owner)
    assert reference.targets is None and reference.referent_identity is None
    require_valid(publication_program(extra_domain=True))  # L is a strict subset of D.


def test_cleanup_and_invoke_frontier_commits_each_private_source_before_merge():
    from tests.fixtures.program_resumption_graphs import resumption_cleanup_invoke_program
    graph = publication_program(target="value", body_graph=resumption_cleanup_invoke_program())
    require_valid(graph)
    assert {operation(graph, row.outcome.source).terminator.kind
            for row in graph.body_outcome_commits} == {TerminatorKind.RETURN, TerminatorKind.RAISE}
    drive = operation(graph, graph.body_drives[0].operation)
    assert len(graph.body_outcome_commits) == len(drive.terminator.successors) == 2


def test_empty_and_mixed_divergent_frontiers_do_not_fabricate_commits():
    from tests.unit.test_body_outcome_frontier import _nonterminating_body
    from tests.fixtures.program_resumption_graphs import resumption_loop_program
    empty = publication_program(body_graph=_nonterminating_body())
    require_valid(empty)
    assert empty.driver_lifecycles and not empty.body_outcome_commits
    mixed = publication_program(target="value", body_graph=resumption_loop_program())
    require_valid(mixed)
    assert len(mixed.body_outcome_commits) == 1


def test_old_d1_graph_does_not_silently_acquire_publication_obligations():
    graph = driver_program()
    require_valid(graph)
    assert not graph.driver_lifecycles and not graph.body_outcome_commits


def test_enabled_scope_requires_coverage_and_unscoped_metadata_cannot_downgrade():
    graph = publication_program()
    assert "publication_coverage" in codes(replace(graph, body_outcome_commits=()))
    assert "publication_scope" in codes(replace(graph, driver_lifecycles=()))
    missing_interface = replace(graph, driver_lifecycles=(DriverLifecycle(RegionID("resume")),))
    assert "publication_scope" in codes(missing_interface)


@pytest.mark.parametrize("drive,source", (
    ("driver.gate", "resume.suspend"),
    ("missing.drive", "resume.suspend"),
    ("driver.drive", "missing.source"),
    ("driver.drive", "resume.return"),  # Beyond the next Suspend for Start.
))
def test_wrong_drive_or_noncurrent_source_is_rejected_without_lookup_crash(drive, source):
    graph = publication_program()
    row, = graph.body_outcome_commits
    changed = replace(row, outcome=DriveOutcomeRef(OperationID(drive), OperationID(source)))
    assert "publication_outcome" in codes(replace(graph, body_outcome_commits=(changed,)))


def test_missing_publication_operation_is_not_created_by_its_declaration():
    graph = publication_program()
    row, = graph.body_outcome_commits
    assert "publication_operation" in codes(replace(graph, body_outcome_commits=(
        replace(row, operation=OperationID("nonexistent.publication")),)))


def test_callback_or_even_pure_work_cannot_precede_the_private_first_commit():
    graph = publication_program()
    row, = graph.body_outcome_commits
    inserted = Operation(OperationID("before.commit"), "ordinary pure work", (Behavior.CONTROL,),
                         effects_complete=True)
    graph = replace(graph, operations=(*graph.operations, inserted), regions=tuple(
        replace(region, blocks=tuple(replace(block, operations=(inserted.id, *block.operations))
                                     if block.operations[0] == row.operation else block
                                     for block in region.blocks)) for region in graph.regions))
    assert "publication_landing" in codes(graph)


def test_produced_reference_payload_cannot_impersonate_original_owner():
    graph = publication_program(target="value")
    row, = graph.body_outcome_commits
    drive = operation(graph, row.outcome.drive)
    edge = drive.terminator.successors[0]
    block = next(block for region in graph.regions for block in region.blocks if block.id == edge.block)
    payload = block.arguments[0]
    commit = operation(graph, row.operation)
    changed = replace(commit, uses=tuple(replace(use, value=payload) if use.id == row.instance else use
                                          for use in commit.uses))
    assert "publication_owner" in codes(change(graph, changed))


def test_duplicate_outcome_claim_cannot_replace_another_actual_source():
    from tests.fixtures.program_resumption_graphs import resumption_cleanup_invoke_program
    graph = publication_program(target="value", body_graph=resumption_cleanup_invoke_program())
    first, second = graph.body_outcome_commits
    graph = replace(graph, body_outcome_commits=(first, replace(second, outcome=first.outcome)))
    assert {"publication_coverage", "publication_landing"} <= codes(graph)


def test_current_state_and_declared_lifecycle_scope_are_both_required():
    graph = publication_program(extra_domain=True)
    interface, = graph.driver_interfaces
    outside = replace(graph, driver_interfaces=(replace(interface, lifecycle=(LocationID("driver.extra"),)),))
    assert "publication_access" in codes(outside)
    row, = graph.body_outcome_commits
    commit = operation(graph, row.operation)
    drive = operation(graph, row.outcome.drive)
    old = next(use.value for use in drive.uses if use.id == graph.body_drives[0].state_inputs[0].source)
    before = commit.accesses[0].before
    stale = replace(commit, uses=tuple(replace(use, value=old) if use.id == before else use
                                       for use in commit.uses))
    assert "stale_state" in codes(change(graph, stale))


@pytest.mark.parametrize("behavior", (Behavior.MEMORY, Behavior.TRANSFER, Behavior.ORDER))
def test_metadata_commit_cannot_claim_drop_copy_or_synchronization_work(behavior):
    graph = publication_program()
    row, = graph.body_outcome_commits
    commit = operation(graph, row.operation)
    assert "publication_shape" in codes(change(graph, replace(commit, behaviors=(*commit.behaviors, behavior))))
    assert "publication_shape" in codes(change(graph, replace(commit, effects_complete=False)))


def test_no_write_is_not_a_body_publication():
    graph = publication_program()
    row, = graph.body_outcome_commits
    commit = operation(graph, row.operation)
    access, = commit.accesses
    before = next(use.value for use in commit.uses if use.id == access.before)
    old_after = access.after
    graph = replace(graph, values=tuple(value for value in graph.values if value.id != old_after),
        operations=tuple(replace(op, uses=tuple(replace(use, value=before) if use.value == old_after else use
                                               for use in op.uses)) for op in graph.operations))
    commit = operation(graph, row.operation)
    graph = change(graph, replace(commit, results=(), accesses=(replace(access, mode=AccessMode.READ, after=None),)))
    assert "publication_writes" in codes(graph)


def test_extra_scalar_output_and_extra_use_do_not_hide_inside_publication():
    graph = publication_program()
    row, = graph.body_outcome_commits
    commit = operation(graph, row.operation)
    value = DataValue(ValueID("publication.extra.result"), RegionID("driver"),
                      OperationResult(commit.id, len(commit.results)), "builtins.int")
    extra = replace(graph, values=(*graph.values, value))
    assert "publication_results" in codes(change(extra, replace(commit, results=(*commit.results, value.id))))
    owner = next(use.value for use in commit.uses if use.id == row.instance)
    use = Use(UseID("publication.extra.use"), owner, UseRole.REFERENCE)
    assert "publication_uses" in codes(change(graph, replace(commit, uses=(*commit.uses, use))))
