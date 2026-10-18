"""Distinct supplied StopIteration routes; no exception-class/native proof.

The internal packet has its own body constructor result and packet definition.
An external escaping packet is the exact delivered input. Initial throw never
enters a body and does not borrow a DriveResult to justify its host exception.
"""
from dataclasses import replace

from scar.ir.program.control import ExceptionPacketDefinition, ProtocolValueKind as P, ProtocolValueType
from scar.ir.program.ids import BlockID, OperationID, ProtocolScopeID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, CompletionResult, CompletionSignature, CompletionSuccessor,
    BlockArgument, ExitKind, LiteralOrigin, Operation, OperationResult, ProtocolValue, ReferenceValue,
    Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.protocols import (
    DriverSubject, OutcomeAdapter, OutcomeAdapterRule as A, ProtocolClause as C,
    ProtocolOperation, ProtocolProfile, ProtocolScope,
)
from tests.fixtures.program_driver_graphs import driver_program
from tests.fixtures.program_generator_admission_graphs import _caller, _environment
from tests.fixtures.program_generator_close_graphs import _body_yield_after_packet
from tests.fixtures.program_protocol_graphs import (
    _adapt_return, _insert_processing, _source_gap, no_entry_throw_program,
)
from tests.fixtures.program_publication_graphs import with_publications
from tests.fixtures.program_resumption_graphs import _Body, _use, resumption_program


def _op(graph, identity):
    return next(op for op in graph.operations if op.id == identity)


def _internal_body():
    """Resume SENT, construct a fresh exception, then actually RAISE its packet.

    Factory RAISE is a different actual body outcome and propagates directly;
    only the successful factory's explicitly supplied class contract is adapted.
    Both keep current world/context and the active caller token exactly once.
    """
    graph = resumption_program()
    b = _Body("resume")
    # Read the actual base block rather than relying on all optional labels.
    value_block = next(block for block in graph.regions[0].blocks if block.id == BlockID("resume.value"))
    attach = value_block.operations[0]
    removed = set(value_block.operations[1:])
    b.values = [value for value in graph.values if not (
        isinstance(value.origin, OperationResult) and value.origin.operation in removed)]
    b.operations = [op for op in graph.operations if op.id not in removed]
    b.blocks = list(graph.regions[0].blocks)
    b.initials = list(graph.frame_context_initials)
    b.attaches = list(graph.frame_context_attaches)
    b.detaches = [row for row in graph.frame_context_detaches if row.operation not in removed]
    by_id = {value.id: value for value in graph.values}
    attach_op = _op(graph, attach)
    attach_after = next(access.after for access in attach_op.accesses)
    caller_result = next(row.caller for row in graph.frame_context_attaches if row.operation == attach)
    world = next(value for value in value_block.arguments
                 if getattr(by_id[value], "location", None) == b.world)
    saved = next(value for value in value_block.arguments if isinstance(by_id[value], ReferenceValue))
    identity = OperationID("stopiter.body.factory")
    actuals = (_use("stopiter.body.factory.input", saved, UseRole.REFERENCE),
               _use("stopiter.body.factory.world", world, UseRole.STATE_CONTENT),
               _use("stopiter.body.factory.context", attach_after, UseRole.STATE_CONTENT))
    signatures, edges, forwarded = [], [], []
    packet_definition = None
    source_ids = []
    for number, kind in enumerate((ExitKind.NORMAL, ExitKind.RAISE)):
        name = f"stopiter.body.post.{number}"
        output = b.argument(name + ".output", name, 0,
                            "reference" if kind is ExitKind.NORMAL else P.EXCEPTION_PACKET)
        current_world = b.argument(name + ".world", name, 1, b.world)
        current_context = b.argument(name + ".context", name, 2, b.context)
        caller = b.argument(name + ".caller", name, 3, P.DRIVE_CALLER_CONTEXT)
        forward = _use(name + ".forward.caller", caller_result)
        forwarded.append(forward)
        signatures.append(CompletionSignature(kind, (
            ValueType(ValueKind.REFERENCE) if kind is ExitKind.NORMAL else ProtocolValueType(P.EXCEPTION_PACKET),
            ValueType(ValueKind.STATE, location=b.world), ValueType(ValueKind.STATE, location=b.context))))
        edges.append(CompletionSuccessor(kind, BlockID(name),
            (CompletionResult(0), CompletionResult(1), CompletionResult(2), forward.id)))
        operations = []
        if kind is ExitKind.NORMAL:
            traceback = ReferenceValue(ValueID("stopiter.body.traceback"), b.region,
                                       LiteralOrigin(None), targets=())
            b.values.append(traceback)
            packet = b.result("stopiter.body.packet", "stopiter.body.pack", 0, P.EXCEPTION_PACKET)
            components = (_use("stopiter.body.exception", output, UseRole.REFERENCE),
                          _use("stopiter.body.traceback.use", traceback.id, UseRole.REFERENCE))
            b.add("stopiter.body.pack", (Behavior.CONTROL,), components, (packet,), effects_complete=True)
            packet_definition = ExceptionPacketDefinition(packet, *(use.id for use in components))
            operations.append("stopiter.body.pack")
        else:
            packet = output
        _, detached = b.switch(name + ".detach", caller, current_context, attach=False)
        outgoing = (_use(name + ".packet", packet),
                    _use(name + ".world.use", current_world, UseRole.STATE_CONTENT),
                    _use(name + ".context.use", detached, UseRole.STATE_CONTENT))
        terminal = b.add(name + ".raise", (Behavior.CONTROL,), outgoing,
            terminator=Terminator(TerminatorKind.RAISE, exit="failure",
                                  values=tuple(use.id for use in outgoing)))
        source_ids.append(terminal.id)
        b.block(name, (output, current_world, current_context, caller),
                (*operations, name + ".detach", terminal.id.value))
    factory = b.add(identity.value, (Behavior.CONTROL,), (*actuals, *forwarded), effects_complete=False,
        invoke_arguments=tuple(use.id for use in actuals), completions=tuple(signatures),
        terminator=Terminator(TerminatorKind.INVOKE, tuple(edges)))
    b.blocks = [replace(block, operations=(attach, factory.id)) if block.id == value_block.id else block
                for block in b.blocks]
    result = b.finish("resume.entry", tuple(port for port in graph.regions[0].exits if port.kind is ExitKind.RAISE))
    return replace(result, exception_packets=(packet_definition,)), tuple(source_ids)


