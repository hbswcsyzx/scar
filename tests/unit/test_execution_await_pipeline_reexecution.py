"""One original await caller reevaluates its entire pipeline on a backedge.

Both selected rounds are supplied captures in one caller activation. Each
Create starts a new B; the first B is already closed before the second Create.
The child implementation completes NORMAL then RAISE. No object identity or
native execution fact is inferred from these declarations.
"""
from copy import deepcopy
from dataclasses import replace

import pytest

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.common import EvidencePoint, MissingEvidence, Unresolved
from scar.ir.execution.content import ObjectIdentity, ObjectRef, ValueDenotation
from scar.ir.execution.coordinates import (
    ControlTransfer, ExecutionRun, HostThreadInstance, InitialEntry,
    ProcessInstance, ResumeIngress, ValueOccurrence,
)
from scar.ir.execution.ids import (
    CallActivationID, DenotationID, HostThreadInstanceID, ProcessInstanceID,
    RegionActivationID, RunID,
)
from scar.ir.execution.model import ExecutionModel
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.resumables import BodyActivationOrigin, BodyDriveExecution
from scar.ir.execution.snapshot import external_artifact, snapshot_for
from scar.ir.execution.validation import validate
from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.cleanup import CleanupRouteTerminator
from scar.ir.program.control import PendingDispatchTerminator
from scar.ir.program.drivers import BodyDriveResult
from scar.ir.program.lifecycle import DriveOutcomeRef
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, DataValue,
    ExitKind, InvokeLiteralResult, Operation, OperationResult, ProtocolValue, StateAccess,
    StateVersionValue, Successor, Terminator, TerminatorKind, Use, UseRole,
)
from scar.ir.program.protocol_connections import ProtocolOperationRef, ProtocolResultConsumers
from scar.ir.program.protocol_await_records import AwaitBodyLink, CoroutineAwaitWrapper
from scar.ir.program.protocols import DriveResult, DriverSubject, HostTerminal, OutcomeAdapter, OwnedUse
from scar.ir.program.resumption import ResumableKind
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid
from scar.ir.v2.evidence import EvidenceEndpoint, EvidenceGraph, EvidenceNodeKind
from scar.ir.v2.ids import ObjectID
from tests.fixtures.execution_async_pipeline_graphs import _body_path
from tests.fixtures.execution_call_graphs import _activation
from tests.fixtures.program_async_pipeline_graphs import _selected_path
from tests.fixtures.program_await_final_region_graphs import await_final_region_program
from tests.fixtures.program_await_cleanup_final_graphs import (
    _BODY_TABLES, _PART_TABLES, _stage, await_cleanup_final_program,
)
from tests.fixtures.program_await_general_final_graphs import await_general_final_program
from tests.fixtures.program_await_raise_sources_graphs import _raising_body, await_raise_source_program
from tests.fixtures.program_await_wrapper_final_graphs import await_wrapper_final_program


_BUDGET = 4_194_304
_TABLES = ('activations', 'segments', 'visits', 'operations', 'values', 'uses', 'transfers')
_FLAGS = ('source_runtime_verified', 'runtime_identity_verified',
          'value_identity_verified', 'transformation_authorized')


def _use(name, value):
    role = (UseRole.STATE_CONTENT if type(value) is StateVersionValue else
            UseRole.PROTOCOL if type(value) is ProtocolValue else
            UseRole.DATA if type(value) is DataValue else UseRole.REFERENCE)
    return Use(UseID(name), value.id, role)


def _self_zero_raise_program():
    """Use the existing true zero-cut Raise body with self acquisition."""
    program, old = await_final_region_program(zero_cut=True, depth=1)
    body, capture_map, cuts, terminal_id = _raising_body(
        program, old, True, ResumableKind.GENERATOR_COROUTINE)
    assert not capture_map and cuts == ()
    part = _stage(body, 0, terminal_id, None)
    replaced_regions = {old['body'].id, old['drivers'][0]['driver_region'].id}
    replaced_operations = {identity for region in program.regions if region.id in replaced_regions
                           for block in region.blocks for identity in block.operations}
    replaced_values = {value.id for value in program.values if value.region in replaced_regions}
    replaced_scopes = {scope.id for scope in program.protocol_scopes
        if type(scope.subject) is DriverSubject and scope.subject.interface_region in replaced_regions}
    retained = {
        'protocol_scopes': tuple(scope for scope in program.protocol_scopes if scope.id not in replaced_scopes),
        'protocol_operations': tuple(row for row in program.protocol_operations if row.scope not in replaced_scopes),
        'exception_packets': tuple(row for row in program.exception_packets if row.value not in replaced_values),
        'literal_evaluations': tuple(row for row in program.literal_evaluations
            if getattr(row.site, 'operation', getattr(getattr(row.site, 'edge', None), 'operation', None))
                not in replaced_operations),
    }
    updates = {name: (*retained.get(name, ()), *getattr(body, name), *part[name])
               for name in _PART_TABLES}
    updates.update({name: getattr(body, name) for name in _BODY_TABLES})
    graph = replace(program,
        regions=tuple(region for region in program.regions if region.id not in replaced_regions)
            + body.regions + (replace(part['region'], parent=old['caller'].id),),
        operations=tuple(row for row in program.operations if row.id not in replaced_operations)
            + body.operations + part['operations'],
        values=tuple(row for row in program.values if row.region not in replaced_regions)
            + body.values + part['values'],
        control_scopes=tuple(row for row in program.control_scopes if row.region not in replaced_regions)
            + body.control_scopes + part['control_scopes'],
        protocol_result_consumers=tuple(row for row in program.protocol_result_consumers
            if row.site.scope not in replaced_scopes) + body.protocol_result_consumers,
        **updates)
    caller = old['caller']
    extract = old['extract']
    removed_regions = {region.id for region in old['stage_regions']}
    removed_blocks = {edge.block for edge in extract.terminator.successors}
    removed = {extract.id,
        *(identity for block in caller.blocks if block.id in removed_blocks for identity in block.operations),
        *(identity for region in graph.regions if region.id in removed_regions
          for block in region.blocks for identity in block.operations)}
    actuals = {use.id: use for use in extract.uses}
    uses = tuple(Use(UseID(f'await.pipeline.raise.consumer.{slot}'), actuals[identity].value,
        actuals[identity].role) for slot, identity in enumerate(extract.invoke_arguments))
    host = Operation(OperationID('await.pipeline.raise.consumer'), 'consume this actual BodyRaise packet',
        (Behavior.CONTROL,), uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.RAISE, exit='failure', values=tuple(use.id for use in uses)))
    caller = replace(caller, exits=tuple(port for port in caller.exits if port.kind is ExitKind.RAISE),
        blocks=tuple(replace(block, operations=(host.id,)) if extract.id in block.operations else block
                     for block in caller.blocks if block.id not in removed_blocks))
    graph = replace(graph,
        regions=tuple(caller if region.id == caller.id else region for region in graph.regions
                      if region.id not in removed_regions),
        operations=tuple(row for row in graph.operations if row.id not in removed) + (host,),
        values=tuple(row for row in graph.values if row.region not in removed_regions
            and not (type(row.origin) is BlockArgument and row.origin.block in removed_blocks)),
        control_scopes=tuple(replace(scope, blocks=tuple(block for block in scope.blocks
            if block not in removed_blocks)) if scope.region == caller.id else scope
            for scope in graph.control_scopes if scope.region not in removed_regions),
        protocol_operations=tuple(row for row in graph.protocol_operations if row.operation not in removed),
        protocol_result_consumers=tuple(replace(row, targets=(HostTerminal(host.id),))
            if row.site.operation == old['drivers'][-1]['caller_call'].id else row
            for row in graph.protocol_result_consumers if row.site.operation not in removed))
    driver = {**old['drivers'][0], 'driver_region': part['region'], 'drive': part['drive'],
        'outcome_source': terminal_id, 'path': part['path'], 'host_terminal': part['host']}
    choices = {next(block for block in old['caller'].blocks if block.id == identity).operations[-1]: edge
               for identity, edge in old['caller_path'] if edge is not None}
    choices.pop(extract.id)
    body_terminal = next(row for row in body.operations if row.id == terminal_id)
    outcome = DriveOutcomeRef(part['drive'].operation, terminal_id)
    return graph, {**old, 'caller': caller, 'caller_path': _selected_path(graph, caller, choices),
        'body': body.regions[0], 'drivers': (driver,), 'body_raised': True,
        'body_terminal': body_terminal, 'drive_outcome': outcome,
        'payload': DriveResult(outcome, 0), 'advance_operation': driver['caller_call'].id,
        'body_packet_use': OwnedUse(body_terminal.id, body_terminal.terminator.values[0]),
        'parent_call': driver['caller_call'], 'extract': None, 'extract_input': HostTerminal(host.id),
        'final': host, 'conversion': None, 'conversion_rows': (), 'final_rows': (),
        'stage_records': (), 'primitive': None, 'pending_definitions': ()}


