"""Conditional session-post history over supplied original effects and captures.

The old reuse capture remains opaque.  The independent positive graph declares
a real post immediately before an independently produced READ/bool/branch; it
does not repair or reinterpret any operation in the old graph.
"""
from dataclasses import replace

import pytest

from scar.ir.execution.common import Unresolved
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate as validate_execution
from scar.ir.program.ids import BlockID, OperationID, ProtocolScopeID, UseID, ValueID
from scar.ir.program.lifecycle import DriverLifecycle, LifecyclePostBinding, SessionPost, SessionUpdate
from scar.ir.program.model import (
    AccessMode, Behavior, Block, CompletionResult, CompletionSignature,
    CompletionSuccessor, DataValue, ExitKind, Footprint, FootprintKind, Operation,
    OperationResult, StateAccess, StateVersionValue, Successor, Terminator,
    TerminatorKind, Use, UseRole, value_type,
)
from scar.ir.program.protocol_connections import RequestStateCondition, RequestStateRule
from scar.ir.program.protocols import (
    AdmissionPredicate, DriverSubject, ProtocolClause, ProtocolOperation,
    ProtocolProfile, ProtocolScope,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.state_addresses import ExistingAccess
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_call_graphs import _model
from tests.fixtures.program_async_connections import async_driver_program
from tests.fixtures.program_async_pipeline_graphs import _selected_path
from tests.fixtures.program_driver_graphs import PACKET, RAW, REFERENCE, _Builder
from tests.fixtures.program_protocol_graphs import _source_gap
from tests.unit.test_program_async_completed_reuse import _reuse_execution


_FLAGS = ('source_runtime_verified', 'runtime_identity_verified',
          'value_identity_verified', 'transformation_authorized')


def _index(program, model):
    require_valid(program)
    checked = validate_execution(model, program)
    assert checked.valid, checked.issues
    return ExecutionIndex(model, program)


def _candidate(view, update):
    candidates = tuple(row for row in view['candidates'] if row['update'] == update)
    assert len(candidates) == 1
    return candidates[0]


def _flags(view):
    assert all(view[name] is False for name in _FLAGS)


def _history_program(*, normal_post=False, wrong_request=False):
    """Independent post/read driver with genuine world and ancillary context READ.

    Existing resumable body/interface types are reused. No BodyDrive, native
    acquisition, or recovered body-source claim is supplied for this tiny graph.
    The session post is an explicit conditional intrinsic contract.
    """
    base, _ = async_driver_program(target='value', session=False, attach_records=False)
    interface, = base.driver_interfaces
    old_driver = next(region for region in base.regions if region.id == interface.region)
    old_ids = {identity for block in old_driver.blocks for identity in block.operations}
    values = {value.id: value for value in base.values}
    old_entry = next(block for block in old_driver.blocks if block.id == old_driver.entry)
    domains = tuple(values[value].location for value in old_entry.arguments
                    if type(values[value]) is StateVersionValue)
    assert len(domains) == 2 and len(interface.lifecycle) == 1
    state_types = tuple(value_type(next(value for value in base.values
        if type(value) is StateVersionValue and value.location == location)) for location in domains)
    builder = _Builder(interface.region.value, domains)
    entry = builder.formals('history.entry', (REFERENCE, RAW, REFERENCE, *state_types))
    body, scheduler, request = entry[:3]
    initial_states = dict(zip(domains, entry[3:]))
    world, = interface.lifecycle
    context = base.resumable_bodies[0].context_location
    read_states = builder.formals('history.read', state_types)
    at_read = dict(zip(domains, read_states))
    source_id = OperationID('history.post')
    request_use = Use(UseID('history.post.request'), body if wrong_request else request, UseRole.REFERENCE)
    body_use = Use(UseID('history.post.body'), body, UseRole.REFERENCE)

    def forward(name, state_values):
        uses = tuple(Use(UseID(f'{name}.{number}'), state_values[location], UseRole.STATE_CONTENT)
                     for number, location in enumerate(domains))
        return Operation(OperationID(name), 'original state forwarding', (Behavior.CONTROL,), uses,
            effects_complete=True, terminator=Terminator(TerminatorKind.JUMP,
                (Successor(BlockID('history.read'), tuple(use.id for use in uses)),)))

    if normal_post:
        own_states = tuple(Use(UseID(f'history.post.state.{number}'), initial_states[location], UseRole.STATE_CONTENT)
                           for number, location in enumerate(domains))
        normal = builder.formals('history.post.normal', state_types)
        raised = builder.formals('history.post.raise', (PACKET, *state_types))
        source = builder.add(source_id.value, (request_use, body_use, *own_states),
            effects_complete=False, invoke_arguments=(request_use.id, body_use.id, *(use.id for use in own_states)),
            completions=(CompletionSignature(ExitKind.NORMAL, state_types),
                         CompletionSignature(ExitKind.RAISE, (PACKET, *state_types))),
            terminator=Terminator(TerminatorKind.INVOKE, (
                CompletionSuccessor(ExitKind.NORMAL, BlockID('history.post.normal'),
                    tuple(CompletionResult(number) for number in range(len(domains)))),
                CompletionSuccessor(ExitKind.RAISE, BlockID('history.post.raise'),
                    tuple(CompletionResult(number) for number in range(1 + len(domains)))))))
        normal_jump = forward('history.normal.jump', dict(zip(domains, normal)))
        packet_use = Use(UseID('history.caught.packet'), raised[0], UseRole.PROTOCOL)
        before = Use(UseID('history.caught.before'), dict(zip(domains, raised[1:]))[context], UseRole.STATE_CONTENT)
        handled = StateVersionValue(ValueID('history.caught.after'), interface.region,
            OperationResult(OperationID('history.caught'), 0), context)
        builder.values.append(handled)
        handler = Operation(OperationID('history.caught'), 'declared caught-context install',
            (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), (packet_use, before), (handled.id,),
            (StateAccess(context, before.id, AccessMode.READ_WRITE, handled.id,
                         Footprint(FootprintKind.WHOLE)),), effects_complete=True)
        raised_states = dict(zip(domains, raised[1:]))
        raised_states[context] = handled.id
        raised_jump = forward('history.raised.jump', raised_states)
        builder.operations.extend((normal_jump, handler, raised_jump))
        builder.block('history.entry', entry, (source,))
        builder.block('history.post.normal', normal, (normal_jump,))
        builder.block('history.post.raise', raised, (handler, raised_jump))
        binding = LifecyclePostBinding.NORMAL_COMPLETION
    else:
        before = Use(UseID('history.post.before'), initial_states[world], UseRole.STATE_CONTENT)
        after = StateVersionValue(ValueID('history.post.after'), interface.region,
            OperationResult(source_id, 0), world)
        builder.values.append(after)
        source = Operation(source_id, 'independent declared COMPLETE post',
            (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), (request_use, body_use, before), (after.id,),
            (StateAccess(world, before.id, AccessMode.READ_WRITE, after.id,
                         Footprint(FootprintKind.WHOLE)),), effects_complete=True)
        current = {**initial_states, world: after.id}
        jump = forward('history.post.jump', current)
        builder.operations.extend((source, jump))
        builder.block('history.entry', entry, (source, jump))
        binding = LifecyclePostBinding.AFTER_OPERATION
    update = SessionUpdate(source.id, request_use.id, body_use.id, binding, SessionPost.COMPLETE)

    read_id, branch_id = OperationID('history.complete.read'), OperationID('history.complete.branch')
    boolean = DataValue(ValueID('history.complete.bool'), interface.region, OperationResult(read_id, 0), 'builtins.bool')
    builder.values.append(boolean)
    receiver = Use(UseID('history.read.request'), request, UseRole.REFERENCE)
    reads = tuple(Use(UseID(f'history.read.state.{number}'), at_read[location], UseRole.STATE_CONTENT)
                  for number, location in enumerate(domains))
    accesses = tuple(StateAccess(location, use.id, AccessMode.READ)
                     for location, use in zip(domains, reads))
    predicate = Operation(read_id, 'independent current request COMPLETE READ',
        (Behavior.CONTROL, Behavior.READ), (receiver, *reads), (boolean.id,), accesses, effects_complete=True)
    condition = Use(UseID('history.branch.bool'), boolean.id, UseRole.DATA)
    branch_uses = [condition]
    branch_edges = []
    for arm in range(2):
        block_id = f'history.exit.{arm}'
        formals = builder.formals(block_id, (REFERENCE, *state_types))
        arguments = []
        for ordinal, value in enumerate((request, *(at_read[location] for location in domains))):
            use = Use(UseID(f'history.branch.{arm}.{ordinal}'), value,
                      UseRole.REFERENCE if ordinal == 0 else UseRole.STATE_CONTENT)
            branch_uses.append(use)
            arguments.append(use.id)
        branch_edges.append(Successor(BlockID(block_id), tuple(arguments)))
        terminal_uses = tuple(Use(UseID(f'history.exit.{arm}.{ordinal}'), value,
            UseRole.REFERENCE if ordinal == 0 else UseRole.STATE_CONTENT) for ordinal, value in enumerate(formals))
        terminal = Operation(OperationID(f'history.exit.{arm}'), 'original query-graph return',
            (Behavior.CONTROL,), terminal_uses, effects_complete=True,
            terminator=Terminator(TerminatorKind.RETURN, exit='normal',
                                  values=tuple(use.id for use in terminal_uses)))
        builder.operations.append(terminal)
        builder.block(block_id, formals, (terminal,))
    branch = Operation(branch_id, 'branch on this READ', (Behavior.CONTROL,), tuple(branch_uses),
        effects_complete=True, terminator=Terminator(TerminatorKind.BRANCH,
            tuple(branch_edges), condition=condition.id))
    builder.operations.extend((predicate, branch))
    builder.block('history.read', read_states, (predicate, branch))
    region = builder.finish('history.entry')
    region = replace(region, exits=tuple(port for port in region.exits if port.kind is ExitKind.NORMAL))
    interface = replace(interface, receiver=request, scheduler_request=scheduler)
    scope = ProtocolScope(ProtocolScopeID('history.scope'), ProtocolProfile.ASYNC_GENERATOR_BODY_V1,
                          DriverSubject(interface.region), _source_gap())
    row = ProtocolOperation(scope.id, ProtocolClause.ASYNC_REQUEST_SOURCE, read_id, 0,
        AdmissionPredicate(RequestStateCondition(receiver.id,
            tuple(ExistingAccess(read_id, number) for number in range(len(accesses))), RequestStateRule.IS_COMPLETE),
            OperationResult(read_id, 0), branch_id), _source_gap())
    retained_values = tuple(value for value in base.values if value.region != interface.region)
    retained_ids = {value.id for value in retained_values}
    graph = replace(base, root=region.id,
        regions=tuple(region if item.id == region.id else item for item in base.regions),
        operations=(*tuple(op for op in base.operations if op.id not in old_ids), *builder.operations),
        values=(*retained_values, *builder.values),
        control_scopes=tuple(replace(item, blocks=tuple(block.id for block in region.blocks))
            if item.region == region.id else item for item in base.control_scopes),
        driver_interfaces=(interface,), final_body_gates=(), body_drives=(),
        request_association_reads=(), body_outcome_commits=(),
        exception_packets=tuple(item for item in base.exception_packets if item.value in retained_ids),
        protocol_scopes=(scope,), protocol_operations=(row,), protocol_bindings=(),
        driver_lifecycles=(DriverLifecycle(region.id),), session_updates=(update,))
    return graph, dict(update=update, source=source, read=predicate, branch=branch,
                       predicate=row, world=world, context=context, normal_post=normal_post)


def _history_execution(*, normal_post=False, raised=False, wrong_request=False):
    program, details = _history_program(normal_post=normal_post, wrong_request=wrong_request)
    region = next(item for item in program.regions if item.id == program.root)
    choices = {op.id: 0 for op in program.operations if op.terminator is not None and op.terminator.successors}
    if normal_post:
        choices[details['source'].id] = 1 if raised else 0
    path = _selected_path(program, region, choices)
    model, scopes, evidence = _model(program, ((region.id, path, 'history.capture'),))
    scope, = scopes
    return program, model, {**details, 'scope': scope, 'source_occurrence': scope[2][details['source'].id],
                            'read_occurrence': scope[2][details['read'].id], 'evidence': evidence}


@pytest.mark.parametrize('reject_raised', (False, True), ids=('old-helper-normal', 'old-helper-raise'))
def test_old_completed_reuse_has_true_post_and_subject_but_retains_every_opaque_or_write_blocker(reject_raised):
    program, model, details = _reuse_execution(reject_raised=reject_raised)
    index = _index(program, model)
    read = details['second_scope'][2][details['predicate']]
    view = index.request_state_history(read, budget=131072)
    update, = program.session_updates
    candidate = _candidate(view, update)
    assert candidate['source'].id == details['first_scope'][2][update.operation]
    assert candidate['post_established'] is True
    assert candidate['subject_binding']['match'] is True
    expected_locations = {value.location for value in ProgramIndex(program).session_publication(update.operation).support}
    predicate = next(op for op in program.operations if op.id == details['predicate'])
    expected_locations.update(access.location for access in predicate.accesses)
    assert set(candidate['locations']) == expected_locations
    assert candidate['preservation']['preserved'] is None
    assert candidate['expected_bool'] is view['expected_bool'] is None
    assert view['observed_branch'] is True
    blockers = {item['operation'] for item in candidate['preservation']['blockers']
                if item['operation'] is not None}
    association, = program.request_association_reads
    assert {details['first_scope'][2][OperationID('adapter.construct')],
            details['first_scope'][2][details['first_terminal'].id],
            details['caller_scope'][2][details['completion_handler'].id],
            details['second_scope'][2][association.operation]} <= blockers
    assert view['source_inventory'] == program.session_updates
    assert view['missing_sources'] == ()
    _flags(view)


def test_independent_complete_post_and_real_ancillary_read_derive_a_conditional_true_boolean():
    program, model, details = _history_execution()
    view = _index(program, model).request_state_history(details['read_occurrence'], budget=32768)
    candidate = _candidate(view, details['update'])
    assert candidate['source'].id == details['source_occurrence']
    assert candidate['post_established'] is True
    assert candidate['subject_binding']['match'] is True
    assert set(candidate['locations']) == {details['world'], details['context']}
    assert {value.location for value in ProgramIndex(program).session_publication(details['source'].id).support} == {details['world']}
    assert candidate['preservation']['preserved'] is True
    assert candidate['preservation']['reached'] is True
    assert candidate['preservation']['blockers'] == ()
    assert candidate['expected_bool'] is view['expected_bool'] is True
    assert view['observed_branch'] is True
    assert view['predicate'] == details['predicate']
    assert view['read'].id == details['read_occurrence']
    _flags(view)


@pytest.mark.parametrize('raised', (False, True), ids=('actual-normal-post', 'actual-raise-no-post'))
def test_normal_only_post_uses_its_exact_selected_completion_before_the_read(raised):
    program, model, details = _history_execution(normal_post=True, raised=raised)
    view = _index(program, model).request_state_history(details['read_occurrence'], budget=32768)
    candidate = _candidate(view, details['update'])
    assert candidate['source'].id == details['source_occurrence']
    actual, = tuple(row for row in model.transfers if row.operation == details['source_occurrence'])
    assert details['source'].terminator.successors[actual.successor_index].kind is (
        ExitKind.RAISE if raised else ExitKind.NORMAL)
    assert candidate['post_established'] is (not raised)
    assert candidate['subject_binding']['match'] is True
    assert set(candidate['locations']) == {details['world'], details['context']}
    assert candidate['expected_bool'] is (None if raised else True)
    assert view['expected_bool'] is (None if raised else True)
    if not raised:
        assert candidate['preservation']['preserved'] is True
    else:
        assert candidate['preservation']['preserved'] is None
    assert view['observed_branch'] is True
    _flags(view)


def test_same_typed_other_request_post_cannot_supply_the_read_even_on_a_complete_effect_path():
    program, model, details = _history_execution(wrong_request=True)
    view = _index(program, model).request_state_history(details['read_occurrence'], budget=32768)
    candidate = _candidate(view, details['update'])
    assert candidate['post_established'] is True
    assert candidate['subject_binding']['match'] is not True
    assert candidate['expected_bool'] is view['expected_bool'] is None
    assert view['observed_branch'] is True
    assert view['source_inventory'] == program.session_updates
    _flags(view)


def test_missing_post_capture_keeps_the_original_source_row_without_using_observed_true_as_a_seed():
    program, model, details = _history_execution()
    source = details['source_occurrence']
    missing_values = {row.id for row in model.values if row.origin == source}
    point = model.activations[0].entry
    unknown = Unresolved('this exact post result was not captured', point)
    changed = replace(model,
        operations=tuple(row for row in model.operations if row.id != source),
        values=tuple(row for row in model.values if row.id not in missing_values),
        uses=tuple(replace(row, value=unknown) if row.value in missing_values else row
                   for row in model.uses if row.operation != source))
    view = _index(program, changed).request_state_history(details['read_occurrence'], budget=32768)
    assert view['source_inventory'] == program.session_updates
    assert view['missing_sources'] == (details['update'],)
    assert view['candidates'] == ()
    assert view['expected_bool'] is None and view['observed_branch'] is True
    assert view['gaps']
    _flags(view)


def test_budget_one_keeps_original_post_inventory_and_does_not_infer_from_the_true_branch():
    program, model, details = _history_execution()
    view = _index(program, model).request_state_history(details['read_occurrence'], budget=1)
    assert view['source_inventory'] == program.session_updates
    assert view['missing_sources'] == ()
    assert set(view['locations']) == {details['world'], details['context']}
    assert view['expected_bool'] is None
    assert all(row['expected_bool'] is None for row in view['candidates'])
    assert view['budget']['truncated'] is True
    assert view['cursor'] is not None
    _flags(view)


@pytest.mark.parametrize('normal_post', (False, True), ids=('after-state-input', 'normal-state-input'))
def test_missing_source_state_input_cannot_establish_post_from_its_captured_outputs(normal_post):
    program, model, details = _history_execution(normal_post=normal_post)
    definitions = {value.id: value for value in program.values}
    state_use = next(use for use in details['source'].uses
        if type(definitions[use.value]) is StateVersionValue
        and definitions[use.value].location == details['world'])
    if normal_post:
        assert state_use.id in details['source'].invoke_arguments
    else:
        assert state_use.id == details['source'].accesses[0].before
    omitted = (details['source_occurrence'], state_use.id)
    assert sum((use.operation, use.use) == omitted for use in model.uses) == 1
    changed = replace(model, uses=tuple(use for use in model.uses
        if (use.operation, use.use) != omitted))
    view = _index(program, changed).request_state_history(details['read_occurrence'], budget=32768)
    candidate = _candidate(view, details['update'])
    assert view['source_inventory'] == program.session_updates
    assert view['missing_sources'] == ()
    assert candidate['source'].id == details['source_occurrence']
    assert candidate['post_established'] is not True
    assert candidate['expected_bool'] is view['expected_bool'] is None
    assert 'state_history_post_input_state_unobserved' in candidate['gaps']
    assert view['observed_branch'] is True
    _flags(view)
