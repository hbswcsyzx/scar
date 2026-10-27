"""Publication queries expose original owner/state/source endpoints."""
from dataclasses import replace

import pytest

from scar.ir.program.codec import dumps
from scar.ir.program.ids import OperationID, RegionID, UseID
from scar.ir.program.model import (
    AccessMode, Footprint, FootprintKind, StateAccess, StateVersionValue, TerminatorKind, Use, UseRole,
)
from scar.ir.program.queries import ProgramIndex
from tests.fixtures.program_driver_graphs import driver_program
from tests.fixtures.program_publication_graphs import publication_program


@pytest.mark.parametrize("target, kind", [
    ("start", TerminatorKind.SUSPEND), ("value", TerminatorKind.RETURN),
    ("packet", TerminatorKind.RAISE),
])
@pytest.mark.parametrize("direct_owner", [False, True])
def test_publication_resolves_original_scope_commit_owner_accesses_and_source(target, kind, direct_owner):
    graph = publication_program(target=target, extra_domain=True, create=True, direct_owner=direct_owner)
    before = dumps(graph)
    index = ProgramIndex(graph)
    scope = graph.driver_lifecycles[0]
    commit = graph.body_outcome_commits[0]
    assert index.driver_lifecycle(scope.region) is scope
    assert index.body_outcome_commit(commit.operation) is commit
    view = index.body_publication(commit.operation)
    assert view.commit is commit
    assert view.instance is index.use_site(commit.instance)
    assert view.drive is index.body_drive(commit.outcome.drive)
    assert view.source.operation == commit.outcome.source
    assert view.source.kind is kind
    assert all(site is index.use_site(site.use.id) for site in view.source.values)
    own = index.operations[commit.operation]
    assert len(view.accesses) == len(own.accesses)
    for access_view, access in zip(view.accesses, own.accesses):
        assert access_view.access is access
        assert access_view.before is index.use_site(access.before)
        if access.after is None:
            assert access_view.after is None
        else:
            assert access_view.after is index.values[access.after]
            assert index.producer(access.after) is access_view.after.origin
            assert access_view.after.origin.operation == commit.operation
    if kind is TerminatorKind.SUSPEND:
        saved = {slot.use for slot in index.operations[view.source.operation].terminator.saved}
        assert saved.isdisjoint(site.use.id for site in view.source.values)
    assert dumps(graph) == before


def test_read_access_has_no_fabricated_after_and_written_subset_keeps_real_producers():
    graph = publication_program(strict_subset=True, extra_domain=True)
    row = graph.body_outcome_commits[0]
    op = next(operation for operation in graph.operations if operation.id == row.operation)
    if not any(access.mode is AccessMode.READ for access in op.accesses):
        interface = graph.driver_interfaces[0]
        read_location = next(location for location in interface.lifecycle
                             if location not in {access.location for access in op.accesses})
        block = next(block for region in graph.regions for block in region.blocks
                     if op.id in block.operations)
        value = next(value for value in graph.values if value.id in block.arguments
                     and isinstance(value, StateVersionValue) and value.location == read_location)
        use = Use(UseID("publication.query.read"), value.id, UseRole.STATE_CONTENT)
        op = replace(op, uses=(*op.uses, use), accesses=(*op.accesses, StateAccess(
            read_location, use.id, AccessMode.READ, footprint=Footprint(FootprintKind.WHOLE))))
        graph = replace(graph, operations=tuple(op if operation.id == op.id else operation
                                               for operation in graph.operations))
    index = ProgramIndex(graph)
    view = index.body_publication(row.operation)
    assert any(item.access.mode is AccessMode.READ and item.after is None for item in view.accesses)
    writes = [item for item in view.accesses if item.after is not None]
    assert writes and len(writes) < len(graph.driver_interfaces[0].lifecycle)
    assert {item.after.id for item in writes} == set(op.results)


def test_legacy_d1_has_no_publication_and_query_arguments_are_strict():
    graph = driver_program()
    index = ProgramIndex(graph)
    drive = graph.body_drives[0]
    assert index.driver_lifecycle(graph.driver_interfaces[0].region) is None
    assert index.body_outcome_commit(drive.operation) is None
    assert index.body_publication(drive.operation) is None
    assert index.drive_outcomes(drive.operation)
    for call in (lambda: index.driver_lifecycle("driver"),
                 lambda: index.body_outcome_commit("driver.drive"),
                 lambda: index.body_publication("driver.drive")):
        with pytest.raises(TypeError):
            call()
    with pytest.raises(KeyError):
        index.driver_lifecycle(RegionID("missing"))
    with pytest.raises(KeyError):
        index.body_publication(OperationID("missing"))


def test_invalid_commit_cannot_become_a_query_view():
    graph = publication_program()
    with pytest.raises(ValueError):
        ProgramIndex(replace(graph, driver_lifecycles=()))
