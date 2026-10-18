"""Supplied generator matrix source routes on original program ports.

These are declarations, not a captured generator activation or native proof.
The caller owns each raw pack; predicates consume only their actual inputs.
"""
from dataclasses import fields, is_dataclass, replace

from scar.ir.literals import PythonLiteral
from scar.ir.program.control import ControlScope, ControlScopeKind
from scar.ir.program.drivers import (
    CreationCapture, NormalResultPort, RawRequestDefinition, RawRequestKind, ResumableCreate,
)
from scar.ir.program.ids import BlockID, ControlScopeID, LocationID, OperationID, ProtocolScopeID, UseID, ValueID
from scar.ir.program.lifecycle import DriverLifecycle
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, DataValue, ExitKind, InvokeLiteralResult, LiteralEvaluation,
    Operation, OperationResult, ProgramGraph, ProtocolValue, ReferenceValue, StateAccess, StateLocation, StateVersionValue, Successor,
    Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType, value_type,
)
from scar.ir.program.protocols import (
    AdmissionPredicate, BodyStateCondition, BodyStatePredicateRule, DriverSubject,
    HostTerminal, NoEntryOutcome, OperationSiteSubject, ProtocolClause as C,
    ProtocolOperation, ProtocolProfile as F, ProtocolScope, ReferenceIsNoneCondition,
    RequestOperandBinding, RequestProcessing, RequestProcessingRule as R,
)
from scar.ir.program.state_addresses import ExistingAccess, InvokeStateOperand
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_control_graphs import _source
from tests.fixtures.program_driver_graphs import (
    PACKET, RAW, REFERENCE, _Builder, _body_with_environment, _use, driver_program, driver_rule,
)
from tests.fixtures.program_generator_close_graphs import _body_yield_after_packet, generator_close_program
from tests.fixtures.program_generator_close_retry_graphs import _branching_body, _driver_part, _first_driver
from tests.fixtures.program_no_body_graphs import no_body_program
from tests.fixtures.program_protocol_graphs import _insert_processing, _source_gap, closed_request_program
from tests.fixtures.program_publication_graphs import with_publications
from tests.fixtures.program_resumption_graphs import resumption_two_cuts_program


def _op(graph, identity):
    return next(op for op in graph.operations if op.id == identity)


def _role(value):
    return (UseRole.STATE_CONTENT if isinstance(value, StateVersionValue) else
            UseRole.REFERENCE if isinstance(value, ReferenceValue) else UseRole.PROTOCOL)


def _state_types(graph):
    return tuple(ValueType(ValueKind.STATE, location=location.id) for location in graph.locations)


def _scope(graph):
    interface, = graph.driver_interfaces
    identity = ProtocolScopeID("matrix.driver.scope")
    scope = ProtocolScope(identity, F.GENERATOR_BODY_V1, DriverSubject(interface.region), _source_gap())
    return replace(graph, protocol_scopes=(scope,), protocol_operations=()), identity


def _environment(graph):
    environment = _body_with_environment()
    refs = tuple(value for value in environment.values if value.id.value.startswith("resume.environment."))
    region = graph.regions[0]
    return replace(graph, values=(*graph.values, *refs), regions=(replace(region,
        blocks=tuple(replace(block, arguments=(*block.arguments, *(ref.id for ref in refs)))
                     if block.id == region.entry else block for block in region.blocks)),),
        environments=environment.environments, function_entries=environment.function_entries)


def _body():
    """One body genuinely yields after either SENT or caught packet ingress."""
    sent, packet = resumption_two_cuts_program(), _body_yield_after_packet()
    changes = {OperationID("resume.raise"): _op(packet, OperationID("resume.raise"))}
    operations = tuple(changes.get(op.id, op) for op in sent.operations)
    known = {op.id for op in operations}
    operations += tuple(op for op in packet.operations
                        if op.id not in known and op.id != OperationID("resume.return"))
    values = {value.id: value for value in sent.values}
    values.update((value.id, value) for value in packet.values if value.id not in values)
    blocks = {block.id: block for block in sent.regions[0].blocks}
    blocks.update((block.id, block) for block in packet.regions[0].blocks if block.id not in blocks)
    def union(left, right):
        return (*left, *(item for item in right if item not in left))
    graph = replace(sent, operations=operations, values=tuple(values.values()),
        regions=(replace(sent.regions[0], blocks=tuple(blocks.values())),),
        frame_context_attaches=union(sent.frame_context_attaches, packet.frame_context_attaches),
        frame_context_detaches=union(sent.frame_context_detaches, packet.frame_context_detaches),
        control_scopes=tuple(replace(scope, blocks=tuple(blocks)) for scope in sent.control_scopes))
    # Reuse the existing complete function environment, adding only its actual
    # entry references to this same body definition; no new producer is made.
    return _environment(graph)


