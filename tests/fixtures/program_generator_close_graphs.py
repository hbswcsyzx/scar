"""Conditional synchronous close routes over original body/gate/state ports.

Names are not protocol recognizers.  Exception class/phase/native helper
applicability remains a source condition; these are declaration fixtures.
"""
from dataclasses import replace

from scar.ir.program.control import ProtocolValueKind as P
from scar.ir.program.ids import BlockID, OperationID, ProtocolScopeID, UseID, ValueID
from scar.ir.program.lifecycle import DriveOutcomeRef
from scar.ir.program.model import (
    Behavior, CompletionResult, CompletionSignature, CompletionSuccessor,
    ExitKind, InvokeLiteralResult, LiteralEvaluation, OperationResult,
    StateVersionValue, Terminator, TerminatorKind, UseRole, ValueKind, ValueType,
)
from scar.ir.literals import PythonLiteral
from scar.ir.program.literal_sources import UnlocatedLiteral
from scar.ir.program.protocols import (
    DriverSubject, DriveResult, HostTerminal, OutcomeAdapter, OutcomeAdapterRule,
    ProtocolClause, ProtocolOperation, ProtocolProfile, ProtocolScope,
    RequestProcessing, RequestProcessingRule,
)
from scar.ir.program.resumption import (
    ResumeInput, ResumeSlot, ResumeSlotKind as I, ResumeSuccessor,
    SavedInput, SavedRole as S, SavedSlot, SuspendTerminator, SuspensionFlavor,
)
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_driver_graphs import driver_program
from tests.fixtures.program_protocol_graphs import _adapt_return, _insert_processing, _source_gap
from tests.fixtures.program_publication_graphs import with_publications
from tests.fixtures.program_resumption_graphs import _Body, _use, resumption_program
from tests.fixtures.program_session_release_graphs import _Tail


def _operation(graph, identity):
    return next(operation for operation in graph.operations if operation.id == identity)


def _body_return_after_packet():
    graph = resumption_program()
    source = _operation(graph, OperationID("resume.raise"))
    # The declared body handles the injected packet and returns its saved
    # Reference.  This does not prove an exception-class match or Python source.
    source = replace(source, uses=tuple(replace(use, value=ValueID("resume.packet.x"),
        role=UseRole.REFERENCE) if use.id == source.terminator.values[0] else use
        for use in source.uses), terminator=replace(source.terminator,
        kind=TerminatorKind.RETURN, exit="normal"))
    return replace(graph, operations=tuple(source if operation.id == source.id else operation
        for operation in graph.operations), regions=tuple(replace(region,
            exits=tuple(port for port in region.exits if port.kind is ExitKind.NORMAL))
            for region in graph.regions))


def _body_yield_after_packet():
    """A true second YIELD plus private NEXT/THROW retry landings."""
    graph = resumption_program()
    b = _Body("resume")
    b.values, b.blocks = list(graph.values), list(graph.regions[0].blocks)
    b.operations = [operation for operation in graph.operations
                    if operation.id != OperationID("resume.raise")]
    b.initials = list(graph.frame_context_initials)
    b.attaches = list(graph.frame_context_attaches)
    b.detaches = list(graph.frame_context_detaches)
    cases = []
    for kind, suffix in ((I.SENT_VALUE, "value"), (I.THROWN_PACKET, "packet")):
        block = "close.retry." + suffix
        frame = b.argument(block + ".frame", block, 0, P.FRAME_CONTEXT)
        saved = b.argument(block + ".saved", block, 1, "reference")
        context = b.argument(block + ".context", block, 2, b.context)
        payload = b.argument(block + ".payload", block, 3,
                             "reference" if kind is I.SENT_VALUE else P.EXCEPTION_PACKET)
        world = b.argument(block + ".world", block, 4, b.world)
        caller, attached = b.switch(block + ".attach", frame, context, attach=True)
        _, detached = b.switch(block + ".detach", caller, attached, attach=False)
        terminal = block + ".exit"
        uses = (_use(terminal + ".payload", saved if kind is I.SENT_VALUE else payload,
                     UseRole.REFERENCE if kind is I.SENT_VALUE else UseRole.PROTOCOL),
                _use(terminal + ".world", world, UseRole.STATE_CONTENT),
                _use(terminal + ".context", detached, UseRole.STATE_CONTENT))
        from scar.ir.program.model import Behavior
        b.add(terminal, (Behavior.CONTROL,), uses, terminator=Terminator(
            TerminatorKind.RETURN if kind is I.SENT_VALUE else TerminatorKind.RAISE,
            exit="normal" if kind is I.SENT_VALUE else "failure",
            values=tuple(use.id for use in uses)))
        b.block(block, (frame, saved, context, payload, world),
                (block + ".attach", block + ".detach", terminal))
        cases.append(ResumeSuccessor((ResumeSlot(I.STATE, b.world), ResumeSlot(kind),
            ResumeSlot(I.STATE, b.context)), BlockID(block),
            (SavedInput(0), SavedInput(1), ResumeInput(2), ResumeInput(1), ResumeInput(0))))
    export = _use("close.ignored.export", "resume.packet.x", UseRole.REFERENCE)
    frame = _use("close.ignored.frame", "resume.packet.detach.frame")
    saved = _use("close.ignored.saved", "resume.packet.x", UseRole.REFERENCE)
    world = _use("close.ignored.world", "resume.packet.world", UseRole.STATE_CONTENT)
    context = _use("close.ignored.context", "resume.packet.detach.after", UseRole.STATE_CONTENT)
    from scar.ir.program.model import Behavior
    b.add("resume.raise", (Behavior.CONTROL,), (export, frame, saved, world, context),
        effects_complete=True, terminator=SuspendTerminator(SuspensionFlavor.YIELD,
            export.id, (SavedSlot(S.FRAME_CONTEXT, frame.id), SavedSlot(S.VALUE, saved.id)),
            (world.id, context.id), tuple(cases)))
    return b.finish("resume.entry", graph.regions[0].exits)