def _pipeline_program(source_kind='self', zero_cut=True, body_raised=False):
    """Retain each source's actual body/driver graph inside one caller loop."""
    if source_kind not in ('self', 'general', 'wrapper'):
        raise ValueError('unknown original await source')
    if body_raised:
        if source_kind == 'self':
            base, original = (_self_zero_raise_program() if zero_cut else
                              await_cleanup_final_program(body_raised=True, depth=2))
        else:
            base, original = await_raise_source_program(source_kind, zero_cut)
    else:
        factory = {'self': await_final_region_program, 'general': await_general_final_program,
                   'wrapper': await_wrapper_final_program}[source_kind]
        base, original = factory(zero_cut=zero_cut, depth=2)
    caller = original['caller']
    blocks = {block.id: block for block in caller.blocks}
    values = {value.id: value for value in base.values}
    operations = {operation.id: operation for operation in base.operations}
    header = blocks[caller.entry]
    header_values = tuple(values[identity] for identity in header.arguments)
    additions = {name: [] for name in ('blocks', 'values', 'operations')}
    replacements, endings, base_paths = {}, {}, {}
    choices = {blocks[block].operations[-1]: selected
               for block, selected in original['caller_path'] if selected is not None}

    def formals(identity, templates):
        rows = tuple(replace(value, id=ValueID(f'{identity.value}.argument.{slot}'),
            region=caller.id, origin=BlockArgument(identity, slot))
            for slot, value in enumerate(templates))
        additions['values'].extend(rows)
        return rows

    prologue_id = BlockID('await.pipeline.prologue')
    prologue_values = formals(prologue_id, header_values)
    prologue_uses = tuple(_use(f'await.pipeline.enter.argument.{slot}', value)
                          for slot, value in enumerate(prologue_values))
    enter = Operation(OperationID('await.pipeline.enter'), 'enter the original pipeline header',
        (Behavior.CONTROL,), prologue_uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.JUMP,
            (Successor(header.id, tuple(use.id for use in prologue_uses)),)))
    additions['operations'].append(enter)
    additions['blocks'].append(Block(prologue_id, tuple(value.id for value in prologue_values),
                                    (enter.id,)))

    selected_endings = ((ExitKind.RAISE, original['caller_path'][-1][0], None),) if body_raised else tuple(
        (edge.kind, edge.block, number) for number, edge in enumerate(original['extract'].terminator.successors))
    for kind, landing_id, edge_number in selected_endings:
        base_paths[kind] = (original['caller_path'] if body_raised else
            _selected_path(base, caller, {**choices, original['extract'].id: edge_number}))
        landing = blocks[landing_id]
        terminal = operations[landing.operations[-1]]
        assert terminal.terminator.kind is (
            TerminatorKind.RETURN if kind is ExitKind.NORMAL else TerminatorKind.RAISE)
        produced = tuple(values[identity] for identity in landing.arguments)
        current_states = {value.location: value for value in produced
                          if type(value) is StateVersionValue}
        assert len(produced) == 3 and len(current_states) == 2
        suffix = kind.value.lower()
        exit_id = BlockID(f'await.pipeline.{suffix}.exit')
        exit_values = formals(exit_id, produced)
        mapping = {old.id: new.id for old, new in zip(produced, exit_values, strict=True)}
        moved = replace(terminal, uses=tuple(replace(use, value=mapping[use.value])
                                            for use in terminal.uses))
        replacements[moved.id] = moved
        additions['blocks'].append(Block(exit_id, tuple(value.id for value in exit_values),
                                        (moved.id,)))

        observe_id = OperationID(f'await.pipeline.{suffix}.observe')
        observed = tuple(_use(f'{observe_id.value}.slot.{slot}', value)
                         for slot, value in enumerate(produced))
        decision = DataValue(ValueID(f'await.pipeline.{suffix}.continue'), caller.id,
            OperationResult(observe_id, 0), 'builtins.bool')
        observer = Operation(observe_id, 'consume this completion and choose whether to reevaluate',
            (Behavior.READ, Behavior.COMPUTE), observed, (decision.id,),
            accesses=tuple(StateAccess(value.location, use.id, AccessMode.READ)
                for value, use in zip(produced, observed, strict=True)
                if type(value) is StateVersionValue), effects_complete=True)
        additions['values'].append(decision)
        additions['operations'].append(observer)

        # Every successor input owns its exact Use. The next iteration gets
        # external references and this completion's current state, never B/W.
        next_inputs = tuple(current_states[value.location]
            if type(value) is StateVersionValue else value for value in header_values)
        continuing = tuple(_use(f'await.pipeline.{suffix}.backedge.{slot}', value)
                           for slot, value in enumerate(next_inputs))
        exiting = tuple(_use(f'await.pipeline.{suffix}.exit.{slot}', value)
                        for slot, value in enumerate(produced))
        condition = _use(f'await.pipeline.{suffix}.condition', decision)
        branch = Operation(OperationID(f'await.pipeline.{suffix}.branch'),
            'reevaluate this same caller or complete its current result', (Behavior.CONTROL,),
            (condition, *continuing, *exiting), effects_complete=True,
            terminator=Terminator(TerminatorKind.BRANCH, (
                Successor(header.id, tuple(use.id for use in continuing)),
                Successor(exit_id, tuple(use.id for use in exiting)),
            ), condition=condition.id))
        additions['operations'].append(branch)
        blocks[landing.id] = replace(landing,
            operations=(*landing.operations[:-1], observer.id, branch.id))
        endings[kind] = {'landing': blocks[landing.id], 'observer': observer,
            'observer_uses': tuple(OwnedUse(observer.id, use.id) for use in observed),
            'branch': branch, 'backedge_uses': continuing, 'exit_uses': exiting,
            'exit': additions['blocks'][-1], 'exit_values': exit_values,
            'terminal': moved, 'current_values': produced}

    caller = replace(caller, entry=prologue_id,
        blocks=(*tuple(blocks[block.id] for block in caller.blocks), *additions['blocks']))
    final_rows = {row.slot: row for row in original['final_rows']}
    observers = {row.slot: endings[original['extract'].terminator.successors[row.slot].kind]
                 ['observer_uses'][0] for row in original['final_rows']}
    receipts = tuple(replace(receipt, targets=(*receipt.targets, observers[receipt.site.slot]))
        if original['extract'] is not None and receipt.site.operation == original['extract'].id
        and receipt.site.slot in final_rows
        else receipt for receipt in base.protocol_result_consumers)
    program = replace(base,
        regions=tuple(caller if region.id == caller.id else region for region in base.regions),
        operations=tuple(replacements.get(operation.id, operation) for operation in base.operations)
            + tuple(additions['operations']),
        values=(*base.values, *additions['values']),
        control_scopes=tuple(replace(scope, blocks=(*scope.blocks,
            *(block.id for block in additions['blocks']))) if scope.region == caller.id else scope
            for scope in base.control_scopes),
        protocol_result_consumers=receipts)
    kinds = (ExitKind.RAISE, ExitKind.RAISE) if body_raised else (ExitKind.NORMAL, ExitKind.RAISE)
    path, offsets = [(prologue_id, 0)], []
    for number, kind in enumerate(kinds):
        start = len(path)
        original_path = base_paths[kind]
        path.extend((*original_path[:-1], (original_path[-1][0], 0 if number == 0 else 1)))
        offsets.append((start, len(path)))
    path.append((endings[kinds[-1]]['exit'].id, None))
    return program, {**original, 'caller': caller, 'caller_path': tuple(path),
        'header': header, 'header_values': header_values, 'prologue': additions['blocks'][0],
        'enter': enter, 'endings': endings, 'round_offsets': tuple(offsets),
        'round_kinds': kinds, 'final': replacements[original['final'].id],
        'source_kind': source_kind, 'zero_cut': zero_cut, 'body_raised': body_raised}


