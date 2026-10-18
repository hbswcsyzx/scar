"""Conditional async/request/cancellation connections on original program ports.

This module consumes one shared ConnectionContext.  Semantic request/Task
projections remain declarations; they never enter the ordinary copy closure.
Missing source/collection is distinct from a known wrong core connection.
"""
from .control import ProtocolValueKind
from .drivers import BodyResume
from .lifecycle import DriveOutcomeRef, SessionPost
from .model import (AccessMode, BlockArgument, DataValue, ExitKind, InvokeLiteralResult,
                    OperationResult, ProtocolValue, ReferenceValue, StateVersionValue,
                    TerminatorKind)
from .protocols import (ContractResult, DriverSubject, OwnedUse, ProtocolCall,
                        ProtocolCallRule, ProtocolClause, ProtocolProfile, StaticProtocolGap)
from .resumption import ResumeSlotKind, SuspendTerminator, SuspensionFlavor
from .state_addresses import ExistingAccess, InvokeStateOperand
from .structured import ControlEdgeReference


def _binding_key(row):
    return row.scope, row.expected_target, row.packet_source, row.consumer


class _Analysis:
    def __init__(self, ctx, *, prepare=True):
        self.ctx = ctx
        self.issues, self.gaps, self.obligations = [], [], []
        self.associations, self.sessions, self.cancellation = [], [], []
        self.deliveries = []
        self.admissions = []
        self.cursor = None
        # A single predicate view needs local diagnostics and port helpers,
        # not another scan of the complete family inventory.
        if not prepare:
            return
        from .protocol_connections import RequestStateCondition, RequestStateRule
        from .protocols import AdmissionPredicate
        self.rows_by_operation = {}
        initial = getattr(ctx, '_async_initial_predicates', None)
        building_initial = initial is None
        if building_initial:
            initial = {}
        for row in ctx.graph.protocol_operations:
            self.rows_by_operation.setdefault(row.operation, []).append(row)
            if (building_initial and type(row.contract) is AdmissionPredicate
                    and type(row.contract.subject) is RequestStateCondition
                    and row.contract.subject.rule is RequestStateRule.IS_INITIAL_STEP):
                initial.setdefault(row.scope, []).append(row)
        if building_initial:
            initial = ctx._async_initial_predicates = {scope: tuple(rows) for scope, rows in initial.items()}
            ctx.preparation['async_initial_predicate_index_rows'] = len(ctx.graph.protocol_operations)
            ctx.preparation['async_initial_predicates'] = sum(len(rows) for rows in initial.values())
        self.initial_predicates = initial
        self.creates = {row.operation: row for row in ctx.graph.async_request_creates}
        markers, updates, bindings, gates = {}, {}, {}, {}
        for gate in ctx.graph.final_body_gates:
            gates.setdefault(ctx.region_of.get(gate.operation), []).append(gate)
        for marker in ctx.graph.request_association_reads:
            markers.setdefault(ctx.region_of.get(marker.operation), []).append(marker)
        for update in ctx.graph.session_updates:
            updates.setdefault(ctx.region_of.get(update.operation), []).append(update)
        for binding in ctx.graph.protocol_bindings:
            scope = getattr(binding, 'scope', getattr(getattr(binding, 'delivery', None), 'scope', None))
            bindings.setdefault(scope, []).append(binding)
        # Preparation inventories original rows only; semantic traversal below
        # remains budgeted. The denominator survives even budget=1.
        self.inventory = tuple({'scope': scope,
            'drives': tuple(ctx.drives_by_region.get(getattr(scope.subject, 'interface_region', getattr(scope.subject, 'region', None)), ())),
            'associations': tuple(markers.get(getattr(scope.subject, 'interface_region', getattr(scope.subject, 'region', None)), ())),
            'updates': tuple(updates.get(getattr(scope.subject, 'interface_region', getattr(scope.subject, 'region', None)), ())),
            'gates': tuple(gates.get(getattr(scope.subject, 'interface_region', getattr(scope.subject, 'region', None)), ())),
            'bindings': tuple(bindings.get(scope.id, ()))} for scope in ctx.scopes.values()
            if scope.profile in (ProtocolProfile.ASYNC_GENERATOR_BODY_V1, ProtocolProfile.TASK_CANCEL_EXTERNAL_V1))

    def request_admission(self, scope):
        """Keep every original gate before looking for predicate attachments."""
        from .protocol_connections import RequestStateCondition
        from .protocols import AdmissionPredicate
        rows = tuple(row for row in self.ctx.graph.protocol_operations if row.scope == scope.id
            and type(row.contract) is AdmissionPredicate and type(row.contract.subject) is RequestStateCondition)
        inventory = next(item for item in self.inventory if item['scope'] is scope)
        for gate in inventory['gates']:
            path = f'async.request_admission.{gate.operation}'
            candidates, cursor, gaps = [], None, []
            if not self.spend('request_admission_gates', path):
                cursor = {'phase': 'request_admission', 'gate': gate.operation, 'predicate_ordinal': 0}
            else:
                for number, row in enumerate(rows):
                    if not self.spend('request_admission_predicates', path):
                        cursor = {'phase': 'request_admission', 'gate': gate.operation, 'predicate_ordinal': number}
                        break
                    view = request_state_view(self.ctx, row)
                    for frontier in view['control_routes']['frontiers']:
                        if not self.spend('request_admission_frontiers', path):
                            cursor = {'phase': 'request_admission', 'gate': gate.operation, 'predicate_ordinal': number}
                            break
                        if frontier.get('gate') is gate:
                            candidates.append({'predicate': row, 'view': view, 'frontier': frontier})
                            code = ('async_request_complete_success_incompatible_at_snapshot'
                                if frontier['request_target_compatible_at_snapshot'] is False else
                                'async_request_admission_snapshot_unresolved' if frontier['currentness'] is not True else None)
                            if code is not None:
                                gaps.append(self.gap(code, path, predicate=row.operation, edge=frontier['edge']))
                    if self.ctx.budget.truncated:
                        cursor = cursor or {'phase': 'request_admission', 'gate': gate.operation, 'predicate_ordinal': number}
                        break
            if cursor is not None:
                status = 'PARTIAL' if candidates else 'NOT_CHECKED'
                if self.cursor is None:
                    self.cursor = cursor
            elif not candidates:
                status = 'MISSING'
                gaps.append(self.gap('async_request_admission_predicate_missing', path))
            else:
                status = ('PARTIAL' if any(item['view']['gaps'] or
                    item['frontier']['request_target_compatible_at_snapshot'] is not True
                    for item in candidates) else 'DECLARED')
            result = {'scope': scope.id, 'gate': gate, 'operation': self.ctx.operations[gate.operation],
                'drive': self.ctx.drives[gate.drive], 'predicate_count': len(rows),
                'candidates': tuple(candidates), 'status': status, 'cursor': cursor, 'gaps': tuple(gaps),
                'native_admission_verified': False, 'transformation_authorized': False}
            self.admissions.append(result)
            self.obligations.append({'scope': scope.id, 'clause': ProtocolClause.ASYNC_REQUEST_SOURCE,
                'operation': gate.operation, 'gate': gate, 'admission': result, 'status': status})

    def request_projection(self, request, path):
        """Conditional field recipes rooted at R, not at the actual body."""
        origins = self.ctx.origins(request)
        projections = []
        for recipe in origins['recipes']:
            if not self.spend('request_origins', path):
                break
            source = recipe['origin']
            if type(source) is not InvokeLiteralResult or source.edge.operation not in self.creates:
                continue
            create = self.creates[source.edge.operation]
            operation = self.ctx.operations[create.operation]
            edge = operation.terminator.successors[source.edge.successor_index]
            if edge.kind is not ExitKind.NORMAL or source.result.index != create.request_result.index:
                continue
            body, latent = OwnedUse(operation.id, create.body), OwnedUse(operation.id, create.latent)
            self.use(body, actual=True)
            self.use(latent, actual=True)
            context = self.ctx.recipe_context(recipe)
            raw = self.ctx.origins(latent)
            definitions = []
            for candidate in raw['recipes']:
                for detail in candidate['raw_requests']:
                    if not self.spend('latent_origins', path):
                        break
                    extended = self.ctx.extend_context(candidate, latent, recipe)
                    definitions.append({**detail, 'recipe': candidate, 'context': extended})
            projections.append({'create': create, 'request_result': source, 'request_recipe': recipe,
                'body_input': body, 'latent_input': latent, 'raw_requests': tuple(definitions),
                'context': context, 'conditions': ('stored request projection implementation unproved',)})
        if not projections:
            self.gap('async_request_origin_unresolved', path)
        return tuple(projections)

    def packet_delivery(self, scope, definition, projection, actual, path):
        from .drivers import RawRequestKind
        from .protocols import RequestProcessing, RequestProcessingRule
        wanted = ((RequestProcessingRule.NORMALIZE_GENERATOR_EXIT,) if definition.kind is RawRequestKind.CLOSE else
                  (RequestProcessingRule.NORMALIZE_ASYNC_THROW, RequestProcessingRule.NORMALIZE_THROW_INSTANCE,
                   RequestProcessingRule.NORMALIZE_THROW_CLASS))
        matches = []
        for row in self.ctx.graph.protocol_operations:
            if row.scope != scope.id or type(row.contract) is not RequestProcessing or row.contract.rule not in wanted:
                continue
            if not self.spend('packet_processors', path):
                break
            result = row.contract.result
            if type(result) is InvokeLiteralResult:
                edge = self.ctx.operations[result.edge.operation].terminator.successors[result.edge.successor_index]
                if edge.kind is not ExitKind.NORMAL:
                    continue
            if self.ctx.reaches(result, actual.operation) is False:
                continue
            raw = OwnedUse(row.operation, row.contract.raw_use)
            # R's original association projection selects L; S cannot replace
            # that role merely because it has the same RAW type.
            latent = self.ctx.bind(projection['latent_projection'], raw, path=path)
            delivered = self.ctx.bind(result, actual, path=path)
            port = self.ctx.port(result)
            if port is not None and port.gap is None and any(
                    not isinstance(self.ctx.values[value], ProtocolValue)
                    or self.ctx.values[value].protocol is not ProtocolValueKind.EXCEPTION_PACKET for value in port.values):
                self.gap('async_normalized_packet_construction_unresolved', path, processing=row)
                continue
            report = self.ctx.correlate({'match': projection['context']['match'],
                'routes': (projection['context'],), 'gaps': (), 'cursor': None}, latent, delivered)
            matches.append({'processing': row, 'latent': latent, 'delivered': delivered, 'binding': report,
                            'match': report['match']})
        flags = tuple(row['match'] for row in matches)
        match = (False if flags and all(value is False for value in flags) else
                 True if flags and all(value is True for value in flags) else None)
        if match is None:
            self.gap('async_latent_packet_normalization_unresolved', path, definition=definition)
        return {'definition': definition, 'projection': projection, 'actual': actual,
                'normalizations': tuple(matches), 'match': match,
                'conditions': ('normalization class/callback semantics unproved',)}

    def initial_step(self, scope, drive):
        selected = []
        for row in self.initial_predicates.get(scope.id, ()):
            if not self.spend('initial_step_predicates', drive.operation):
                return None
            view = request_state_view(self.ctx, row)
            if self.ctx.budget.truncated:
                if self.cursor is None:
                    self.cursor = {'path': str(drive.operation), 'phase': 'initial_step_predicate_view'}
                return None
            for frontier in view['control_routes']['frontiers']:
                if not self.spend('initial_step_frontiers', drive.operation):
                    return None
                if frontier.get('drive') == drive:
                    truth = frontier['edge'].successor_index == 0
                    selected.append(truth)
                    if not frontier['read_snapshot_current']:
                        self.gap('async_initial_selection_snapshot_changed', row.operation,
                            frontier=frontier, current_gate_authorized=False)
        if selected and all(value is selected[0] for value in selected):
            return selected[0]
        return None

    def request_delivery(self, scope, drive, projections, path):
        from .drivers import RawRequestKind
        from .driver_flow import body_drive_target
        if type(drive.target) is not BodyResume:
            return
        first = self.initial_step(scope, drive)
        if first is None:
            self.gap('async_request_step_source_unresolved', path, first_step=first)
            return
        if first is False:
            scheduler = self.ctx.origins(OwnedUse(drive.operation, drive.scheduler_request))
            definitions = tuple({**detail, 'recipe': recipe} for recipe in scheduler['recipes']
                                for detail in recipe['raw_requests'])
            projections = ({'raw_requests': definitions, 'context': None, 'scheduler': True},)
        _, _, ingress = body_drive_target(self.ctx.graph, drive)
        for item in drive.resume_inputs:
            if not self.spend('delivery_slots', path):
                break
            slot = ingress.inputs[item.slot]
            actual = OwnedUse(drive.operation, item.source)
            alternatives = []
            for projection in projections:
                for raw in projection['raw_requests']:
                    if not self.spend('latent_deliveries', path):
                        break
                    definition = raw['definition']
                    current_projection = projection
                    if first and 'context' in raw:
                        context = self.ctx.correlate({'match': projection['context']['match'],
                            'routes': (projection['context'],), 'gaps': (), 'cursor': None},
                            {'match': raw['context']['match'], 'routes': (raw['context'],),
                             'gaps': raw['context']['gaps'], 'cursor': None})
                        current_projection = {**projection, 'context': {
                            **raw['context'], 'match': context['match']}}
                    if definition.kind in (RawRequestKind.THROW, RawRequestKind.CLOSE):
                        if slot.kind is not ResumeSlotKind.THROWN_PACKET:
                            self.issue('async_delivery_slot', path, 'THROW/CLOSE requires the original THROWN_PACKET slot')
                            continue
                        if first:
                            alternatives.append(self.packet_delivery(scope, definition, current_projection, actual, path))
                        else:
                            self.gap('async_scheduler_packet_normalization_unresolved', path, definition=definition)
                            alternatives.append({'definition': definition, 'match': None, 'actual': actual})
                        continue
                    if slot.kind is not ResumeSlotKind.SENT_VALUE:
                        self.issue('async_delivery_slot', path, 'NEXT/SEND latent request needs its exact SENT_VALUE slot')
                        continue
                    if definition.kind is RawRequestKind.SEND:
                        pack = self.ctx.values[definition.value].origin.operation
                        expected = OwnedUse(pack, definition.operands[0])
                        delivery = self.ctx.bind(expected, actual, path=path)
                        result = (self.ctx.correlate({'match': current_projection['context']['match'],
                            'routes': (current_projection['context'],), 'gaps': (), 'cursor': None}, delivery)
                            if first else delivery)
                    else:
                        # Fixed NEXT semantics demands None. This comparison
                        # inspects existing literal facts, never invents one.
                        from .request_inputs import _none_content
                        view = self.ctx.origins(actual)
                        contexts = []
                        for recipe in view['recipes']:
                            if not self.spend('next_sources', path):
                                break
                            context = self.ctx.recipe_context(recipe)
                            context['match'] = _none_content(recipe)
                            contexts.append(context)
                        flags = tuple(route['match'] for route in contexts)
                        match = False if flags and all(value is False for value in flags) else True if flags and all(value is True for value in flags) else None
                        report = {'match': match, 'routes': tuple(contexts), 'gaps': view['gaps'], 'cursor': view['cursor']}
                        result = (self.ctx.correlate({'match': current_projection['context']['match'],
                            'routes': (current_projection['context'],), 'gaps': (), 'cursor': None},
                            report) if first else report)
                    alternatives.append({'definition': definition, 'projection': projection,
                                         'actual': actual, 'binding': result, 'match': result['match']})
            if alternatives and all(item['match'] is False for item in alternatives):
                self.issue('async_delivery_source', path, 'no contextual latent request supplies this actual delivery')
            elif not alternatives or not all(item['match'] is True for item in alternatives):
                self.gap('async_delivery_source_unresolved', path)
            self.deliveries.append({'scope': scope.id, 'drive': drive, 'slot': item.slot,
                'actual': actual, 'initial_step': first, 'alternatives': tuple(alternatives),
                'selection_basis': 'ORIGINAL_PREDICATE_EDGE', 'current_step_verified': False,
                'conditions': ('historical branch selects the declared source, not current phase or gate admission',)})

    def spend(self, kind, path):
        if self.ctx.spend('async_' + kind):
            return True
        self.gap('protocol_budget_exhausted', path)
        if self.cursor is None:
            self.cursor = {'path': path, 'phase': kind}
        return False

    def issue(self, code, path, message):
        self.issues.append((code, str(path), message))

    def gap(self, code, path, **details):
        result = {'code': code, 'path': str(path), **details}
        self.gaps.append(result)
        return result

    def check(self, result, code, path):
        if result['match'] is False:
            self.issue(code, path, 'original consumer differs from its independently declared source')
        elif result['match'] is None:
            self.gap(code + '_unresolved', path, binding=result)
        return result

    def bind(self, expected, actual, code, path):
        return self.check(self.ctx.bind(expected, actual, path=str(path)), code, path)

    def use(self, owned, *, actual=False):
        use = self.ctx.owned_use(owned.operation, owned.use)
        operation = self.ctx.operations[owned.operation]
        if actual:
            arguments = operation.invoke_arguments if operation.terminator is not None else operation.call_arguments
            if (operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
                    or operation.callee is not None) and use.id not in arguments:
                raise ValueError('role is an edge forward, not an original call operand')
        return use

    def port(self, source, *, owner=None, normal=False, reference=False):
        port = self.ctx.port(source)
        if port is None or port.gap is not None:
            return port
        if owner is not None and port.operation != owner:
            raise ValueError('port belongs to another original operation')
        if normal and type(source) is InvokeLiteralResult:
            edge = self.ctx.operations[port.operation].terminator.successors[port.edge]
            if edge.kind is not ExitKind.NORMAL:
                raise ValueError('association/Task result must be an actual NORMAL result')
        if reference and (not port.values or any(not isinstance(self.ctx.values[value], ReferenceValue)
                                                 for value in port.values)):
            raise ValueError('role requires an original Reference result')
        return port

    def actual_states(self, operation):
        return {self.ctx.values[use.value].location: OwnedUse(operation.id, use.id)
                for use in operation.uses if isinstance(self.ctx.values[use.value], StateVersionValue)
                and (operation.terminator is None or operation.terminator.kind is not TerminatorKind.INVOKE
                     or use.id in operation.invoke_arguments)}

    def site(self, site):
        operation = self.ctx.operations[site.operation]
        if type(site) is ExistingAccess:
            access = operation.accesses[site.index]
            return access.location, access
        if type(site) is InvokeStateOperand:
            use = self.use(OwnedUse(site.operation, site.state_use), actual=True)
            value = self.ctx.values[use.value]
            if not isinstance(value, StateVersionValue) or operation.terminator is None or operation.terminator.kind is not TerminatorKind.INVOKE:
                raise ValueError('state site is not an original INVOKE state input')
            return value.location, None
        raise TypeError('state site requires its exact original typed reference')

    def support(self, sites, consumer, path, *, after=False, completion=None):
        states, support = self.actual_states(consumer), []
        for number, site in enumerate(sites):
            if not self.spend('state_sites', f'{path}.{number}'):
                break
            location, access = self.site(site)
            actual = states.get(location)
            if actual is not None and type(site) is InvokeStateOperand and after and completion is not None:
                operation = self.ctx.operations[site.operation]
                edge = operation.terminator.successors[completion.successor_index]
                signature = next(row for row in operation.completions if row.kind is edge.kind)
                positions = [index for index, type_ in enumerate(signature.types)
                             if getattr(type_, 'location', None) == location]
                from .model import CompletionResult
                result = (self.ctx.bind(InvokeLiteralResult(completion, CompletionResult(positions[0])), actual,
                                       path=str(path)) if len(positions) == 1 else
                          {'match': None, 'gaps': ('completion_state_port_unavailable',), 'routes': (), 'conditions': ()})
            else:
                result = (self.ctx.current(site, actual, after=after and (access is None or access.after is not None), path=str(path)) if actual is not None
                          else {'match': None, 'gaps': ('state_consumer_port_unavailable',), 'routes': (), 'conditions': ()})
            # A historical read is legal; no current association is inferred
            # across a callback/unknown write just because its bool survived.
            if result['match'] is not True:
                self.gap('async_current_support_unresolved', path, site=site, support=result)
            support.append({'site': site, 'access': access, 'actual': actual, 'binding': result})
        return tuple(support)

    def formal(self, region, value):
        entry = self.ctx.blocks[self.ctx.regions[region].entry]
        return BlockArgument(entry.id, entry.arguments.index(value))

    def correspond(self, expected, actual, path):
        result = self.ctx.bind(expected, actual, path=str(path))
        # Both are observations of an original reference, not producers.
        # A task association may be read before cancel() itself is called.
        if result['match'] is False and type(expected) is OwnedUse:
            reverse = self.ctx.bind(actual, expected, path=str(path))
            if reverse['match'] is True:
                return reverse
            if reverse['match'] is None:
                return reverse
        return result

    def request_associations(self, scope):
        from .protocol_connections import RequestAssociation
        interface = self.ctx.interfaces[scope.subject.interface_region]
        region = interface.region
        rows = [row for row in self.ctx.graph.protocol_operations
                if row.scope == scope.id and type(row.contract) is RequestAssociation]
        markers = [row for row in self.ctx.graph.request_association_reads
                   if self.ctx.region_of[row.operation] == region]
        declarations = []
        marked = set()
        for marker in markers:
            operation = self.ctx.operations[marker.operation]
            number = next(i for i, edge in enumerate(operation.terminator.successors) if edge.kind is ExitKind.NORMAL)
            from .model import CompletionResult
            body = InvokeLiteralResult(ControlEdgeReference(operation.id, number), CompletionResult(marker.body_result.index))
            latent = InvokeLiteralResult(ControlEdgeReference(operation.id, number), CompletionResult(marker.latent_result.index))
            sites = tuple(InvokeStateOperand(operation.id, use.id) for use in operation.uses
                          if use.id in operation.invoke_arguments and isinstance(self.ctx.values[use.value], StateVersionValue))
            declarations.append((marker, RequestAssociation(marker.request, body, latent, sites)))
            marked.add(operation.id)
            for row in rows:
                if row.operation == operation.id and (row.contract.request_use, row.contract.body, row.contract.latent) != (marker.request, body, latent):
                    self.issue('async_association_marker', operation.id, 'attachment contradicts the original RequestAssociationRead ports')
        declarations.extend((row, row.contract) for row in rows if row.operation not in marked)
        views = []
        for declaration, contract in declarations:
            operation = self.ctx.operations[declaration.operation]
            path = f'async.association.{operation.id}'
            if not self.spend('associations', path):
                break
            try:
                request = OwnedUse(operation.id, contract.request_use)
                use = self.use(request, actual=True)
                if not isinstance(self.ctx.values[use.value], ReferenceValue):
                    raise ValueError('request projection input requires Reference')
                receiver = self.bind(self.formal(region, interface.receiver), request, 'async_request_source', path)
                projections = self.request_projection(request, path)
                body = self.port(contract.body, owner=operation.id, normal=True, reference=True)
                latent = self.port(contract.latent, owner=operation.id, normal=True)
                if body is not None and body.gap is not None or latent is not None and latent.gap is not None:
                    self.gap('async_association_projection_unresolved', path)
                if latent is not None and latent.gap is None and (not latent.values or any(
                        not isinstance(self.ctx.values[value], ProtocolValue)
                        or self.ctx.values[value].protocol is not ProtocolValueKind.RAW_DRIVER_REQUEST for value in latent.values)):
                    raise ValueError('latent projection requires the original RAW_DRIVER_REQUEST role')
                if type(contract.body) is InvokeLiteralResult and type(contract.latent) is InvokeLiteralResult and contract.body.edge != contract.latent.edge:
                    raise ValueError('body and latent projections select different completion edges')
                if body is not None and latent is not None and body.gap is None and latent.gap is None and body.values == latent.values:
                    raise ValueError('body/latent projections require different original result roles')
                view = {'scope': scope, 'declaration': declaration, 'operation': operation, 'request': request,
                        'receiver': receiver, 'body': contract.body, 'latent': contract.latent,
                        'projections': projections,
                        'state_sites': contract.state_sites, 'gates': [],
                        'conditions': ('request association implementation and runtime object identity unproved',)}
                for drive in self.ctx.drives_by_region.get(region, ()):
                    if not self.spend('association_gates', path):
                        break
                    gate = next(row for row in self.ctx.graph.final_body_gates if row.drive == drive.operation)
                    gate_op = self.ctx.operations[gate.operation]
                    if type(contract.body) is not StaticProtocolGap and self.ctx.reaches(contract.body, gate.operation) is False and operation.id != gate.operation:
                        continue
                    actual = OwnedUse(gate.operation, gate_op.invoke_arguments[gate.body_argument])
                    # Each independent projection remains a candidate. A second
                    # fresh read of the same R need not copy the first result.
                    binding = self.ctx.bind(contract.body, actual, path=path)
                    if type(contract.latent) is OwnedUse and contract.latent == OwnedUse(gate.operation, gate_op.invoke_arguments[gate.scheduler_argument]):
                        self.issue('async_latent_scheduler_role', path, 'scheduler role cannot stand in for latent projection')
                    completion = contract.body.edge if type(contract.body) is InvokeLiteralResult else None
                    current = self.support(contract.state_sites, gate_op, path, after=True, completion=completion)
                    view['gates'].append({'drive': drive, 'gate': gate, 'body_binding': binding, 'state_support': current})
                view['gates'] = tuple(view['gates'])
                views.append(view)
            except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
                self.issue('async_association_reference', path, str(exc))
        for drive in self.ctx.drives_by_region.get(region, ()):
            candidates = tuple((view, gate) for view in views for gate in view['gates'] if gate['drive'].operation == drive.operation)
            matches = tuple(gate['body_binding']['match'] for _, gate in candidates)
            if not candidates:
                self.gap('async_request_association_missing', drive.operation)
            elif all(match is False for match in matches):
                self.issue('async_body_source', drive.operation, 'no applicable independent request projection supplies this body')
            elif True not in matches:
                self.gap('async_body_source_unresolved', drive.operation)
            self.obligations.append({'scope': scope.id, 'clause': ProtocolClause.ASYNC_REQUEST_ASSOCIATE,
                                     'operation': drive.operation, 'candidates': candidates,
                                     'status': 'DECLARED' if True in matches else 'NOT_CHECKED' if self.ctx.budget.truncated else 'MISSING' if not candidates else 'PARTIAL'})
            projections = tuple({**projection, 'latent_projection': view['latent']} for view, gate in candidates
                                if gate['body_binding']['match'] is True for projection in view['projections'])
            self.request_delivery(scope, drive, projections, str(drive.operation))
        self.associations.extend(views)

    def session_outcomes(self, scopes):
        from .protocol_connections import AsyncSessionOutcome
        bindings = [row for row in self.ctx.graph.protocol_bindings if type(row) is AsyncSessionOutcome]
        updates = {row.operation: row for row in self.ctx.graph.session_updates}
        indexed = {(row.scope, row.update, row.source): row for row in bindings}
        for row in bindings:
            path = f'async.session.{row.update}'
            if not self.spend('session_bindings', path):
                break
            try:
                scope = self.ctx.scopes[row.scope]
                update = updates[row.update]
                if scope.profile is not ProtocolProfile.ASYNC_GENERATOR_BODY_V1 or self.ctx.region_of[row.update] != scope.subject.interface_region:
                    raise ValueError('session source requires this exact enabled async driver')
                operation = self.ctx.operations[update.operation]
                if type(row.source) is DriveOutcomeRef:
                    drive = self.ctx.drives[row.source.drive]
                    if self.ctx.region_of[drive.operation] != scope.subject.interface_region or drive.session is None:
                        raise ValueError('session source selects another driver/body receiver')
                    from .protocols import DriveResult
                    source = self.ctx.port(DriveResult(row.source, 0))
                    body = self.ctx.operations[row.source.source]
                    kind = body.terminator.kind
                    expected = (SessionPost.HOLD if type(body.terminator) is SuspendTerminator and body.terminator.flavor is SuspensionFlavor.AWAIT
                                else SessionPost.COMPLETE if kind in (TerminatorKind.RETURN, TerminatorKind.RAISE)
                                or type(body.terminator) is SuspendTerminator and body.terminator.flavor is SuspensionFlavor.ASYNC_YIELD else None)
                    from .protocols import OutcomeAdapter, OutcomeAdapterRule
                    close_failure = any(candidate.scope == scope.id and type(candidate.contract) is OutcomeAdapter
                        and candidate.contract.rule is OutcomeAdapterRule.ASYNCGEN_CLOSE_YIELD_ERROR
                        and getattr(candidate.contract.input, 'outcome', None) == row.source
                        for candidate in self.ctx.graph.protocol_operations)
                    if close_failure:
                        expected = None
                        self.gap('async_close_failure_session_unresolved', path)
                    if kind is TerminatorKind.RETURN:
                        self.gap('async_return_source_classification_unproved', path)
                        from .driver_flow import body_outcome_uses
                        from .request_inputs import _none_content
                        actuals = body_outcome_uses(body)
                        if actuals:
                            payload = self.ctx.origins(OwnedUse(body.id, actuals[0]))
                            known = tuple(_none_content(recipe) for recipe in payload['recipes'])
                            if False in known:
                                self.issue('async_return_value', body.id,
                                    'async-generator Return has a known non-None payload')
                            elif not known or None in known:
                                self.gap('async_return_payload_unproved', body.id)
                    elif kind is TerminatorKind.RAISE:
                        self.gap('async_terminal_exception_classification_unproved', path)
                    if expected is not None and update.post is not expected:
                        self.issue('async_session_post', path, 'session post differs from the exact async outcome')
                    interface = self.ctx.interfaces[scope.subject.interface_region]
                    request_source = self.formal(interface.region, interface.receiver)
                    self.bind(request_source, OwnedUse(drive.operation, drive.session), 'async_session_request', path)
                    self.bind(request_source, OwnedUse(update.operation, update.request), 'async_session_request', path)
                    self.bind(OwnedUse(drive.operation, drive.instance), OwnedUse(update.operation, update.body), 'async_session_body', path)
                    if source is not None and self.ctx.reaches(source.source, operation.id) is False:
                        self.issue('async_session_source', path, 'selected outcome cannot reach this update')
                else:
                    source = self.ctx.port(row.source)
                    self.gap('async_session_helper_semantics_unproved', path)
                self.sessions.append({'binding': row, 'update': update, 'operation': operation, 'source': source,
                                      'conditions': ('native session update applicability unproved',)})
            except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
                self.issue('async_session_reference', path, str(exc))
        for scope in scopes:
            region = scope.subject.interface_region
            for update in updates.values():
                if self.ctx.region_of[update.operation] != region:
                    continue
                for drive in self.ctx.drives_by_region.get(region, ()):
                    for edge in self.ctx.operations[drive.operation].terminator.successors:
                        if not self.spend('session_sources', str(update.operation)):
                            break
                        from .protocols import DriveResult
                        outcome = DriveOutcomeRef(drive.operation, edge.source)
                        if self.ctx.reaches(DriveResult(outcome, 0), update.operation) is False:
                            continue
                        binding = indexed.get((scope.id, update.operation, outcome))
                        self.obligations.append({'scope': scope.id, 'clause': ProtocolClause.ASYNC_ITEM_ADAPTER,
                            'operation': update.operation, 'source': outcome, 'binding': binding,
                            'status': 'DECLARED' if binding else 'MISSING'})
                        if binding is None:
                            self.gap('async_session_outcome_missing', update.operation, outcome=outcome)

    def cancel_task(self, scope):
        rows = [row for row in self.rows_by_operation.get(scope.subject.operation, ())
                if row.scope == scope.id and type(row.contract) is ProtocolCall
                and row.contract.rule is ProtocolCallRule.TASK_CANCEL_CALL]
        if not rows:
            self.gap('cancel_request_site_unbound', scope.id)
            return None
        uses = {row.contract.receiver_use for row in rows}
        if len(uses) != 1:
            raise ValueError('cancel request results disagree on their actual task receiver')
        result = OwnedUse(scope.subject.operation, next(iter(uses)))
        self.use(result, actual=True)
        return result

    def cancel_target(self, scope, expected, actual, path):
        from .protocol_connections import TaskCreatedTarget, TaskTargetRead, TaskTargetRole
        task = self.cancel_task(scope)
        if type(expected) is StaticProtocolGap:
            self.gap('cancel_task_identity_unmodeled', path)
            return None
        if type(expected) is TaskCreatedTarget:
            port = self.port(expected.task_result, normal=True, reference=True)
            if port is None or port.gap is not None:
                self.gap('cancel_task_creation_unresolved', path)
                return None
            self.use(expected.body_use, actual=True)
            if expected.body_use.operation != port.operation:
                raise ValueError('Task result and stored body input are not one original creation')
            if task is not None:
                self.bind(expected.task_result, task, 'cancel_task_source', path)
            result = self.ctx.bind(expected.body_use, actual, path=path)
        elif type(expected) is TaskTargetRead:
            self.use(expected.task, actual=True)
            self.port(expected.target, owner=expected.task.operation, normal=True, reference=True)
            if any(site.operation != expected.task.operation for site in expected.state_sites):
                raise ValueError('Task target read support must name its own original state ports')
            if task is not None:
                self.check(self.correspond(task, expected.task, path), 'cancel_task_source', path)
            result = self.ctx.bind(expected.target, actual, path=path)
            completion = expected.target.edge if type(expected.target) is InvokeLiteralResult else None
            support = self.support(expected.state_sites, self.ctx.operations[actual.operation], path, after=True, completion=completion)
            if not support or any(item['binding']['match'] is not True for item in support):
                self.gap('cancel_target_current_support_unresolved', path, support=support)
                if result['match'] is True:
                    result = {**result, 'match': None}
            if expected.role is TaskTargetRole.CURRENT_AWAITED:
                if not support:
                    self.gap('cancel_current_awaited_support_unresolved', path)
                if result['match'] is not True:
                    self.gap('cancel_waiter_forwarding_unresolved', path, binding=result)
                    result = {**result, 'match': None}
        else:
            raise TypeError('cancel target requires its exact typed Task interface')
        if type(expected.interface) is StaticProtocolGap:
            self.gap('cancel_target_interface_unresolved', path)
        self.check(result, 'cancel_target_source', path)
        return result

    def delivery_receiver(self, consumer):
        operation = self.ctx.operations[consumer.operation]
        self.use(consumer, actual=True)
        drive = self.ctx.drives.get(operation.id)
        if drive is not None:
            if type(drive.target) is not BodyResume:
                raise ValueError('cancel packet cannot be injected into BodyStart')
            from .driver_flow import body_drive_target
            _, _, ingress = body_drive_target(self.ctx.graph, drive)
            candidates = [item for item in drive.resume_inputs if item.source == consumer.use]
            if len(candidates) != 1 or ingress.inputs[candidates[0].slot].kind is not ResumeSlotKind.THROWN_PACKET:
                raise ValueError('cancel consumer is not the exact THROWN_PACKET input')
            return OwnedUse(operation.id, drive.instance), True
        candidates = [row.contract for row in self.rows_by_operation.get(operation.id, ())
                      if type(row.contract) is ProtocolCall and consumer.use in row.contract.argument_uses
                      and row.contract.rule is ProtocolCallRule.DELEGATE_THROW]
        if len(candidates) != 1:
            self.gap('cancel_delivery_consumer_unbound', consumer.operation)
            return None, False
        return OwnedUse(operation.id, candidates[0].receiver_use), False

    def cancel_terminals(self, delivery, path):
        """Derive propagation of the injected packet; no 'handled' flag."""
        from .protocols import DriveResult
        from .protocol_validation import host_output_copy, host_terminals
        drive = self.ctx.drives.get(delivery.consumer.operation)
        if drive is None:
            return ()
        expected = None
        for binding in self.ctx.index.drive_input_bindings(drive.operation):
            if getattr(getattr(binding.source, 'use', None), 'id', None) == delivery.consumer.use:
                expected = self.ctx.values[binding.formal].origin
                break
        routes = []
        for edge in self.ctx.operations[drive.operation].terminator.successors:
            if not self.spend('cancel_terminal_sources', path):
                break
            body = self.ctx.operations[edge.source]
            if body.terminator.kind is not TerminatorKind.RAISE:
                continue
            packet_uses = tuple(use for use in body.uses if use.id in body.terminator.values
                and isinstance(self.ctx.values[use.value], ProtocolValue)
                and self.ctx.values[use.value].protocol is ProtocolValueKind.EXCEPTION_PACKET)
            if len(packet_uses) != 1 or expected is None:
                self.gap('cancel_terminal_packet_unresolved', path, outcome=body)
                continue
            copied = self.ctx.bind(expected, OwnedUse(body.id, packet_uses[0].id), path=path)
            source = DriveResult(DriveOutcomeRef(drive.operation, body.id), 0)
            terminals = []
            for terminal in host_terminals(self.ctx, source):
                if not self.spend('cancel_host_terminals', path):
                    break
                if self.ctx.operations[terminal.operation].terminator.kind is TerminatorKind.RAISE:
                    terminals.append({'terminal': terminal, 'must_copy': host_output_copy(self.ctx, source, terminal)})
            routes.append({'source': source, 'body_packet': copied, 'host_terminals': tuple(terminals),
                'match': copied['match'] is True and bool(terminals) and all(item['must_copy'] is True for item in terminals)})
        return tuple(routes)

    def cancellation_bindings(self):
        from .protocol_connections import CancelDelivery, CancelHandling, TaskStatusRead
        deliveries = {_binding_key(row): row for row in self.ctx.graph.protocol_bindings if type(row) is CancelDelivery}
        known = {scope.id: scope for scope in self.ctx.scopes.values() if scope.profile is ProtocolProfile.TASK_CANCEL_EXTERNAL_V1}
        for number, row in enumerate(self.ctx.graph.protocol_bindings):
            if type(row) not in (CancelDelivery, CancelHandling, TaskStatusRead):
                continue
            path = f'cancel.bindings.{number}'
            if not self.spend('cancel_bindings', path):
                break
            try:
                identity = row.delivery.scope if type(row) is CancelHandling else row.scope
                scope = known.get(identity)
                if scope is None:
                    raise ValueError('cancel relation requires its exact TASK_CANCEL_EXTERNAL scope')
                if type(row) is CancelDelivery:
                    receiver, packet_role = self.delivery_receiver(row.consumer)
                    target = self.cancel_target(scope, row.expected_target, receiver, path) if receiver else None
                    source = self.port(row.packet_source)
                    if source is not None and source.gap is None and packet_role and any(
                            not isinstance(self.ctx.values[value], ProtocolValue)
                            or self.ctx.values[value].protocol is not ProtocolValueKind.EXCEPTION_PACKET for value in source.values):
                        raise ValueError('BodyDrive cancellation delivery requires its whole original exception packet')
                    packet = self.bind(row.packet_source, row.consumer, 'cancel_packet_source', path)
                    self.cancellation.append({'binding': row, 'scope': scope, 'receiver': receiver,
                                              'target': target, 'packet': packet,
                                              'terminal_routes': self.cancel_terminals(row, path)})
                elif type(row) is CancelHandling:
                    key = _binding_key(row.delivery)
                    delivery = deliveries.get(key)
                    if delivery is None:
                        self.issue('cancel_delivery_reference', path, 'full delivery natural key does not identify a declaration')
                        continue
                    packet = self.use(row.handler_packet)
                    if not isinstance(self.ctx.values[packet.value], ProtocolValue) or self.ctx.values[packet.value].protocol is not ProtocolValueKind.EXCEPTION_PACKET:
                        raise ValueError('handler requires its actual original packet Use')
                    expected = delivery.consumer
                    drive = self.ctx.drives.get(delivery.consumer.operation)
                    if drive is not None:
                        for binding in self.ctx.index.drive_input_bindings(drive.operation):
                            if type(binding.source) is not type(None) and getattr(binding.source, 'use', None) is not None and binding.source.use.id == delivery.consumer.use:
                                expected = self.ctx.values[binding.formal].origin
                                break
                    routed = self.bind(expected, row.handler_packet, 'cancel_handler_packet', path)
                    handler_region = self.ctx.region_of[row.handler_packet.operation]
                    domains = {body.context_location for body in self.ctx.graph.resumable_bodies if body.region == handler_region}
                    domains.update(item.location for item in self.ctx.graph.handled_context_domains if item.region == handler_region)
                    for site in row.context_sites:
                        location, access = self.site(site)
                        if domains and location not in domains:
                            raise ValueError('handler site is not its canonical handled-context domain')
                        if access is not None and (access.mode not in (AccessMode.WRITE, AccessMode.READ_WRITE) or access.after is None):
                            raise ValueError('handler context install must retain its real written after-state')
                    support = self.support(row.context_sites, self.ctx.operations[row.handler_packet.operation], path)
                    if not row.context_sites:
                        self.gap('cancel_handler_context_unresolved', path)
                    if type(row.continuation) is ControlEdgeReference:
                        operation = self.ctx.operations[row.continuation.operation]
                        if (operation.terminator is None or row.continuation.successor_index >= len(operation.terminator.successors)
                                or self.ctx.region_of[operation.id] != self.ctx.region_of[row.handler_packet.operation]):
                            raise ValueError('handler continuation is not its exact original CFG edge')
                    else:
                        self.gap('cancel_handler_continuation_unresolved', path)
                    self.cancellation.append({'binding': row, 'scope': scope, 'delivery': delivery,
                                              'packet': routed, 'context_support': support})
                else:
                    self.use(row.task, actual=True)
                    result = self.port(row.result, owner=row.task.operation, normal=True)
                    if result is not None and result.gap is None and (not result.values or any(
                            not isinstance(self.ctx.values[value], DataValue)
                            or self.ctx.values[value].data_type != 'builtins.bool' for value in result.values)):
                        raise ValueError('Task status must be its own original bool result')
                    task = self.cancel_task(scope)
                    if task is not None:
                        self.check(self.correspond(task, row.task, path), 'cancel_status_task', path)
                    for site in row.state_sites:
                        if site.operation != row.task.operation:
                            raise ValueError('status state site belongs to another operation')
                        _, access = self.site(site)
                        if access is not None and access.mode is not AccessMode.READ:
                            raise ValueError('ordinary Task status observation must read without writing')
                    if type(row.consumer) is StaticProtocolGap:
                        self.gap('cancel_status_consumer_unresolved', path)
                        consumer = None
                    else:
                        consumer = self.bind(row.result, row.consumer, 'cancel_status_result', path)
                    support = self.support(row.state_sites, self.ctx.operations[row.task.operation], path)
                    if not row.state_sites:
                        self.gap('cancel_status_state_unresolved', path)
                    self.cancellation.append({'binding': row, 'scope': scope, 'result': result, 'consumer': consumer,
                                              'state_support': support,
                                              'conditions': ('native Task status read semantics unproved',)})
            except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
                self.issue('cancel_binding_reference', path, str(exc))
        for scope in known.values():
            for clause, kind in ((ProtocolClause.CANCEL_DELIVERY, CancelDelivery),
                                 (ProtocolClause.CANCEL_HANDLER_OR_TERMINAL, CancelHandling),
                                 (ProtocolClause.TASK_STATUS_ROUTE, TaskStatusRead)):
                matches = tuple(row for row in self.ctx.graph.protocol_bindings if type(row) is kind
                    and (row.delivery.scope if kind is CancelHandling else row.scope) == scope.id)
                derived = tuple(item for item in self.cancellation if item['scope'].id == scope.id
                    and 'terminal_routes' in item and any(route['match'] for route in item['terminal_routes']))
                coverage = []
                if kind is CancelHandling:
                    for delivery in deliveries.values():
                        if delivery.scope != scope.id:
                            continue
                        handled = tuple(item for item in matches if _binding_key(item.delivery) == _binding_key(delivery))
                        terminals = tuple(item for item in derived if item['binding'] == delivery)
                        status = ('NOT_CHECKED' if self.ctx.budget.truncated else
                                  'DECLARED' if handled or terminals else 'MISSING')
                        coverage.append({'delivery': delivery, 'handling': handled, 'terminals': terminals, 'status': status})
                        if status == 'MISSING':
                            self.gap('cancel_handler_or_terminal_missing', scope.id, delivery=delivery)
                handler_complete = bool(coverage) and all(item['status'] == 'DECLARED' for item in coverage)
                present = handler_complete if kind is CancelHandling else bool(matches)
                self.obligations.append({'scope': scope.id, 'clause': clause, 'bindings': matches,
                    'derived_terminals': derived if kind is CancelHandling else (),
                    'delivery_coverage': tuple(coverage),
                    'status': 'NOT_CHECKED' if self.ctx.budget.truncated else 'DECLARED' if present else 'MISSING'})
                if not present:
                    self.gap('cancel_required_binding_missing', scope.id, clause=clause)

    def run(self):
        scopes = tuple(scope for scope in self.ctx.scopes.values() if scope.profile is ProtocolProfile.ASYNC_GENERATOR_BODY_V1)
        for scope in scopes:
            self.request_admission(scope)
            if not self.spend('scopes', str(scope.id)):
                for drive in self.ctx.drives_by_region.get(scope.subject.interface_region, ()):
                    self.obligations.append({'scope': scope.id, 'clause': ProtocolClause.ASYNC_REQUEST_ASSOCIATE,
                        'operation': drive.operation, 'candidates': (), 'status': 'NOT_CHECKED'})
                continue
            try:
                if type(scope.subject) is not DriverSubject:
                    raise ValueError('async protocol requires its exact driver subject')
                self.request_associations(scope)
            except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
                self.issue('async_scope_reference', scope.id, str(exc))
        self.session_outcomes(scopes)
        self.cancellation_bindings()
        return {'issues': tuple(self.issues), 'associations': tuple(self.associations), 'deliveries': tuple(self.deliveries),
                'request_admissions': tuple(self.admissions),
                'session_outcomes': tuple(self.sessions), 'cancellation': tuple(self.cancellation),
                'obligations': tuple(self.obligations), 'inventory': self.inventory,
                'gaps': tuple(self.gaps), 'cursor': self.cursor,
                'source_runtime_verified': False, 'runtime_identity_verified': False,
                'value_identity_verified': False, 'transformation_authorized': False}


