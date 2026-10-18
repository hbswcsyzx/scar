"""Declared D1 driver graphs; no source, instance or runtime admission evidence."""
from dataclasses import replace

from scar.ir.program.control import ControlScope, ControlScopeKind, ProtocolValueKind as P, ProtocolValueType
from scar.ir.program.drivers import (
    AsyncRequestCreate, BodyDrive, BodyDriveResult, BodyDriveSuccessor, BodyDriveTerminator,
    BodyResume, BodyResumeInput, BodyStart, BodyStateInput, CreationCapture,
    DriverInterface, DriverReceiverKind, DriverRule, DriverRuleProfile, FinalBodyGate,
    NormalResultPort, RawRequestDefinition, RawRequestKind, RequestAssociationRead,
    ResumableCreate,
)
from scar.ir.program.environments import EnvironmentInterface, EnvironmentMember, EnvironmentRole, FunctionEntryLayout
from scar.ir.program.functions import FormalPort
from scar.ir.program.ids import BlockID, ControlScopeID, EnvironmentInterfaceID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, CompletionSignature, CompletionSuccessor,
    ExitKind, ExitPort, Operation, OperationResult, ProgramGraph, ProtocolValue,
    ReferenceValue, Region, StateLocation, StateVersionValue, Terminator, TerminatorKind,
    Use, UseRole, ValueKind, ValueType, value_type,
)
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.v2.ids import OperationDefinitionID, ValueSlotID
from tests.fixtures.program_control_graphs import _source
from tests.fixtures.program_resumption_graphs import resumption_program


REFERENCE = ValueType(ValueKind.REFERENCE)
PACKET = ProtocolValueType(P.EXCEPTION_PACKET)
RAW = ProtocolValueType(P.RAW_DRIVER_REQUEST)


def driver_rule():
    return DriverRule(DriverRuleProfile.PYTHON_RESUMPTION_V1,
        ProviderFactReference(ProviderArtifact("fixture://driver-rule", "a" * 64, 1, "driver-contract-v1"), "D1 declaration only"))


def _use(name, value, *, state=False, protocol=False):
    return Use(UseID(name), value, UseRole.STATE_CONTENT if state else UseRole.PROTOCOL if protocol else UseRole.REFERENCE)


class _Builder:
    def __init__(self, name, domains):
        self.region = RegionID(name)
        self.domains = tuple(domains)
        self.values, self.operations, self.blocks = [], [], []

    def value(self, name, origin, type_):
        if type_ == REFERENCE:
            value = ReferenceValue(ValueID(name), self.region, origin)
        elif isinstance(type_, ValueType) and type_.kind is ValueKind.STATE:
            value = StateVersionValue(ValueID(name), self.region, origin, type_.location)
        else:
            value = ProtocolValue(ValueID(name), self.region, origin, type_.protocol)
        self.values.append(value)
        return value.id

    def formals(self, block, types):
        return tuple(self.value(f"{block}.arg.{index}", BlockArgument(BlockID(block), index), type_)
                     for index, type_ in enumerate(types))

    def add(self, name, uses=(), **kwargs):
        op = Operation(OperationID(name), name, (Behavior.CONTROL,), tuple(uses), **kwargs)
        self.operations.append(op)
        return op

    def block(self, name, arguments, operations):
        self.blocks.append(Block(BlockID(name), tuple(arguments), tuple(operation.id for operation in operations)))

    def finish(self, entry, *, parent=None):
        states = tuple(ValueType(ValueKind.STATE, location=location) for location in self.domains)
        return Region(self.region, "declared driver fixture", BlockID(entry), tuple(self.blocks), (
            ExitPort("normal", ExitKind.NORMAL, (REFERENCE, *states)),
            ExitPort("failure", ExitKind.RAISE, (PACKET, *states)),
        ), parent=parent)

    def terminal(self, name, arguments, *, fail=False):
        kinds = {value.id: value for value in self.values}
        uses = tuple(_use(f"{name}.use.{index}", value, state=index > 0,
                          protocol=isinstance(kinds.get(value), ProtocolValue))
                     for index, value in enumerate(arguments))
        return self.add(name, uses, terminator=Terminator(
            TerminatorKind.RAISE if fail else TerminatorKind.RETURN,
            exit="failure" if fail else "normal", values=tuple(use.id for use in uses)))


