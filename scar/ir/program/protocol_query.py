"""Bounded protocol obligations over a supplied model, not source recovery."""
from .driver_flow import body_drive_target, body_outcome_uses
from .ids import ProtocolScopeID
from .model import InvokeLiteralResult, OperationResult, ProtocolValue, TerminatorKind
from .protocol_flow import ProtocolFlow
from .protocol_rules import required_clauses
from .protocols import (AdmissionPredicate, DriverSubject, HostTerminal, NoEntryOutcome, OutcomeAdapter,
                        PacketConstruction, ProtocolCall, ProtocolClause,
                        RequestProcessing, ReferenceIsNoneCondition, OwnedUse, StaticProtocolGap)
from .protocol_validation import adapter_host_output, no_entry_route
from .resumption import SuspendTerminator


_GROUPS = tuple(f'F{i:02}' for i in range(1, 25)) + tuple(f'X{i:02}' for i in range(25, 29))


def _row_view(ctx, row, index=None):
    contract, gaps, ports = row.contract, [], []
    predicate = None
    if type(contract) is AdmissionPredicate:
        from .protocol_connections import RequestStateCondition
        if type(contract.subject) is RequestStateCondition:
            from .protocol_async import request_state_view
            predicate = request_state_view(ctx, row)
        else:
            from .admission import admission_view
            predicate = admission_view(ctx, row)
        if type(contract.subject) is ReferenceIsNoneCondition:
            from .control import ProtocolValueKind
            from .request_inputs import request_input_binding
            reports = []
            interface = ctx.interfaces.get(ctx.region_of[row.operation])
            if ctx.budget.truncated:
                predicate['gaps'] += ('protocol_budget_exhausted',)
            elif index is None:
                predicate['gaps'] += ('admission_prepared_input_index_unavailable',)
            elif interface is None:
                predicate['gaps'] += ('admission_raw_interface_unavailable',)
            else:
                scheduler = ctx.driver_roles(interface.region)[1]
                carriers = {}
                for use in predicate['branch'].uses:
                    if not ctx.spend('admission_raw_carriers'):
                        predicate['gaps'] += ('protocol_budget_exhausted',)
                        break
                    value = ctx.values[use.value]
                    if (isinstance(value, ProtocolValue)
                            and value.protocol is ProtocolValueKind.RAW_DRIVER_REQUEST
                            and value.id in scheduler):
                        carriers.setdefault(value.id, []).append(use)
                for uses in carriers.values():
                    if not ctx.spend('admission_joint_queries'):
                        predicate['gaps'] += ('protocol_budget_exhausted',)
                        break
                    report = request_input_binding(index,
                        OwnedUse(predicate['branch'].id, uses[0].id),
                        OwnedUse(row.operation, contract.subject.input_use), accounting=ctx.budget, _flow=ctx)
                    reports.append({'carrier_uses': tuple(uses), 'report': report})
                    if report['status'] in ('PARTIAL', 'TRUNCATED'):
                        predicate['gaps'] += ('admission_request_input_routes_unresolved',)
                    if not report['bindings']:
                        predicate['gaps'] += ('admission_request_input_unlinked',)
                if not carriers:
                    predicate['gaps'] += ('admission_raw_carrier_unavailable',)
            predicate['request_input_bindings'] = tuple(reports)
            if predicate['gaps']:
                predicate['status'] = 'PARTIAL'
        ports.append(predicate['result'])
        gaps.extend(predicate['gaps'])
    elif type(contract) in (RequestProcessing, ProtocolCall):
        ports.append(ctx.port(contract.result))
    elif type(contract) is OutcomeAdapter:
        ports.extend((ctx.port(contract.input, referring=row), ctx.port(contract.output)))
        if type(contract.output) is HostTerminal and adapter_host_output(ctx, row) is not True:
            gaps.append('protocol_adapter_output_unresolved')
    elif type(contract) is PacketConstruction:
        ports.extend((ctx.port(contract.exception_source, referring=row),
                      ctx.port(contract.traceback_source, referring=row)))
    elif type(contract) is NoEntryOutcome:
        route = no_entry_route(ctx, row)
        gaps.extend(route['gaps'])
        ports.extend((route.get('source'), route.get('terminal')))
    for port in ports:
        if port is None:
            gaps.append('protocol_budget_exhausted')
        elif port.gap is not None:
            gaps.append(port.gap)
    return {'record': row, 'operation': ctx.operations[row.operation],
            'ports': tuple(ports), 'state_sites': getattr(contract, 'state_sites', ()),
            'predicate': predicate,
            'status': 'PARTIAL' if gaps else 'DECLARED', 'gaps': tuple(gaps),
            'conditions': ('source/native applicability unproved',)}


