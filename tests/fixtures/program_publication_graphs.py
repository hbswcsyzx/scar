"""D2.1 declared publication paths over the existing D1 driver fixtures."""
from dataclasses import replace

from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.lifecycle import BodyOutcomeCommit, DriverLifecycle, DriveOutcomeRef
from scar.ir.program.model import (
    AccessMode, Behavior, BlockArgument, Footprint, FootprintKind, Operation,
    OperationResult, ReferenceValue, StateAccess, StateVersionValue, Use, UseRole,
)
from tests.fixtures.program_driver_graphs import driver_program


def publication_program(*, target="start", extra_domain=False, strict_subset=False,
                        create=False, direct_owner=False, body_graph=None):
    graph = driver_program(target=target, extra_domain=extra_domain or strict_subset,
                           create=create, body_graph=body_graph)
    drive, = graph.body_drives
    drive_op = next(op for op in graph.operations if op.id == drive.operation)
    interface, = graph.driver_interfaces
    if strict_subset:
        all_domains = tuple(location.id for location in graph.locations)
        interface = replace(interface, lifecycle=all_domains)
    region = next(region for region in graph.regions if region.id == interface.region)
    blocks = {block.id: block for block in region.blocks}
    values = {value.id: value for value in graph.values}
    operations = {op.id: op for op in graph.operations}
    drive_uses = {use.id: use for use in drive_op.uses}
    original_owner = drive_uses[drive.instance].value
    new_values, new_operations, commits, successors, forwards = [], [], [], [], []
    write_location = interface.lifecycle[0]
    for number, edge in enumerate(drive_op.terminator.successors):
        landing = blocks[edge.block]
        operation = OperationID(f"publication.{number}")
        arguments = landing.arguments
        if direct_owner:
            owner = original_owner
            successor = edge
        else:
            owner = ValueID(f"publication.{number}.owner")
            new_values.append(ReferenceValue(owner, region.id, BlockArgument(landing.id, len(arguments))))
            forward = Use(UseID(f"publication.{number}.forward"), original_owner, UseRole.REFERENCE)
            forwards.append(forward)
            arguments = (*arguments, owner)
            successor = replace(edge, arguments=(*edge.arguments, forward.id))
        successors.append(successor)
        instance = Use(UseID(f"publication.{number}.instance"), owner, UseRole.REFERENCE)
        uses, accesses, afters, replacement = [instance], [], [], {}
        current = {values[value].location: value for value in landing.arguments
                   if isinstance(values[value], StateVersionValue)}
        for index, location in enumerate(interface.lifecycle):
            before = Use(UseID(f"publication.{number}.before.{index}"), current[location], UseRole.STATE_CONTENT)
            uses.append(before)
            if location == write_location:
                after = ValueID(f"publication.{number}.after.{index}")
                new_values.append(StateVersionValue(after, region.id, OperationResult(operation, len(afters)), location))
                afters.append(after)
                replacement[current[location]] = after
                accesses.append(StateAccess(location, before.id, AccessMode.READ_WRITE, after,
                                            Footprint(FootprintKind.WHOLE)))
            else:
                accesses.append(StateAccess(location, before.id, AccessMode.READ,
                                            footprint=Footprint(FootprintKind.WHOLE)))
        publication = Operation(operation, "declared body publication",
            (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), tuple(uses), tuple(afters),
            tuple(accesses), effects_complete=True)
        new_operations.append(publication)
        commits.append(BodyOutcomeCommit(operation, DriveOutcomeRef(drive.operation, edge.source), instance.id))
        for operation_id in landing.operations:
            old = operations[operation_id]
            operations[operation_id] = replace(old, uses=tuple(
                replace(use, value=replacement.get(use.value, use.value)) for use in old.uses))
        blocks[landing.id] = replace(landing, arguments=arguments,
                                     operations=(operation, *landing.operations))
    operations[drive_op.id] = replace(drive_op, uses=(*drive_op.uses, *forwards),
                                      terminator=replace(drive_op.terminator, successors=tuple(successors)))
    return replace(graph,
        regions=tuple(replace(item, blocks=tuple(blocks[block.id] for block in item.blocks))
                      if item.id == region.id else item for item in graph.regions),
        operations=(*operations.values(), *new_operations), values=(*graph.values, *new_values),
        driver_interfaces=(interface,), driver_lifecycles=(DriverLifecycle(region.id),),
        body_outcome_commits=tuple(commits))
