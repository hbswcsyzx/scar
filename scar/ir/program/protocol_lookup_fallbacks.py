"""Independent request sources and derived delegated-lookup packet routes.

The attachment names E0. EL and EM come from exact original own result ports;
the branch and its legs are derived, never an editable list of expected routes.
"""
from .exception_matches import BuiltinExceptionCategory, ExceptionHandlerOperand, FixedBuiltinHandler
from .model import ExitKind, InvokeLiteralResult, ProtocolValue, TerminatorKind
from .control import ProtocolValueKind
from .drivers import RawRequestKind
from .protocol_connections import (DelegateLookupFallback, InjectedPacketTrigger,
    NormalizedThrowSource, ProtocolOperationRef)
from .protocol_packet_routes import packet_continuations, packet_frontiers
from .protocols import (ContractResult, OwnedUse, ProtocolCall, ProtocolCallRule as CR,
    ProtocolProfile, StaticGapReason, StaticProtocolGap)
from .structured import ControlEdgeReference


_RULES = (CR.DELEGATE_THROW_LOOKUP, CR.DELEGATE_CLOSE_LOOKUP)


def _bindings(ctx):
    inventory = getattr(ctx, '_lookup_fallback_inventory', None)
    if inventory is None:
        by_site, rows = {}, []
        for binding in ctx.graph.protocol_bindings:
            if type(binding) is DelegateLookupFallback:
                rows.append(binding)
                by_site.setdefault(binding.lookup, {}).setdefault(binding.matcher, []).append(binding)
        inventory = tuple(rows), {site: {matcher: tuple(group) for matcher, group in groups.items()}
                                  for site, groups in by_site.items()}
        ctx._lookup_fallback_inventory = inventory
        ctx.preparation['lookup_fallback_binding_rows'] = len(rows)
        ctx.preparation['lookup_fallback_binding_sites'] = len(by_site)
    return inventory


def _site(row):
    return ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)


def _eligible(ctx, row):
    if row is None or type(row.contract) is not ProtocolCall or row.contract.rule not in _RULES:
        return False
    scope = ctx.scopes[row.scope]
    port = ctx.port(row.contract.result)
    return (scope.profile is ProtocolProfile.DELEGATION_SITE_V1 and port is not None
            and port.gap is None and port.phase == 'edge'
            and ctx.operations[row.operation].terminator.successors[port.edge].kind is ExitKind.RAISE)


def fallback_binding_issues(ctx):
    """Supplied rows outside the original lookup denominator cannot disappear."""
    issues = []
    for binding in _bindings(ctx)[0]:
        if not ctx.spend('lookup_fallback_binding_inventory'):
            break
        try:
            row = ctx.row(binding.lookup)
            eligible = _eligible(ctx, row)
            if ctx.budget.truncated:
                break
            if not eligible:
                raise ValueError('fallback must select the exact THROW/CLOSE lookup own RAISE')
            operation = ctx.operations.get(binding.matcher)
            if operation is None or ctx.region_of[operation.id] != ctx.region_of[row.operation]:
                raise ValueError('fallback matcher must exist in the lookup original region')
        except (KeyError, ValueError, TypeError) as exc:
            issues.append(('protocol_lookup_fallback_site', str(binding.lookup), str(exc)))
    return tuple(issues)


