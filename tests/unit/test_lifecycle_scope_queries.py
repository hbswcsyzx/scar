"""Detached lifecycle query views retain their unproved rule and exact point."""
from dataclasses import FrozenInstanceError, fields, replace
import json

import pytest

from scar.ir.program.codec import dumps, loads
from scar.ir.program.ids import OperationID, RegionID
from scar.ir.program.model import ExitKind
from scar.ir.program.queries import LifecyclePosition, LifecycleScope, ProgramIndex
from scar.ir.v2.common import ProofStatus
from tests.fixtures.program_driver_graphs import driver_program
from tests.fixtures.program_no_body_graphs import no_body_program
from tests.fixtures.program_publication_graphs import publication_program
from tests.fixtures.program_session_release_graphs import session_release_program


@pytest.mark.parametrize("version", (11, 12, 13, 14))
def test_only_explicit_scopes_wrap_facts_without_changing_legacy_wire(version):
    graph = {11: driver_program, 12: publication_program, 13: no_body_program,
             14: session_release_program}[version]()
    payload = dumps(graph)
    assert json.loads(payload)["schema_version"] == version
    index = ProgramIndex(graph)
    interface = graph.driver_interfaces[0]
    scope = index.lifecycle_scope(interface.region)
    if version == 11:
        assert scope is None
        assert index.lifecycle_before(graph.body_drives[0].operation) is None
    else:
        assert scope.declaration is graph.driver_lifecycles[0]
        assert scope.interface is interface
        assert scope.rule is interface.rule
        assert scope.rule.implementation is interface.rule.implementation
        assert scope.applicability is ProofStatus.UNKNOWN
        assert index.lifecycle_scope(interface.region) is scope
    assert dumps(graph) == payload
    assert dumps(loads(payload)) == payload


def test_scope_is_immutable_has_no_authority_constructor_and_raw_getters_stay_strict():
    graph = session_release_program()
    index = ProgramIndex(graph)
    scope = index.lifecycle_scope(graph.driver_interfaces[0].region)
    assert tuple(field.name for field in fields(LifecycleScope)) == ("declaration", "interface")
    assert not hasattr(scope, "__dict__")
    with pytest.raises((FrozenInstanceError, TypeError)):
        scope.applicability = ProofStatus.PROVEN
    with pytest.raises(FrozenInstanceError):
        scope.interface = None
    with pytest.raises(TypeError):
        LifecycleScope(scope.declaration, scope.interface, applicability=ProofStatus.PROVEN)
    with pytest.raises(TypeError):
        index.lifecycle_scope("region")
    with pytest.raises(KeyError):
        index.lifecycle_scope(RegionID("missing"))
    with pytest.raises(TypeError):
        index.lifecycle_after(graph.session_updates[0].operation, facts=object())


def test_before_after_and_edge_points_keep_original_operation_and_actual_successor():
    graph = session_release_program(binding="NORMAL_COMPLETION")
    index = ProgramIndex(graph)
    row = graph.session_updates[0]
    operation = index.operations[row.operation]
    scope = index.lifecycle_scope(graph.driver_interfaces[0].region)
    for method, position in ((index.lifecycle_before, LifecyclePosition.BEFORE),
                             (index.lifecycle_after, LifecyclePosition.AFTER)):
        point = method(row.operation)
        assert point.scope is scope and point.operation is operation
        assert point.position is position
        assert point.successor_index is point.successor is None
    for number, successor in enumerate(operation.terminator.successors):
        point = index.lifecycle_edge(row.operation, number)
        assert point.position is LifecyclePosition.EDGE
        assert point.operation is operation and point.scope is scope
        assert point.successor_index == number
        assert point.successor is successor
    point = index.lifecycle_before(row.operation)
    with pytest.raises(FrozenInstanceError):
        point.operation = None
    with pytest.raises(ValueError):
        replace(point, successor_index=0)
    with pytest.raises(TypeError):
        replace(point, position="BEFORE")
    edge = index.lifecycle_edge(row.operation, 0)
    for bad in (True, -1, len(operation.terminator.successors)):
        with pytest.raises(ValueError):
            index.lifecycle_edge(row.operation, bad)
        with pytest.raises(ValueError):
            replace(edge, successor_index=bad)
    for method in (index.lifecycle_before, index.lifecycle_after):
        with pytest.raises(TypeError):
            method("operation")
        with pytest.raises(KeyError):
            method(OperationID("missing"))


@pytest.mark.parametrize("binding", ("AFTER_OPERATION", "NORMAL_COMPLETION"))
def test_detached_publications_keep_source_chain_and_real_post_location(binding):
    graph = session_release_program(binding=binding)
    if binding == "NORMAL_COMPLETION":
        identity = graph.session_updates[0].operation
        operation = next(op for op in graph.operations if op.id == identity)
        operation = replace(operation, terminator=replace(operation.terminator,
            successors=tuple(reversed(operation.terminator.successors))))
        graph = replace(graph, operations=tuple(operation if old.id == identity else old
                                                for old in graph.operations))
    index = ProgramIndex(graph)
    session = index.session_publication(graph.session_updates[0].operation)
    release = index.terminal_release_publication(graph.terminal_frame_releases[0].operation)
    assert session.point.operation is index.operations[session.update.operation]
    assert release.point.operation is index.operations[release.release.operation]
    assert session.point.scope is release.point.scope
    assert release.point.position is LifecyclePosition.BEFORE
    if binding == "AFTER_OPERATION":
        assert session.point.position is LifecyclePosition.AFTER
        assert session.point.successor is session.normal_successor is None
    else:
        assert session.point.position is LifecyclePosition.EDGE
        assert session.point.successor_index == 1
        assert session.point.successor is session.normal_successor
        assert session.point.successor.kind is ExitKind.NORMAL
    del index
    scope = session.point.scope
    assert scope.declaration is graph.driver_lifecycles[0]
    assert scope.rule.implementation is graph.driver_interfaces[0].rule.implementation
    assert scope.applicability is release.point.scope.applicability is ProofStatus.UNKNOWN
    assert release.point.terminal.is_finished(release.owner.use.value)
    assert release.sources[0].commit is graph.body_outcome_commits[0]


def test_unknown_callback_does_not_change_scope_or_turn_finished_history_into_current_post():
    graph = session_release_program(callback=True)
    index = ProgramIndex(graph)
    session = index.session_publication(graph.session_updates[0].operation)
    release = index.terminal_release_publication(graph.terminal_frame_releases[0].operation)
    assert session.point.session.posts
    assert not release.point.session.posts
    assert release.point.terminal.is_finished(release.owner.use.value)
    assert session.point.scope is release.point.scope
    assert release.point.scope.applicability is ProofStatus.UNKNOWN
