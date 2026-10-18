"""Source-rooted production inspection, without a closed writer set or ready proof.

The traversal budget counts lineage nodes, source edges/raw rows, inspected
association joins, and selector ranks.  Snapshot validation and inventory replay
have their own byte/line budgets and happen before this query; they are not
represented as cheap traversal operations.  No URI or provider is executed here.
"""
from __future__ import annotations

from copy import deepcopy

from scar.ir.provenance import _byte_bounds, _width
from scar.ir.v2.evidence import EvidenceNodeKind, EvidenceRelation
from scar.ir.v2.values import ValueGraph
from .common import Unresolved
from .content import ObservationConsumer, VersionRef
from .content_validation import artifact_key, point_scope
from .coordinates import OccurrencePhase, OccurrencePoint
from .coverage import RegionRef
from .ids import ContentReadID
from .production import InventorySourceRef, RawRecordRef, SourceEdgeRef, SourceEndpointRef
from .source_validation import resolve_endpoint
from .work import MaterializationRef


_RELATIONS = frozenset((EvidenceRelation.PRODUCES, EvidenceRelation.MATERIALIZES,
    EvidenceRelation.OBSERVED_WRITE, EvidenceRelation.OVERWRITES,
    EvidenceRelation.ALIASES, EvidenceRelation.USES_STORAGE, EvidenceRelation.ESCAPES))


class _Budget:
    def __init__(self, limit, gaps):
        if type(limit) is not int:
            raise TypeError('production budget must be an exact integer')
        if limit <= 0:
            raise ValueError('production budget must be positive')
        self.limit, self.used, self.truncated = limit, 0, False
        self.costs = {key: 0 for key in ('lineage_nodes', 'source_edges', 'raw_rows',
                                        'association_joins', 'selector_rank')}
        self.gaps = gaps

    def take(self, kind, path, count=1):
        if count > self.limit - self.used:
            if not self.truncated:
                self.gaps.append({'code': 'production_budget', 'path': path,
                    'message': 'traversal truncated; unvisited sources/joins are not independent or absent'})
            self.truncated = True
            return False
        self.used += count
        self.costs[kind] += count
        return True


def _gap(gaps, code, path, message):
    gaps.append({'code': code, 'path': path, 'message': message})


def _version_key(reference):
    return artifact_key(reference.artifact), reference.version


def _lineage(ctx, demand, budget, gaps):
    if demand is None:
        _gap(gaps, 'production_lineage_unresolved', 'demand', 'no resolved scoped demand version')
        return (), set()
    pending, seen, result = [demand], set(), []
    while pending:
        ref = pending.pop()
        key = _version_key(ref)
        if key in seen:
            continue
        if not budget.take('lineage_nodes', 'lineage'):
            break
        seen.add(key)
        graph = ctx.snapshots.graph(ref.artifact, ValueGraph)
        row = None if graph is None else graph.versions.get(ref.version)
        if row is None:
            _gap(gaps, 'production_lineage_pending', 'lineage', 'original version graph/row is unavailable')
            continue
        provenance = None if row.provenance_id is None else graph.provenance.get(row.provenance_id)
        parents, seen_parents = [], set()
        dependencies_complete = True
        for references in (row.parent_versions, () if provenance is None else provenance.inputs):
            for parent in references:
                if not budget.take('association_joins', 'lineage.dependencies'):
                    dependencies_complete = False
                    break
                if parent not in seen_parents:
                    parents.append(parent)
                    seen_parents.add(parent)
            if not dependencies_complete:
                break
        dependencies = tuple(VersionRef(ref.artifact, item) for item in parents)
        result.append({'version': ref, 'original': row, 'provenance': provenance,
                       'dependencies': dependencies, 'dependencies_complete': dependencies_complete,
                       'is_demand': key == _version_key(demand)})
        pending.extend(reversed(dependencies))
    _gap(gaps, 'production_lineage_unverified', 'lineage',
         'declared parent/provenance dependencies are not native production, purity, or current writers')
    return tuple(result), seen


def _run(ctx, resolved):
    read = resolved['read']
    if type(read.consumer) is not ObservationConsumer:
        return point_scope(ctx, OccurrencePoint(read.consumer.subject.operation, OccurrencePhase.BEFORE))[0]
    root = resolved['observation_root']
    if root is not None:
        for point in (root.interval.start, root.interval.end, root.anchor):
            run = point_scope(ctx, point)[0]
            if run is not None:
                return run
    return None


