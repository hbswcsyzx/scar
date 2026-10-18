"""Two supplied static close requests sharing one canonical resumable body.

This is a ProgramGraph of caller INVOKEs and two actual BodyDrive sites.  It is
not an ExecutionModel, a captured continuation activation, or native identity
evidence.  The second request follows the first call's actual RAISE completion.
"""
from dataclasses import fields, is_dataclass, replace

from scar.ir.program.control import ControlScope, ControlScopeKind, ProtocolValueKind as P
from scar.ir.program.drivers import RawRequestDefinition, RawRequestKind
from scar.ir.program.ids import (
    BlockID, ControlScopeID, OperationID, ProtocolScopeID, RegionID, UseID, ValueID,
)
from scar.ir.program.model import (
    AccessMode, Behavior, DataValue, Footprint, FootprintKind, Operation,
    CompletionResult, CompletionSignature, CompletionSuccessor, ExitKind,
    OperationResult, StateAccess, Successor, Terminator, TerminatorKind, UseRole,
)
from scar.ir.program.protocols import (
    DriverSubject, DriveResult, HostTerminal, OutcomeAdapter, OutcomeAdapterRule,
    ProtocolClause, ProtocolOperation, ProtocolProfile, ProtocolScope,
    RequestProcessing, RequestProcessingRule,
)
from scar.ir.program.lifecycle import DriveOutcomeRef
from tests.fixtures.program_control_graphs import _source
from tests.fixtures.program_driver_graphs import PACKET, RAW, REFERENCE, _Builder, _use
from tests.fixtures.program_generator_close_graphs import (
    _body_yield_after_packet, generator_close_program,
)
from tests.fixtures.program_protocol_graphs import _adapt_return, _insert_processing, _source_gap
from tests.fixtures.program_publication_graphs import with_publications
from tests.fixtures.program_resumption_graphs import _Body, _use as _body_use
from tests.fixtures.program_session_release_graphs import _Tail


def _operation(graph, identity):
    return next(operation for operation in graph.operations if operation.id == identity)


def _branching_body():
    """A real data predicate chooses body Return(v) or an ignored-close YIELD."""
    graph = _body_yield_after_packet()
    b = _Body("resume")
    b.values, b.blocks = list(graph.values), list(graph.regions[0].blocks)
    moved = {OperationID("resume.packet.detach"), OperationID("resume.raise")}
    b.operations = [operation for operation in graph.operations if operation.id not in moved]
    b.initials, b.attaches = list(graph.frame_context_initials), list(graph.frame_context_attaches)
    b.detaches = list(graph.frame_context_detaches)
    condition_id = OperationID("close.body.choice")
    condition = DataValue(ValueID("close.body.choice.value"), graph.root,
                          OperationResult(condition_id, 0), "builtins.bool")
    b.values.append(condition)
    packet = _body_use("close.body.choice.packet", "resume.packet.payload")
    before = _body_use("close.body.choice.world", "resume.packet.world", UseRole.STATE_CONTENT)
    b.operations.append(Operation(condition_id, "declared body data predicate, not a native phase claim",
        (Behavior.COMPUTE, Behavior.READ), (packet, before), (condition.id,),
        accesses=(StateAccess(b.world, before.id, AccessMode.READ,
                              footprint=Footprint(FootprintKind.WHOLE)),), effects_complete=True))
    branch_uses = [_body_use("close.body.choose.condition", condition.id, UseRole.DATA)]
    edges = []
    for label in ("return", "yield"):
        block = "close.body." + label
        caller = b.argument(block + ".caller", block, 0, P.DRIVE_CALLER_CONTEXT)
        world = b.argument(block + ".world", block, 1, b.world)
        context = b.argument(block + ".context", block, 2, b.context)
        value = b.argument(block + ".value", block, 3, "reference")
        actual = (_body_use(block + ".in.caller", "resume.packet.attach.caller"),
                  _body_use(block + ".in.world", "resume.packet.world", UseRole.STATE_CONTENT),
                  _body_use(block + ".in.context", "resume.packet.attach.after", UseRole.STATE_CONTENT),
                  _body_use(block + ".in.value", "resume.packet.x", UseRole.REFERENCE))
        branch_uses.extend(actual)
        edges.append(Successor(BlockID(block), tuple(use.id for use in actual)))
        if label == "return":
            _, after = b.switch(block + ".detach", caller, context, attach=False)
            outgoing = (_body_use(block + ".out.value", value, UseRole.REFERENCE),
                        _body_use(block + ".out.world", world, UseRole.STATE_CONTENT),
                        _body_use(block + ".out.context", after, UseRole.STATE_CONTENT))
            b.add(block + ".exit", (Behavior.CONTROL,), outgoing,
                terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                                      values=tuple(use.id for use in outgoing)))
            operations = (block + ".detach", block + ".exit")
        else:
            replacements = {ValueID("resume.packet.attach.caller"): caller,
                            ValueID("resume.packet.world"): world,
                            ValueID("resume.packet.attach.after"): context,
                            ValueID("resume.packet.x"): value}
            for identity in (OperationID("resume.packet.detach"), OperationID("resume.raise")):
                operation = _operation(graph, identity)
                b.operations.append(replace(operation, uses=tuple(replace(use,
                    value=replacements.get(use.value, use.value)) for use in operation.uses)))
            operations = ("resume.packet.detach", "resume.raise")
        b.block(block, (caller, world, context, value), operations)
    branch = b.add("close.body.choose", (Behavior.CONTROL,), branch_uses,
        terminator=Terminator(TerminatorKind.BRANCH, tuple(edges), condition=branch_uses[0].id))
    b.blocks = [replace(block, operations=(OperationID("resume.packet.attach"), condition_id, branch.id))
                if block.id == BlockID("resume.packet") else block for block in b.blocks]
    return b.finish("resume.entry", graph.regions[0].exits)


