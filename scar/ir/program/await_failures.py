"""Source-owned and expanded await failures on original control/result ports."""
from .await_outcome_flow import (answer, bind_target, consumers, flags, inventory,
    packet_use, result_legs, selected, state_links, terminal_inventory)
from .model import ExitKind, InvokeLiteralResult, TerminatorKind
from .protocol_await_records import AwaitAcquisition, ExpandedAwaitCallee
from .protocol_connections import ProtocolOperationRef
from .protocols import OwnedUse, ProtocolClause, ProtocolProfile, StaticProtocolGap
from .structured import ControlEdgeReference


def _caller_cleanup(ctx, source, choices, issues):
    """Current caller completion, without retyping the callee's incoming R."""
    from .completion_adapter_routes import continuation_rows, structured_region
    from .model import StateVersionValue
    if not structured_region(ctx, source):
        return None
    continuations, missing = continuation_rows(ctx, source, choices)
    terminals, gaps = [], list(missing)
    for row in continuations:
        for receipt in row['continuation']['terminals']:
            if not ctx.spend('await_failure_caller_terminals'):
                gaps.append('await_failure_caller_budget')
                break
            operation = ctx.operations[receipt['terminal'].operation]
            state_uses = []
            if ctx.spend('await_failure_caller_state_uses', len(operation.terminator.values) + 1):
                for ordinal, identity in enumerate(operation.terminator.values):
                    actual = OwnedUse(operation.id, identity)
                    value = ctx.values[ctx.owned_use(operation.id, identity).value]
                    if type(value) is StateVersionValue:
                        state_uses.append({'ordinal': ordinal, 'actual': actual,
                            'value': value, 'location': value.location})
            local = list(receipt['gaps'])
            if ctx.budget.truncated:
                local.append('await_failure_caller_state_budget')
            if receipt['binding']['match'] is False:
                issues.append(('protocol_await_failure_current_source', str(operation.id),
                    'caller terminal is not its current cleanup completion source'))
            terminals.append({**receipt, 'state_uses': tuple(state_uses),
                'requires_final_extraction': False,
                'status': 'CONTRADICTED' if receipt['binding']['match'] is False else
                    'PARTIAL' if local or ctx.budget.truncated else receipt['status'],
                'gaps': tuple(dict.fromkeys(local))})
            gaps.extend(local)
    if not terminals:
        gaps.append('await_failure_caller_terminal_unproved')
    if ctx.budget.truncated:
        gaps.append('await_failure_caller_budget')
    return {'caller_continuations': continuations, 'caller_terminals': tuple(terminals),
            'gaps': tuple(dict.fromkeys(gaps))}


def _ref(row):
    return ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)


