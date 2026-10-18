"""Hand-authored resumable-body graphs; no source or runtime adapter proof.

The fixtures retain only typed IDs, signatures and effects.  Their two state
domains deliberately keep ordinary shared contents separate from context.
"""
from __future__ import annotations

from dataclasses import replace

from scar.ir.program.bindings import BindingDefinition, BindingRead, BindingState
from scar.ir.program.cleanup import (
    CleanupEnter, CleanupInterface, CleanupReplace, CleanupResume,
    CleanupRouteSuccessor, CleanupRouteTerminator, HandledContextDomain,
)
from scar.ir.program.control import (
    ControlPort, ControlScope, ControlScopeKind, LanguageCompletionKind,
    PendingCompletionDefinition, PendingDispatchTerminator, PendingPayload,
    PendingSuccessor, ProtocolValueKind as P, ProtocolValueType,
)
from scar.ir.program.ids import (
    BlockID, ControlPortID, ControlScopeID, LocationID, OperationID, RegionID, UseID, ValueID,
)
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, DataValue, ExitKind, ExitPort,
    CompletionResult, CompletionSignature, CompletionSuccessor,
    Footprint, FootprintKind, LiteralOrigin, LocalBindingValue, Operation,
    OperationResult, ProgramGraph, ProtocolValue, ReferenceValue, Region,
    StateAccess, StateLocation, StateVersionValue, Successor, Terminator,
    TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.resumption import (
    FrameContextAttach, FrameContextDetach, FrameContextInitial, ResumableBody,
    ResumableKind, ResumeInput, ResumeSlot, ResumeSlotKind as I, ResumeSuccessor,
    SavedInput, SavedRole as S, SavedSlot, SuspendTerminator, SuspensionFlavor,
)
from scar.ir.v2.ids import ValueSlotID
from scar.ir.program.structured import ControlEdgeReference

from tests.fixtures.program_control_graphs import _source


def _use(name, value, role=UseRole.PROTOCOL):
    return Use(UseID(name), ValueID(value) if isinstance(value, str) else value, role)


def _operation(graph, name):
    return next(item for item in graph.operations if item.id == OperationID(name))


def _change_operation(graph, name, operation):
    return replace(graph, operations=tuple(operation if item.id == OperationID(name)
                                           else item for item in graph.operations))


