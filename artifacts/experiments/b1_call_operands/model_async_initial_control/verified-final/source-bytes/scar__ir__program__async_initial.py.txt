"""Conditional first-ASEND inputs and control on the original request CFG.

Association projections are semantic declarations, never ordinary copy edges.
Every query uses its caller's ConnectionContext and accounting budget.
"""
from .admission import admission_routes, predicate_shape_errors
from .copy_flow import required_choices, selected
from .drivers import BodyResume, BodyStart, DriverReceiverKind, RawRequestKind
from .model import (CompletionResult, DataValue, ExitKind, InvokeLiteralResult,
                    OperationResult, StateVersionValue, TerminatorKind)
from .protocol_connections import RawOperandSource, RequestStateCondition, RequestStateRule
from .protocols import (AdmissionPredicate, BodyStateCondition, BodyStatePredicateRule,
                        DriverSubject, HostTerminal, OwnedUse, ProtocolProfile, ReferenceIsNoneCondition,
                        RequestProcessing, RequestProcessingRule)
from .request_inputs import _none_content
from .session_occupancy import (_aggregate, _answer, _declarations, _prepare,
                                _read_branch_support)
from .structured import ControlEdgeReference


_FLAGS = {'native_phase_verified': False, 'source_runtime_verified': False,
          'runtime_identity_verified': False, 'value_identity_verified': False,
          'transformation_authorized': False}


def _context_report(context):
    return _answer(context['match'], routes=(context,), gaps=context.get('gaps', ()))


def _contexts(ctx, reports, *, complete=True):
    return _aggregate(ctx, reports, complete=complete)


def _join(ctx, *reports):
    # correlate's support rows deliberately omit an aggregate match field.
    # Add it when that complete report becomes another join's input.
    return _contexts(ctx, (ctx.correlate(*reports),))


def _under_choices(report, choices):
    selected_edges = {edge.operation: edge.successor_index for edge in choices}
    routes = []
    for route in report['routes']:
        compatible = True
        for key, number in route.get('choices', {}).items():
            # Recipe choices are (exact caller prefix, original operation).
            # Matching uses the original operation, never a sibling label.
            operation = key[1] if type(key) is tuple and len(key) == 2 else key
            if operation in selected_edges and selected_edges[operation] != number:
                compatible = False
                break
        if compatible:
            routes.append(route)
    match = report['match']
    if not routes and match is True:
        match = False
    return {**report, 'match': match, 'routes': tuple(routes)}


def _inventory(ctx):
    cached = getattr(ctx, '_async_initial_inventory', None)
    if cached is not None:
        return cached
    scopes = tuple(scope for scope in ctx.scopes.values()
                   if scope.profile is ProtocolProfile.ASYNC_GENERATOR_BODY_V1)
    scope_ids = {scope.id for scope in scopes}
    predicates, processing = [], []
    for row in ctx.graph.protocol_operations:
        if row.scope not in scope_ids:
            continue
        if type(row.contract) is AdmissionPredicate:
            predicates.append(row)
        elif (type(row.contract) is RequestProcessing
              and row.contract.rule is RequestProcessingRule.CHECK_INITIAL_ASEND):
            processing.append(row)
    regions = {scope.subject.interface_region for scope in scopes
               if type(scope.subject) is DriverSubject}
    # These are original records, not deductions from optional attachments.
    # In particular deleting every new predicate/processing row cannot delete
    # a bool, branch, helper completion or a body-entry obligation.
    operations = tuple(operation for operation in ctx.graph.operations
                       if ctx.region_of[operation.id] in regions)
    booleans = tuple(operation for operation in operations if any(
        isinstance(ctx.values[value], DataValue) and ctx.values[value].data_type == 'builtins.bool'
        for value in operation.results))
    branches = tuple(operation for operation in operations if operation.terminator is not None
                     and operation.terminator.kind is TerminatorKind.BRANCH)
    own_ports = tuple({'operation': operation, 'edge': ControlEdgeReference(operation.id, number),
                      'kind': edge.kind, 'signature': signature,
                      'results': tuple(InvokeLiteralResult(ControlEdgeReference(operation.id, number),
                                        CompletionResult(slot)) for slot in range(len(signature.types)))}
        for operation in operations if operation.terminator is not None
        and operation.terminator.kind is TerminatorKind.INVOKE
        for number, edge in enumerate(operation.terminator.successors)
        for signature in operation.completions if signature.kind is edge.kind)
    cached = {'scopes': scopes, 'predicates': tuple(predicates), 'processing': tuple(processing),
        'drives': tuple(drive for drive in ctx.graph.body_drives
                        if ctx.region_of[drive.operation] in regions),
        'gates': tuple(gate for gate in ctx.graph.final_body_gates
                       if ctx.region_of[gate.operation] in regions),
        'associations': tuple(row for row in ctx.graph.request_association_reads
                              if ctx.region_of[row.operation] in regions),
        'operations': operations, 'bool_producers': booleans, 'branches': branches,
        'helper_ports': own_ports,
        'uninterpreted_bool_producers': tuple(operation for operation in booleans
            if operation.id not in {row.operation for row in predicates}),
        'known_inventory_complete': True}
    ctx.preparation['async_initial_control_predicates'] = len(predicates)
    ctx.preparation['async_initial_control_processing_rows'] = len(processing)
    ctx._async_initial_inventory = cached
    return cached


