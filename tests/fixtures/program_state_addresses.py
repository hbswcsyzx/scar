"""Small manual core graph for state-address validation.

The fixture uses one shared state carrier, two reference owners, an existing
resource requirement, and an INVOKE with real NORMAL/RAISE state ports. It is
not source recovery or an alias/runtime proof.
"""
from scar.ir.program.ids import (
    BlockID, LocationID, OperationID, RegionID, ResourceRequirementID, UseID, ValueID,
)
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, DataValue, ExitKind, ExitPort, Footprint, Operation,
    OperationResult, ProgramGraph, ReferenceValue, Region, StateAccess, StateLocation,
    StateVersionValue, Stability, Terminator, TerminatorKind, Use, UseRole, ValueKind,
    ValueType,
)
from scar.ir.program.state_addresses import (
    AddressCoverage, AddressEffect, Element, ExistingAccess, InvokeStateOperand,
    ReferenceOwner, ResourceOwner, StateAddressRefinement,
)
from scar.ir.program.resources import ResourceRequirement, ResourceRole, ResourceUse
from scar.ir.v2.contracts import ResourceKind


def _use(name, value, role=UseRole.DATA):
    return Use(UseID(name), ValueID(value), role)


def _data(name, origin, data_type="builtins.int"):
    return DataValue(ValueID(name), RegionID("address.root"), origin, data_type)


def _reference(name, origin, targets=("address.world",)):
    return ReferenceValue(
        ValueID(name), RegionID("address.root"), origin, name,
        tuple(LocationID(item) for item in targets), Footprint(),
    )


def _state(name, origin):
    return StateVersionValue(ValueID(name), RegionID("address.root"), origin,
                             LocationID("address.world"))


