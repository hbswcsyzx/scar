"""Bounded original-port connections for ordinary Python exception matching."""
from .control import ProtocolValueKind
from .exception_matches import ExceptionHandlerOperand, FixedBuiltinHandler
from .model import (AccessMode, Behavior, BlockArgument, CompletionResult, DataValue, ExitKind,
                    InvokeLiteralResult, OperationResult, ProtocolValue, ReferenceValue,
                    StateVersionValue, TerminatorKind)
from .protocols import OwnedUse
from .state_addresses import ExistingAccess, InvokeStateOperand
from .structured import ControlEdgeReference


def _role(ctx, value):
    row = ctx.values[value]
    if isinstance(row, ReferenceValue):
        return 'reference'
    if isinstance(row, ProtocolValue) and row.protocol is ProtocolValueKind.EXCEPTION_PACKET:
        return 'packet'
    return None


def _operand(ctx, operation, identity):
    actual = ctx.owned_use(operation.id, identity)
    if operation.terminator is not None and identity not in operation.invoke_arguments:
        raise ValueError('matcher input must be a real invocation operand, not edge forwarding')
    return actual


def _source_port(ctx, source):
    # Structural validation precedes prepared ConnectionContext construction.
    # Resolve this existing canonical formal without creating a new producer.
    if type(source) is BlockArgument:
        source.__post_init__()
        block = ctx.blocks.get(source.block)
        if block is None or source.index >= len(block.arguments):
            raise ValueError('matcher source formal does not exist')
        value = block.arguments[source.index]
        if ctx.values[value].origin != source:
            raise ValueError('matcher source must retain its original formal producer')
        from .protocol_flow import ProtocolPort
        return ProtocolPort(source, block.operations[0], (value,), 'before')
    return ctx.port(source)


def _own_port(ctx, matcher, source, kind):
    operation = ctx.operations[matcher.operation]
    if type(source) is OperationResult:
        if operation.terminator is not None or kind is not ExitKind.NORMAL:
            raise ValueError('ordinary result is not an INVOKE completion')
        producer = source.operation
    else:
        producer = source.edge.operation
        if (operation.terminator is None or operation.terminator.kind is not TerminatorKind.INVOKE
                or source.edge.successor_index >= len(operation.terminator.successors)
                or operation.terminator.successors[source.edge.successor_index].kind is not kind
                or type(source.result) is not CompletionResult):
            raise ValueError('matcher result must select its own exact completion kind and result slot')
    if producer != matcher.operation:
        raise ValueError('matcher completion must be produced by its own operation')
    port = ctx.port(source)
    if port is None or port.gap is not None:
        return port
    values = tuple(ctx.values[value] for value in port.values)
    if not values or (kind is ExitKind.NORMAL and not all(
            isinstance(value, DataValue) and value.data_type == 'builtins.bool' for value in values)) or (
            kind is ExitKind.RAISE and not all(isinstance(value, ProtocolValue)
            and value.protocol is ProtocolValueKind.EXCEPTION_PACKET for value in values)):
        raise ValueError('matcher NORMAL must be bool and RAISE must be its own exception packet')
    return port


def matcher_errors(ctx, matcher):
    """Structural attachment checks; source-copy queries run after core prep."""
    errors = []
    def issue(code, message):
        errors.append(('exception_match_' + code, str(matcher.operation), str(message)))
    operation = ctx.operations.get(matcher.operation)
    if operation is None:
        return (('exception_match_operation', str(matcher.operation), 'matcher operation does not exist'),)
    invoke = operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
    if (operation.callee is not None and not invoke) or (operation.terminator is not None and not invoke):
        issue('operation', 'matcher requires an ordinary primitive or original INVOKE')
        return tuple(errors)
    if not invoke and (not operation.effects_complete
            or not set(operation.behaviors).issubset({Behavior.COMPUTE, Behavior.READ, Behavior.CONTROL})
            or any(access.mode is not AccessMode.READ or access.after is not None for access in operation.accesses)):
        issue('effects', 'ordinary matcher is a declared callback-free read-only primitive')
    expected = ({edge.kind for edge in operation.terminator.successors} if invoke else {ExitKind.NORMAL})
    declared = {kind for kind, source in ((ExitKind.NORMAL, matcher.normal_result),
                 (ExitKind.RAISE, matcher.raise_result)) if source is not None}
    if declared != expected:
        issue('completions', 'matcher must retain every actual original NORMAL/RAISE completion')
    for kind, source in ((ExitKind.NORMAL, matcher.normal_result), (ExitKind.RAISE, matcher.raise_result)):
        if source is not None:
            try:
                _own_port(ctx, matcher, source, kind)
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                issue('result', exc)
    try:
        actual = _operand(ctx, operation, matcher.input_use)
        role = _role(ctx, actual.value)
        if role is None:
            issue('input', 'matcher input must be an original exception Reference or whole packet')
        port = _source_port(ctx, matcher.source)
        if port is not None and port.gap is None and any(_role(ctx, value) != role for value in port.values):
            issue('source', 'exception source and actual input must have compatible canonical roles')
    except (KeyError, TypeError, ValueError) as exc:
        issue('input', exc)
    if type(matcher.handler) is ExceptionHandlerOperand:
        try:
            handler = _operand(ctx, operation, matcher.handler.use)
            if not isinstance(ctx.values[handler.value], ReferenceValue) or matcher.handler.use == matcher.input_use:
                issue('handler', 'dynamic handler requires its own distinct original Reference operand')
            port = _source_port(ctx, matcher.handler.source)
            if port is not None and port.gap is None and any(
                    not isinstance(ctx.values[value], ReferenceValue) for value in port.values):
                issue('handler', 'independent handler source must be Reference-valued')
        except (KeyError, TypeError, ValueError) as exc:
            issue('handler', exc)
    required = {ExistingAccess(operation.id, index) for index in range(len(operation.accesses))}
    if invoke:
        required.update(InvokeStateOperand(operation.id, identity) for identity in operation.invoke_arguments
                        if isinstance(ctx.values[ctx.owned_use(operation.id, identity).value], StateVersionValue))
    if set(matcher.state_sites) != required:
        issue('state', 'matcher state sites must retain all and only its actual original accesses/state inputs')
    if matcher.normal_result is not None:
        branch = ctx.operations.get(matcher.branch)
        if (branch is None or branch.terminator is None or branch.terminator.kind is not TerminatorKind.BRANCH
                or ctx.region_of[branch.id] != ctx.region_of[operation.id]):
            issue('branch', 'matcher bool must feed a real BRANCH in its original region')
    return tuple(errors)