def _scheduler_input(ctx, interface, operation):
    """An existing S-role Use, not an added formal or an inferred producer."""
    roles = ctx.driver_roles(interface.region)[1]
    return next((OwnedUse(operation.id, use.id) for use in operation.uses
                 if use.value in roles), None)


def effective_requests(ctx, scope, scheduler_input, projections, first, *, choices=()):
    """Select L only for first S=NEXT/None; preserve each original context.

    Unknown content is not a request to fall back to L. The returned raw
    definitions always predate the delivery; actual delivery never picks them.
    """
    gaps, options = [], []
    if first is None or scheduler_input is None:
        return {'projections': (), 'gaps': ('async_effective_request_unresolved',),
                'source_coverage': (), 'cursor': None, 'source_inventory_complete': False}
    scheduler = ctx.origins(scheduler_input, guard=choices or None)
    # The complete recipe denominator is retained before classification. A
    # producer with no RawRequestDefinition is an unresolved source, not an
    # absent route which a recognized sibling can silently replace.
    coverage = [{'recipe': recipe, 'raw_requests': recipe['raw_requests'],
                 'checked': False, 'resolved': False, 'options': (), 'gaps': ()}
                for recipe in scheduler['recipes']]
    complete = scheduler['source_inventory_complete'] and bool(scheduler['recipes'])
    for number, recipe in enumerate(scheduler['recipes']):
        if not ctx.spend('async_initial_scheduler_recipes'):
            complete = False
            break
        entry = coverage[number]
        entry['checked'] = True
        start = len(options)
        local_gaps = []
        context = ctx.recipe_context(recipe)
        if not recipe['raw_requests']:
            complete = False
            local_gaps.append('async_initial_scheduler_definition_unresolved')
        if context['match'] is not True:
            complete = False
            local_gaps.append('async_initial_scheduler_context_unresolved')
        if (recipe.get('freshness') is not True
                and recipe.get('freshness_target') is not None):
            complete = False
            local_gaps.append('async_initial_scheduler_currentness_unresolved')
        for raw in recipe['raw_requests']:
            if not ctx.spend('async_initial_scheduler_definitions'):
                complete = False
                break
            definition = raw['definition']
            # Packet requests keep their existing normalization semantics.
            # Only NEXT/SEND have an optional first-step L fallback.
            if not first or definition.kind in (RawRequestKind.THROW, RawRequestKind.CLOSE):
                options.append({'raw_requests': ({**raw, 'recipe': recipe},),
                    'scheduler': True, 'context': context,
                    'source_inventory_complete': not local_gaps, 'selection': 'CURRENT_S'})
                continue
            classifications = []
            if definition.kind is RawRequestKind.NEXT:
                classifications.append((True, _context_report(context)))
            elif definition.kind is RawRequestKind.SEND:
                if not definition.operands or type(recipe['origin']) is not OperationResult:
                    complete = False
                    local_gaps.append('async_initial_scheduler_operand_unresolved')
                    continue
                operand = OwnedUse(recipe['origin'].operation, definition.operands[0])
                origins = ctx.origins(operand, guard=choices or None)
                complete = complete and origins['source_inventory_complete'] and bool(origins['recipes'])
                if not origins['source_inventory_complete'] or not origins['recipes']:
                    local_gaps.append('async_initial_scheduler_operand_inventory_unresolved')
                for candidate in origins['recipes']:
                    if not ctx.spend('async_initial_scheduler_operand_recipes'):
                        complete = False
                        break
                    extended = ctx.extend_context(candidate, operand, recipe)
                    joined = _join(ctx, _context_report(context), _context_report(extended))
                    classifications.append((_none_content(candidate), joined))
            for is_none, classification in classifications:
                if classification['match'] is False:
                    # Different original caller/CFG alternatives are not an
                    # applicable operand for this particular raw recipe.
                    continue
                if classification['match'] is not True or is_none is None:
                    complete = False
                    local_gaps.append('async_initial_scheduler_none_unresolved')
                    continue
                if not is_none:
                    # Keep the exact S recipe, including caller and branch.
                    for route in classification['routes']:
                        options.append({'raw_requests': ({**raw, 'recipe': recipe},),
                            'scheduler': True, 'context': {**route, 'match': True},
                            'source_inventory_complete': not local_gaps, 'selection': 'FIRST_NONNONE_S'})
                    continue
                for projection in projections:
                    if not ctx.spend('async_initial_latent_choices'):
                        complete = False
                        break
                    joined = _join(ctx, classification, _context_report(projection['context']))
                    if joined['match'] is False:
                        # Mutually exclusive original callers are alternatives,
                        # not an AND requirement on a single source path.
                        continue
                    if joined['match'] is not True:
                        complete = False
                        local_gaps.append('async_initial_latent_context_unresolved')
                        continue
                    for route in joined['routes']:
                        options.append({**projection, 'context': {**route, 'match': True},
                            'scheduler': False, 'selection': 'FIRST_NONE_S_USES_L',
                            'source_inventory_complete': projection.get('source_inventory_complete', False)})
        entry['options'] = tuple(options[start:])
        entry['resolved'] = (bool(entry['options']) and not local_gaps and not ctx.budget.truncated
                             and all(option['source_inventory_complete'] for option in entry['options']))
        if not entry['resolved']:
            complete = False
            if not local_gaps:
                local_gaps.append('async_initial_scheduler_source_coverage_unresolved')
        entry['gaps'] = tuple(dict.fromkeys(local_gaps))
        gaps.extend(entry['gaps'])
    if not options:
        complete = False
        gaps.append('async_effective_request_unresolved')
    if ctx.budget.truncated:
        complete = False
        gaps.append('protocol_budget_exhausted')
    if not complete:
        options = [{**option, 'source_inventory_complete': False} for option in options]
    return {'projections': tuple(options), 'scheduler': scheduler,
            'source_coverage': tuple(coverage),
            'source_inventory_complete': complete, 'gaps': tuple(dict.fromkeys(gaps)),
            'cursor': scheduler['cursor'] or ({'phase': 'initial_scheduler_selection'}
                                              if ctx.budget.truncated else None)}