def _body_new_raise_after_packet():
    """Real body helper N/R produce packets distinct from the injected packet."""
    graph = resumption_program()
    b = _Body("resume")
    b.blocks = list(graph.regions[0].blocks)
    removed = {OperationID("resume.packet.detach"), OperationID("resume.raise")}
    b.values = [value for value in graph.values if not (
        isinstance(value.origin, OperationResult) and value.origin.operation in removed)]
    b.operations = [operation for operation in graph.operations if operation.id not in removed]
    b.initials = list(graph.frame_context_initials)
    b.attaches = list(graph.frame_context_attaches)
    b.detaches = [row for row in graph.frame_context_detaches if row.operation not in removed]
    identity = OperationID("close.body.helper")
    actual = (_use("close.body.helper.packet", "resume.packet.payload"),
              _use("close.body.helper.world", "resume.packet.world", UseRole.STATE_CONTENT),
              _use("close.body.helper.context", "resume.packet.attach.after", UseRole.STATE_CONTENT))
    forwards, edges = [], []
    from scar.ir.program.control import ProtocolValueType
    signature = (ProtocolValueType(P.EXCEPTION_PACKET),
                 ValueType(ValueKind.STATE, location=b.world),
                 ValueType(ValueKind.STATE, location=b.context))
    for index, kind in enumerate((ExitKind.NORMAL, ExitKind.RAISE)):
        block = f"close.body.post.{index}"
        packet = b.argument(block + ".packet", block, 0, P.EXCEPTION_PACKET)
        world = b.argument(block + ".world", block, 1, b.world)
        context = b.argument(block + ".context", block, 2, b.context)
        caller = b.argument(block + ".caller", block, 3, P.DRIVE_CALLER_CONTEXT)
        forward = _use(block + ".forward.caller", "resume.packet.attach.caller")
        forwards.append(forward)
        edges.append(CompletionSuccessor(kind, BlockID(block),
            (CompletionResult(0), CompletionResult(1), CompletionResult(2), forward.id)))
        _, detached = b.switch(block + ".detach", caller, context, attach=False)
        outgoing = (_use(block + ".raise.packet", packet),
                    _use(block + ".raise.world", world, UseRole.STATE_CONTENT),
                    _use(block + ".raise.context", detached, UseRole.STATE_CONTENT))
        b.add(block + ".raise", (Behavior.CONTROL,), outgoing,
            terminator=Terminator(TerminatorKind.RAISE, exit="failure",
                                  values=tuple(use.id for use in outgoing)))
        b.block(block, (packet, world, context, caller), (block + ".detach", block + ".raise"))
    b.add(identity.value, (Behavior.CONTROL,), (*actual, *forwards), effects_complete=False,
        invoke_arguments=tuple(use.id for use in actual),
        completions=tuple(CompletionSignature(kind, signature) for kind in (ExitKind.NORMAL, ExitKind.RAISE)),
        terminator=Terminator(TerminatorKind.INVOKE, tuple(edges)))
    b.blocks = [replace(block, operations=(OperationID("resume.packet.attach"), identity))
                if block.id == BlockID("resume.packet") else block for block in b.blocks]
    return b.finish("resume.entry", graph.regions[0].exits)


