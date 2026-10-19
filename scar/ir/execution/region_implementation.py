"""Exact captured expansion of a call's original implementation frames.

Static frames do not identify occurrences. Each descent needs this caller's
CallActivation, and each return needs that association's actual completion.
"""
from .await_outcome_evidence import locate, pair, target, choice
from .resumable_flow import value_for_use


def _joint(bindings):
    checks = tuple(row.get('match') for row in bindings)
    return {'match': False if False in checks else None if not checks or None in checks else True,
            'bindings': tuple(bindings), 'gaps': tuple(dict.fromkeys(
                gap for row in bindings for gap in row.get('gaps', ())))}


def _state(selected, gaps=(), bindings=()):
    if selected is False:
        return 'NOT_APPLICABLE'
    if selected is None or gaps or any(row.get('match') is not True for row in bindings):
        return 'PARTIAL'
    return 'DECLARED'


def _frames(ctx, definition, operation, shared):
    frames, indexed = [], {}
    for original in definition['frames']:
        admitted = shared.spend('region_occurrence_frames', len(original['key']) + 1,
                                path='region.frames')
        key, local = original['key'], []
        if not admitted:
            caller, reached = None, None
            local.append('region_occurrence_budget')
        elif len(key) == 1:
            caller, reached = operation, True if operation is not None else None
        else:
            parent = indexed.get(key[:-1])
            entry = None if parent is None else parent['entry']
            caller, reached = locate(ctx, entry, original['parent_call'], shared, entry=True) if admitted else (None, None)
        links = () if caller is None or not admitted else ctx.call_activations_by_caller.get(caller.id, ())
        call = ctx.resolved_call_activations[links[0]] if len(links) == 1 else None
        entry, completion = (None, None) if call is None else (call['entry'], call['completion'])
        inputs = []
        if reached is not False:
            if call is None:
                local.append('region_call_activation_unobserved')
            if entry is None:
                local.append('region_call_entry_unobserved')
            if completion is None:
                local.append('region_call_completion_unobserved')
        for row in () if call is None else call['inputs']:
            if not shared.spend('region_occurrence_inputs', path='region.inputs'):
                local.append('region_occurrence_budget')
                break
            binding = pair(ctx, row['actual_value'], row['formal'], shared)
            local.extend(binding['gaps'])
            if binding['match'] is not True:
                local.append('region_call_input_unproved')
            inputs.append({'ordinal': row['ordinal'], 'actual': row['actual'],
                'actual_value': row['actual_value'], 'formal': row['formal'], 'binding': binding})
        result = {'key': key, 'definition': original, 'call': call, 'caller': caller,
            'entry': entry, 'completion': completion, 'inputs': tuple(inputs),
            'selected': reached, 'status': _state(reached, local,
                tuple(row['binding'] for row in inputs)), 'gaps': tuple(local)}
        frames.append(result)
        indexed[key] = result
    return tuple(frames), indexed