def _body_with_environment():
    graph = resumption_program()
    body = graph.regions[0]
    entry = next(block for block in body.blocks if block.id == body.entry)
    roles = tuple(EnvironmentRole)[:5]
    references = tuple(ReferenceValue(ValueID(f"resume.environment.{role.value}"), body.id,
                       BlockArgument(entry.id, len(entry.arguments) + index))
                       for index, role in enumerate(roles))
    environment = EnvironmentInterface(EnvironmentInterfaceID("resume.environment"), body.id,
        OperationDefinitionID("resume.definition"), tuple(EnvironmentMember(role, ref.id)
                                                        for role, ref in zip(roles, references)))
    layout = FunctionEntryLayout(environment.id, (FormalPort(ValueSlotID("resume.parameter.x"), ValueID("resume.x")),))
    body = replace(body, blocks=tuple(replace(block, arguments=(*block.arguments, *(ref.id for ref in references)))
                                     if block.id == entry.id else block for block in body.blocks))
    return replace(graph, regions=(body,), values=(*graph.values, *references),
                   environments=(environment,), function_entries=(layout,))


def driver_program(*, target="start", create=False, extra_domain=False, async_request=False, body_graph=None):
    """External instance or bound Create drives Start/value/packet with exact state."""
    graph = _body_with_environment() if body_graph is None else body_graph
    body = graph.regions[0]
    body_domains = tuple(location.id for location in graph.locations)
    domains = (*body_domains, *((LocationID("driver.extra"),) if extra_domain else ()))
    states = tuple(ValueType(ValueKind.STATE, location=location) for location in domains)
    b = _Builder("driver", domains)
    payload_type = None if target == "start" else PACKET if target == "packet" else REFERENCE
    # BODY receiver is B; ASYNC_REQUEST has distinct fixed R plus an external B boundary.
    roles = (REFERENCE, RAW, *((REFERENCE,) if async_request else ()),
             *((payload_type,) if payload_type is not None else ()))
    args = b.formals("driver.entry", (*roles, *states))
    instance, scheduler = args[:2]
    session = args[2] if async_request else None
    payload_index = 3 if async_request else 2
    payload = None if payload_type is None else args[payload_index]
    role_values = (instance, scheduler, *((session,) if session is not None else ()),
                   *((payload,) if payload is not None else ()))
    state_values = args[len(roles):]
    gate_inputs = tuple(_use(f"driver.gate.input.{index}", value, state=index >= len(role_values),
                             protocol=index < len(roles) and isinstance(roles[index], ProtocolValueType))
                        for index, value in enumerate((*role_values, *state_values)))
    forwards = tuple(_use(f"driver.gate.forward.{index}", value, protocol=isinstance(roles[index], ProtocolValueType))
                     for index, value in enumerate(role_values))
    landing = b.formals("driver.ingress", (*roles, *states))
    reject = b.formals("driver.reject", (PACKET, *states))
    gate = b.add("driver.gate", (*gate_inputs, *forwards), effects_complete=True,
        invoke_arguments=tuple(use.id for use in gate_inputs),
        completions=(CompletionSignature(ExitKind.NORMAL, states), CompletionSignature(ExitKind.RAISE, (PACKET, *states))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID("driver.ingress"),
                (*(use.id for use in forwards), *(CompletionResult(index) for index in range(len(states))))),
            CompletionSuccessor(ExitKind.RAISE, BlockID("driver.reject"),
                tuple(CompletionResult(index) for index in range(len(states) + 1))),
        )))
    drive_roles = tuple(_use(f"driver.drive.role.{index}", value, protocol=isinstance(roles[index], ProtocolValueType))
                        for index, value in enumerate(landing[:len(roles)]))
    drive_states = tuple(_use(f"driver.drive.state.{index}", value, state=True)
                         for index, value in enumerate(landing[len(roles):len(roles) + len(body_domains)]))
    from scar.ir.program.driver_flow import body_drive_target, body_outcome_uses
    from scar.ir.program.resumption_flow import first_body_outcome_operations
    if target == "start":
        target_record = BodyStart(body.id)
        resume_inputs = ()
    else:
        from scar.ir.program.resumption import SuspendTerminator
        suspend = next(op for op in graph.operations if isinstance(op.terminator, SuspendTerminator))
        case = 1 if target == "packet" else 0
        target_record = BodyResume(suspend.id, case)
        slots = suspend.terminator.successors[case].inputs
        dynamic_slot = next(index for index, slot in enumerate(slots) if slot.location is None)
        resume_inputs = (BodyResumeInput(dynamic_slot, drive_roles[payload_index].id),)
    drive = BodyDrive(OperationID("driver.drive"), drive_roles[0].id, drive_roles[1].id,
        drive_roles[2].id if async_request else None, target_record,
        tuple(BodyStateInput(location, use.id) for location, use in zip(body_domains, drive_states)), resume_inputs)
    _, start, _ = body_drive_target(graph, drive)
    source_ids = first_body_outcome_operations(body, {op.id: op for op in graph.operations}, start)
    successors, extra_uses, outcome_blocks = [], [], []
    values_by_id = {value.id: value for value in graph.values}
    for number, source in enumerate(source_ids):
        source_op = next(op for op in graph.operations if op.id == source)
        source_uses = {use.id: use for use in source_op.uses}
        result_types = tuple(value_type(values_by_id[source_uses[use].value]) for use in body_outcome_uses(source_op))
        block_name = "driver.outcome" if len(source_ids) == 1 else f"driver.outcome.{number}"
        outcome = b.formals(block_name, (*result_types, *states[len(body_domains):]))
        extras = tuple(_use(f"driver.drive.extra.{number}.{index}", value, state=True)
                       for index, value in enumerate(landing[len(roles) + len(body_domains):]))
        extra_uses.extend(extras)
        successors.append(BodyDriveSuccessor(source, BlockID(block_name),
            (*(BodyDriveResult(index) for index in range(len(result_types))), *(use.id for use in extras))))
        outcome_blocks.append((block_name, outcome, source_op.terminator.kind is TerminatorKind.RAISE))
    drive_op = b.add("driver.drive", (*drive_roles, *drive_states, *extra_uses), effects_complete=True,
        terminator=BodyDriveTerminator(tuple(successors)))
    b.block("driver.entry", args, (gate,))
    b.block("driver.ingress", landing, (drive_op,))
    reject_terminal = b.terminal("driver.reject.raise", reject, fail=True)
    b.block("driver.reject", reject, (reject_terminal,))
    for block_name, outcome, fail in outcome_blocks:
        b.block(block_name, outcome, (b.terminal(block_name + ".exit", outcome, fail=fail),))
    driver = b.finish("driver.entry")
    if target == "packet":
        normal = b.terminal("driver.reject.normal", (instance, *reject[1:]))
        b.operations.remove(reject_terminal)
        b.blocks = [replace(block, operations=(normal.id,)) if block.id == BlockID("driver.reject") else block
                    for block in b.blocks]
        driver = b.finish("driver.entry")
    if not source_ids:
        driver = replace(driver, exits=tuple(port for port in driver.exits if port.kind is ExitKind.RAISE))
    interface = DriverInterface(driver.id, body.id,
        DriverReceiverKind.ASYNC_REQUEST if async_request else DriverReceiverKind.BODY,
        session if async_request else instance, scheduler, (body_domains[0],), driver_rule())
    gate_row = FinalBodyGate(gate.id, drive_op.id, 0, 1, 2 if async_request else None,
                            () if payload is None else (payload_index,))
    result = replace(graph, root=driver.id, regions=(driver, replace(body, parent=driver.id)),
        operations=(*graph.operations, *b.operations), values=(*graph.values, *b.values),
        locations=(*graph.locations, *((StateLocation(domains[-1], "driver-only contents"),) if extra_domain else ())),
        control_scopes=(*graph.control_scopes, ControlScope(ControlScopeID("driver.function"), driver.id, None,
            ControlScopeKind.FUNCTION, _source("driver"), tuple(block.id for block in b.blocks))),
        driver_interfaces=(interface,), final_body_gates=(gate_row,), body_drives=(drive,))
    return _with_creator(result, target=target, async_request=async_request) if create else result


