"""A declared native coroutine wrapper W, its held B and a real driver call.

The native getter is a semantic projection with original input/result ports.
It is never represented as a W-to-B copy or an extra coroutine lookup.
"""
from dataclasses import replace

from scar.ir.program.control import ControlScope, ControlScopeKind
from scar.ir.program.ids import BlockID, ControlScopeID, OperationID, ProtocolScopeID, UseID
from scar.ir.program.model import (
    AccessMode, Behavior, BlockArgument, CompletionResult, CompletionSuccessor,
    ExitKind, OperationResult, StateAccess, StateVersionValue, Terminator,
    TerminatorKind, ValueKind, ValueType,
)
from scar.ir.program.drivers import CreationCapture
from scar.ir.program.protocol_await_records import (
    AwaitBodyLink, CoroutineAwaitWrapper, WrapperHeldBody,
)
from scar.ir.program.protocol_connections import (
    InitialAdvance, ProtocolCallInputCase, ProtocolCallInputs,
    ProtocolOperationRef, ProtocolResultConsumers,
)
from scar.ir.program.protocols import (
    ContractResult, HostTerminal, OperationSiteSubject, OwnedUse,
    ProtocolClause, ProtocolOperation, ProtocolProfile, ProtocolScope,
    StaticGapReason, StaticProtocolGap,
)
from scar.ir.program.resumption import (
    ResumableKind, SuspendTerminator, SuspensionFlavor,
)
from scar.ir.program.state_addresses import ExistingAccess, InvokeStateOperand
from tests.fixtures.program_await_pipeline_graphs import await_self_pipeline_program
from tests.fixtures.program_control_graphs import _source
from tests.fixtures.program_driver_graphs import PACKET, RAW, REFERENCE, _Builder, _use


def _add_second_creation(graph, prior):
    """A second actual Create, before W construction, preserving B1 separately."""
    factory = next(region for region in graph.regions if region.id == graph.root)
    created = next(block for block in factory.blocks if block.id == BlockID("factory.created"))
    values = {value.id: value for value in graph.values}
    domains = tuple(values[value].location for value in created.arguments[1:])
    states = tuple(ValueType(ValueKind.STATE, location=location) for location in domains)
    b = _Builder("factory", domains)
    normal = b.formals("factory.second.created", (REFERENCE, REFERENCE, *states))
    failed = b.formals("factory.second.failed", (PACKET, *states))
    original = next(op for op in graph.operations if op.id == prior["create"].operation)
    old_states = tuple(use.value for use in original.uses
                       if isinstance(values[use.value], StateVersionValue))
    latest_states = dict(zip(old_states, created.arguments[1:], strict=True))
    renamed = {use.id: UseID("factory.second." + use.id.value) for use in original.uses}
    actuals = tuple(replace(use, id=renamed[use.id],
                           value=latest_states.get(use.value, use.value)) for use in original.uses)
    keep_first = _use("factory.second.keep.first", created.arguments[0])
    second = b.add("factory.second.create", (*actuals, keep_first),
        effects_complete=True, invoke_arguments=tuple(use.id for use in actuals),
        completions=original.completions,
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID("factory.second.created"),
                (keep_first.id, *(CompletionResult(index) for index in range(1 + len(states))))),
            CompletionSuccessor(ExitKind.RAISE, BlockID("factory.second.failed"),
                tuple(CompletionResult(index) for index in range(len(failed)))),
        )))
    fail = b.terminal("factory.second.failed.raise", failed, fail=True)
    current = {created.arguments[0]: normal[0],
               **dict(zip(created.arguments[1:], normal[2:], strict=True))}
    constructor = replace(prior["get"], uses=tuple(replace(use,
        value=current.get(use.value, use.value)) for use in prior["get"].uses))
    b.block("factory.second.created", normal, (constructor,))
    b.block("factory.second.failed", failed, (fail,))
    factory = replace(factory, blocks=tuple(replace(block, operations=(second.id,))
        if block.id == created.id else block for block in factory.blocks) + tuple(b.blocks))
    declaration = replace(prior["create"], operation=second.id,
        function_object=renamed[prior["create"].function_object],
        captures=tuple(CreationCapture(capture.formal, renamed[capture.source])
                       for capture in prior["create"].captures))
    graph = replace(graph,
        regions=tuple(factory if region.id == factory.id else region for region in graph.regions),
        operations=tuple(constructor if op.id == constructor.id else op for op in graph.operations)
            + tuple(b.operations), values=(*graph.values, *b.values),
        resumable_creates=(*graph.resumable_creates, declaration),
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in factory.blocks))
            if scope.region == factory.id else scope for scope in graph.control_scopes))
    return graph, {**prior, "get": constructor, "second_create": declaration,
                   "constructor_expected": BlockArgument(BlockID("factory.second.created"), 0)}


