"""Valid pending-projection graphs for provider producer ambiguity tests."""
from scar.ir.program.control import (
    ControlPort,
    ControlScope,
    ControlScopeKind,
    LanguageCompletionKind,
    PendingCompletionDefinition,
    PendingDispatchTerminator,
    PendingPayload,
    PendingSuccessor,
    ProtocolValueKind,
)
from scar.ir.program.ids import (
    BlockID,
    ControlPortID,
    ControlScopeID,
    LocationID,
    OperationID,
    RegionID,
    UseID,
    ValueID,
)
from scar.ir.program.model import (
    Behavior,
    Block,
    BlockArgument,
    DataValue,
    ExitKind,
    ExitPort,
    Operation,
    OperationResult,
    ProgramGraph,
    ProtocolValue,
    ReferenceValue,
    Region,
    StateLocation,
    StateVersionValue,
    Successor,
    Terminator,
    TerminatorKind,
    Use,
    UseRole,
    ValueKind,
    ValueType,
)
from scar.ir.program.providers import (
    ProviderBinding,
    ProviderElement,
    ProviderElementKind,
    ProviderPathKey,
    ProviderRegion,
    ProviderRegionRelation,
)

from tests.fixtures.program_provider_graphs import definition_provider_graph


def shared_pending_projection_graph() -> ProgramGraph:
    """Two independent RETURN pending payloads project into one exit phi."""
    region = RegionID("provider.pending.region")
    world = LocationID("provider.pending.world")
    function = ControlScopeID("provider.pending.function")
    port = ControlPortID("provider.pending.return")
    entry, path_a, path_b, exit_block = map(BlockID, (
        "provider.pending.entry", "provider.pending.path_a",
        "provider.pending.path_b", "provider.pending.exit",
    ))

    condition = DataValue(ValueID("provider.pending.condition"), region,
                          BlockArgument(entry, 0), "builtins.bool")
    input_a = ReferenceValue(ValueID("provider.pending.input_a"), region,
                             BlockArgument(entry, 1))
    input_b = ReferenceValue(ValueID("provider.pending.input_b"), region,
                             BlockArgument(entry, 2))
    initial_world = StateVersionValue(ValueID("provider.pending.initial_world"), region,
                                      BlockArgument(entry, 3), world)

    ref_a = ReferenceValue(ValueID("provider.pending.ref_a"), region,
                           BlockArgument(path_a, 0))
    world_a = StateVersionValue(ValueID("provider.pending.world_a"), region,
                                BlockArgument(path_a, 1), world)
    ref_b = ReferenceValue(ValueID("provider.pending.ref_b"), region,
                           BlockArgument(path_b, 0))
    world_b = StateVersionValue(ValueID("provider.pending.world_b"), region,
                                BlockArgument(path_b, 1), world)

    pending_a = ProtocolValue(ValueID("provider.pending.return_a"), region,
                              OperationResult(OperationID("provider.pending.make_a"), 0),
                              ProtocolValueKind.PENDING_COMPLETION)
    pending_b = ProtocolValue(ValueID("provider.pending.return_b"), region,
                              OperationResult(OperationID("provider.pending.make_b"), 0),
                              ProtocolValueKind.PENDING_COMPLETION)
    exit_value = ReferenceValue(ValueID("provider.pending.exit_value"), region,
                                BlockArgument(exit_block, 0))
    exit_world = StateVersionValue(ValueID("provider.pending.exit_world"), region,
                                   BlockArgument(exit_block, 1), world)
    values = (
        condition, input_a, input_b, initial_world, ref_a, world_a, ref_b, world_b,
        pending_a, pending_b, exit_value, exit_world,
    )

    branch_condition = Use(UseID("provider.pending.branch.condition"), condition.id, UseRole.DATA)
    branch_a_ref = Use(UseID("provider.pending.branch.a.ref"), input_a.id, UseRole.REFERENCE)
    branch_a_world = Use(UseID("provider.pending.branch.a.world"), initial_world.id,
                         UseRole.STATE_CONTENT)
    branch_b_ref = Use(UseID("provider.pending.branch.b.ref"), input_b.id, UseRole.REFERENCE)
    branch_b_world = Use(UseID("provider.pending.branch.b.world"), initial_world.id,
                         UseRole.STATE_CONTENT)
    branch_uses = (branch_condition, branch_a_ref, branch_a_world,
                   branch_b_ref, branch_b_world)
    branch = Operation(
        OperationID("provider.pending.branch"),
        "choose return payload source",
        (Behavior.CONTROL,),
        branch_uses,
        terminator=Terminator(TerminatorKind.BRANCH, (
            Successor(path_a, (branch_a_ref.id, branch_a_world.id)),
            Successor(path_b, (branch_b_ref.id, branch_b_world.id)),
        ), condition=branch_condition.id),
    )

    payload_a = Use(UseID("provider.pending.payload_a"), ref_a.id, UseRole.REFERENCE)
    make_a = Operation(OperationID("provider.pending.make_a"), "construct RETURN A",
                       (Behavior.CONTROL,), (payload_a,), (pending_a.id,), effects_complete=True)
    payload_b = Use(UseID("provider.pending.payload_b"), ref_b.id, UseRole.REFERENCE)
    make_b = Operation(OperationID("provider.pending.make_b"), "construct RETURN B",
                       (Behavior.CONTROL,), (payload_b,), (pending_b.id,), effects_complete=True)

    pending_use_a = Use(UseID("provider.pending.dispatch_a.pending"), pending_a.id,
                        UseRole.PROTOCOL)
    world_use_a = Use(UseID("provider.pending.dispatch_a.world"), world_a.id,
                      UseRole.STATE_CONTENT)
    dispatch_a = Operation(
        OperationID("provider.pending.dispatch_a"), "dispatch RETURN A",
        (Behavior.CONTROL,), (pending_use_a, world_use_a),
        terminator=PendingDispatchTerminator(pending_use_a.id, (
            PendingSuccessor(port, exit_block, (PendingPayload(), world_use_a.id)),
        )),
    )

    pending_use_b = Use(UseID("provider.pending.dispatch_b.pending"), pending_b.id,
                        UseRole.PROTOCOL)
    world_use_b = Use(UseID("provider.pending.dispatch_b.world"), world_b.id,
                      UseRole.STATE_CONTENT)
    dispatch_b = Operation(
        OperationID("provider.pending.dispatch_b"), "dispatch RETURN B",
        (Behavior.CONTROL,), (pending_use_b, world_use_b),
        terminator=PendingDispatchTerminator(pending_use_b.id, (
            PendingSuccessor(port, exit_block, (PendingPayload(), world_use_b.id)),
        )),
    )

    return_use = Use(UseID("provider.pending.exit.return"), exit_value.id, UseRole.REFERENCE)
    exit_state_use = Use(UseID("provider.pending.exit.world"), exit_world.id,
                         UseRole.STATE_CONTENT)
    exit_op = Operation(
        OperationID("provider.pending.return_exit"), "shared return exit shim",
        (Behavior.CONTROL,), (return_use, exit_state_use),
        terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                              values=(return_use.id, exit_state_use.id)),
    )

    blocks = (
        Block(entry, (condition.id, input_a.id, input_b.id, initial_world.id), (branch.id,)),
        Block(path_a, (ref_a.id, world_a.id), (make_a.id, dispatch_a.id)),
        Block(path_b, (ref_b.id, world_b.id), (make_b.id, dispatch_b.id)),
        Block(exit_block, (exit_value.id, exit_world.id), (exit_op.id,)),
    )
    region_record = Region(region, "two pending projections into one exit", entry, blocks, (
        ExitPort("normal", ExitKind.NORMAL, (
            ValueType(ValueKind.REFERENCE), ValueType(ValueKind.STATE, location=world),
        )),
    ))
    scope = ControlScope(function, region, None, ControlScopeKind.FUNCTION,
                         _source_reference(), tuple(block.id for block in blocks))
    control_port = ControlPort(port, function, LanguageCompletionKind.RETURN, exit="normal")

    provider_graph = definition_provider_graph()
    envelope = provider_graph.provider_envelopes[0]
    association = ProviderRegion(envelope.id, "external.shared_return", region,
                                 ProviderRegionRelation.DEFINES_REPRESENTATION)
    operation_binding = ProviderBinding(
        envelope.id, region,
        ProviderElement(ProviderElementKind.OPERATION, "dispatch_b"), dispatch_b.id,
    )
    value_binding = ProviderBinding(
        envelope.id, region,
        ProviderElement(ProviderElementKind.REFERENCE_VALUE, "dispatch_b",
                        (ProviderPathKey("return"),)),
        exit_value.id,
    )

    # Put B last among the two dispatchers. Reversing only this tuple changes
    # which dispatch the old last-wins edge producer map selected.
    operations = (branch, make_a, dispatch_a, make_b, exit_op, dispatch_b)
    return ProgramGraph(
        region, (region_record,), operations, values,
        (StateLocation(world, "shared projection world"),),
        control_scopes=(scope,), control_ports=(control_port,),
        pending_completions=(
            PendingCompletionDefinition(pending_a.id, port, payload_a.id),
            PendingCompletionDefinition(pending_b.id, port, payload_b.id),
        ),
        provider_envelopes=(envelope,), provider_regions=(association,),
        provider_bindings=(operation_binding, value_binding),
    )


def _source_reference():
    from scar.ir.v2.common import SourceReference
    from scar.ir.v2.ids import SourceAtomID
    return SourceReference(SourceAtomID("provider.pending.function"),
                           "provider_pending_fixture.py", "handwritten", 1, 1)


__all__ = ["shared_pending_projection_graph"]