def _with_creator(graph, *, target="start", async_request=False, drive=True):
    """A separate creator Region passes its actual NORMAL handle to driver entry."""
    if async_request:
        raise ValueError("creator composition currently exposes body receivers")
    body = next(region for region in graph.regions if region.id == RegionID("resume"))
    body_values = {value.id: value for value in graph.values}
    body_entry = next(block for block in body.blocks if block.id == body.entry)
    references = [formal for formal in body_entry.arguments if isinstance(body_values[formal], ReferenceValue)]
    driver = next((region for region in graph.regions if region.id == RegionID("driver")), None)
    domains = tuple(value.location for value in graph.values if driver is not None
                    and value.region == driver.id and isinstance(value, StateVersionValue)
                    and isinstance(value.origin, BlockArgument) and value.origin.block == driver.entry)
    if not domains:
        domains = tuple(location.id for location in graph.locations)
    states = tuple(ValueType(ValueKind.STATE, location=location) for location in domains)
    b = _Builder("factory", domains)
    entry = b.formals("factory.entry", (*(REFERENCE for _ in references), *states,
                                          *((PACKET,) if target == "packet" else ())))
    state_values = entry[len(references):len(references) + len(states)]
    raw_kind = RawRequestKind.NEXT if target == "start" else RawRequestKind.THROW if target == "packet" else RawRequestKind.SEND
    raw_operand = () if target == "start" else (_use("factory.raw.operand", entry[0]),)
    raw = b.value("factory.raw", OperationResult(OperationID("factory.raw.pack"), 0), RAW)
    raw_op = Operation(OperationID("factory.raw.pack"), "raw request pack", (Behavior.COMPUTE,), raw_operand, (raw,), effects_complete=True)
    b.operations.append(raw_op)
    create_uses = tuple(_use(f"factory.create.input.{index}", value, state=index >= len(references))
                        for index, value in enumerate((*entry[:len(references)], *state_values)))
    created = b.formals("factory.created", (REFERENCE, *states))
    failed = b.formals("factory.failed", (PACKET, *states))
    create_op = b.add("factory.create", create_uses, effects_complete=True,
        invoke_arguments=tuple(use.id for use in create_uses),
        completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, *states)), CompletionSignature(ExitKind.RAISE, (PACKET, *states))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID("factory.created"), tuple(CompletionResult(i) for i in range(len(states) + 1))),
            CompletionSuccessor(ExitKind.RAISE, BlockID("factory.failed"), tuple(CompletionResult(i) for i in range(len(states) + 1))),
        )))
    captures = tuple(CreationCapture(formal, use.id) for formal, use in zip(references, create_uses))
    function_formal = next(item.reference for item in graph.environments[0].members if item.role is EnvironmentRole.FUNCTION_OBJECT)
    function_use = next(item.source for item in captures if item.formal == function_formal)
    create_row = ResumableCreate(create_op.id, body.id, function_use, captures, NormalResultPort(0), driver_rule())
    b.block("factory.entry", entry, (raw_op, create_op))
    b.block("factory.failed", failed, (b.terminal("factory.failed.raise", failed, fail=True),))
    if drive:
        actual_values = (created[0], raw, *((entry[-1] if target == "packet" else entry[0],) if target != "start" else ()), *created[1:])
        uses = tuple(_use(f"factory.call.input.{i}", value, state=i >= len(actual_values) - len(states),
                               protocol=value == raw or target == "packet" and value == entry[-1])
                     for i, value in enumerate(actual_values))
        normal = b.formals("factory.normal", (REFERENCE, *states))
        failure = b.formals("factory.call.failure", (PACKET, *states))
        call = b.add("factory.call", uses, effects_complete=True, callee=driver.id,
            invoke_arguments=tuple(use.id for use in uses),
            completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, *states)), CompletionSignature(ExitKind.RAISE, (PACKET, *states))),
            terminator=Terminator(TerminatorKind.INVOKE, (
                CompletionSuccessor(ExitKind.NORMAL, BlockID("factory.normal"), tuple(CompletionResult(i) for i in range(len(states) + 1))),
                CompletionSuccessor(ExitKind.RAISE, BlockID("factory.call.failure"), tuple(CompletionResult(i) for i in range(len(states) + 1))),
            )))
        b.block("factory.created", created, (call,))
        b.block("factory.normal", normal, (b.terminal("factory.normal.return", normal),))
        b.block("factory.call.failure", failure, (b.terminal("factory.call.failure.raise", failure, fail=True),))
    else:
        b.block("factory.created", created, (b.terminal("factory.created.return", created),))
    factory = b.finish("factory.entry")
    return replace(graph, root=factory.id,
        regions=(factory, *(replace(region, parent=factory.id) if region.parent is None else region for region in graph.regions)),
        operations=(*graph.operations, *b.operations), values=(*graph.values, *b.values),
        control_scopes=(*graph.control_scopes, ControlScope(ControlScopeID("factory.function"), factory.id, None,
            ControlScopeKind.FUNCTION, _source("factory"), tuple(block.id for block in b.blocks))),
        resumable_creates=(*graph.resumable_creates, create_row),
        raw_driver_requests=(*graph.raw_driver_requests, RawRequestDefinition(raw, raw_kind, tuple(use.id for use in raw_operand))))


