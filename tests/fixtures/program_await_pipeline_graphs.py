"""One same-graph native-self await acquisition and first body drive.

The graph keeps the real Create, GET_AWAITABLE INVOKE, and driver CALL ports.
Its protocol rows are declarations over those ports; they do not prove native
applicability or runtime execution.
"""
from dataclasses import replace

from scar.ir.program.ids import BlockID, OperationID, ProtocolScopeID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, ExitKind, InvokeLiteralResult, StateVersionValue,
    Terminator, TerminatorKind, ValueKind, ValueType,
)
from scar.ir.program.protocol_await_records import AwaitAcquisition, AwaitBodyLink
from scar.ir.program.protocol_connections import (
    InitialAdvance, ProtocolCallInputCase, ProtocolCallInputs,
    ProtocolOperationRef, ProtocolResultConsumers,
)
from scar.ir.program.protocols import (
    ContractResult, HostTerminal, OperationSiteSubject, OwnedUse,
    ProtocolCall, ProtocolCallRule, ProtocolClause, ProtocolOperation,
    ProtocolProfile, ProtocolScope, StaticGapReason, StaticProtocolGap,
)
from scar.ir.program.resumption import ResumableKind
from scar.ir.program.state_addresses import InvokeStateOperand
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_driver_graphs import (
    PACKET, REFERENCE, _Builder, _use, driver_program,
)