def _driver(target, *, body_graph=None):
    graph = driver_program(target=target, body_graph=_body() if body_graph is None else body_graph)
    graph, scope = _scope(graph)
    details = {"scope": scope, "drive": graph.body_drives[0].operation}
    if target != "start":
        original_exits = next(region for region in graph.regions if region.id == graph.root).exits
        graph, processing = _insert_processing(graph, target=target)
        if body_graph is None:
            graph = replace(graph, regions=tuple(replace(region, exits=original_exits)
                if region.id == graph.root else region for region in graph.regions))
        # The old generic packet driver accepted a prepacked boundary input;
        # this actual method reads an original class/instance reference instead.
        interface, = graph.driver_interfaces
        region = next(region for region in graph.regions if region.id == interface.region)
        entry = next(block for block in region.blocks if block.id == region.entry)
        argument = next(value for value in graph.values if value.id == entry.arguments[2])
        if target == "packet":
            argument = ReferenceValue(argument.id, argument.region, argument.origin)
            graph = replace(graph, values=tuple(argument if value.id == argument.id else value
                                                for value in graph.values))
        helper = _op(graph, processing["processing"])
        expanded = _use("matrix.normalization.argument", argument.id)
        helper = replace(helper, uses=(*helper.uses, expanded),
                         invoke_arguments=(*helper.invoke_arguments, expanded.id))
        graph = replace(graph, operations=tuple(helper if op.id == helper.id else op for op in graph.operations))
        rule = R.NORMALIZE_THROW_CLASS if target == "packet" else R.CHECK_SEND
        rows = tuple(ProtocolOperation(scope, C.REQUEST_PROCESSING, processing["processing"], number,
            RequestProcessing(processing["raw_use"], (RequestOperandBinding(0, expanded.id),), processing[result],
                              processing["state_sites"], rule), _source_gap())
            for number, result in ((0, "normal_result"), (1, "raise_result")))
        graph = replace(graph, protocol_operations=rows)
        details.update(processing)
    return with_publications(graph), details


def _created_close(graph):
    """Reuse the original no-body predicate/mark without moving a later gate."""
    template = no_body_program()
    interface, = graph.driver_interfaces
    region = next(region for region in graph.regions if region.id == interface.region)
    entry = next(block for block in region.blocks if block.id == region.entry)
    template_region = next(region for region in template.regions if region.id == interface.region)
    template_entry = next(block for block in template_region.blocks if block.id == template_region.entry)
    test, = template.created_close_tests
    branch = _op(template, OperationID("driver.created_close.branch"))
    true_block = next(block for block in template_region.blocks
                      if block.id == branch.terminator.successors[0].block)
    false_id = BlockID("matrix.close.noncreated")
    mapping = dict(zip(template_entry.arguments, entry.arguments))
    def remap(value):
        if type(value) is ValueID:
            return mapping.get(value, value)
        if type(value) is BlockID and value == branch.terminator.successors[1].block:
            return false_id
        if type(value) is tuple:
            return tuple(remap(item) for item in value)
        if is_dataclass(value):
            return replace(value, **{field.name: remap(getattr(value, field.name)) for field in fields(value)})
        return value
    values = {value.id: value for value in graph.values}
    false_values = tuple(replace(values[identity], id=ValueID(f"matrix.close.noncreated.{number}"),
                                 origin=BlockArgument(false_id, number))
                         for number, identity in enumerate(entry.arguments))
    substitution = dict(zip(entry.arguments, (value.id for value in false_values)))
    operations = tuple(replace(op, uses=tuple(replace(use, value=substitution.get(use.value, use.value))
                                            for use in op.uses)) for op in graph.operations)
    ids = {test.operation, branch.id, *true_block.operations}
    additions = tuple(remap(op) for op in template.operations if op.id in ids)
    added_values = tuple(remap(value) for value in template.values if (
        isinstance(value.origin, OperationResult) and value.origin.operation in ids
        or isinstance(value.origin, BlockArgument) and value.origin.block == true_block.id))
    blocks = tuple(replace(block, operations=(test.operation, branch.id)) if block.id == entry.id else block
                   for block in region.blocks)
    blocks += (remap(true_block), Block(false_id, tuple(value.id for value in false_values), entry.operations))
    return replace(graph, operations=(*operations, *additions),
        values=(*graph.values, *false_values, *added_values),
        regions=tuple(replace(item, blocks=blocks) if item.id == region.id else item for item in graph.regions),
        created_close_tests=(remap(test),), no_body_finishes=tuple(remap(row) for row in template.no_body_finishes),
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in blocks))
                             if scope.region == region.id else scope for scope in graph.control_scopes))


def _ensure_extra_reference(graph):
    interface, = graph.driver_interfaces
    region = next(region for region in graph.regions if region.id == interface.region)
    entry = next(block for block in region.blocks if block.id == region.entry)
    value = ReferenceValue(ValueID("matrix.send.argument"), region.id,
                           BlockArgument(entry.id, len(entry.arguments)))
    graph = replace(graph, values=(*graph.values, value), regions=tuple(replace(item,
        blocks=tuple(replace(block, arguments=(*block.arguments, value.id))
                     if block.id == entry.id else block for block in item.blocks))
        if item.id == region.id else item for item in graph.regions))
    return graph, value.id