def _body_sources(ctx, row, operation, branch, actual):
    """The checking R's independent association B, plus the whole state tuple."""
    from .protocol_async import _Analysis
    inventory = _prepare(ctx)
    analysis = _Analysis(ctx, prepare=False)
    analysis.creates = inventory['creates']
    interface = ctx.interfaces[ctx.region_of[operation.id]]
    expected_r = analysis.formal(interface.region, interface.receiver)
    associations, checks, source_checks = [], [], []
    complete = True
    for declaration, contract in _declarations(ctx, row, inventory):
        if not analysis.spend('initial_association_sources', operation.id):
            complete = False
            break
        source = contract.body
        if ctx.reaches(source, operation.id) is False:
            continue
        choices, ready = required_choices(ctx, source)
        if not ready:
            complete = False
            continue
        request = OwnedUse(declaration.operation, contract.request_use)
        receiver = ctx.bind(expected_r, request, choices=choices, path='async.initial.receiver')
        body = ctx.bind(source, actual, choices=choices, path='async.initial.body')
        origins = ctx.origins(request)
        projections = analysis.request_projection(request, 'async.initial.projection')
        source_complete = (origins['source_inventory_complete'] and bool(origins['recipes'])
            and len(projections) == len(origins['recipes'])
            and all(projection['source_inventory_complete'] for projection in projections))
        contexts = _contexts(ctx, (_context_report(projection['context']) for projection in projections),
                             complete=source_complete)
        source_binding = _contexts(ctx, (ctx.correlate(receiver, body, contexts),), complete=source_complete)
        state = analysis.support(contract.state_sites, branch, 'async.initial.association_state',
            after=True, completion=source.edge if type(source) is InvokeLiteralResult else None)
        full = _contexts(ctx, (ctx.correlate(source_binding, *(item['binding'] for item in state)),),
                         complete=source_complete and len(state) == len(contract.state_sites))
        associations.append({'declaration': declaration, 'contract': contract, 'choices': choices,
            'request': request, 'receiver': receiver, 'body': source, 'latent': contract.latent,
            'body_binding': body, 'source_binding': source_binding, 'projections': projections,
            'state_support': state, 'association_state_consumer': branch, 'binding': full})
        source_checks.append(source_binding)
        checks.append(full)
        complete = complete and source_complete
    return {'associations': tuple(associations), 'body_binding': _contexts(ctx, source_checks, complete=complete),
            'binding': _contexts(ctx, checks, complete=complete), 'gaps': tuple(analysis.gaps),
            'cursor': analysis.cursor, 'complete': complete and bool(associations)}


