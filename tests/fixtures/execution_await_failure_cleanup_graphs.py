"""Exact helper failures, Get own RAISE, and caller C1 captures.

Each invocation owns its caller and acquisition-helper activations. The helper
completion remains separate from the caller's current Return/Raise. No drive,
body activation, suspension, or runtime identity evidence is manufactured.
"""
from dataclasses import replace

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.common import EvidencePoint, MissingEvidence
from scar.ir.execution.coordinates import ExecutionRun, HostThreadInstance, ProcessInstance
from scar.ir.execution.ids import CallActivationID, HostThreadInstanceID, ProcessInstanceID, RunID
from scar.ir.execution.model import ExecutionModel
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.program.model import CompletionResult, InvokeLiteralResult, OperationResult, StateVersionValue
from scar.ir.program.protocols import ContractResult, OwnedUse
from tests.fixtures.execution_await_outcome_graphs import _omit_suffix
from tests.fixtures.execution_call_graphs import _activation
from tests.fixtures.program_await_failure_cleanup_graphs import await_failure_cleanup_program


_TABLES = ('activations', 'segments', 'visits', 'operations', 'values', 'uses', 'transfers')


def await_failure_cleanup_execution(stage='qualification_reject', mode='preserve', instances=2,
        missing_payload_use=None, missing_dispatch=None, missing_helper_call=None):
    """Return two independent original-port captures, optionally incomplete.

    Missing payload means the first pending constructor's original incoming
    packet Use. Missing dispatch removes that caller's dispatch and suffix.
    Missing helper call omits only the selected instance's explicit association.
    """
    if type(instances) is not int or instances < 1:
        raise ValueError('instances must be a positive exact integer')
    for label, instance in (('missing_payload_use', missing_payload_use),
                            ('missing_dispatch', missing_dispatch),
                            ('missing_helper_call', missing_helper_call)):
        if instance is not None and (type(instance) is not int or not 0 <= instance < instances):
            raise ValueError(label + ' must select an exact captured instance')
    program, static = await_failure_cleanup_program(stage=stage, mode=mode)
    cleanup = static['failure_cleanup']
    helper_region = cleanup['helper_region']
    if helper_region is None and missing_helper_call is not None:
        raise ValueError('the primitive wrapper constructor has no helper CallActivation to omit')
    source = MissingEvidence('supplied acquisition failure and synchronous caller cleanup; no native proof')
    run = RunID('await.failure.cleanup.run')
    process = ProcessInstanceID('await.failure.cleanup.process')
    thread = HostThreadInstanceID('await.failure.cleanup.thread')
    point = EvidencePoint(run, process, source)
    combined = {name: [] for name in _TABLES}
    calls, examples = [], []
    definitions = {value.id: value for value in program.values}
    operations = {operation.id: operation for operation in program.operations}
    blocks = {block.id: block for region in program.regions for block in region.blocks}

    def append(captured):
        for name in _TABLES:
            combined[name].extend(captured[name])

    def value_at(origin, definition):
        matches = tuple(value for value in combined['values']
                        if value.origin == origin and value.value == definition)
        if len(matches) != 1:
            raise AssertionError('an original value port must name exactly one captured occurrence')
        return matches[0]

    def original_use(occurrence, identity):
        matches = tuple(use for use in combined['uses']
                        if (use.operation, use.use) == (occurrence, identity))
        if len(matches) != 1:
            raise AssertionError('an original owned Use must have exactly one occurrence before omission')
        return matches[0]

    def use_value(use):
        return next(value for value in combined['values'] if value.id == use.value)

    def port_value(port, occurrence_map):
        if type(port) is ContractResult:
            port = port.result_port
        if type(port) is OwnedUse:
            return use_value(original_use(occurrence_map[port.operation], port.use))
        if type(port) is OperationResult:
            operation = operations[port.operation]
            return value_at(occurrence_map[port.operation], operation.results[port.index])
        if type(port) is not InvokeLiteralResult:
            raise AssertionError('the failure source must retain an actual own typed result')
        occurrence = occurrence_map[port.edge.operation]
        transfer, = tuple(row for row in combined['transfers'] if row.operation == occurrence)
        if transfer.successor_index != port.edge.successor_index:
            raise AssertionError('the supplied source port must be this occurrence selected completion')
        operation = operations[port.edge.operation]
        edge = operation.terminator.successors[transfer.successor_index]
        visit = next(row for row in combined['visits'] if row.id == transfer.target)
        block = blocks[visit.block]
        formals = tuple(formal for argument, formal in zip(edge.arguments, block.arguments)
                        if type(argument) is CompletionResult and argument.index == port.result.index)
        if len(formals) != 1:
            raise AssertionError('an own completion slot must retain one exact original landing formal')
        return value_at(visit.id, formals[0])

    def pending_constructor(definition, mapped):
        if definition is None:
            return None
        origin = definitions[definition.value].origin
        if type(origin) is not OperationResult:
            raise AssertionError('the original pending definition needs its own canonical constructor')
        return mapped[origin.operation]

    for instance in range(instances):
        prefix = f'await.failure.cleanup.instance.{instance}'
        caller_region = cleanup['caller_region']
        captured, caller, caller_visits, caller_map = _activation(program,
            caller_region.id, cleanup['caller_path'], prefix + '.caller', point, thread)
        append(captured)
        source_occurrence = caller_map[cleanup['source_operation'].id]
        root = port_value(cleanup['source_result'], caller_map)
        transfer, = tuple(row for row in combined['transfers'] if row.operation == source_occurrence)
        source_states = tuple(value_at(transfer.target, definition.id) for definition in cleanup['source_states'])
        forwarded_value = value_at(transfer.target, cleanup['forwarded_reference'].id)
        forwarded_use = original_use(source_occurrence, cleanup['forwarded_use'].use)
        helper_activation, helper_visits, helper_map, association = None, (), {}, None
        helper_terminal, helper_packet_use, helper_packet = None, None, None
        stage_occurrence = source_occurrence if helper_region is None else None
        stage_source_occurrence = source_occurrence if helper_region is None else None
        stage_source, stage_use = root if helper_region is None else None, None
        constructor, constructor_uses = None, ()
        if helper_region is not None:
            captured, helper_activation, helper_visits, helper_map = _activation(program,
                helper_region.id, cleanup['helper_path'], prefix + '.helper', point, thread)
            append(captured)
            terminal = cleanup['helper_terminal']
            helper_terminal = helper_map[terminal.id]
            association = CallActivation(CallActivationID(prefix + '.get.helper'), source_occurrence,
                helper_activation, helper_visits[0], helper_terminal, source)
            if missing_helper_call != instance:
                calls.append(association)
            packet_use = cleanup.get('helper_stage_packet_use')
            if packet_use is None:
                payload_uses = tuple(use for use in terminal.uses
                    if use.id in terminal.terminator.values
                    and not isinstance(definitions[use.value], StateVersionValue))
                if len(payload_uses) != 1:
                    raise AssertionError('the original helper terminal must retain one whole packet payload')
                packet_use = OwnedUse(terminal.id, payload_uses[0].id)
            helper_packet_use = original_use(helper_terminal, packet_use.use)
            helper_packet = use_value(helper_packet_use)
            stage_source = port_value(cleanup['stage_source'], helper_map)
            stage_port = cleanup['stage_source']
            stage_site = stage_port.edge.operation if type(stage_port) is InvokeLiteralResult else stage_port.operation
            stage_source_occurrence = helper_map[stage_site]
            stage_definition = cleanup['stage_operation']
            stage_occurrence = helper_map[stage_definition.id]
            stage_use = helper_packet_use
            packet_definition = cleanup['packet_definition']
            if packet_definition is not None:
                origin = definitions[packet_definition.value].origin
                if type(origin) is not OperationResult:
                    raise AssertionError('the rejected qualification packet requires its original constructor')
                constructor = helper_map[origin.operation]
                constructor_uses = tuple(original_use(constructor, identity)
                    for identity in (packet_definition.exception, packet_definition.traceback))

        terminal, = cleanup['terminals']
        current = caller_map[terminal.id]
        payload, = cleanup['payload_uses']
        current_use = original_use(current, payload.use)
        current_states = tuple(original_use(caller_map[owned.operation], owned.use)
                               for owned in cleanup['state_uses'])
        original_pending = cleanup['pending']
        pending = pending_constructor(original_pending, caller_map)
        payload_use = original_use(pending, original_pending.payload)
        replacement = cleanup['replacement_pending']
        replacement_constructor = pending_constructor(replacement, caller_map)
        selected_pending = replacement or original_pending
        selected_constructor = replacement_constructor or pending
        dispatch = caller_map[cleanup['dispatch'].id]
        helper_states = tuple(original_use(helper_map[owned.operation], owned.use)
                              for owned in cleanup['helper_state_uses'])
        examples.append({'instance': instance, 'caller_activation': caller,
            'caller_visits': caller_visits, 'caller_operations': caller_map,
            'caller_path': cleanup['caller_path'], 'source': source_occurrence,
            'get': source_occurrence, 'source_operation': source_occurrence,
            'source_result_port': cleanup['source_result'], 'source_result': root,
            'source_transfer': transfer, 'source_landing': transfer.target,
            'root_value': root, 'root_packet': root, 'source_states': source_states,
            'source_state_values': source_states,
            'forwarded_value': forwarded_value, 'forwarded_reference': forwarded_value,
            'forwarded_use': forwarded_use,
            'helper_activation': helper_activation, 'helper_visits': helper_visits,
            'helper_operations': helper_map, 'helper_scope': None if helper_activation is None else
                (helper_activation, helper_visits, helper_map),
            'helper_call': association, 'call_activation': association,
            'call_activations': () if association is None else (association,),
            'call_completion': helper_terminal, 'helper_terminal': helper_terminal,
            'helper_terminal_use': helper_packet_use, 'helper_terminal_value': helper_packet,
            'helper_state_uses': helper_states,
            'helper_state_values': tuple(use_value(use) for use in helper_states),
            'stage': stage_occurrence, 'stage_source_occurrence': stage_source_occurrence,
            'stage_source_port': cleanup['stage_source'],
            'stage_source_use': stage_use, 'stage_source_value': stage_source,
            'packet_constructor': constructor, 'packet_constructor_uses': constructor_uses,
            'caller_terminal': current, 'current_terminal': current, 'final': current,
            'current_terminal_definition': terminal, 'final_definition': terminal,
            'current_payload_use': current_use, 'current_payload_value': use_value(current_use),
            'current_state_uses': current_states,
            'current_state_values': tuple(use_value(use) for use in current_states),
            'pending_definition': original_pending, 'pending_constructor': pending,
            'pending_payload_use': original_pending.payload, 'pending_payload_occurrence': payload_use,
            'primary_pending_definition': original_pending, 'primary_pending_constructor': pending,
            'replacement_pending_definition': replacement,
            'replacement_pending_constructor': replacement_constructor,
            'selected_pending_definition': selected_pending,
            'selected_pending_constructor': selected_constructor,
            'dispatch': dispatch, 'cleanup_actions': tuple(caller_map[operation.id]
                for operation in cleanup['action_operations']),
            'implementation_frames': (), 'body_segments': (), 'body_drives': ()})

    model = ExecutionModel(snapshot_for(program), runs=(ExecutionRun(run, source),),
        processes=(ProcessInstance(process, run, 909, source),),
        threads=(HostThreadInstance(thread, process, 1010, source),),
        **{name: tuple(rows) for name, rows in combined.items()},
        call_activations=tuple(calls), body_drive_executions=(), body_activation_origins=())
    if missing_payload_use is not None:
        example = examples[missing_payload_use]
        model = replace(model, uses=tuple(row for row in model.uses
            if (row.operation, row.use) != (example['pending_constructor'], example['pending_payload_use'])))
    if missing_dispatch is not None:
        model = _omit_suffix(program, model, examples[missing_dispatch]['dispatch'])
    return program, model, {'static': static, 'instances': tuple(examples),
        'source': source, 'point': point, 'stage': stage, 'mode': mode,
        'missing_payload_use': missing_payload_use, 'missing_dispatch': missing_dispatch,
        'missing_helper_call': missing_helper_call}


__all__ = ['await_failure_cleanup_execution']