def _guard(graph, *, block_id, owner, raw, label, rule=None, input_value=None,
           admit_true=True, request_kind=RawRequestKind.NEXT, initial=None):
    """Split a real block before its existing computation, with a genuine reject helper."""
    interface, = graph.driver_interfaces
    region = next(region for region in graph.regions if region.id == interface.region)
    block = next(block for block in region.blocks if block.id == block_id)
    values = {value.id: value for value in graph.values}
    b = _Builder(region.id.value, tuple(location.id for location in graph.locations))
    state_types = _state_types(graph)
    current = tuple(values[identity] for identity in block.arguments
                    if isinstance(values[identity], StateVersionValue))
    predicate_id, branch_id = OperationID(label + ".predicate"), OperationID(label + ".branch")
    condition = DataValue(ValueID(label + ".bool"), region.id,
                           OperationResult(predicate_id, 0), "builtins.bool")
    if input_value is None:
        own = (Use(UseID(label + ".owner"), owner, UseRole.REFERENCE),
               Use(UseID(label + ".state"), current[0].id, UseRole.STATE_CONTENT))
        predicate = Operation(predicate_id, "body state read", (Behavior.CONTROL, Behavior.READ),
            own, (condition.id,), (StateAccess(current[0].location, own[1].id, AccessMode.READ),),
            effects_complete=True)
        subject = BodyStateCondition(own[0].id, (ExistingAccess(predicate_id, 0),), rule)
    else:
        own = (Use(UseID(label + ".input"), input_value, UseRole.REFERENCE),)
        predicate = Operation(predicate_id, "reference is None", (Behavior.COMPUTE,), own,
                              (condition.id,), effects_complete=True)
        subject = ReferenceIsNoneCondition(own[0].id)
    admitted_name, rejected_name = label + ".admitted", label + ".rejected"
    admitted = b.formals(admitted_name, tuple(value_type(values[value]) for value in block.arguments))
    rejected = b.formals(rejected_name, (REFERENCE, RAW, *state_types))
    forward_uses = [Use(UseID(label + ".condition"), condition.id, UseRole.DATA)]
    edge_uses = []
    for number, actuals in enumerate((block.arguments, (owner, raw, *(value.id for value in current)))):
        arguments = []
        for position, value in enumerate(actuals):
            use = Use(UseID(f"{label}.edge.{number}.{position}"), value, _role(values[value]))
            forward_uses.append(use)
            arguments.append(use.id)
        edge_uses.append(tuple(arguments))
    edges = (Successor(BlockID(admitted_name), edge_uses[0]),
             Successor(BlockID(rejected_name), edge_uses[1]))
    if not admit_true:
        edges = tuple(reversed(edges))
    branch = Operation(branch_id, "branch on original read", (Behavior.CONTROL,), tuple(forward_uses),
        effects_complete=True, terminator=Terminator(TerminatorKind.BRANCH, edges,
                                                     condition=forward_uses[0].id))
    substitution = dict(zip(block.arguments, admitted))
    operations = tuple(replace(op, uses=tuple(replace(use, value=substitution.get(use.value, use.value))
                                            for use in op.uses)) for op in graph.operations)
    helper_id = OperationID(label + ".reject")
    actual = (_use(label + ".reject.owner", rejected[0]),
              _use(label + ".reject.raw", rejected[1], protocol=True),
              *(_use(f"{label}.reject.state.{number}", state, state=True)
                for number, state in enumerate(rejected[2:])))
    completions, terminals, selected_owners = [], [], []
    forwards = []
    for number, kind in enumerate((ExitKind.NORMAL, ExitKind.RAISE)):
        landing_name = label + f".reject.{number}"
        landing = b.formals(landing_name, (PACKET, *state_types, REFERENCE))
        forwarded = _use(label + f".reject.forward.{number}", rejected[0])
        forwards.append(forwarded)
        completions.append(CompletionSuccessor(kind, BlockID(landing_name),
            (*(CompletionResult(index) for index in range(1 + len(state_types))), forwarded.id)))
        terminal = b.terminal(landing_name + ".raise", landing[:-1], fail=True)
        b.block(landing_name, landing, (terminal,))
        terminals.append(terminal.id)
        selected_owners.append(landing[-1])
    helper = b.add(helper_id.value, (*actual, *forwards), effects_complete=False,
        invoke_arguments=tuple(use.id for use in actual),
        completions=tuple(CompletionSignature(kind, (PACKET, *state_types))
                          for kind in (ExitKind.NORMAL, ExitKind.RAISE)),
        terminator=Terminator(TerminatorKind.INVOKE, tuple(completions)))
    b.block(rejected_name, rejected, (helper,))
    blocks = tuple(replace(item, operations=(predicate.id, branch.id)) if item.id == block.id else item
                   for item in region.blocks)
    blocks += (Block(BlockID(admitted_name), admitted, block.operations), *b.blocks)
    row = ProtocolOperation(graph.protocol_scopes[0].id, C.RAW_ADMISSION, predicate.id, 0,
        AdmissionPredicate(subject, OperationResult(predicate.id, 0), branch.id), _source_gap())
    rule_for_kind = {RawRequestKind.NEXT: R.CHECK_NEXT, RawRequestKind.SEND: R.CHECK_SEND,
                     RawRequestKind.THROW: R.CHECK_THROW, RawRequestKind.CLOSE: R.CHECK_CLOSE}[request_kind]
    rows = [row, *(ProtocolOperation(row.scope, C.RAW_ADMISSION, helper.id, number,
        RequestProcessing(actual[1].id, (), InvokeLiteralResult(ControlEdgeReference(helper.id, number),
            CompletionResult(0)), tuple(InvokeStateOperand(helper.id, use.id) for use in actual[2:]),
            rule_for_kind), _source_gap()) for number in range(2))]
    scopes = list(graph.protocol_scopes)
    if initial is not None:
        identity = ProtocolScopeID(label + ".initial.scope")
        scopes.append(ProtocolScope(identity, F.CREATED_THROW_V1,
                                   OperationSiteSubject(region.id, helper.id), _source_gap()))
        selected = 1 if initial == "constructor-failure" else 0
        edge = ControlEdgeReference(helper.id, selected)
        clause = C.INITIAL_THROW_CONSTRUCTOR_FAILURE if selected else C.INITIAL_THROW_DELIVERED
        rows.append(ProtocolOperation(identity, clause, helper.id, selected,
            NoEntryOutcome(actual[0].id, actual[1].id, InvokeLiteralResult(edge, CompletionResult(0)),
                tuple(InvokeStateOperand(helper.id, use.id) for use in actual[2:]), edge,
                HostTerminal(terminals[selected])), _source_gap()))
    graph = replace(graph, operations=(*operations, predicate, branch, *b.operations),
        values=(*graph.values, condition, *b.values),
        regions=tuple(replace(item, blocks=blocks) if item.id == region.id else item for item in graph.regions),
        protocol_scopes=tuple(scopes), protocol_operations=(*graph.protocol_operations, *rows),
        driver_lifecycles=graph.driver_lifecycles or (DriverLifecycle(region.id),),
        control_scopes=tuple(replace(scope, blocks=tuple(item.id for item in blocks))
                             if scope.region == region.id else scope for scope in graph.control_scopes))
    return graph, {"predicate": predicate.id, "branch": branch.id, "helper": helper.id,
                   "terminals": tuple(terminals), "owner_formals": tuple(selected_owners),
                   "row": row, "admitted": BlockID(admitted_name),
                   "rejected": BlockID(rejected_name), "condition_use": forward_uses[0].id,
                   "admitted_map": substitution, "initial": initial}