def create_only_program():
    return _with_creator(_body_with_environment(), drive=False)


def raw_only_program(kind=RawRequestKind.NEXT):
    """Construct a raw protocol and return an independent Reference, no driver."""
    b = _Builder("raw", ())
    args = b.formals("raw.entry", (REFERENCE,))
    count = 0 if kind in (RawRequestKind.NEXT, RawRequestKind.CLOSE) else 1
    uses = tuple(_use(f"raw.pack.input.{index}", args[0]) for index in range(count))
    value = b.value("raw.request", OperationResult(OperationID("raw.pack"), 0), RAW)
    pack = Operation(OperationID("raw.pack"), "raw protocol", (Behavior.COMPUTE,), uses, (value,), effects_complete=True)
    b.operations.append(pack)
    ret = b.terminal("raw.return", args)
    b.block("raw.entry", args, (pack, ret))
    region = Region(b.region, "raw-only boundary", BlockID("raw.entry"), tuple(b.blocks), (ExitPort("normal", ExitKind.NORMAL, (REFERENCE,)),))
    return ProgramGraph(region.id, (region,), tuple(b.operations), tuple(b.values),
        raw_driver_requests=(RawRequestDefinition(value, kind, tuple(use.id for use in uses)),))


def async_request_program():
    """Create a body handle, create a request, and read its actual association."""
    graph = create_only_program()
    factory = next(region for region in graph.regions if region.id == graph.root)
    created = next(block for block in factory.blocks if block.id == BlockID("factory.created"))
    values = {value.id: value for value in graph.values}
    domains = tuple(values[formal].location for formal in created.arguments[1:])
    states = tuple(ValueType(ValueKind.STATE, location=location) for location in domains)
    b = _Builder("factory", domains)
    request = b.formals("factory.request", (REFERENCE, *states))
    request_fail = b.formals("factory.request.failure", (PACKET, *states))
    create_values = (created.arguments[0], ValueID("factory.raw"), *created.arguments[1:])
    create_uses = tuple(_use(f"factory.request.create.input.{i}", value, state=i > 1, protocol=i == 1)
                        for i, value in enumerate(create_values))
    request_op = b.add("factory.request.create", create_uses, effects_complete=True,
        invoke_arguments=tuple(use.id for use in create_uses),
        completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, *states)), CompletionSignature(ExitKind.RAISE, (PACKET, *states))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID("factory.request"), tuple(CompletionResult(i) for i in range(len(states) + 1))),
            CompletionSuccessor(ExitKind.RAISE, BlockID("factory.request.failure"), tuple(CompletionResult(i) for i in range(len(states) + 1))),
        )))
    association = b.formals("factory.association", (REFERENCE, RAW, *states))
    association_fail = b.formals("factory.association.failure", (PACKET, *states))
    read_uses = tuple(_use(f"factory.association.input.{i}", value, state=i > 0)
                      for i, value in enumerate(request))
    read_op = b.add("factory.association.read", read_uses, effects_complete=True,
        invoke_arguments=tuple(use.id for use in read_uses),
        completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, RAW, *states)), CompletionSignature(ExitKind.RAISE, (PACKET, *states))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID("factory.association"), tuple(CompletionResult(i) for i in range(len(states) + 2))),
            CompletionSuccessor(ExitKind.RAISE, BlockID("factory.association.failure"), tuple(CompletionResult(i) for i in range(len(states) + 1))),
        )))
    b.block("factory.request", request, (read_op,))
    b.block("factory.request.failure", request_fail, (b.terminal("factory.request.failure.raise", request_fail, fail=True),))
    b.block("factory.association", association, (b.terminal("factory.association.return", (association[0], *association[2:])),))
    b.block("factory.association.failure", association_fail, (b.terminal("factory.association.failure.raise", association_fail, fail=True),))
    old_return = created.operations[0]
    factory = replace(factory, blocks=tuple(replace(block, operations=(request_op.id,)) if block.id == created.id else block
                                           for block in factory.blocks) + tuple(b.blocks))
    return replace(graph, regions=tuple(factory if region.id == factory.id else region for region in graph.regions),
        operations=tuple(operation for operation in graph.operations if operation.id != old_return) + tuple(b.operations),
        values=(*graph.values, *b.values),
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in factory.blocks)) if scope.region == factory.id else scope
                             for scope in graph.control_scopes),
        async_request_creates=(AsyncRequestCreate(request_op.id, create_uses[0].id, create_uses[1].id, NormalResultPort(0), driver_rule()),),
        request_association_reads=(RequestAssociationRead(read_op.id, read_uses[0].id, NormalResultPort(0), NormalResultPort(1), driver_rule()),))


