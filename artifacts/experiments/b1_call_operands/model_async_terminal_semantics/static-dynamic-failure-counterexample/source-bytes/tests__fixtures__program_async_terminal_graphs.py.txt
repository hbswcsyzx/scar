"""Supplied frame-local async exception conversion, not native execution.

The intrinsic has an independently versioned logical interface. Only its
exception Reference is a native argument; packets and abstract states remain
core-only ports. A real body invocation finishes before driver propagation.
"""
from dataclasses import replace

from scar.ir.program.control import (ControlScope, ControlScopeKind,
    ExceptionPacketDefinition, ProtocolValueKind as P)
from scar.ir.program.drivers import (AsyncRequestCreate, CreationCapture,
    NormalResultPort, RawRequestDefinition, RawRequestKind, ResumableCreate)
from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.exception_matches import (BuiltinExceptionCategory,
    ExceptionMatcher, FixedBuiltinHandler)
from scar.ir.program.ids import (BlockID, ControlScopeID, NativeBoundaryID,
    OperationID, ProtocolScopeID, ValueID)
from scar.ir.program.lifecycle import SessionPost
from scar.ir.program.model import (AccessMode, Behavior, BlockArgument,
    CompletionResult, CompletionSignature, CompletionSuccessor, DataValue,
    ExitKind, ExitPort, Footprint, FootprintKind, InvokeLiteralResult, LiteralOrigin,
    Operation, OperationResult, ReferenceValue, StateAccess, StateVersionValue,
    Successor, Terminator, TerminatorKind, UseRole, ValueKind, ValueType)
from scar.ir.program.native import (CoreInputPort, CoreOutputPort, EntryPortRef,
    ExitPortRef, NativeBoundary, NativeInputSlot, NativeOutputSlot)
from scar.ir.program.providers import (ProviderArtifact, ProviderElement,
    ProviderElementKind, ProviderBinding, ProviderFactReference, ProviderRegion,
    ProviderRegionRelation)
from scar.ir.program.protocol_connections import (AsyncSessionOutcome,
    RequestAssociation, RequestStateCondition, RequestStateRule)
from scar.ir.program.protocols import (AdmissionPredicate, BodyStatePredicateRule,
    DriverSubject, OwnedUse, ProtocolClause, ProtocolOperation, ProtocolProfile,
    ProtocolScope, RequestProcessing, RequestProcessingRule)
from scar.ir.program.resumption import ResumableKind, SuspendTerminator, SuspensionFlavor
from scar.ir.program.state_addresses import (AddressCoverage, AddressEffect,
    ExistingAccess, InvokeStateOperand, ObjectField, ReferenceOwner, StateAddressRefinement)
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_async_connections import _association
from tests.fixtures.program_async_pipeline_graphs import _driver_component, _selected_path
from tests.fixtures.program_control_graphs import _source
from tests.fixtures.program_driver_graphs import PACKET, RAW, REFERENCE, _Builder, _use, driver_program, driver_rule
from tests.fixtures.program_generator_admission_graphs import _environment, _guard
from tests.fixtures.program_protocol_graphs import _source_gap
from tests.fixtures.program_provider_graphs import _envelope
from tests.fixtures.program_publication_graphs import with_publications
from tests.fixtures.program_resumption_graphs import _Body, _use as _body_use, resumption_program
from tests.fixtures.program_session_release_graphs import _Tail


def _op(graph, identity):
    return next(row for row in graph.operations if row.id == identity)