def exception_match_errors(graph, *, context=None):
    if not graph.exception_matches:
        return ()
    from .protocol_flow import ProtocolFlow
    ctx = ProtocolFlow(graph) if context is None else context
    return tuple(error for matcher in graph.exception_matches for error in matcher_errors(ctx, matcher))


def matcher_view(ctx, matcher):
    """Supply-model evidence; category declarations never prove native identity."""
    cache = getattr(ctx, '_exception_match_views', None)
    if cache is None:
        cache = ctx._exception_match_views = {}
    if matcher.operation in cache:
        return cache[matcher.operation]
    operation = ctx.operations[matcher.operation]
    issues, gaps, inputs, state_support = [], [], [], []
    normal = None if matcher.normal_result is None else {'result': matcher.normal_result, 'port': None, 'consumers': None}
    raised = None if matcher.raise_result is None else {'result': matcher.raise_result, 'port': None, 'consumers': None}
    result = {'matcher': matcher, 'status': 'NOT_CHECKED', 'inputs': (), 'joint': (),
        'bool_binding': None, 'normal': normal, 'raised': raised, 'branches': (),
        'state_support': (), 'gaps': (), 'issues': (), 'cursor': None,
        'source_runtime_verified': False, 'runtime_identity_verified': False,
        'native_applicability_verified': False, 'transformation_authorized': False,
        'conditions': ('supplied-model exception matching only; source/native interpretation unproved',)}
    if not ctx.spend('exception_match_sites'):
        return {**result, 'gaps': ('exception_match_budget_exhausted',),
                'cursor': {'phase': 'exception_match', 'operation': matcher.operation}}
    pairs = [(matcher.source, OwnedUse(matcher.operation, matcher.input_use), 'source')]
    interpretation = matcher.handler
    if type(matcher.handler) is ExceptionHandlerOperand:
        pairs.append((matcher.handler.source, OwnedUse(matcher.operation, matcher.handler.use), 'handler'))
        interpretation = matcher.handler.interpretation
    for expected, actual, role in pairs:
        report = ctx.bind(expected, actual)
        inputs.append(report)
        if report['match'] is False:
            issues.append(('exception_match_' + role, str(matcher.operation),
                           'actual matcher operand is not its independently declared current source'))
        elif report['match'] is None:
            gaps.append('exception_match_' + role + '_unresolved')
    joint = ctx.correlate(*inputs)
    gaps.extend(joint['gaps'])
    if joint['match'] is False and all(item['match'] is True for item in inputs):
        issues.append(('exception_match_context', str(matcher.operation), 'matcher input tuple has incompatible contexts'))
    if type(interpretation) is not FixedBuiltinHandler:
        gaps.append('exception_match_handler_category_unproved')
    else:
        # A fact locator is still only a declaration until replayed against
        # the source/runtime. Preserve explicit StaticProtocolGap as well.
        gaps.append('exception_match_builtin_applicability_unproved')
    result['category'] = interpretation.category if type(interpretation) is FixedBuiltinHandler else None
    result['handler_interpretation'] = interpretation
    bool_binding = None
    if normal is not None:
        normal['port'] = ctx.port(matcher.normal_result)
        branch = ctx.operations[matcher.branch]
        bool_binding = ctx.bind(matcher.normal_result, OwnedUse(branch.id, branch.terminator.condition))
        if bool_binding['match'] is False:
            issues.append(('exception_match_bool_source', str(matcher.operation), 'branch does not consume this matcher NORMAL bool'))
        elif bool_binding['match'] is None:
            gaps.append('exception_match_bool_source_unresolved')
        result['branches'] = tuple({'edge': ControlEdgeReference(branch.id, index),
            'truth': index == 0, 'successor': successor} for index, successor in enumerate(branch.terminator.successors))
    if raised is not None:
        raised['port'] = ctx.port(matcher.raise_result)
    for site in matcher.state_sites:
        if not ctx.spend('exception_match_state_sites'):
            gaps.append('exception_match_budget_exhausted')
            break
        if type(site) is ExistingAccess:
            access = operation.accesses[site.index]
            state_support.append({'site': site, 'before': OwnedUse(operation.id, access.before),
                                  'access': access, 'after': access.after})
        else:
            use = ctx.owned_use(operation.id, site.state_use)
            location = ctx.values[use.value].location
            completions = []
            for number, edge in enumerate(operation.terminator.successors):
                if not ctx.spend('exception_match_state_edges'):
                    break
                for argument, formal in zip(edge.arguments, ctx.blocks[edge.block].arguments):
                    if not ctx.spend('exception_match_state_slots'):
                        break
                    if isinstance(ctx.values[formal], StateVersionValue) and ctx.values[formal].location == location:
                        produced = (InvokeLiteralResult(ControlEdgeReference(operation.id, number), argument)
                                    if type(argument) is CompletionResult else None)
                        completions.append({'edge': ControlEdgeReference(operation.id, number),
                            'kind': edge.kind, 'formal': formal, 'argument': argument,
                            'result': produced, 'source': produced if produced is not None else
                                OwnedUse(operation.id, argument)})
            state_support.append({'site': site, 'before': OwnedUse(operation.id, site.state_use),
                                  'location': location, 'completions': tuple(completions)})
    from .protocol_connection_validation import consumer_ledger
    for kind, completion in ((ExitKind.NORMAL, normal), (ExitKind.RAISE, raised)):
        if completion is None:
            continue
        completion['consumers'] = consumer_ledger(ctx, source=completion['result'],
            site=(matcher.operation, kind), source_operation=matcher.operation)
        gaps.extend(completion['consumers']['gaps'])
    if ctx.budget.truncated:
        gaps.append('exception_match_budget_exhausted')
    result.update(status='REJECTED' if issues else 'PARTIAL' if gaps else 'DECLARED',
        inputs=tuple(inputs), joint=joint['routes'], correlation=joint, bool_binding=bool_binding,
        state_support=tuple(state_support), gaps=tuple(gaps), issues=tuple(issues),
        cursor={'phase': 'exception_match', 'operation': matcher.operation} if ctx.budget.truncated else None)
    cache[matcher.operation] = result
    return result


