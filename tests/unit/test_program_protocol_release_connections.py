"""New no-entry → historical terminal fact → original-state release joins."""
from dataclasses import replace

import pytest

from scar.ir.program.ids import OperationID
from scar.ir.program.lifecycle import SessionPost
from scar.ir.program.model import ExitKind, StateVersionValue
from scar.ir.program.queries import NoEntryPublication, ProgramIndex
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_protocol_release_graphs import protocol_release_program


def _operation(graph, identity):
    return next(operation for operation in graph.operations if operation.id == identity)


def _codes(graph):
    return {issue.code for issue in validate(graph)}


def _change_use(graph, operation_id, use_id, value):
    return replace(graph, operations=tuple(replace(operation, uses=tuple(
        replace(use, value=value) if use.id == use_id else use for use in operation.uses))
        if operation.id == operation_id else operation for operation in graph.operations))


@pytest.mark.parametrize("selected", (ExitKind.NORMAL, ExitKind.RAISE))
def test_initial_throw_exact_post_edge_publishes_finished_owner_before_real_release(selected):
    graph, details = protocol_release_program(selected=selected)
    require_valid(graph)
    index = ProgramIndex(graph)
    helper = _operation(graph, details["processing"])
    publication, = index.no_entry_publications(helper.id)
    release = index.terminal_release_publication(details["release"])
    assert isinstance(publication, NoEntryPublication)
    assert release.sources == (publication,)
    assert publication.declaration == details["row"]
    assert publication.selected_edge == details["row"].contract.selected_edge
    assert publication.source.source == details["row"].contract.selected_input
    assert publication.source.edge == details["selected_edge"]
    assert publication.terminal.operation == details["terminals"][details["selected_edge"]]
    assert publication.instance.use.id == details["row"].contract.instance_use
    assert release.owner.use.value == details["released_owner"]
    assert release.point.terminal.is_finished(details["released_owner"])
    assert not index.lifecycle_before(helper.id).terminal.is_finished(details["owner"])
    assert not index.lifecycle_after(helper.id).terminal.is_finished(details["owner"])
    selected_block = helper.terminator.successors[details["selected_edge"]].block
    region = next(region for region in graph.regions if region.id == graph.root)
    block = next(block for block in region.blocks if block.id == selected_block)
    states = {index.values[value].location: value for value in block.arguments
              if isinstance(index.values[value], StateVersionValue)}
    operation = _operation(graph, details["release"])
    assert {index.use_site(access.before).use.value for access in operation.accesses} == set(states.values())
    # Both helper alternatives are actual host RAISE, including helper NORMAL.
    terminal = _operation(graph, details["terminals"][details["selected_edge"]])
    assert terminal.terminator.kind.value == "RAISE"


@pytest.mark.parametrize("selected", (ExitKind.NORMAL, ExitKind.RAISE))
def test_unselected_branch_cannot_release_an_owner_finished_only_on_the_other_edge(selected):
    selected_index = 0 if selected is ExitKind.NORMAL else 1
    graph, _ = protocol_release_program(selected=selected, release_edge=1 - selected_index)
    assert "terminal_release_unfinished" in _codes(graph)


@pytest.mark.parametrize("selected", (ExitKind.NORMAL, ExitKind.RAISE))
def test_preentry_rejection_is_a_valid_route_but_does_not_publish_or_allow_release(selected):
    graph, details = protocol_release_program(selected=selected, reject=True, release=False)
    require_valid(graph)
    index = ProgramIndex(graph)
    assert index.no_entry_publications(details["transition"]) == ()
    assert not index.lifecycle_before(details["terminals"][details["selected_edge"]]).terminal.is_finished(
        details["released_owner"])
    with_release, _ = protocol_release_program(selected=selected, reject=True)
    assert "terminal_release_unfinished" in _codes(with_release)