def _intrinsic(world, context, route):
    b = _Builder('async.terminal.intrinsic', (world, context))
    states = tuple(ValueType(ValueKind.STATE, location=location) for location in b.domains)
    types = (PACKET, REFERENCE, PACKET, *states)
    entry = b.formals('terminal.intrinsic.entry', types)
    matched = b.formals('terminal.intrinsic.matched', types)
    second = b.formals('terminal.intrinsic.second', types)
    ordinary = b.formals('terminal.intrinsic.ordinary', types)
    artifact = ProviderArtifact(
        'https://raw.githubusercontent.com/python/cpython/v3.14.7/Python/intrinsics.c',
        '9c218e09ee44ef416440ee3e473d3f0686a1752ab68222d49ebcbce99bd1264f',
        9254, 'cpython-source-v3.14.7')
    fact = lambda name: ProviderFactReference(artifact, 'INTRINSIC_STOPITERATION_ERROR/' + name)
    matchers, branches = [], []
    def choose(name, arguments, category, yes, no):
        actual = _use(name + '.packet', arguments[0], protocol=True)
        dependencies = tuple(_use(name + f'.state.{i}', state, state=True)
                             for i, state in enumerate(arguments[-2:]))
        boolean = DataValue(ValueID(name + '.bool'), b.region,
                            OperationResult(OperationID(name), 0), 'builtins.bool')
        b.values.append(boolean)
        operation = Operation(OperationID(name), 'original fixed matcher',
            (Behavior.COMPUTE, Behavior.READ), (actual, *dependencies), (boolean.id,),
            tuple(StateAccess(location, use.id, AccessMode.READ) for location, use in zip(b.domains, dependencies)),
            effects_complete=True)
        b.operations.append(operation)
        condition = _body_use(name + '.condition', boolean.id, UseRole.DATA)
        uses, edges = [condition], []
        for number, destination in enumerate((yes, no)):
            copies = tuple(_use(name + f'.forward.{number}.{i}', value,
                state=i >= 3, protocol=i in (0, 2)) for i, value in enumerate(arguments))
            uses.extend(copies)
            edges.append(Successor(BlockID(destination), tuple(use.id for use in copies)))
        branch = b.add(name + '.branch', uses, effects_complete=True,
            terminator=Terminator(TerminatorKind.BRANCH, tuple(edges), condition=condition.id))
        matchers.append(ExceptionMatcher(operation.id, actual.id,
            BlockArgument(BlockID('terminal.intrinsic.entry'), 0),
            FixedBuiltinHandler(category, fact('matcher/' + category.value)), boolean.origin,
            None, branch.id, tuple(ExistingAccess(operation.id, i) for i in range(2))))
        branches.append(branch)
        return operation, branch
    first_ops = choose('terminal.match.stop', entry, BuiltinExceptionCategory.STOP_ITERATION,
                       'terminal.intrinsic.matched', 'terminal.intrinsic.second')
    second_ops = choose('terminal.match.stop_async', second, BuiltinExceptionCategory.STOP_ASYNC_ITERATION,
                        'terminal.intrinsic.matched', 'terminal.intrinsic.ordinary')
    b.block('terminal.intrinsic.entry', entry, first_ops)
    b.block('terminal.intrinsic.second', second, second_ops)
    normal = b.formals('terminal.constructor.normal', (REFERENCE, *states, REFERENCE, PACKET))
    raised = b.formals('terminal.constructor.raised', (PACKET, *states))
    inputs = (_use('terminal.constructor.original', matched[1]),
              _use('terminal.constructor.raw_packet', matched[0], protocol=True),
              *(_use(f'terminal.constructor.state.{i}', value, state=True)
                for i, value in enumerate(matched[-2:])))
    forwards = (_use('terminal.constructor.forward.exception', matched[1]),
                _use('terminal.constructor.forward.packet', matched[0], protocol=True))
    constructor = b.add('terminal.constructor', (*inputs, *forwards), effects_complete=False,
        invoke_arguments=tuple(use.id for use in inputs),
        completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, *states)),
                     CompletionSignature(ExitKind.RAISE, (PACKET, *states))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID('terminal.constructor.normal'),
                (CompletionResult(0), CompletionResult(1), CompletionResult(2),
                 forwards[0].id, forwards[1].id)),
            CompletionSuccessor(ExitKind.RAISE, BlockID('terminal.constructor.raised'),
                tuple(CompletionResult(i) for i in range(3))))))
    b.block('terminal.intrinsic.matched', matched, (constructor,))
    chaining, refinements = [], []
    current_world = normal[1]
    for number, field in enumerate(('__cause__', '__context__')):
        name = 'terminal.chain.' + str(number)
        owner = _use(name + '.new_exception', normal[0])
        original = _use(name + '.original_exception', normal[3])
        before = _use(name + '.world', current_world, state=True)
        after = b.value(name + '.after', OperationResult(OperationID(name), 0), states[0])
        operation = Operation(OperationID(name), 'original exception attribute write',
            (Behavior.WRITE, Behavior.READ), (owner, original, before), (after,),
            (StateAccess(world, before.id, AccessMode.READ_WRITE, after,
                         Footprint(FootprintKind.WHOLE)),), effects_complete=True)
        b.operations.append(operation)
        chaining.append(operation)
        refinements.append(StateAddressRefinement(ExistingAccess(operation.id, 0),
            (AddressEffect(ReferenceOwner(owner.id), (ObjectField(field),), AccessMode.READ_WRITE),),
            AddressCoverage.DECLARED_COMPLETE, fact('chaining/' + field)))
        current_world = after
    none = ReferenceValue(ValueID('terminal.traceback.none'), b.region, LiteralOrigin(None), targets=())
    b.values.append(none)
    packet = b.value('terminal.runtime.packet', OperationResult(OperationID('terminal.runtime.pack'), 0), PACKET)
    components = (_use('terminal.runtime.exception', normal[0]), _use('terminal.runtime.traceback', none.id))
    pack = b.add('terminal.runtime.pack', components, results=(packet,), effects_complete=True)
    packet_definition = ExceptionPacketDefinition(packet, components[0].id, components[1].id)
    def returned(name, exception, payload, world_, context_):
        uses = (_use(name + '.exception', exception), _use(name + '.packet', payload, protocol=True),
                _use(name + '.world', world_, state=True), _use(name + '.context', context_, state=True))
        return b.add(name, uses, effects_complete=True,
            terminator=Terminator(TerminatorKind.RETURN, exit='normal', values=tuple(use.id for use in uses)))
    normal_terminal = returned('terminal.intrinsic.converted', normal[0], packet, current_world, normal[2])
    ordinary_terminal = returned('terminal.intrinsic.unchanged', ordinary[1], ordinary[0], *ordinary[-2:])
    raise_terminal = b.terminal('terminal.intrinsic.failed', raised, fail=True)
    b.block('terminal.constructor.normal', normal, (*chaining, pack, normal_terminal))
    b.block('terminal.constructor.raised', raised, (raise_terminal,))
    b.block('terminal.intrinsic.ordinary', ordinary, (ordinary_terminal,))
    region = replace(b.finish('terminal.intrinsic.entry'), exits=(
        ExitPort('normal', ExitKind.NORMAL, (REFERENCE, PACKET, *states)),
        ExitPort('failure', ExitKind.RAISE, (PACKET, *states))))
    envelope = _envelope('async-terminal-intrinsic', artifact=artifact)
    boundary = NativeBoundary(NativeBoundaryID('async.terminal.intrinsic.boundary'), envelope.id,
        region.id, fact('logical-signature'), None, None,
        (NativeInputSlot(0, 'original exception reference', fact('exception-input'), EntryPortRef(region.id, entry[1])),),
        (NativeOutputSlot(0, 'returned exception reference', fact('exception-output'), ExitPortRef(region.id, 'normal', 0)),),
        tuple(CoreInputPort(EntryPortRef(region.id, value), 'core-only packet/state, not a native ABI argument')
              for i, value in enumerate(entry) if i != 1),
        tuple(CoreOutputPort(ExitPortRef(region.id, exit_.name, i), 'core packet/current-state/error projection')
              for exit_ in region.exits for i in range(len(exit_.types))
              if not (exit_.kind is ExitKind.NORMAL and i == 0)))
    choices = {branches[0].id: 1 if route in ('stop-async-iteration', 'ordinary') else 0,
               branches[1].id: int(route == 'ordinary'), constructor.id: int(route == 'constructor-raise')}
    completion = (raise_terminal if route == 'constructor-raise' else
                  ordinary_terminal if route == 'ordinary' else normal_terminal)
    return b, region, {'region': region, 'entry_formals': entry, 'matchers': tuple(matchers),
        'branches': tuple(branches), 'constructor': constructor,
        'constructor_results': tuple(InvokeLiteralResult(ControlEdgeReference(constructor.id, i), CompletionResult(0)) for i in range(2)),
        'chaining': tuple(chaining), 'refinements': tuple(refinements),
        'original_exception': entry[1], 'original_packet': entry[0], 'old_packet': entry[2],
        'packet_definition': packet_definition, 'normal_terminal': normal_terminal,
        'raise_terminal': raise_terminal, 'ordinary_terminal': ordinary_terminal,
        'completion': completion, 'choices': choices, 'native_boundary': boundary,
        'artifact': artifact, 'provider': envelope}