def _pipeline_capture(source_kind='self', zero_cut=True, body_raised=False, missing=None):
    program, static = _pipeline_program(source_kind, zero_cut, body_raised)
    source = MissingEvidence('supplied two-round caller path; no native or runtime identity proof')
    run = RunID('await.pipeline.run')
    process = ProcessInstanceID('await.pipeline.process')
    thread = HostThreadInstanceID('await.pipeline.thread')
    point = EvidencePoint(run, process, source)
    combined = {name: [] for name in _TABLES}
    calls, origins, drives, examples, assignments = [], [], [], [], {}
    blocks = {block.id: block for region in program.regions for block in region.blocks}
    operations = {row.id: row for row in program.operations}

    def append(rows, *, activation=True):
        for name in _TABLES:
            if name != 'activations' or activation:
                combined[name].extend(rows[name])

    def denote(owner, definition, name):
        value, = tuple(row for row in combined['values']
                       if row.origin == owner and row.value == definition)
        previous = assignments.setdefault(value.id, name)
        assert previous == name

    def result_value(occurrence, slot):
        transfer, = tuple(row for row in combined['transfers'] if row.operation == occurrence)
        operation = operations[next(row.operation for row in combined['operations'] if row.id == occurrence)]
        edge = operation.terminator.successors[transfer.successor_index]
        formal, = tuple(formal for actual, formal in zip(edge.arguments, blocks[edge.block].arguments, strict=True)
            if type(actual) is CompletionResult and actual.index == slot)
        value, = tuple(row for row in combined['values'] if (row.origin, row.value) == (transfer.target, formal))
        return value

    caller_rows, caller_activation, caller_visits, _ = _activation(program,
        static['caller'].id, static['caller_path'], 'await.pipeline.caller', point, thread)
    append(caller_rows)
    occurrence_index = {(row.visit, row.operation): row.id for row in caller_rows['operations']}
    by_site = {}
    for row in caller_rows['operations']:
        by_site.setdefault(row.operation, []).append(row.id)
    by_site = {site: tuple(rows) for site, rows in by_site.items()}
    for number, (kind, (start, stop)) in enumerate(zip(static['round_kinds'],
            static['round_offsets'], strict=True)):
        prefix = f'await.pipeline.round.{number}'
        visits = caller_visits[start:stop]
        visit_set = set(visits)
        caller_map = {row.operation: row.id for row in caller_rows['operations']
                      if row.visit in visit_set}
        helper_scope, acquisition_call = None, None
        if source_kind == 'general':
            rows, activation, entered, mapping = _activation(program,
                static['helper'].id, static['helper_path'], prefix + '.acquisition', point, thread)
            append(rows)
            helper_scope = (activation, entered, mapping)
            acquisition_call = CallActivation(CallActivationID(prefix + '.acquisition.call'),
                caller_map[static['get'].id], activation, entered[0],
                mapping[static['helper_return'].id], source)
            calls.append(acquisition_call)
            creation = mapping[static['primary_creation'].operation]
        else:
            creation = caller_map[static['primary_creation'].operation]
        body_name, wrapper_name = prefix + '.B', prefix + '.W'
        if source_kind == 'wrapper':
            assignments[result_value(creation, 0).id] = body_name
            assignments[result_value(caller_map[static['decoy_creation'].operation], 0).id] = prefix + '.decoy'
            assignments[result_value(caller_map[static['constructor'].id], 0).id] = wrapper_name
            construction, = tuple(row for row in program.protocol_operations
                if row.operation == static['constructor'].id and row.slot == 0
                and type(row.contract) is CoroutineAwaitWrapper)
            body_operand, = tuple(row for row in combined['uses']
                if (row.operation, row.use) == (caller_map[static['constructor'].id], construction.contract.body_use))
            assignments[body_operand.value] = body_name

        wrapper_scopes, wrapper_calls, driver_scopes, driver_calls, body_drives = [], [], [], [], []
        for ordinal, definition in enumerate(static['drivers']):
            if source_kind == 'wrapper':
                wrapper = definition['wrapper']
                rows, activation, entered, mapping = _activation(program,
                    wrapper['region'].id, wrapper['path'], prefix + f'.wrapper.{ordinal}', point, thread)
                append(rows)
                wrapper_scopes.append((activation, entered, mapping))
                denote(entered[0], wrapper['entry'][0], wrapper_name)
                denote(mapping[wrapper['read'].id], wrapper['read_body'], body_name)
                selected_kind = ExitKind.RAISE if ordinal == len(static['drivers']) - 1 else ExitKind.NORMAL
                call = CallActivation(CallActivationID(prefix + f'.wrapper.call.{ordinal}'),
                    caller_map[definition['caller_call'].id], activation, entered[0],
                    mapping[wrapper['terminals'][selected_kind].id], source)
                wrapper_calls.append(call)
                calls.append(call)
                driver_caller = mapping[wrapper['inner_call'].id]
            else:
                driver_caller = caller_map[definition['caller_call'].id]
            rows, activation, entered, mapping = _activation(program,
                definition['driver_region'].id, definition['path'],
                prefix + f'.driver.{ordinal}', point, thread)
            append(rows)
            driver_scopes.append((activation, entered, mapping))
            call = CallActivation(CallActivationID(prefix + f'.driver.call.{ordinal}'),
                driver_caller, activation, entered[0],
                mapping[definition['host_terminal'].id], source)
            calls.append(call)
            driver_calls.append(call)
            if source_kind == 'wrapper':
                denote(entered[0], blocks[definition['driver_region'].entry].arguments[0], body_name)
                ingress = next(visit for visit in rows['visits']
                    if definition['drive'].operation in blocks[visit.block].operations)
                denote(ingress.id, blocks[ingress.block].arguments[0], body_name)

        body_activation = RegionActivationID(prefix + '.body')
        body_entries, body_segments, body_maps, body_visits, literal_ids = [], [], [], [], set()
        previous = None
        for ordinal, definition in enumerate(static['drivers']):
            if ordinal == 0:
                start, ingress = static['body'].entry, InitialEntry(point)
            else:
                target = definition['drive'].target
                prior = operations[static['drivers'][ordinal - 1]['outcome_source']]
                assert target.suspend == prior.id
                start = prior.terminator.successors[target.successor].block
                ingress = ResumeIngress(previous, target.successor, point)
            path = _body_path(program, static['body'], start, definition['outcome_source'])
            if body_raised and not zero_cut:
                ports = {row.id: row for row in program.control_ports}
                wanted = 'RAISE' if ordinal == 2 else 'RETURN'
                selected_port = next(row.port for row in static['pending_definitions']
                                     if ports[row.port].kind.value == wanted)
                path = tuple((block, next(number for number, edge in enumerate(term.successors)
                    if edge.port == selected_port)) if type(term := operations[blocks[block].operations[-1]].terminator)
                    in (CleanupRouteTerminator, PendingDispatchTerminator) else (block, selected)
                    for block, selected in path)
            rows, temporary, entered, mapping = _activation(program, static['body'].id,
                path, prefix + f'.body.segment.{ordinal}', point, thread)
            rows['activations'] = tuple(replace(row, id=body_activation) for row in rows['activations'])
            rows['segments'] = tuple(replace(row, activation=body_activation, ingress=ingress)
                                     for row in rows['segments'])
            actual_values = []
            for value in rows['values']:
                if value.origin == temporary:
                    if value.value in literal_ids:
                        continue
                    literal_ids.add(value.value)
                    value = replace(value, origin=body_activation)
                actual_values.append(value)
            rows['values'] = tuple(actual_values)
            append(rows, activation=ordinal == 0)
            if ordinal:
                combined['transfers'].append(ControlTransfer(previous, definition['drive'].target.successor, entered[0]))
            body_entries.append(entered[0])
            body_segments.append(rows['segments'][0].id)
            body_maps.append(mapping)
            body_visits.append(entered)
            actual_outcome = mapping[definition['outcome_source']]
            drive = BodyDriveExecution(driver_scopes[ordinal][2][definition['drive'].operation],
                body_activation, entered[0], actual_outcome, source)
            body_drives.append(drive)
            drives.append(drive)
            previous = actual_outcome
        origin = BodyActivationOrigin(body_activation, creation, source)
        origins.append(origin)
        if source_kind == 'wrapper':
            for slot, capture in enumerate(static['primary_creation'].captures):
                source_use, = tuple(row for row in combined['uses']
                    if (row.operation, row.use) == (creation, capture.source))
                assignments[source_use.value] = f'await.pipeline.external.capture.{slot}'
                denote(body_entries[0], capture.formal, f'await.pipeline.external.capture.{slot}')

        frames = []
        for ordinal, definition in enumerate(static['stage_records']):
            rows, activation, entered, mapping = _activation(program,
                definition['region'].id, definition['paths'][kind],
                prefix + f'.implementation.{ordinal}', point, thread)
            append(rows)
            frames.append({'definition': definition, 'activation': activation,
                'visits': entered, 'operations': mapping, 'entry': entered[0],
                'completion': mapping[definition['terminals'][kind].id]})
        root_call = None
        if not body_raised:
            root_call = CallActivation(CallActivationID(prefix + '.implementation.root'),
                caller_map[static['extract'].id], frames[0]['activation'], frames[0]['entry'],
                frames[0]['completion'], source)
            calls.append(root_call)
        nested_calls = []
        for ordinal, (parent, child) in enumerate(zip(frames, frames[1:])):
            call = CallActivation(CallActivationID(prefix + f'.implementation.child.{ordinal}'),
                parent['operations'][parent['definition']['operation'].id],
                child['activation'], child['entry'], child['completion'], source)
            calls.append(call)
            nested_calls.append(call)
        ending = static['endings'][kind]
        examples.append({'number': number, 'kind': kind, 'caller_activation': caller_activation,
            'caller_visits': visits, 'caller_operations': caller_map,
            'header_visit': visits[0], 'creation': creation,
            'decoy_creation': caller_map[(static['outer_creations'][0] if source_kind == 'general'
                                         else static['decoy_creation']).operation],
            'acquisition': caller_map[static['get'].id],
            'helper_scope': helper_scope, 'acquisition_call': acquisition_call,
            'wrapper_scopes': tuple(wrapper_scopes), 'wrapper_calls': tuple(wrapper_calls),
            'driver_scopes': tuple(driver_scopes), 'driver_calls': tuple(driver_calls),
            'advance': caller_map[static['advance_operation']], 'body_activation': body_activation,
            'body_origin': origin, 'body_entries': tuple(body_entries),
            'body_segments': tuple(body_segments), 'body_maps': tuple(body_maps),
            'body_visits': tuple(body_visits), 'body_drives': tuple(body_drives),
            'conversion': None if body_raised else driver_scopes[-1][2][static['conversion'].id],
            'extraction': None if root_call is None else root_call.caller, 'implementation_frames': tuple(frames),
            'implementation_root_call': root_call,
            'implementation_nested_calls': tuple(nested_calls),
            'observer': caller_map[ending['observer'].id],
            'branch': caller_map[ending['branch'].id], 'ending': ending})

    evidence_graphs, denotations = {}, ()
    if source_kind == 'wrapper':
        evidence = EvidenceGraph()
        for name in dict.fromkeys(assignments.values()):
            evidence.register_external(EvidenceEndpoint(EvidenceNodeKind.OBJECT, ObjectID(name)))
        artifact = external_artifact(evidence, 'memory:await-pipeline-loop-supplied-objects')
        evidence_graphs = {artifact.sha256: evidence}
        gap = Unresolved('supplied distinct wrapper/body identities; no native capture', point)
        denotations = tuple(ValueDenotation(DenotationID(identity.value), identity,
            ObjectIdentity(ObjectRef(artifact, ObjectID(name))), gap, source)
            for identity, name in assignments.items())
    model = ExecutionModel(snapshot_for(program), runs=(ExecutionRun(run, source),),
        processes=(ProcessInstance(process, run, 10, source),),
        threads=(HostThreadInstance(thread, process, 11, source),),
        **{name: tuple(rows) for name, rows in combined.items()},
        call_activations=tuple(calls), body_activation_origins=tuple(origins),
        body_drive_executions=tuple(drives), denotations=denotations)
    if missing is not None:
        second = examples[1]
        omitted_uses, omitted_calls, omitted_transfers = set(), set(), set()
        if missing == 'source-use':
            row, = tuple(row for row in static['get_rows'] if row.slot == 0)
            omitted_uses.add((second['acquisition'], row.contract.operand_use))
        elif missing == 'helper-call':
            omitted_calls.add(second['acquisition_call'].id)
        elif missing == 'inner-call':
            omitted_calls.add(second['driver_calls'][-1].id)
        elif missing == 'child-call':
            omitted_calls.add(second['implementation_nested_calls'][0].id)
        elif missing == 'observer-payload':
            omitted_uses.add((second['observer'], second['ending']['observer_uses'][0].use))
        elif missing == 'observer-state':
            omitted_uses.add((second['observer'], second['ending']['observer_uses'][1].use))
        elif missing == 'resume-transfer':
            omitted_transfers.add(second['body_drives'][0].outcome)
        elif missing == 'terminal-use':
            terminal = second['ending']['terminal']
            omitted_uses.add((by_site[terminal.id][0], terminal.terminator.values[0]))
        else:
            raise ValueError('unknown instance-local missing capture')
        model = replace(model,
            uses=tuple(row for row in model.uses if (row.operation, row.use) not in omitted_uses),
            call_activations=tuple(row for row in model.call_activations if row.id not in omitted_calls),
            transfers=tuple(row for row in model.transfers if row.operation not in omitted_transfers))
    return program, model, {'static': static, 'source': source,
        'caller_activation': caller_activation, 'caller_visits': caller_visits,
        'occurrence_index': occurrence_index, 'operations_by_site': by_site,
        'rounds': tuple(examples), 'final': by_site[static['endings'][ExitKind.RAISE]['terminal'].id][0],
        'evidence_graphs': evidence_graphs, 'missing': missing}