def _first_driver(body, *, release):
    """Keep both real first outcomes; only ignored YIELD uses the error adapter."""
    from tests.fixtures.program_driver_graphs import driver_program
    graph = driver_program(target="packet", body_graph=body)
    exits = next(region for region in graph.regions if region.id == graph.root).exits
    graph, processing = _insert_processing(graph, target="packet")
    graph = replace(graph, regions=tuple(replace(region, exits=exits)
        if region.id == graph.root else region for region in graph.regions))
    scope = ProtocolScope(ProtocolScopeID("close.first.scope"), ProtocolProfile.GENERATOR_BODY_V1,
                           DriverSubject(graph.root), _source_gap())
    rows = [ProtocolOperation(scope.id, ProtocolClause.REQUEST_PROCESSING, processing["processing"], slot,
        RequestProcessing(processing["raw_use"], (), processing[port], processing["state_sites"],
            RequestProcessingRule.NORMALIZE_GENERATOR_EXIT), _source_gap())
        for slot, port in ((0, "normal_result"), (1, "raise_result"))]
    drive, = graph.body_drives
    operation = _operation(graph, drive.operation)
    error_edge = next(edge for edge in operation.terminator.successors
                      if _operation(graph, edge.source).terminator.kind is TerminatorKind.SUSPEND)
    value_edge = next(edge for edge in operation.terminator.successors
                      if _operation(graph, edge.source).terminator.kind is TerminatorKind.RETURN)
    terminal = next(block for region in graph.regions for block in region.blocks
                    if block.id == value_edge.block).operations[-1]
    host = _operation(graph, terminal)
    rows.append(ProtocolOperation(scope.id, ProtocolClause.CLOSE_ROUTE, terminal, 0,
        OutcomeAdapter(DriveResult(DriveOutcomeRef(drive.operation, value_edge.source), 0),
            host.terminator.values[0], HostTerminal(terminal), OutcomeAdapterRule.CLOSE_RETURN_VALUE), _source_gap()))
    graph = replace(graph, protocol_scopes=(scope,), protocol_operations=tuple(rows))
    # The old helper takes one selected edge.  Build that adapter without
    # validating a partial graph, then restore the original complete frontier.
    selected = replace(operation, terminator=replace(operation.terminator, successors=(error_edge,)))
    graph = replace(graph, operations=tuple(selected if current.id == selected.id else current
                                           for current in graph.operations))
    graph = _adapt_return(graph, scope.id)
    graph = replace(graph, operations=tuple(operation if current.id == operation.id else current
        for current in graph.operations), regions=tuple(replace(region, exits=exits)
            if region.id == graph.root else region for region in graph.regions),
        protocol_operations=tuple(replace(row, clause=ProtocolClause.CLOSE_ROUTE,
            contract=replace(row.contract, rule=OutcomeAdapterRule.CLOSE_IGNORED_EXIT_TO_RUNTIME_ERROR))
            if row.operation == OperationID("adapter.construct") else row for row in graph.protocol_operations))
    graph = with_publications(graph)
    commit = next(row for row in graph.body_outcome_commits if row.outcome.source == error_edge.source)
    error_terminal = OperationID("adapter.normal.exit")
    if release:
        marker = _operation(graph, commit.operation)
        owner = next(use.value for use in marker.uses if use.id == commit.instance)
        tail = _Tail(graph, error_terminal, body=owner)
        tail.release(0)
        graph = tail.finish()
    return graph, {"scope": scope.id, "drive": drive.operation, "source": error_edge.source,
        "processing": processing["processing"], "publication": commit.operation,
        "terminals": (error_terminal, OperationID("adapter.failure.exit")), "normal_terminal": terminal}