def _seeds(ctx, scope_id=None):
    """Original scope subjects survive deletion of all own RAISE rows."""
    seeds, seen, missing = [], set(), []
    for scope in ctx.graph.protocol_scopes:
        if scope_id is not None and scope.id != scope_id:
            continue
        if scope.profile not in (ProtocolProfile.AWAIT_ACQUISITION_V1,
                                  ProtocolProfile.COROUTINE_WRAPPER_CONSTRUCTION_V1):
            continue
        operation = ctx.operations[scope.subject.operation]
        clause = (ProtocolClause.AWAIT_ACQUISITION
                  if scope.profile is ProtocolProfile.AWAIT_ACQUISITION_V1
                  else ProtocolClause.WRAPPER_CONSTRUCTION)
        rows = tuple(row for row in ctx.rows_by_clause.get((scope.id, clause), ())
                     if row.operation == operation.id)
        for parent in result_legs(ctx, operation):
            if parent['kind'] is not ExitKind.RAISE:
                continue
            own_row = next((row for row in rows if getattr(row.contract, 'result', None)
                            == parent['own_result']), None)
            common = {'scope': scope.id, 'source_operation': operation.id,
                'parent_result': parent['own_result'], 'parent_edge': parent['edge'],
                'acquisition': _ref(own_row) if own_row is not None
                    and type(own_row.contract) is AwaitAcquisition else None,
                'source_row': own_row}

            def append(stage_operation, edge, stage, choices, *, own=False):
                key = scope.id, operation.id, stage_operation, edge
                if key not in seen:
                    seen.add(key)
                    seeds.append({**common, 'key': key, 'stage_operation': stage_operation,
                        'edge': edge, 'stage': stage, 'choices': choices, 'own': own})

            append(operation.id, parent['edge'], 'ACQUISITION_RAISE'
                if clause is ProtocolClause.AWAIT_ACQUISITION else 'WRAPPER_CONSTRUCTION_RAISE', (), own=True)
            for row in rows:
                expansion = getattr(row.contract, 'expansion', None)
                if type(expansion) is not ExpandedAwaitCallee:
                    continue
                prefix = ()
                for ref, stage_kind in ((expansion.lookup, 'LOOKUP'),
                                        (expansion.call, 'METHOD_CALL'),
                                        (expansion.qualification, 'QUALIFICATION_RAISE')):
                    if type(ref) is StaticProtocolGap:
                        missing.append('await_failure_expansion_stage_missing')
                        break
                    local = ctx.row(ref)
                    stage_operation = ctx.operations[local.operation]
                    branch = getattr(local.contract, 'branch', None)
                    if branch is not None:
                        reject = ControlEdgeReference(branch, 1 if local.contract.accepts_true else 0)
                        append(branch, reject, 'QUALIFICATION_REJECT', prefix)
                        continue
                    for leg in result_legs(ctx, stage_operation):
                        if leg['kind'] is ExitKind.RAISE:
                            append(stage_operation.id, leg['edge'], stage_kind, prefix)
                    normal = tuple(leg for leg in result_legs(ctx, stage_operation)
                                   if leg['kind'] is ExitKind.NORMAL)
                    if len(normal) == 1 and normal[0]['edge'] is not None:
                        prefix = selected(ctx, prefix, normal[0]['edge'])
                    else:
                        missing.append('await_failure_normal_prefix_unresolved')
                        break
    ctx.preparation['await_original_failure_seeds'] = len(seeds)
    return tuple(seeds), tuple(dict.fromkeys(missing))