def _own_values(program, model, occurrence, operation):
    """Read each original full completion slot, not a landing ordinal guess."""
    transfer, = tuple(row for row in model.transfers if row.operation == occurrence)
    edge = operation.terminator.successors[transfer.successor_index]
    block = next(block for region in program.regions for block in region.blocks if block.id == edge.block)
    signature, = tuple(row for row in operation.completions if row.kind is edge.kind)
    produced = []
    for slot in range(len(signature.types)):
        formal, = tuple(formal for argument, formal in zip(edge.arguments, block.arguments, strict=True)
            if type(argument) is CompletionResult and argument.index == slot)
        actual, = tuple(row for row in model.values if (row.origin, row.value) == (transfer.target, formal))
        produced.append(actual)
    return transfer, tuple(produced)


def _consumer(report, static, example):
    actual, consumer = _one_selected_consumer(report, static, example)
    return actual, consumer


def _selected_outcomes(report, static, example):
    """Select an actual tuple after retaining every original input-case row."""
    return tuple((definition, occurrence) for definition in report['outcomes']
        if definition['definition']['source'] == static['source']
        and definition['definition']['advance_operation'] == static['advance_operation']
        and definition['definition']['drive_outcome'] == static['drive_outcome']
        for occurrence in definition['occurrences']
        if occurrence['advance'].id == example['advance']
        and occurrence['drive'] is not None
        and occurrence['drive'].id == example['body_drives'][-1].drive
        and occurrence['selected'] is True)