class _Body:
    """Small fixture constructor; it never validates its own expected results."""

    def __init__(self, name):
        self.region = RegionID(name)
        self.world, self.context = LocationID(name + ".world"), LocationID(name + ".context")
        self.values, self.operations, self.blocks = [], [], []
        self.initials, self.attaches, self.detaches = [], [], []

    def argument(self, name, block, index, kind):
        origin = BlockArgument(BlockID(block), index)
        return self._value(name, origin, kind)

    def result(self, name, operation, index, kind):
        return self._value(name, OperationResult(OperationID(operation), index), kind)

    def _value(self, name, origin, kind):
        if kind == "reference":
            value = ReferenceValue(ValueID(name), self.region, origin)
        elif kind in (self.world, self.context):
            value = StateVersionValue(ValueID(name), self.region, origin, kind)
        elif type(kind) is ValueSlotID:
            value = LocalBindingValue(ValueID(name), self.region, origin, kind)
        else:
            value = ProtocolValue(ValueID(name), self.region, origin, kind)
        self.values.append(value)
        return value.id

    def add(self, name, behaviors, uses=(), results=(), **kwargs):
        operation = Operation(OperationID(name), name, behaviors, tuple(uses),
                              tuple(results), **kwargs)
        self.operations.append(operation)
        return operation

    def initial(self, name):
        frame = self.result(name + ".frame", name, 0, P.FRAME_CONTEXT)
        self.add(name, (Behavior.CONTROL,), results=(frame,), effects_complete=True)
        self.initials.append(FrameContextInitial(OperationID(name), frame))
        return frame

    def switch(self, name, value, state, *, attach):
        operand = _use(name + ".operand", value)
        before = _use(name + ".context", state, UseRole.STATE_CONTENT)
        protocol = P.DRIVE_CALLER_CONTEXT if attach else P.FRAME_CONTEXT
        output = self.result(name + (".caller" if attach else ".frame"), name, 0, protocol)
        after = self.result(name + ".after", name, 1, self.context)
        self.add(name, (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
                 (operand, before), (output, after), effects_complete=True,
                 accesses=(StateAccess(self.context, before.id, AccessMode.READ_WRITE,
                                      after, Footprint(FootprintKind.WHOLE)),))
        if attach:
            self.attaches.append(FrameContextAttach(OperationID(name), operand.id, output))
        else:
            self.detaches.append(FrameContextDetach(OperationID(name), operand.id, output))
        return output, after

    def block(self, name, arguments, operations):
        block = Block(BlockID(name), tuple(arguments), tuple(OperationID(op) for op in operations))
        self.blocks.append(block)
        return block

    def finish(self, entry, exits):
        region = Region(self.region, "hand-authored resumable body", BlockID(entry),
                        tuple(self.blocks), tuple(exits))
        return ProgramGraph(
            self.region, (region,), tuple(self.operations), tuple(self.values),
            (StateLocation(self.world, "shared contents"),
             StateLocation(self.context, "current handled-context")),
            control_scopes=(ControlScope(ControlScopeID(self.region.value + ".function"),
                self.region, None, ControlScopeKind.FUNCTION, _source(self.region.value),
                tuple(block.id for block in self.blocks)),),
            resumable_bodies=(ResumableBody(self.region, ResumableKind.GENERATOR, self.context),),
            frame_context_initials=tuple(self.initials),
            frame_context_attaches=tuple(self.attaches),
            frame_context_detaches=tuple(self.detaches),
        )


def resumption_program():
    """Three blocks, two ingress signatures; slot order differs from formals.

    A sent reference returns the saved input after a real world-state write.
    An injected packet escapes with that drive's post-Detach context state.
    """
    b = _Body("resume")
    x = b.argument("resume.x", "resume.entry", 0, "reference")
    w0 = b.argument("resume.world.0", "resume.entry", 1, b.world)
    c0 = b.argument("resume.context.0", "resume.entry", 2, b.context)
    f0 = b.initial("resume.initial")
    t0, c1 = b.switch("resume.attach", f0, c0, attach=True)
    f1, c2 = b.switch("resume.detach", t0, c1, attach=False)

    # VALUE: inputs=(context, sent, world); formals=(world,x,frame,sent,context).
    wv = b.argument("resume.value.world", "resume.value", 0, b.world)
    xv = b.argument("resume.value.x", "resume.value", 1, "reference")
    fv = b.argument("resume.value.frame", "resume.value", 2, P.FRAME_CONTEXT)
    sent = b.argument("resume.value.sent", "resume.value", 3, "reference")
    cv = b.argument("resume.value.context", "resume.value", 4, b.context)
    # PACKET: inputs=(packet,world,context); formals=(context,frame,packet,world,x).
    cp = b.argument("resume.packet.context", "resume.packet", 0, b.context)
    fp = b.argument("resume.packet.frame", "resume.packet", 1, P.FRAME_CONTEXT)
    packet = b.argument("resume.packet.payload", "resume.packet", 2, P.EXCEPTION_PACKET)
    wp = b.argument("resume.packet.world", "resume.packet", 3, b.world)
    xp = b.argument("resume.packet.x", "resume.packet", 4, "reference")

    export = _use("resume.suspend.export", x, UseRole.REFERENCE)
    sf = _use("resume.suspend.frame", f1)
    sx = _use("resume.suspend.x", x, UseRole.REFERENCE)
    hw = _use("resume.suspend.world", w0, UseRole.STATE_CONTENT)
    hc = _use("resume.suspend.context", c2, UseRole.STATE_CONTENT)
    suspend = SuspendTerminator(SuspensionFlavor.YIELD, export.id,
        (SavedSlot(S.FRAME_CONTEXT, sf.id), SavedSlot(S.VALUE, sx.id)), (hw.id, hc.id), (
            ResumeSuccessor((ResumeSlot(I.STATE, b.context), ResumeSlot(I.SENT_VALUE),
                             ResumeSlot(I.STATE, b.world)), BlockID("resume.value"),
                            (ResumeInput(2), SavedInput(1), SavedInput(0),
                             ResumeInput(1), ResumeInput(0))),
            ResumeSuccessor((ResumeSlot(I.THROWN_PACKET), ResumeSlot(I.STATE, b.world),
                             ResumeSlot(I.STATE, b.context)), BlockID("resume.packet"),
                            (ResumeInput(2), SavedInput(0), ResumeInput(0),
                             ResumeInput(1), SavedInput(1))),
        ))
    b.add("resume.suspend", (Behavior.CONTROL,), (export, sf, sx, hw, hc),
          terminator=suspend, effects_complete=True)
    tv, cv1 = b.switch("resume.value.attach", fv, cv, attach=True)
    before = _use("resume.value.write.before", wv, UseRole.STATE_CONTENT)
    written = b.result("resume.value.world.written", "resume.value.write", 0, b.world)
    b.add("resume.value.write", (Behavior.READ, Behavior.WRITE), (before,), (written,),
          accesses=(StateAccess(b.world, before.id, AccessMode.READ_WRITE, written,
                               Footprint(FootprintKind.WHOLE)),), effects_complete=True)
    _, cv2 = b.switch("resume.value.detach", tv, cv1, attach=False)
    ret_uses = (_use("resume.return.value", xv, UseRole.REFERENCE),
                _use("resume.return.world", written, UseRole.STATE_CONTENT),
                _use("resume.return.context", cv2, UseRole.STATE_CONTENT))
    b.add("resume.return", (Behavior.CONTROL,), ret_uses,
          terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                                values=tuple(use.id for use in ret_uses)))
    tp, cp1 = b.switch("resume.packet.attach", fp, cp, attach=True)
    _, cp2 = b.switch("resume.packet.detach", tp, cp1, attach=False)
    fail_uses = (_use("resume.raise.packet", packet),
                 _use("resume.raise.world", wp, UseRole.STATE_CONTENT),
                 _use("resume.raise.context", cp2, UseRole.STATE_CONTENT))
    b.add("resume.raise", (Behavior.CONTROL,), fail_uses,
          terminator=Terminator(TerminatorKind.RAISE, exit="failure",
                                values=tuple(use.id for use in fail_uses)))
    b.block("resume.entry", (x, w0, c0),
            ("resume.initial", "resume.attach", "resume.detach", "resume.suspend"))
    b.block("resume.value", (wv, xv, fv, sent, cv),
            ("resume.value.attach", "resume.value.write", "resume.value.detach", "resume.return"))
    b.block("resume.packet", (cp, fp, packet, wp, xp),
            ("resume.packet.attach", "resume.packet.detach", "resume.raise"))
    return b.finish("resume.entry", (
        ExitPort("normal", ExitKind.NORMAL, (ValueType(ValueKind.REFERENCE),
            ValueType(ValueKind.STATE, location=b.world),
            ValueType(ValueKind.STATE, location=b.context))),
        ExitPort("failure", ExitKind.RAISE, (ProtocolValueType(P.EXCEPTION_PACKET),
            ValueType(ValueKind.STATE, location=b.world),
            ValueType(ValueKind.STATE, location=b.context))),
    ))


def resumption_binding_program():
    """A BOUND local crosses a temporal edge and is read after restoration."""
    graph = resumption_program()
    region = graph.root
    slot = ValueSlotID("resume.local.slot")
    bind_id = OperationID("resume.bind")
    binding = LocalBindingValue(ValueID("resume.binding"), region,
                                OperationResult(bind_id, 0), slot)
    payload = _use("resume.bind.payload", "resume.x", UseRole.REFERENCE)
    bind = Operation(bind_id, "bind local", (Behavior.COMPUTE,), (payload,),
                     (binding.id,), effects_complete=True)
    graph = replace(graph, values=(*graph.values, binding), operations=(*graph.operations, bind),
        binding_definitions=(BindingDefinition(binding.id, BindingState.BOUND, payload.id),))
    blocks = []
    restored = []
    for block in graph.regions[0].blocks:
        if block.id == BlockID("resume.entry"):
            ops = list(block.operations)
            ops.insert(ops.index(OperationID("resume.detach")), bind.id)
            blocks.append(replace(block, operations=tuple(ops)))
        else:
            token = LocalBindingValue(ValueID(block.id.value + ".binding"), region,
                BlockArgument(block.id, len(block.arguments)), slot)
            restored.append(token)
            blocks.append(replace(block, arguments=(*block.arguments, token.id)))
    graph = replace(graph, regions=(replace(graph.regions[0], blocks=tuple(blocks)),),
                    values=(*graph.values, *restored))
    suspend = _operation(graph, "resume.suspend")
    binding_use = _use("resume.suspend.binding", binding.id, UseRole.LOCAL_BINDING)
    graph = _change_operation(graph, "resume.suspend", replace(suspend,
        uses=(*suspend.uses, binding_use), terminator=replace(suspend.terminator,
            saved=(*suspend.terminator.saved, SavedSlot(S.LOCAL_BINDING, binding_use.id)),
            successors=tuple(replace(edge, arguments=(*edge.arguments, SavedInput(2)))
                             for edge in suspend.terminator.successors))))
    read_input = _use("resume.read.binding", "resume.value.binding", UseRole.LOCAL_BINDING)
    result = ReferenceValue(ValueID("resume.read.result"), region,
                            OperationResult(OperationID("resume.read"), 0))
    read = Operation(OperationID("resume.read"), "read restored local", (Behavior.COMPUTE,),
                     (read_input,), (result.id,), effects_complete=True)
    blocks = tuple(replace(block, operations=(block.operations[0], read.id, *block.operations[1:]))
                   if block.id == BlockID("resume.value") else block for block in graph.regions[0].blocks)
    graph = replace(graph, values=(*graph.values, result), operations=(*graph.operations, read),
        regions=(replace(graph.regions[0], blocks=blocks),),
        binding_reads=(BindingRead(read.id, read_input.id, result.id),))
    ret = _operation(graph, "resume.return")
    return _change_operation(graph, "resume.return", replace(ret, uses=tuple(
        replace(use, value=result.id) if use.id == UseID("resume.return.value") else use
        for use in ret.uses)))