@pytest.mark.parametrize("selected", (ExitKind.NORMAL, ExitKind.RAISE))
def test_readonly_annotation_cannot_create_a_terminal_state_transition(selected):
    graph, details = protocol_release_program(selected=selected, ordinary_read=True, release=False)
    require_valid(graph)
    index = ProgramIndex(graph)
    assert index.no_entry_publications(details["transition"]) == ()
    assert not index.lifecycle_before(details["terminals"][details["selected_edge"]]).terminal.is_finished(
        details["released_owner"])
    report = index.protocol_obligations(details["scope"])
    assert any("no_entry_transition_effect_unproved" in row["gaps"]
               for scope in report["scopes"] for obligation in scope["obligations"]
               for row in obligation["rows"])
    with_release, _ = protocol_release_program(selected=selected, ordinary_read=True)
    assert "terminal_release_unfinished" in _codes(with_release)


@pytest.mark.parametrize("selected", (ExitKind.NORMAL, ExitKind.RAISE))
def test_broad_no_entry_helper_kills_current_session_post_while_exact_edge_retains_terminal_history(selected):
    graph, details = protocol_release_program(selected=selected, session_before=True)
    require_valid(graph)
    index = ProgramIndex(graph)
    before = index.lifecycle_before(details["processing"])
    assert {fact.post for fact in before.session.for_pair(details["request"], details["owner"])} == {
        SessionPost.HOLD}
    for number, owner in enumerate(details["owner_formals"]):
        edge = index.lifecycle_edge(details["processing"], number)
        assert edge.session.for_pair(details["request"], owner) == ()
        assert edge.terminal.is_finished(owner) is (number == details["selected_edge"])
    release = index.terminal_release_publication(details["release"])
    assert release.point.session.for_pair(details["request"], details["released_owner"]) == ()
    assert release.point.terminal.is_finished(details["released_owner"])
    assert len(release.sources) == 1


def test_another_valid_reference_is_not_the_finished_release_owner():
    graph, details = protocol_release_program(session_before=True)
    declaration, = graph.terminal_frame_releases
    wrong = _change_use(graph, declaration.operation, declaration.owner, details["request"])
    assert "terminal_release_unfinished" in _codes(wrong)


@pytest.mark.parametrize("selected", (ExitKind.NORMAL, ExitKind.RAISE))
def test_original_input_state_cannot_replace_the_actual_partial_post_state_at_release(selected):
    graph, details = protocol_release_program(selected=selected, session_before=True)
    release = _operation(graph, details["release"])
    access = release.accesses[0]
    values = {value.id: value for value in graph.values}
    helper = _operation(graph, details["processing"])
    old = next(use.value for use in helper.uses if isinstance(values[use.value], StateVersionValue)
               and values[use.value].location == access.location)
    wrong = _change_use(graph, release.id, access.before, old)
    assert "stale_state" in _codes(wrong)


@pytest.mark.parametrize("selected", (ExitKind.NORMAL, ExitKind.RAISE))
def test_two_real_initial_routes_on_one_helper_keep_edge_facts_separate(selected):
    graph, details = protocol_release_program(selected=selected, both_initial_edges=True)
    require_valid(graph)
    index = ProgramIndex(graph)
    publications = index.no_entry_publications(details["processing"])
    assert {publication.selected_edge.successor_index for publication in publications} == {0, 1}
    for number, owner in enumerate(details["owner_formals"]):
        point = index.lifecycle_edge(details["processing"], number)
        assert point.terminal.is_finished(owner)
        assert not point.terminal.is_finished(details["owner_formals"][1 - number])
    # T is an explanatory set of possible static seed operations.  It does not
    # claim that every returned publication happened on this specific path.
    release = index.terminal_release_publication(details["release"])
    assert release.point.terminal.source_operations(details["released_owner"]) == {
        details["processing"]}
    assert release.sources == publications


@pytest.mark.parametrize("invalid,exception", (("preentry.source", TypeError),
                                               (OperationID("no.such.operation"), KeyError)))
def test_no_entry_publications_keeps_strict_canonical_operation_getter_contract(invalid, exception):
    graph, _ = protocol_release_program()
    with pytest.raises(exception):
        ProgramIndex(graph).no_entry_publications(invalid)


def test_existing_ordinary_operation_without_no_entry_declaration_has_no_publications():
    graph, details = protocol_release_program()
    index = ProgramIndex(graph)
    assert index.no_entry_publications(details["release"]) == ()