def _one_selected_consumer(report, static, example):
    pair, = tuple((actual, consumer) for _definition, actual in _selected_outcomes(report, static, example)
        for consumer in actual['consumers']
        if consumer['definition']['actual'] == static['extract_input']
        and consumer['definition']['requires_final_extraction'] is True
        and consumer['selected'] is True)
    return pair


def _assert_implementation(program, model, index, static, example, consumer):
    implementation = consumer['implementation']
    calls = (example['implementation_root_call'], *example['implementation_nested_calls'])
    assert tuple(frame['call']['association'] for frame in implementation['frames']) == calls
    assert tuple(frame['completion'].id for frame in implementation['frames']) == tuple(
        frame['completion'] for frame in example['implementation_frames'])
    leaf, = tuple(stage for stage in implementation['stages']
                  if stage['occurrence'].operation == static['primitive'].id)
    assert leaf['occurrence'].id == example['implementation_frames'][-1]['operations'][static['primitive'].id]
    assert leaf['input_support']['match'] is True
    selected, = tuple(leg for leg in leaf['legs'] if leg['definition']['kind'] is example['kind'])
    assert selected['selected'] is True
    assert {row['definition']['slot'] for row in selected['results']} == {0, 1, 2}
    uses = {(row.operation, row.use): row for row in model.uses}
    values = {row.id: row for row in model.values}
    observer_values = tuple(values[uses[(example['observer'], owned.use)].value]
                            for owned in example['ending']['observer_uses'])
    for result in selected['results']:
        slot = result['definition']['slot']
        assert type(result['value']) is ValueOccurrence
        assert result['value'].value == static['stage_records'][-1]['landing_values'][example['kind']][slot].id
        paths = tuple(path for path in result['paths'] if path['selected'] is True
            and path['binding']['match'] is True and path['contribution']['match'] is True)
        assert paths
        for path in paths:
            assert len(path['hops']) == static['depth']
            current = result['value']
            for hop, ordinal in zip(path['hops'], reversed(range(static['depth'])), strict=True):
                frame = example['implementation_frames'][ordinal]
                owned = frame['definition']['terminal_uses'][example['kind']][slot]
                assert hop['call']['association'] == calls[ordinal]
                assert hop['terminal'].id == frame['completion']
                assert hop['use'] == uses[(frame['completion'], owned.use)]
                assert hop['source_value'].id == current.id
                assert hop['terminal_value'].id == hop['use'].value
                assert hop['binding']['match'] is True and hop['post_binding']['match'] is True
                parent = static['extract'] if ordinal == 0 else static['stage_records'][ordinal - 1]['operation']
                _, outputs = _own_values(program, model, calls[ordinal].caller, parent)
                assert hop['parent_value'] == outputs[slot]
                current = hop['parent_value']
            assert path['interface_value'].id == current.id == observer_values[slot].id
            if slot == 0:
                target, = tuple(row for row in path['targets']
                    if row['operation'] is not None and row['operation'].id == example['observer'])
                assert target['selected'] is True and target['binding']['match'] is True
                assert target['use'] == uses[(example['observer'], example['ending']['observer_uses'][0].use)]
            if example['kind'] is ExitKind.NORMAL and slot == 0:
                assert path['status'] == 'PARTIAL' and path['gaps']
                assert all(getattr(gap, 'code', gap) == 'body_reference_identity_unproved'
                           for gap in path['gaps'])
            else:
                assert path['status'] == 'DECLARED' and path['gaps'] == ()
    for leg in leaf['legs']:
        if leg is not selected:
            assert leg['selected'] is False
            assert all(row['value'] is None for row in leg['results'])
    _, parent_outputs = _own_values(program, model, example['extraction'], static['extract'])
    assert observer_values == parent_outputs
    before = index.occurrence(example['observer'])['before']
    for value in observer_values[1:]:
        canonical = next(row for row in program.values if row.id == value.value)
        assert before[canonical.location] == value.id
    outputs = tuple(row for row in implementation['outputs'] if row['selected'] is True)
    assert {row['slot'] for row in outputs} == {0, 1, 2}
    for output in outputs:
        assert output['value'] == parent_outputs[output['slot']]
        terminal, = tuple(row for row in output['terminals'] if row['selected'] is True)
        assert terminal['occurrence'].id == example['implementation_frames'][0]['completion']
        assert terminal['match'] is True
        assert terminal['use'].value == terminal['value'].id
    assert all(implementation[flag] is False for flag in _FLAGS)


def test_same_caller_backedge_recreates_zero_cut_self_pipeline_and_uses_each_round_child_result():
    program, model, details = _pipeline_capture()
    require_valid(program)
    validation = validate(model, program)
    assert validation.valid, validation.issues
    index = ExecutionIndex(model, program)
    static = details['static']
    report = index.await_body_links(static['acquisition_scope'], budget=_BUDGET)
    assert not report['budget']['truncated']
    assert report['issues'] == ()
    rounds = details['rounds']
    caller_segments = tuple(row for row in model.segments if row.activation == details['caller_activation'])
    assert len(caller_segments) == 1 and type(caller_segments[0].ingress) is InitialEntry
    assert {example['caller_activation'] for example in rounds} == {details['caller_activation']}
    assert len({example['creation'] for example in rounds}) == 2
    assert len({example['body_activation'] for example in rounds}) == 2
    assert tuple(example['kind'] for example in rounds) == (ExitKind.NORMAL, ExitKind.RAISE)
    assert len(details['operations_by_site'][static['get'].id]) == 2
    assert len(details['operations_by_site'][static['primary_creation'].operation]) == 2
    assert len(details['operations_by_site'][static['extract'].id]) == 2
    assert tuple(row.id for row in model.operations if row.operation == static['conversion'].id) == tuple(
        example['conversion'] for example in rounds)
    assert not any(getattr(operation.terminator, 'kind', None) is TerminatorKind.SUSPEND
                   for operation in program.operations)
    for example in rounds:
        assert example['creation'] != example['decoy_creation']
        origin = index.body_activation_origin(example['body_activation'], budget=_BUDGET)
        assert origin['association'] == example['body_origin']
        assert example['body_origin'].creation == example['creation']
        association, = example['body_drives']
        drive = index.drive_execution(association.drive, budget=_BUDGET)
        assert drive['association'] == association
        assert drive['activation'].id == example['body_activation']
        assert drive['entry'].id == example['body_entries'][0]
        assert drive['outcome'].id == association.outcome
        assert len(example['body_segments']) == 1
        assert drive['instance']['creation_handle'] == origin['handle'] is not None
        assert origin['creation'].id == example['creation']
        body_segment, = tuple(row for row in model.segments if row.id == example['body_segments'][0])
        assert type(body_segment.ingress) is InitialEntry
        selected, = tuple(occurrence for job in report['jobs'] if job['source'] == static['source']
            for occurrence in job['occurrences'] if occurrence['advance'].id == example['advance']
            and occurrence['advance_selected'] is True and occurrence['case_selected'] is True)
        assert tuple(row['occurrence'].id for row in selected['matched_sources']) == (example['acquisition'],)
        route, = selected['routes']
        assert tuple(row['association'] for row in route['call_chain']) == example['driver_calls']
        assert route['drive_occurrence'].id == association.drive
        assert route['drive']['activation'].id == example['body_activation']
        actual, consumer = _consumer(report, static, example)
        assert actual['body_outcome'].id == association.outcome
        conversions = tuple(row for row in actual['conversion_legs'] if row['selected'] is True)
        assert conversions and all(row['occurrence'].id == example['conversion'] for row in conversions)
        assert consumer['operation'].id == example['extraction']
        assert consumer['binding']['match'] is True
        _assert_implementation(program, model, index, static, example, consumer)

    first, second = rounds
    transfers = {row.operation: row for row in model.transfers}
    backedge = transfers[first['branch']]
    assert backedge.successor_index == 0 and backedge.target == second['header_visit']
    assert transfers[second['branch']].successor_index == 1
    uses = {(row.operation, row.use): row for row in model.uses}
    header_values = tuple(row for row in model.values if row.origin == second['header_visit'])
    for canonical in static['header_values']:
        value, = tuple(row for row in header_values if row.value == canonical.id)
        route = index.formal_route(value.id)
        assert route.transfer == backedge
        if type(canonical) is StateVersionValue:
            owned, = tuple(owned for owned, current in zip(first['ending']['observer_uses'],
                first['ending']['current_values'], strict=True)
                if type(current) is StateVersionValue and current.location == canonical.location)
            assert route.source_use.value == uses[(first['observer'], owned.use)].value
    final = index.occurrence(details['final'])
    assert final['operation'].terminator.kind is TerminatorKind.RAISE
    _, current = _own_values(program, model, second['extraction'], static['extract'])
    for use, value in zip(final['uses'], current, strict=True):
        route = index.formal_route(use.value)
        assert route.transfer == transfers[second['branch']]
        assert route.source_use.value == value.id
    assert all(report[flag] is False for flag in _FLAGS)