def exception_match_reports(ctx):
    rows, cursor = [], None
    total = len(ctx.graph.exception_matches)
    for number, matcher in enumerate(ctx.graph.exception_matches):
        if not ctx.spend('exception_match_inventory'):
            cursor = {'phase': 'exception_matches', 'next_index': number, 'total': total}
            break
        rows.append(matcher_view(ctx, matcher))
        if ctx.budget.truncated:
            cursor = {'phase': 'exception_matches', 'next_index': number + 1, 'total': total,
                      'partial_operation': matcher.operation}
            break
    return {'obligations': tuple(rows), 'issues': tuple(issue for row in rows for issue in row['issues']),
            'gaps': (*tuple(gap for row in rows for gap in row['gaps']),
                     *(('exception_match_inventory_incomplete',) if cursor is not None else ())),
            'supplied_matcher_count': total, 'unexamined_matcher_count': total - len(rows),
            'known_inventory_complete': cursor is None,
            'cursor': cursor,
            'source_runtime_verified': False, 'transformation_authorized': False}


def exception_match(index, operation, *, budget=4096):
    from scar.ir.execution.validity_budget import ValidityBudget
    from .ids import OperationID
    from .protocol_connection_flow import ConnectionContext
    if type(operation) is not OperationID:
        raise TypeError('exception matcher query requires exact original OperationID')
    matcher = index._exception_matches.get(operation)
    if matcher is None:
        raise KeyError(operation)
    accounting = ValidityBudget(budget)
    ctx = ConnectionContext(index.graph, index=index, budget=accounting)
    result = matcher_view(ctx, matcher)
    return {**result, 'budget': {'limit': accounting.limit, 'used': accounting.used,
        'costs': dict(accounting.costs), 'truncated': accounting.truncated}, 'preparation': dict(ctx.preparation)}