def _universe(ctx, run, budget, gaps):
    """Enumerate first: association deletion cannot buy a smaller source universe."""
    candidates, pending = [], []
    inventories = tuple(row for row in ctx.source_inventories.values() if run is None or row.run == run)
    if not inventories:
        _gap(gaps, 'production_inventory_missing', 'inventory',
             'no independent source inventory for the original consumer run; an empty AND is not satisfied')
    if run is None:
        _gap(gaps, 'production_run_unresolved', 'demand',
             'consumer run is unresolved; all inventories remain candidates, without a scope match proof')
    for inventory in inventories:
        resolution = ctx.source_resolutions.get(inventory.id)
        if resolution is None or not resolution.sources:
            pending.append({'inventory': inventory, 'source': None, 'reason': 'source inventory/index pending'})
            continue
        for declared in resolution.sources:
            source = ctx.inventory_sources.get((inventory.id, declared.key), declared)
            reference = InventorySourceRef(inventory.id, source.key)
            if source.bundle is None or not source.projection_replayed:
                pending.append({'inventory': inventory, 'source': reference,
                                'reason': 'source projection is pending; raw candidates do not close its scope'})
            if source.bundle is not None:
                for edge in source.bundle.evidence.edges.values():
                    if not budget.take('source_edges', f'source[{reference}].edges'):
                        pending.append({'inventory': inventory, 'source': reference,
                                        'reason': 'unvisited source edges after traversal budget'})
                        break
                    if edge.relation in _RELATIONS:
                        candidates.append({'id': ('edge', inventory.id, source.key, edge.edge_id),
                            'source': SourceEdgeRef(reference, edge.edge_id), 'original': edge,
                            'relation': edge.relation.value, 'endpoints': (),
                            'write_associations': (), 'outcome_productions': (),
                            'relevance': (), 'conditions': []})
            for raw in source.raw_records:
                if not budget.take('raw_rows', f'source[{reference}].raw'):
                    pending.append({'inventory': inventory, 'source': reference,
                                    'reason': 'unvisited raw rows after traversal budget'})
                    break
                metadata = raw.payload.get('metadata') if type(raw.payload) is dict else None
                native = type(metadata) is dict and 'scar_native_result' in metadata
                # Even a non-native row can contain an unprojected effect. Keep
                # it as raw evidence; do not invent an ALIASES/OVERWRITES edge.
                candidates.append({'id': ('raw', inventory.id, source.key, raw.line, raw.sha256),
                    'source': RawRecordRef(reference, raw.line, raw.sha256), 'original': raw,
                    'relation': 'raw_native_result' if native else 'raw_record', 'endpoints': (),
                    'write_associations': (), 'outcome_productions': (),
                    'relevance': (), 'conditions': []})
    if pending:
        _gap(gaps, 'production_inventory_pending', 'inventory',
             'unresolved or unvisited source scope remains; enumerated candidates are not a closed writer inventory')
    return candidates, tuple(pending)


def _facets(ctx, resolved):
    """Derive original facets; bare identifiers never cross artifact scopes."""
    artifact = resolved.get('values_artifact')
    if artifact is None:
        return None
    return {'artifact': artifact,
        **{key: resolved.get(key) for key in ('value_version', 'materialization', 'region', 'allocation')}}


def _target_facets(resolved):
    graph, artifact = resolved['graph'], resolved['artifact']
    result = {'artifact': artifact, 'value_version': None, 'materialization': None,
              'region': None, 'allocation': None}
    result[resolved['facet']] = resolved['identity']
    if result['materialization'] is not None:
        mat = graph.materializations[result['materialization']]
        result.update(value_version=mat.value_version, region=mat.region)
    if result['region'] is not None:
        result['allocation'] = graph.regions[result['region']].allocation
    return result


