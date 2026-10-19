"""Source-owned and expanded await failures on original control/result ports."""
from .await_outcome_flow import (answer, bind_target, consumers, flags, inventory,
    packet_use, result_legs, selected, state_links, terminal_inventory)
from .model import ExitKind, InvokeLiteralResult, TerminatorKind
from .protocol_await_records import AwaitAcquisition, ExpandedAwaitCallee
from .protocol_connections import ProtocolOperationRef
from .protocols import OwnedUse, ProtocolClause, ProtocolProfile, StaticProtocolGap
from .structured import ControlEdgeReference


def _ref(row):
    return ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)


def _seeds(ctx):
    """Original scope subjects survive deletion of all own RAISE rows."""
    seeds, seen, missing = [], set(), []
    for scope in ctx.graph.protocol_scopes:
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


def failure_paths(ctx):
    from .protocol_await import _result_copy
    seeds, preparation_gaps = _seeds(ctx)
    paths, issues, gaps, checked, cursor = [], [], list(preparation_gaps), 0, None
    for seed in seeds:
        path = {key: value for key, value in seed.items()
                if key not in ('source_row', 'own', 'parent_result', 'parent_edge')}
        local = []
        if not ctx.spend('await_failure_paths'):
            paths.append({**path, 'terminals': (), 'status': 'NOT_CHECKED', 'gaps': (), **flags()})
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
        endpoints, endpoint_gaps = (((), ('await_failure_anchor_missing',)) if anchor is None
                                   else terminal_inventory(ctx, anchor, whole_choices))
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
                        *(consumer['binding'] for consumer in receiver_views))
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
                'states': states, 'consumers': receiver_views,
                'status': 'CONTRADICTED' if any(binding['match'] is False for binding in bindings) else
                          'PARTIAL' if terminal_gaps or not raised or ctx.budget.truncated else 'DECLARED',
                'gaps': tuple(dict.fromkeys(terminal_gaps)), **flags()})
            gaps.extend(terminal_gaps)
        checked += int(not ctx.budget.truncated)
        local.extend(gap for terminal in terminals for gap in terminal['gaps'])
        paths.append({**path, 'terminals': tuple(terminals),
            'status': 'CONTRADICTED' if any(terminal['status'] == 'CONTRADICTED' for terminal in terminals) else
                      'PARTIAL' if local or ctx.budget.truncated or not terminals else 'DECLARED',
            'gaps': tuple(dict.fromkeys(local)), **flags()})
        gaps.extend(local)
        if ctx.budget.truncated:
            cursor = cursor or {'phase': 'await_failure_terminals', 'key': seed['key']}
    complete = not preparation_gaps and not ctx.budget.truncated
    return {'failure_paths': tuple(paths), 'failure_path_inventory': inventory(paths, checked, complete,
        cursor=cursor), 'issues': tuple(issues), 'gaps': tuple(gaps)}