def _caller(graph, *, kind, send_none, stage, throw_operands=1, retry_graph=None):
    """Actual Create/external owner -> raw pack -> INVOKE; retry from real RAISE."""
    interface = graph.driver_interfaces[0]
    region = next(region for region in graph.regions if region.id == interface.region)
    entry = next(block for block in region.blocks if block.id == region.entry)
    values = {value.id: value for value in graph.values}
    domains, state_types = tuple(location.id for location in graph.locations), _state_types(graph)
    b = _Builder("matrix.calls", domains)
    environment = graph.environments[0]
    body = next(region for region in graph.regions if region.id == interface.body)
    body_entry = next(block for block in body.blocks if block.id == body.entry)
    references = tuple(value for value in body_entry.arguments if isinstance(values[value], ReferenceValue))
    extra_packet = any(isinstance(values[value], ProtocolValue) and value_type(values[value]) == PACKET
                       for value in entry.arguments)
    inputs = b.formals("matrix.calls.entry", (REFERENCE, *(REFERENCE for _ in references),
                                             *((PACKET,) if extra_packet else ()), *state_types))
    external_owner, captures = inputs[0], inputs[1:1 + len(references)]
    old_packet = inputs[1 + len(references)] if extra_packet else None
    initial_states = inputs[-len(domains):]
    raw_rows, literals = [], []
    producer = OperationID("matrix.calls.argument")
    argument = b.value("matrix.calls.argument.value", OperationResult(producer, 0), REFERENCE)
    make_argument = b.add(producer.value, results=(argument,), effects_complete=True)
    if kind is not RawRequestKind.THROW:
        literals.append(LiteralEvaluation(OperationResult(producer, 0),
                                         PythonLiteral.from_python(None if send_none else 7, exact=True)))
    prelude = [make_argument]
    owner, states = external_owner, initial_states
    if stage == "created":
        actuals = tuple(_use(f"matrix.calls.create.{index}", value, state=index >= len(captures))
                        for index, value in enumerate((*captures, *states)))
        created = b.formals("matrix.calls.created", (REFERENCE, *state_types))
        failed = b.formals("matrix.calls.create.failed", (PACKET, *state_types))
        create = b.add("matrix.calls.create", actuals, effects_complete=True,
            invoke_arguments=tuple(use.id for use in actuals),
            completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, *state_types)),
                         CompletionSignature(ExitKind.RAISE, (PACKET, *state_types))),
            terminator=Terminator(TerminatorKind.INVOKE, (
                CompletionSuccessor(ExitKind.NORMAL, BlockID("matrix.calls.created"),
                    tuple(CompletionResult(index) for index in range(1 + len(domains)))),
                CompletionSuccessor(ExitKind.RAISE, BlockID("matrix.calls.create.failed"),
                    tuple(CompletionResult(index) for index in range(1 + len(domains)))))))
        function_formal = next(member.reference for member in environment.members
                               if member.role.value == "FUNCTION_OBJECT")
        create_row = ResumableCreate(create.id, body.id,
            actuals[references.index(function_formal)].id,
            tuple(CreationCapture(formal, use.id) for formal, use in zip(references, actuals)),
            NormalResultPort(0), driver_rule())
        b.block("matrix.calls.entry", inputs, (*prelude, create))
        b.block("matrix.calls.create.failed", failed,
                (b.terminal("matrix.calls.create.raise", failed, fail=True),))
        owner, states, current_block, current_args = created[0], created[1:], "matrix.calls.created", created
        prefix = []
    else:
        create_row = None
        current_block, current_args, prefix = "matrix.calls.entry", inputs, prelude

    def pack(name, request_kind):
        operands = tuple(_use(f"{name}.operand.{number}", argument)
                         for number in range(1 if request_kind is RawRequestKind.SEND else
                                             throw_operands if request_kind is RawRequestKind.THROW else 0))
        raw = b.value(name + ".value", OperationResult(OperationID(name), 0), RAW)
        operation = b.add(name, operands, results=(raw,), effects_complete=True)
        raw_rows.append(RawRequestDefinition(raw, request_kind, tuple(use.id for use in operands)))
        return operation, raw

    def invoke(name, callee, call_owner, raw, current_states, *, keep_owner):
        callee_entry = next(block for block in callee.blocks if block.id == callee.entry)
        callee_values = {value.id: value for value in (*graph.values, *(retry_graph["values"] if retry_graph else ()))}
        arguments = []
        by_location = dict(zip(domains, current_states))
        for formal in callee_entry.arguments:
            value = callee_values[formal]
            arguments.append(by_location[value.location] if isinstance(value, StateVersionValue) else
                             old_packet if value_type(value) == PACKET else
                             raw if _role(value) is UseRole.PROTOCOL else
                             call_owner if formal == callee_entry.arguments[0] else argument)
        actuals = tuple(_use(f"{name}.actual.{number}", value,
            state=isinstance(callee_values[formal], StateVersionValue),
            protocol=_role(callee_values[formal]) is UseRole.PROTOCOL)
            for number, (formal, value) in enumerate(zip(callee_entry.arguments, arguments)))
        kinds = {port.kind for port in callee.exits}
        normal = b.formals(name + ".normal", (REFERENCE, *state_types)) if ExitKind.NORMAL in kinds else ()
        failed = b.formals(name + ".raise", (PACKET, *state_types, *((REFERENCE,) if keep_owner else ()))) if ExitKind.RAISE in kinds else ()
        forward = (_use(name + ".owner.forward", call_owner),) if keep_owner else ()
        successors = []
        if normal:
            successors.append(CompletionSuccessor(ExitKind.NORMAL, BlockID(name + ".normal"),
                tuple(CompletionResult(index) for index in range(1 + len(domains)))))
        if failed:
            successors.append(CompletionSuccessor(ExitKind.RAISE, BlockID(name + ".raise"),
                (*(CompletionResult(index) for index in range(1 + len(domains))),
                 *(use.id for use in forward))))
        operation = b.add(name, (*actuals, *forward), callee=callee.id, effects_complete=True,
            invoke_arguments=tuple(use.id for use in actuals),
            completions=tuple(CompletionSignature(port.kind, port.types) for port in callee.exits),
            terminator=Terminator(TerminatorKind.INVOKE, tuple(successors)))
        if normal:
            b.block(name + ".normal", normal, (b.terminal(name + ".return", normal),))
        return operation, failed

    raw_op, raw = pack("matrix.calls.raw", kind)
    call, failed = invoke("matrix.calls.first", region, owner, raw, states,
                          keep_owner=retry_graph is not None or stage == "running")
    b.block(current_block, current_args, (*prefix, raw_op, call))
    retry_call = None
    if retry_graph is not None:
        retry_raw_op, retry_raw = pack("matrix.calls.retry.raw", RawRequestKind.NEXT)
        retry_call, retry_failed = invoke("matrix.calls.retry", retry_graph["region"], failed[-1],
                                         retry_raw, failed[1:1 + len(domains)], keep_owner=False)
        b.block("matrix.calls.first.raise", failed, (retry_raw_op, retry_call))
        b.block("matrix.calls.retry.raise", retry_failed,
                (b.terminal("matrix.calls.retry.raise.exit", retry_failed, fail=True),))
    elif stage == "running":
        continued = b.add("matrix.calls.outer.continue", (_use("matrix.calls.outer.owner", failed[-1]),),
                           effects_complete=True)
        b.block("matrix.calls.first.raise", failed,
                (continued, b.terminal("matrix.calls.outer.return", (failed[-1], *failed[1:1 + len(domains)]))))
    elif failed:
        b.block("matrix.calls.first.raise", failed,
                (b.terminal("matrix.calls.first.raise.exit", failed, fail=True),))
    caller = b.finish("matrix.calls.entry")
    terminal_kinds = {ExitKind.NORMAL if op.terminator.kind is TerminatorKind.RETURN else ExitKind.RAISE
                      for op in b.operations if op.terminator is not None
                      and op.terminator.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE)}
    caller = replace(caller, exits=tuple(port for port in caller.exits if port.kind in terminal_kinds))
    graph = replace(graph, root=caller.id,
        regions=(caller, *(replace(region, parent=caller.id) if region.parent is None else region
                           for region in graph.regions)),
        values=(*graph.values, *b.values), operations=(*graph.operations, *b.operations),
        raw_driver_requests=(*graph.raw_driver_requests, *raw_rows),
        resumable_creates=(*graph.resumable_creates, *((create_row,) if create_row else ())),
        literal_evaluations=(*graph.literal_evaluations, *literals),
        control_scopes=(*graph.control_scopes, ControlScope(ControlScopeID("matrix.calls.function"),
            caller.id, None, ControlScopeKind.FUNCTION, _source("supplied static generator calls"),
            tuple(block.id for block in caller.blocks))))
    return graph, {"call": call.id, "raw": raw, "argument": argument,
                   "owner": owner, "initial_states": tuple(states), "raise_formals": failed,
                   "old_packet_actual": old_packet,
                   "retry_call": None if retry_call is None else retry_call.id,
                   "outer_continuation": OperationID("matrix.calls.outer.continue") if stage == "running" else None}


