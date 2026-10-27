"""Expand a declared call interface through its original implementation ports.

Input-copy and produced-result support are independent. Leaf contributions
are alternative witnesses; neither a repeated node nor a matching type grants
semantics, purity, identity or transformation authority.
"""
from collections import deque

from .copy_flow import flow, selected
from .copy_consumers import consumer_graph
from .model import (CompletionResult, ExitKind, InvokeLiteralResult, OperationResult)
from .operation_results import produced_slots, result_legs
from .protocols import OwnedUse
from .structured import ControlEdgeReference


def _flags():
    return dict(source_runtime_verified=False, runtime_identity_verified=False,
                value_identity_verified=False, transformation_authorized=False)


def _joint(bindings):
    checks = tuple(binding.get('match') for binding in bindings)
    return {'match': False if False in checks else None if not checks or None in checks else True,
            'bindings': tuple(bindings), 'gaps': tuple(dict.fromkeys(
                gap for binding in bindings for gap in binding.get('gaps', ()))), **_flags()}


def _source_inputs(ctx, inputs):
    """Alternative source-related arguments, not all parameters or state.

    A may-copy input admits a possible stage; it cannot make that stage an
    unconditional contributor. Conditional refinements remain unproved here.
    """
    if not ctx.spend('region_source_input_support', len(inputs) + 1):
        return {'match': None, 'gaps': ('region_source_input_budget',), **_flags()}
    related = tuple(row for row in inputs if row['may'] is not False)
    match = True if any(row['must'] is True for row in related) else None
    return {'match': match, 'inputs': related,
            'gaps': () if match is True else ('region_source_input_unproved',), **_flags()}


def _inputs(ctx, stage, uses, calls):
    if stage.id in calls:
        return calls[stage.id]['arguments']
    raw = ctx.index._operation_argument_templates[stage.id]
    if not ctx.spend('region_original_input_lookup', len(uses) + 1):
        return raw
    lookup = {row['actual'].use: row for row in uses}
    rows = []
    for original in raw:
        if not ctx.spend('region_original_inputs'):
            # Preserve full original arity without deriving an unpaid suffix.
            return raw
        member = lookup.get(original['actual'].use)
        rows.append(original if member is None else {**original,
            'may': member['may'], 'must': member['must'], 'binding': member['binding']})
    return tuple(rows)


def _parent_ports(ctx, call, kind, slot):
    term = call.terminator
    if term is None:
        if kind is ExitKind.NORMAL:
            yield OperationResult(call.id, slot), None
        return
    for number, edge in enumerate(term.successors):
        if not ctx.spend('region_return_edges'):
            return
        if edge.kind is not kind:
            continue
        for position, argument in enumerate(edge.arguments):
            if not ctx.spend('region_return_positions'):
                return
            if type(argument) is CompletionResult and argument.index == slot:
                yield InvokeLiteralResult(ControlEdgeReference(call.id, number), argument), position


def _targets(ctx, source, parent_legs):
    targets = []
    for leg in parent_legs:
        if source == leg['own_result']:
            for target, binding in zip(leg.get('targets', ()), leg.get('bindings', ())):
                if not ctx.spend('region_final_targets'):
                    return tuple(targets)
                targets.append({'target': target, 'binding': binding})
        for state in leg.get('states', ()):
            if not ctx.spend('region_final_state_targets'):
                return tuple(targets)
            if state['source'] == source:
                targets.append({'target': state['target'], 'binding': state['binding']})
    return tuple(targets)


