"""Derived driver ports over canonical body definitions, without another graph.

These helpers do not validate a ProgramGraph, instantiate ProgramIndex, or
establish runtime correspondence. Callers validate ownership/frontier membership
separately; malformed lookups raise ValueError rather than inventing a port.
"""
from __future__ import annotations

from .model import TerminatorKind, value_type
from .resumption import SuspendTerminator


def body_drive_target(graph, drive):
    """Resolve the declared body and this drive's entry or resume landing."""
    from .drivers import BodyDrive, BodyResume, BodyStart

    if type(drive) is not BodyDrive:
        raise TypeError("body drive target needs an exact BodyDrive")
    bodies = {body.region for body in graph.resumable_bodies}
    regions = {region.id: region for region in graph.regions}
    target = drive.target
    if type(target) is BodyStart:
        region = regions.get(target.body)
        if region is None or region.id not in bodies:
            raise ValueError("start target must name a declared resumable body")
        return region, region.entry, None
    if type(target) is not BodyResume:
        raise ValueError("drive target must be BodyStart or BodyResume")
    source = next((op for op in graph.operations if op.id == target.suspend), None)
    if source is None or type(source.terminator) is not SuspendTerminator:
        raise ValueError("resume target must name a real Suspend operation")
    region = next((region for region in graph.regions
                   if any(source.id in block.operations for block in region.blocks)), None)
    if region is None or region.id not in bodies:
        raise ValueError("resume source must belong to a declared resumable body")
    if target.successor >= len(source.terminator.successors):
        raise ValueError("resume successor index exceeds the suspension signature")
    edge = source.terminator.successors[target.successor]
    return region, edge.block, edge


def body_outcome_uses(operation):
    """Return only the source operation's public handoff/terminal UseIDs."""
    term = operation.terminator
    if type(term) is SuspendTerminator:
        return (term.exported, *term.handoff)
    if term is not None and term.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
        return term.values
    raise ValueError("drive outcome source must be Suspend, Return or Raise")


def body_outcome_types(graph, source):
    """Derive one actual source's signature; this does not admit that source."""
    operation = next((op for op in graph.operations if op.id == source), None)
    if operation is None:
        raise ValueError("drive outcome source operation is missing")
    values = {value.id: value for value in graph.values}
    uses = {use.id: use for use in operation.uses}
    result = []
    for identity in body_outcome_uses(operation):
        use = uses.get(identity)
        if use is None or use.value not in values:
            raise ValueError("outcome signature must use the source's canonical operands")
        result.append(value_type(values[use.value]))
    return tuple(result)


__all__ = ["body_drive_target", "body_outcome_uses", "body_outcome_types"]