def resumption_loop_program():
    """An attached ordinary loop forwards the same drive's caller token.

    Its self edge may diverge; structural acceptance is not totality evidence.
    """
    graph = resumption_program()
    region = graph.root
    world, context = (location.id for location in graph.locations)
    values = list(graph.values)
    operations = list(graph.operations)
    blocks = list(graph.regions[0].blocks)

    def arg(name, block, index, kind):
        origin = BlockArgument(BlockID(block), index)
        if kind == "caller":
            value = ProtocolValue(ValueID(name), region, origin, P.DRIVE_CALLER_CONTEXT)
        elif kind == "reference":
            value = ReferenceValue(ValueID(name), region, origin)
        else:
            value = StateVersionValue(ValueID(name), region, origin, kind)
        values.append(value)
        return value.id

    header = (
        arg("resume.loop.caller", "resume.loop", 0, "caller"),
        arg("resume.loop.x", "resume.loop", 1, "reference"),
        arg("resume.loop.world", "resume.loop", 2, world),
        arg("resume.loop.context", "resume.loop", 3, context),
    )
    exit_args = (
        arg("resume.loop.exit.world", "resume.loop.exit", 0, world),
        arg("resume.loop.exit.caller", "resume.loop.exit", 1, "caller"),
        arg("resume.loop.exit.context", "resume.loop.exit", 2, context),
        arg("resume.loop.exit.x", "resume.loop.exit", 3, "reference"),
    )
    condition = DataValue(ValueID("resume.loop.condition"), region,
                          LiteralOrigin(True), "builtins.bool")
    values.append(condition)
    actuals = (
        _use("resume.loop.enter.caller", "resume.value.attach.caller"),
        _use("resume.loop.enter.x", "resume.value.x", UseRole.REFERENCE),
        _use("resume.loop.enter.world", "resume.value.world.written", UseRole.STATE_CONTENT),
        _use("resume.loop.enter.context", "resume.value.attach.after", UseRole.STATE_CONTENT),
    )
    enter = Operation(OperationID("resume.loop.enter"), "ordinary loop ingress",
        (Behavior.CONTROL,), actuals, terminator=Terminator(TerminatorKind.JUMP,
            (Successor(BlockID("resume.loop"), tuple(use.id for use in actuals)),)))
    loop_uses = [_use("resume.loop.test", condition.id, UseRole.DATA)]
    edges = []
    for label, target, actual_values in (
        ("again", "resume.loop", header),
        ("exit", "resume.loop.exit", (header[2], header[0], header[3], header[1])),
    ):
        args = []
        for index, actual in enumerate(actual_values):
            value = next(value for value in values if value.id == actual)
            role = (UseRole.PROTOCOL if isinstance(value, ProtocolValue) else
                    UseRole.REFERENCE if isinstance(value, ReferenceValue) else UseRole.STATE_CONTENT)
            use = _use(f"resume.loop.{label}.{index}", actual, role)
            loop_uses.append(use)
            args.append(use.id)
        edges.append(Successor(BlockID(target), tuple(args)))
    choose = Operation(OperationID("resume.loop.choose"), "possibly non-total attached loop",
        (Behavior.CONTROL,), tuple(loop_uses), terminator=Terminator(
            TerminatorKind.BRANCH, tuple(edges), condition=loop_uses[0].id))
    # Move the existing final Detach/Return into an ordinary successor.  Their
    # results retain one producer; only their current operands change.
    detach = _operation(graph, "resume.value.detach")
    detach = replace(detach, uses=tuple(replace(use,
        value=exit_args[1] if use.id == UseID("resume.value.detach.operand") else exit_args[2])
        for use in detach.uses))
    ret = _operation(graph, "resume.return")
    ret = replace(ret, uses=tuple(replace(use, value=exit_args[3])
        if use.id == UseID("resume.return.value") else replace(use, value=exit_args[0])
        if use.id == UseID("resume.return.world") else use for use in ret.uses))
    operations = [detach if op.id == detach.id else ret if op.id == ret.id else op
                  for op in operations]
    operations.extend((enter, choose))
    blocks = [replace(block, operations=(block.operations[0], block.operations[1], enter.id))
              if block.id == BlockID("resume.value") else block for block in blocks]
    blocks.extend((Block(BlockID("resume.loop"), header, (choose.id,)),
                   Block(BlockID("resume.loop.exit"), exit_args, (detach.id, ret.id))))
    return replace(graph, values=tuple(values), operations=tuple(operations),
        regions=(replace(graph.regions[0], blocks=tuple(blocks)),),
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in blocks))
                             for scope in graph.control_scopes))


