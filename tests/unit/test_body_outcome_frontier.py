"""First-outcome frontier queries for validated resumable bodies."""
from dataclasses import replace

import pytest

from scar.ir.program.codec import dumps, loads
from scar.ir.program.ids import BlockID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, DataValue, LiteralOrigin, Successor, Terminator,
    TerminatorKind, UseRole,
)
from scar.ir.program.queries import BodyOutcomeSite, ProgramIndex
from scar.ir.program.resumption_flow import first_body_outcome_operations
from scar.ir.program.validation import require_valid
from tests.fixtures.program_graphs import shared_body_calls_program
from tests.fixtures.program_resumption_graphs import (
    _Body, _use, resumption_cleanup_invoke_program,
    resumption_cleanup_program, resumption_loop_program, resumption_program,
    resumption_two_cuts_program,
)


def _site_map(sites):
    return {site.operation: site for site in sites}


def _assert_use_sites_are_canonical(index, sites):
    for site in sites:
        for use_site in site.values:
            assert use_site is index.use_site(use_site.use.id)


def _nonterminating_body():
    """Two blocks: Initial/Attach then an attached boolean self-loop."""
    from scar.ir.program.control import ProtocolValueKind as P

    body = _Body("frontier.diverging")
    world = body.argument("frontier.diverging.entry.world", "frontier.diverging.entry", 0,
                          body.world)
    context = body.argument("frontier.diverging.entry.context", "frontier.diverging.entry", 1,
                            body.context)
    frame = body.initial("frontier.diverging.initial")
    caller, attached_context = body.switch(
        "frontier.diverging.attach", frame, context, attach=True)

    loop_caller = body.argument("frontier.diverging.loop.caller", "frontier.diverging.loop", 0,
                                P.DRIVE_CALLER_CONTEXT)
    loop_world = body.argument("frontier.diverging.loop.world", "frontier.diverging.loop", 1,
                               body.world)
    loop_context = body.argument("frontier.diverging.loop.context", "frontier.diverging.loop", 2,
                                 body.context)
    condition = DataValue(
        ValueID("frontier.diverging.condition"),
        body.region, LiteralOrigin(True), "builtins.bool")
    body.values.append(condition)

    enter_uses = (
        _use("frontier.diverging.enter.caller", caller),
        _use("frontier.diverging.enter.world", world, UseRole.STATE_CONTENT),
        _use("frontier.diverging.enter.context", attached_context, UseRole.STATE_CONTENT),
    )
    body.add("frontier.diverging.enter", (Behavior.CONTROL,), enter_uses,
        terminator=Terminator(TerminatorKind.JUMP, (Successor(
            BlockID("frontier.diverging.loop"), tuple(use.id for use in enter_uses)),)))

    branch_uses = [_use("frontier.diverging.condition.use", condition.id, UseRole.DATA)]
    successors = []
    for edge_name in ("left", "right"):
        caller_use = _use(f"frontier.diverging.{edge_name}.caller", loop_caller)
        world_use = _use(f"frontier.diverging.{edge_name}.world", loop_world,
                         UseRole.STATE_CONTENT)
        context_use = _use(f"frontier.diverging.{edge_name}.context", loop_context,
                           UseRole.STATE_CONTENT)
        branch_uses.extend((caller_use, world_use, context_use))
        successors.append(Successor(BlockID("frontier.diverging.loop"),
                                    (caller_use.id, world_use.id, context_use.id)))
    body.add("frontier.diverging.loop.branch", (Behavior.CONTROL,), tuple(branch_uses),
        terminator=Terminator(TerminatorKind.BRANCH, tuple(successors),
                              condition=branch_uses[0].id))

    body.block("frontier.diverging.entry", (world, context), (
        "frontier.diverging.initial", "frontier.diverging.attach",
        "frontier.diverging.enter"))
    body.block("frontier.diverging.loop", (loop_caller, loop_world, loop_context),
               ("frontier.diverging.loop.branch",))
    return body.finish("frontier.diverging.entry", ())


def _two_body_graph():
    parent = resumption_program()
    child = resumption_cleanup_program()
    child_region = replace(child.regions[0], parent=parent.root)
    return replace(
        parent,
        regions=(*parent.regions, child_region),
        operations=(*parent.operations, *child.operations),
        values=(*parent.values, *child.values),
        locations=(*parent.locations, *child.locations),
        control_scopes=(*parent.control_scopes, *child.control_scopes),
        control_ports=(*parent.control_ports, *child.control_ports),
        pending_completions=(*parent.pending_completions, *child.pending_completions),
        handled_context_domains=(*parent.handled_context_domains,
                                 *child.handled_context_domains),
        cleanup_interfaces=(*parent.cleanup_interfaces, *child.cleanup_interfaces),
        cleanup_enters=(*parent.cleanup_enters, *child.cleanup_enters),
        cleanup_resumes=(*parent.cleanup_resumes, *child.cleanup_resumes),
        cleanup_replacements=(*parent.cleanup_replacements, *child.cleanup_replacements),
        resumable_bodies=(*parent.resumable_bodies, *child.resumable_bodies),
        frame_context_initials=(*parent.frame_context_initials,
                                *child.frame_context_initials),
        frame_context_attaches=(*parent.frame_context_attaches,
                                *child.frame_context_attaches),
        frame_context_detaches=(*parent.frame_context_detaches,
                                *child.frame_context_detaches),
    )


