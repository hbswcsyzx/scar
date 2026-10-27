"""Explicit Start/Resume paths for persistent bodies, never runtime recovery.

One Program retains all original ports. Dynamic owner denotations are scoped
declarations with unresolved evidence, not inferred from shared code or IDs.
"""
from dataclasses import replace

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.common import Unresolved
from scar.ir.execution.content import ObjectIdentity, ObjectRef, ValueDenotation
from scar.ir.execution.coordinates import ExecutionSegment, HostThreadInstance, ResumeIngress
from scar.ir.execution.ids import CallActivationID, DenotationID, ExecutionSegmentID, HostThreadInstanceID
from scar.ir.execution.resumables import BodyActivationOrigin, BodyDriveExecution
from scar.ir.execution.snapshot import external_artifact
from scar.ir.program.control import ProtocolValueKind as P
from scar.ir.program.ids import BlockID, OperationID, ValueID
from scar.ir.program.model import (
    Behavior, BlockArgument, CompletionResult, CompletionSignature, CompletionSuccessor,
    DataValue, ExitKind, LiteralOrigin, OperationResult, ProtocolValue, ReferenceValue,
    Successor, Terminator, TerminatorKind, UseRole,
)
from scar.ir.v2.evidence import EvidenceEndpoint, EvidenceGraph, EvidenceNodeKind
from scar.ir.v2.ids import ObjectID
from tests.fixtures.execution_call_graphs import _model
from tests.fixtures.program_driver_graphs import PACKET, RAW, _Builder, _use, driver_program
from tests.fixtures.program_generator_close_retry_graphs import _driver_part


def _program(resume, extra_domain):
    program = driver_program(create=True, extra_domain=extra_domain)
    second, maps = _driver_part(driver_program(target=resume, extra_domain=extra_domain), 'resume.driver')
    root = next(region for region in program.regions if region.id == program.root)
    normal = next(block for block in root.blocks if block.id == BlockID('factory.normal'))
    first = next(block for block in root.blocks if block.id == BlockID('factory.entry'))
    values = {value.id: value for value in program.values}
    state_types = tuple(port for port in root.exits[0].types[1:])
    b = _Builder(root.id.value, tuple(port.location for port in state_types))
    payload = first.arguments[0]
    extra = ()
    if resume == 'packet':
        packet = ProtocolValue(ValueID('factory.resume.packet'), root.id,
            BlockArgument(first.id, len(first.arguments)), P.EXCEPTION_PACKET)
        payload = packet.id
        extra = (packet,)
        root = replace(root, blocks=tuple(replace(block, arguments=(*block.arguments, payload))
            if block.id == first.id else block for block in root.blocks))
    raw_operand = _use('factory.resume.raw.operand', first.arguments[0])
    raw = b.value('factory.resume.raw.value', OperationResult(OperationID('factory.resume.raw'), 0), RAW)
    raw_op = b.add('factory.resume.raw', (raw_operand,), results=(raw,), effects_complete=True)
    from scar.ir.program.drivers import RawRequestDefinition, RawRequestKind
    request = RawRequestDefinition(raw, RawRequestKind.THROW if resume == 'packet' else RawRequestKind.SEND,
                                   (raw_operand.id,))
    actual_values = (ValueID('factory.created.arg.0'), raw, payload, *normal.arguments[1:])
    uses = tuple(_use(f'factory.resume.call.{index}', value, state=index >= 3,
                     protocol=index == 1 or resume == 'packet' and index == 2)
                 for index, value in enumerate(actual_values))
    landings, edges, terminals = [], [], []
    for number, port in enumerate(second['region'].exits):
        name = 'factory.resume.' + port.kind.value.lower()
        args = b.formals(name, port.types)
        terminal = b.terminal(name + '.exit', args, fail=port.kind is ExitKind.RAISE)
        b.block(name, args, (terminal,))
        edges.append(CompletionSuccessor(port.kind, BlockID(name),
                                        tuple(CompletionResult(index) for index in range(len(port.types)))))
        landings.append(BlockID(name))
        terminals.append(terminal.id)
    call = b.add('factory.resume.call', uses, callee=second['region'].id, effects_complete=True,
        invoke_arguments=tuple(use.id for use in uses),
        completions=tuple(CompletionSignature(port.kind, port.types) for port in second['region'].exits),
        terminator=Terminator(TerminatorKind.INVOKE, tuple(edges)))
    old_return, = normal.operations
    root = replace(root, blocks=tuple(replace(block, operations=(raw_op.id, call.id))
        if block.id == normal.id else block for block in root.blocks) + tuple(b.blocks))
    tables = ('driver_interfaces', 'final_body_gates', 'body_drives')
    program = replace(program,
        regions=tuple(root if region.id == root.id else region for region in program.regions)
                + (replace(second['region'], parent=root.id),),
        operations=tuple(op for op in program.operations if op.id != old_return)
                   + tuple(b.operations) + second['operations'],
        values=(*program.values, *extra, *b.values, *second['values']),
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in root.blocks))
            if scope.region == root.id else scope for scope in program.control_scopes) + second['control_scopes'],
        raw_driver_requests=(*program.raw_driver_requests, request),
        **{name: (*getattr(program, name), *second[name]) for name in tables})
    return program, second, maps