def resumption_two_cuts_program(*, save_value=True):
    """A second suspension and an indirect merge expose old-value dominance.

    ``save_value=False`` intentionally leaves an old reference used after the
    second cut. It remains logically dominating; availability must reject it.
    """
    graph = resumption_program()
    b = _Body("resume")
    b.values = list(graph.values)
    b.operations = [op for op in graph.operations if op.id != OperationID("resume.return")]
    b.initials = list(graph.frame_context_initials)
    b.attaches = list(graph.frame_context_attaches)
    b.detaches = list(graph.frame_context_detaches)
    b.blocks = list(graph.regions[0].blocks)
    world = b.argument("resume.second.world", "resume.second", 0, b.world)
    frame = b.argument("resume.second.frame", "resume.second", 1, P.FRAME_CONTEXT)
    sent = b.argument("resume.second.sent", "resume.second", 2, "reference")
    context = b.argument("resume.second.context", "resume.second", 3, b.context)
    second_args = [world, frame, sent, context]
    if save_value:
        x = b.argument("resume.second.x", "resume.second", 4, "reference")
        second_args.append(x)
    export = _use("resume.second.suspend.export", "resume.value.sent", UseRole.REFERENCE)
    saved_frame = _use("resume.second.suspend.frame", "resume.value.detach.frame")
    hw = _use("resume.second.suspend.world", "resume.value.world.written", UseRole.STATE_CONTENT)
    hc = _use("resume.second.suspend.context", "resume.value.detach.after", UseRole.STATE_CONTENT)
    own = [export, saved_frame, hw, hc]
    saved = [SavedSlot(S.FRAME_CONTEXT, saved_frame.id)]
    projections = [ResumeInput(2), SavedInput(0), ResumeInput(0), ResumeInput(1)]
    if save_value:
        sx = _use("resume.second.suspend.x", "resume.value.x", UseRole.REFERENCE)
        own.append(sx)
        saved.append(SavedSlot(S.VALUE, sx.id))
        projections.append(SavedInput(1))
    b.add("resume.second.suspend", (Behavior.CONTROL,), own, effects_complete=True,
        terminator=SuspendTerminator(SuspensionFlavor.YIELD, export.id, tuple(saved),
            (hw.id, hc.id), (ResumeSuccessor((ResumeSlot(I.SENT_VALUE),
                ResumeSlot(I.STATE, b.context), ResumeSlot(I.STATE, b.world)),
                BlockID("resume.second"), tuple(projections)),)))
    caller, attached = b.switch("resume.second.attach", frame, context, attach=True)
    merged_world = b.argument("resume.second.merge.world", "resume.second.merge", 0, b.world)
    merged_caller = b.argument("resume.second.merge.caller", "resume.second.merge", 1,
                              P.DRIVE_CALLER_CONTEXT)
    merged_context = b.argument("resume.second.merge.context", "resume.second.merge", 2, b.context)
    merged_args = [merged_world, merged_caller, merged_context]
    actuals = [_use("resume.second.merge.in.world", world, UseRole.STATE_CONTENT),
               _use("resume.second.merge.in.caller", caller),
               _use("resume.second.merge.in.context", attached, UseRole.STATE_CONTENT)]
    returned = ValueID("resume.value.x")
    if save_value:
        returned = b.argument("resume.second.merge.x", "resume.second.merge", 3, "reference")
        merged_args.append(returned)
        actuals.append(_use("resume.second.merge.in.x", x, UseRole.REFERENCE))
    b.add("resume.second.jump", (Behavior.CONTROL,), actuals,
        terminator=Terminator(TerminatorKind.JUMP, (Successor(BlockID("resume.second.merge"),
            tuple(use.id for use in actuals)),)))
    _, detached = b.switch("resume.second.detach", merged_caller, merged_context, attach=False)
    actuals = (_use("resume.second.return.value", returned, UseRole.REFERENCE),
               _use("resume.second.return.world", merged_world, UseRole.STATE_CONTENT),
               _use("resume.second.return.context", detached, UseRole.STATE_CONTENT))
    b.add("resume.second.return", (Behavior.CONTROL,), actuals,
        terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                             values=tuple(use.id for use in actuals)))
    b.blocks = [replace(block, operations=(*block.operations[:-1],
                    OperationID("resume.second.suspend")))
                if block.id == BlockID("resume.value") else block for block in b.blocks]
    b.block("resume.second", second_args, ("resume.second.attach", "resume.second.jump"))
    b.block("resume.second.merge", merged_args, ("resume.second.detach", "resume.second.return"))
    return b.finish("resume.entry", graph.regions[0].exits)


