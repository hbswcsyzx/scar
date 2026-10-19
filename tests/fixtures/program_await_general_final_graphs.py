"""One supplied general-await source, persistent body and final implementation.

The independent caller input A is acquired before the first NEXT.  The actual
bound-method call inside that acquisition creates B.  All subsequent drives
use the returned iterator, including the first drive on the two-cut path.
The old caller Create sites remain explicit decoys, never B's origin.
"""
from dataclasses import replace

from scar.ir.program.control import ExceptionPacketDefinition
from scar.ir.program.ids import BlockID, OperationID, ProtocolScopeID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, ExitKind, InvokeLiteralResult,
    Operation, OperationResult, ReferenceValue, StateVersionValue, Successor,
    Terminator, TerminatorKind, Use, UseRole,
)
from scar.ir.program.protocol_await_records import (
    AwaitAcquisition, AwaitBodyLink, AwaitIteratorQualification, ExpandedAwaitCallee,
)
from scar.ir.program.protocol_connections import (
    InitialAdvance, ProtocolCallInputCase, ProtocolCallInputs, ProtocolOperationRef,
    ProtocolResultConsumers,
)
from scar.ir.program.protocols import (
    ContractResult, DriverSubject, HostTerminal, OperationSiteSubject, OwnedUse,
    ProtocolCall, ProtocolCallRule, ProtocolClause, ProtocolOperation, ProtocolProfile,
    ProtocolScope, StaticGapReason, StaticProtocolGap,
)
from scar.ir.program.resumption import ResumableKind
from scar.ir.program.state_addresses import InvokeStateOperand
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_async_pipeline_graphs import _selected_path
from tests.fixtures.program_await_final_region_graphs import await_final_region_program
from tests.fixtures.program_await_general_graphs import _helper_region


def _ref(row):
    return ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)


