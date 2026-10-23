"""Small derived queries over a validated resumable body's ordinary CFG."""
from __future__ import annotations

from collections.abc import Mapping

from scar.ir.program.ids import BlockID, OperationID
from scar.ir.program.model import Operation, Region, TerminatorKind


_BODY_OUTCOMES = frozenset({
    TerminatorKind.SUSPEND,
    TerminatorKind.RETURN,
    TerminatorKind.RAISE,
})


def first_body_outcome_operations(
    region: Region,
    operations: Mapping[OperationID, Operation],
    start: BlockID,
) -> tuple[OperationID, ...]:
    """Return terminal body operations reached before the next suspension.

    The caller supplies the already validated graph's operation mapping. Every
    ordinary CFG successor is followed, including INVOKE and typed C0/C1
    routing. A SUSPEND is an outcome for this drive; its temporal successors
    are deliberately not traversed. Operation IDs are sorted only to make the
    result stable; that order is not an execution order.
    """
    blocks = {block.id: block for block in region.blocks}
    if type(start) is not BlockID:
        raise TypeError("body outcome start must be BlockID")
    if start not in blocks:
        raise ValueError("body outcome start must belong to the region")

    pending = [start]
    seen_blocks: set[BlockID] = set()
    found: set[OperationID] = set()

    while pending:
        block_id = pending.pop()
        if block_id in seen_blocks:
            continue
        seen_blocks.add(block_id)
        block = blocks[block_id]
        if not block.operations:
            raise ValueError("validated body block must have a terminator")
        terminator = operations[block.operations[-1]].terminator
        if terminator is None:
            raise ValueError("validated body block must end in a terminator")
        if terminator.kind in _BODY_OUTCOMES:
            found.add(block.operations[-1])
            continue
        for successor in terminator.successors:
            if successor.block not in blocks:
                raise ValueError("validated body CFG successor leaves its region")
            if successor.block not in seen_blocks:
                pending.append(successor.block)

    return tuple(sorted(found, key=lambda identity: identity.wire))


__all__ = ["first_body_outcome_operations"]