def _suspended_value_driver(kind):
    """SENT is the exact method argument, or this invocation's actual None."""
    graph, scope = _scope(driver_program(target="value", body_graph=_body()))
    details = {"scope": scope, "drive": graph.body_drives[0].operation}
    if kind is RawRequestKind.NEXT:
        interface, = graph.driver_interfaces
        region = next(region for region in graph.regions if region.id == interface.region)
        entry = next(block for block in region.blocks if block.id == region.entry)
        obsolete = entry.arguments[2]
        identity = OperationID("matrix.suspended.next.none")
        none = ReferenceValue(ValueID("matrix.suspended.next.none.value"), region.id,
                              OperationResult(identity, 0))
        make_none = Operation(identity, "produce current NEXT delivery None", (Behavior.COMPUTE,),
                              results=(none.id,), effects_complete=True)
        arguments = tuple(value for value in entry.arguments if value != obsolete)
        graph = replace(graph,
            values=tuple(replace(value, origin=BlockArgument(entry.id, arguments.index(value.id)))
                         if value.id in arguments else value for value in graph.values
                         if value.id != obsolete) + (none,),
            operations=tuple(replace(op, uses=tuple(replace(use, value=none.id)
                if use.value == obsolete else use for use in op.uses)) for op in graph.operations) + (make_none,),
            regions=tuple(replace(item, blocks=tuple(replace(block, arguments=arguments,
                operations=(identity, *block.operations)) if block.id == entry.id else block
                for block in item.blocks)) if item.id == region.id else item for item in graph.regions),
            literal_evaluations=(*graph.literal_evaluations, LiteralEvaluation(OperationResult(identity, 0),
                PythonLiteral.from_python(None, exact=True))))
        details["delivery_none"] = none.id
    return with_publications(graph), details


