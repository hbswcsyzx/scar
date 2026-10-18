"""Activation-local copies and fresh pending values from canonical CFG operands.

Call after core, lexical ownership and cleanup entry/stack validation.  These
derived facts neither store another producer graph nor prove source/runtime
cleanup behavior.  Freshness here concerns this activation, not loop iteration
identity or the replacement's final destination.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import AbstractSet, Mapping, TYPE_CHECKING

from .control import ProtocolValueKind
from .ids import BlockID, OperationID, ValueID
from .model import BlockArgument, OperationResult, ProgramGraph, ProtocolValue
from .resumption import SavedInput, SavedRole, saved_actual_use

if TYPE_CHECKING:
    from .cleanup import CleanupInterface


@dataclass(frozen=True, slots=True)
class CleanupForwardFacts:
    slice_blocks: frozenset[BlockID]
    pending: frozenset[ValueID]
    context: frozenset[ValueID]
    fresh: frozenset[ValueID]


def _must_forward(
    seeds: AbstractSet[ValueID],
    incoming: Mapping[ValueID, tuple[ValueID | None, ...]],
) -> frozenset[ValueID]:
    """Require all incoming copies, with a seed for every surviving cycle.

    ``None`` is a noncopy boundary.  Incoming lists retain every actual/formal
    binding, including different successors of the same predecessor.  First
    find seed reachability (OR least fixed point), then descend from that set
    using AND.  Intersecting independent OR/AND solutions only at the end would
    leave seeded phis polluted by unsupported cycles in the result.
    """
    reachable = set(seeds)
    while True:
        added = {formal for formal, sources in incoming.items()
                 if formal not in reachable
                 and any(source in reachable for source in sources)}
        if not added:
            break
        reachable.update(added)

    must = reachable
    while True:
        removed = {formal for formal, sources in incoming.items()
                   if formal in must and formal not in seeds
                   and (not sources or any(source not in must for source in sources))}
        if not removed:
            return frozenset(must)
        must.difference_update(removed)


def derive_cleanup_forward(
    graph: ProgramGraph,
    interface: CleanupInterface,
    *,
    scope_blocks: frozenset[BlockID],
    operation_blocks: Mapping[OperationID, BlockID],
    dominators: Mapping[BlockID, AbstractSet[BlockID]],
) -> CleanupForwardFacts:
    """Derive copies of this entry's pending/context and local fresh pending.

    ``scope_blocks`` contains the cleanup's complete lexical subtree.  Its
    entry must be the sole entrance, with its unique Enter first, and the
    caller must already have checked cleanup stack/exit coverage.  We cut
    reentry rather than propagating previous visits through entry parameters.
    All real incoming edges to other slice blocks participate; an edge from
    outside this activation supplies False even if its operand names a seed.
    """
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    operations = {operation.id: operation for operation in graph.operations}
    values = {value.id: value for value in graph.values}

    reached: set[BlockID] = set()
    pending_blocks = [interface.entry]
    while pending_blocks:
        block_id = pending_blocks.pop()
        if block_id in reached or block_id not in scope_blocks:
            continue
        reached.add(block_id)
        terminator = operations[blocks[block_id].operations[-1]].terminator
        pending_blocks.extend(edge.block for edge in terminator.successors
                              if edge.block != interface.entry)
    slice_blocks = frozenset(reached)

    incoming: dict[ValueID, list[ValueID | None]] = {
        value.id: [] for value in graph.values
        if isinstance(value, ProtocolValue)
        and isinstance(value.origin, BlockArgument)
        and value.origin.block in slice_blocks
        and value.origin.block != interface.entry
    }
    for block in blocks.values():
        operation = operations[block.operations[-1]]
        own = {use.id: use.value for use in operation.uses}
        for edge in operation.terminator.successors:
            if edge.block not in slice_blocks or edge.block == interface.entry:
                continue
            for actual, formal in zip(edge.arguments, blocks[edge.block].arguments):
                if formal in incoming:
                    actual_use = saved_actual_use(operation, actual)
                    source = own.get(actual_use) if block.id in slice_blocks else None
                    if isinstance(actual, SavedInput) and source is not None:
                        role = operation.terminator.saved[actual.saved_slot].role
                        protocol = getattr(values[source], "protocol", None)
                        if ((protocol is ProtocolValueKind.PENDING_COMPLETION
                             and role is not SavedRole.PENDING_COMPLETION)
                                or (protocol is ProtocolValueKind.SAVED_HANDLED_CONTEXT
                                    and role is not SavedRole.CLEANUP_CONTEXT)):
                            source = None
                    incoming[formal].append(source)
    copies = {formal: tuple(sources) for formal, sources in incoming.items()}

    enter, = (item for item in graph.cleanup_enters if item.cleanup == interface.scope)
    fresh_seeds = set()
    for definition in graph.pending_completions:
        value = values[definition.value]
        if (not isinstance(value, ProtocolValue)
                or value.protocol is not ProtocolValueKind.PENDING_COMPLETION
                or not isinstance(value.origin, OperationResult)):
            continue
        producer_block = operation_blocks[value.origin.operation]
        if (producer_block in slice_blocks
                and interface.entry in dominators.get(producer_block, ())):
            fresh_seeds.add(value.id)

    return CleanupForwardFacts(
        slice_blocks,
        _must_forward(frozenset((interface.pending_argument,)), copies),
        _must_forward(frozenset((enter.saved_context,)), copies),
        _must_forward(fresh_seeds, copies),
    )


__all__ = ["CleanupForwardFacts", "derive_cleanup_forward"]