def resumable_execution(*, resume='value', instances=1, switched_thread=False, known_creation=True, extra_domain=False):
    """Return (ProgramGraph, ExecutionModel, details) with original dynamic ports.

    Switched-thread capture deliberately stops the factory after its first
    synchronous call. The later driver is externally entered on thread2;
    inventing a synchronous cross-thread CallActivation would be false.
    """
    if resume not in ('value', 'packet') or type(instances) is not int or instances < 1:
        raise ValueError('finite fixture expects value/packet and positive exact instances')
    program, second, maps = _program(resume, extra_domain)
    paths = []
    case = 1 if resume == 'packet' else 0
    second_entry = second['region'].entry
    second_ingress = maps[BlockID][BlockID('driver.ingress')]
    second_outcome = maps[BlockID][BlockID('driver.outcome')]
    for number in range(instances):
        prefix = f'instance.{number}'
        factory = ((BlockID('factory.entry'), 0), (BlockID('factory.created'), 0),
            (BlockID('factory.normal'), case), (BlockID('factory.resume.raise' if case else 'factory.resume.normal'), None))
        paths.extend(((program.root, factory, prefix + '.factory'),
            (program.driver_interfaces[0].region,
             ((BlockID('driver.entry'), 0), (BlockID('driver.ingress'), 0), (BlockID('driver.outcome'), None)), prefix + '.start'),
            (second['region'].id, ((second_entry, 0), (second_ingress, 0), (second_outcome, None)), prefix + '.resume'),
            (program.resumable_bodies[0].region,
             ((BlockID('resume.entry'), case), (BlockID('resume.packet' if case else 'resume.value'), None)), prefix + '.body')))
    model, scopes, source = _model(program, tuple(paths))
    point = model.activations[0].entry
    gap = Unresolved('supplied declaration has no runtime/source identity witness', point)
    evidence = EvidenceGraph()
    for number in range(instances):
        for suffix in ('body', 'wrong', *(f'capture.{index}' for index in range(6))):
            evidence.register_external(EvidenceEndpoint(EvidenceNodeKind.OBJECT, ObjectID(f'{number}.{suffix}')))
    artifact = external_artifact(evidence, 'memory:resumable-object-declarations')
    links, origins, calls, denotations, details, segments = [], [], [], [], [], list(model.segments)
    all_values = {(value.origin, value.value): value for value in model.values}
    for number in range(instances):
        factory, start, resumed, body = scopes[number * 4:number * 4 + 4]
        activation, visits, operations = body
        suspension, outcome = operations[OperationID('resume.suspend')], operations[OperationID('resume.raise' if case else 'resume.return')]
        original = next(segment for segment in model.segments if segment.activation == activation)
        new = ExecutionSegment(ExecutionSegmentID(f'instance.{number}.body.resumed'), activation,
            original.host_thread, ResumeIngress(suspension, case, point))
        segments.append(new)
        model = replace(model, visits=tuple(replace(visit, segment=new.id) if visit.id == visits[1] else visit
                                           for visit in model.visits))
        drives = (start[2][OperationID('driver.drive')], resumed[2][maps[OperationID][OperationID('driver.drive')]])
        links.extend((BodyDriveExecution(drives[0], activation, visits[0], suspension, source),
                      BodyDriveExecution(drives[1], activation, visits[1], outcome, source)))
        creation = factory[2][OperationID('factory.create')]
        origins.append(BodyActivationOrigin(activation, creation if known_creation else gap, source))
        calls.extend((CallActivation(CallActivationID(f'{number}.start'), factory[2][OperationID('factory.call')],
            start[0], start[1][0], start[2][OperationID('driver.outcome.exit')], source),))
        if not switched_thread:
            calls.append(CallActivation(CallActivationID(f'{number}.resume'), factory[2][OperationID('factory.resume.call')],
                resumed[0], resumed[1][0], resumed[2][maps[OperationID][OperationID('driver.outcome.exit')]], source))
        body_entry = next(block for region in program.regions for block in region.blocks if block.id == BlockID('resume.entry'))
        references = [formal for formal in body_entry.arguments
                      if type(next(value for value in program.values if value.id == formal)) is ReferenceValue]
        assignments = {}
        def denote(origin, static, suffix):
            value = all_values.get((origin, static))
            if value is not None:
                assignments[value.id] = suffix
        denote(factory[1][1], ValueID('factory.created.arg.0'), 'body')
        for occurrence in (start, resumed):
            for visit in occurrence[1][:2]:
                original_block = next(row for row in model.visits if row.id == visit).block
                block = next(row for region in program.regions for row in region.blocks if row.id == original_block)
                denote(visit, block.arguments[0], 'body')
        for index, formal in enumerate(references):
            denote(factory[1][0], ValueID(f'factory.entry.arg.{index}'), f'capture.{index}')
            denote(visits[0], formal, f'capture.{index}')
        for visit, static in ((visits[1], ValueID('resume.packet.x' if case else 'resume.value.x')),
                              (factory[1][2], ValueID('factory.normal.arg.0'))):
            denote(visit, static, 'capture.0')
        for occurrence in (start, resumed):
            if occurrence is start or not case:
                target = next(row for row in model.visits if row.id == occurrence[1][2]).block
                block = next(row for region in program.regions for row in region.blocks if row.id == target)
                denote(occurrence[1][2], block.arguments[0], 'capture.0')
        if not case:
            for visit in resumed[1][:2]:
                block = next(row for region in program.regions for row in region.blocks
                    if row.id == next(row for row in model.visits if row.id == visit).block)
                denote(visit, block.arguments[2], 'capture.0')
            denote(visits[1], ValueID('resume.value.sent'), 'capture.0')
            denote(factory[1][3], ValueID('factory.resume.normal.arg.0'), 'capture.0')
        for identity, suffix in assignments.items():
            denotations.append(ValueDenotation(DenotationID(identity.value), identity,
                ObjectIdentity(ObjectRef(artifact, ObjectID(f'{number}.{suffix}'))), gap, source))
        details.append({'activation': activation, 'entries': visits, 'suspension': suspension, 'outcome': outcome,
            'drives': drives, 'creation': creation, 'factory': factory, 'start': start, 'resume': resumed,
            'segments': (original.id, new.id), 'owner_object': ObjectID(f'{number}.body'), 'wrong_object': ObjectID(f'{number}.wrong')})
    if switched_thread:
        switched = HostThreadInstanceID('resumable.thread.2')
        model = replace(model, threads=(*model.threads, HostThreadInstance(switched, model.processes[0].id, 12, source)))
        truncated_visits = {scope[1][3] for scope in scopes[::4]}
        truncating = {scope[1][2] for scope in scopes[::4]}
        removed = {row.id for row in model.operations if row.visit in truncated_visits | truncating}
        model = replace(model,
            visits=tuple(row for row in model.visits if row.id not in truncated_visits),
            operations=tuple(row for row in model.operations if row.id not in removed),
            uses=tuple(row for row in model.uses if row.operation not in removed),
            values=tuple(row for row in model.values if row.origin not in removed | truncated_visits),
            transfers=tuple(row for row in model.transfers if row.operation not in removed and row.target not in truncated_visits))
        changed_segments = {*(item['segments'][1] for item in details),
            *(row.id for row in segments if row.activation in {scope[0] for scope in scopes[2::4]})}
        segments = [replace(row, host_thread=switched) if row.id in changed_segments else row for row in segments]
        remaining = {row.id for row in model.values}
        denotations = [row for row in denotations if row.value in remaining]
    model = replace(model, segments=tuple(segments), call_activations=tuple(calls),
        denotations=tuple(denotations), body_drive_executions=tuple(links), body_activation_origins=tuple(origins))
    return program, model, {'instances': tuple(details), 'source': source, 'point': point, 'gap': gap,
        'object_artifact': artifact, 'evidence_graphs': {artifact.sha256: evidence}, 'resume': resume,
        'maps': maps, 'switched_thread': switched_thread, 'extra_domain': extra_domain}


