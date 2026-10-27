"""Original ordinary-except ports, without native category/identity claims.

The matcher declarations interpret existing operations.  Removing every
``exception_matches`` row leaves the same canonical CFG, Uses and producers.
"""
from dataclasses import replace

from scar.ir.program.control import ProtocolValueKind, ProtocolValueType
from scar.ir.program.exception_matches import (
    BuiltinExceptionCategory, ExceptionHandlerOperand, ExceptionMatcher,
    FixedBuiltinHandler,
)
from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, DataValue, ExitKind, ExitPort, InvokeLiteralResult, Operation,
    OperationResult, ProgramGraph, ProtocolValue, ReferenceValue, Region, StateAccess,
    StateLocation, StateVersionValue, Successor, Terminator, TerminatorKind, Use,
    UseRole, ValueKind, ValueType,
)
from scar.ir.program.protocol_connections import ProtocolOperationRef
from scar.ir.program.protocols import ContractResult, OwnedUse, StaticGapReason, StaticProtocolGap
from scar.ir.program.state_addresses import ExistingAccess, InvokeStateOperand
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_method_lookup_graphs import method_lookup_program
from tests.fixtures.program_protocol_graphs import _scope


REFERENCE = ValueType(ValueKind.REFERENCE)
BOOLEAN = ValueType(ValueKind.DATA, "builtins.bool")
PACKET = ProtocolValueType(ProtocolValueKind.EXCEPTION_PACKET)


def _fixed_handler():
    return FixedBuiltinHandler(BuiltinExceptionCategory.ATTRIBUTE_ERROR,
        StaticProtocolGap(StaticGapReason.NATIVE_APPLICABILITY_UNPROVEN))


class _Graph:
    def __init__(self):
        self.region = RegionID("exception-match")
        self.location = LocationID("exception-match.world")
        self.state_type = ValueType(ValueKind.STATE, location=self.location)
        self.values, self.operations, self.blocks = [], [], []

    def formal(self, name, block, ordinal, type_):
        identity, origin = ValueID(name), BlockArgument(block, ordinal)
        if type_ == self.state_type:
            value = StateVersionValue(identity, self.region, origin, self.location)
        elif type_ == BOOLEAN:
            value = DataValue(identity, self.region, origin, "builtins.bool")
        elif type_ == PACKET:
            value = ProtocolValue(identity, self.region, origin,
                                  ProtocolValueKind.EXCEPTION_PACKET)
        else:
            value = ReferenceValue(identity, self.region, origin)
        self.values.append(value)
        return value

    @staticmethod
    def use(name, value):
        role = (UseRole.STATE_CONTENT if isinstance(value, StateVersionValue) else
                UseRole.DATA if isinstance(value, DataValue) else
                UseRole.PROTOCOL if isinstance(value, ProtocolValue) else UseRole.REFERENCE)
        return Use(UseID(name), value.id, role)

    def terminal(self, name, block, payload, state):
        actuals = (self.use(name + ".payload", payload), self.use(name + ".state", state))
        raised = isinstance(payload, ProtocolValue)
        operation = Operation(OperationID(name), "original selected terminal", (Behavior.CONTROL,),
            actuals, effects_complete=True,
            terminator=Terminator(TerminatorKind.RAISE if raised else TerminatorKind.RETURN,
                exit="failure" if raised else "normal", values=tuple(use.id for use in actuals)))
        self.operations.append(operation)
        return operation

    def branch(self, block, payload, state, boolean, payload_type):
        operation_id = OperationID("exception-match.branch")
        condition = self.use("exception-match.branch.bool", boolean)
        uses, edges, terminals = [condition], [], []
        for ordinal, label in enumerate(("matched", "unmatched")):
            destination = BlockID("exception-match." + label)
            formals = (self.formal(destination.value + ".input", destination, 0, payload_type),
                       self.formal(destination.value + ".state", destination, 1, self.state_type))
            actuals = (self.use(destination.value + ".forward.input", payload),
                       self.use(destination.value + ".forward.state", state))
            uses.extend(actuals)
            edges.append(Successor(destination, tuple(use.id for use in actuals)))
            terminal = self.terminal(destination.value + ".exit", destination, *formals)
            self.blocks.append(Block(destination, tuple(value.id for value in formals), (terminal.id,)))
            terminals.append(terminal)
        branch = Operation(operation_id, "branch on this matcher bool", (Behavior.CONTROL,),
            tuple(uses), effects_complete=True,
            terminator=Terminator(TerminatorKind.BRANCH, tuple(edges), condition=condition.id))
        self.operations.append(branch)
        return branch, tuple(terminals)