def _index(program, model, details):
    require_valid(program)
    validation = validate(model, program, evidence_graphs=details['evidence_graphs'])
    assert validation.valid, validation.issues
    return ExecutionIndex(model, program, evidence_graphs=details['evidence_graphs'])


def _report(index, static, *, budget=_BUDGET):
    return index.await_body_links(static['acquisition_scope'], budget=budget)


def _observer_values(model, example):
    uses = {(row.operation, row.use): row for row in model.uses}
    values = {row.id: row for row in model.values}
    return tuple(values[uses[(example['observer'], owned.use)].value]
                 for owned in example['ending']['observer_uses'])


def _actual_outcome(report, static, example):
    (_definition, actual), = _selected_outcomes(report, static, example)
    return actual


def _selected_advances(report, static, example):
    return tuple(occurrence for job in report['jobs'] if job['source'] == static['source']
        for occurrence in job['occurrences'] if occurrence['advance'].id in {
            example['caller_operations'][item['caller_call'].id]
            for item in static['drivers'] if not item['direct']}
        and occurrence['advance_selected'] is True and occurrence['case_selected'] is True)


def _assert_raise(program, model, index, report, static, example):
    actual = _actual_outcome(report, static, example)
    assert actual['conversion_legs'] == ()
    assert actual['body_outcome'].id == example['body_drives'][-1].outcome
    assert example['implementation_frames'] == () and example['extraction'] is None
    if 'terminals' in actual:
        terminals = tuple(row for row in actual['terminals'] if row['selected'] is True)
        assert terminals
        for terminal in terminals:
            assert terminal['operation'].id == example['driver_calls'][-1].completion
            assert terminal['body_binding']['match'] is True
            assert terminal['root_binding']['match'] is True
            assert terminal['binding']['match'] is True
            assert terminal['packet_use'].value == terminal['packet_value'].id
            for state in terminal['states']:
                assert state['binding']['match'] is True
    else:
        # A primitive transparent D uses the original D5 advance-leg shape.
        # It has no synchronous cleanup-continuation terminal inventory.
        selected_definition, = tuple(definition for definition, occurrence
            in _selected_outcomes(report, static, example) if occurrence is actual)
        definition = selected_definition['definition']
        leg, = tuple(row for row in definition['advance_legs'] if row['kind'] is ExitKind.RAISE)
        assert leg['delivery_binding']['match'] is True
        assert leg['own_result'].edge.operation == static['advance_operation']

    uses = {(row.operation, row.use): row for row in model.uses}
    captured_operations = {row.id: row for row in model.operations}
    operations = {row.id: row for row in program.operations}
    body_terminal = operations[static['drivers'][-1]['outcome_source']]
    body_slots = tuple(uses[(actual['body_outcome'].id, identity)]
                       for identity in body_terminal.terminator.values)
    drive = index.drive_execution(actual['drive'].id, budget=_BUDGET)
    assert len(drive['outputs']) == len(body_slots) == 3
    for binding, source in zip(drive['outputs'], body_slots, strict=True):
        assert binding['source_occurrence'].id == actual['body_outcome'].id
        assert binding['source_use'] == source
        assert binding['source_value'].id == source.value
        formal_route = index.formal_route(binding['formal'].id)
        assert formal_route.transfer.operation == actual['drive'].id
        assert type(formal_route.argument) is BodyDriveResult
        assert formal_route.argument.index == body_slots.index(source)

    # Check every real D/(W) own packet and state result against the exact
    # selected callee terminal Use and the caller's full completion slot.
    chain = (example['driver_calls'][-1],) + (
        (example['wrapper_calls'][-1],) if static['source_kind'] == 'wrapper' else ())
    for association in chain:
        call = index.call_activation(association.id)
        terminal = operations[captured_operations[association.completion].operation]
        parent = operations[captured_operations[association.caller].operation]
        _, produced = _own_values(program, model, association.caller, parent)
        assert call['completion'].id == association.completion
        assert terminal.terminator.kind is TerminatorKind.RAISE
        assert len(call['outputs']) == len(produced) == 3
        before_terminal = index.occurrence(association.completion)['before']
        for slot, binding in enumerate(call['outputs']):
            assert binding['ordinal'] == slot
            assert binding['callee_use'] == uses[(association.completion, terminal.terminator.values[slot])]
            assert binding['caller_formal'] == produced[slot]
            assert binding['edge_argument'] == CompletionResult(slot)
            if slot:
                canonical = next(row for row in program.values if row.id == binding['callee_use_definition'].value)
                assert before_terminal[canonical.location] == binding['callee_use'].value
    observer_owned = example['ending']['observer_uses'][0]
    consumer, = tuple(row for row in actual['consumers']
        if row['definition']['actual'] == observer_owned and row['selected'] is True)
    assert consumer['operation'].id == example['observer']
    assert consumer['definition']['requires_final_extraction'] is False
    assert consumer['binding']['match'] is True
    assert consumer['implementation'] is None
    _, parent_outputs = _own_values(program, model, example['advance'], static['drivers'][-1]['caller_call'])
    observer_values = _observer_values(model, example)
    assert observer_values == parent_outputs
    assert body_terminal.terminator.kind is TerminatorKind.RAISE
    assert type(next(row for row in program.values if row.id == observer_values[0].value)) is ProtocolValue
    before = index.occurrence(example['observer'])['before']
    for value in observer_values[1:]:
        canonical = next(row for row in program.values if row.id == value.value)
        assert before[canonical.location] == value.id