def await_wrapper_program(*, attach_link=True, second_create=False):
    """Create B -> native constructor W -> wrapper getter -> real Drive(B)."""
    graph, prior = await_self_pipeline_program()
    if second_create:
        graph, prior = _add_second_creation(graph, prior)
    values = {value.id: value for value in graph.values}
    body = replace(graph.resumable_bodies[0], kind=ResumableKind.COROUTINE)
    constructor = replace(prior["get"], label="native coroutine wrapper constructor")
    domains = tuple(values[use.value].location for use in constructor.uses
                    if isinstance(values[use.value], StateVersionValue))
    states = tuple(ValueType(ValueKind.STATE, location=location) for location in domains)
    b = _Builder("wrapper.advance", domains)
    entry = b.formals("wrapper.advance.entry", (REFERENCE, RAW, *states))
    world_index = next(index for index, location in enumerate(domains)
                       if location != body.context_location)
    getter_id = OperationID("wrapper.held_body.read")
    held = b.value("wrapper.held_body", OperationResult(getter_id, 0), REFERENCE)
    read_uses = (
        _use("wrapper.held_body.wrapper", entry[0]),
        _use("wrapper.held_body.world", entry[2 + world_index], state=True),
    )
    getter = b.add(getter_id.value, read_uses, results=(held,),
        accesses=(StateAccess(domains[world_index], read_uses[1].id,
                                    AccessMode.READ),), effects_complete=True)
    getter = replace(getter, behaviors=(Behavior.READ,))
    b.operations[-1] = getter
    normal = b.formals("wrapper.advance.normal", (REFERENCE, *states))
    failure = b.formals("wrapper.advance.failure", (PACKET, *states))
    call_uses = (
        _use("wrapper.driver.instance", held),
        _use("wrapper.driver.raw", entry[1], protocol=True),
        *(_use(f"wrapper.driver.state.{index}", value, state=True)
          for index, value in enumerate(entry[2:])),
    )
    inner_call = b.add("wrapper.driver.call", call_uses,
        effects_complete=True, callee=prior["driver"].region,
        invoke_arguments=tuple(use.id for use in call_uses),
        completions=prior["call"].completions,
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID("wrapper.advance.normal"),
                tuple(CompletionResult(index) for index in range(len(normal)))),
            CompletionSuccessor(ExitKind.RAISE, BlockID("wrapper.advance.failure"),
                tuple(CompletionResult(index) for index in range(len(failure)))),
        )))
    returned = b.terminal("wrapper.advance.return", normal)
    raised = b.terminal("wrapper.advance.raise", failure, fail=True)
    b.block("wrapper.advance.entry", entry, (getter, inner_call))
    b.block("wrapper.advance.normal", normal, (returned,))
    b.block("wrapper.advance.failure", failure, (raised,))
    wrapper_region = b.finish("wrapper.advance.entry", parent=graph.root)
    call = replace(prior["call"], callee=wrapper_region.id)

    scope = ProtocolScopeID("await.wrapper.construction")
    unknown = StaticProtocolGap(StaticGapReason.NATIVE_APPLICABILITY_UNPROVEN)
    expected_body = prior.get("constructor_expected", BlockArgument(BlockID("factory.created"), 0))
    sites = tuple(InvokeStateOperand(constructor.id, use.id)
                  for use in constructor.uses[1:])
    constructor_rows = tuple(ProtocolOperation(
        scope, ProtocolClause.WRAPPER_CONSTRUCTION, constructor.id, slot,
        CoroutineAwaitWrapper(constructor.uses[0].id, expected_body,
            prior["get_rows"][slot].contract.result, sites), unknown,
    ) for slot in range(len(constructor.terminator.successors)))
    source = ProtocolOperationRef(scope, ProtocolClause.WRAPPER_CONSTRUCTION,
                                  constructor.id, 0)
    iterator = ContractResult(scope, ProtocolClause.WRAPPER_CONSTRUCTION,
        constructor.id, 0, constructor_rows[0].contract.result)
    inputs = tuple(ProtocolCallInputs(
        ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot),
        (ProtocolCallInputCase(None, iterator, (), InitialAdvance(iterator)),),
    ) for row in prior["call_rows"])
    projection = WrapperHeldBody(source, expected_body,
        OwnedUse(constructor.id, constructor.uses[0].id),
        OwnedUse(getter.id, getter.uses[0].id), OperationResult(getter.id, 0),
        (ExistingAccess(getter.id, 0),))
    links = tuple(AwaitBodyLink(source,
        ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot),
        prior["drive"].operation, projection, None) for row in prior["call_rows"])
    consumers = (
        ProtocolResultConsumers(source, (OwnedUse(call.id, call.uses[0].id),)),
        ProtocolResultConsumers(ProtocolOperationRef(scope,
            ProtocolClause.WRAPPER_CONSTRUCTION, constructor.id, 1),
            (HostTerminal(prior["get_failure"].id),)),
        *(row for row in graph.protocol_result_consumers
          if row.site.scope != prior["acquisition_scope"]),
    )
    operations = tuple(
        constructor if op.id == constructor.id else call if op.id == call.id else
        replace(op, terminator=replace(op.terminator, flavor=SuspensionFlavor.AWAIT))
        if type(op.terminator) is SuspendTerminator else op
        for op in graph.operations)
    regions = tuple(replace(region, parent=wrapper_region.id)
        if region.id == prior["driver"].region else region for region in graph.regions)
    graph = replace(graph,
        regions=(*regions, wrapper_region), operations=(*operations, *b.operations),
        values=(*graph.values, *b.values),
        resumable_bodies=(body, *graph.resumable_bodies[1:]),
        control_scopes=(*graph.control_scopes,
            ControlScope(ControlScopeID("wrapper.advance.function"), wrapper_region.id,
                None, ControlScopeKind.FUNCTION, _source("wrapper.advance"),
                tuple(block.id for block in wrapper_region.blocks))),
        protocol_scopes=tuple(row for row in graph.protocol_scopes
            if row.id != prior["acquisition_scope"]) + (
            ProtocolScope(scope, ProtocolProfile.COROUTINE_WRAPPER_CONSTRUCTION_V1,
                OperationSiteSubject(graph.root, constructor.id), unknown),),
        protocol_operations=tuple(row for row in graph.protocol_operations
            if row.scope != prior["acquisition_scope"]) + constructor_rows,
        protocol_call_inputs=inputs, protocol_result_consumers=consumers,
        protocol_bindings=tuple(row for row in graph.protocol_bindings
            if type(row) is not AwaitBodyLink) + (links if attach_link else ()))
    return graph, {
        **prior, "construction_scope": scope, "constructor": constructor,
        "constructor_rows": constructor_rows, "call": call, "body": body,
        "wrapper_region": wrapper_region, "read": getter, "read_body": held,
        "wrapper_entry": entry, "inner_call": inner_call,
        "inner_return": returned, "inner_raise": raised,
        "projection": projection, "links": links,
    }


__all__ = ["await_wrapper_program"]