def generator_close_program(*, outcome="return", adapter="direct", release=False,
                            body_graph=None, resume_suspend=None):
    """Return ``(graph,details)`` for a true packet ingress and close outcome.

    ``outcome='yield'`` has a real later retry cut; adapter NORMAL builds the
    host error packet and RAISE propagates its own failure.  ``adapter='helper'``
    on Return models a genuine opaque boundary returning its own selected
    result, whose identity correspondence remains a native/source condition.
    """
    if outcome not in ("return", "yield", "raise", "propagate") or adapter not in ("direct", "helper"):
        raise ValueError("unknown close declaration fixture")
    body = body_graph or (_body_return_after_packet() if outcome == "return" else
                         _body_yield_after_packet() if outcome == "yield" else
                         _body_new_raise_after_packet() if outcome == "propagate" else resumption_program())
    if resume_suspend is not None:
        selected = _operation(body, resume_suspend)
        if not isinstance(selected.terminator, SuspendTerminator):
            raise ValueError("explicit retry target must be an original Suspend")
        prioritized = replace(body, operations=(selected, *(operation for operation in body.operations
                                                          if operation.id != selected.id)))
    else:
        prioritized = body
    graph = driver_program(target="packet", body_graph=prioritized)
    # Operation ordering has no target semantics.  Restore original body order
    # after the old fixture's first-Suspend selection and check the exact target.
    body_operations = {operation.id for operation in body.operations}
    graph = replace(graph, operations=(*body.operations, *(operation for operation in graph.operations
                                                          if operation.id not in body_operations)))
    if resume_suspend is not None and graph.body_drives[0].target.suspend != resume_suspend:
        raise AssertionError("driver did not select the explicit original retry cut")
    root = next(region for region in graph.regions if region.id == graph.root)
    original_exits = root.exits
    graph, processing = _insert_processing(graph, target="packet")
    # _insert_processing's generic THROW fixture drops NORMAL.  Close may
    # legitimately return v; retain that original driver signature here.
    valid_exits = tuple(port for port in original_exits if outcome != "propagate" or port.kind is ExitKind.RAISE)
    graph = replace(graph, regions=tuple(replace(region, exits=valid_exits)
        if region.id == graph.root else region for region in graph.regions))
    interface, = graph.driver_interfaces
    scope = ProtocolScope(ProtocolScopeID("close.generator.scope"),
        ProtocolProfile.GENERATOR_BODY_V1, DriverSubject(interface.region), _source_gap())
    rows = tuple(ProtocolOperation(scope.id, ProtocolClause.REQUEST_PROCESSING,
        processing["processing"], slot, RequestProcessing(processing["raw_use"], (),
        processing[port], processing["state_sites"], RequestProcessingRule.NORMALIZE_GENERATOR_EXIT),
        _source_gap()) for slot, port in ((0, "normal_result"), (1, "raise_result")))
    graph = replace(graph, protocol_scopes=(scope,), protocol_operations=rows)
    drive, = graph.body_drives
    drive_op = _operation(graph, drive.operation)
    edges = drive_op.terminator.successors
    edge = edges[0]
    original_terminals = tuple(next(block for region in graph.regions for block in region.blocks
        if block.id == selected.block).operations[-1] for selected in edges)
    terminal = original_terminals[0]
    rule = (OutcomeAdapterRule.CLOSE_RETURN_VALUE if outcome in ("return", "raise")
            else OutcomeAdapterRule.CLOSE_IGNORED_EXIT_TO_RUNTIME_ERROR)
    if outcome == "propagate":
        terminals = original_terminals
    elif outcome == "return" and adapter == "direct":
        host = _operation(graph, terminal)
        row = ProtocolOperation(scope.id, ProtocolClause.CLOSE_ROUTE, host.id, 0,
            OutcomeAdapter(DriveResult(DriveOutcomeRef(drive.operation, edge.source), 0),
                host.terminator.values[0], HostTerminal(host.id), rule), _source_gap())
        graph = replace(graph, protocol_operations=(*graph.protocol_operations, row))
        terminals = (terminal,)
    else:
        graph = _adapt_return(graph, scope.id)
        graph = replace(graph, protocol_operations=tuple(replace(row,
            clause=ProtocolClause.CLOSE_ROUTE, contract=replace(row.contract, rule=rule))
            if type(row.contract) is OutcomeAdapter else row for row in graph.protocol_operations))
        terminals = (OperationID("adapter.normal.exit"), OperationID("adapter.failure.exit"))
        if outcome in ("return", "raise"):
            if outcome == "raise":
                invoke = _operation(graph, OperationID("adapter.construct"))
                invoke = replace(invoke, uses=tuple(replace(use, role=UseRole.PROTOCOL)
                    if use.id == UseID("adapter.input") else use for use in invoke.uses))
                graph = replace(graph, operations=tuple(invoke if operation.id == invoke.id else operation
                    for operation in graph.operations), literal_evaluations=(*graph.literal_evaluations,
                    LiteralEvaluation(InvokeLiteralResult(ControlEdgeReference(invoke.id, 0), CompletionResult(0)),
                        PythonLiteral.from_python(None, exact=True),
                        UnlocatedLiteral("declared close suppression result; native exception-class applicability unproved"))))
            normal = _operation(graph, terminals[0])
            normal = replace(normal, uses=tuple(replace(use, value=ValueID("adapter.exception"),
                role=UseRole.REFERENCE) if use.id == normal.terminator.values[0] else use
                for use in normal.uses), terminator=replace(normal.terminator,
                    kind=TerminatorKind.RETURN, exit="normal"))
            graph = replace(graph, operations=tuple(normal if operation.id == normal.id else operation
                for operation in graph.operations), regions=tuple(replace(region, exits=original_exits)
                if region.id == graph.root else region for region in graph.regions))
    # Insert the required first commit after constructing the adapter.  This
    # rebinds its real state inputs to the publication's current after states.
    graph = with_publications(graph)
    commits = graph.body_outcome_commits
    commit = commits[0]
    release_operation = None
    if release:
        publication = _operation(graph, commit.operation)
        owner = next(use.value for use in publication.uses if use.id == commit.instance)
        tail = _Tail(graph, terminals[0], body=owner)
        tail.release(0)
        graph = tail.finish()
        release_operation = graph.terminal_frame_releases[-1].operation
    return graph, {"scope": scope.id, "processing": processing["processing"],
        "drive": drive.operation, "source": edge.source, "sources": tuple(edge.source for edge in edges),
        "publication": commit.operation, "publications": tuple(row.operation for row in commits),
        "terminals": terminals, "release": release_operation, "outcome": outcome,
        "adapter": adapter, "retry_suspend": OperationID("resume.raise") if outcome == "yield" else None,
        "retry_targets": (BlockID("close.retry.value"), BlockID("close.retry.packet"))
            if outcome == "yield" else ()}


