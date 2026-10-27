"""C1 integration regressions reproduced before the final gate."""
from dataclasses import replace

import pytest

from scar.ir.program import CleanupRouteTerminator, Use, UseID, UseRole, dumps
from scar.ir.program.validation import validate
from tests.fixtures.program_cleanup_graphs import resume_multistate_graph


class RouteSubclass(CleanupRouteTerminator):
    pass


def test_new_route_subclass_cannot_lose_its_required_wire_discriminator():
    graph = resume_multistate_graph()
    route = next(o for o in graph.operations if isinstance(o.terminator, CleanupRouteTerminator))
    subclass = RouteSubclass(route.terminator.pending, route.terminator.successors)
    with pytest.raises(TypeError, match="exact CleanupRouteTerminator"):
        replace(route, terminator=subclass)


def test_validator_rechecks_forged_route_subclass_before_serialization():
    graph = resume_multistate_graph()
    route = next(o for o in graph.operations if isinstance(o.terminator, CleanupRouteTerminator))
    forged = replace(route)
    object.__setattr__(forged, "terminator", RouteSubclass(
        route.terminator.pending, route.terminator.successors))
    graph = replace(graph, operations=tuple(forged if o.id == route.id else o for o in graph.operations))
    assert any(i.code == "schema" and "exact CleanupRouteTerminator" in i.message
               for i in validate(graph))
    with pytest.raises(ValueError, match="exact CleanupRouteTerminator"):
        dumps(graph)


def test_saved_context_cannot_escape_as_an_ordinary_operation_operand():
    graph = resume_multistate_graph()
    context = graph.cleanup_enters[0].saved_context
    work = next(o for o in graph.operations if o.id.value == "shared.cleanup.write")
    changed = replace(work, uses=(*work.uses, Use(
        UseID("regression.context.escape"), context, UseRole.PROTOCOL)))
    graph = replace(graph, operations=tuple(changed if o.id == work.id else o for o in graph.operations))
    assert {i.code for i in validate(graph)} == {"cleanup_context_escape"}


def test_removing_pop_cannot_hide_behind_current_state_and_valid_pending_edges():
    graph = resume_multistate_graph()
    restore, = graph.cleanup_resumes
    work = next(o for o in graph.operations if o.id == restore.operation)
    changed = replace(work, uses=tuple(u for u in work.uses
                                     if u.id not in (restore.pending, restore.context)))
    graph = replace(graph, cleanup_resumes=(), operations=tuple(
        changed if o.id == work.id else o for o in graph.operations))
    codes = {i.code for i in validate(graph)}
    assert "cleanup_stack_entry" in codes
    assert codes <= {"cleanup_stack_entry", "cleanup_exit_bypass"}