def _body(route):
    base = resumption_program()
    b = _Body('resume')
    block = next(row for row in base.regions[0].blocks if row.id == BlockID('resume.value'))
    removed = set(block.operations[1:])
    b.values = [value for value in base.values if not (type(value.origin) is OperationResult
                                                     and value.origin.operation in removed)]
    b.operations = [operation for operation in base.operations if operation.id not in removed]
    b.blocks = list(base.regions[0].blocks)
    b.initials, b.attaches = list(base.frame_context_initials), list(base.frame_context_attaches)
    b.detaches = [row for row in base.frame_context_detaches if row.operation not in removed]
    builder, intrinsic_region, intrinsic = _intrinsic(b.world, b.context, route)
    none = ReferenceValue(ValueID('terminal.body.traceback'), b.region, LiteralOrigin(None), targets=())
    b.values.append(none)
    packets = []
    packs = []
    for label, exception in (('source', block.arguments[3]), ('old', block.arguments[1])):
        identity = 'terminal.body.' + label + '.pack'
        value = b.result(identity + '.value', identity, 0, P.EXCEPTION_PACKET)
        uses = (_body_use(identity + '.exception', exception, UseRole.REFERENCE),
                _body_use(identity + '.traceback', none.id, UseRole.REFERENCE))
        packs.append(b.add(identity, (Behavior.CONTROL,), uses, (value,), effects_complete=True))
        packets.append(ExceptionPacketDefinition(value, uses[0].id, uses[1].id))
    attach = _op(base, block.operations[0])
    caller = next(row.caller for row in b.attaches if row.operation == attach.id)
    inputs = (_body_use('terminal.body.call.packet', packets[0].value),
        _body_use('terminal.body.call.exception', block.arguments[3], UseRole.REFERENCE),
        _body_use('terminal.body.call.old_packet', packets[1].value),
        _body_use('terminal.body.call.world', block.arguments[0], UseRole.STATE_CONTENT),
        _body_use('terminal.body.call.context', attach.accesses[0].after, UseRole.STATE_CONTENT))
    signatures, edges, forwards, terminals = [], [], [], []
    for number, exit_ in enumerate(intrinsic_region.exits):
        name = 'terminal.body.post.' + str(number)
        kinds = ('reference', P.EXCEPTION_PACKET, b.world, b.context) if number == 0 else (P.EXCEPTION_PACKET, b.world, b.context)
        formals = tuple(b.argument(name + '.arg.' + str(i), name, i, kind) for i, kind in enumerate(kinds))
        caller_formal = b.argument(name + '.caller', name, len(kinds), P.DRIVE_CALLER_CONTEXT)
        forwarded = _body_use(name + '.forward.caller', caller)
        forwards.append(forwarded)
        signatures.append(CompletionSignature(exit_.kind, exit_.types))
        edges.append(CompletionSuccessor(exit_.kind, BlockID(name),
            (*(CompletionResult(i) for i in range(len(kinds))), forwarded.id)))
        _, after = b.switch(name + '.detach', caller_formal, formals[-1], attach=False)
        uses = (_body_use(name + '.packet', formals[1] if number == 0 else formals[0]),
                _body_use(name + '.world', formals[-2], UseRole.STATE_CONTENT),
                _body_use(name + '.context', after, UseRole.STATE_CONTENT))
        terminal = b.add(name + '.raise', (Behavior.CONTROL,), uses, effects_complete=True,
            terminator=Terminator(TerminatorKind.RAISE, exit='failure', values=tuple(use.id for use in uses)))
        b.block(name, (*formals, caller_formal), (name + '.detach', terminal.id.value))
        terminals.append(terminal)
    call = b.add('terminal.body.call', (Behavior.CONTROL,), (*inputs, *forwards),
        callee=intrinsic_region.id, effects_complete=False,
        invoke_arguments=tuple(use.id for use in inputs), completions=tuple(signatures),
        terminator=Terminator(TerminatorKind.INVOKE, tuple(edges)))
    b.blocks = [replace(row, operations=(attach.id, *(op.id for op in packs), call.id))
                if row.id == block.id else row for row in b.blocks]
    graph = _environment(b.finish('resume.entry', tuple(exit_ for exit_ in base.regions[0].exits if exit_.kind is ExitKind.RAISE)))
    graph = replace(graph, regions=(graph.regions[0], replace(intrinsic_region, parent=graph.root)),
        values=(*graph.values, *builder.values),
        exception_packets=(*packets, intrinsic['packet_definition']),
        exception_matches=intrinsic['matchers'], state_address_refinements=intrinsic['refinements'],
        control_scopes=(*graph.control_scopes, ControlScope(ControlScopeID('terminal.intrinsic.scope'),
            intrinsic_region.id, None, ControlScopeKind.FUNCTION, _source('conditional intrinsic expansion'),
            tuple(row.id for row in intrinsic_region.blocks))),
        resumable_bodies=tuple(replace(row, kind=ResumableKind.ASYNC_GENERATOR) for row in graph.resumable_bodies),
        operations=tuple(replace(operation, terminator=replace(operation.terminator, flavor=SuspensionFlavor.AWAIT))
            if type(operation.terminator) is SuspendTerminator else operation
            for operation in (*graph.operations, *builder.operations)),
        provider_envelopes=(intrinsic['provider'],),
        provider_regions=(ProviderRegion(intrinsic['provider'].id, 'INTRINSIC_STOPITERATION_ERROR',
                          intrinsic_region.id, ProviderRegionRelation.DEFINES_REPRESENTATION),),
        provider_bindings=tuple(ProviderBinding(intrinsic['provider'].id, intrinsic_region.id,
            ProviderElement(ProviderElementKind.OPERATION, operation.id.value), operation.id)
            for operation in builder.operations if operation.id in {
                *(row.operation for row in intrinsic['matchers']),
                intrinsic['constructor'].id, *(row.id for row in intrinsic['chaining'])}),
        native_boundaries=(intrinsic['native_boundary'],))
    selected = int(route == 'constructor-raise')
    intrinsic = {**intrinsic, 'region': graph.regions[1], 'call': call, 'body_terminal': terminals[selected],
        'body_terminals': tuple(terminals), 'body_packet_definitions': tuple(packets),
        'body_choices': {call.id: selected},
        'path': _selected_path(graph, intrinsic_region, intrinsic['choices'])}
    return graph, intrinsic