def _derived(ctx, scope, clause):
    region = (scope.subject.interface_region if type(scope.subject) is DriverSubject
              else scope.subject.region)
    drives = ctx.drives_by_region.get(region, ())
    if clause is ProtocolClause.BODY_INGRESS:
        return tuple({'drive': drive, 'target': body_drive_target(ctx.graph, drive),
                      'state_inputs': drive.state_inputs, 'resume_inputs': drive.resume_inputs}
                     for drive in drives)
    if clause in (ProtocolClause.BODY_SUSPENSION, ProtocolClause.BODY_TERMINAL):
        result = []
        for drive in drives:
            operation = ctx.operations[drive.operation]
            for edge in operation.terminator.successors:
                body = ctx.operations[edge.source]
                if ((clause is ProtocolClause.BODY_SUSPENSION and type(body.terminator) is SuspendTerminator)
                        or (clause is ProtocolClause.BODY_TERMINAL and body.terminator.kind
                            in (TerminatorKind.RETURN, TerminatorKind.RAISE))):
                    result.append({'drive': drive, 'source': body, 'successor': edge,
                                   'original_uses': body_outcome_uses(body)})
        return tuple(result)
    if clause is ProtocolClause.CREATED_CLOSE_BRANCH:
        from .created_close import created_close_view
        return (created_close_view(ctx, scope),)
    if clause is ProtocolClause.ASYNC_REQUEST_ASSOCIATE:
        return tuple({'association': row, 'operation': ctx.operations[row.operation]}
                     for row in ctx.graph.request_association_reads if ctx.region_of[row.operation] == region)
    return ()


def protocol_obligations(graph, scope=None, *, budget=4096, _index=None):
    # Reuse the finite budget mechanism, not execution facts or its validator.
    from scar.ir.execution.validity_budget import ValidityBudget
    shared = ValidityBudget(budget)
    if scope is not None and type(scope) is not ProtocolScopeID:
        raise TypeError('protocol scope query requires exact ProtocolScopeID or None')
    from .queries import ProgramIndex
    from .protocol_connection_flow import ConnectionContext
    from .protocol_connection_validation import connection_reports
    index = ProgramIndex(graph) if _index is None else _index
    ctx = ConnectionContext(graph, index=index, budget=shared)
    if scope is not None and scope not in ctx.scopes:
        raise KeyError(scope)
    selected = tuple(row for row in graph.protocol_scopes if scope is None or row.id == scope)
    global_gaps = [{'code': 'SOURCE_SCOPE_INVENTORY_UNRESOLVED',
                    'message': 'supplied records do not prove an exhaustive source/site inventory'}]
    views, cursor = [], None
    for declaration in selected:
        obligations = []
        for clause in required_clauses(declaration.profile):
            # Keep the fixed denominator even after budget exhaustion.
            rows = ctx.rows_by_clause.get((declaration.id, clause), ())
            details, gaps, bindings, status = [], [], [], 'NOT_CHECKED'
            if shared.spend('protocol_clauses', path='protocol.inventory'):
                for row in rows:
                    if not shared.spend('protocol_rows', path='protocol.rows'):
                        break
                    details.append(_row_view(ctx, row, index))
                original = _derived(ctx, declaration, clause) if not shared.truncated else ()
                for item in original:
                    gaps.extend(item.get('gaps', ()))
                expected, known = set(), {}
                for row in rows:
                    if not shared.spend('protocol_binding_rows', path='protocol.binding_inventory'):
                        break
                    expected.add((row.operation, row.slot))
                    known[row.operation, row.slot] = row
                    if type(row.contract) in (RequestProcessing, ProtocolCall, OutcomeAdapter):
                        operation = ctx.operations[row.operation]
                        if operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE:
                            for number in range(len(operation.terminator.successors)):
                                if not shared.spend('protocol_binding_edges', path='protocol.binding_inventory'):
                                    break
                                expected.add((operation.id, number))
                # Presence is an original indexed lookup, not an analysis guess.
                known.update(((operation, slot), ctx.rows.get((declaration.id, clause, operation, slot)))
                             for operation, slot in expected)
                for operation, slot in sorted(expected, key=lambda item: (item[0].wire, item[1])):
                    present = known.get((operation, slot))
                    bindings.append({'operation': operation, 'slot': slot,
                                     'row': present, 'status': 'DECLARED' if present else 'MISSING'})
                if any(item['row'] is None for item in bindings):
                    gaps.append('protocol_required_edge_unbound')
                if details or original:
                    status = 'PARTIAL' if gaps or shared.truncated or any(item['gaps'] for item in details) else 'DECLARED'
                else:
                    status = 'MISSING'
                    gaps.append('required_protocol_clause_unbound')
                if shared.truncated:
                    status = 'PARTIAL' if details else 'NOT_CHECKED'
            else:
                original = ()
            if shared.truncated and cursor is None:
                cursor = {'scope': declaration.id, 'clause': clause,
                          'remaining_rows': max(0, len(rows) - len(details))}
            obligations.append({'clause': clause, 'status': status, 'rows': tuple(details),
                                'original': original, 'bindings': tuple(bindings), 'gaps': tuple(gaps),
                                'required_row_count_unproved': True})
        views.append({'scope': declaration, 'profile': declaration.profile,
                      'obligations': tuple(obligations),
                      'conditions': ('source/native applicability unproved',
                                     'source site inventory unproved'),
                      'source_inventory_complete': False})
    connections = connection_reports(ctx)
    global_gaps.extend(shared.gaps)
    return {'scopes': tuple(views), 'gaps': tuple(global_gaps),
            'obligation_groups': _GROUPS, 'cursor': cursor,
            'budget': {'limit': shared.limit, 'used': shared.used,
                       'costs': dict(shared.costs), 'truncated': shared.truncated},
            'preparation_work': dict(ctx.preparation),
            'connections': connections,
            'source_inventory_complete': False,
            'protocol_implementation_complete': False,
            'source_runtime_verified': False, 'transformation_authorized': False}


__all__ = ['protocol_obligations']
