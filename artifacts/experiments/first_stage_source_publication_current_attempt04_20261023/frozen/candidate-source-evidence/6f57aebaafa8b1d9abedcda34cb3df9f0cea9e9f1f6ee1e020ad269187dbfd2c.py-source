"""Bounded original async-request paths, not an execution or native effect graph.

Only the supplied driver Region is enumerated. A completed local host route
without an explicit BodyDrive says nothing about callbacks or callee/native
internals. Request field interpretations remain conditional declarations and
never add an ordinary copy between an owner and a newly produced Reference.
"""
from .drivers import DriverReceiverKind
from .model import (CompletionResult, ExitKind, InvokeLiteralResult, ReferenceValue,
                    StateVersionValue, TerminatorKind)
from .protocols import (AdmissionPredicate, BodyStateCondition, DriverSubject,
                        HostTerminal, OwnedUse, ProtocolProfile, StaticProtocolGap)
from .resumption import ResumableKind
from .structured import ControlEdgeReference


_FLAGS = dict(source_runtime_verified=False, runtime_identity_verified=False,
              native_applicability_verified=False, value_identity_verified=False,
              transformation_authorized=False)
_CONDITIONS = (
    'only the original supplied driver Region is enumerated',
    'callee/native internals and callbacks are not checked',
    'stored request projections and source/native applicability remain conditional',
)


def _unknown(code, *, cursor=None):
    return {'match': None, 'routes': (), 'gaps': (code,), 'cursor': cursor,
            'conditions': _CONDITIONS, **_FLAGS}


def request_no_drive_inventory(ctx):
    """Original rows only; this preparation spends no semantic query budget."""
    cached = getattr(ctx, '_async_request_path_inventory', None)
    if cached is not None:
        return cached
    rows = []
    for interface in ctx.graph.driver_interfaces:
        body = ctx.bodies.get(interface.body)
        if (interface.receiver_kind is not DriverReceiverKind.ASYNC_REQUEST
                or body is None or body.kind is not ResumableKind.ASYNC_GENERATOR):
            continue
        region = ctx.regions[interface.region]
        entry = ctx.blocks[region.entry]
        operations = tuple(ctx.operations[identity] for block in region.blocks
                           for identity in block.operations)
        invokes = []
        for operation in operations:
            terminator = operation.terminator
            if terminator is None or terminator.kind is not TerminatorKind.INVOKE:
                continue
            edges = []
            for number, successor in enumerate(terminator.successors):
                edge = ControlEdgeReference(operation.id, number)
                signature = next(row for row in operation.completions if row.kind is successor.kind)
                edges.append({'edge': edge, 'successor': successor, 'kind': successor.kind,
                    'signature': signature, 'own_results': tuple(
                        InvokeLiteralResult(edge, CompletionResult(slot))
                        for slot in range(len(signature.types)))})
            invokes.append({'operation': operation, 'edges': tuple(edges)})
        rows.append({'key': interface.region, 'interface': interface,
            'scopes': tuple(scope for scope in ctx.graph.protocol_scopes
                if scope.profile is ProtocolProfile.ASYNC_GENERATOR_BODY_V1
                and type(scope.subject) is DriverSubject
                and scope.subject.interface_region == interface.region),
            'region': region, 'entry': entry,
            'receiver': ctx.values[interface.receiver],
            'scheduler': ctx.values[interface.scheduler_request],
            'operations': operations,
            'branches': tuple(operation for operation in operations
                if operation.terminator is not None
                and operation.terminator.kind is TerminatorKind.BRANCH),
            'invokes': tuple(invokes),
            'hosts': tuple(HostTerminal(operation.id) for operation in operations
                if operation.terminator is not None
                and operation.terminator.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE)),
            'drives': tuple(ctx.drives_by_region.get(interface.region, ()))})
    cached = ctx._async_request_path_inventory = tuple(rows)
    ctx.preparation['async_request_path_interfaces'] = len(cached)
    ctx.preparation['async_request_path_operations'] = sum(len(row['operations']) for row in cached)
    ctx.preparation['async_request_path_invoke_edges'] = sum(
        len(invoke['edges']) for row in cached for invoke in row['invokes'])
    return cached