def resumption_cleanup_program(*, replace_pending=False):
    """Yield inside active cleanup, preserving Enter anchors across the cut.

    Replacement is constructed *before* the yield in this same cleanup
    activation, then forwarded through new parameters and used after resume.
    No second Enter, saved-context producer or frame allocation is invented.
    """
    b = _Body("finally")
    root_scope = ControlScopeID("finally.function")
    protected_scope = ControlScopeID("finally.protected")
    cleanup_scope = ControlScopeID("finally.cleanup.scope")
    return_port = ControlPortID("finally.return.port")
    pending_definitions = []

    def args(block, specs):
        return tuple(b.argument(block + "." + suffix, block, index, kind)
                     for index, (suffix, kind) in enumerate(specs))

    def jump(name, target, actuals):
        uses = tuple(_use(name + "." + str(index), value, role)
                     for index, (value, role) in enumerate(actuals))
        return b.add(name, (Behavior.CONTROL,), uses, terminator=Terminator(
            TerminatorKind.JUMP, (Successor(BlockID(target), tuple(use.id for use in uses)),)))

    def pack(name, reference):
        payload = _use(name + ".payload", reference, UseRole.REFERENCE)
        value = b.result(name + ".pending", name, 0, P.PENDING_COMPLETION)
        b.add(name, (Behavior.CONTROL,), (payload,), (value,), effects_complete=True)
        pending_definitions.append(PendingCompletionDefinition(value, return_port, payload.id))
        return value

    def cleanup_action(name, pending, saved, world, context, replacement=None):
        uses = [_use(name + ".pending", pending), _use(name + ".context", saved),
                _use(name + ".world", world, UseRole.STATE_CONTENT),
                _use(name + ".ambient", context, UseRole.STATE_CONTENT)]
        if replacement is not None:
            uses.append(_use(name + ".replacement", replacement))
        wa = b.result(name + ".world.after", name, 0, b.world)
        ca = b.result(name + ".context.after", name, 1, b.context)
        b.add(name, (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), uses, (wa, ca),
            accesses=(StateAccess(b.world, uses[2].id, AccessMode.READ_WRITE, wa,
                                  Footprint(FootprintKind.WHOLE)),
                      StateAccess(b.context, uses[3].id, AccessMode.READ_WRITE, ca,
                                  Footprint(FootprintKind.WHOLE))), effects_complete=False)
        return uses, wa, ca

    x, w0, c0 = args("finally.entry", (
        ("x", "reference"), ("world", b.world), ("context", b.context)))
    f0 = b.initial("finally.initial")
    caller0, c1 = b.switch("finally.attach", f0, c0, attach=True)
    entry_jump = jump("finally.to-protected", "finally.protected", (
        (x, UseRole.REFERENCE), (w0, UseRole.STATE_CONTENT),
        (c1, UseRole.STATE_CONTENT), (caller0, UseRole.PROTOCOL)))
    px, pw, pc, pt = args("finally.protected", (
        ("x", "reference"), ("world", b.world), ("context", b.context),
        ("caller", P.DRIVE_CALLER_CONTEXT)))
    original = pack("finally.original", px)
    pe, we, ce, te, xe = args("finally.cleanup", (
        ("pending", P.PENDING_COMPLETION), ("world", b.world),
        ("context", b.context), ("caller", P.DRIVE_CALLER_CONTEXT), ("x", "reference")))
    route_uses = (_use("finally.protected.selector", original),
        _use("finally.protected.pending", original),
        _use("finally.protected.world.out", pw, UseRole.STATE_CONTENT),
        _use("finally.protected.context.out", pc, UseRole.STATE_CONTENT),
        _use("finally.protected.caller.out", pt),
        _use("finally.protected.x.out", px, UseRole.REFERENCE))
    b.add("finally.protected.route", (Behavior.CONTROL,), route_uses,
        terminator=CleanupRouteTerminator(route_uses[0].id, (
            CleanupRouteSuccessor(return_port, BlockID("finally.cleanup"),
                                  tuple(use.id for use in route_uses[1:])),)))
    enter_id = OperationID("finally.cleanup.enter")
    saved_context = b.result("finally.saved-context", enter_id.value, 0, P.SAVED_HANDLED_CONTEXT)
    ew = b.result("finally.enter.world", enter_id.value, 1, b.world)
    ec = b.result("finally.enter.context", enter_id.value, 2, b.context)
    enter_uses = (_use("finally.enter.pending", pe),
                  _use("finally.enter.world.before", we, UseRole.STATE_CONTENT),
                  _use("finally.enter.context.before", ce, UseRole.STATE_CONTENT))
    b.add(enter_id.value, (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), enter_uses,
        (saved_context, ew, ec), accesses=(
            StateAccess(b.world, enter_uses[1].id, AccessMode.READ_WRITE, ew,
                        Footprint(FootprintKind.WHOLE)),
            StateAccess(b.context, enter_uses[2].id, AccessMode.READ_WRITE, ec,
                        Footprint(FootprintKind.WHOLE))), effects_complete=False)
    replacement = pack("finally.fresh", xe) if replace_pending else None
    frame, detached = b.switch("finally.cleanup.detach", te, ec, attach=False)
    specs = [("pending", P.PENDING_COMPLETION), ("world", b.world),
             ("frame", P.FRAME_CONTEXT), ("saved-context", P.SAVED_HANDLED_CONTEXT),
             ("context", b.context), ("sent", "reference"), ("x", "reference")]
    if replace_pending:
        specs.append(("replacement", P.PENDING_COMPLETION))
    landing = args("finally.landing", specs)
    saved_uses = [_use("finally.suspend.frame", frame),
                  _use("finally.suspend.pending", pe),
                  _use("finally.suspend.saved-context", saved_context),
                  _use("finally.suspend.x", xe, UseRole.REFERENCE)]
    saved_roles = [S.FRAME_CONTEXT, S.PENDING_COMPLETION, S.CLEANUP_CONTEXT, S.VALUE]
    projections = [SavedInput(1), ResumeInput(2), SavedInput(0), SavedInput(2),
                   ResumeInput(0), ResumeInput(1), SavedInput(3)]
    if replace_pending:
        saved_uses.append(_use("finally.suspend.replacement", replacement))
        saved_roles.append(S.PENDING_COMPLETION)
        projections.append(SavedInput(4))
    exported = _use("finally.suspend.export", xe, UseRole.REFERENCE)
    hw = _use("finally.suspend.world", ew, UseRole.STATE_CONTENT)
    hc = _use("finally.suspend.context", detached, UseRole.STATE_CONTENT)
    b.add("finally.suspend", (Behavior.CONTROL,), (exported, *saved_uses, hw, hc),
        effects_complete=True, terminator=SuspendTerminator(SuspensionFlavor.YIELD,
            exported.id, tuple(SavedSlot(role, use.id) for role, use in zip(saved_roles, saved_uses)),
            (hw.id, hc.id), (ResumeSuccessor((ResumeSlot(I.STATE, b.context),
                ResumeSlot(I.SENT_VALUE), ResumeSlot(I.STATE, b.world)),
                BlockID("finally.landing"), tuple(projections)),)))
    caller1, attached = b.switch("finally.landing.attach", landing[2], landing[4], attach=True)
    exit_specs = [("world", b.world), ("pending", P.PENDING_COMPLETION),
                  ("caller", P.DRIVE_CALLER_CONTEXT), ("context", b.context),
                  ("saved-context", P.SAVED_HANDLED_CONTEXT)]
    exit_actuals = [(landing[1], UseRole.STATE_CONTENT), (landing[0], UseRole.PROTOCOL),
                   (caller1, UseRole.PROTOCOL), (attached, UseRole.STATE_CONTENT),
                   (landing[3], UseRole.PROTOCOL)]
    if replace_pending:
        exit_specs.append(("replacement", P.PENDING_COMPLETION))
        exit_actuals.append((landing[7], UseRole.PROTOCOL))
    exit_args = args("finally.finish-cleanup", exit_specs)
    landing_jump = jump("finally.landing.jump", "finally.finish-cleanup", exit_actuals)
    action_name = "finally.replace" if replace_pending else "finally.resume"
    action_uses, wa, ca = cleanup_action(action_name, exit_args[1], exit_args[4],
        exit_args[0], exit_args[3], exit_args[5] if replace_pending else None)
    route_args = args("finally.route", (("pending", P.PENDING_COMPLETION),
        ("world", b.world), ("context", b.context), ("caller", P.DRIVE_CALLER_CONTEXT)))
    action_jump = jump("finally.finish.jump", "finally.route", (
        (exit_args[5] if replace_pending else exit_args[1], UseRole.PROTOCOL),
        (wa, UseRole.STATE_CONTENT), (ca, UseRole.STATE_CONTENT), (exit_args[2], UseRole.PROTOCOL)))
    dispatch_args = args("finally.dispatch", (("world", b.world),
        ("caller", P.DRIVE_CALLER_CONTEXT), ("pending", P.PENDING_COMPLETION),
        ("context", b.context)))
    ru = (_use("finally.route.selector", route_args[0]),
          _use("finally.route.world", route_args[1], UseRole.STATE_CONTENT),
          _use("finally.route.caller", route_args[3]),
          _use("finally.route.pending", route_args[0]),
          _use("finally.route.context", route_args[2], UseRole.STATE_CONTENT))
    b.add("finally.route.op", (Behavior.CONTROL,), ru,
        terminator=CleanupRouteTerminator(ru[0].id, (
            CleanupRouteSuccessor(return_port, BlockID("finally.dispatch"),
                                  tuple(use.id for use in ru[1:])),)))
    result, wr, cr, tr = args("finally.exit", (("value", "reference"),
        ("world", b.world), ("context", b.context), ("caller", P.DRIVE_CALLER_CONTEXT)))
    du = (_use("finally.dispatch.pending", dispatch_args[2]),
          _use("finally.dispatch.world", dispatch_args[0], UseRole.STATE_CONTENT),
          _use("finally.dispatch.context", dispatch_args[3], UseRole.STATE_CONTENT),
          _use("finally.dispatch.caller", dispatch_args[1]))
    b.add("finally.dispatch.op", (Behavior.CONTROL,), du,
        terminator=PendingDispatchTerminator(du[0].id, (
            PendingSuccessor(return_port, BlockID("finally.exit"),
                             (PendingPayload(), du[1].id, du[2].id, du[3].id)),)))
    _, final_context = b.switch("finally.exit.detach", tr, cr, attach=False)
    ret = (_use("finally.return.value", result, UseRole.REFERENCE),
           _use("finally.return.world", wr, UseRole.STATE_CONTENT),
           _use("finally.return.context", final_context, UseRole.STATE_CONTENT))
    b.add("finally.return", (Behavior.CONTROL,), ret, terminator=Terminator(
        TerminatorKind.RETURN, exit="normal", values=tuple(use.id for use in ret)))
    b.block("finally.entry", (x, w0, c0), ("finally.initial", "finally.attach", entry_jump.id.value))
    b.block("finally.protected", (px, pw, pc, pt), ("finally.original", "finally.protected.route"))
    cleanup_ops = [enter_id.value]
    if replace_pending:
        cleanup_ops.append("finally.fresh")
    b.block("finally.cleanup", (pe, we, ce, te, xe),
            (*cleanup_ops, "finally.cleanup.detach", "finally.suspend"))
    b.block("finally.landing", landing, ("finally.landing.attach", landing_jump.id.value))
    b.block("finally.finish-cleanup", exit_args, (action_name, action_jump.id.value))
    b.block("finally.route", route_args, ("finally.route.op",))
    b.block("finally.dispatch", dispatch_args, ("finally.dispatch.op",))
    b.block("finally.exit", (result, wr, cr, tr), ("finally.exit.detach", "finally.return"))
    graph = b.finish("finally.entry", (ExitPort("normal", ExitKind.NORMAL,
        (ValueType(ValueKind.REFERENCE), ValueType(ValueKind.STATE, location=b.world),
         ValueType(ValueKind.STATE, location=b.context))),))
    scopes = (
        ControlScope(root_scope, b.region, None, ControlScopeKind.FUNCTION, _source("finally"),
            tuple(BlockID(name) for name in ("finally.entry", "finally.route", "finally.dispatch", "finally.exit"))),
        ControlScope(protected_scope, b.region, root_scope, ControlScopeKind.BLOCK,
                     _source("finally.protected"), (BlockID("finally.protected"),)),
        ControlScope(cleanup_scope, b.region, root_scope, ControlScopeKind.CLEANUP,
                     _source("finally.cleanup"), tuple(BlockID(name) for name in (
                         "finally.cleanup", "finally.landing", "finally.finish-cleanup"))),
    )
    exit_record = (CleanupReplace(OperationID(action_name), cleanup_scope,
        action_uses[0].id, action_uses[4].id, action_uses[1].id,
        ControlEdgeReference(action_jump.id, 0)) if replace_pending else
        CleanupResume(OperationID(action_name), cleanup_scope,
            action_uses[0].id, action_uses[1].id, ControlEdgeReference(action_jump.id, 0)))
    return replace(graph, control_scopes=scopes,
        control_ports=(ControlPort(return_port, root_scope, LanguageCompletionKind.RETURN,
                                  exit="normal"),),
        pending_completions=tuple(pending_definitions),
        handled_context_domains=(HandledContextDomain(b.region, b.context),),
        cleanup_interfaces=(CleanupInterface(cleanup_scope, protected_scope,
                            BlockID("finally.cleanup"), pe),),
        cleanup_enters=(CleanupEnter(enter_id, cleanup_scope, enter_uses[0].id, saved_context),),
        cleanup_resumes=() if replace_pending else (exit_record,),
        cleanup_replacements=(exit_record,) if replace_pending else ())