def await_self_pipeline_program(*, attach_link=True):
    """Return the canonical Create→GET_AWAITABLE→NEXT body-drive graph."""
    graph = driver_program(create=True, target="start")
    body = graph.resumable_bodies[0]
    graph = replace(graph, resumable_bodies=(
        replace(body, kind=ResumableKind.GENERATOR_COROUTINE),
        *graph.resumable_bodies[1:],
    ))

    factory = next(region for region in graph.regions if region.id == graph.root)
    values = {value.id: value for value in graph.values}
    created_block = next(block for block in factory.blocks
                         if block.id == BlockID("factory.created"))
    created = created_block.arguments
    domains = tuple(values[identity].location for identity in created[1:]
                    if isinstance(values[identity], StateVersionValue))
    state_types = tuple(ValueType(ValueKind.STATE, location=location) for location in domains)
    builder = _Builder(factory.id.value, domains)

    awaitable = builder.formals("factory.awaitable", (REFERENCE, *state_types))
    failed = builder.formals("factory.awaitable.failure", (PACKET, *state_types))
    get_uses = (
        _use("factory.get_awaitable.operand", created[0]),
        *(_use(f"factory.get_awaitable.state.{index}", value, state=True)
          for index, value in enumerate(created[1:])),
    )
    get = builder.add("factory.get_awaitable", get_uses,
        effects_complete=False,
        invoke_arguments=tuple(use.id for use in get_uses),
        completions=(
            CompletionSignature(ExitKind.NORMAL, (REFERENCE, *state_types)),
            CompletionSignature(ExitKind.RAISE, (PACKET, *state_types)),
        ),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID("factory.awaitable"),
                tuple(CompletionResult(index) for index in range(len(awaitable)))),
            CompletionSuccessor(ExitKind.RAISE, BlockID("factory.awaitable.failure"),
                tuple(CompletionResult(index) for index in range(len(failed)))),
        )))
    get_failure = builder.terminal("factory.awaitable.failure.raise", failed, fail=True)

    old_call = next(operation for operation in graph.operations
                     if operation.id == OperationID("factory.call"))
    replacement_values = dict(zip(created, awaitable, strict=True))
    call = replace(old_call, uses=tuple(replace(use,
        value=replacement_values.get(use.value, use.value)) for use in old_call.uses))
    values.update((value.id, value) for value in builder.values)
    await_block = Block(BlockID("factory.awaitable"), awaitable, (call.id,))
    failure_block = Block(BlockID("factory.awaitable.failure"), failed, (get_failure.id,))
    new_blocks = tuple(
        replace(block, operations=(get.id,)) if block.id == BlockID("factory.created") else block
        for block in factory.blocks
    ) + (await_block, failure_block)
    factory = replace(factory, blocks=new_blocks)

    acquisition_scope = ProtocolScopeID("await.self.acquisition")
    advance_scope = ProtocolScopeID("await.self.advance")
    unproven = StaticProtocolGap(StaticGapReason.NATIVE_APPLICABILITY_UNPROVEN)
    create_row = graph.resumable_creates[0]
    get_state_sites = tuple(InvokeStateOperand(get.id, use.id) for use in get_uses[1:])
    call_state_sites = tuple(InvokeStateOperand(call.id, use.id) for use in call.uses
                             if isinstance(values.get(use.value), StateVersionValue))
    get_rows = tuple(ProtocolOperation(
        acquisition_scope, ProtocolClause.AWAIT_ACQUISITION, get.id, slot,
        AwaitAcquisition(get_uses[0].id, BlockArgument(created_block.id, 0),
            InvokeLiteralResult(ControlEdgeReference(get.id, slot), CompletionResult(0)),
            get_state_sites, unproven),
        unproven,
    ) for slot in range(len(get.terminator.successors)))
    call_rows = tuple(ProtocolOperation(
        advance_scope, ProtocolClause.DELEGATE_ADVANCE, call.id, slot,
        ProtocolCall(call.uses[0].id, (),
            InvokeLiteralResult(ControlEdgeReference(call.id, slot), CompletionResult(0)),
            call_state_sites, ProtocolCallRule.DELEGATE_NEXT),
        unproven,
    ) for slot in range(len(call.terminator.successors)))

    iterator = ContractResult(acquisition_scope, ProtocolClause.AWAIT_ACQUISITION,
                              get.id, 0, get_rows[0].contract.result)
    inputs = tuple(ProtocolCallInputs(
        ProtocolOperationRef(advance_scope, ProtocolClause.DELEGATE_ADVANCE, call.id, row.slot),
        (ProtocolCallInputCase(None, iterator, (), InitialAdvance(iterator)),),
    ) for row in call_rows)
    consumers = (
        ProtocolResultConsumers(ProtocolOperationRef(acquisition_scope,
            ProtocolClause.AWAIT_ACQUISITION, get.id, 0),
            (OwnedUse(call.id, call.uses[0].id),)),
        ProtocolResultConsumers(ProtocolOperationRef(acquisition_scope,
            ProtocolClause.AWAIT_ACQUISITION, get.id, 1),
            (HostTerminal(get_failure.id),)),
        ProtocolResultConsumers(ProtocolOperationRef(advance_scope,
            ProtocolClause.DELEGATE_ADVANCE, call.id, 0),
            (HostTerminal(OperationID("factory.normal.return")),)),
        ProtocolResultConsumers(ProtocolOperationRef(advance_scope,
            ProtocolClause.DELEGATE_ADVANCE, call.id, 1),
            (HostTerminal(OperationID("factory.call.failure.raise")),)),
    )
    links = tuple(AwaitBodyLink(
        ProtocolOperationRef(acquisition_scope, ProtocolClause.AWAIT_ACQUISITION, get.id, 0),
        ProtocolOperationRef(advance_scope, ProtocolClause.DELEGATE_ADVANCE, call.id, row.slot),
        OperationID("driver.drive"), None, None,
    ) for row in call_rows)
    scopes = (
        ProtocolScope(acquisition_scope, ProtocolProfile.AWAIT_ACQUISITION_V1,
            OperationSiteSubject(factory.id, get.id), unproven),
        ProtocolScope(advance_scope, ProtocolProfile.DELEGATION_SITE_V1,
            OperationSiteSubject(factory.id, call.id), unproven),
    )
    regions = tuple(factory if region.id == factory.id else region for region in graph.regions)
    operations = tuple(call if operation.id == call.id else operation
                       for operation in graph.operations) + (get, get_failure)
    scopes_all = tuple(replace(scope, blocks=tuple(block.id for block in factory.blocks))
        if scope.region == factory.id else scope for scope in graph.control_scopes)
    result = replace(graph, regions=regions, operations=operations,
        values=(*graph.values, *builder.values), control_scopes=scopes_all,
        protocol_scopes=(*graph.protocol_scopes, *scopes),
        protocol_operations=(*graph.protocol_operations, *get_rows, *call_rows),
        protocol_call_inputs=(*graph.protocol_call_inputs, *inputs),
        protocol_result_consumers=(*graph.protocol_result_consumers, *consumers),
        protocol_bindings=(*graph.protocol_bindings, *(links if attach_link else ())))
    return result, {
        "acquisition_scope": acquisition_scope, "advance_scope": advance_scope,
        "get": get, "call": call, "create": create_row, "body": body,
        "driver": graph.driver_interfaces[0], "drive": graph.body_drives[0],
        "links": links, "get_rows": get_rows, "call_rows": call_rows,
        "get_failure": get_failure,
    }


__all__ = ["await_self_pipeline_program"]