def body_request_projection(analysis, request, path):
    """Project only Create.body, retaining every original request recipe.

    No latent Use is visited and no RAW origin is requested. Missing request
    recipes remain entries, so a recognized sibling cannot complete inventory.
    """
    ctx = analysis.ctx
    origins = ctx.origins(request)
    rows = [{'role': 'body', 'create': None, 'request_result': recipe['origin'],
             'request_recipe': recipe, 'body_input': None, 'latent_input': None,
             'raw_requests': (), 'context': None, 'checked': False, 'gaps': (),
             'source_inventory_complete': False,
             'overall_association_complete': False, 'conditions': _CONDITIONS}
            for recipe in origins['recipes']]
    complete = origins['source_inventory_complete'] and bool(rows)
    for row in rows:
        if not analysis.spend('body_request_origins', path):
            complete = False
            break
        row['checked'] = True
        recipe, source = row['request_recipe'], row['request_result']
        context = ctx.recipe_context(recipe)
        row['context'] = context
        gaps = []
        create = (analysis.creates.get(source.edge.operation)
                  if type(source) is InvokeLiteralResult else None)
        if create is None:
            gaps.append('async_body_request_create_unresolved')
        else:
            operation = ctx.operations[create.operation]
            successor = operation.terminator.successors[source.edge.successor_index]
            if (successor.kind is not ExitKind.NORMAL
                    or source.result.index != create.request_result.index):
                gaps.append('async_body_request_result_unresolved')
            else:
                body = OwnedUse(operation.id, create.body)
                analysis.use(body, actual=True)
                row.update(create=create, body_input=body)
        if context['match'] is not True:
            gaps.append('async_body_request_context_unresolved')
        if recipe.get('freshness_target') is not None and recipe.get('freshness') is not True:
            gaps.append('async_body_request_currentness_unresolved')
        row['gaps'] = tuple(gaps)
        if gaps:
            complete = False
            for code in gaps:
                analysis.gap(code, path)
    complete = complete and not ctx.budget.truncated and all(row['checked'] for row in rows)
    for row in rows:
        row['source_inventory_complete'] = complete
    if not rows:
        analysis.gap('async_body_request_origin_unresolved', path)
    elif not complete:
        analysis.gap('async_body_request_inventory_unresolved', path)
    return tuple(rows)