def _guard_inventory(ctx, row, bindings, issues, gaps):
    if len(bindings) == 1 and bindings[0].guard is None:
        return
    if any(binding.guard is None for binding in bindings):
        issues.append(('protocol_lookup_fallback_guard', str(_site(row)),
                       'multiple fallback cases require exact incoming guards'))
        return
    guards, targets = tuple(binding.guard for binding in bindings), []
    for guard in guards:
        try:
            ctx.selected_edges(guard)
            if ctx.region_of[guard.operation] != ctx.region_of[row.operation]:
                raise ValueError('guard belongs to another region')
            targets.append(ctx.operations[guard.operation].terminator.successors[guard.successor_index].block)
        except (KeyError, ValueError, TypeError) as exc:
            issues.append(('protocol_lookup_fallback_guard', str(_site(row)), str(exc)))
            return
    if len(set(targets)) != 1 or len(set(guards)) != len(guards):
        issues.append(('protocol_lookup_fallback_guard', str(_site(row)),
                       'fallback cases must enumerate distinct incoming edges of one merge'))
        return
    _, _, incoming, reached, _ = ctx._edges(ctx.region_of[row.operation])
    denominator = {(edge[0], edge[1]) for parent, edge in incoming[targets[0]] if parent in reached}
    declared = {(guard.operation, guard.successor_index) for guard in guards}
    if declared - denominator:
        issues.append(('protocol_lookup_fallback_guard', str(_site(row)), 'guard is not an applicable incoming edge'))
    if denominator - declared:
        gaps.append('lookup_fallback_case_missing')
    # Source availability below also has to hold with this guard before the
    # lookup. A later branch cannot retroactively select its request source.
    for guard in guards:
        operation = ctx.operations[guard.operation]
        if (ctx.block_of[operation.id] == ctx.block_of[row.operation]
                and ctx.positions[operation.id] >= ctx.positions[row.operation]):
            issues.append(('protocol_lookup_fallback_guard', str(_site(row)), 'fallback guard must precede lookup'))
        pending = [operation.terminator.successors[guard.successor_index].block]
        seen, reaches = set(), False
        while pending:
            if not ctx.spend('lookup_fallback_guard_positions'):
                gaps.append('lookup_fallback_guard_reachability_unresolved')
                break
            block_id = pending.pop()
            if block_id in seen:
                continue
            seen.add(block_id)
            block = ctx.blocks[block_id]
            if row.operation in block.operations:
                reaches = True
                break
            last = ctx.operations[block.operations[-1]]
            if last.id != guard.operation:
                pending.extend(edge.block for edge in getattr(last.terminator, 'successors', ()))
        if not reaches and not ctx.budget.truncated:
            issues.append(('protocol_lookup_fallback_guard', str(_site(row)),
                           'selected guard cannot reach the original lookup'))


def _continuation_cases(source, cases, truncated):
    """All compatible cases retain their own complete continuation result."""
    rows = tuple(item['continuation'] for item in cases)
    gaps = tuple(dict.fromkeys(gap for item in rows for gap in item['gaps']))
    complete = bool(rows) and all(item['known_inventory_complete'] for item in rows) and not truncated
    if not rows:
        gaps += ('lookup_fallback_continuation_case_missing',)
    if truncated:
        gaps += ('lookup_fallback_budget_exhausted',)
    contradicted = any(item['status'] == 'CONTRADICTED' for item in rows)
    result = {'source': source, 'known_inventory_complete': complete,
              'source_inventory_complete': False, 'frontier_only': False,
              'gaps': gaps, 'cursor': next((item['cursor'] for item in rows if item['cursor'] is not None),
                                         {'phase': 'lookup_fallback_continuation_cases'} if truncated else None),
              'status': 'CONTRADICTED' if contradicted else 'PARTIAL' if gaps or not complete
                        or any(item['status'] != 'DECLARED' for item in rows) else 'DECLARED',
              'source_runtime_verified': False, 'runtime_identity_verified': False,
              'native_applicability_verified': False, 'transformation_authorized': False}
    for field in ('targets', 'checks', 'actions', 'projections', 'suspensions',
                  'overrides', 'boundaries', 'helpers', 'conditions'):
        result[field] = tuple(value for row in rows for value in row[field])
    return result