def _operand_sources(ctx, row, operation, branch):
    """Check the exact raw ordinal, independent of the tested Reference's origin."""
    from .protocol_async import _Analysis
    inventory = _prepare(ctx)
    analysis = _Analysis(ctx, prepare=False)
    analysis.creates = inventory['creates']
    actual = OwnedUse(operation.id, row.contract.subject.input_use)
    reports, projections = [], []
    interface = ctx.interfaces[ctx.region_of[operation.id]]
    # The initial predicate is a separate input to the joint control.  Here
    # retain every feasible initial/later source; the joint walk selects it.
    for declaration, contract in _declarations(ctx, row, inventory):
        if not analysis.spend('initial_operand_associations', row.operation):
            break
        if ctx.reaches(contract.latent, operation.id) is False:
            continue
        request = OwnedUse(declaration.operation, contract.request_use)
        for projection in analysis.request_projection(request, 'async.initial.operand_projection'):
            projections.append({**projection, 'latent_projection': contract.latent})
    # The independent CHECK_INITIAL_ASEND raw/ordinal ledger is also valid on
    # no-Drive rejection paths. It is not selected by chasing actual producers.
    for processing in _inventory(ctx)['processing']:
        if processing.scope != row.scope:
            continue
        raw = OwnedUse(processing.operation, processing.contract.raw_use)
        if not ctx.spend('async_initial_operand_bindings'):
            break
        report = ctx.request_binding(raw, actual, 0)
        reports.append({'processing': processing, 'raw': raw, 'ordinal': 0, 'report': report})
    checks = []
    for projection in projections:
        for raw in projection['raw_requests']:
            if not ctx.spend('async_initial_operand_sources'):
                break
            definition = raw['definition']
            if definition.kind is not RawRequestKind.SEND or type(raw['recipe']['origin']) is not OperationResult:
                continue
            source = OwnedUse(raw['recipe']['origin'].operation, definition.operands[0])
            binding = ctx.bind(source, actual, path='async.initial.operand')
            context = _context_report(raw.get('context', projection['context']))
            combined = _join(ctx, binding, context)
            checks.append({'definition': definition, 'source': source, 'projection': projection,
                           'raw': raw, 'binding': combined, 'is_none': None})
    # Prefer independently enumerated effective S/L sources whenever an S Use
    # is actually forwarded by the branch. There is no invented raw operand.
    scheduler = _scheduler_input(ctx, interface, branch)
    effective = effective_requests(ctx, ctx.scopes[row.scope], scheduler, projections, True)
    if effective['source_inventory_complete']:
        effective_checks = []
        for projection in effective['projections']:
            for raw in projection['raw_requests']:
                if not ctx.spend('async_initial_effective_operand_bindings'):
                    break
                definition = raw['definition']
                if definition.kind is RawRequestKind.SEND and type(raw['recipe']['origin']) is OperationResult:
                    source = OwnedUse(raw['recipe']['origin'].operation, definition.operands[0])
                    binding = _join(ctx, ctx.bind(source, actual, path='async.initial.effective_operand'),
                                    _context_report(projection['context']))
                    effective_checks.append({'definition': definition, 'source': source,
                        'projection': projection, 'raw': raw, 'binding': binding, 'is_none': None})
        checks = effective_checks
    complete = (bool(checks) and effective['source_inventory_complete'] and not ctx.budget.truncated
                and all(item['projection'].get('source_inventory_complete', False) for item in checks))
    binding = _contexts(ctx, (item['binding'] for item in checks), complete=complete)
    content = ctx.origins(actual)
    values = tuple(_none_content(recipe) for recipe in content['recipes'])
    is_none = (values[0] if values and content['source_inventory_complete']
               and all(value is values[0] for value in values) else None)
    return {'operand_bindings': tuple(checks), 'request_input_bindings': tuple(reports),
            'effective_sources': effective, 'binding': binding, 'declared_is_none': is_none,
            'operand_origins': content, 'associations': (), 'gaps': tuple(analysis.gaps),
            'cursor': analysis.cursor, 'complete': complete}


def async_predicate_view(ctx, row):
    from .protocol_async import _Analysis
    subject = row.contract.subject
    if type(subject) not in (BodyStateCondition, ReferenceIsNoneCondition):
        raise TypeError('async predicate requires BodyStateCondition or ReferenceIsNoneCondition')
    cache = getattr(ctx, '_async_initial_predicate_views', None)
    if cache is None:
        cache = ctx._async_initial_predicate_views = {}
    key = row.scope, row.clause, row.operation, row.slot
    if key in cache:
        return cache[key]
    operation, branch = ctx.operations[row.operation], ctx.operations[row.contract.branch]
    analysis = _Analysis(ctx, prepare=False)
    body = type(subject) is BodyStateCondition
    identity = subject.instance_use if body else subject.input_use
    actual = OwnedUse(operation.id, identity)
    boolean = ctx.bind(row.contract.result, OwnedUse(branch.id, branch.terminator.condition),
                       path='async.initial.bool')
    support = analysis.support(subject.state_sites if body else (), operation, 'async.initial.read')
    branch_support = _read_branch_support(ctx, analysis, operation, branch)
    sources = (_body_sources(ctx, row, operation, branch, actual) if body
               else _operand_sources(ctx, row, operation, branch))
    routes = admission_routes(ctx, row)
    # A single predicate never grants admission. In particular Created plus
    # nonNone has to be interpreted together on the same original path.
    routes = {**routes, 'frontiers': tuple({**frontier,
        'target_compatible_at_snapshot': None} for frontier in routes['frontiers'])}
    gaps = [*routes['gaps'], *(gap['code'] if type(gap) is dict else gap for gap in sources['gaps']),
            *(gap['code'] if type(gap) is dict else gap for gap in analysis.gaps)]
    if boolean['match'] is not True:
        gaps.append('async_initial_bool_unresolved')
    if sources['binding']['match'] is not True:
        gaps.append('async_initial_source_tuple_unresolved')
    if ctx.budget.truncated:
        gaps.append('protocol_budget_exhausted')
    wrong = boolean['match'] is False or sources.get('body_binding', sources['binding'])['match'] is False
    view = {'predicate': row, 'operation': operation, 'subject': subject,
        'input': ctx.owned_use(actual.operation, actual.use), 'actual': actual,
        'result': ctx.port(row.contract.result), 'branch': branch,
        'condition': ctx.owned_use(branch.id, branch.terminator.condition),
        'bool_must_copy': boolean['match'], 'boolean_binding': boolean,
        'state_support': support, 'read_branch_support': branch_support,
        'successors': tuple(enumerate(branch.terminator.successors)), 'control_routes': routes,
        **sources, 'status': 'CONTRADICTED' if wrong else 'PARTIAL' if gaps else 'DECLARED',
        'gaps': tuple(dict.fromkeys(gaps)),
        'cursor': sources['cursor'] or analysis.cursor or
                  ({'phase': 'async_initial_predicate', 'operation': row.operation} if ctx.budget.truncated else None),
        'expected_bool': sources.get('declared_is_none'), 'target_compatible_at_snapshot': None,
        **_FLAGS}
    cache[key] = view
    return view