def resumption_invoke_program(*, leak_caller=False, reuse_use=False):
    """Unknown INVOKE returns fresh states on both paths; caller stays local.

    Leak mutations either reuse a control-port Use (invalid core binding) or
    add an independent actual for the same private caller Value (C2 escape).
    """
    b = _Body("invoke-resume")
    x = b.argument("invoke.x", "invoke.entry", 0, "reference")
    world = b.argument("invoke.world", "invoke.entry", 1, b.world)
    context = b.argument("invoke.context", "invoke.entry", 2, b.context)
    initial = b.initial("invoke.initial")
    caller, attached = b.switch("invoke.attach", initial, context, attach=True)
    nw = b.argument("invoke.normal.world", "invoke.normal", 0, b.world)
    nt = b.argument("invoke.normal.caller", "invoke.normal", 1, P.DRIVE_CALLER_CONTEXT)
    nc = b.argument("invoke.normal.context", "invoke.normal", 2, b.context)
    nx = b.argument("invoke.normal.x", "invoke.normal", 3, "reference")
    ft = b.argument("invoke.failure.caller", "invoke.failure", 0, P.DRIVE_CALLER_CONTEXT)
    fw = b.argument("invoke.failure.world", "invoke.failure", 1, b.world)
    packet = b.argument("invoke.failure.packet", "invoke.failure", 2, P.EXCEPTION_PACKET)
    fc = b.argument("invoke.failure.context", "invoke.failure", 3, b.context)
    uses = [_use("invoke.call.world", world, UseRole.STATE_CONTENT),
            _use("invoke.call.context", attached, UseRole.STATE_CONTENT),
            _use("invoke.call.normal.caller", caller),
            _use("invoke.call.normal.x", x, UseRole.REFERENCE),
            _use("invoke.call.failure.caller", caller)]
    actuals = [uses[0].id, uses[1].id]
    if leak_caller:
        if reuse_use:
            actuals.append(uses[2].id)
        else:
            leaked = _use("invoke.call.leaked-caller", caller)
            uses.append(leaked)
            actuals.append(leaked.id)
    state_types = (ValueType(ValueKind.STATE, location=b.world),
                   ValueType(ValueKind.STATE, location=b.context))
    b.add("invoke.call", (Behavior.CONTROL,), uses,
        completions=(CompletionSignature(ExitKind.NORMAL, state_types),
                     CompletionSignature(ExitKind.RAISE,
                        (ProtocolValueType(P.EXCEPTION_PACKET), *state_types))),
        invoke_arguments=tuple(actuals), effects_complete=False,
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID("invoke.normal"),
                (CompletionResult(0), uses[2].id, CompletionResult(1), uses[3].id)),
            CompletionSuccessor(ExitKind.RAISE, BlockID("invoke.failure"),
                (uses[4].id, CompletionResult(1), CompletionResult(0), CompletionResult(2))),)))
    for label, token, before, payload, w, kind, exit_name in (
        ("normal", nt, nc, nx, nw, TerminatorKind.RETURN, "normal"),
        ("failure", ft, fc, packet, fw, TerminatorKind.RAISE, "failure"),
    ):
        _, after = b.switch("invoke." + label + ".detach", token, before, attach=False)
        values = (_use("invoke." + label + ".payload", payload,
                       UseRole.REFERENCE if label == "normal" else UseRole.PROTOCOL),
                  _use("invoke." + label + ".world.out", w, UseRole.STATE_CONTENT),
                  _use("invoke." + label + ".context.out", after, UseRole.STATE_CONTENT))
        b.add("invoke." + label + ".exit", (Behavior.CONTROL,), values,
              terminator=Terminator(kind, exit=exit_name, values=tuple(use.id for use in values)))
    b.block("invoke.entry", (x, world, context),
            ("invoke.initial", "invoke.attach", "invoke.call"))
    b.block("invoke.normal", (nw, nt, nc, nx), ("invoke.normal.detach", "invoke.normal.exit"))
    b.block("invoke.failure", (ft, fw, packet, fc), ("invoke.failure.detach", "invoke.failure.exit"))
    return b.finish("invoke.entry", (
        ExitPort("normal", ExitKind.NORMAL, (ValueType(ValueKind.REFERENCE), *state_types)),
        ExitPort("failure", ExitKind.RAISE, (ProtocolValueType(P.EXCEPTION_PACKET), *state_types)),
    ))