def _driver_part(graph, prefix):
    """Explicitly rename only the second static driver; body definitions stay one."""
    interface, = graph.driver_interfaces
    region = next(region for region in graph.regions if region.id == interface.region)
    block_ids = {block.id for block in region.blocks}
    operation_ids = {identity for block in region.blocks for identity in block.operations}
    operations = tuple(operation for operation in graph.operations if operation.id in operation_ids)
    values = tuple(value for value in graph.values if value.region == region.id)
    maps = {
        RegionID: {region.id: RegionID(prefix)},
        BlockID: {identity: BlockID(prefix + "." + identity.value) for identity in block_ids},
        OperationID: {identity: OperationID(prefix + "." + identity.value) for identity in operation_ids},
        ValueID: {value.id: ValueID(prefix + "." + value.id.value) for value in values},
        UseID: {use.id: UseID(prefix + "." + use.id.value) for operation in operations for use in operation.uses},
        ControlScopeID: {scope.id: ControlScopeID(prefix + "." + scope.id.value)
                         for scope in graph.control_scopes if scope.region == region.id},
        ProtocolScopeID: {scope.id: ProtocolScopeID(prefix + "." + scope.id.value)
                          for scope in graph.protocol_scopes},
    }

    def rename(value):
        if type(value) in maps:
            return maps[type(value)].get(value, value)
        if isinstance(value, tuple):
            return tuple(rename(item) for item in value)
        if is_dataclass(value):
            return replace(value, **{field.name: rename(getattr(value, field.name))
                                     for field in fields(value)})
        return value

    tables = {name: rename(getattr(graph, name)) for name in (
        "driver_interfaces", "final_body_gates", "body_drives", "driver_lifecycles",
        "body_outcome_commits", "terminal_frame_releases", "protocol_scopes",
        "protocol_operations", "literal_evaluations",
    )}
    driver_values = {value.id for value in values}
    tables["exception_packets"] = rename(tuple(row for row in graph.exception_packets
                                               if row.value in driver_values))
    tables.update(region=rename(region), operations=rename(operations), values=rename(values),
                  control_scopes=rename(tuple(scope for scope in graph.control_scopes
                                              if scope.region == region.id)))
    return tables, maps