def async_predicate_errors(ctx, row):
    subject = row.contract.subject
    body = type(subject) is BodyStateCondition
    if not body and type(subject) is not ReferenceIsNoneCondition:
        raise TypeError('async predicate requires BodyStateCondition or ReferenceIsNoneCondition')
    identity = subject.instance_use if body else subject.input_use
    issues = list(predicate_shape_errors(ctx, row, identity=identity,
        state_sites=subject.state_sites if body else (), stateful=body))
    operation = ctx.operations[row.operation]
    expected = {identity, *(access.before for access in operation.accesses)}
    if {use.id for use in operation.uses} != expected:
        issues.append(('async_initial_predicate_inputs', str(row.operation),
                       'predicate consumes only its exact Reference and every original READ input'))
    scope = ctx.scopes[row.scope]
    interface = ctx.interfaces.get(ctx.region_of[row.operation])
    if (scope.profile is not ProtocolProfile.ASYNC_GENERATOR_BODY_V1
            or type(scope.subject) is not DriverSubject or interface is None
            or interface.receiver_kind is not DriverReceiverKind.ASYNC_REQUEST
            or scope.subject.interface_region != interface.region):
        issues.append(('async_initial_predicate_profile', str(row.operation),
                       'async initial predicates require their exact request driver interface'))
    if issues:
        return tuple(issues)
    view = async_predicate_view(ctx, row)
    if view.get('body_binding', view['binding'])['match'] is False:
        issues.append(('async_initial_body' if body else 'async_initial_operand', str(row.operation),
                       'predicate input differs from its independent associated body or effective ordinal0'))
    return tuple(issues)


def _path_predicate(ctx, row, view, choices):
    """Recheck one tuple under this path, not another frontier's outcome."""
    condition = OwnedUse(view['branch'].id, view['branch'].terminator.condition)
    boolean = ctx.bind(row.contract.result, condition, choices=choices,
                       path='async.initial.path.bool')
    subject = row.contract.subject
    sources = []
    complete = view.get('complete', True)
    gaps = []
    if type(subject) is BodyStateCondition:
        for item in view['associations']:
            if not ctx.spend('async_initial_path_associations'):
                break
            # The independently declared association's entire NORMAL state
            # tuple remains a dependency, including domains not read by this
            # predicate. A fresh B copy alone cannot replace that tuple.
            context = _under_choices(item['binding'], choices)
            if context['match'] is False:
                continue
            # This complete report already proves the exact same B Use and
            # every association state dependency. Restrict its original caller
            # alternatives; do not restart a cross-region origin resolution.
            sources.append(context)
    elif type(subject) is ReferenceIsNoneCondition:
        effective_complete = view['effective_sources']['source_inventory_complete']
        complete = complete and effective_complete
        if not effective_complete:
            gaps.append('async_initial_effective_source_inventory_unresolved')
        for item in view['operand_bindings']:
            if not ctx.spend('async_initial_path_operands'):
                break
            context = _under_choices(item['binding'], choices)
            if context['match'] is False:
                continue
            # The independent raw/ordinal/caller proof already targets this
            # exact predicate Use. Reinterpreting its nonNone literal leaf as
            # a new identity source would discard that original proof.
            sources.append(context)
    else:
        sources.append(view['request_binding'])
    source = _contexts(ctx, sources, complete=complete and bool(sources) and not ctx.budget.truncated)
    if not complete:
        gaps.append('async_initial_predicate_source_inventory_unresolved')
        source = {**source, 'gaps': (*source['gaps'], *gaps)}
    state = []
    for item in view.get('read_branch_support', ()):
        for actual in item['actuals']:
            if not ctx.spend('async_initial_path_read_support'):
                break
            state.append(ctx.bind(OwnedUse(row.operation, item['access'].before), actual,
                                  choices=choices, path='async.initial.path.read'))
    return {'boolean': boolean, 'source': source, 'state_support': tuple(state),
            'source_inventory_complete': complete, 'gaps': tuple(gaps),
            'binding': _join(ctx, boolean, source, *state)}


