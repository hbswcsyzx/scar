"""Declared body publication, after the canonical core and D1 checks.

No actual native fields, runtime object identity, guard execution, session state,
reference ownership or transformation authority is inferred by these checks.
"""
from __future__ import annotations

from .drivers import BodyDriveTerminator
from .ids import UseID
from .model import (
    AccessMode, Behavior, FootprintKind, ReferenceValue, StateVersionValue, UseRole,
)


def body_publication_errors(graph, *, operation_blocks, region_domains, incoming_edges):
    """Validate explicit scopes and each exact source/owner/current-state join."""
    errors = []

    def error(code, path, message):
        errors.append((code, str(path), message))

    values = {row.id: row for row in graph.values}
    operations = {row.id: row for row in graph.operations}
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    owners = {block.id: region.id for region in graph.regions for block in region.blocks}
    interfaces = {row.region: row for row in graph.driver_interfaces}
    drives = {row.operation: row for row in graph.body_drives}
    scopes = {row.region for row in graph.driver_lifecycles}
    commits = {row.operation: row for row in graph.body_outcome_commits}

    for scope in graph.driver_lifecycles:
        if scope.region not in interfaces:
            error("publication_scope", scope.region, "lifecycle scope requires its existing DriverInterface")

    expected = {}
    for drive_id, drive in drives.items():
        region_id = owners[operation_blocks[drive_id]]
        if region_id not in scopes:
            continue
        for edge in operations[drive_id].terminator.successors:
            expected[(drive_id, edge.source)] = edge

    by_outcome = {}
    for row in graph.body_outcome_commits:
        op = operations.get(row.operation)
        if op is None:
            error("publication_operation", row.operation, "publication must name its real operation")
            continue
        region_id = owners[operation_blocks[row.operation]]
        interface = interfaces.get(region_id)
        if region_id not in scopes or interface is None:
            error("publication_scope", row.operation, "publication requires its owning enabled driver scope")
            continue
        drive = drives.get(row.outcome.drive)
        drive_op = operations.get(row.outcome.drive)
        if (drive is None or drive_op is None
                or type(drive_op.terminator) is not BodyDriveTerminator
                or owners[operation_blocks[drive.operation]] != region_id):
            error("publication_outcome", row.operation, "publication requires a BodyDrive in this driver")
            continue
        edge = next((item for item in drive_op.terminator.successors
                     if item.source == row.outcome.source), None)
        if edge is None:
            error("publication_outcome", row.operation, "source must be an actual outcome edge of this drive")
            continue
        key = (row.outcome.drive, row.outcome.source)
        by_outcome.setdefault(key, []).append(row.operation)
        landing = blocks[edge.block]
        if (operation_blocks[row.operation] != edge.block
                or landing.operations[0] != row.operation
                or len(incoming_edges[edge.block]) != 1):
            error("publication_landing", row.operation, "commit must be first on its exact private outcome landing")

        own = {use.id: use for use in op.uses}
        instance = own.get(row.instance)
        drive_uses = {use.id: use for use in drive_op.uses}
        actual_owner = drive_uses[drive.instance].value
        owner_matches = instance is not None and instance.value == actual_owner
        if instance is not None and instance.value in landing.arguments:
            index = landing.arguments.index(instance.value)
            actual = edge.arguments[index]
            owner_matches = (type(actual) is UseID and actual in drive_uses
                             and drive_uses[actual].value == actual_owner)
        if (instance is None or instance.role is not UseRole.REFERENCE
                or not isinstance(values[instance.value], ReferenceValue) or not owner_matches):
            error("publication_owner", row.operation, "owner must copy this drive's original instance, not a produced payload")

        if (op.terminator is not None or op.callee is not None or op.call_arguments
                or op.invoke_arguments or op.completions or not op.effects_complete
                or set(op.behaviors) != {Behavior.CONTROL, Behavior.READ, Behavior.WRITE}):
            error("publication_shape", row.operation, "publication is a complete callback-free ordinary state intrinsic")
        lifecycle = set(interface.lifecycle)
        if not lifecycle.issubset(region_domains[region_id]):
            # D1 already checks this; keep the local obligation explicit.
            error("publication_domains", row.operation, "lifecycle domains must belong to this driver")
        writes = set()
        state_uses = set()
        for access in op.accesses:
            state_uses.add(access.before)
            if (access.location not in lifecycle
                    or access.mode not in (AccessMode.READ, AccessMode.READ_WRITE)
                    or access.footprint.kind is not FootprintKind.WHOLE
                    or access.full_overwrite
                    or access.reference not in (None, row.instance)):
                error("publication_access", row.operation, "publication accesses are whole current READ/RW lifecycle domains")
            before = own.get(access.before)
            if (before is None or before.role is not UseRole.STATE_CONTENT
                    or not isinstance(values[before.value], StateVersionValue)):
                error("publication_state", row.operation, "publication must use its canonical state access inputs")
            if access.mode is AccessMode.READ_WRITE:
                writes.add(access.after)
        if not writes:
            error("publication_writes", row.operation, "body publication requires at least one actual lifecycle state write")
        if set(op.results) != writes:
            error("publication_results", row.operation, "publication results must be exactly its real written after states")
        if set(own) != state_uses | {row.instance}:
            error("publication_uses", row.operation, "only the original instance and access-before Uses belong to publication")

    for outcome, edge in expected.items():
        found = by_outcome.get(outcome, ())
        if len(found) != 1:
            error("publication_coverage", outcome[0], "each enabled source edge requires exactly one body publication")
        elif blocks[edge.block].operations[0] not in commits:
            error("publication_landing", found[0], "source landing must begin with its declared publication")
    return tuple(errors)


__all__ = ["body_publication_errors"]