def _stage(body, number, chosen_source):
    graph, sources = _association(driver_program(target='start' if number == 0 else 'value',
        async_request=True, extra_domain=True, body_graph=body))
    graph = replace(graph, regions=(*graph.regions, *body.regions[1:]))
    interface, = graph.driver_interfaces
    scope = ProtocolScope(ProtocolScopeID('async.terminal.scope'), ProtocolProfile.ASYNC_GENERATOR_BODY_V1,
                          DriverSubject(interface.region), _source_gap())
    graph = with_publications(replace(graph, protocol_scopes=(scope,)))
    for commit in tuple(graph.body_outcome_commits):
        tail = _Tail(graph, commit.operation)
        tail.metadata(SessionPost.HOLD if number == 0 else SessionPost.COMPLETE,
                      'terminal.session.' + str(tuple(graph.body_outcome_commits).index(commit)))
        graph = tail.finish()
    read, = graph.request_association_reads
    operation = _op(graph, read.operation)
    normal = next(i for i, edge in enumerate(operation.terminator.successors) if edge.kind is ExitKind.NORMAL)
    row = ProtocolOperation(scope.id, ProtocolClause.ASYNC_REQUEST_ASSOCIATE, read.operation, 0,
        RequestAssociation(read.request,
            InvokeLiteralResult(ControlEdgeReference(read.operation, normal), CompletionResult(read.body_result.index)),
            InvokeLiteralResult(ControlEdgeReference(read.operation, normal), CompletionResult(read.latent_result.index)),
            tuple(InvokeStateOperand(operation.id, use.id) for use in operation.uses
                  if use.id in operation.invoke_arguments and isinstance(
                      next(value for value in graph.values if value.id == use.value), StateVersionValue))), _source_gap())
    graph = replace(graph, protocol_operations=(row,), protocol_bindings=tuple(
        AsyncSessionOutcome(scope.id, update.operation, commit.outcome)
        for commit in graph.body_outcome_commits for update in graph.session_updates
        if update.operation in next(block.operations for region in graph.regions for block in region.blocks
                                    if commit.operation in block.operations)))
    graph, predicate = _guard(graph, block_id=BlockID('driver.no_body.test'), owner=sources['session'],
        raw=sources['scheduler'], label='terminal.request.step', rule=BodyStatePredicateRule.IS_CREATED,
        admit_true=number == 0)
    rows = []
    for candidate in graph.protocol_operations:
        if type(candidate.contract) is AdmissionPredicate:
            subject = candidate.contract.subject
            candidate = replace(candidate, clause=ProtocolClause.ASYNC_REQUEST_SOURCE,
                contract=replace(candidate.contract, subject=RequestStateCondition(subject.instance_use,
                    subject.state_sites, RequestStateRule.IS_INITIAL_STEP)))
        elif type(candidate.contract) is RequestProcessing:
            helper = _op(graph, candidate.operation)
            candidate = replace(candidate, clause=ProtocolClause.ASYNC_REQUEST_DELIVERY,
                contract=replace(candidate.contract, raw_use=helper.invoke_arguments[0],
                                 rule=RequestProcessingRule.CHECK_ASYNC_REQUEST))
        rows.append(candidate)
    graph = replace(graph, protocol_operations=tuple(rows))
    driver_region = next(region for region in graph.regions if region.id == interface.region)
    driver_operations = {identity for block in driver_region.blocks for identity in block.operations}
    actual_kinds = {ExitKind.RAISE if operation.terminator.kind is TerminatorKind.RAISE
                    else ExitKind.NORMAL for operation in graph.operations
                    if operation.id in driver_operations and type(operation.terminator) is Terminator
                    and operation.terminator.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE)}
    graph = replace(graph, regions=tuple(replace(region, exits=tuple(
        port for port in region.exits if port.kind in actual_kinds))
        if region.id == interface.region else region for region in graph.regions))
    part = _driver_component(graph, 'terminal.driver.' + str(number))
    part['predicate'] = part['rename'](predicate)
    part['chosen_source'] = chosen_source
    return graph, part