def _endpoints(ctx, candidate, budget, gaps):
    ref, original = candidate['source'], candidate['original']
    if type(ref) is not SourceEdgeRef:
        return ()
    result = []
    for endpoint in (original.source, original.target):
        if endpoint.kind is EvidenceNodeKind.OPERATION_INSTANCE:
            continue
        if not budget.take('association_joins', f'{candidate["id"]}.endpoint'):
            break
        reference = SourceEndpointRef(ref.source, endpoint)
        resolved = resolve_endpoint(ctx, reference, f'production[{candidate["id"]}].endpoint')
        mappings = []
        for bridge in ctx.resolved_source_bridges.values():
            if not budget.take('association_joins', f'{candidate["id"]}.bridge'):
                break
            if bridge['row'].endpoint == reference:
                mappings.append(bridge)
        if len(mappings) > 1:
            candidate['conditions'].append('multiple_endpoint_bridges')
            _gap(gaps, 'production_bridge_ambiguous', str(candidate['id']),
                 'multiple declared bridge targets are retained; no first target is chosen')
        result.append({'reference': reference, 'resolved': resolved, 'bridges': tuple(mappings)})
    return tuple(result)


def _spatial(ctx, facets, demand, budget, path):
    region = demand.get('selector')
    if type(region) is not RegionRef:
        return 'unresolved'
    if artifact_key(facets['artifact']) != artifact_key(region.artifact):
        return 'different_scope'
    graph = ctx.snapshots.graph(region.artifact, ValueGraph)
    if graph is None:
        return 'unresolved'
    required = graph.regions[region.region]
    allocation = facets.get('allocation')
    if allocation is None:
        return 'unresolved'
    if allocation != required.allocation:
        return 'different_allocation'
    offered = None if facets.get('region') is None else graph.regions[facets['region']]
    if offered is None:
        return 'possible_overlap'
    if not budget.take('selector_rank', path, len(required.shape) + len(offered.shape)):
        return 'unresolved'
    if 0 in required.shape or 0 in offered.shape:
        return 'disjoint'
    if (_width(required) is None or _width(offered) is None
            or required.layout != 'strided' or offered.layout != 'strided'):
        return 'possible_overlap'
    if offered.id == required.id:
        return 'overlap'
    left, right = _byte_bounds(required), _byte_bounds(offered)
    if left[0] >= right[1] or right[0] >= left[1]:
        return 'disjoint'
    # Bounding boxes cannot fill holes. This is a possible conflict only.
    return 'possible_overlap'


def _relevance(ctx, candidate, demand, lineage, budget):
    labels, spatial = set(), []
    for endpoint in candidate['endpoints']:
        base = _facets(ctx, endpoint['resolved']) if endpoint['resolved'] is not None else None
        variants = ([] if base is None else [(base, False)])
        for bridge in endpoint['bridges']:
            if not budget.take('association_joins', f'{candidate["id"]}.bridge_facets'):
                break
            if bridge['target'] is not None:
                variants.append((_target_facets(bridge['target']), True))
        for facets, conditional in variants:
            if not budget.take('association_joins', f'{candidate["id"]}.facet_relevance'):
                break
            version = facets.get('value_version')
            key = (artifact_key(facets['artifact']), version)
            if version is not None and key in lineage:
                labels.add('lineage_prerequisite')
                if demand['version'] is not None and key == _version_key(demand['version']):
                    labels.add('target_version_observation')
            overlap = _spatial(ctx, facets, demand, budget, str(candidate['id']))
            spatial.append(overlap)
            if overlap in ('overlap', 'possible_overlap'):
                labels.add('possible_invalidator')
            if conditional:
                candidate['conditions'].append('endpoint_bridge_runtime_unverified')
    current = []
    for write in candidate['write_associations']:
        if not budget.take('association_joins', f'{candidate["id"]}.placement'):
            break
        placement, original = write['placement'], write['row'].placement
        if placement is None or type(original) is Unresolved or placement[0] is None:
            candidate['conditions'].append('write_placement_unresolved')
            continue
        mat, selector = placement
        facets = {'artifact': original.materialization.artifact,
            'value_version': mat.value_version, 'materialization': original.materialization.materialization,
            'region': selector.region if type(selector) is RegionRef else mat.region, 'allocation': None}
        graph = ctx.snapshots.graph(facets['artifact'], ValueGraph)
        if graph is not None and facets['region'] is not None:
            facets['allocation'] = graph.regions[facets['region']].allocation
        overlap = _spatial(ctx, facets, demand, budget, str(candidate['id']))
        if overlap in ('overlap', 'possible_overlap'):
            labels.add('possible_invalidator')
        same_version = (demand['version'] is not None
            and (artifact_key(facets['artifact']), mat.value_version) == _version_key(demand['version']))
        same_mat = (demand['materialization'] is not None
            and artifact_key(facets['artifact']) == artifact_key(demand['materialization'].artifact)
            and facets['materialization'] == demand['materialization'].materialization)
        demand_selector = demand['selector']
        same_selector = (type(selector) is RegionRef and type(demand_selector) is RegionRef
            and artifact_key(selector.artifact) == artifact_key(demand_selector.artifact)
            and selector.region == demand_selector.region)
        if type(selector) is not RegionRef and type(demand_selector) is not RegionRef:
            same_selector = original == demand['placement']
        if same_version and same_mat and same_selector:
            current.append(write)
        elif overlap not in ('disjoint', 'different_allocation'):
            candidate['conditions'].append('write_demand_relevance_unresolved')
    candidate['current_write_associations'] = tuple(current)
    if current:
        labels.add('current_production_association')
        candidate['conditions'].append('association_does_not_establish_demand_coverage_or_content')
    if not labels or any(item in ('unresolved', 'different_scope') for item in spatial):
        labels.add('unresolved_relevance')
    # An observed result could be a view/copy/no-op; it is never a native write
    # merely because the source relation is PRODUCES.
    if candidate['relation'] == EvidenceRelation.PRODUCES.value:
        candidate['conditions'].append('observed_result_is_not_native_write')
    if candidate['relation'] == EvidenceRelation.ESCAPES.value:
        labels.add('unresolved_relevance')
        candidate['conditions'].append('escape_effect_mapping_unresolved')
    if type(candidate['source']) is RawRecordRef:
        labels.add('unresolved_relevance')
        candidate['conditions'].append('raw_effect_or_selector_mapping_unresolved')
    candidate['spatial_relations'] = tuple(spatial)
    return tuple(sorted(labels))