def lookup_fallbacks(ctx, row, matches, issue, missing):
    """Preserve actual lookup/matcher consumers before optional binding rows."""
    site = _site(row)
    if row.contract.rule not in _RULES:
        return ()
    el = ContractResult(row.scope, row.clause, row.operation, row.slot, row.contract.result)
    supplied = _bindings(ctx)[1].get(site, {})
    actuals = {match['matcher'].operation: match['matcher'] for match in matches}
    actual_matchers = frozenset(actuals)
    # A deleted matcher attachment is still named by the immutable operation
    # and supplied source link; absence never becomes an empty success.
    for matcher in supplied:
        actuals.setdefault(matcher, ctx.index._exception_matches.get(matcher))
    if not actuals:
        missing('lookup_fallback_matcher_missing', site)
        return ()
    entries = []
    for identity, matcher in actuals.items():
        declarations = supplied.get(identity, ())
        group_issues, group_gaps = [], []
        if declarations:
            _guard_inventory(ctx, row, declarations, group_issues, group_gaps)
        else:
            group_gaps.append('lookup_fallback_binding_missing')
        for binding in declarations or (None,):
            entry = {'matcher': matcher, 'binding': binding, 'status': 'NOT_CHECKED',
                'paths': (), 'inputs': (), 'joint': (), 'issues': (), 'gaps': (),
                'source_runtime_verified': False, 'runtime_identity_verified': False,
                'native_applicability_verified': False, 'transformation_authorized': False}
            entries.append(entry)
            problems, gaps, reports, paths = list(group_issues), list(group_gaps), [], []
            input_jobs, receiver_cases = [], []
            if not ctx.spend('lookup_fallback_cases'):
                entry['gaps'] = ('lookup_fallback_budget_exhausted',)
                missing('lookup_fallback_budget_exhausted', site)
                continue
            if matcher is None:
                gaps.append('lookup_fallback_matcher_missing')
            elif identity not in actual_matchers:
                gaps.append('lookup_fallback_actual_consumer_unresolved')
            request = None if binding is None else binding.request
            e0 = StaticProtocolGap(StaticGapReason.NATIVE_APPLICABILITY_UNPROVEN)
            guard = None if binding is None else binding.guard
            try:
                selected = ctx.selected_edges((ControlEdgeReference(row.operation, row.slot),
                                               *((guard,) if guard is not None else ())))
            except (KeyError, ValueError, TypeError) as exc:
                problems.append(('protocol_lookup_fallback_guard', str(site), str(exc)))
                selected = (ControlEdgeReference(row.operation, row.slot),)
                guard = None
            if type(request) is NormalizedThrowSource:
                if row.contract.rule is not CR.DELEGATE_THROW_LOOKUP:
                    problems.append(('protocol_lookup_fallback_source', str(site), 'raw normalization source requires THROW'))
                from .protocol_validation import raw_definition
                raw_value = ctx.values[ctx.owned_use(request.raw.operation, request.raw.use).value]
                if (not isinstance(raw_value, ProtocolValue)
                        or raw_value.protocol is not ProtocolValueKind.RAW_DRIVER_REQUEST):
                    problems.append(('protocol_lookup_fallback_source', str(site),
                                     'raw anchor must be an actual RAW_DRIVER_REQUEST operand'))
                definition = raw_definition(ctx, request.raw)
                if definition is None:
                    gaps.append('lookup_fallback_raw_source_unresolved')
                elif definition.kind is not RawRequestKind.THROW or len(definition.operands) not in (1, 2, 3):
                    problems.append(('protocol_lookup_fallback_source', str(site), 'request must be an original THROW pack of one to three operands'))
                input_jobs.append(('available', request.raw, row.operation, ()))
                e0 = request.packet
                # Native normalization, traceback construction and body ingress
                # are not certified by a pair of supplied source identifiers.
                gaps.append('normalized_packet_source_unproved')
            elif type(request) is InjectedPacketTrigger:
                if row.contract.rule is not CR.DELEGATE_CLOSE_LOOKUP:
                    problems.append(('protocol_lookup_fallback_source', str(site), 'CLOSE injection cannot stand for a raw THROW normalization'))
                e0 = request.packet
                gaps.append('lookup_fallback_generator_exit_category_unproved')
            elif type(request) is StaticProtocolGap or request is None:
                gaps.append('lookup_fallback_injected_packet_source_missing')
            if type(e0) is StaticProtocolGap:
                gaps.append('lookup_fallback_packet_source_unresolved')
            if type(e0) is not StaticProtocolGap:
                port = ctx.port(e0)
                if port is None or port.gap is not None:
                    gaps.append('lookup_fallback_packet_source_unresolved')
                elif not port.values or any(not isinstance(ctx.values[value], ProtocolValue)
                    or ctx.values[value].protocol is not ProtocolValueKind.EXCEPTION_PACKET for value in port.values):
                    problems.append(('protocol_lookup_fallback_source', str(site), 'E0 requires an independent whole exception packet'))
                input_jobs.append(('available', e0, row.operation, ()))
            declaration = ctx.call_inputs.get(site)
            if declaration is None:
                gaps.append('lookup_fallback_receiver_source_missing')
            else:
                for case in declaration.cases:
                    if not ctx.spend('lookup_fallback_receiver_cases'):
                        gaps.append('lookup_fallback_budget_exhausted')
                        break
                    choices = (*selected, *((case.guard,) if case.guard is not None else ()))
                    if len({choice.operation for choice in choices}) != len({(choice.operation, choice.successor_index) for choice in choices}):
                        continue
                    receiver_cases.append((case, ctx.selected_edges(choices)))
            if matcher is not None:
                actual = OwnedUse(matcher.operation, matcher.input_use)
                lookup_input = ctx.bind(el, actual, choices=selected)
                if (lookup_input['match'] is False and binding is not None
                        and ctx.may_forwards(el, actual) is False):
                    problems.append(('protocol_lookup_fallback_site', str(site),
                                     'matcher consumes another lookup evaluation, not this exact own RAISE'))
                input_jobs.extend((('bind', el, actual, ()), ('bind', matcher.source, actual, ())))
                interpretation = matcher.handler.interpretation if type(matcher.handler) is ExceptionHandlerOperand else matcher.handler
                if type(interpretation) is not FixedBuiltinHandler:
                    gaps.append('lookup_fallback_handler_category_unproved')
                elif interpretation.category is not BuiltinExceptionCategory.ATTRIBUTE_ERROR and binding is not None:
                    problems.append(('protocol_lookup_fallback_category', str(site), 'missing-method fallback requires the declared AttributeError matcher'))
                if type(matcher.handler) is ExceptionHandlerOperand:
                    input_jobs.append(('bind', matcher.handler.source,
                                       OwnedUse(matcher.operation, matcher.handler.use), ()))
                gaps.append('lookup_fallback_native_category_unproved')
                own_normal = (() if not isinstance(matcher.normal_result, InvokeLiteralResult)
                              else (matcher.normal_result.edge,))
                if matcher.normal_result is not None:
                    branch = ctx.operations[matcher.branch]
                    input_jobs.append(('bind', matcher.normal_result,
                                       OwnedUse(branch.id, branch.terminator.condition), own_normal))
                    for number, kind, source in ((0, 'MATCH', e0), (1, 'NO_MATCH', el)):
                        edge = ControlEdgeReference(branch.id, number)
                        route = packet_frontiers(ctx, source,
                            start=(branch.terminator.successors[number].block, 0),
                            choices=ctx.selected_edges((*selected, *own_normal, edge)),
                            cuts=(row.operation, matcher.operation))
                        paths.append({'kind': kind, 'source': source, 'edge': edge,
                                      'route': route, 'continuation_cases': [],
                                      'continuation_start': (branch.terminator.successors[number].block, 0),
                                      'continuation_choices': (*own_normal, edge)})
                if matcher.raise_result is not None:
                    edge = matcher.raise_result.edge
                    operation = ctx.operations[matcher.operation]
                    route = packet_frontiers(ctx, matcher.raise_result,
                        start=(operation.terminator.successors[edge.successor_index].block, 0),
                        choices=ctx.selected_edges((*selected, edge)), cuts=(row.operation, matcher.operation))
                    paths.append({'kind': 'MATCHER_RAISE', 'source': matcher.raise_result, 'edge': edge,
                                  'route': route, 'continuation_cases': [],
                                  'continuation_start': (operation.terminator.successors[edge.successor_index].block, 0),
                                  'continuation_choices': (edge,)})
            # Cases are alternatives. Correlate the complete tuple inside each
            # selected case; joining mutually exclusive cases as one AND can
            # reject a sound caller/CFG inventory. Preserve every case below.
            input_cases, joint_routes = [], []
            if not receiver_cases:
                gaps.append('lookup_fallback_receiver_case_missing')
            for case, case_choices in receiver_cases or ((None, selected),):
                if not ctx.spend('lookup_fallback_input_tuples'):
                    gaps.append('lookup_fallback_budget_exhausted')
                    break
                case_reports = []
                if case is not None:
                    case_reports.append(ctx.bind(case.receiver,
                        OwnedUse(row.operation, row.contract.receiver_use), choices=case_choices))
                for kind, expected, actual, extra in input_jobs:
                    if not ctx.spend('lookup_fallback_input_roles'):
                        gaps.append('lookup_fallback_budget_exhausted')
                        break
                    choices = ctx.selected_edges((*case_choices, *extra))
                    case_reports.append(ctx.available(expected, actual, guard=choices) if kind == 'available'
                                        else ctx.bind(expected, actual, choices=choices))
                for report in case_reports:
                    if report['match'] is False:
                        problems.append(('protocol_lookup_fallback_source', str(site),
                                         'independent source is not current in this complete input case'))
                    elif report['match'] is None:
                        gaps.append('lookup_fallback_source_unresolved')
                joint = ctx.correlate(*case_reports)
                if joint['match'] is False:
                    problems.append(('protocol_lookup_fallback_source', str(site),
                                     'one fallback input tuple has incompatible caller/CFG contexts'))
                gaps.extend(joint['gaps'])
                reports.extend(case_reports)
                joint_routes.extend(joint['routes'])
                input_cases.append({'case': case, 'choices': case_choices,
                                    'inputs': tuple(case_reports), 'correlation': joint})
                for path in paths:
                    if not ctx.spend('lookup_fallback_continuation_cases'):
                        gaps.append('lookup_fallback_budget_exhausted')
                        break
                    choices = ctx.selected_edges((*case_choices, *path['continuation_choices']))
                    continuation = packet_continuations(ctx, path['source'],
                        start=path['continuation_start'], choices=choices,
                        cuts=(row.operation, matcher.operation))
                    path['continuation_cases'].append({'case': case, 'choices': choices,
                                                       'continuation': continuation})
            for path in paths:
                path['continuation_cases'] = tuple(path['continuation_cases'])
                path['continuation'] = _continuation_cases(path['source'],
                    path['continuation_cases'], ctx.budget.truncated)
                if (path['route']['status'] == 'CONTRADICTED'
                        or path['continuation']['status'] == 'CONTRADICTED'):
                    if binding is not None:
                        problems.append(('protocol_lookup_fallback_packet', str(site), 'fallback leg ' + path['kind'] + ' does not preserve its independent selected packet'))
                    else:
                        gaps.append('lookup_fallback_packet_route_unproved')
                # The old receipt remains frontier-only. Its later-C1 gap is
                # answered by the complete walk, not silently kept forever or
                # treated as an independent proof of a final consumer.
                gaps.extend(path['continuation']['gaps'])
            if ctx.budget.truncated:
                gaps.append('lookup_fallback_budget_exhausted')
            entry.update(status='CONTRADICTED' if problems else 'PARTIAL' if gaps else 'DECLARED',
                paths=tuple(paths), inputs=tuple(reports), joint=tuple(joint_routes),
                input_cases=tuple(input_cases),
                issues=tuple(problems), gaps=tuple(dict.fromkeys(gaps)))
            for code, path, message in problems:
                issue(code, path, message)
            for gap in entry['gaps']:
                missing(gap, site)
    return tuple(entries)


__all__ = ['lookup_fallbacks', 'fallback_binding_issues']