def resumption_cleanup_invoke_program():
    """After a cleanup suspension, unknown work may Resume or Raise→Replace.

    Extend the stable Resume fixture instead of duplicating its Enter/capture/
    context setup. The call's two private outcomes carry distinct current
    world/context states; the new packet becomes a fresh pending Raise.
    """
    graph = resumption_cleanup_program()
    b = _Body("finally")
    b.values = list(graph.values)
    b.operations = [op for op in graph.operations if op.id != OperationID("finally.landing.jump")]
    b.detaches = list(graph.frame_context_detaches)
    raise_port = ControlPortID("finally.raise.port")
    cleanup_scope = ControlScopeID("finally.cleanup.scope")

    def args(block, specs):
        return tuple(b.argument(block + "." + suffix, block, index, kind)
                     for index, (suffix, kind) in enumerate(specs))

    failed = args("finally.failed", (("packet", P.EXCEPTION_PACKET),
        ("pending", P.PENDING_COMPLETION), ("world", b.world),
        ("caller", P.DRIVE_CALLER_CONTEXT), ("saved-context", P.SAVED_HANDLED_CONTEXT),
        ("context", b.context)))
    # Every formal/actual binding owns its Use, even when values alias.
    u = [_use("finally.invoke.world", "finally.landing.world", UseRole.STATE_CONTENT),
         _use("finally.invoke.context", "finally.landing.attach.after", UseRole.STATE_CONTENT),
         _use("finally.invoke.x", "finally.landing.x", UseRole.REFERENCE)]
    for label in ("normal", "raise"):
        u.extend((_use(f"finally.invoke.{label}.pending", "finally.landing.pending"),
                  _use(f"finally.invoke.{label}.caller", "finally.landing.attach.caller"),
                  _use(f"finally.invoke.{label}.saved-context", "finally.landing.saved-context")))
    state_types = (ValueType(ValueKind.STATE, location=b.world),
                   ValueType(ValueKind.STATE, location=b.context))
    b.add("finally.invoke", (Behavior.CONTROL,), u, effects_complete=False,
        invoke_arguments=tuple(use.id for use in u[:3]), completions=(
            CompletionSignature(ExitKind.NORMAL, state_types),
            CompletionSignature(ExitKind.RAISE, (ProtocolValueType(P.EXCEPTION_PACKET), *state_types))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID("finally.finish-cleanup"),
                (CompletionResult(0), u[3].id, u[4].id, CompletionResult(1), u[5].id)),
            CompletionSuccessor(ExitKind.RAISE, BlockID("finally.failed"),
                (CompletionResult(0), u[6].id, CompletionResult(1), u[7].id,
                 u[8].id, CompletionResult(2))),)))
    packet = _use("finally.new-raise.packet", failed[0])
    fresh = b.result("finally.new-raise.pending", "finally.new-raise", 0, P.PENDING_COMPLETION)
    b.add("finally.new-raise", (Behavior.CONTROL,), (packet,), (fresh,), effects_complete=True)
    replacement_args = args("finally.replace-raise", (("world", b.world),
        ("pending", P.PENDING_COMPLETION), ("replacement", P.PENDING_COMPLETION),
        ("caller", P.DRIVE_CALLER_CONTEXT), ("saved-context", P.SAVED_HANDLED_CONTEXT),
        ("context", b.context)))
    forwards = tuple(_use("finally.failed.out." + str(index), value, role)
        for index, (value, role) in enumerate(((failed[2], UseRole.STATE_CONTENT),
            (failed[1], UseRole.PROTOCOL), (fresh, UseRole.PROTOCOL),
            (failed[3], UseRole.PROTOCOL), (failed[4], UseRole.PROTOCOL),
            (failed[5], UseRole.STATE_CONTENT))))
    b.add("finally.failed.jump", (Behavior.CONTROL,), forwards, terminator=Terminator(
        TerminatorKind.JUMP, (Successor(BlockID("finally.replace-raise"),
                                     tuple(use.id for use in forwards)),)))
    inputs = (_use("finally.raise-replace.pending", replacement_args[1]),
              _use("finally.raise-replace.replacement", replacement_args[2]),
              _use("finally.raise-replace.saved-context", replacement_args[4]),
              _use("finally.raise-replace.world", replacement_args[0], UseRole.STATE_CONTENT),
              _use("finally.raise-replace.context", replacement_args[5], UseRole.STATE_CONTENT))
    wa = b.result("finally.raise-replace.world.after", "finally.raise-replace", 0, b.world)
    ca = b.result("finally.raise-replace.context.after", "finally.raise-replace", 1, b.context)
    b.add("finally.raise-replace", (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), inputs,
        (wa, ca), effects_complete=False, accesses=(
            StateAccess(b.world, inputs[3].id, AccessMode.READ_WRITE, wa, Footprint(FootprintKind.WHOLE)),
            StateAccess(b.context, inputs[4].id, AccessMode.READ_WRITE, ca, Footprint(FootprintKind.WHOLE))))
    forwarded = (_use("finally.raise-replace.out.pending", replacement_args[2]),
                 _use("finally.raise-replace.out.world", wa, UseRole.STATE_CONTENT),
                 _use("finally.raise-replace.out.context", ca, UseRole.STATE_CONTENT),
                 _use("finally.raise-replace.out.caller", replacement_args[3]))
    b.add("finally.raise-replace.jump", (Behavior.CONTROL,), forwarded, terminator=Terminator(
        TerminatorKind.JUMP, (Successor(BlockID("finally.route"), tuple(use.id for use in forwarded)),)))

    # Both selected pending variants meet in the original parent-scope corridor.
    selector = _use("finally.route.selector", "finally.route.pending")
    route_uses, route_edges = [selector], []
    for label, port in (("return", graph.control_ports[0].id), ("raise", raise_port)):
        actual = tuple(_use(f"finally.route.{label}.{index}", name, role)
            for index, (name, role) in enumerate((("finally.route.world", UseRole.STATE_CONTENT),
                ("finally.route.caller", UseRole.PROTOCOL), ("finally.route.pending", UseRole.PROTOCOL),
                ("finally.route.context", UseRole.STATE_CONTENT))))
        route_uses.extend(actual)
        route_edges.append(CleanupRouteSuccessor(port, BlockID("finally.dispatch"),
                                                 tuple(use.id for use in actual)))
    route = Operation(OperationID("finally.route.op"), "route selected pending",
        (Behavior.CONTROL,), tuple(route_uses), terminator=CleanupRouteTerminator(selector.id, tuple(route_edges)))
    raised = args("finally.raise-exit", (("packet", P.EXCEPTION_PACKET),
        ("world", b.world), ("context", b.context), ("caller", P.DRIVE_CALLER_CONTEXT)))
    selector = _use("finally.dispatch.pending", "finally.dispatch.pending")
    dispatch_uses, dispatch_edges = [selector], []
    for label, port, target in (("return", graph.control_ports[0].id, "finally.exit"),
                                ("raise", raise_port, "finally.raise-exit")):
        actual = tuple(_use(f"finally.dispatch.{label}.{index}", value, role)
            for index, (value, role) in enumerate((("finally.dispatch.world", UseRole.STATE_CONTENT),
                ("finally.dispatch.context", UseRole.STATE_CONTENT), ("finally.dispatch.caller", UseRole.PROTOCOL))))
        dispatch_uses.extend(actual)
        dispatch_edges.append(PendingSuccessor(port, BlockID(target),
                              (PendingPayload(), *(use.id for use in actual))))
    dispatch = Operation(OperationID("finally.dispatch.op"), "dispatch selected pending",
        (Behavior.CONTROL,), tuple(dispatch_uses),
        terminator=PendingDispatchTerminator(selector.id, tuple(dispatch_edges)))
    _, context = b.switch("finally.raise-exit.detach", raised[3], raised[2], attach=False)
    actual = (_use("finally.raise-exit.packet.out", raised[0]),
              _use("finally.raise-exit.world.out", raised[1], UseRole.STATE_CONTENT),
              _use("finally.raise-exit.context.out", context, UseRole.STATE_CONTENT))
    b.add("finally.raise-exit.op", (Behavior.CONTROL,), actual, terminator=Terminator(
        TerminatorKind.RAISE, exit="failure", values=tuple(use.id for use in actual)))
    b.operations = [route if op.id == route.id else dispatch if op.id == dispatch.id else op
                    for op in b.operations]
    blocks = tuple(replace(block, operations=(block.operations[0], OperationID("finally.invoke")))
        if block.id == BlockID("finally.landing") else block for block in graph.regions[0].blocks)
    extra_blocks = (
        Block(BlockID("finally.failed"), failed, (OperationID("finally.new-raise"), OperationID("finally.failed.jump"))),
        Block(BlockID("finally.replace-raise"), replacement_args,
              (OperationID("finally.raise-replace"), OperationID("finally.raise-replace.jump"))),
        Block(BlockID("finally.raise-exit"), raised,
              (OperationID("finally.raise-exit.detach"), OperationID("finally.raise-exit.op"))),
    )
    scopes = tuple(replace(scope, blocks=(*scope.blocks,
        *(block.id for block in extra_blocks[:2]))) if scope.id == cleanup_scope else
        replace(scope, blocks=(*scope.blocks, extra_blocks[2].id))
        if scope.kind is ControlScopeKind.FUNCTION else scope for scope in graph.control_scopes)
    return replace(graph, values=tuple(b.values), operations=tuple(b.operations),
        regions=(replace(graph.regions[0], blocks=(*blocks, *extra_blocks),
            exits=(*graph.regions[0].exits, ExitPort("failure", ExitKind.RAISE,
                (ProtocolValueType(P.EXCEPTION_PACKET), *state_types)))),),
        control_scopes=scopes, control_ports=(*graph.control_ports,
            ControlPort(raise_port, ControlScopeID("finally.function"), LanguageCompletionKind.RAISE, exit="failure")),
        pending_completions=(*graph.pending_completions,
            PendingCompletionDefinition(fresh, raise_port, packet.id)),
        cleanup_replacements=(CleanupReplace(OperationID("finally.raise-replace"), cleanup_scope,
            inputs[0].id, inputs[1].id, inputs[2].id,
            ControlEdgeReference(OperationID("finally.raise-replace.jump"), 0)),),
        frame_context_detaches=tuple(b.detaches))