def _same_source(left, right):
    if type(left) is RawRecordRef and type(right) is RawRecordRef:
        return (left.source == right.source and left.line == right.line
                and left.sha256.lower() == right.sha256.lower())
    return type(left) is SourceEdgeRef and type(right) is SourceEdgeRef and left == right


def _associations(ctx, candidate, budget, gaps):
    writes, produced = [], []
    for resolved in ctx.resolved_writes.values():
        row = resolved['row']
        matches = False
        for reference in (row.stage, *row.evidence):
            if not budget.take('association_joins', f'{candidate["id"]}.write'):
                break
            if _same_source(reference, candidate['source']):
                matches = True
        if matches:
            writes.append(resolved)
        if budget.truncated:
            break
    write_ids = {item['row'].id for item in writes}
    for resolved in ctx.resolved_produced.values():
        if not budget.take('association_joins', f'{candidate["id"]}.produced'):
            break
        if resolved['row'].write in write_ids:
            produced.append(resolved)
    candidate['write_associations'], candidate['outcome_productions'] = tuple(writes), tuple(produced)
    if not writes:
        candidate['conditions'].append('missing_exact_write_join')
        _gap(gaps, 'production_write_join_missing', str(candidate['id']),
             'no exact SourceEdgeRef or physical raw line/SHA stage connects this source fact to a write')
    elif write_ids - {item['row'].write for item in produced}:
        candidate['conditions'].append('missing_exact_outcome_production_join')
        _gap(gaps, 'production_outcome_join_missing', str(candidate['id']),
             'write association has no exact produced-selector/outcome join; host establishment may have no work outcome')