def empty_frontier_execution():
    """A finite capture prefix of a body with no finite static outcome."""
    from tests.fixtures.program_resumption_graphs import _Body, _use as body_use
    b = _Body('empty.body')
    world = b.argument('empty.world', 'empty.entry', 0, b.world)
    context = b.argument('empty.context', 'empty.entry', 1, b.context)
    frame = b.initial('empty.initial')
    caller, attached = b.switch('empty.attach', frame, context, attach=True)
    args = (b.argument('empty.loop.caller', 'empty.loop', 0, P.DRIVE_CALLER_CONTEXT),
            b.argument('empty.loop.world', 'empty.loop', 1, b.world),
            b.argument('empty.loop.context', 'empty.loop', 2, b.context))
    before = tuple(body_use(f'empty.enter.{index}', value,
        UseRole.PROTOCOL if index == 0 else UseRole.STATE_CONTENT)
        for index, value in enumerate((caller, world, attached)))
    b.add('empty.enter', (Behavior.CONTROL,), before, terminator=Terminator(TerminatorKind.JUMP,
        (Successor(BlockID('empty.loop'), tuple(use.id for use in before)),)))
    condition = DataValue(ValueID('empty.condition'), b.region, LiteralOrigin(True), 'builtins.bool')
    b.values.append(condition)
    uses = [body_use('empty.condition.use', condition.id, UseRole.DATA)]
    edges = []
    for ordinal in range(2):
        current = tuple(body_use(f'empty.again.{ordinal}.{index}', value,
            UseRole.PROTOCOL if index == 0 else UseRole.STATE_CONTENT) for index, value in enumerate(args))
        uses.extend(current)
        edges.append(Successor(BlockID('empty.loop'), tuple(use.id for use in current)))
    b.add('empty.choose', (Behavior.CONTROL,), uses,
        terminator=Terminator(TerminatorKind.BRANCH, tuple(edges), condition=uses[0].id))
    b.block('empty.entry', (world, context), ('empty.initial', 'empty.attach', 'empty.enter'))
    b.block('empty.loop', args, ('empty.choose',))
    program = driver_program(body_graph=b.finish('empty.entry', ()))
    model, scopes, source = _model(program, (
        (program.root, ((BlockID('driver.entry'), 0), (BlockID('driver.ingress'), None)), 'empty.driver'),
        (program.resumable_bodies[0].region,
         ((BlockID('empty.entry'), 0), (BlockID('empty.loop'), 0), (BlockID('empty.loop'), None)), 'empty.body')))
    driver, body = scopes
    drive = driver[2][OperationID('driver.drive')]
    gap = Unresolved('no captured completion; finite prefix does not prove runtime divergence', model.activations[0].entry)
    model = replace(model,
        body_drive_executions=(BodyDriveExecution(drive, body[0], body[1][0], gap, source),),
        body_activation_origins=(BodyActivationOrigin(body[0], gap, source),))
    return program, model, {'drive': drive, 'activation': body[0], 'entry': body[1][0], 'gap': gap}


__all__ = ['resumable_execution', 'empty_frontier_execution']