def test_entry_and_each_resume_landing_stop_at_their_first_outcome():
    graph = resumption_program()
    index = ProgramIndex(graph)

    entry = index.body_outcomes(RegionID("resume"))
    value_resume = index.body_outcomes(RegionID("resume"), BlockID("resume.value"))
    packet_resume = index.body_outcomes(RegionID("resume"), BlockID("resume.packet"))

    assert tuple(_site_map(entry)) == (OperationID("resume.suspend"),)
    assert tuple(_site_map(value_resume)) == (OperationID("resume.return"),)
    assert tuple(_site_map(packet_resume)) == (OperationID("resume.raise"),)
    suspend = _site_map(entry)[OperationID("resume.suspend")]
    assert suspend.kind is TerminatorKind.SUSPEND
    assert tuple(site.use.id for site in suspend.values) == (
        UseID("resume.suspend.export"),
        UseID("resume.suspend.world"),
        UseID("resume.suspend.context"),
    )
    assert UseID("resume.suspend.frame") not in {site.use.id for site in suspend.values}
    assert UseID("resume.suspend.x") not in {site.use.id for site in suspend.values}
    assert all(isinstance(site, BodyOutcomeSite) for site in (*entry, *value_resume, *packet_resume))
    for sites in (entry, value_resume, packet_resume):
        _assert_use_sites_are_canonical(index, sites)


def test_two_cut_queries_do_not_follow_the_next_temporal_edge():
    graph = resumption_two_cuts_program()
    index = ProgramIndex(graph)

    assert tuple(_site_map(index.body_outcomes(RegionID("resume")))) == (
        OperationID("resume.suspend"),)
    assert tuple(_site_map(index.body_outcomes(
        RegionID("resume"), BlockID("resume.value")))) == (
        OperationID("resume.second.suspend"),)
    assert tuple(_site_map(index.body_outcomes(
        RegionID("resume"), BlockID("resume.second")))) == (
        OperationID("resume.second.return"),)


def test_invoke_and_cleanup_routes_reach_both_first_body_outcomes():
    graph = resumption_cleanup_invoke_program()
    index = ProgramIndex(graph)

    entry = index.body_outcomes(RegionID("finally"))
    resumed = index.body_outcomes(RegionID("finally"), BlockID("finally.landing"))

    assert tuple(_site_map(entry)) == (OperationID("finally.suspend"),)
    assert set(_site_map(resumed)) == {
        OperationID("finally.return"), OperationID("finally.raise-exit.op")}
    assert _site_map(resumed)[OperationID("finally.return")].kind is TerminatorKind.RETURN
    assert _site_map(resumed)[OperationID("finally.raise-exit.op")].kind is TerminatorKind.RAISE


def test_branch_and_self_loop_are_explored_once_without_claiming_totality():
    graph = resumption_loop_program()
    index = ProgramIndex(graph)

    outcomes = index.body_outcomes(RegionID("resume"), BlockID("resume.value"))
    assert tuple(_site_map(outcomes)) == (OperationID("resume.return"),)


def test_valid_nonterminating_body_has_an_empty_frontier():
    graph = _nonterminating_body()
    require_valid(graph)
    assert ProgramIndex(graph).body_outcomes(graph.root) == ()


def test_nonresumable_region_is_unknown_and_start_endpoints_are_strict():
    plain = shared_body_calls_program()
    index = ProgramIndex(plain)
    assert index.body_outcomes(RegionID("caller")) is None

    body_index = ProgramIndex(resumption_loop_program())
    with pytest.raises(TypeError):
        body_index.body_outcomes("resume")
    with pytest.raises(KeyError):
        body_index.body_outcomes(RegionID("missing"))
    with pytest.raises(TypeError):
        body_index.body_outcomes(RegionID("resume"), "resume.value")
    with pytest.raises(KeyError):
        body_index.body_outcomes(RegionID("resume"), BlockID("missing"))
    with pytest.raises(ValueError):
        body_index.body_outcomes(RegionID("resume"), BlockID("resume.loop"))

    two_bodies = ProgramIndex(_two_body_graph())
    with pytest.raises(ValueError):
        two_bodies.body_outcomes(RegionID("resume"), BlockID("finally.landing"))


def test_pure_helper_and_query_leave_canonical_graph_wire_unchanged():
    graph = resumption_program()
    region = graph.regions[0]
    operations = {operation.id: operation for operation in graph.operations}
    assert first_body_outcome_operations(
        region, operations, region.entry) == (OperationID("resume.suspend"),)

    before = dumps(graph)
    original_values = graph.values
    original_origins = tuple(value.origin for value in graph.values)
    index = ProgramIndex(graph)
    sites = index.body_outcomes(RegionID("resume"))
    _assert_use_sites_are_canonical(index, sites)
    assert dumps(graph) == before
    assert graph.values is original_values
    assert all(value.origin is origin
               for value, origin in zip(graph.values, original_origins))
    assert loads(before) == graph