def _groups(candidates, budget, gaps):
    """Only an identical physical raw stage AND production/placement can group."""
    groups, by_write = [], {}
    for candidate in candidates:
        for write in candidate['current_write_associations']:
            if not budget.take('association_joins', 'current_production.write'):
                break
            row = write['row']
            group = by_write.get(row.id)
            if group is None and type(row.stage) is RawRecordRef:
                for item in groups:
                    if not budget.take('association_joins', 'current_production.group'):
                        break
                    if (type(item['stage']) is RawRecordRef and _same_source(item['stage'], row.stage)
                            and item['production'] == row.production and item['placement'] == row.placement
                            and item['writer'] == row.writer):
                        group = item
                        break
            if group is None:
                group = {'stage': row.stage, 'production': row.production, 'placement': row.placement,
                         'writer': row.writer, 'write_associations': [], 'outcome_productions': [],
                         'candidates': [], '_write_ids': set(), '_produced_ids': set(), '_candidate_ids': set(),
                         'conditions': ('source/native applicability and demand coverage remain unverified',)}
                groups.append(group)
            by_write[row.id] = group
            if row.id not in group['_write_ids']:
                group['write_associations'].append(write)
                group['_write_ids'].add(row.id)
            if candidate['id'] not in group['_candidate_ids']:
                group['candidates'].append(candidate['id'])
                group['_candidate_ids'].add(candidate['id'])
            for item in candidate['outcome_productions']:
                if not budget.take('association_joins', 'current_production.produced'):
                    break
                if item['row'].write == row.id and item['row'].id not in group['_produced_ids']:
                    group['outcome_productions'].append(item)
                    group['_produced_ids'].add(item['row'].id)
    if len(groups) > 1:
        _gap(gaps, 'production_duplicate_stage_unresolved', 'current_production',
             'distinct source stages/production/placement remain separate; shared host, ticket or ancestry does not prove duplicate work')
    return tuple({**{key: value for key, value in group.items() if not key.startswith('_')},
        **{key: tuple(group[key]) for key in
        ('write_associations', 'outcome_productions', 'candidates')}} for group in groups)


def production(ctx, read_id, *, budget=4096):
    """Return conditional source candidates for an original content read.

    No caller-supplied contribution list is accepted. The result is detached,
    contains no target tensor values, and never grants runtime/ready authority.
    """
    gaps = []
    traversal = _Budget(budget, gaps)
    if type(read_id) is not ContentReadID:
        raise TypeError('production read must be an exact ContentReadID')
    resolved = ctx.resolved_content_reads[read_id]
    read, placement = resolved['read'], resolved['placement']
    materialization = None if type(read.placement) is Unresolved else read.placement.materialization
    version = (None if placement is None or placement[0] is None or materialization is None
               else VersionRef(materialization.artifact, placement[0].value_version))
    demand = {'read': read, 'run': _run(ctx, resolved), 'placement': read.placement,
              'materialization': materialization, 'version': version,
              'selector': None if placement is None else placement[1],
              'denotation': resolved['denotation'], 'state_support': read.support}
    lineage, lineage_keys = _lineage(ctx, version, traversal, gaps)
    candidates, pending = _universe(ctx, demand['run'], traversal, gaps)
    # All independent source rows are enumerated before any optional write or
    # bridge joins. Deleting associations cannot shrink this candidate prefix.
    for candidate in candidates:
        candidate['endpoints'] = _endpoints(ctx, candidate, traversal, gaps)
        _associations(ctx, candidate, traversal, gaps)
        candidate['relevance'] = _relevance(ctx, candidate, demand, lineage_keys, traversal)
        if traversal.truncated:
            candidate['conditions'].append('traversal_incomplete')
        candidate['conditions'] = tuple(dict.fromkeys(candidate['conditions']))
    groups = _groups(candidates, traversal, gaps)
    _gap(gaps, 'production_capture_unverified', 'inventory',
         'format replay accounts for supplied files, not all runtime writes, aliases, dropped events or external effects')
    return deepcopy({'read': read, 'demand': demand, 'lineage_prerequisites': lineage,
        'candidates': tuple(candidates), 'current_production': groups,
        'possible_invalidators': tuple(item['id'] for item in candidates if 'possible_invalidator' in item['relevance']),
        'unresolved_relevance': tuple(item['id'] for item in candidates if 'unresolved_relevance' in item['relevance']),
        'pending_sources': pending,
        'gaps': tuple({'code': item.code, 'path': item.path, 'message': item.message} for item in ctx.gaps) + tuple(gaps),
        'budget_used': traversal.used, 'budget_costs': traversal.costs, 'truncated': traversal.truncated,
        'budget_scope': 'lineage/source rows/association joins/selector ranks; excludes snapshot/replay byte/line costs and detached report copying',
        'source_runtime_verified': False, 'readiness_verified': False, 'transformation_authorized': False})


__all__ = ['production']