def multiple_creates_program():
    """Two real Create sites have private completions and merge at one driver call."""
    from scar.ir.program.model import DataValue, LiteralOrigin, Successor
    graph = driver_program(create=True)
    factory = next(region for region in graph.regions if region.id == graph.root)
    old_entry = next(block for block in factory.blocks if block.id == factory.entry)
    old_created = next(block for block in factory.blocks if block.id == BlockID("factory.created"))
    op_map = {operation.id: operation for operation in graph.operations}
    old_create = op_map[OperationID("factory.create")]
    old_call = op_map[OperationID("factory.call")]
    value_map = {value.id: value for value in graph.values}
    domains = tuple(value_map[formal].location for formal in old_created.arguments[1:])
    states = tuple(ValueType(ValueKind.STATE, location=location) for location in domains)
    b = _Builder("factory", domains)
    first_states = b.formals("factory.site.1", states)
    second_states = b.formals("factory.site.2", states)
    second_created = b.formals("factory.created.2", (REFERENCE, *states))
    second_failure = b.formals("factory.failed.2", (PACKET, *states))
    joined = b.formals("factory.join", (REFERENCE, *states))
    state_positions = {location: index for index, location in enumerate(domains)}
    first_uses, second_uses, second_ids = [], [], {}
    for index, use in enumerate(old_create.uses):
        value = value_map[use.value]
        first_value = first_states[state_positions[value.location]] if isinstance(value, StateVersionValue) else use.value
        second_value = second_states[state_positions[value.location]] if isinstance(value, StateVersionValue) else use.value
        first_uses.append(replace(use, value=first_value))
        new_use = replace(use, id=UseID(f"factory.create.2.input.{index}"), value=second_value)
        second_uses.append(new_use)
        second_ids[use.id] = new_use.id
    first_create = replace(old_create, uses=tuple(first_uses))
    second_create = replace(old_create, id=OperationID("factory.create.2"), uses=tuple(second_uses),
        invoke_arguments=tuple(second_ids[uid] for uid in old_create.invoke_arguments),
        terminator=replace(old_create.terminator, successors=(
            replace(old_create.terminator.successors[0], block=BlockID("factory.created.2")),
            replace(old_create.terminator.successors[1], block=BlockID("factory.failed.2")),
        )))
    b.operations.append(second_create)
    condition = DataValue(ValueID("factory.branch.condition"), factory.id, LiteralOrigin(True), "builtins.bool")
    branch_uses = [Use(UseID("factory.branch.condition.use"), condition.id, UseRole.DATA)]
    successors = []
    for number, target in enumerate(("factory.site.1", "factory.site.2")):
        forwarded = tuple(_use(f"factory.branch.{number}.{i}", value.id, state=True)
                          for i, value in enumerate(value_map[formal] for formal in old_entry.arguments
                                                    if isinstance(value_map[formal], StateVersionValue)))
        branch_uses.extend(forwarded)
        successors.append(Successor(BlockID(target), tuple(use.id for use in forwarded)))
    branch = b.add("factory.branch", branch_uses, terminator=Terminator(
        TerminatorKind.BRANCH, tuple(successors), condition=branch_uses[0].id))
    def join_jump(name, arguments):
        uses = tuple(_use(f"{name}.input.{i}", value, state=i > 0) for i, value in enumerate(arguments))
        return b.add(name, uses, terminator=Terminator(TerminatorKind.JUMP,
            (Successor(BlockID("factory.join"), tuple(use.id for use in uses)),)))
    first_jump = join_jump("factory.created.join", old_created.arguments)
    second_jump = join_jump("factory.created.2.join", second_created)
    substitution = dict(zip(old_created.arguments, joined))
    call = replace(old_call, uses=tuple(replace(use, value=substitution.get(use.value, use.value)) for use in old_call.uses))
    b.block("factory.site.1", first_states, (first_create,))
    b.block("factory.site.2", second_states, (second_create,))
    b.block("factory.created.2", second_created, (second_jump,))
    b.block("factory.failed.2", second_failure, (b.terminal("factory.failed.2.raise", second_failure, fail=True),))
    b.block("factory.join", joined, (call,))
    factory = replace(factory, blocks=tuple(
        replace(block, operations=(OperationID("factory.raw.pack"), branch.id)) if block.id == old_entry.id else
        replace(block, operations=(first_jump.id,)) if block.id == old_created.id else block
        for block in factory.blocks) + tuple(b.blocks))
    row = graph.resumable_creates[0]
    second_row = replace(row, operation=second_create.id, function_object=second_ids[row.function_object],
        captures=tuple(replace(capture, source=second_ids[capture.source]) for capture in row.captures))
    return replace(graph, regions=tuple(factory if region.id == factory.id else region for region in graph.regions),
        operations=tuple(first_create if operation.id == first_create.id else call if operation.id == call.id else operation
                         for operation in graph.operations) + tuple(b.operations),
        values=(*graph.values, condition, *b.values),
        resumable_creates=(*graph.resumable_creates, second_row),
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in factory.blocks)) if scope.region == factory.id else scope
                             for scope in graph.control_scopes))