def failure_paths(ctx, *, scope=None, derive=True):
    from .protocol_await import _result_copy
    seeds, preparation_gaps = _seeds(ctx, scope)
    paths, issues, gaps, checked, cursor = [], [], list(preparation_gaps), 0, None
    for seed in seeds:
        path = {key: value for key, value in seed.items()
                if key not in ('source_row', 'own', 'parent_result', 'parent_edge')}
        path.update(source_result=seed['parent_result'], source_edge=seed['parent_edge'])
        local = []
        if not derive or not ctx.spend('await_failure_paths'):
            paths.append({**path, 'terminals': (), 'status': 'NOT_CHECKED',
                'gaps': ('await_static_details_deferred_without_capture',) if not derive else (), **flags()})
            if derive:
                cursor = cursor or {'phase': 'await_failure_paths', 'key': seed['key']}
            continue
        # A BRANCH supplies only an original control edge. Use its original
        # first landing formal as a traversal anchor, never a fake result.
        stage = ctx.operations[seed['stage_operation']]
        if stage.terminator.kind is TerminatorKind.BRANCH:
            landing = ctx.blocks[stage.terminator.successors[seed['edge'].successor_index].block]
            anchor = ctx.values[landing.arguments[0]].origin if landing.arguments else None
        else:
            anchor = next((leg['own_result'] for leg in result_legs(ctx, stage)
                           if leg['edge'] == seed['edge']), None)
        whole_choices = selected(ctx, seed['choices'], seed['edge'], seed['parent_edge'])
        caller = _caller_cleanup(ctx, seed['parent_result'], whole_choices, issues)
        endpoints, endpoint_gaps = (((), ()) if caller is not None and seed['own'] else
            ((), ('await_failure_anchor_missing',)) if anchor is None else
            terminal_inventory(ctx, anchor, whole_choices))
        if caller is not None:
            local.extend(caller['gaps'])
        local.extend(endpoint_gaps)
        if seed['source_row'] is None:
            local.append('await_failure_source_row_missing')
        receiver_ledger = consumers(ctx, seed['parent_result'], whole_choices)
        receipts = (None if seed['source_row'] is None else
                    ctx.result_consumers.get(_ref(seed['source_row'])))
        targets = list(receiver_ledger['targets'])
        if receipts is not None:
            targets.extend(target for target in receipts.targets
                           if type(target) is not StaticProtocolGap and target not in targets)
        receiver_views = tuple({'actual': target,
            'binding': bind_target(ctx, seed['parent_result'], target, whole_choices)} for target in targets)
        if receipts is None:
            local.append('protocol_result_consumers_missing')
        elif any(target not in receipts.targets for target in receiver_ledger['targets']):
            local.append('await_failure_consumer_receipt_incomplete')
        local.extend(receiver_ledger['gaps'])
        source_bindings = () if caller is None else tuple(view['binding'] for view in receiver_views)
        for binding in source_bindings:
            if binding['match'] is False:
                local.append('await_failure_source_consumer_contradicted')
                issues.append(('protocol_await_failure_source_consumer', str(seed['key']),
                    'original incoming failure does not reach its declared source consumer'))
            elif binding['match'] is None:
                local.append('await_failure_source_consumer_unproved')
        terminals = []
        for terminal in endpoints:
            if not ctx.spend('await_failure_terminals'):
                break
            packet = packet_use(ctx, terminal)
            raised = ctx.operations[terminal.operation].terminator.kind is TerminatorKind.RAISE
            report = (answer(False, gaps=('await_failure_whole_packet_missing',)) if packet is None else
                ctx.bind(seed['parent_result'], packet, guard=whole_choices) if seed['own'] else
                _result_copy(ctx, packet, seed['parent_result'], whole_choices))
            states = state_links(ctx, terminal, seed['parent_edge'], whole_choices, outward=seed['own'])
            terminal_gaps = list(local)
            bindings = (report, *(state['binding'] for state in states),
                        *(() if caller is not None else (consumer['binding'] for consumer in receiver_views)))
            stage_fields = {}
            if caller is not None and not seed['own']:
                stage_source = None if stage.terminator.kind is TerminatorKind.BRANCH else anchor
                stage_binding = None if stage_source is None else (
                    answer(gaps=('await_failure_stage_packet_missing',)) if packet is None else
                    ctx.bind(stage_source, packet, guard=whole_choices))
                origins = (None if stage_source is not None or packet is None else
                           ctx.origins(packet, guard=whole_choices))
                stage_fields = {'stage_source': stage_source, 'stage_binding': stage_binding,
                    'control_anchor': seed['edge'] if stage_source is None else None,
                    'stage_origins': origins}
                if stage_binding is not None:
                    bindings = (*bindings, stage_binding)
                elif origins is None or not origins['source_inventory_complete'] or not origins['recipes']:
                    terminal_gaps.append('await_failure_stage_origins_unproved')
            if not raised:
                terminal_gaps.append('await_failure_terminal_not_raise')
            for binding in bindings:
                if binding['match'] is None:
                    terminal_gaps.append('await_failure_binding_unproved')
                elif binding['match'] is False:
                    terminal_gaps.append('await_failure_binding_contradicted')
                    issues.append(('protocol_await_failure_copy', str(seed['key']),
                        'failure packet/state/consumer is not the same exact original completion'))
            terminals.append({'terminal': terminal, 'packet': packet, 'binding': report,
                'states': states, 'consumers': receiver_views, **stage_fields,
                'status': 'CONTRADICTED' if any(binding['match'] is False for binding in bindings) else
                          'PARTIAL' if terminal_gaps or not raised or ctx.budget.truncated else 'DECLARED',
                'gaps': tuple(dict.fromkeys(terminal_gaps)), **flags()})
            gaps.extend(terminal_gaps)
        checked += int(not ctx.budget.truncated)
        local.extend(gap for terminal in terminals for gap in terminal['gaps'])
        children = (*terminals, *(() if caller is None else caller['caller_terminals']))
        paths.append({**path, 'terminals': tuple(terminals), **({} if caller is None else {
                'caller_continuations': caller['caller_continuations'],
                'caller_terminals': caller['caller_terminals'], 'source_consumers': receiver_views}),
            'status': 'CONTRADICTED' if any(binding['match'] is False for binding in source_bindings)
                or any(terminal['status'] == 'CONTRADICTED' for terminal in children) else
                      'PARTIAL' if local or ctx.budget.truncated or not children else 'DECLARED',
            'gaps': tuple(dict.fromkeys(local)), **flags()})
        gaps.extend(local)
        if ctx.budget.truncated:
            cursor = cursor or {'phase': 'await_failure_terminals', 'key': seed['key']}
    complete = not preparation_gaps and not ctx.budget.truncated
    return {'failure_paths': tuple(paths), 'failure_path_inventory': inventory(paths, checked, complete,
        cursor=cursor), 'issues': tuple(issues), 'gaps': tuple(gaps)}