def exception_match_program(*, mode="ordinary", input_kind="reference", known_callee=False,
                            forward_state=False):
    """Return one genuine matcher plus independent same-typed source decoys.

    ``ordinary`` is a fixed intrinsic with its real coarse READ and no handler
    operand. ``invoke`` has a real dynamic handler and reversed R/N edges.
    NORMAL's bool is slot 1, landing formal 2, after an original forwarded Use;
    RAISE's packet is slot 1, landing formal 0. ``raise-only`` has no NORMAL
    signature, bool, branch, or fake successful path.

    ``forward_state`` instead declares a complete-effects opaque invocation:
    each N/R landing receives the unchanged original state through its own
    edge Use, while completion signatures contain only bool/packet results.
    """
    if mode not in ("ordinary", "invoke", "raise-only"):
        raise ValueError("unknown matcher fixture mode")
    if input_kind not in ("reference", "packet"):
        raise ValueError("unknown matcher fixture input kind")
    if known_callee and mode != "invoke":
        raise ValueError("known callee fixture retains both actual completion paths")
    if forward_state and (mode != "invoke" or known_callee):
        raise ValueError("forwarded-state fixture is a separate complete-effects opaque INVOKE")
    b, entry = _Graph(), BlockID("exception-match.entry")
    payload_type = REFERENCE if input_kind == "reference" else PACKET
    inputs = tuple(b.formal(f"exception-match.input.{ordinal}", entry, ordinal, type_)
                   for ordinal, type_ in enumerate((payload_type, payload_type, REFERENCE,
                                                    REFERENCE, BOOLEAN, b.state_type)))
    payload, unrelated_payload, handler_value, unrelated_handler, unrelated_bool, initial = inputs
    probe_use = b.use("exception-match.probe.state", initial)
    probe = Operation(OperationID("exception-match.probe"), "independent original state read",
        (Behavior.READ,), (probe_use,),
        accesses=(StateAccess(b.location, probe_use.id, AccessMode.READ),), effects_complete=True)
    b.operations.append(probe)
    identity = OperationID("exception-match.evaluate")
    input_use, state_use = b.use("exception-match.packet", payload), b.use("exception-match.state", initial)
    raised_port, handler_use, normal_port = None, None, None
    boolean, branch, branch_terminals = None, None, ()
    normal_state, raised_state, raised_packet = initial, None, None
    entry_arguments = tuple(value.id for value in inputs)
    if mode == "ordinary":
        boolean = DataValue(ValueID("exception-match.bool"), b.region,
                            OperationResult(identity, 0), "builtins.bool")
        b.values.append(boolean)
        operation = Operation(identity, "fixed builtin ordinary exception match",
            (Behavior.COMPUTE, Behavior.READ), (input_use, state_use), (boolean.id,),
            accesses=(StateAccess(b.location, state_use.id, AccessMode.READ),), effects_complete=True)
        b.operations.append(operation)
        normal_port = OperationResult(identity, 0)
        branch, branch_terminals = b.branch(entry, payload, initial, boolean, payload_type)
        b.blocks.insert(0, Block(entry, entry_arguments, (probe.id, operation.id, branch.id)))
        handler, sites = _fixed_handler(), (ExistingAccess(identity, 0),)
    else:
        handler_use = b.use("exception-match.handler", handler_value)
        actuals = (input_use, handler_use, state_use)
        failure = BlockID("exception-match.raised")
        raised_packet = b.formal("exception-match.raised.packet", failure, 0, PACKET)
        raised_state = b.formal("exception-match.raised.state", failure, 1, b.state_type)
        packet_slot = 0 if forward_state else 1
        raised_port = InvokeLiteralResult(ControlEdgeReference(identity, 0), CompletionResult(packet_slot))
        signatures = [CompletionSignature(ExitKind.RAISE,
                         (PACKET,) if forward_state else (b.state_type, PACKET))]
        raised_forward = b.use("exception-match.raised.forward.state", initial) if forward_state else None
        edges = [CompletionSuccessor(ExitKind.RAISE, failure,
                    (CompletionResult(packet_slot),
                     raised_forward.id if forward_state else CompletionResult(0)))]
        uses = [*actuals, *((raised_forward,) if forward_state else ())]
        if mode == "invoke":
            normal = BlockID("exception-match.normal")
            forwarded = b.use("exception-match.normal.forward", payload)
            uses.append(forwarded)
            normal_payload = b.formal("exception-match.normal.input", normal, 0, payload_type)
            normal_state = b.formal("exception-match.normal.state", normal, 1, b.state_type)
            boolean = b.formal("exception-match.normal.bool", normal, 2, BOOLEAN)
            normal_forward = b.use("exception-match.normal.forward.state", initial) if forward_state else None
            if forward_state:
                uses.append(normal_forward)
            bool_slot = 0 if forward_state else 1
            signatures.append(CompletionSignature(ExitKind.NORMAL,
                                (BOOLEAN,) if forward_state else (b.state_type, BOOLEAN)))
            edges.append(CompletionSuccessor(ExitKind.NORMAL, normal,
                (forwarded.id, normal_forward.id if forward_state else CompletionResult(0),
                 CompletionResult(bool_slot))))
            normal_port = InvokeLiteralResult(ControlEdgeReference(identity, 1), CompletionResult(bool_slot))
            branch, branch_terminals = b.branch(normal, normal_payload, normal_state, boolean, payload_type)
            b.blocks.insert(0, Block(normal, (normal_payload.id, normal_state.id, boolean.id), (branch.id,)))
        operation = Operation(identity, "dynamic handler type-check and exception match",
            (Behavior.CONTROL,), tuple(uses), effects_complete=forward_state,
            invoke_arguments=tuple(use.id for use in actuals), completions=tuple(signatures),
            terminator=Terminator(TerminatorKind.INVOKE, tuple(edges)))
        b.operations.append(operation)
        raised_exit = b.terminal("exception-match.raised.exit", failure, raised_packet, raised_state)
        b.blocks.extend((Block(failure, (raised_packet.id, raised_state.id), (raised_exit.id,)),
                         Block(entry, entry_arguments, (probe.id, operation.id))))
        handler = ExceptionHandlerOperand(handler_use.id, handler_value.origin, _fixed_handler())
        sites = (InvokeStateOperand(identity, state_use.id),)
    row = ExceptionMatcher(identity, input_use.id, payload.origin, handler, normal_port,
        raised_port, None if branch is None else branch.id, sites)
    exits = []
    if input_kind == "reference" and mode != "raise-only":
        exits.append(ExitPort("normal", ExitKind.NORMAL, (REFERENCE, b.state_type)))
    if input_kind == "packet" or mode != "ordinary":
        exits.append(ExitPort("failure", ExitKind.RAISE, (PACKET, b.state_type)))
    region = Region(b.region, "ordinary except matching ports", entry, tuple(b.blocks), tuple(exits))
    graph = ProgramGraph(b.region, (region,), tuple(b.operations), tuple(b.values),
        locations=(StateLocation(b.location, "coarse current world"),),
        control_scopes=(_scope(b.region, b.blocks),), exception_matches=(row,))
    details = {"matcher": row, "operation": operation, "entry": entry,
        "input": payload, "input_use": input_use, "wrong_input": unrelated_payload,
        "handler": handler_value, "handler_use": handler_use, "wrong_handler": unrelated_handler,
        "wrong_bool": unrelated_bool, "initial_state": initial, "normal_state": normal_state,
        "raised_state": raised_state, "raised_packet": raised_packet,
        "normal": normal_port, "raised": raised_port, "bool": boolean, "branch": branch,
        "terminals": branch_terminals, "probe": probe, "state_sites": sites}
    return _with_known_callee(graph, details, payload_type) if known_callee else (graph, details)