def _later_admission_program(*, stage, kind, send_none, throw_propagates):
    if stage == "closed":
        graph, details = closed_request_program(kind=kind)
        if kind in (RawRequestKind.SEND, RawRequestKind.THROW):
            helper = _op(graph, details["processing"])
            operand = _use("matrix.closed.operand", details["old_return"])
            helper = replace(helper, uses=(*helper.uses, operand),
                             invoke_arguments=(*helper.invoke_arguments, operand.id))
            rows = tuple(replace(row, contract=replace(row.contract,
                operand_bindings=(RequestOperandBinding(0, operand.id),))) for row in graph.protocol_operations)
            if kind is RawRequestKind.THROW:
                rows += tuple(replace(row, clause=C.REQUEST_PROCESSING,
                    contract=replace(row.contract, rule=R.NORMALIZE_THROW_CLASS)) for row in rows)
            graph = replace(graph, operations=tuple(helper if op.id == helper.id else op
                for op in graph.operations), protocol_operations=rows)
            details["operand_use"] = operand.id
        if kind is RawRequestKind.CLOSE:
            graph = replace(graph, literal_evaluations=(*graph.literal_evaluations,
                LiteralEvaluation(InvokeLiteralResult(ControlEdgeReference(details["processing"], 0),
                    CompletionResult(0)), PythonLiteral.from_python(None, exact=True))))
    elif kind in (RawRequestKind.NEXT, RawRequestKind.SEND):
        graph, details = _suspended_value_driver(kind)
    elif kind is RawRequestKind.THROW:
        graph, details = _driver("packet", body_graph=_body_with_environment() if throw_propagates else None)
    else:
        graph, details = _first_driver(_environment(_branching_body()), release=False)
        interface, = graph.driver_interfaces
        region = next(region for region in graph.regions if region.id == interface.region)
        entry = next(block for block in region.blocks if block.id == region.entry)
        obsolete = entry.arguments[2]
        assert not any(use.value == obsolete for op in graph.operations for use in op.uses)
        arguments = tuple(value for value in entry.arguments if value != obsolete)
        graph = replace(graph, values=tuple(replace(value,
            origin=BlockArgument(entry.id, arguments.index(value.id))) if value.id in arguments else value
            for value in graph.values if value.id != obsolete),
            regions=tuple(replace(item, blocks=tuple(replace(block, arguments=arguments)
                if block.id == entry.id else block for block in item.blocks))
                if item.id == region.id else item for item in graph.regions))
    interface, = graph.driver_interfaces
    region = next(region for region in graph.regions if region.id == interface.region)
    graph, guard = _guard(graph, block_id=region.entry, owner=interface.receiver,
        raw=interface.scheduler_request, label="matrix." + stage,
        rule=BodyStatePredicateRule.IS_CLOSED if stage == "closed" else BodyStatePredicateRule.IS_SUSPENDED,
        request_kind=kind)
    graph, caller = _caller(graph, kind=kind, send_none=send_none, stage=stage)
    return graph, {**details, **caller, "stage": stage, "kind": kind, "guards": (guard,),
                   "send_none": send_none, "throw_propagates": throw_propagates}


