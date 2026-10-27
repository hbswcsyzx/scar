"""Detached public completion queries over one original ProgramIndex."""
from copy import deepcopy

from scar.ir.execution.validity_budget import ValidityBudget
from .protocol_connection_flow import ConnectionContext
from .protocol_packet_routes import completion_continuations as _query


def completion_continuations(index, source, *, start=None, choices=(), cross_resume=False,
                             budget=4096):
    shared = ValidityBudget(budget)
    ctx = ConnectionContext(index.graph, index=index, budget=shared)
    guards = ctx.selected_edges(choices)
    ctx._returns.guards = guards
    result = _query(ctx, source, start=start, choices=guards, cross_resume=cross_resume)
    return deepcopy({**result, 'budget': {'limit': shared.limit, 'used': shared.used,
        'truncated': shared.truncated, 'costs': dict(shared.costs)},
        'preparation': dict(ctx.preparation)})