def async_terminal_program(*, route='stop-iteration'):
    if route not in ('stop-iteration', 'stop-async-iteration', 'ordinary', 'constructor-raise'):
        raise ValueError('unknown async terminal route')
    body, intrinsic = _body(route)
    stages = [_stage(body, number, OperationID('resume.suspend') if number == 0
                     else intrinsic['body_terminal'].id)[1] for number in range(2)]
    domains = (*tuple(location.id for location in body.locations),
               next(value.location for value in stages[0]['values'] if isinstance(value, StateVersionValue)
                    and value.location not in {location.id for location in body.locations}))
    state_types = tuple(ValueType(ValueKind.STATE, location=location) for location in domains)
    b = _Builder('terminal.caller', domains)
    region = body.regions[0]
    entry_block = next(row for row in region.blocks if row.id == region.entry)
    values = {value.id: value for value in body.values}
    captures = tuple(value for value in entry_block.arguments if isinstance(values[value], ReferenceValue))
    entry = b.formals('terminal.caller.entry', (*(REFERENCE for _ in captures), REFERENCE, *state_types))
    initial_states = entry[-len(domains):]
    created = b.formals('terminal.body.created', (REFERENCE, *state_types))
    create_fail = b.formals('terminal.body.failed', (PACKET, *state_types))
    create_uses = tuple(_use(f'terminal.create.input.{i}', value, state=i >= len(captures))
                        for i, value in enumerate((*entry[:len(captures)], *initial_states)))
    create = b.add('terminal.create', create_uses, effects_complete=True,
        invoke_arguments=tuple(use.id for use in create_uses),
        completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, *state_types)), CompletionSignature(ExitKind.RAISE, (PACKET, *state_types))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID('terminal.body.created'), tuple(CompletionResult(i) for i in range(1 + len(domains)))),
            CompletionSuccessor(ExitKind.RAISE, BlockID('terminal.body.failed'), tuple(CompletionResult(i) for i in range(1 + len(domains)))))))
    capture_rows = tuple(CreationCapture(formal, use.id) for formal, use in zip(captures, create_uses))
    function = next(member.reference for member in body.environments[0].members if member.role is EnvironmentRole.FUNCTION_OBJECT)
    creation = ResumableCreate(create.id, region.id, next(row.source for row in capture_rows if row.formal == function),
                              capture_rows, NormalResultPort(0), driver_rule())
    b.block('terminal.caller.entry', entry, (create,))
    b.block('terminal.body.failed', create_fail, (b.terminal('terminal.body.failed.exit', create_fail, fail=True),))
    latent = b.value('terminal.latent', OperationResult(OperationID('terminal.latent.pack'), 0), RAW)
    pack = b.add('terminal.latent.pack', results=(latent,), effects_complete=True)
    request_created = b.formals('terminal.request.created', (REFERENCE, REFERENCE, *state_types))
    request_failed = b.formals('terminal.request.failed', (PACKET, *state_types))
    request_uses = (_use('terminal.request.body', created[0]), _use('terminal.request.latent', latent, protocol=True),
                    *(_use(f'terminal.request.state.{i}', value, state=True) for i, value in enumerate(created[1:])))
    forwarded = _use('terminal.request.forward.body', created[0])
    request = b.add('terminal.request.create', (*request_uses, forwarded), effects_complete=True,
        invoke_arguments=tuple(use.id for use in request_uses),
        completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, *state_types)), CompletionSignature(ExitKind.RAISE, (PACKET, *state_types))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID('terminal.request.created'),
                (CompletionResult(0), forwarded.id, *(CompletionResult(i + 1) for i in range(len(domains))))),
            CompletionSuccessor(ExitKind.RAISE, BlockID('terminal.request.failed'), tuple(CompletionResult(i) for i in range(1 + len(domains)))))))
    request_row = AsyncRequestCreate(request.id, request_uses[0].id, request_uses[1].id, NormalResultPort(0), driver_rule())
    b.block('terminal.body.created', created, (pack, request))
    b.block('terminal.request.failed', request_failed, (b.terminal('terminal.request.failed.exit', request_failed, fail=True),))
    raws = [RawRequestDefinition(latent, RawRequestKind.NEXT, ())]
    current_r, current_b, *current_states = request_created
    current_block, current_formals = 'terminal.request.created', request_created
    drivers, calls = [], []
    caller_choices = {create.id: 0, request.id: 0}
    for number, part in enumerate(stages):
        interface, = part['driver_interfaces']
        drive, = part['body_drives']
        gate, = part['final_body_gates']
        own_ops, own_values = {row.id: row for row in part['operations']}, {row.id: row for row in part['values']}
        chosen, = tuple(commit for commit in part['body_outcome_commits'] if commit.outcome.source == part['chosen_source'])
        host_block = next(block for block in part['region'].blocks if chosen.operation in block.operations)
        host = own_ops[host_block.operations[-1]]
        update = next(update for update in part['session_updates'] if update.operation in host_block.operations)
        scheduler_uses = () if number == 0 else (_use('terminal.scheduler.sent', entry[len(captures)]),)
        scheduler = b.value(f'terminal.scheduler.{number}', OperationResult(OperationID(f'terminal.scheduler.{number}.pack'), 0), RAW)
        scheduler_pack = b.add(f'terminal.scheduler.{number}.pack', scheduler_uses, results=(scheduler,), effects_complete=True)
        raws.append(RawRequestDefinition(scheduler, RawRequestKind.NEXT if number == 0 else RawRequestKind.SEND,
                                        tuple(use.id for use in scheduler_uses)))
        formals = next(block.arguments for block in part['region'].blocks if block.id == part['region'].entry)
        actual_values = tuple(current_r if formal == interface.receiver else scheduler if formal == interface.scheduler_request
            else current_states[domains.index(own_values[formal].location)] if isinstance(own_values[formal], StateVersionValue)
            else current_b if formal == formals[0] else entry[len(captures)] for formal in formals)
        actuals = tuple(_use(f'terminal.call.{number}.arg.{i}', value,
            state=isinstance(own_values[formal], StateVersionValue), protocol=not isinstance(own_values[formal], (ReferenceValue, StateVersionValue)))
            for i, (formal, value) in enumerate(zip(formals, actual_values)))
        successors, forwards, landings = [], [], {}
        for exit_ in part['region'].exits:
            name = f'terminal.call.{number}.{exit_.kind.value.lower()}'
            args = b.formals(name, (REFERENCE, REFERENCE, *exit_.types))
            refs = (_use(name + '.request', current_r), _use(name + '.body', current_b))
            forwards.extend(refs)
            successors.append(CompletionSuccessor(exit_.kind, BlockID(name),
                (*(use.id for use in refs), *(CompletionResult(i) for i in range(len(exit_.types))))))
            landings[exit_.kind] = name, args
        call = b.add(f'terminal.call.{number}', (*actuals, *forwards), callee=part['region'].id,
            effects_complete=True, invoke_arguments=tuple(use.id for use in actuals),
            completions=tuple(CompletionSignature(exit_.kind, exit_.types) for exit_ in part['region'].exits),
            terminator=Terminator(TerminatorKind.INVOKE, tuple(successors)))
        b.block(current_block, current_formals, (scheduler_pack, call))
        wanted = ExitKind.RAISE if host.terminator.kind is TerminatorKind.RAISE else ExitKind.NORMAL
        caller_choices[call.id] = next(i for i, edge in enumerate(successors) if edge.kind is wanted)
        for kind, (name, args) in landings.items():
            if kind is not wanted or number == 1:
                b.block(name, args, (b.terminal(name + '.exit', args[2:], fail=kind is ExitKind.RAISE),))
        current_block, current_formals = landings[wanted]
        current_r, current_b = current_formals[:2]
        current_states = current_formals[3:]
        choices = {gate.operation: 0, part['request_association_reads'][0].operation: 0,
                   part['predicate']['branch']: int(number != 0),
                   drive.operation: next(i for i, edge in enumerate(own_ops[drive.operation].terminator.successors)
                                         if edge.source == chosen.outcome.source)}
        drivers.append({'caller_call': call, 'driver_region': part['region'], 'interface': interface,
            'drive': drive, 'gate': gate, 'outcome': chosen.outcome, 'outcome_source': chosen.outcome.source,
            'publication': chosen, 'update': update, 'host_terminal': host, 'entry_formals': formals,
            'predicate': part['predicate'], 'path_choices': choices,
            'association_read': part['request_association_reads'][0]})
        calls.append(call)
    caller = b.finish('terminal.caller.entry')
    caller_exits = {operation.terminator.exit for operation in b.operations
                    if type(operation.terminator) is Terminator
                    and operation.terminator.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE)}
    caller = replace(caller, exits=tuple(port for port in caller.exits if port.name in caller_exits))
    tables = ('driver_interfaces', 'final_body_gates', 'body_drives', 'driver_lifecycles',
        'body_outcome_commits', 'terminal_frame_releases', 'protocol_scopes', 'protocol_operations',
        'literal_evaluations', 'request_association_reads', 'session_updates', 'protocol_bindings',
        'protocol_call_inputs', 'protocol_result_consumers')
    from scar.ir.program.model import StateLocation
    graph = replace(body, root=caller.id, regions=(caller, replace(region, parent=caller.id),
        *body.regions[1:], *(replace(part['region'], parent=caller.id) for part in stages)),
        operations=(*body.operations, *(operation for part in stages for operation in part['operations']), *b.operations),
        values=(*body.values, *(value for part in stages for value in part['values']), *b.values),
        locations=(*body.locations, StateLocation(domains[-1], 'driver-only state')),
        control_scopes=(*body.control_scopes, *(scope for part in stages for scope in part['control_scopes']),
            ControlScope(ControlScopeID('terminal.caller.scope'), caller.id, None, ControlScopeKind.FUNCTION,
                _source('supplied async terminal caller'), tuple(block.id for block in caller.blocks))),
        resumable_creates=(creation,), async_request_creates=(request_row,), raw_driver_requests=tuple(raws),
        **{name: tuple(row for part in stages for row in part[name]) for name in tables})
    for item in drivers:
        item['path'] = _selected_path(graph, item['driver_region'], item['path_choices'])
    body_choices = intrinsic['body_choices']
    body_paths = {0: ((region.entry, 0),),
        1: _selected_path(graph, replace(region, entry=BlockID('resume.value')), body_choices)}
    return graph, {'route': route, 'caller': caller, 'caller_path': _selected_path(graph, caller, caller_choices),
        'body': next(row for row in graph.regions if row.id == region.id),
        'primary_creation': creation, 'drivers': tuple(drivers), 'calls': tuple(calls),
        'body_paths': body_paths, 'intrinsic': intrinsic, 'source': intrinsic['body_terminal'],
        'drive_outcome': drivers[-1]['outcome'], 'request': {'create': request_row, 'operation': request},
        'initial_states': initial_states, 'root_entry': entry, 'capture_formals': captures}


__all__ = ['async_terminal_program']