def _path(ctx, definition, source, selected, indexed, operation, shared, input_support):
    from .await_links import _result, _use
    hops, local, value, checks = [], [], source, [definition['binding']]
    chosen = selected
    for original in definition['hops']:
        admitted = shared.spend('region_occurrence_return_hops', len(original['frame']) + 1,
                                path='region.return')
        if not admitted:
            local.append('region_occurrence_budget')
            chosen = None if chosen is not False else False
            break
        frame = indexed.get(original['frame'])
        call = None if frame is None else frame['call']
        completion = None if frame is None else frame['completion']
        if chosen is not False:
            if completion is not None and completion.operation != original['terminal'].operation:
                chosen = False
            elif completion is None:
                chosen = None
        terminal = completion if chosen is True else None
        use = _use(ctx, terminal, original['terminal'])
        terminal_value = value_for_use(ctx, use)
        caller = None if frame is None else frame['caller']
        parent_value = _result(ctx, caller, original['caller_result']) if chosen is True else None
        binding = pair(ctx, value, terminal_value, shared) if chosen is not False else {'match': None, 'gaps': ()}
        post = pair(ctx, terminal_value, parent_value, shared) if chosen is not False else {'match': None, 'gaps': ()}
        hop_gaps = []
        if chosen is not False:
            if call is None:
                hop_gaps.append('region_return_call_unobserved')
            if completion is None:
                hop_gaps.append('region_return_completion_unobserved')
            if use is None:
                hop_gaps.append('region_return_use_unobserved')
            if parent_value is None:
                hop_gaps.append('region_parent_result_unobserved')
            checks.extend((binding, post))
        hops.append({'definition': original, 'call': call, 'terminal': terminal,
            'use': use, 'source_value': value, 'terminal_value': terminal_value,
            'parent_value': parent_value, 'binding': binding, 'post_binding': post,
            'selected': chosen, 'status': _state(chosen, hop_gaps, (binding, post)),
            'gaps': tuple(hop_gaps)})
        local.extend(hop_gaps)
        value = parent_value
    targets = []
    for original in definition['targets']:
        if not shared.spend('region_occurrence_final_targets', path='region.targets'):
            local.append('region_occurrence_budget')
            break
        projected = target(ctx, original['target'], operation, value, shared) if chosen is True else {
            'definition': original['target'], 'selected': chosen, 'operation': None,
            'value': None, 'binding': {'match': None, 'gaps': ()},
            'status': _state(chosen, ('region_final_target_unobserved',)), 'gaps': ()}
        targets.append(projected)
        # An accurately unselected target is inventory, not an obligation of
        # this selected return. Unknown/missing targets still need evidence.
        if chosen is not False and projected['selected'] is not False:
            checks.append(projected['binding'])
    binding = _joint(checks)
    if shared.truncated and binding['match'] is not False:
        binding = {**binding, 'match': None,
                   'gaps': (*binding['gaps'], 'region_occurrence_budget')}
    contribution = _joint((input_support, binding))
    local.extend(binding['gaps'])
    return {'definition': definition, 'hops': tuple(hops), 'interface_value': value,
        'binding': binding, 'input_support': input_support, 'contribution': contribution,
        'targets': tuple(targets), 'selected': chosen,
        'status': _state(chosen, local, (binding,)), 'gaps': tuple(dict.fromkeys(local))}


def _outputs(ctx, definition, operation, indexed, witnesses, witness_matches, shared):
    """Only this root frame's captured completion covers an actual output.

    Static terminal inventory stays under definition. A captured different
    terminal is unselected; an absent completion never means unselected.
    """
    from .await_links import _result, _use
    root = indexed.get(definition['entry_frame'])
    completion = None if root is None else root['completion']
    outputs = []
    for original in definition['outputs']:
        admitted = shared.spend('region_occurrence_output_slots', path='region.outputs')
        selected = (None if operation is None or not admitted else
                    True if original['edge'] is None else choice(ctx, operation, original['edge']))
        value = _result(ctx, operation, original['source']) if selected is True else None
        terminals, local, active, matched = [], [], 0, 0
        for terminal in original['terminals']:
            checked = shared.spend('region_occurrence_output_terminals', path='region.outputs.terminals')
            chosen = (False if selected is False else None if not checked or selected is None
                      or completion is None else completion.operation == terminal['terminal'].operation)
            occurrence = completion if chosen is True else None
            use = _use(ctx, occurrence, terminal['terminal'])
            actual_value = value_for_use(ctx, use)
            key = original['source'], terminal['terminal']
            support = witnesses.get(key, ())
            paid = shared.spend('region_occurrence_output_witnesses', len(support) + 1,
                                 path='region.outputs.witnesses')
            support = tuple(support) if paid else ()
            match = (True if chosen is True and paid and value is not None
                     and use is not None and witness_matches.get(key, False) else None)
            gaps = []
            if chosen is not False:
                active += 1
                matched += int(match is True)
                if not checked or not paid:
                    gaps.append('region_occurrence_budget')
                if completion is None:
                    gaps.append('region_output_completion_unobserved')
                if use is None:
                    gaps.append('region_output_use_unobserved')
                if value is None:
                    gaps.append('region_output_value_unobserved')
                if match is not True:
                    gaps.append('region_output_contribution_unproved')
                local.extend(gaps)
            terminals.append({'definition': terminal, 'terminal': terminal['terminal'],
                'occurrence': occurrence, 'use': use, 'value': actual_value,
                'witnesses': support, 'match': match, 'selected': chosen,
                'status': _state(chosen, gaps), 'gaps': tuple(gaps)})
        if selected is not False and (not active or matched != active):
            local.append('region_output_contribution_unproved')
        if selected is not False and not original['enumeration_complete']:
            # A partial static terminal inventory cannot establish that all
            # relevant runtime branches have been represented in this view.
            local.append('region_output_static_inventory_unproved')
        if not admitted:
            local.append('region_occurrence_budget')
        outputs.append({'definition': original, 'source': original['source'],
            'type': original['type'], 'kind': original['kind'], 'slot': original['slot'],
            'edge': original['edge'], 'value': value, 'selected': selected,
            'terminals': tuple(terminals), 'status': _state(selected, local),
            'gaps': tuple(dict.fromkeys(local))})
    return tuple(outputs)


