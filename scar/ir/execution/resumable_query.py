"""Detached, bounded projections with original port denominators and gaps."""
from copy import deepcopy

from .coordinates import _identifier
from .ids import OperationOccurrenceID, RegionActivationID


def _flags():
    return {'source_runtime_verified': False, 'runtime_identity_verified': False,
            'value_identity_verified': False, 'transformation_authorized': False}


def _budget(shared):
    return {'limit': shared.limit, 'used': shared.used, 'truncated': shared.truncated,
            'costs': dict(shared.costs), 'gaps': tuple(shared.gaps)}


def _preparation(ctx):
    return {'canonical': ctx.body_preparation, 'external': ctx.external_preparation,
            'compatibility': ctx.body_identity_preparation,
            'cost_scope': 'preparation/validation and detached copying are outside the derived traversal limit'}


def _host_cycle_view(ctx, shared):
    prepared = ctx.host_cycle_preparation
    cost = prepared['endpoints'] + prepared['local_edges'] + prepared['bridge_edges'] + 1
    checked = shared.spend('body_query_host_cycle_summary', cost, 'body.host_order')
    return {'status': prepared['status'] if checked else 'NOT_CHECKED',
            'scope': 'captured local chains and admitted conditional CALL/body bridges',
            'capture_complete': False, 'preparation': prepared}


def drive_execution(ctx, identity, *, shared):
    _identifier(identity, OperationOccurrenceID, 'body drive query occurrence')
    if identity not in ctx.body_drive_occurrences:
        raise ValueError('body drive query requires a captured canonical BodyDrive occurrence')
    view = ctx.resolved_body_drives[identity]
    result = {**view, **_flags()}
    result['validation_gaps'] = tuple(ctx.gaps)
    cursor = None
    checked = 0
    pending = []
    for field in ('inputs', 'outputs', 'forwards'):
        bindings = []
        for ordinal, item in enumerate(view[field]):
            row = dict(item)
            for endpoint in (item['source_value'], item['formal']):
                if endpoint is not None and hasattr(endpoint, 'id'):
                    pending.append(endpoint.id)
            if shared.spend('body_query_bindings', path=f'body.{field}[{ordinal}]'):
                row['check_status'] = 'DECLARED'
                checked += 1
            else:
                if cursor is None:
                    cursor = {'field': field, 'ordinal': ordinal, 'drive': identity}
                row['compatibility'] = None
                row['check_status'] = 'NOT_CHECKED'
            bindings.append(row)
        result[field] = tuple(bindings)
    for endpoint in (view['instance']['value'], view['instance']['creation_handle']):
        if endpoint is not None and hasattr(endpoint, 'id'):
            pending.append(endpoint.id)
    copies, seen = [], set()
    while pending:
        target = pending.pop()
        if target in seen or target not in ctx.body_copy_compatibility:
            continue
        seen.add(target)
        if not shared.spend('body_query_copy_edges', path='body.copy_support'):
            if cursor is None:
                cursor = {'field': 'copy_support', 'target': target, 'drive': identity}
            break
        row = ctx.body_copy_compatibility[target]
        copies.append(row)
        pending.append(row['source'])
    result['copy_support'] = tuple(copies)
    if shared.spend('body_query_instance', path='body.instance'):
        result['instance'] = dict(view['instance'], check_status='DECLARED')
    else:
        if cursor is None:
            cursor = {'field': 'instance', 'ordinal': 0, 'drive': identity}
        result['instance'] = dict(view['instance'], compatibility=None,
                                  persistent_compatibility=None, check_status='NOT_CHECKED')
    result['host_order'] = _host_cycle_view(ctx, shared)
    if shared.truncated and cursor is None:
        cursor = {'field': 'host_order', 'ordinal': 0, 'drive': identity}
    result.update(input_count=len(view['inputs']), output_count=len(view['outputs']),
                  forward_count=len(view['forwards']), checked_binding_count=checked,
                  budget=_budget(shared), cursor=cursor, preparation_work=_preparation(ctx))
    copy_gaps = tuple(gap for row in copies for gap in row['gaps'])
    result['gaps'] = tuple(dict.fromkeys((*view['gaps'], *copy_gaps)))
    result['status'] = ('MISSING' if view['association'] is None else
                        'PARTIAL' if result['gaps'] or shared.truncated else 'DECLARED')
    return deepcopy(result)


def body_activation_origin(ctx, identity, *, shared):
    _identifier(identity, RegionActivationID, 'body activation origin query')
    activation = ctx.activations.get(identity)
    if activation is None or activation.region not in ctx.resumable_bodies:
        raise ValueError('body origin query requires a resumable body activation')
    from .resumable_flow import creation_view
    view = ctx.resolved_body_origins.get(identity)
    if view is None:
        view = creation_view(ctx, identity)
    captures, cursor = {}, None
    for ordinal, (formal, capture) in enumerate(view['captures'].items()):
        checked = shared.spend('body_origin_captures', path=f'body.origin.captures[{ordinal}]')
        captures[formal] = {**capture, 'check_status': 'DECLARED' if checked else 'NOT_CHECKED'}
        if not checked and cursor is None:
            cursor = {'field': 'captures', 'ordinal': ordinal, 'activation': identity}
    drives = tuple(ctx.body_drives_by_activation.get(identity, ()))
    if not shared.spend('body_origin_drives', len(drives) + 1, 'body.origin.drives') and cursor is None:
        cursor = {'field': 'drives', 'ordinal': 0, 'activation': identity}
    host_order = _host_cycle_view(ctx, shared)
    if shared.truncated and cursor is None:
        cursor = {'field': 'host_order', 'ordinal': 0, 'activation': identity}
    return deepcopy({**view, **_flags(), 'captures': captures, 'drives': drives, 'host_order': host_order,
        'validation_gaps': tuple(ctx.gaps),
        'status': 'MISSING' if view['association'] is None else 'PARTIAL' if view['gaps'] or shared.truncated else 'DECLARED',
        'budget': _budget(shared), 'cursor': cursor, 'preparation_work': _preparation(ctx)})


__all__ = ['drive_execution', 'body_activation_origin']