def _processing_view(ctx, row, consumer, choices, predicates):
    """Original ordered raw operand and each own completion/state port."""
    from .protocol_async import _Analysis
    analysis = _Analysis(ctx, prepare=False)
    operation, contract = ctx.operations[row.operation], row.contract
    raw = OwnedUse(operation.id, contract.raw_use)
    bindings, gaps, issues = [], [], []
    for item in contract.operand_bindings:
        if not ctx.spend('async_initial_processing_operands'):
            gaps.append('protocol_budget_exhausted')
            break
        actual = OwnedUse(operation.id, item.operation_use)
        report = ctx.bind(RawOperandSource(raw, item.request_ordinal), actual, choices=choices,
                          path='async.initial.processing.ordinal')
        bindings.append({'ordinal': item.request_ordinal, 'actual': actual,
                         'raw_operand_binding': report, 'report': report})
    if tuple(item.request_ordinal for item in contract.operand_bindings) != (0,):
        gaps.append('async_initial_processing_ordinal_unresolved')
        issues.append(('async_initial_processing_ordinal', str(row.operation),
                       'CHECK_INITIAL_ASEND must bind its exact SEND operand at ordinal zero'))
    # The contract supplies the raw anchor. Its original source inventory is
    # checked before any expected operand is compared with an actual input.
    origins = ctx.origins(raw, guard=choices or None)
    definitions = tuple(detail['definition'] for recipe in origins['recipes']
                        for detail in recipe['raw_requests'])
    if (origins['source_inventory_complete'] and definitions
            and all(definition.kind is not RawRequestKind.SEND for definition in definitions)):
        issues.append(('async_initial_processing_kind', str(row.operation),
                       'CHECK_INITIAL_ASEND requires the original SEND request, not another raw kind'))
    elif (not origins['source_inventory_complete'] or not definitions
          or any(definition.kind is not RawRequestKind.SEND for definition in definitions)):
        gaps.append('async_initial_processing_kind_unresolved')
    source_bindings, source_definitions = [], []
    source_complete = True
    for predicate in predicates:
        view = predicate['view']
        if type(predicate['record'].contract.subject) is not ReferenceIsNoneCondition:
            continue
        source_complete = (source_complete and view['complete']
                           and view['effective_sources']['source_inventory_complete'])
        for item in view['operand_bindings']:
            if not ctx.spend('async_initial_processing_source_tuples'):
                break
            projection = item['projection']
            context = _under_choices(item['binding'], choices)
            if context['match'] is False:
                continue
            interface = ctx.interfaces[ctx.region_of[row.operation]]
            source = (analysis.formal(interface.region, interface.scheduler_request)
                      if projection.get('scheduler') else projection.get('latent_projection'))
            if source is None:
                gaps.append('async_initial_processing_raw_projection_unresolved')
                continue
            expected_raw = ctx.bind(source, raw, choices=choices,
                                    path='async.initial.processing.raw')
            # Connect the previously proved original predicate input to this
            # helper's actual operand locally. The complete source proof stays
            # separate, including caller context and the original ordinal.
            inputs = tuple(ctx.bind(view['actual'], OwnedUse(operation.id, binding.operation_use),
                                    choices=choices, path='async.initial.processing.operand')
                           for binding in contract.operand_bindings if binding.request_ordinal == 0)
            source_bindings.append({'source': source, 'raw_binding': expected_raw,
                'input_source': view['actual'], 'original_operand_source': item['source'],
                'source_proof': context,
                'operand_bindings': inputs, 'binding': _join(ctx, context, expected_raw, *inputs)})
            source_definitions.append(item['definition'])
    source_binding = _contexts(ctx, (item['binding'] for item in source_bindings),
                               complete=source_complete and bool(source_bindings) and not ctx.budget.truncated)
    if (source_binding['match'] is True and source_definitions
            and all(definition.kind is RawRequestKind.SEND for definition in source_definitions)):
        # RawOperandSource intentionally knows only ordinary copies. The
        # source-first Create/Association projection is a separate conditional
        # meaning, supported by both raw and ordinal ports in one caller tuple.
        # Keep the unresolved ordinary-copy receipt intact for inspection.
        gaps = [gap for gap in gaps if gap != 'async_initial_processing_kind_unresolved']
        for item in bindings:
            original = item['raw_operand_binding']
            if original['match'] is None and not ctx.budget.truncated:
                item['report'] = {**source_binding, 'raw_operand_binding': original,
                    'semantic_projection': True,
                    'selection_basis': 'ORIGINAL_REQUEST_CREATE_ASSOCIATION_ORDINAL', **_FLAGS}
    if source_binding['match'] is False:
        issues.append(('async_initial_processing_source', str(row.operation),
                       'the check consumes another raw request or another ordinal-zero source'))
    elif source_binding['match'] is None:
        gaps.append('async_initial_processing_source_unresolved')
    chosen = next((edge for edge in choices if edge.operation == operation.id), None)
    own = contract.result
    applicable = chosen is None or type(own) is not InvokeLiteralResult or own.edge == chosen
    support, terminals = (), ()
    if applicable and chosen is not None:
        support = analysis.support(contract.state_sites, consumer, 'async.initial.processing_state',
                                   after=True, completion=chosen)
        gaps.extend(item['code'] for item in analysis.gaps)
        if (consumer.terminator is not None and consumer.terminator.kind is TerminatorKind.RAISE):
            terminals = tuple({'actual': actual,
                'binding': ctx.bind(own, actual, choices=choices, path='async.initial.processing.host')}
                for actual in ctx.terminal_uses(HostTerminal(consumer.id)))
            if not terminals:
                gaps.append('async_initial_processing_host_missing')
        else:
            gaps.append('async_initial_processing_host_unresolved')
        for terminal in terminals:
            if terminal['binding']['match'] is False:
                issues.append(('async_initial_processing_packet', str(consumer.id),
                               'rejection host must consume this selected helper own packet'))
            elif terminal['binding']['match'] is None:
                gaps.append('async_initial_processing_packet_unresolved')
        if len(support) != len(contract.state_sites) or any(
                item['binding']['match'] is not True for item in support):
            gaps.append('async_initial_processing_state_unresolved')
    if any(item['report']['match'] is not True for item in bindings):
        gaps.append('async_initial_processing_operand_unresolved')
    if any(item['report']['match'] is False for item in bindings):
        issues.append(('async_initial_processing_operand', str(row.operation),
                       'the rejection helper operand is not this raw request ordinal zero'))
    return {'record': row, 'operation': operation, 'raw': raw, 'own_result': own,
            'edge': own.edge if type(own) is InvokeLiteralResult else None,
            'applicable': applicable, 'operand_bindings': tuple(bindings),
            'source_bindings': tuple(source_bindings), 'source_binding': source_binding,
            'terminals': terminals, 'state_support': support, 'issues': tuple(issues),
            'gaps': tuple(gaps), **_FLAGS}