def _paths(ctx, source, type_, frame, frames, entry_frame, choices, parent_legs, input_support):
    pending, paths = deque([(frame, source, (), choices)]), []
    while pending:
        key, current, hops, guards = pending.popleft()
        if not ctx.spend('region_result_paths', len(hops) + len(key) + 1):
            break
        definition = frames[key]
        parent_call = ctx.operations[definition['parent_call']]
        conditions = selected(ctx, guards, (current.edge,) if type(current) is InvokeLiteralResult else ())
        before = flow(ctx, current, conditions)
        for exit_ in ctx.regions[definition['region']].exits:
            if not ctx.spend('region_output_exit_kinds'):
                break
            for slot, expected_type in enumerate(exit_.types):
                if not ctx.spend('region_output_exit_slots'):
                    break
                if expected_type != type_:
                    continue  # Compatibility filter only, never copy evidence.
                for site in ctx.index._exit_ports[(definition['region'], exit_.name, slot)]:
                    if not ctx.spend('region_output_terminal_uses'):
                        break
                    if before is not None and site.operation not in before:
                        continue
                    actual = OwnedUse(site.operation, site.use.id)
                    copied = None if before is None else site.use.value in before[site.operation]
                    binding = {'match': copied, 'source': current, 'actual': actual,
                        'gaps': ('region_output_copy_unresolved',) if copied is None else (), **_flags()}
                    for target, position in _parent_ports(ctx, parent_call, exit_.kind, slot):
                        if not ctx.spend('region_return_path_copies', len(hops) + 1):
                            break
                        next_choices = selected(ctx, conditions,
                            (target.edge,) if type(target) is InvokeLiteralResult else ())
                        hop = {'frame': key, 'call': parent_call.id, 'source': current,
                            'terminal': actual, 'kind': exit_.kind, 'slot': slot,
                            'caller_result': target, 'landing_position': position,
                            'binding': binding, 'choices': next_choices}
                        path = (*hops, hop)
                        if key == entry_frame:
                            joined = _joint(tuple(row['binding'] for row in path))
                            paths.append({'hops': path, 'interface_result': target,
                                'binding': joined, 'input_support': input_support,
                                'contribution': _joint((input_support, joined)),
                                'targets': _targets(ctx, target, parent_legs),
                                'status': 'DECLARED' if joined['match'] is True else
                                          'CONTRADICTED' if joined['match'] is False else 'PARTIAL',
                                'gaps': joined['gaps']})
                        elif key[:-1] in frames:
                            pending.append((key[:-1], target, path, next_choices))
                    if ctx.budget.truncated:
                        break
                if ctx.budget.truncated:
                    break
            if ctx.budget.truncated:
                break
        if ctx.budget.truncated:
            break
    return tuple(paths)