def state_as_close_payload_program():
    """Metadata-only wrong STATE input/output on an unchanged core-valid graph."""
    graph = with_publications(driver_program(target="start"))
    interface, = graph.driver_interfaces
    scope = ProtocolScope(ProtocolScopeID("close.state.scope"), ProtocolProfile.GENERATOR_BODY_V1,
                           DriverSubject(interface.region), _source_gap())
    commit, = graph.body_outcome_commits
    operation = _operation(graph, commit.operation)
    index = next(index for index, access in enumerate(operation.accesses) if access.after is not None)
    access = operation.accesses[index]
    drive = _operation(graph, commit.outcome.drive)
    values = {value.id: value for value in graph.values}
    source = _operation(graph, commit.outcome.source)
    from scar.ir.program.driver_flow import body_outcome_uses
    source_uses = {use.id: use.value for use in source.uses}
    state_slot = next(number for number, identity in enumerate(body_outcome_uses(source))
        if isinstance(values[source_uses[identity]], StateVersionValue)
        and values[source_uses[identity]].location == access.location)
    row = ProtocolOperation(scope.id, ProtocolClause.CLOSE_ROUTE, operation.id, 0,
        OutcomeAdapter(DriveResult(DriveOutcomeRef(drive.id, source.id), state_slot), access.before,
            values[access.after].origin, OutcomeAdapterRule.CLOSE_IGNORED_EXIT_TO_RUNTIME_ERROR),
        _source_gap())
    graph = replace(graph, protocol_scopes=(scope,), protocol_operations=(row,))
    return graph, {"row": row, "source_slot": state_slot, "scope": scope.id}


__all__ = ["generator_close_program", "state_as_close_payload_program"]
