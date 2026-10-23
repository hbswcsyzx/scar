"""Compose original program/execution associations without transformation proof.

The full supplied graphs are retained as the denominator. Derived views share
one budget and one prepared external snapshot; only the public result detaches.
"""
from copy import deepcopy
from dataclasses import fields

from .coordinates import OccurrencePoint, OccurrencePhase
from .validation import ExecutionIssue
from .work import WithinOperation


def _inventory(ctx):
    counts = {field.name: len(getattr(ctx.model, field.name))
              for field in fields(ctx.model) if field.name != 'snapshot'}
    return {'program': ctx.program, 'execution': ctx.model, 'execution_counts': counts,
            'canonical_counts': {'regions': len(ctx.program.regions),
                'operations': len(ctx.program.operations), 'values': len(ctx.program.values),
                'locations': len(ctx.program.locations)},
            'scope': 'all supplied canonical definitions and execution records; not complete source/runtime capture'}


def _reads(ctx, budget):
    from .validity_query import validity_shared
    result = []
    for ordinal, read in enumerate(ctx.model.content_reads):
        if not budget.spend('composition_read', path=f'composition.reads[{ordinal}]'):
            break
        if not budget.remaining:
            budget.mark_truncated(f'composition.reads[{ordinal}]',
                                  'read identity inspected but no budget remains for content reconciliation')
            result.append({'read': read, 'validity': None, 'status': 'TRUNCATED',
                           'query_budget_used': 0})
            break
        start = budget.used
        view = validity_shared(ctx, read.id, budget=budget, include_context_gaps=False)
        result.append({'read': read, 'validity': view,
                       'status': 'TRUNCATED' if view['truncated'] else 'INSPECTED',
                       'query_budget_used': budget.used - start})
        if budget.truncated:
            break
    completed = sum(item['status'] == 'INSPECTED' for item in result)
    cursor = next(({'table': 'content_reads', 'ordinal': ordinal, 'phase': 'validity'}
                   for ordinal, item in enumerate(result) if item['status'] == 'TRUNCATED'), None)
    if cursor is None and len(result) < len(ctx.model.content_reads):
        cursor = {'table': 'content_reads', 'ordinal': len(result), 'phase': 'identity'}
    return {'items': tuple(result), 'visited': len(result), 'completed': completed,
            'total': len(ctx.model.content_reads), 'pending': len(ctx.model.content_reads) - completed,
            'status': 'TRUNCATED' if budget.truncated else 'DERIVED',
            'cursor': cursor}


def _production(ctx, budget):
    registries = (('writes', ctx.resolved_writes), ('outcome_productions', ctx.resolved_produced),
                  ('established_productions', ctx.resolved_establishments))
    result, pending, cursor = {}, {}, None
    for name, registry in registries:
        items = []
        for ordinal, resolved in enumerate(registry.values()):
            if not budget.spend('composition_production', path=f'composition.{name}[{ordinal}]'):
                if cursor is None:
                    cursor = {'table': name, 'ordinal': ordinal}
                break
            items.append(resolved)
        result[name] = tuple(items)
        pending[name] = len(registry) - len(items)
    return {**result, 'pending': pending, 'cursor': cursor,
            'status': 'TRUNCATED' if any(pending.values()) else 'DERIVED',
            'meaning': 'original write/result/actual associations, not a caller-selected complete writer set'}


def _sources(ctx, budget):
    result, cursor = [], None
    for ordinal, binding in enumerate(ctx.model.source_inventories):
        if not budget.spend('composition_inventory', path=f'composition.sources[{ordinal}]'):
            cursor = {'table': 'source_inventories', 'ordinal': ordinal}
            break
        resolution = ctx.source_resolutions.get(binding.id)
        sources = []
        for source_number, source in enumerate(() if resolution is None else resolution.sources):
            if not budget.spend('composition_inventory_source',
                                path=f'composition.sources[{ordinal}].sources[{source_number}]'):
                cursor = {'table': 'source_inventories', 'ordinal': ordinal,
                          'source_ordinal': source_number}
                break
            evidence = None if source.bundle is None else source.bundle.evidence
            edges = []
            for edge_ordinal, edge in enumerate(() if evidence is None else evidence.edges.values()):
                if not budget.spend('composition_source_edge',
                                    path=f'composition.sources[{ordinal}].sources[{source_number}].edges[{edge_ordinal}]'):
                    cursor = {'table': 'source_inventories', 'ordinal': ordinal,
                              'source_ordinal': source_number, 'edge_ordinal': edge_ordinal}
                    break
                edges.append(edge)
            sources.append({'key': source.key, 'raw_artifact': source.raw_artifact,
                'raw_record_count': len(source.raw_records),
                'evidence_artifact': source.evidence_artifact, 'values_artifact': source.values_artifact,
                'semantic_artifact': source.semantic_artifact,
                'projection_replayed': source.projection_replayed,
                'evidence': {'instance_count': None if evidence is None else len(evidence.instances),
                    'edge_count': None if evidence is None else len(evidence.edges),
                    'edges': tuple(edges),
                    'pending_edges': None if evidence is None else len(evidence.edges) - len(edges),
                    'status': 'UNRESOLVED' if evidence is None else 'TRUNCATED' if cursor is not None else 'DERIVED',
                    'meaning': 'original supplied evidence edges, including effects independent of ContentReads; not native complete capture'}})
            if cursor is not None:
                break
        result.append({'binding': binding, 'sources': tuple(sources),
            'total_sources': None if resolution is None else len(resolution.sources),
            'pending_sources': None if resolution is None else len(resolution.sources) - len(sources),
            'format_replayed': None if resolution is None else resolution.format_replayed,
            'gaps': () if resolution is None else resolution.gaps})
        if cursor is not None:
            break
    return {'items': tuple(result), 'total': len(ctx.model.source_inventories),
            'pending': len(ctx.model.source_inventories) - len(result), 'cursor': cursor,
            'status': 'TRUNCATED' if cursor is not None else 'DERIVED',
            'capture_complete': False,
            'meaning': 'supplied manifest/projection counts; not all native writers, aliases or external effects'}