def await_general_final_program(*, zero_cut=True, depth=1):
    """Return the same canonical general source through zero/two cuts and E/G/F.

    Only the existing acquisition gets a real callee.  Its helper owns the
    lookup, call, Create and qualification.  Children of the final extractor
    remain ordinary region implementations, without duplicate await semantics.
    """
    graph, prior = await_final_region_program(zero_cut=zero_cut, depth=depth)
    caller = prior['caller']
    operations = {row.id: row for row in graph.operations}
    values = {row.id: row for row in graph.values}
    blocks = {row.id: row for row in caller.blocks}
    entry = blocks[caller.entry]
    a = ReferenceValue(ValueID('await.general.final.A'), caller.id,
                       BlockArgument(entry.id, len(entry.arguments)))
    blocks[entry.id] = replace(entry, arguments=(*entry.arguments, a.id))
    added_values = [a]
    added_operations = []
    body = replace(graph.resumable_bodies[0], kind=ResumableKind.GENERATOR)
    environment = graph.environments[0]
    layout = next(row for row in graph.function_entries if row.environment == environment.id)
    old_create = prior['primary_creation']
    create_operation = operations[old_create.operation]
    capture_uses = {use.id: use for use in create_operation.uses}
    capture_values = {capture.formal: capture_uses[capture.source].value
                      for capture in old_create.captures}
    environment_values = tuple(capture_values[member.reference] for member in environment.members)

    old_get = prior['get']
    old_actuals = {use.id: use for use in old_get.uses}
    state_uses = tuple(old_actuals[identity] for identity in old_get.invoke_arguments
                       if isinstance(values[old_actuals[identity].value], StateVersionValue))
    state_locations = tuple(values[use.value].location for use in state_uses)
    helper = _helper_region(caller.id, state_locations, body, environment, layout, old_create.rule)
    forwards = tuple(use for use in old_get.uses if use.id not in old_get.invoke_arguments)
    first_call = prior['calls'][0]
    calls = list(prior['calls'])
    driver_details = [dict(row) for row in prior['drivers']]

    if not zero_cut:
        # The old fixture acquires only after its first direct drive.  Move
        # this exact Get before that drive and route its current outputs into
        # the original call0.  New B is never resumed from another B's cut.
        call_actuals = {use.id: use for use in first_call.uses}
        early_states = tuple(call_actuals[identity].value for identity in first_call.invoke_arguments
                             if isinstance(values[call_actuals[identity].value], StateVersionValue))
        state_uses = tuple(replace(use, value=value)
                           for use, value in zip(state_uses, early_states))
        call_forwards = tuple(use for use in first_call.uses if use.id not in first_call.invoke_arguments)
        forwards = tuple(replace(use, value=source.value)
                         for use, source in zip(forwards, call_forwards))
        acquired = blocks[BlockID('await.resume.acquired')]
        before_call = BlockID('await.general.final.before_first_call')
        incoming = tuple(replace(values[identity],
            id=ValueID(f'{before_call.value}.arg.{index}'), origin=BlockArgument(before_call, index))
            for index, identity in enumerate(acquired.arguments))
        added_values.extend(incoming)
        iterator, retained, decoy = incoming[:3]
        new_states = incoming[-len(state_uses):]
        state_actual_ids = tuple(identity for identity in first_call.invoke_arguments
            if isinstance(values[call_actuals[identity].value], StateVersionValue))
        updates = {first_call.invoke_arguments[0]: iterator.id,
                   **{identity: value.id for identity, value in zip(state_actual_ids, new_states)},
                   **{use.id: value.id for use, value in zip(call_forwards, (iterator, decoy))}}
        first_call = replace(first_call, uses=tuple(replace(use, value=updates.get(use.id, use.value))
                                                   for use in first_call.uses))
        operations[first_call.id] = first_call
        calls[0] = first_call
        driver_details[0].update(caller_call=first_call, direct=False)
        old_call_block = next(block for block in caller.blocks if first_call.id in block.operations)
        # NEXT raw packing is a real operation, moved with its consuming call.
        blocks[before_call] = Block(before_call, tuple(value.id for value in incoming),
                                   old_call_block.operations)
        blocks[old_call_block.id] = replace(old_call_block, operations=(old_get.id,))
        normal = blocks[driver_details[0]['selected_landing']]
        latest = tuple(values[identity] for identity in normal.arguments)
        # Original normal formals are B, decoy, handoff payload, W, C.
        selected_values = (latest[0], latest[0], latest[1], *latest[-len(state_uses):])
        jump_uses = tuple(Use(UseID(f'await.general.final.after_first.{index}'), value.id,
            UseRole.STATE_CONTENT if isinstance(value, StateVersionValue) else UseRole.REFERENCE)
            for index, value in enumerate(selected_values))
        jump = Operation(OperationID('await.general.final.after_first'),
            'carry this B and the current post-call states after its first cut',
            (Behavior.CONTROL,), jump_uses, effects_complete=True,
            terminator=Terminator(TerminatorKind.JUMP,
                (Successor(acquired.id, tuple(use.id for use in jump_uses)),)))
        added_operations.append(jump)
        blocks[normal.id] = replace(normal, operations=tuple(
            jump.id if identity == old_get.id else identity for identity in normal.operations))
        get_edges = tuple(replace(edge, block=before_call) if edge.kind is ExitKind.NORMAL else edge
                          for edge in old_get.terminator.successors)
        get_terminator = replace(old_get.terminator, successors=get_edges)
    else:
        get_terminator = old_get.terminator
        driver_details[0]['direct'] = False

    get_operand = replace(old_actuals[old_get.invoke_arguments[0]], value=a.id)
    get_captures = tuple(Use(UseID(f'await.general.final.get.capture.{index}'), identity, UseRole.REFERENCE)
                         for index, identity in enumerate(environment_values))
    get_actuals = (get_operand, *get_captures, *state_uses)
    get = replace(old_get, callee=helper['region'].id, uses=(*get_actuals, *forwards),
                  invoke_arguments=tuple(use.id for use in get_actuals), terminator=get_terminator)
    operations[get.id] = get

    method_scope_id = ProtocolScopeID('await.general.final.method')
    gap = StaticProtocolGap(StaticGapReason.NATIVE_APPLICABILITY_UNPROVEN)
    lookup, call, qualify, branch = (helper[key] for key in ('lookup', 'call', 'qualify', 'branch'))
    helper_values = {value.id: value for value in helper['values']}

    def state_sites(operation):
        return tuple(InvokeStateOperand(operation.id, use.id) for use in operation.uses
                     if isinstance(helper_values[use.value], StateVersionValue))

    def method_rows(operation, clause, rule):
        return tuple(ProtocolOperation(method_scope_id, clause, operation.id, index,
            ProtocolCall(operation.uses[0].id, (), InvokeLiteralResult(
                ControlEdgeReference(operation.id, index), CompletionResult(0)),
                state_sites(operation), rule), gap)
            for index in range(len(operation.terminator.successors)))

    lookup_rows = method_rows(lookup, ProtocolClause.AWAIT_LOOKUP, ProtocolCallRule.AWAIT_LOOKUP)
    method_call_rows = method_rows(call, ProtocolClause.AWAIT_CALL, ProtocolCallRule.AWAIT_CALL)
    qualification_row = ProtocolOperation(method_scope_id, ProtocolClause.AWAIT_ITERATOR_QUALIFICATION,
        qualify.id, 0, AwaitIteratorQualification(qualify.uses[0].id,
            BlockArgument(helper['call_normal'], 0), OperationResult(qualify.id, 0),
            (), branch.id, True), gap)
    expansion = ExpandedAwaitCallee(_ref(lookup_rows[0]), _ref(method_call_rows[0]), _ref(qualification_row))
    get_rows = tuple(replace(row, contract=AwaitAcquisition(get_operand.id, a.origin,
        InvokeLiteralResult(ControlEdgeReference(get.id, row.slot), CompletionResult(0)),
        tuple(InvokeStateOperand(get.id, use.id) for use in state_uses), expansion))
        for row in prior['get_rows'])
    acquired_result = ContractResult(get_rows[0].scope, get_rows[0].clause, get.id,
                                    get_rows[0].slot, get_rows[0].contract.result)
    lookup_result = ContractResult(method_scope_id, lookup_rows[0].clause, lookup.id, 0,
                                  lookup_rows[0].contract.result)
    call_result = ContractResult(method_scope_id, method_call_rows[0].clause, call.id, 0,
                                method_call_rows[0].contract.result)
    method_inputs = tuple(ProtocolCallInputs(_ref(row), (ProtocolCallInputCase(None,
        BlockArgument(helper['entry'], 0) if row.operation == lookup.id else lookup_result,
        (), None),)) for row in (*lookup_rows, *method_call_rows))
    method_consumers = (
        ProtocolResultConsumers(_ref(lookup_rows[0]), (OwnedUse(call.id, call.uses[0].id),)),
        ProtocolResultConsumers(_ref(lookup_rows[1]), (HostTerminal(helper['lookup_raise'].id),)),
        ProtocolResultConsumers(_ref(method_call_rows[0]), (OwnedUse(qualify.id, qualify.uses[0].id),)),
        ProtocolResultConsumers(_ref(method_call_rows[1]), (HostTerminal(helper['call_raise'].id),)),
        ProtocolResultConsumers(_ref(qualification_row), (OwnedUse(branch.id, branch.uses[0].id),)),
    )
    scopes = tuple(replace(scope, profile=ProtocolProfile.GENERATOR_BODY_V1)
        if isinstance(scope.subject, DriverSubject)
        and scope.profile is ProtocolProfile.GENERATOR_COROUTINE_BODY_V1 else scope
        for scope in graph.protocol_scopes)
    # The original template was a generator-coroutine direct-body interface.
    # General __await__ returns a plain generator here, so its genuine Return
    # adapter uses that body's HOST_ADAPTER clause and matching receipt keys.
    conversion_rows = tuple(replace(row, clause=ProtocolClause.HOST_ADAPTER)
                            for row in prior['conversion_rows'])
    conversion_map = {_ref(old): new for old, new in zip(prior['conversion_rows'], conversion_rows)}
    conversion_receipts = tuple(replace(receipt, site=_ref(conversion_map[receipt.site]))
                                for receipt in prior['conversion_receipts'])
    new_rows, new_inputs, new_links = [], [], []
    if not zero_cut:
        first_scope = ProtocolScopeID('await.general.final.first_advance')
        scopes += (ProtocolScope(first_scope, ProtocolProfile.DELEGATION_SITE_V1,
            OperationSiteSubject(caller.id, first_call.id), gap),)
        use_map = {use.id: use for use in first_call.uses}
        first_state_sites = tuple(InvokeStateOperand(first_call.id, identity)
            for identity in first_call.invoke_arguments
            if isinstance(next((value for value in added_values if value.id == use_map[identity].value),
                               values.get(use_map[identity].value)), StateVersionValue))
        for index in range(len(first_call.terminator.successors)):
            row = ProtocolOperation(first_scope, ProtocolClause.DELEGATE_ADVANCE, first_call.id, index,
                ProtocolCall(first_call.invoke_arguments[0], (), InvokeLiteralResult(
                    ControlEdgeReference(first_call.id, index), CompletionResult(0)),
                    first_state_sites, ProtocolCallRule.DELEGATE_NEXT), gap)
            new_rows.append(row)
            new_inputs.append(ProtocolCallInputs(_ref(row), (
                ProtocolCallInputCase(None, acquired_result, (), InitialAdvance(acquired_result)),)))
            new_links.append(AwaitBodyLink(prior['source'], _ref(row),
                                          driver_details[0]['drive'].operation, None, None))

    method_scope = ProtocolScope(method_scope_id, ProtocolProfile.AWAIT_METHOD_IMPLEMENTATION_V1,
        OperationSiteSubject(helper['region'].id, lookup.id), gap)
    all_call_rows = (*new_rows, *prior['call_rows'])
    get_consumers = tuple(replace(receipt, targets=tuple(OwnedUse(row.operation, row.contract.receiver_use)
        for row in all_call_rows if row.slot == 0)) if receipt.site == _ref(get_rows[0]) else
        replace(receipt, site=_ref(conversion_map[receipt.site])) if receipt.site in conversion_map else receipt
        for receipt in graph.protocol_result_consumers)
    caller = replace(caller, blocks=tuple(blocks.values()))
    result = replace(graph,
        regions=tuple(caller if region.id == caller.id else region for region in graph.regions)
                + (helper['region'],),
        operations=(*operations.values(), *added_operations, *helper['operations']),
        values=(*graph.values, *added_values, *helper['values']),
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in caller.blocks))
            if scope.region == caller.id else scope for scope in graph.control_scopes) + (helper['scope'],),
        resumable_bodies=(body,), resumable_creates=(*graph.resumable_creates, helper['create']),
        protocol_scopes=(*scopes, method_scope),
        protocol_operations=tuple(conversion_map.get(_ref(row), row)
            for row in graph.protocol_operations if row.operation != get.id)
            + (*get_rows, *lookup_rows, *method_call_rows, qualification_row, *new_rows),
        protocol_call_inputs=(*graph.protocol_call_inputs, *method_inputs, *new_inputs),
        protocol_result_consumers=(*get_consumers, *method_consumers),
        protocol_bindings=(*graph.protocol_bindings, *new_links),
        exception_packets=(*graph.exception_packets, ExceptionPacketDefinition(helper['packet'].id,
            helper['packet_error'].uses[0].id, helper['packet_error'].uses[1].id)))
    choices = {operation.id: 0 for operation in prior['create_operations']}
    choices[get.id] = 0
    if not zero_cut:
        choices[OperationID('await.general.final.after_first')] = 0
    choices.update((row['caller_call'].id, row['selected_call_edge']) for row in driver_details)
    choices[prior['extract'].id] = 0
    helper_choices = {lookup.id: 0, call.id: 0, branch.id: 0}
    return result, {**prior, 'caller': caller,
        'caller_choices': choices, 'caller_path': _selected_path(result, caller, choices),
        'get': get, 'get_rows': get_rows, 'calls': tuple(calls), 'drivers': tuple(driver_details),
        'call_rows': tuple(all_call_rows), 'links': (*prior['links'], *new_links),
        'body_kind': ResumableKind.GENERATOR, 'A': a.origin, 'A_value': a,
        'B': BlockArgument(helper['call_normal'], 0), 'helper': helper['region'],
        'helper_definition': helper, 'helper_path': _selected_path(result, helper['region'], helper_choices),
        'helper_lookup': lookup, 'helper_call': call, 'helper_return': helper['return'],
        'helper_create': helper['create'], 'helper_create_operation': call,
        'helper_entry': helper['entry'], 'qualification': qualify,
        'qualification_branch': branch, 'qualification_row': qualification_row,
        'method_scope': method_scope_id, 'method_lookup_rows': lookup_rows,
        'method_call_rows': method_call_rows, 'lookup_success': lookup_result,
        'call_success': call_result, 'accepted_edge': ControlEdgeReference(branch.id, 0),
        'rejected_edge': ControlEdgeReference(branch.id, 1),
        'outer_creations': prior['creations'], 'primary_creation': helper['create'],
        'conversion_rows': conversion_rows, 'conversion_sites': tuple(map(_ref, conversion_rows)),
        'conversion_receipts': conversion_receipts}


__all__ = ['await_general_final_program']