def _with_known_callee(graph, details, payload_type):
    """Expand the existing INVOKE as a real helper, retaining its signatures.

    The helper has a normal bool result and a distinct failure construction
    with a world write.  Its two control choices are ordinary core producers;
    no native class/tuple validity is inferred from their names or shapes.
    """
    b = _Graph()
    b.region, b.location = RegionID("exception-match.helper"), graph.locations[0].id
    b.state_type = ValueType(ValueKind.STATE, location=b.location)
    entry, normal, failure = (BlockID("exception-match.helper." + suffix)
                              for suffix in ("entry", "normal", "failure"))
    payload, handler, state = (b.formal("exception-match.helper.input." + str(index), entry, index, type_)
                               for index, type_ in enumerate((payload_type, REFERENCE, b.state_type)))
    evaluate_id = OperationID("exception-match.helper.evaluate")
    valid = DataValue(ValueID("exception-match.helper.valid"), b.region,
                      OperationResult(evaluate_id, 0), "builtins.bool")
    matched = DataValue(ValueID("exception-match.helper.matched"), b.region,
                        OperationResult(evaluate_id, 1), "builtins.bool")
    b.values.extend((valid, matched))
    actuals = (b.use("exception-match.helper.evaluate.input", payload),
               b.use("exception-match.helper.evaluate.handler", handler),
               b.use("exception-match.helper.evaluate.state", state))
    evaluate = Operation(evaluate_id, "original validity and match evaluation",
        (Behavior.COMPUTE, Behavior.READ), actuals, (valid.id, matched.id),
        accesses=(StateAccess(b.location, actuals[-1].id, AccessMode.READ),), effects_complete=True)
    n_state = b.formal("exception-match.helper.normal.state", normal, 0, b.state_type)
    n_bool = b.formal("exception-match.helper.normal.bool", normal, 1, BOOLEAN)
    r_handler = b.formal("exception-match.helper.failure.handler", failure, 0, REFERENCE)
    r_state = b.formal("exception-match.helper.failure.state", failure, 1, b.state_type)
    condition = b.use("exception-match.helper.choose.condition", valid)
    n_actuals = (b.use("exception-match.helper.choose.normal.state", state),
                 b.use("exception-match.helper.choose.normal.bool", matched))
    r_actuals = (b.use("exception-match.helper.choose.failure.handler", handler),
                 b.use("exception-match.helper.choose.failure.state", state))
    choose = Operation(OperationID("exception-match.helper.choose"), "original handler validity branch",
        (Behavior.CONTROL,), (condition, *n_actuals, *r_actuals), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH, (
            Successor(normal, tuple(use.id for use in n_actuals)),
            Successor(failure, tuple(use.id for use in r_actuals))), condition=condition.id))
    returns = (b.use("exception-match.helper.return.state", n_state),
               b.use("exception-match.helper.return.bool", n_bool))
    returned = Operation(OperationID("exception-match.helper.return"), "helper normal completion",
        (Behavior.CONTROL,), returns, effects_complete=True,
        terminator=Terminator(TerminatorKind.RETURN, exit="normal", values=tuple(use.id for use in returns)))
    error_id = OperationID("exception-match.helper.new-error")
    error = ReferenceValue(ValueID("exception-match.helper.error"), b.region, OperationResult(error_id, 0))
    traceback = ReferenceValue(ValueID("exception-match.helper.traceback"), b.region, OperationResult(error_id, 1))
    after = StateVersionValue(ValueID("exception-match.helper.error.state"), b.region,
                              OperationResult(error_id, 2), b.location)
    b.values.extend((error, traceback, after))
    error_actuals = (b.use("exception-match.helper.error.handler", r_handler),
                     b.use("exception-match.helper.error.before", r_state))
    construct = Operation(error_id, "original new error and traceback with current world effects",
        (Behavior.COMPUTE, Behavior.READ, Behavior.WRITE), error_actuals,
        (error.id, traceback.id, after.id),
        accesses=(StateAccess(b.location, error_actuals[-1].id, AccessMode.READ_WRITE, after.id),),
        effects_complete=False)
    pack_id = OperationID("exception-match.helper.packet")
    packet = ProtocolValue(ValueID("exception-match.helper.packet.value"), b.region,
                            OperationResult(pack_id, 0), ProtocolValueKind.EXCEPTION_PACKET)
    b.values.append(packet)
    components = (b.use("exception-match.helper.packet.exception", error),
                  b.use("exception-match.helper.packet.traceback", traceback))
    pack = Operation(pack_id, "original exception/traceback packet", (Behavior.CONTROL,),
        components, (packet.id,), effects_complete=True)
    raised_uses = (b.use("exception-match.helper.raise.state", after),
                   b.use("exception-match.helper.raise.packet", packet))
    raised = Operation(OperationID("exception-match.helper.raise"), "helper exceptional completion",
        (Behavior.CONTROL,), raised_uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.RAISE, exit="failure", values=tuple(use.id for use in raised_uses)))
    blocks = (Block(entry, (payload.id, handler.id, state.id), (evaluate.id, choose.id)),
              Block(normal, (n_state.id, n_bool.id), (returned.id,)),
              Block(failure, (r_handler.id, r_state.id), (construct.id, pack.id, raised.id)))
    child = Region(b.region, "expanded handler matching helper", entry, blocks,
        (ExitPort("normal", ExitKind.NORMAL, (b.state_type, BOOLEAN)),
         ExitPort("failure", ExitKind.RAISE, (b.state_type, PACKET))), parent=graph.root)
    invocation = replace(details["operation"], callee=child.id)
    from scar.ir.program.control import ExceptionPacketDefinition
    graph = replace(graph, regions=(*graph.regions, child),
        operations=tuple(invocation if row.id == invocation.id else row for row in graph.operations)
                   + (evaluate, choose, returned, construct, pack, raised),
        values=(*graph.values, *b.values), control_scopes=(*graph.control_scopes, _scope(child.id, blocks)),
        exception_packets=(*graph.exception_packets,
            ExceptionPacketDefinition(packet.id, components[0].id, components[1].id)))
    return graph, {**details, "operation": invocation, "callee": child,
                   "callee_normal": returned, "callee_raised": raised, "callee_after": after}