def _lifecycle(ctx, budget):
    work_views, cursor = [], None
    for ordinal, work in enumerate(ctx.model.submissions):
        if not budget.spend('composition_work', path=f'composition.work[{ordinal}]'):
            cursor = {'table': 'submissions', 'ordinal': ordinal}
            break
        operation = (ctx.occurrences[work.origin.operation]
                     if type(work.origin) is WithinOperation else None)
        core = None if operation is None else ctx.core_operations[operation.operation]
        transfer = None if operation is None else ctx.outgoing.get(operation.id)
        successor = (None if transfer is None else core.terminator.successors[transfer.successor_index])
        groups = (('outcomes', ctx.work_outcomes.get(work.id, ())),
                  ('quiescences', ctx.work_quiescences.get(work.id, ())),
                  ('retentions', ctx.work_retentions.get(work.id, ())))
        view = {'submission': work, 'host_occurrence': operation,
                'host_operation': core, 'actual_host_transfer': transfer,
                'actual_host_successor': successor,
                'host_before': None if operation is None else ctx.current(
                    OccurrencePoint(operation.id, OccurrencePhase.BEFORE)), 'counts': {}, 'pending': {}}
        for name, rows in groups:
            selected = []
            for position, row in enumerate(rows):
                if not budget.spend('composition_work_relation',
                                    path=f'composition.work[{ordinal}].{name}[{position}]'):
                    if cursor is None:
                        cursor = {'table': 'submissions', 'ordinal': ordinal,
                                  'relation': name, 'relation_ordinal': position}
                    break
                selected.append(row)
            view[name] = tuple(selected)
            view['counts'][name] = len(rows)
            view['pending'][name] = len(rows) - len(selected)
        work_views.append(view)
        if cursor is not None:
            break
    return {'work': tuple(work_views), 'total_work': len(ctx.model.submissions),
            'pending_work': len(ctx.model.submissions) - len(work_views), 'cursor': cursor,
            'handles': ctx.model.handles, 'target_lifetime_events': ctx.model.target_lifetime_events,
            'status': 'TRUNCATED' if cursor is not None else 'DERIVED',
            'meaning': 'host completion, work terminal, quiescence, borrow release, handle end and retirement remain distinct; no free or persistence proof'}


def resource_composition(ctx, scopes, *, budget):
    """Return one detached projection; the caller already prepared this context."""
    from .composition_requirements import requirements
    from .composition_routes import routes

    observations = requirements(ctx, scopes, budget=budget)
    # Publish the Q-phase receipt, not the mutable traversal controller. Later
    # phases continue charging the same controller without changing this view.
    observations['budget'] = {'limit': budget.limit, 'used': budget.used,
        'remaining': budget.remaining, 'costs': dict(budget.costs),
        'truncated': budget.truncated, 'scope': 'Q scans and joins at the end of the Q phase'}
    reads = _reads(ctx, budget)
    productions = _production(ctx, budget)
    sources = _sources(ctx, budget)
    dependencies = routes(ctx, budget=budget)
    lifecycle = _lifecycle(ctx, budget)
    gaps = list(ctx.gaps)
    for row in (*observations['gaps'], *dependencies['gaps'], *budget.gaps):
        issue = row if type(row) is ExecutionIssue else ExecutionIssue(
            row['code'], str(row['path']), row['message'])
        gaps.append(issue)
    return deepcopy({'requested_scopes': scopes, 'inventory': _inventory(ctx),
        'observations': observations, 'reads': reads, 'production': productions,
        'sources': sources, 'routes': dependencies, 'lifecycle': lifecycle,
        'external_preparation': ctx.external_preparation,
        'gaps': tuple(dict.fromkeys(gaps)),
        'status': 'TRUNCATED' if budget.truncated else 'DERIVED',
        'budget': {'limit': budget.limit, 'used': budget.used, 'remaining': budget.remaining,
                   'costs': dict(budget.costs), 'truncated': budget.truncated,
                   'scope': 'shared derived Q joins, content queries, routes and work/source views; preparation/FK/replay and detached copying separate'},
        'scope_inventory_complete': False, 'source_runtime_verified': False,
        'runtime_visibility_verified': False, 'transformation_authorized': False})


__all__ = ['resource_composition']
