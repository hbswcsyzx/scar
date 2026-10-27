"""No-entry protocol/lifecycle compositions over the original state SSA.

These are declaration fixtures.  They do not execute Python throw, prove native
instance identity, or infer that a frame's references have been freed.
"""
from dataclasses import replace

from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.lifecycle import SessionPost
from scar.ir.program.model import (
    AccessMode, Behavior, BlockArgument, ExitKind, Footprint, FootprintKind,
    Operation, ReferenceValue, StateAccess, StateVersionValue, Use, UseRole,
)
from scar.ir.program.protocols import OperationSiteSubject
from scar.ir.program.state_addresses import ExistingAccess
from tests.fixtures.program_protocol_graphs import no_entry_throw_program
from tests.fixtures.program_session_release_graphs import _Tail


def _prefix_session(graph, details):
    """A real HOLD update before the broad transition, with a separate request."""
    interface, = graph.driver_interfaces
    region = next(region for region in graph.regions if region.id == interface.region)
    entry = next(block for block in region.blocks if block.id == region.entry)
    request = ReferenceValue(ValueID("protocol.release.request"), region.id,
                             BlockArgument(entry.id, len(entry.arguments)))
    graph = replace(graph, values=(*graph.values, request), regions=tuple(
        replace(item, blocks=tuple(replace(block, arguments=(*block.arguments, request.id))
            if block.id == entry.id else block for block in item.blocks))
        if item.id == region.id else item for item in graph.regions))
    tail = _Tail(graph, details["processing"], body=details["owner"], request=request.id)
    tail.metadata(SessionPost.HOLD, "protocol.release.incoming.hold")
    graph = tail.finish()
    return graph, request.id, graph.session_updates[-1].operation


def _ordinary_read_transition(graph, details):
    """Attach INITIAL_THROW to a real ordinary READ without inventing a write."""
    selected = details["selected_edge"]
    terminal = details["terminals"][selected]
    interface, = graph.driver_interfaces
    region = next(region for region in graph.regions if region.id == interface.region)
    block = next(block for block in region.blocks if terminal in block.operations)
    values = {value.id: value for value in graph.values}
    identity = OperationID("protocol.release.readonly")
    owner = Use(UseID("protocol.release.readonly.instance"),
                details["owner_formals"][selected], UseRole.REFERENCE)
    raw = Use(UseID("protocol.release.readonly.raw"),
              interface.scheduler_request, UseRole.PROTOCOL)
    packet = Use(UseID("protocol.release.readonly.packet"), block.arguments[1], UseRole.PROTOCOL)
    states = tuple(Use(UseID(f"protocol.release.readonly.state.{index}"), value, UseRole.STATE_CONTENT)
                   for index, value in enumerate(block.arguments)
                   if isinstance(values[value], StateVersionValue))
    accesses = tuple(StateAccess(values[use.value].location, use.id, AccessMode.READ,
                                footprint=Footprint(FootprintKind.WHOLE)) for use in states)
    operation = Operation(identity, "ordinary read is not a lifecycle transition",
                          (Behavior.CONTROL, Behavior.READ), (owner, raw, packet, *states),
                          accesses=accesses, effects_complete=True)
    row = details["row"]
    contract = replace(row.contract, instance_use=owner.id, effective_request_use=raw.id,
        state_sites=tuple(ExistingAccess(identity, index) for index in range(len(accesses))),
        selected_edge=None)
    row = replace(row, operation=identity, slot=0, contract=contract)
    graph = replace(graph, operations=(*graph.operations, operation),
        regions=tuple(replace(item, blocks=tuple(replace(current,
            operations=(*current.operations[:-1], identity, terminal))
            if current.id == block.id else current for current in item.blocks))
            if item.id == region.id else item for item in graph.regions),
        protocol_operations=(row,), protocol_scopes=tuple(replace(scope,
            subject=OperationSiteSubject(region.id, identity)) for scope in graph.protocol_scopes))
    return graph, {**details, "transition": identity, "row": row}


def protocol_release_program(*, selected=ExitKind.NORMAL, reject=False,
                             ordinary_read=False, session_before=False,
                             release=True, release_edge=None, both_initial_edges=False):
    """Return ``(graph, details)``; each release consumes its real current states.

    ``release_edge`` deliberately permits the nonselected branch for negative
    tests.  ``both_initial_edges`` declares two real routes on one INVOKE, while
    still inserting only one release.  No extra producer or lifecycle graph is
    created.  The original helper remains callback-capable and kills session P.
    """
    if ordinary_read and both_initial_edges:
        raise ValueError("ordinary READ fixture has one declared transition")
    graph, details = no_entry_throw_program(selected=selected, reject=reject)
    if both_initial_edges:
        other = ExitKind.RAISE if selected is ExitKind.NORMAL else ExitKind.NORMAL
        _, other_details = no_entry_throw_program(selected=other)
        graph = replace(graph, protocol_operations=(*graph.protocol_operations, other_details["row"]))
    request, incoming_post = None, None
    if session_before:
        graph, request, incoming_post = _prefix_session(graph, details)
    details = {**details, "transition": details["processing"]}
    if ordinary_read:
        graph, details = _ordinary_read_transition(graph, details)
    edge = details["selected_edge"] if release_edge is None else release_edge
    if release:
        tail = _Tail(graph, details["terminals"][edge],
                     body=details["owner_formals"][edge], request=request)
        tail.release(edge)
        graph = tail.finish()
        release_operation = graph.terminal_frame_releases[-1].operation
    else:
        release_operation = None
    return graph, {**details, "request": request, "incoming_post": incoming_post,
        "release": release_operation, "release_edge": edge,
        "released_owner": details["owner_formals"][edge],
        "both_initial_edges": both_initial_edges}


__all__ = ["protocol_release_program"]