def async_connections(ctx):
    """Analyze once per shared context; no provider execution or implicit IO."""
    from .protocol_connection_flow import ConnectionContext
    if type(ctx) is not ConnectionContext:
        raise TypeError('async connections require the exact shared ConnectionContext')
    cached = getattr(ctx, '_async_connections_report', None)
    if cached is None:
        cached = _Analysis(ctx).run()
        ctx._async_connections_report = cached
    return cached


def async_errors(ctx):
    return async_connections(ctx)['issues']


def request_state_errors(ctx, row):
    """Reuse the ordinary read/bool checks without treating R as body phase."""
    from dataclasses import replace
    from .admission import admission_errors
    from .protocols import BodyStateCondition, BodyStatePredicateRule
    from .protocol_connections import RequestStateCondition
    if type(row.contract.subject) is not RequestStateCondition:
        raise TypeError('request state checks require exact RequestStateCondition')
    subject = row.contract.subject
    proxy = replace(row, contract=replace(row.contract,
        subject=BodyStateCondition(subject.request_use, subject.state_sites, BodyStatePredicateRule.IS_CREATED)))
    # Only local shape/boolean provenance is reused. Body target compatibility
    # is deliberately not interpreted as request-step compatibility.
    issues = list(admission_errors(ctx, proxy))
    operation = ctx.operations[row.operation]
    expected = {subject.request_use, *(access.before for access in operation.accesses)}
    if {use.id for use in operation.uses} != expected:
        issues.append(('async_request_predicate_inputs', str(row.operation),
                       'request predicate has only its real request and READ inputs'))
    return tuple(issues)