def initial_asend_connections(ctx):
    """One bounded walk per original scope, preserving complete path tuples."""
    from .protocol_async import request_state_view
    cached = getattr(ctx, '_initial_asend_connections', None)
    if cached is not None:
        return cached
    inventory = _inventory(ctx)
    # Old profiles without the new joint subjects retain their existing
    # request/packet path and its original budget denominator.
    enabled = {row.scope for row in inventory['predicates']
               if type(row.contract.subject) in (BodyStateCondition, ReferenceIsNoneCondition)}
    views, paths, issues, gaps, cursor = [], [], [], [], None
    if inventory['uninterpreted_bool_producers']:
        gaps.append('async_initial_predicate_interpretation_missing')
        # The original bool/branch denominator survives complete metadata
        # deletion; anonymous bools remain uninterpreted, never inferred from
        # a name, observed value or which BodyDrive follows them.
        enabled.update(scope.id for scope in inventory['scopes']
            if type(scope.subject) is DriverSubject and any(
                ctx.region_of[operation.id] == scope.subject.interface_region
                for operation in inventory['uninterpreted_bool_producers']))
    by_operation = {}
    for row in inventory['predicates']:
        by_operation.setdefault(row.operation, []).append(row)
    for scope in inventory['scopes']:
        if scope.id not in enabled:
            continue
        region = ctx.regions[scope.subject.interface_region]
        pending = [(region.entry, (), (), (), frozenset())]
        while pending:
            if not ctx.spend('async_initial_control_blocks'):
                cursor = {'phase': 'initial_control', 'scope': scope.id, 'pending_paths': len(pending)}
                break
            block_id, choices, predicates, processing, seen = pending.pop()
            if block_id in seen:
                gaps.append('async_initial_control_visit_unselected')
                continue
            seen = seen | {block_id}
            block = ctx.blocks[block_id]
            stopped = False
            for identity in block.operations:
                if not ctx.spend('async_initial_control_operations'):
                    cursor = {'phase': 'initial_control', 'operation': identity}
                    stopped = True
                    break
                operation = ctx.operations[identity]
                for row in by_operation.get(identity, ()):
                    if row.scope != scope.id:
                        continue
                    subject = row.contract.subject
                    view = (request_state_view(ctx, row) if type(subject) is RequestStateCondition
                            else async_predicate_view(ctx, row)
                            if type(subject) in (BodyStateCondition, ReferenceIsNoneCondition) else None)
                    if view is not None:
                        if not any(item['record'] == row for item in views):
                            views.append({'record': row, 'view': view})
                        predicates = (*predicates, {'record': row, 'view': view})
                processing = (*processing, *(row for row in inventory['processing']
                                              if row.scope == scope.id and row.operation == identity))
                drive = ctx.drives.get(identity)
                gate = ctx.gates.get(identity)
                if gate is not None:
                    drive = ctx.drives[gate.drive]
                terminal = (operation if operation.terminator is not None
                    and operation.terminator.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE) else None)
                if drive is None and terminal is None:
                    continue
                selected_predicates, truth_values, ready = [], {}, not ctx.budget.truncated
                for item in predicates:
                    row, view = item['record'], item['view']
                    edge = next((edge for edge in choices if edge.operation == row.contract.branch), None)
                    truth = None if edge is None else edge.successor_index == 0
                    path_binding = _path_predicate(ctx, row, view, choices)
                    selected_predicates.append({**item, 'truth': truth, **path_binding})
                    subject = row.contract.subject
                    if type(subject) is RequestStateCondition and subject.rule is RequestStateRule.IS_INITIAL_STEP:
                        truth_values.setdefault('initial', []).append(truth)
                    elif type(subject) is BodyStateCondition and subject.rule is BodyStatePredicateRule.IS_CREATED:
                        truth_values.setdefault('created', []).append(truth)
                    elif type(subject) is ReferenceIsNoneCondition:
                        truth_values.setdefault('none', []).append(truth)
                    ready = ready and truth is not None and path_binding['binding']['match'] is True
                    if drive is not None and operation.id in ctx.gates:
                        frontiers = tuple(frontier for frontier in view['control_routes']['frontiers']
                            if frontier.get('gate') == gate and frontier.get('edge') == edge)
                        ready = ready and bool(frontiers) and all(
                            frontier.get('read_snapshot_current') is True for frontier in frontiers)
                truths = {key: values[0] if values and all(value is values[0] for value in values)
                          else None for key, values in truth_values.items()}
                # Two None checks refer to one effective input only when the
                # independent input tuples cohere. Different Ref subjects are
                # not replaced by the last bool encountered on this path.
                none_predicates = tuple(item for item in selected_predicates
                    if type(item['record'].contract.subject) is ReferenceIsNoneCondition)
                if len(none_predicates) > 1:
                    first_none = none_predicates[0]['view']['actual']
                    same_inputs = tuple(ctx.bind(first_none, item['view']['actual'], choices=choices,
                        path='async.initial.path.same_none_input') for item in none_predicates[1:])
                    if any(item['match'] is not True for item in same_inputs):
                        truths['none'] = None
                        ready = False
                if any(value is None for value in truths.values()):
                    ready = False
                processing_views = tuple(_processing_view(ctx, row, operation, choices,
                    selected_predicates) for row in processing)
                issues.extend(issue for item in processing_views for issue in item['issues'])
                processing_gaps = tuple(gap for item in processing_views if item['applicable']
                                        for gap in item['gaps'])
                whole_inputs = [item['binding'] for item in selected_predicates]
                for item in processing_views:
                    if item['applicable']:
                        whole_inputs.append(item['source_binding'])
                        whole_inputs.extend(binding['report'] for binding in item['operand_bindings'])
                        whole_inputs.extend(terminal['binding'] for terminal in item['terminals'])
                        whole_inputs.extend(state['binding'] for state in item['state_support'])
                joint = _join(ctx, *whole_inputs) if whole_inputs else _answer()
                ready = ready and joint['match'] is True and not ctx.budget.truncated
                if drive is not None:
                    ready = ready and truths.get('initial') is not None and truths.get('created') is not None
                    if type(drive.target) is BodyStart:
                        ready = ready and truths.get('none') is not None
                compatible = None
                if ready and drive is not None:
                    created, none = truths.get('created'), truths.get('none')
                    if type(drive.target) is BodyStart:
                        compatible = created and none
                    elif type(drive.target) is BodyResume:
                        compatible = not created
                local_gaps = (*(() if ready else ('async_initial_control_tuple_unresolved',)),
                              *processing_gaps)
                if compatible is False:
                    issues.append(('async_initial_target', str(identity),
                        'this original Created/effective-operand path cannot enter the selected Start/Resume'))
                paths.append({'scope': scope.id, 'choices': choices, 'predicates': tuple(selected_predicates),
                    'processing': processing, 'processing_views': processing_views,
                    'gate': gate, 'drive': drive, 'terminal': terminal,
                    'binding': joint,
                    'initial_step': truths.get('initial'), 'body_created': truths.get('created'),
                    'effective_is_none': truths.get('none'), 'compatible_at_snapshot': compatible,
                    'status': 'CONTRADICTED' if compatible is False else 'PARTIAL' if local_gaps else 'DECLARED',
                    'gaps': local_gaps, **_FLAGS})
                stopped = True
                break
            if stopped or ctx.budget.truncated:
                continue
            terminator = ctx.operations[block.operations[-1]]
            if terminator.terminator is None:
                gaps.append('async_initial_control_successor_unresolved')
                continue
            for number, edge in reversed(tuple(enumerate(terminator.terminator.successors))):
                if not ctx.spend('async_initial_control_edges'):
                    break
                if edge.block is None:
                    gaps.append('async_initial_control_exit_unresolved')
                    continue
                try:
                    combined = selected(ctx, choices, (ControlEdgeReference(terminator.id, number),))
                except ValueError:
                    gaps.append('async_initial_control_visit_unselected')
                    continue
                pending.append((edge.block, combined, predicates, processing, seen))
    if ctx.budget.truncated:
        gaps.append('protocol_budget_exhausted')
        cursor = cursor or {'phase': 'initial_asend_connections'}
    gaps.extend(gap for path in paths for gap in path['gaps'])
    result = {'predicates': tuple(views), 'processing': inventory['processing'],
        'drives': inventory['drives'], 'routes': tuple(paths), 'inventory': inventory,
        'issues': tuple(issues), 'gaps': tuple(dict.fromkeys(gaps)), 'cursor': cursor,
        'status': 'CONTRADICTED' if issues else 'PARTIAL' if gaps else 'DECLARED',
        'known_inventory_complete': True,
        'proofs_complete': not gaps and not issues and not ctx.budget.truncated,
        'budget': {'limit': ctx.budget.limit, 'used': ctx.budget.used,
                   'costs': dict(ctx.budget.costs), 'truncated': ctx.budget.truncated}, **_FLAGS}
    ctx._initial_asend_connections = result
    return result


__all__ = ['async_predicate_errors', 'async_predicate_view', 'initial_asend_connections']