def generator_admission_program(*, stage="created", kind=RawRequestKind.NEXT,
                                send_none=True, constructor_failure=False, retry=False,
                                throw_operands=1, throw_propagates=False):
    """All sixteen cells; phase predicates remain conditional source declarations."""
    if stage not in ("created", "running", "suspended", "closed") or type(kind) is not RawRequestKind:
        raise ValueError("stage/kind outside this finite fixture")
    if stage in ("suspended", "closed"):
        return _later_admission_program(stage=stage, kind=kind, send_none=send_none,
                                        throw_propagates=throw_propagates)
    if retry and not (stage == "created" and kind is RawRequestKind.SEND and not send_none):
        raise ValueError("retry models the rejected initial non-None send")
    target = "packet" if kind is RawRequestKind.THROW else (
        "value" if stage == "running" and kind is RawRequestKind.SEND else "start")
    if kind is RawRequestKind.CLOSE:
        graph, details = _first_driver(_environment(_branching_body()), release=False)
        # Its genuine CLOSE branch already normalizes GeneratorExit. Remove
        # only the old, now unused prepacked entry payload port.
        interface, = graph.driver_interfaces
        region = next(region for region in graph.regions if region.id == interface.region)
        entry = next(block for block in region.blocks if block.id == region.entry)
        obsolete = entry.arguments[2]
        if any(use.value == obsolete for op in graph.operations for use in op.uses):
            raise AssertionError("obsolete close delivery port is unexpectedly consumed")
        arguments = tuple(value for value in entry.arguments if value != obsolete)
        graph = replace(graph, values=tuple(replace(value, origin=BlockArgument(entry.id, arguments.index(value.id)))
            if value.id in arguments else value for value in graph.values if value.id != obsolete),
            regions=tuple(replace(item, blocks=tuple(replace(block, arguments=arguments)
                if block.id == entry.id else block for block in item.blocks))
                if item.id == region.id else item for item in graph.regions))
    else:
        graph, details = _driver(target)
    interface, = graph.driver_interfaces
    guards = []
    region = next(region for region in graph.regions if region.id == interface.region)
    entry = next(block for block in region.blocks if block.id == region.entry)
    retry_part = None
    if stage == "created" and kind is RawRequestKind.CLOSE:
        graph = _created_close(graph)
        test, = graph.created_close_tests
        scope = ProtocolScope(ProtocolScopeID("matrix.created.close"), F.CREATED_CLOSE_V1,
                              OperationSiteSubject(interface.region, test.operation), _source_gap())
        graph = replace(graph, protocol_scopes=(*graph.protocol_scopes, scope))
        terminal = _op(graph, OperationID("driver.no_body.return"))
        none_id = OperationID("matrix.created.close.none")
        none = ReferenceValue(ValueID("matrix.created.close.none.value"), interface.region,
                              OperationResult(none_id, 0))
        make_none = Operation(none_id, "produce None", (Behavior.COMPUTE,), results=(none.id,), effects_complete=True)
        terminal = replace(terminal, uses=tuple(replace(use, value=none.id)
            if use.id == terminal.terminator.values[0] else use for use in terminal.uses))
        graph = replace(graph, values=(*graph.values, none),
            operations=tuple(terminal if op.id == terminal.id else op for op in graph.operations) + (make_none,),
            literal_evaluations=(*graph.literal_evaluations, LiteralEvaluation(OperationResult(none_id, 0),
                PythonLiteral.from_python(None, exact=True))),
            regions=tuple(replace(region, blocks=tuple(replace(block,
                operations=(*block.operations[:-1], make_none.id, terminal.id))
                if terminal.id in block.operations else block for block in region.blocks))
                if region.id == interface.region else region for region in graph.regions))
        details = {"created_close_test": test.operation,
                   "finish": graph.no_body_finishes[0].operation, "none": none.id}
    elif stage == "created":
        if kind is RawRequestKind.SEND:
            graph, argument = _ensure_extra_reference(graph)
            graph, none_guard = _guard(graph, block_id=entry.id, owner=interface.receiver,
                raw=interface.scheduler_request, label="matrix.none", input_value=argument,
                request_kind=kind)
            guards.append(none_guard)
        graph, guard = _guard(graph, block_id=entry.id, owner=interface.receiver,
            raw=interface.scheduler_request, label="matrix.created", rule=BodyStatePredicateRule.IS_CREATED,
            admit_true=kind is not RawRequestKind.THROW, request_kind=kind,
            initial=("constructor-failure" if constructor_failure else "delivered")
                    if kind is RawRequestKind.THROW else None)
        guards.append(guard)
        if retry:
            second, _ = _driver("start")
            next_interface, = second.driver_interfaces
            next_region = next(region for region in second.regions if region.id == next_interface.region)
            second, _ = _guard(second, block_id=next_region.entry, owner=next_interface.receiver,
                raw=next_interface.scheduler_request, label="matrix.retry.created",
                rule=BodyStatePredicateRule.IS_CREATED)
            # Only the next static driver is needed; discard its independent
            # caller and retain this graph's one canonical shared body.
            retry_part, _ = _driver_part(second, "matrix.retry.driver")
            extra_names = ("driver_interfaces", "final_body_gates", "body_drives", "driver_lifecycles",
                           "body_outcome_commits", "terminal_frame_releases", "protocol_scopes",
                           "protocol_operations", "literal_evaluations")
            graph = replace(graph, regions=(*graph.regions, retry_part["region"]),
                operations=(*graph.operations, *retry_part["operations"]),
                values=(*graph.values, *retry_part["values"]),
                control_scopes=(*graph.control_scopes, *retry_part["control_scopes"]),
                **{name: (*getattr(graph, name), *retry_part[name]) for name in extra_names})
    else:
        if target == "start":
            candidates = ((entry.id, interface.receiver, interface.scheduler_request),)
        else:
            helper = _op(graph, details["processing"])
            normal, failed = helper.terminator.successors
            normal_block = next(block for block in region.blocks if block.id == normal.block)
            candidates = ((normal.block, normal_block.arguments[0], normal_block.arguments[1]),
                          (failed.block, interface.receiver, interface.scheduler_request))
        for number, (block, owner, raw) in enumerate(candidates):
            graph, guard = _guard(graph, block_id=block, owner=owner, raw=raw,
                label=f"matrix.running.{number}", rule=BodyStatePredicateRule.IS_RUNNING,
                admit_true=False, request_kind=kind)
            guards.append(guard)
    graph, caller = _caller(graph, kind=kind, send_none=send_none, stage=stage,
                            throw_operands=throw_operands, retry_graph=retry_part)
    return graph, {**details, **caller, "stage": stage, "kind": kind,
                   "guards": tuple(guards), "constructor_failure": constructor_failure,
                   "send_none": send_none}