def _assert_round(program, model, index, report, static, example):
    origin = index.body_activation_origin(example['body_activation'], budget=_BUDGET)
    assert origin['association'] == example['body_origin']
    assert origin['creation'].id == example['creation'] != example['decoy_creation']
    assert example['body_origin'].creation == example['creation']
    expected = 1 if static['zero_cut'] else 3
    assert len(example['body_segments']) == len(example['body_drives']) == expected
    assert len({drive.activation for drive in example['body_drives']}) == 1
    segments = {row.id: row for row in model.segments}
    for ordinal, (definition, association) in enumerate(zip(static['drivers'], example['body_drives'], strict=True)):
        drive = index.drive_execution(association.drive, budget=_BUDGET)
        assert drive['association'] == association
        assert drive['activation'].id == example['body_activation']
        assert drive['entry'].id == example['body_entries'][ordinal]
        assert drive['outcome'].id == association.outcome
        assert drive['instance']['creation_handle'] == origin['handle'] is not None
        segment = segments[example['body_segments'][ordinal]]
        assert segment.activation == example['body_activation']
        if ordinal:
            assert type(segment.ingress) is ResumeIngress
            assert segment.ingress.suspension == example['body_drives'][ordinal - 1].outcome
            transfer, = tuple(row for row in model.transfers if row.operation == segment.ingress.suspension)
            assert transfer.target == association.entry
            assert transfer.successor_index == definition['drive'].target.successor
        else:
            assert type(segment.ingress) is InitialEntry
        assert index.call_activation(example['driver_calls'][ordinal].id)['association'] == example['driver_calls'][ordinal]
    selected = _selected_advances(report, static, example)
    assert {row['advance'].id for row in selected} == {
        example['caller_operations'][item['caller_call'].id] for item in static['drivers'] if not item['direct']}
    for occurrence in selected:
        assert tuple(source['occurrence'].id for source in occurrence['matched_sources']) == (example['acquisition'],)
        ordinal, = tuple(number for number, item in enumerate(static['drivers'])
            if example['caller_operations'][item['caller_call'].id] == occurrence['advance'].id)
        route, = occurrence['routes']
        expected_calls = ((example['wrapper_calls'][ordinal], example['driver_calls'][ordinal])
            if static['source_kind'] == 'wrapper' else (example['driver_calls'][ordinal],))
        assert tuple(row['association'] for row in route['call_chain']) == expected_calls
        assert route['drive_occurrence'].id == example['body_drives'][ordinal].drive
        assert route['drive']['activation'].id == example['body_activation']
        if static['source_kind'] == 'wrapper':
            projection, = route['projections']
            assert projection['constructor'].id == example['acquisition']
            assert projection['distinctness']['status'] == 'DECLARED_DISTINCT_OBJECTS'
            held, = tuple(row for row in projection['bindings'] if row['role'] == 'native_held_body')
            assert held['original_copy'] is None and held['conditional_native_projection'] is True
    if static['source_kind'] == 'general':
        call = index.call_activation(example['acquisition_call'].id)
        assert call['association'] == example['acquisition_call']
        assert call['caller'].id == example['acquisition']
        assert call['activation'].id == example['helper_scope'][0]
        assert example['creation'] == example['helper_scope'][2][static['helper_create'].operation]
    if static['body_raised']:
        _assert_raise(program, model, index, report, static, example)
    else:
        actual, consumer = _consumer(report, static, example)
        assert actual['body_outcome'].id == example['body_drives'][-1].outcome
        conversions = tuple(row for row in actual['conversion_legs'] if row['selected'] is True)
        assert conversions and all(row['occurrence'].id == example['conversion'] for row in conversions)
        assert consumer['operation'].id == example['extraction'] and consumer['binding']['match'] is True
        _assert_implementation(program, model, index, static, example, consumer)


def _assert_loop(program, model, index, details):
    static, rounds = details['static'], details['rounds']
    segments = tuple(row for row in model.segments if row.activation == details['caller_activation'])
    assert len(segments) == 1 and type(segments[0].ingress) is InitialEntry
    assert {row['caller_activation'] for row in rounds} == {details['caller_activation']}
    assert len({row['creation'] for row in rounds}) == len({row['body_activation'] for row in rounds}) == 2
    assert tuple(row['kind'] for row in rounds) == static['round_kinds']
    assert len(details['operations_by_site'][static['get'].id]) == 2
    first, second = rounds
    transfers = {row.operation: row for row in model.transfers}
    backedge = transfers[first['branch']]
    assert backedge.successor_index == 0 and backedge.target == second['header_visit']
    assert transfers[second['branch']].successor_index == 1
    assert first['header_visit'] != second['header_visit']
    first_values = _observer_values(model, first)
    header_values = tuple(row for row in model.values if row.origin == second['header_visit'])
    for canonical in static['header_values']:
        value, = tuple(row for row in header_values if row.value == canonical.id)
        route = index.formal_route(value.id)
        assert route.transfer == backedge
        if type(canonical) is StateVersionValue:
            expected, = tuple(actual for template, actual in zip(first['ending']['current_values'], first_values, strict=True)
                if type(template) is StateVersionValue and template.location == canonical.location)
            assert route.source_use.value == expected.id
        else:
            source, = tuple(row for row in model.values
                            if (row.origin, row.value) == (first['header_visit'], canonical.id))
            assert route.source_use.value == source.id
    final = index.occurrence(details['final'])
    assert final['operation'] == second['ending']['terminal']
    assert final['operation'].terminator.kind is TerminatorKind.RAISE
    for use, value in zip(final['uses'], _observer_values(model, second), strict=True):
        route = index.formal_route(use.value)
        assert route.transfer == transfers[second['branch']]
        assert route.source_use.value == value.id


_OTHER_CORNERS = tuple((source, zero, raised) for source in ('self', 'general', 'wrapper')
    for zero in (True, False) for raised in (False, True)
    if (source, zero, raised) != ('self', True, False))


@pytest.mark.parametrize(('source_kind', 'zero_cut', 'body_raised'), _OTHER_CORNERS,
    ids=tuple(f'{source}-{"zero" if zero else "two"}-Body{"Raise" if raised else "Return"}'
              for source, zero, raised in _OTHER_CORNERS))
def test_two_round_pipeline_keeps_source_body_kind_fullslots_and_current_consumer(
        source_kind, zero_cut, body_raised):
    program, model, details = _pipeline_capture(source_kind, zero_cut, body_raised)
    index = _index(program, model, details)
    report = _report(index, details['static'])
    assert report['issues'] == () and not report['budget']['truncated']
    _assert_loop(program, model, index, details)
    for example in details['rounds']:
        _assert_round(program, model, index, report, details['static'], example)
    assert all(report[flag] is False for flag in _FLAGS)


_MISSING = (
    ('self', True, False, 'source-use'),
    ('general', True, False, 'helper-call'),
    ('wrapper', True, False, 'inner-call'),
    ('self', True, False, 'child-call'),
    ('general', True, True, 'observer-payload'),
    ('wrapper', True, False, 'observer-state'),
    ('wrapper', False, True, 'resume-transfer'),
    ('self', False, False, 'terminal-use'),
)


def _codes(rows):
    return {getattr(row, 'code', row) for row in rows}


def _job_keys(report):
    return {(row['scope'], row['source'], row['advance'], row['input_guard'], row['choices'])
            for row in report['jobs']}


@pytest.mark.parametrize(('source_kind', 'zero_cut', 'body_raised', 'missing'), _MISSING,
                         ids=tuple(row[-1] for row in _MISSING))