class _Walk:
    def __init__(self, ctx):
        self.ctx = ctx
        self.paths, self.boundaries, self.gaps, self.issues = [], [], [], []
        self.cursor = None
        self.complete = True
        self.association_rows = {}
        self.predicate_rows = {}
        from .protocol_connections import RequestAssociation
        for row in ctx.graph.protocol_operations:
            if type(row.contract) is RequestAssociation:
                self.association_rows.setdefault(row.operation, []).append(row)
            elif (type(row.contract) is AdmissionPredicate
                  and type(row.contract.subject) is BodyStateCondition):
                self.predicate_rows.setdefault(row.operation, []).append(row)

    def spend(self, kind, identity, cost=1):
        if not self.ctx.budget.truncated and self.ctx.spend('async_request_path_' + kind, cost):
            return True
        self.complete = False
        if self.cursor is None:
            self.cursor = {'phase': kind, 'operation': identity}
        return False

    def boundary(self, code, item, operation, choices):
        self.complete = False
        row = {'code': code, 'interface': item['interface'], 'operation': operation,
               'choices': choices}
        self.boundaries.append(row)
        self.gaps.append(row)

    def invocation(self, operation, edge, successor):
        signature = next(row for row in operation.completions if row.kind is successor.kind)
        block = self.ctx.blocks[successor.block]
        results, states = [], []
        if not self.spend('completion_arguments', operation.id, len(successor.arguments) + 1):
            return {'operation': operation, 'selected_edge': edge, 'own_results': (), 'states': ()}
        landings = {}
        for position, (argument, formal) in enumerate(zip(successor.arguments, block.arguments)):
            if type(argument) is CompletionResult:
                landings.setdefault(argument.index, []).append({
                    'formal': self.ctx.values[formal], 'argument': argument, 'position': position})
        for slot, type_ in enumerate(signature.types):
            if not self.spend('own_result_slots', operation.id):
                break
            result = {'slot': slot, 'source': InvokeLiteralResult(edge, CompletionResult(slot)),
                      'type': type_, 'landings': tuple(landings.get(slot, ()))}
            results.append(result)
            if getattr(type_, 'location', None) is not None:
                states.append(result)
        return {'operation': operation, 'selected_edge': edge,
                'own_results': tuple(results), 'states': tuple(states)}

    def terminal_states(self, operation, choices, current):
        rows = []
        for identity in operation.terminator.values:
            use = self.ctx.owned_use(operation.id, identity)
            value = self.ctx.values[use.value]
            if not isinstance(value, StateVersionValue):
                continue
            actual = OwnedUse(operation.id, identity)
            if not self.spend('terminal_state_slots', operation.id):
                report = _unknown('async_request_path_budget_exhausted', cursor=self.cursor)
            else:
                expected = current.get(value.location)
                report = (self.ctx.bind(self.ctx.values[expected].origin, actual, choices=choices,
                                       path='async.request_path.state') if expected is not None else
                          _unknown('async_request_path_current_state_unresolved'))
            rows.append({'location': value.location, 'actual': actual, 'value': value,
                         'binding': report})
        return tuple(rows)

    def associations(self, item, operations, choices):
        from .protocol_async import _Analysis
        analysis = _Analysis(self.ctx, prepare=False)
        analysis.creates = {row.operation: row for row in self.ctx.graph.async_request_creates}
        rows = []
        # Only original declarations encountered on this exact local path.
        for operation in operations:
            for declaration in self.association_rows.get(operation.id, ()):
                contract = declaration.contract
                if declaration.scope not in {scope.id for scope in item['scopes']}:
                    continue
                if not self.spend('body_associations', operation.id):
                    return tuple(rows)
                request = OwnedUse(operation.id, contract.request_use)
                projections = analysis.request_projection(request, str(operation.id), role='body')
                receiver = self.ctx.bind(item['receiver'].origin, request, choices=choices,
                                         path='async.request_path.receiver')
                complete = bool(projections) and all(row['source_inventory_complete'] for row in projections)
                projection_contexts = tuple(row['context'] for row in projections if row['context'] is not None)
                projection = {'match': True if complete and len(projection_contexts) == len(projections)
                    and all(row['match'] is True for row in projection_contexts) else None,
                    'routes': projection_contexts, 'gaps': (), 'cursor': analysis.cursor,
                    'conditions': _CONDITIONS, **_FLAGS}
                consumers = []
                position = operations.index(operation)
                for consumer in operations[position + 1:]:
                    if not self.spend('body_consumer_operations', consumer.id):
                        break
                    for predicate in self.predicate_rows.get(consumer.id, ()):
                        if predicate.scope == declaration.scope:
                            consumers.append((consumer, predicate))
                bindings = []
                for consumer, predicate in consumers:
                    if not self.spend('body_consumers', consumer.id):
                        break
                    actual = OwnedUse(consumer.id, predicate.contract.subject.instance_use)
                    copied = self.ctx.bind(contract.body, actual, choices=choices,
                                           path='async.request_path.body')
                    branch = self.ctx.operations[predicate.contract.branch]
                    state = analysis.support(contract.state_sites, branch,
                        'async.request_path.association_state', after=True,
                        completion=contract.body.edge if type(contract.body) is InvokeLiteralResult else None)
                    # Context alternatives stay in one report. Correlation
                    # then covers every original recipe without ANDing two
                    # mutually exclusive callers into one invented path.
                    reports = (projection, receiver, copied, *(row['binding'] for row in state))
                    joint = self.ctx.correlate(*reports)
                    bindings.append({'actual': actual, 'copy_binding': copied,
                        'receiver_binding': receiver, 'state_support': state, 'binding': joint})
                bindings = tuple(bindings)
                matches = tuple(row['binding']['match'] for row in bindings)
                match = (True if bindings and all(value is True for value in matches) else
                         False if bindings and all(value is False for value in matches) else None)
                if not complete or self.ctx.budget.truncated:
                    match = None
                binding = {'match': match,
                    'routes': tuple(route for row in bindings for route in row['binding']['routes']),
                    'gaps': (() if match is True else ('async_request_path_body_unresolved',)),
                    'cursor': analysis.cursor, 'conditions': _CONDITIONS, **_FLAGS}
                overall_gap = (('async_request_latent_role_unprovided',)
                               if type(contract.latent) is StaticProtocolGap else ())
                rows.append({'declaration': declaration, 'operation': operation, 'role': 'body',
                    'request': request, 'body': contract.body, 'body_projection': projections,
                    'projection_context': projection, 'receiver_binding': receiver,
                    'body_consumers': bindings, 'body_binding': binding,
                    'overall_association_complete': False if type(contract.latent) is StaticProtocolGap else None,
                    'gaps': (*analysis.gaps, *overall_gap),
                    'body_status': 'DECLARED' if match is True else
                                   'CONTRADICTED' if match is False else 'PARTIAL',
                    'status': 'PARTIAL' if overall_gap else 'DECLARED' if match is True else
                              'CONTRADICTED' if match is False else 'PARTIAL'})
        return tuple(rows)

    def finish_path(self, item, operations, choices, invocations, current, *, terminal=None, drive=None,
                    unresolved=False):
        operation = operations[-1]
        states = self.terminal_states(operation, choices, current) if terminal is not None else ()
        associations = self.associations(item, operations, choices) if not unresolved else ()
        incomplete = unresolved or self.ctx.budget.truncated
        if self.ctx.budget.truncated:
            self.complete = False
            self.cursor = self.cursor or {'phase': 'path_bindings', 'operation': operation.id}
        gaps = ('async_request_path_unresolved',) if incomplete else ()
        self.paths.append({'key': (item['key'], choices, operation.id),
            'interface': item['interface'], 'choices': choices, 'operations': operations,
            'invocations': invocations, 'terminal': terminal, 'drive': drive,
            'states': states, 'associations': associations,
            'declared_no_drive': None if incomplete else terminal is not None,
            'status': 'PARTIAL' if incomplete else 'DECLARED', 'gaps': gaps,
            'cursor': self.cursor if incomplete else None})

    def walk(self, item):
        ctx = self.ctx
        pending = [(item['entry'].id, (), (), (), (), {})]
        while pending:
            if not self.spend('blocks', pending[-1][0]):
                break
            block_id, choices, ancestors, prefix, invocations, previous = pending.pop()
            block = ctx.blocks[block_id]
            if block_id in ancestors:
                operation = ctx.operations[block.operations[0]]
                self.boundary('async_request_path_cycle_unresolved', item, operation, choices)
                self.finish_path(item, (*prefix, operation), choices, invocations, previous, unresolved=True)
                continue
            ancestors = (*ancestors, block_id)
            current = dict(previous)
            current.update((ctx.values[value].location, value) for value in block.arguments
                           if isinstance(ctx.values[value], StateVersionValue))
            operations = prefix
            for identity in block.operations:
                if not self.spend('operations', identity):
                    break
                operation = ctx.operations[identity]
                operations = (*operations, operation)
                drive = ctx.drives.get(identity)
                if drive is not None:
                    self.finish_path(item, operations, choices, invocations, current, drive=drive)
                    break
                for access in operation.accesses:
                    if access.after is not None:
                        current[access.location] = access.after
                for value in operation.results:
                    record = ctx.values[value]
                    if isinstance(record, StateVersionValue):
                        current[record.location] = value
                terminator = operation.terminator
                if terminator is None:
                    continue
                if terminator.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
                    self.finish_path(item, operations, choices, invocations, current,
                                     terminal=HostTerminal(identity))
                    break
                if terminator.kind not in (TerminatorKind.JUMP, TerminatorKind.BRANCH, TerminatorKind.INVOKE):
                    self.boundary('async_request_path_control_unresolved', item, operation, choices)
                    self.finish_path(item, operations, choices, invocations, current, unresolved=True)
                    break
                for number, successor in reversed(tuple(enumerate(terminator.successors))):
                    if not self.spend('edges', identity):
                        break
                    edge = ControlEdgeReference(identity, number)
                    selected = (*choices, edge)
                    own = (self.invocation(operation, edge, successor),) if terminator.kind is TerminatorKind.INVOKE else ()
                    pending.append((successor.block, selected, ancestors, operations,
                                    (*invocations, *own), current))
                break
            if ctx.budget.truncated:
                self.complete = False
                self.cursor = self.cursor or {'phase': 'path', 'operation': block.operations[-1]}
                break