def two_close_requests_program(*, release_first=False):
    """Return ``(graph,details)``: close→ignored YIELD→host RAISE→retry close.

    The retry targets the second cut's THROWN_PACKET case.  Its fresh normalizer
    packet and latest state enter that body landing, whose true RAISE supplies F.
    A caller-owned instance Reference is explicitly forwarded into the first
    RAISE landing and supplied as the second call's actual instance argument.
    """
    body = _branching_body()
    first, first_details = _first_driver(body, release=release_first)
    second, second_details = generator_close_program(outcome="raise", adapter="helper",
        body_graph=body, resume_suspend=OperationID("resume.raise"), release=True)
    part, maps = _driver_part(second, "close.second")
    first_interface, = first.driver_interfaces
    second_interface, = part["driver_interfaces"]
    domains = tuple(location.id for location in first.locations)
    from scar.ir.program.model import ValueKind, ValueType
    state_types = tuple(ValueType(ValueKind.STATE, location=location) for location in domains)
    caller = _Builder("close.calls", domains)
    entry = caller.formals("close.calls.entry", (REFERENCE, PACKET, *state_types))
    instance, initial_packet, *initial_states = entry
    raws = []

    def raw(name):
        result = caller.value(name + ".value", OperationResult(OperationID(name), 0), RAW)
        operation = caller.add(name, results=(result,), effects_complete=True)
        raws.append(RawRequestDefinition(result, RawRequestKind.CLOSE, ()))
        return operation, result

    raw1, request1 = raw("close.calls.raw.1")
    first_region = next(region for region in first.regions if region.id == first_interface.region)
    if {port.kind for port in first_region.exits} != {ExitKind.NORMAL, ExitKind.RAISE}:
        raise AssertionError("first close fixture must retain both real body paths")
    first_normal = caller.formals("close.calls.first.normal", (REFERENCE, *state_types))
    raised = caller.formals("close.calls.first.raise", (PACKET, *state_types, REFERENCE))
    first_actual_values = (instance, request1, initial_packet, *initial_states)
    first_actuals = tuple(_use(f"close.calls.first.actual.{index}", value,
        state=index >= 3, protocol=index in (1, 2)) for index, value in enumerate(first_actual_values))
    owner_copy = _use("close.calls.first.forward.instance", instance)
    call1 = caller.add("close.calls.first", (*first_actuals, owner_copy),
        callee=first_region.id, invoke_arguments=tuple(use.id for use in first_actuals),
        effects_complete=True,
        completions=tuple(CompletionSignature(port.kind, port.types) for port in first_region.exits),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID("close.calls.first.normal"),
                tuple(CompletionResult(index) for index in range(1 + len(domains)))),
            CompletionSuccessor(ExitKind.RAISE, BlockID("close.calls.first.raise"),
                (*(CompletionResult(index) for index in range(1 + len(domains))), owner_copy.id)),)))
    caller.block("close.calls.entry", entry, (raw1, call1))
    caller.block("close.calls.first.normal", first_normal,
                 (caller.terminal("close.calls.first.return", first_normal),))

    raw2, request2 = raw("close.calls.raw.2")
    current_states = raised[1:1 + len(domains)]
    second_actual_values = (raised[-1], request2, raised[0], *current_states)
    second_actuals = tuple(_use(f"close.calls.second.actual.{index}", value,
        state=index >= 3, protocol=index in (1, 2)) for index, value in enumerate(second_actual_values))
    normal = caller.formals("close.calls.done", (REFERENCE, *state_types))
    failed = caller.formals("close.calls.failed", (PACKET, *state_types))
    second_region = part["region"]
    call2 = caller.add("close.calls.second", second_actuals, callee=second_region.id,
        invoke_arguments=tuple(use.id for use in second_actuals), effects_complete=True,
        completions=tuple(CompletionSignature(port.kind, port.types) for port in second_region.exits),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID("close.calls.done"),
                tuple(CompletionResult(index) for index in range(1 + len(domains)))),
            CompletionSuccessor(ExitKind.RAISE, BlockID("close.calls.failed"),
                tuple(CompletionResult(index) for index in range(1 + len(domains)))),)))
    caller.block("close.calls.first.raise", raised, (raw2, call2))
    caller.block("close.calls.done", normal,
                 (caller.terminal("close.calls.return", normal),))
    caller.block("close.calls.failed", failed,
                 (caller.terminal("close.calls.raise", failed, fail=True),))
    caller_region = caller.finish("close.calls.entry")
    regions = tuple(replace(region, parent=caller_region.id) for region in first.regions)
    graph = replace(first, root=caller_region.id,
        regions=(caller_region, *regions, replace(second_region, parent=caller_region.id)),
        operations=(*first.operations, *part["operations"], *caller.operations),
        values=(*first.values, *part["values"], *caller.values),
        control_scopes=(*first.control_scopes, *part["control_scopes"],
            ControlScope(ControlScopeID("close.calls.function"), caller_region.id, None,
                ControlScopeKind.FUNCTION, _source("two supplied close calls"),
                tuple(block.id for block in caller_region.blocks))),
        raw_driver_requests=(*first.raw_driver_requests, *raws),
        exception_packets=(*first.exception_packets, *part["exception_packets"]),
        **{name: (*getattr(first, name), *part[name]) for name in (
            "driver_interfaces", "final_body_gates", "body_drives", "driver_lifecycles",
            "body_outcome_commits", "terminal_frame_releases", "protocol_scopes",
            "protocol_operations", "literal_evaluations")})
    return graph, {"first": first_details,
        "second": {**second_details,
            **{key: maps[OperationID][second_details[key]]
               for key in ("processing", "drive", "publication", "release")},
            "scope": maps[ProtocolScopeID][second_details["scope"]]},
        "calls": (call1.id, call2.id), "raws": (request1, request2),
        "caller_instance": instance, "forward_instance": owner_copy.id,
        "retry_instance": raised[-1], "first_post_states": tuple(current_states),
        "initial_states": tuple(initial_states), "shared_body": body.root,
        "first_cut": first.body_drives[0].target.suspend,
        "second_cut": second.body_drives[0].target.suspend,
        "second_gate": part["final_body_gates"][0].operation,
        "second_old_packet": maps[ValueID][ValueID("driver.entry.arg.2")],
        "second_instance": second_interface.receiver}


__all__ = ["two_close_requests_program"]