def _old_packet_input(graph):
    """An original available same-typed input for meaningful source mutations."""
    interface, = graph.driver_interfaces
    region = next(region for region in graph.regions if region.id == interface.region)
    entry = next(block for block in region.blocks if block.id == region.entry)
    old = ProtocolValue(ValueID("stopiter.old.packet"), region.id,
                        BlockArgument(entry.id, len(entry.arguments)), P.EXCEPTION_PACKET)
    return replace(graph, values=(*graph.values, old), regions=tuple(replace(item,
        blocks=tuple(replace(block, arguments=(*block.arguments, old.id)) if block.id == entry.id else block
                     for block in item.blocks)) if item.id == region.id else item for item in graph.regions)), old.id


def stopiter_program(*, route="escaping", selected=ExitKind.NORMAL, wrong_source_kind=False):
    """Return (graph, details) for internal/escaping/caught/created declarations.

    Runtime exception class and source-rule applicability remain unproved. The
    test concerns exact supplied source ports and consumer behavior, not labels.
    """
    from scar.ir.program.drivers import RawRequestKind
    from scar.ir.program.protocols import RequestOperandBinding, RequestProcessing, RequestProcessingRule
    if route not in ("internal", "escaping", "caught", "created"):
        raise ValueError("unknown supplied StopIteration route")
    if route == "created":
        graph, details = no_entry_throw_program(selected=selected)
        graph, old_packet = _old_packet_input(graph)
        graph, caller = _caller(graph, kind=RawRequestKind.THROW, send_none=True, stage="created")
        return graph, {**details, **caller, "route": route, "adapters": (),
                       "old_packet": old_packet,
                       "adapted_source": None, "host_terminals": (details["terminals"][details["selected_edge"]],)}
    if route == "internal":
        body, sources = _internal_body()
        target, kind = "value", RawRequestKind.SEND
        adapted_source = sources[0]
    else:
        body = _body_yield_after_packet() if route == "caught" else resumption_program()
        target, kind = "packet", RawRequestKind.THROW
        adapted_source = OperationID("resume.raise")
    body = _environment(body)
    graph = driver_program(target=target, body_graph=body)
    original_exits = next(region for region in graph.regions if region.id == graph.root).exits
    graph, processing = _insert_processing(graph, target=target)
    if route == "caught" and not wrong_source_kind:
        graph = replace(graph, regions=tuple(replace(region, exits=original_exits)
                                             if region.id == graph.root else region for region in graph.regions))
    interface, = graph.driver_interfaces
    scope = ProtocolScope(ProtocolScopeID("stopiter.driver.scope"), ProtocolProfile.GENERATOR_BODY_V1,
                          DriverSubject(interface.region), _source_gap())
    driver = next(region for region in graph.regions if region.id == interface.region)
    entry = next(block for block in driver.blocks if block.id == driver.entry)
    argument = entry.arguments[2]
    if target == "packet":
        original = next(value for value in graph.values if value.id == argument)
        argument_ref = ReferenceValue(original.id, original.region, original.origin)
        graph = replace(graph, values=tuple(argument_ref if value.id == original.id else value for value in graph.values))
    helper = _op(graph, processing["processing"])
    expanded = Use(UseID("stopiter.request.argument"), argument, UseRole.REFERENCE)
    helper = replace(helper, uses=(*helper.uses, expanded), invoke_arguments=(*helper.invoke_arguments, expanded.id))
    rows = tuple(ProtocolOperation(scope.id, C.REQUEST_PROCESSING, helper.id, number,
        RequestProcessing(processing["raw_use"], (RequestOperandBinding(0, expanded.id),),
            processing[result], processing["state_sites"], RequestProcessingRule.CHECK_SEND
            if target == "value" else RequestProcessingRule.NORMALIZE_THROW_INSTANCE), _source_gap())
        for number, result in ((0, "normal_result"), (1, "raise_result")))
    graph = replace(graph, operations=tuple(helper if op.id == helper.id else op for op in graph.operations),
                    protocol_scopes=(scope,), protocol_operations=rows)
    drive, = graph.body_drives
    drive_op = _op(graph, drive.operation)
    all_edges = drive_op.terminator.successors
    selected_edge = next(edge for edge in all_edges if edge.source == adapted_source)
    adapter_rows = ()
    if route != "caught" or wrong_source_kind:
        # _adapt_return operates on one selected source; no intermediate graph
        # is validated. Restore the full original frontier after its local edit.
        selected_drive = replace(drive_op, terminator=replace(drive_op.terminator, successors=(selected_edge,)))
        graph = replace(graph, operations=tuple(selected_drive if op.id == drive_op.id else op for op in graph.operations))
        graph = _adapt_return(graph, scope.id)
        graph = replace(graph, operations=tuple(
            replace(op, terminator=replace(op.terminator, successors=all_edges)) if op.id == drive_op.id else
            replace(op, uses=tuple(replace(use, role=UseRole.PROTOCOL) if use.id == UseID("adapter.input") else use
                                  for use in op.uses)) if op.id == OperationID("adapter.construct") else op
            for op in graph.operations),
            protocol_operations=tuple(replace(row, contract=replace(row.contract,
                rule=A.GENERATOR_ESCAPE_STOPITER_TO_RUNTIME_ERROR)) if type(row.contract) is OutcomeAdapter else row
                for row in graph.protocol_operations))
        # A YIELD payload is a Reference, even when its metadata deliberately
        # carries the wrong RAISE-only adaptation rule in the negative fixture.
        if route == "caught":
            graph = replace(graph, operations=tuple(replace(op, uses=tuple(
                replace(use, role=UseRole.REFERENCE) if use.id == UseID("adapter.input") else use
                for use in op.uses)) if op.id == OperationID("adapter.construct") else op
                for op in graph.operations))
        adapter_rows = tuple(row for row in graph.protocol_operations if type(row.contract) is OutcomeAdapter)
    # Actual terminal kinds determine the host interface; only the caught-item
    # route has a normal result. No fictional host NORMAL port is retained.
    if route != "caught" or wrong_source_kind:
        graph = replace(graph, regions=tuple(replace(region,
            exits=tuple(port for port in region.exits if port.kind is ExitKind.RAISE))
            if region.id == interface.region else region for region in graph.regions))
    graph = with_publications(graph)
    graph, old_packet = _old_packet_input(graph)
    graph, caller = _caller(graph, kind=kind, send_none=True, stage="suspended")
    host_terminals = (OperationID("adapter.normal.exit"), OperationID("adapter.failure.exit")) if adapter_rows else (
        next(block.operations[-1] for region in graph.regions for block in region.blocks if block.id == selected_edge.block),)
    return graph, {**processing, **caller, "route": route, "scope": scope.id,
                   "drive": drive.operation, "adapted_source": adapted_source,
                   "sources": tuple(edge.source for edge in all_edges), "adapters": adapter_rows,
                   "old_packet": old_packet,
                   "host_terminals": host_terminals,
                   "factory": OperationID("stopiter.body.factory") if route == "internal" else None}


__all__ = ["stopiter_program"]