def request_no_drive_paths(index, scope=None, *, budget=4096):
    """Enumerate a supplied local driver CFG through first Drive/host only.

    ``declared_no_drive`` never proves that native/callee internals did not
    execute a body. This independent query owns its budget; legacy async
    reports only prepare the original inventory and do not run this walk.
    """
    from scar.ir.execution.validity_budget import ValidityBudget
    from .protocol_connection_flow import ConnectionContext
    shared = ValidityBudget(budget)
    ctx = ConnectionContext(index.graph, index=index, budget=shared)
    inventory = request_no_drive_inventory(ctx)
    if scope is not None:
        declaration = ctx.scopes[scope]
        if (declaration.profile is not ProtocolProfile.ASYNC_GENERATOR_BODY_V1
                or type(declaration.subject) is not DriverSubject):
            raise ValueError('request paths require an async driver scope')
        inventory = tuple(row for row in inventory if row['key'] == declaration.subject.interface_region)
    walk = _Walk(ctx)
    for item in inventory:
        walk.walk(item)
        if shared.truncated:
            break
    complete = walk.complete and not shared.truncated
    gaps = tuple(walk.gaps) + (({'code': 'async_request_path_budget_exhausted',
                               'cursor': walk.cursor},) if shared.truncated else ())
    return {'inventory': inventory, 'paths': tuple(walk.paths),
        'boundaries': tuple(walk.boundaries), 'issues': tuple(walk.issues), 'gaps': gaps,
        'status': 'DECLARED' if complete else 'PARTIAL' if walk.paths else 'NOT_CHECKED',
        'known_inventory_complete': complete,
        'paths_total': len(walk.paths) if complete else None,
        'cursor': walk.cursor, 'closed_body_effects': False,
        'budget': {'limit': shared.limit, 'used': shared.used,
                   'costs': dict(shared.costs), 'truncated': shared.truncated},
        'preparation': dict(ctx.preparation), 'conditions': _CONDITIONS, **_FLAGS}


__all__ = ['request_no_drive_inventory', 'request_no_drive_paths']