def request_state_view(ctx, row):
    from .admission import admission_routes
    from .protocol_connections import RequestStateRule
    cache = getattr(ctx, '_async_request_state_views', None)
    if cache is None:
        cache = ctx._async_request_state_views = {}
    key = row.scope, row.clause, row.operation, row.slot
    if key in cache:
        return cache[key]
    analysis = _Analysis(ctx, prepare=False)
    contract, operation = row.contract, ctx.operations[row.operation]
    branch = ctx.operations[contract.branch]
    result = ctx.port(contract.result)
    condition = OwnedUse(branch.id, branch.terminator.condition)
    boolean = ctx.bind(contract.result, condition, path='async.request_state.bool')
    # BRANCH needs only its actual bool Use. Keep the original READ inputs
    # here; currentness at each final gate is checked by admission_routes.
    support = analysis.support(contract.subject.state_sites, operation, 'async.request_state.read')
    routes = admission_routes(ctx, row)
    interface = ctx.interfaces[ctx.region_of[operation.id]]
    expected = analysis.formal(interface.region, interface.receiver)
    actual = OwnedUse(operation.id, contract.subject.request_use)
    request = ctx.bind(expected, actual, path='async.request_state.receiver')
    gaps = [*analysis.gaps, *routes['gaps']]
    original_gap_count = len(analysis.gaps)
    if request['match'] is not True:
        gaps.append('async_request_predicate_receiver_unresolved')
    frontiers = []
    for frontier in routes['frontiers']:
        if frontier['kind'] != 'FINAL_GATE':
            frontiers.append(frontier)
            continue
        if not analysis.spend('request_admission_bindings', row.operation):
            gate_request = {'match': None, 'routes': (), 'gaps': ('protocol_budget_exhausted',), 'cursor': None}
            same = gate_request
        else:
            gate = frontier['gate']
            gate_operation = frontier['operation']
            gate_request = (ctx.bind(expected, OwnedUse(gate_operation.id,
                gate_operation.invoke_arguments[gate.session_argument]), path='async.request_state.gate_receiver')
                if gate.session_argument is not None else
                {'match': None, 'routes': (), 'gaps': ('async_gate_session_port_missing',), 'cursor': None})
            same = ctx.correlate(request, gate_request)
        truth = frontier['edge'].successor_index == 0
        complete_support = (bool(frontier['state_support']) and
            len(frontier['state_support']) == len(operation.accesses))
        currentness = (None if ctx.budget.truncated or not complete_support else
                       frontier['read_snapshot_current'])
        compatible = None
        if (contract.subject.rule is RequestStateRule.IS_COMPLETE and currentness is True
                and same['match'] is True and boolean['match'] is True):
            compatible = not truth
            if not compatible:
                gaps.append('async_request_complete_success_incompatible_at_snapshot')
        elif currentness is not True:
            gaps.append('async_request_admission_snapshot_unresolved')
        frontiers.append({**frontier, 'truth': truth, 'request_binding': request,
            'gate_request_binding': gate_request, 'same_request': same, 'currentness': currentness,
            'request_target_compatible_at_snapshot': compatible,
            'native_admission_verified': False,
            'conditions': ('compatibility concerns only this predicate, never complete admission',
                'initial-step selects L/S and does not establish body phase or occupancy')})
    routes = {**routes, 'frontiers': tuple(frontiers)}
    if boolean['match'] is not True:
        gaps.append('async_request_predicate_bool_unresolved')
    gaps.extend(analysis.gaps[original_gap_count:])
    view = {'predicate': row, 'operation': operation, 'subject': contract.subject,
            'input': ctx.owned_use(operation.id, contract.subject.request_use),
            'result': result, 'branch': branch, 'condition': ctx.owned_use(branch.id, condition.use),
            'bool_must_copy': boolean['match'], 'binding': boolean, 'state_support': support,
            'successors': tuple(enumerate(branch.terminator.successors)),
            'request_binding': request, 'control_routes': routes, 'gaps': tuple(gaps),
            'status': 'PARTIAL' if gaps else 'DECLARED',
            'conditions': ('request state implementation and source applicability unproved',),
            'native_phase_verified': False, 'source_runtime_verified': False,
            'transformation_authorized': False}
    cache[key] = view
    return view


__all__ = ['async_connections', 'async_errors', 'request_state_errors', 'request_state_view']