def test_second_round_missing_capture_never_borrows_the_complete_first_round(
        source_kind, zero_cut, body_raised, missing):
    program, model, details = _pipeline_capture(source_kind, zero_cut, body_raised, missing)
    index = _index(program, model, details)
    static = details['static']
    report = _report(index, static)
    first, second = details['rounds']
    assert first['caller_activation'] == second['caller_activation']
    assert first['body_activation'] != second['body_activation']
    _assert_round(program, model, index, report, static, first)
    assert report['status'] == 'PARTIAL'
    if missing in ('source-use', 'helper-call', 'inner-call'):
        selected = _selected_advances(report, static, second)
        assert selected
        assert all(row['status'] == 'PARTIAL' and row['gaps'] for row in selected)
        assert all(source['occurrence'].id != first['acquisition']
                   for row in selected for source in row['matched_sources'])
        codes = _codes(gap for row in selected for gap in row['gaps'])
        if missing == 'source-use':
            # The own result still identifies Get1. Its missing operand does
            # not erase that result or permit Get0 to supply the B input.
            for occurrence in selected:
                source, = occurrence['matched_sources']
                assert source['occurrence'].id == second['acquisition']
                assert source['body_input'] is None
                route, = occurrence['routes']
                projection, = route['projections']
                binding, = projection['bindings']
                assert binding['source_value'] == source['value']
                assert binding['formal'] == route['drive']['instance']['creation_handle']
                assert binding['original_copy'] is False
                assert binding['compatibility']['status'] == 'UNPROVED'
            assert 'body_reference_identity_unproved' in codes
            assert any(gap.code == 'use_unobserved' and gap.path == str(second['acquisition'])
                       for gap in index.report.gaps)
        elif missing == 'helper-call':
            assert 'await_general_body_source_occurrence_unproved' in codes
        else:
            assert 'await_drive_call_chain_missing' in codes
            assert all(row['routes'] == () for row in selected)
    elif missing == 'child-call':
        _, consumer = _consumer(report, static, second)
        implementation = consumer['implementation']
        assert implementation['status'] == 'PARTIAL'
        assert len(implementation['frames']) == 2
        assert implementation['frames'][0]['call']['association'] == second['implementation_root_call']
        assert implementation['frames'][1]['call'] is None
        assert 'region_call_activation_unobserved' in _codes(implementation['frames'][1]['gaps'])
    elif missing == 'resume-transfer':
        association = second['body_drives'][1]
        drive = index.drive_execution(association.drive, budget=_BUDGET)
        assert drive['association'] == association and drive['activation'].id == second['body_activation']
        assert drive['status'] == 'PARTIAL'
        assert 'body_resume_transfer_unobserved' in _codes(drive['gaps'])
        assert 'resume_transfer_unobserved' in _codes(index.report.gaps)
    elif missing == 'observer-state':
        current = index.occurrence(second['observer'])
        assert current['uses'][1] is None
        assert current['uses'][0] is not None and current['uses'][2] is not None
        assert index.occurrence(first['observer'])['uses'][1] is not None
        assert 'use_unobserved' in _codes(index.report.gaps)
    elif missing == 'observer-payload':
        actual = _actual_outcome(report, static, second)
        consumer, = tuple(row for row in actual['consumers']
            if row['definition']['actual'] == second['ending']['observer_uses'][0])
        assert consumer['selected'] is True and consumer['use'] is None
        assert consumer['binding']['match'] is None and consumer['status'] == 'PARTIAL'
        assert 'await_outcome_consumer_use_missing' in _codes(consumer['gaps'])
    else:
        _, consumer = _consumer(report, static, second)
        leg, = tuple(row for row in consumer['legs'] if row['definition']['kind'] is ExitKind.RAISE)
        terminal, = tuple(row for row in leg['targets'] if row['operation'] is not None
                          and row['operation'].id == details['final'])
        assert terminal['selected'] is True and terminal['use'] is None
        assert terminal['binding']['match'] is None and terminal['status'] == 'PARTIAL'
        assert 'await_outcome_consumer_use_missing' in _codes(terminal['gaps'])
    assert all(report[flag] is False for flag in _FLAGS)


def test_previous_round_create_is_a_core_rejected_body_origin_not_a_protocol_match():
    program, model, details = _pipeline_capture()
    _index(program, model, details)
    first, second = details['rounds']
    wrong = replace(model, body_activation_origins=tuple(
        replace(row, creation=first['creation']) if row.activation == second['body_activation'] else row
        for row in model.body_activation_origins))
    validation = validate(wrong, program)
    assert not validation.valid
    assert 'body_creation_reused' in _codes(validation.issues)
    with pytest.raises(ValueError, match='body_creation_reused'):
        ExecutionIndex(wrong, program)


@pytest.mark.parametrize('budget', (1, 128), ids=('one', 'middle'))
def test_shared_budget_retains_both_round_anchors_and_all_original_outcome_keys(budget):
    program, model, details = _pipeline_capture('general', False, False)
    complete = _report(_index(program, model, details), details['static'])
    limited = _report(_index(program, model, details), details['static'], budget=budget)
    assert limited['budget']['used'] <= budget
    assert limited['budget']['truncated'] is True and limited['cursor'] is not None
    assert limited['status'] == 'PARTIAL'
    assert complete['inventory']['known_inventory_complete'] is True
    assert limited['inventory']['known_inventory_complete'] is False
    assert limited['inventory']['original_anchors'] == complete['inventory']['original_anchors']
    assert limited['inventory']['source_count'] == complete['inventory']['source_count']
    # An unpaid case keeps an unchecked guard/choice placeholder. Compare the
    # raw source/advance/outcome anchors without dropping any case occurrence.
    def anchors(report):
        return {(row['definition']['source'], row['definition']['advance_operation'],
                 row['definition']['drive_outcome']) for row in report['outcomes']}
    assert anchors(limited) == anchors(complete)
    assert {(job['source'], job['advance']) for job in limited['jobs']} == {
        (job['source'], job['advance']) for job in complete['jobs']}
    for job in limited['jobs']:
        assert job['source_occurrence_count'] == 2
        assert job['checked_source_occurrence_count'] + job['pending_source_occurrence_count'] == 2
        if job['advance_operation'] is not None:
            expected = {example['caller_operations'][job['advance_operation']] for example in details['rounds']}
            assert job['occurrence_count'] == 2
            assert {row['advance'].id for row in job['occurrences']} == expected
    for definition in limited['outcomes']:
        assert definition['occurrence_count'] == 2
        assert definition['checked_occurrence_count'] + definition['pending_occurrence_count'] == 2
        assert {row['advance'].id for row in definition['occurrences']} == {
            example['caller_operations'][definition['definition']['advance_operation']]
            for example in details['rounds']}
    assert limited['outcome_inventory']['known_inventory_complete'] is False
    assert limited['outcome_inventory']['jobs_total'] is None
    assert limited['outcome_inventory']['pending_count'] is None
    assert all(limited[flag] is False for flag in _FLAGS)


def _source_pairs(report):
    return {(row['advance'].id, source['occurrence'].id) for job in report['jobs']
        for row in job['occurrences'] if row['advance_selected'] is True and row['case_selected'] is True
        for source in row['matched_sources']}


def test_detached_results_and_fresh_external_catalog_keep_each_round_source():
    program, model, details = _pipeline_capture('wrapper', False, False)
    original = deepcopy(model)
    index = _index(program, model, details)
    first = _report(index, details['static'])
    expected = _source_pairs(first)
    assert expected
    for job in first['jobs']:
        for row in job['occurrences']:
            row['matched_sources'] = ()
    first['outcomes'] = ()
    second = _report(index, details['static'])
    fresh = _report(_index(program, model,
        {**details, 'evidence_graphs': deepcopy(details['evidence_graphs'])}), details['static'])
    assert _source_pairs(second) == _source_pairs(fresh) == expected
    assert model == original
    for example in details['rounds']:
        _assert_round(program, model, index, second, details['static'], example)
    assert all(fresh[flag] is False for flag in _FLAGS)


def test_deleting_all_body_links_keeps_both_reexecuted_advances_and_outcome_denominators():
    program, model, details = _pipeline_capture()
    complete = _report(_index(program, model, details), details['static'])
    without = replace(program, protocol_bindings=tuple(row for row in program.protocol_bindings
                                                      if type(row) is not AwaitBodyLink))
    capture = replace(model, snapshot=snapshot_for(without))
    report = _report(_index(without, capture, details), details['static'])
    assert {row['key'] for row in report['outcomes']} == {row['key'] for row in complete['outcomes']}
    assert _job_keys(report) == _job_keys(complete)
    assert {row['advance'].id for job in report['jobs'] for row in job['occurrences']} == {
        example['advance'] for example in details['rounds']}
    assert report['status'] == 'PARTIAL'
    selected = tuple(row for job in report['jobs'] for row in job['occurrences']
                     if row['advance_selected'] is True and row['case_selected'] is True)
    assert selected and all('await_body_link_missing' in _codes(row['gaps']) for row in selected)