def lookup_exception_match_program(*, attach=True):
    """Extend the real lookup RAISE consumer, preserving all old normal routes.

    This proves a connection opportunity, not missing-method fallback: both
    matcher bool branches still propagate the exact lookup packet.  The
    independent builtin interpretation remains explicitly unproved.
    """
    graph, prior = method_lookup_program(request="throw")
    region, = graph.regions
    lookup_row = prior["method_rows"][1]
    old_exit = prior["method_failure"]
    payload_id, state_id = prior["method"]["failure_values"]
    values = {value.id: value for value in graph.values}
    payload, state = values[payload_id], values[state_id]
    identity, branch_id = OperationID("lookup.match"), OperationID("lookup.match.branch")
    boolean = DataValue(ValueID("lookup.match.bool"), region.id, OperationResult(identity, 0), "builtins.bool")
    input_use = Use(UseID("lookup.match.packet"), payload.id, UseRole.PROTOCOL)
    state_use = Use(UseID("lookup.match.state"), state.id, UseRole.STATE_CONTENT)
    matcher_op = Operation(identity, "fixed AttributeError interpretation of this lookup packet",
        (Behavior.COMPUTE, Behavior.READ), (input_use, state_use), (boolean.id,),
        accesses=(StateAccess(state.location, state_use.id, AccessMode.READ),), effects_complete=True)
    uses = [Use(UseID("lookup.match.condition"), boolean.id, UseRole.DATA)]
    edges, added_values, added_blocks, terminals = [], [boolean], [], []
    for ordinal, label in enumerate(("matched", "unmatched")):
        block = BlockID("lookup.match." + label)
        packet = replace(payload, id=ValueID(block.value + ".packet"), origin=BlockArgument(block, 0))
        after = replace(state, id=ValueID(block.value + ".state"), origin=BlockArgument(block, 1))
        added_values.extend((packet, after))
        forwarded = (Use(UseID(block.value + ".forward.packet"), payload.id, UseRole.PROTOCOL),
                     Use(UseID(block.value + ".forward.state"), state.id, UseRole.STATE_CONTENT))
        uses.extend(forwarded)
        edges.append(Successor(block, tuple(use.id for use in forwarded)))
        exit_uses = (Use(UseID(block.value + ".raise.packet"), packet.id, UseRole.PROTOCOL),
                     Use(UseID(block.value + ".raise.state"), after.id, UseRole.STATE_CONTENT))
        terminal = Operation(OperationID(block.value + ".raise"), "propagate this lookup packet",
            (Behavior.CONTROL,), exit_uses, effects_complete=True,
            terminator=Terminator(TerminatorKind.RAISE, exit="failure", values=tuple(use.id for use in exit_uses)))
        terminals.append(terminal)
        added_blocks.append(Block(block, (packet.id, after.id), (terminal.id,)))
    branch = Operation(branch_id, "actual lookup-category bool branch", (Behavior.CONTROL,),
        tuple(uses), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH, tuple(edges), condition=uses[0].id))
    source = ContractResult(lookup_row.scope, lookup_row.clause, lookup_row.operation,
                            lookup_row.slot, lookup_row.contract.result)
    matcher = ExceptionMatcher(identity, input_use.id, source, _fixed_handler(),
        OperationResult(identity, 0), None, branch.id, (ExistingAccess(identity, 0),))
    consumer_site = ProtocolOperationRef(lookup_row.scope, lookup_row.clause,
                                        lookup_row.operation, lookup_row.slot)
    consumers = tuple(replace(row, targets=(OwnedUse(identity, input_use.id),))
        if row.site == consumer_site else row for row in graph.protocol_result_consumers)
    blocks = tuple(replace(block, operations=(matcher_op.id, branch.id))
        if old_exit.id in block.operations else block for block in region.blocks) + tuple(added_blocks)
    graph = replace(graph, regions=(replace(region, blocks=blocks),),
        operations=tuple(operation for operation in graph.operations if operation.id != old_exit.id)
                   + (matcher_op, branch, *terminals), values=(*graph.values, *added_values),
        protocol_result_consumers=consumers,
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in blocks))
                             for scope in graph.control_scopes),
        exception_matches=(matcher,) if attach else ())
    return graph, {"prior": prior, "lookup_row": lookup_row, "matcher": matcher,
                   "operation": matcher_op, "input_use": input_use, "branch": branch,
                   "terminals": tuple(terminals), "consumer_site": consumer_site}


__all__ = ["exception_match_program", "lookup_exception_match_program"]