def region_implementation(ctx, source, operation, choices=(), *, graph=None, parent_legs=()):
    """Same-context view used by semantic interfaces, without a new public IR."""
    if operation.callee is None:
        return None
    graph = consumer_graph(ctx, source, choices) if graph is None else graph
    entry_frame = (operation.id,)
    frames, stages, outputs, witnesses, witness_matches, gaps = [], [], [], {}, {}, []
    known = graph['inventory']['known_inventory_complete']
    proofs = graph['inventory']['proofs_complete']
    cursor = None
    # Preserve every original interface result key even on budget1. These raw
    # signature anchors are not callee-exit joins or completed proof inventory.
    for leg in result_legs(ctx, operation):
        for result in produced_slots(ctx, operation, leg):
            outputs.append({**result, 'kind': leg['kind'], 'edge': leg['edge'],
                'terminals': (), 'enumeration_complete': False,
                'status': 'NOT_CHECKED', 'gaps': ()})
    for frame in graph['frames']:
        if not ctx.spend('region_implementation_frame_checks', len(frame['key']) + 1):
            known = proofs = False
            break
        if frame['key'][:1] != entry_frame:
            continue
        if not ctx.spend('region_implementation_frames', len(frame['key']) + 1):
            known = proofs = False
            break
        frames.append(frame)
    by_key = {}
    for frame in frames:
        if not ctx.spend('region_implementation_frame_index', len(frame['key']) + 1):
            known = proofs = False
            break
        by_key[frame['key']] = frame
    for frame in frames:
        if frame['key'] not in by_key or not ctx.spend('region_implementation_call_index', len(frame['calls']) + 1):
            known = proofs = False
            break
        calls = {call['operation']: call for call in frame['calls']}
        groups = {}
        for consumer in frame['consumers']:
            if not ctx.spend('region_implementation_consumers'):
                break
            if consumer['role'] != 'EXIT':
                groups.setdefault(consumer['actual'].operation, []).append(consumer)
        for identity, uses in groups.items():
            if not ctx.spend('region_implementation_stages'):
                break
            stage = ctx.operations[identity]
            inputs = _inputs(ctx, stage, uses, calls)
            input_support = _source_inputs(ctx, inputs)
            legs = []
            for leg in result_legs(ctx, stage):
                results = []
                for result in produced_slots(ctx, stage, leg):
                    if not ctx.spend('region_implementation_result_slots'):
                        break
                    paths = _paths(ctx, result['source'], result['type'], frame['key'],
                                   by_key, entry_frame, choices, parent_legs, input_support)
                    results.append({**result, 'paths': paths})
                    if stage.callee is None:
                        for path in paths:
                            if not ctx.spend('region_implementation_witnesses'):
                                break
                            end = path['hops'][-1]
                            key = path['interface_result'], end['terminal']
                            witnesses.setdefault(key, []).append(path)
                            witness_matches[key] = (witness_matches.get(key, False)
                                                    or path['contribution']['match'] is True)
                            if path['contribution']['match'] is None:
                                proofs = False
                legs.append({**leg, 'results': tuple(results)})
                if ctx.budget.truncated:
                    break
            stages.append({'key': (frame['key'], identity), 'frame': frame['key'],
                'operation': identity, 'expanded': stage.callee is not None,
                'inputs': inputs, 'input_support': input_support, 'legs': tuple(legs)})
            if not stage.effects_complete:
                gaps.append('region_implementation_effects_unproved')
                known = False
            if ctx.budget.truncated:
                break
        if ctx.budget.truncated:
            break
    for output in outputs:
        if not ctx.spend('region_interface_output_slots'):
            break
        terminals, enumeration_complete, matches = [], True, 0
        for exit_ in ctx.regions[operation.callee].exits:
            if not ctx.spend('region_interface_output_exits'):
                enumeration_complete = False
                break
            if exit_.kind is not output['kind']:
                continue
            for site in ctx.index._exit_ports[(operation.callee, exit_.name, output['slot'])]:
                if not ctx.spend('region_interface_output_terminals'):
                    enumeration_complete = False
                    break
                actual = OwnedUse(site.operation, site.use.id)
                key = output['source'], actual
                raw_support = witnesses.get(key, ())
                if not ctx.spend('region_interface_output_witnesses', len(raw_support) + 1):
                    enumeration_complete = False
                    break
                support = tuple(raw_support)
                matched = True if witness_matches.get(key, False) else None
                matches += int(matched is True)
                terminals.append({'terminal': actual, 'witnesses': support, 'match': matched,
                    'status': 'DECLARED' if matched is True else 'PARTIAL',
                    'gaps': () if matched is True else ('region_output_contribution_unproved',)})
            if not enumeration_complete:
                break
        complete = enumeration_complete and bool(terminals) and matches == len(terminals)
        output.update(terminals=tuple(terminals), enumeration_complete=enumeration_complete,
                      status='DECLARED' if complete else 'PARTIAL',
                      gaps=() if complete else ('region_output_contribution_unproved',))
    if not known:
        gaps.append('region_implementation_inventory_unresolved')
    if entry_frame not in by_key:
        known = proofs = False
        gaps.append('region_implementation_entry_frame_unresolved')
    if ctx.budget.truncated:
        known = proofs = False
        gaps.append('region_implementation_budget')
        cursor = {'phase': 'region_implementation', 'operation': operation.id}
    if any(output['status'] != 'DECLARED' for output in outputs):
        proofs = False
        gaps.append('region_implementation_outputs_unproved')
    return {'operation': operation.id, 'callee': operation.callee, 'entry_frame': entry_frame,
        'frames': tuple(frames), 'stages': tuple(stages), 'outputs': tuple(outputs),
        'inventory': {'enumerated_frames': len(frames), 'checked_frames': len(frames),
            'frames_total': len(frames) if known else None, 'enumerated_stages': len(stages),
            'stages_total': len(stages) if known else None, 'enumerated_outputs': len(outputs),
            'outputs_total': len(outputs) if known else None, 'known_inventory_complete': known,
            'proofs_complete': proofs, 'cursor': cursor},
        'status': 'PARTIAL' if gaps else 'DECLARED', 'gaps': tuple(dict.fromkeys(gaps)),
        'cursor': cursor, **_flags()}