def region_implementation(ctx, definition, operation, source, shared):
    from .await_links import _flags, _result, _use
    if definition is None:
        return None
    frames, indexed = _frames(ctx, definition, operation, shared)
    stages, local, witnesses, witness_matches = [], [], {}, {}
    for original in definition['stages']:
        admitted = shared.spend('region_occurrence_stages', path='region.stages')
        frame = indexed.get(original['frame'])
        entry = None if frame is None else frame['entry']
        occurrence, reached = locate(ctx, entry, original['operation'], shared, entry=True) if admitted else (None, None)
        inputs, legs, gaps, related, supported = [], [], [], [], False
        for row in original['inputs']:
            if not shared.spend('region_occurrence_stage_inputs', path='region.stage.inputs'):
                gaps.append('region_occurrence_budget')
                break
            use = _use(ctx, occurrence, row['actual'])
            value = value_for_use(ctx, use)
            binding = (pair(ctx, source, value, shared) if row['may'] is not False
                       else None)
            if binding is not None:
                related.append(binding)
                supported = supported or binding['match'] is True
                gaps.extend(binding['gaps'])
            inputs.append({'definition': row, 'use': use, 'value': value, 'binding': binding})
        input_support = {'match': True if supported else None, 'bindings': tuple(related),
            'gaps': () if supported else ('region_stage_input_unproved',)}
        if reached is not False:
            gaps.extend(input_support['gaps'])
        for leg in original['legs']:
            checked = shared.spend('region_occurrence_legs', path='region.legs')
            selected = (False if reached is False else None if occurrence is None or not checked else
                        True if leg['edge'] is None else choice(ctx, occurrence, leg['edge']))
            results = []
            for row in leg['results']:
                if not shared.spend('region_occurrence_result_slots', path='region.results'):
                    selected = None if selected is not False else False
                value = _result(ctx, occurrence, row['source']) if selected is True else None
                projected = []
                for path in row['paths']:
                    if not shared.spend('region_occurrence_paths', path='region.paths'):
                        gaps.append('region_occurrence_budget')
                        break
                    result = _path(ctx, path, value, selected, indexed, operation, shared, input_support)
                    projected.append(result)
                    if not original['expanded'] and shared.spend('region_occurrence_witnesses',
                            path='region.witnesses'):
                        end = path['hops'][-1]
                        key = path['interface_result'], end['terminal']
                        witnesses.setdefault(key, []).append(result)
                        witness_matches[key] = (witness_matches.get(key, False) or
                            result['selected'] is True and result['contribution']['match'] is True)
                paths = tuple(projected)
                results.append({'definition': row, 'value': value, 'paths': paths})
            legs.append({'definition': leg, 'selected': selected, 'results': tuple(results)})
        if reached is not False and occurrence is None:
            gaps.append('region_stage_occurrence_unobserved')
        stages.append({'definition': original, 'occurrence': occurrence, 'inputs': tuple(inputs),
            'input_support': input_support, 'legs': tuple(legs),
            'selected': reached, 'status': _state(reached, gaps),
            'gaps': tuple(gaps)})
        local.extend(gaps)
    for frame in frames:
        if frame['status'] == 'PARTIAL':
            local.extend(frame['gaps'])
    outputs = _outputs(ctx, definition, operation, indexed, witnesses, witness_matches, shared)
    for output in outputs:
        if output['status'] == 'PARTIAL':
            local.extend(output['gaps'])
    # Native/effects uncertainty remains separate from local original-copy
    # witnesses. Bad optional contributors do not poison other good witnesses.
    local.extend(definition['gaps'])
    if shared.truncated:
        local.append('region_occurrence_budget')
    for stage in stages:
        for leg in stage['legs']:
            if leg['selected'] is None:
                local.append('region_completion_choice_unobserved')
    return {'definition': definition, 'frames': frames, 'stages': tuple(stages),
        'outputs': outputs, 'status': 'PARTIAL' if local else 'DECLARED',
        'gaps': tuple(dict.fromkeys(local)), **_flags()}