def state_address_program():
    """Return ``(ProgramGraph, details)`` with one access and one INVOKE site."""
    values = (
        _reference("address.source", BlockArgument(BlockID("address.entry"), 0)),
        _reference("address.destination", BlockArgument(BlockID("address.entry"), 1)),
        _reference("address.invoke_owner", BlockArgument(BlockID("address.entry"), 2)),
        _data("address.key", BlockArgument(BlockID("address.entry"), 3)),
        _state("address.world.initial", BlockArgument(BlockID("address.entry"), 4)),
        _state("address.world.accessed", OperationResult(OperationID("address.root_access"), 0)),
        _state("address.world.normal", BlockArgument(BlockID("address.normal"), 0)),
        _data("address.error", BlockArgument(BlockID("address.raise"), 0), "builtins.Exception"),
        _state("address.world.raise", BlockArgument(BlockID("address.raise"), 1)),
    )
    source = _use("address.source.use", "address.source", UseRole.REFERENCE)
    destination = _use("address.destination.use", "address.destination", UseRole.REFERENCE)
    key = _use("address.key.use", "address.key")
    before = _use("address.world.before", "address.world.initial", UseRole.STATE_CONTENT)
    root_id = OperationID("address.root_access")
    root_operation = Operation(
        root_id, "read and update multiple owners on one carrier",
        (Behavior.READ, Behavior.WRITE),
        (source, destination, key, before),
        (ValueID("address.world.accessed"),),
        (StateAccess(LocationID("address.world"), before.id, AccessMode.READ_WRITE,
                     ValueID("address.world.accessed"), Footprint()),),
        effects_complete=False,
    )

    requirement_id = ResourceRequirementID("address.resource.requirement")
    requirement = ResourceRequirement(
        requirement_id, root_id, ResourceKind.OTHER, ResourceRole.OPAQUE_RESOURCE,
    )
    resource_use = ResourceUse(root_id, requirement_id)

    invoke_world = _use("address.invoke.world", "address.world.accessed", UseRole.STATE_CONTENT)
    invoke_reference = _use("address.invoke.reference", "address.invoke_owner", UseRole.REFERENCE)
    invoke_key = _use("address.invoke.key", "address.key")
    invoke_id = OperationID("address.invoke")
    invoke = Operation(
        invoke_id, "unknown operation with distinct NORMAL and RAISE state outcomes",
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
        (invoke_world, invoke_reference, invoke_key),
        effects_complete=True,
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID("address.normal"),
                                (CompletionResult(0),)),
            CompletionSuccessor(ExitKind.RAISE, BlockID("address.raise"),
                                (CompletionResult(0), CompletionResult(1))),
        )),
        completions=(
            CompletionSignature(ExitKind.NORMAL, (
                ValueType(ValueKind.STATE, location=LocationID("address.world")),
            )),
            CompletionSignature(ExitKind.RAISE, (
                ValueType(ValueKind.DATA, data_type="builtins.Exception"),
                ValueType(ValueKind.STATE, location=LocationID("address.world")),
            )),
        ),
        invoke_arguments=(invoke_world.id, invoke_reference.id, invoke_key.id),
    )

    normal_use = _use("address.normal.world", "address.world.normal", UseRole.STATE_CONTENT)
    normal_return = Operation(
        OperationID("address.normal.return"), "return through the NORMAL port",
        (Behavior.CONTROL,), (normal_use,),
        terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                              values=(normal_use.id,)),
    )
    raised_error = _use("address.raise.error", "address.error")
    raised_world = _use("address.raise.world", "address.world.raise", UseRole.STATE_CONTENT)
    raised_return = Operation(
        OperationID("address.raise.return"), "raise through the RAISE port",
        (Behavior.CONTROL,), (raised_error, raised_world),
        terminator=Terminator(TerminatorKind.RAISE, exit="failure",
                              values=(raised_error.id, raised_world.id)),
    )

    root_refinement = StateAddressRefinement(
        ExistingAccess(root_id, 0),
        (
            AddressEffect(ReferenceOwner(source.id), (Element(key.id),), AccessMode.READ),
            AddressEffect(ReferenceOwner(destination.id), (Element(key.id),), AccessMode.WRITE),
            AddressEffect(ResourceOwner(requirement_id), (Element(key.id),),
                          AccessMode.READ_WRITE),
        ),
        AddressCoverage.PARTIAL,
    )
    invoke_refinement = StateAddressRefinement(
        InvokeStateOperand(invoke_id, invoke_world.id),
        (AddressEffect(ReferenceOwner(invoke_reference.id), (Element(invoke_key.id),),
                       AccessMode.READ_WRITE),),
        AddressCoverage.PARTIAL,
    )

    entry = Block(BlockID("address.entry"), tuple(value.id for value in values[:5]),
                  (root_id, invoke_id))
    normal = Block(BlockID("address.normal"), (ValueID("address.world.normal"),),
                    (normal_return.id,))
    raise_block = Block(BlockID("address.raise"),
                        (ValueID("address.error"), ValueID("address.world.raise")),
                        (raised_return.id,))
    region = Region(
        RegionID("address.root"), "state address site graph", entry.id,
        (entry, normal, raise_block),
        (
            ExitPort("normal", ExitKind.NORMAL, (
                ValueType(ValueKind.STATE, location=LocationID("address.world")),
            )),
            ExitPort("failure", ExitKind.RAISE, (
                ValueType(ValueKind.DATA, data_type="builtins.Exception"),
                ValueType(ValueKind.STATE, location=LocationID("address.world")),
            )),
        ),
    )
    graph = ProgramGraph(
        region.id, (region,), (root_operation, invoke, normal_return, raised_return), values,
        (StateLocation(LocationID("address.world"), "shared state carrier", stability=Stability.UNKNOWN),),
        resource_requirements=(requirement,), resource_uses=(resource_use,),
        state_address_refinements=(root_refinement, invoke_refinement),
    )
    return graph, {
        "root_operation": root_id,
        "root_access_index": 0,
        "invoke_operation": invoke_id,
        "invoke_state_use": invoke_world.id,
        "invoke_normal_block": normal.id,
        "invoke_raise_block": raise_block.id,
        "resource_requirement": requirement_id,
        "dynamic_key_use": invoke_key.id,
        "root_dynamic_key_use": key.id,
        "root_reference_uses": (source.id, destination.id),
    }


__all__ = ["state_address_program"]