def invalid_request_binding_program(*, operand_count=4):
    """A real only-RAISE call-binding failure, before any valid RAW exists.

    The native/source correspondence to throw(0 or 4 operands) remains an
    explicit fixture interpretation, not a newly inferred protocol fact.
    The handler continues with actual partial poststate, never an old snapshot.
    """
    if operand_count not in (0, 4):
        raise ValueError("the finite invalid THROW arities are zero and four")
    location = LocationID("matrix.invalid.world")
    state = ValueType(ValueKind.STATE, location=location)
    binder = _Builder("matrix.invalid.binder", (location,))
    entry = binder.formals("matrix.invalid.binder.entry", (REFERENCE, *(REFERENCE for _ in range(operand_count)), state))
    failure = binder.formals("matrix.invalid.binder.failure", (PACKET, state))
    actuals = tuple(_use(f"matrix.invalid.bind.actual.{number}", value, state=number == len(entry) - 1)
                    for number, value in enumerate(entry))
    bind = binder.add("matrix.invalid.bind", actuals, effects_complete=False,
        invoke_arguments=tuple(use.id for use in actuals),
        completions=(CompletionSignature(ExitKind.RAISE, (PACKET, state)),),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.RAISE, BlockID("matrix.invalid.binder.failure"),
                                (CompletionResult(0), CompletionResult(1))),)))
    binder.block("matrix.invalid.binder.entry", entry, (bind,))
    binder.block("matrix.invalid.binder.failure", failure,
                 (binder.terminal("matrix.invalid.bind.raise", failure, fail=True),))
    callee = binder.finish("matrix.invalid.binder.entry")
    callee = replace(callee, exits=tuple(port for port in callee.exits if port.kind is ExitKind.RAISE))
    caller = _Builder("matrix.invalid.caller", (location,))
    incoming = caller.formals("matrix.invalid.caller.entry", (REFERENCE, *(REFERENCE for _ in range(operand_count)), state))
    caught = caller.formals("matrix.invalid.caller.handler", (PACKET, state, REFERENCE))
    call_actuals = tuple(_use(f"matrix.invalid.call.actual.{number}", value,
                             state=number == len(incoming) - 1)
                         for number, value in enumerate(incoming))
    owner = _use("matrix.invalid.call.owner.forward", incoming[0])
    call = caller.add("matrix.invalid.call", (*call_actuals, owner), effects_complete=True,
        callee=callee.id, invoke_arguments=tuple(use.id for use in call_actuals),
        completions=(CompletionSignature(ExitKind.RAISE, (PACKET, state)),),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.RAISE, BlockID("matrix.invalid.caller.handler"),
                                (CompletionResult(0), CompletionResult(1), owner.id)),)))
    caller.block("matrix.invalid.caller.entry", incoming, (call,))
    returned = caller.terminal("matrix.invalid.handler.return", (caught[2], caught[1]))
    caller.block("matrix.invalid.caller.handler", caught, (returned,))
    root = caller.finish("matrix.invalid.caller.entry")
    root = replace(root, exits=tuple(port for port in root.exits if port.kind is ExitKind.NORMAL))
    callee = replace(callee, parent=root.id)
    scopes = tuple(ControlScope(ControlScopeID(region.id.value + ".function"), region.id,
        None, ControlScopeKind.FUNCTION, _source("invalid binding before valid raw request"),
        tuple(block.id for block in region.blocks)) for region in (root, callee))
    graph = ProgramGraph(root.id, (root, callee), (*caller.operations, *binder.operations),
        (*caller.values, *binder.values), (StateLocation(location, "call binding effects"),),
        control_scopes=scopes)
    return graph, {"call": call.id, "binder": bind.id, "handler": caught,
                   "return": returned.id, "initial_state": incoming[-1],
                   "operand_count": operand_count}


__all__ = ["generator_admission_program", "invalid_request_binding_program"]
