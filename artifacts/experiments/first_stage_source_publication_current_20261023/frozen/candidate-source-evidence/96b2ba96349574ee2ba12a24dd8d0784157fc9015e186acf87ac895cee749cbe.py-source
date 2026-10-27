"""Resolve independent source inventories and scoped endpoint associations.

Format replay gives structural correspondence inside one bundle. It does not
certify capture completeness, physical writes or cross-artifact value equality.
"""
from scar.ir.v2.evidence import EvidenceEndpoint, EvidenceGraph, EvidenceNodeKind as N
from .content import ObjectRef, VersionRef
from .content_validation import artifact_key
from .coverage import RegionRef
from .inventory import InventoryResolver
from .production import RawRecordRef, SourceEdgeRef, SourceEndpointRef
from .resources import AllocationTarget
from .snapshot import SnapshotError
from .work import MaterializationRef


def source_inventory_errors(ctx):
    """Load sources before resource/D validation so bundle scope is reusable."""
    ctx.source_resolutions, ctx.inventory_sources = {}, {}
    replayed, included = {}, set()
    for binding in ctx.source_inventories.values():
        path = f'source_inventories[{binding.id}]'
        if binding.run not in ctx.runs:
            ctx.issue('inventory_run', path, 'source inventory references an absent canonical run')
        try:
            key = artifact_key(binding.manifest), artifact_key(binding.index)
            if key not in replayed:
                replayed[key] = InventoryResolver(ctx.snapshots).resolve(binding.manifest, binding.index)
            result = replayed[key]
            ctx.source_resolutions[binding.id] = result
            for gap in result.gaps:
                ctx.gap(gap.code, f'{path}.{gap.path}', gap.message)
            for source in result.sources:
                ctx.inventory_sources[binding.id, source.key] = source
                if source.bundle is not None:
                    for artifact, graph in (
                        (source.evidence_artifact, source.bundle.evidence),
                        (source.values_artifact, source.bundle.values),
                        (source.semantic_artifact, source.bundle.semantic),
                    ):
                        component = artifact_key(artifact)
                        if component not in included:
                            ctx.snapshots.include(artifact, graph)
                            included.add(component)
        except SnapshotError as error:
            ctx.issue(error.code, path, str(error))
        except (TypeError, ValueError, KeyError, AttributeError, OverflowError, RecursionError) as error:
            ctx.issue('inventory_invalid', path, str(error))


def _source(ctx, reference, path):
    binding = ctx.source_inventories.get(reference.inventory)
    if binding is None:
        ctx.issue('inventory_binding', path, 'source refers to an absent inventory binding')
        return None
    source = ctx.inventory_sources.get((reference.inventory, reference.stream))
    if source is None:
        resolution = ctx.source_resolutions.get(reference.inventory)
        known_empty = resolution is not None and any(
            row.code == 'inventory_sources_empty' for row in resolution.gaps)
        if resolution is None or not resolution.sources and not known_empty:
            ctx.gap('inventory_source_pending', path, 'source manifest was not resolved; source membership remains pending')
        else:
            ctx.issue('inventory_stream', path, 'source stream is absent from its exact manifest')
        return None
    return {'source': source, 'inventory': binding, 'run': binding.run,
            'raw_artifact': source.raw_artifact, 'artifact': source.evidence_artifact,
            'graph': None if source.bundle is None else source.bundle.evidence}


def resolve_raw(ctx, reference, path):
    if type(reference) is not RawRecordRef:
        raise TypeError('resolve_raw requires exact RawRecordRef')
    reference.__post_init__()
    result = _source(ctx, reference.source, path)
    if result is None:
        return None
    source = result['source']
    record = next((row for row in source.raw_records if row.line == reference.line), None)
    if record is None:
        if source.projection_replayed:
            ctx.issue('inventory_raw_line', path, 'raw line is absent from exact source bytes')
        else:
            ctx.gap('inventory_raw_pending', path, 'raw line/projection is pending, not an absent write')
        return None
    if record.sha256 != reference.sha256.lower():
        ctx.issue('inventory_raw_digest', path, 'raw reference names different physical line bytes')
        return None
    if record.payload is None:
        ctx.gap('inventory_raw_unparsed', path, 'physical source line has no parsed JSON object')
        return None
    return {**result, 'record': record}


def resolve_edge(ctx, reference, path):
    if type(reference) is not SourceEdgeRef:
        raise TypeError('resolve_edge requires exact SourceEdgeRef')
    reference.__post_init__()
    result = _source(ctx, reference.source, path)
    if result is None:
        return None
    if result['graph'] is None:
        ctx.gap('inventory_projection_pending', path, 'source projection is unavailable; source edges remain pending')
        return None
    edge = result['graph'].edges.get(reference.edge)
    if edge is None:
        ctx.issue('inventory_edge', path, 'source edge is absent from its exact normalized projection')
        return None
    return {**result, 'edge': edge}


def resolve_endpoint(ctx, reference, path):
    """Derive facets only within the strict replayed IRBundle component scope."""
    if type(reference) is not SourceEndpointRef:
        raise TypeError('resolve_endpoint requires exact SourceEndpointRef')
    reference.__post_init__()
    result = _source(ctx, reference.source, path)
    if result is None:
        return None
    source, endpoint = result['source'], reference.endpoint
    if result['graph'] is None:
        ctx.gap('inventory_projection_pending', path, 'source endpoint projection is pending')
        return None
    if not result['graph']._endpoint_exists(endpoint):
        ctx.issue('inventory_endpoint', path, 'endpoint is absent from its exact normalized projection')
        return None
    graph = source.bundle.values
    version = mat = obj = region = allocation = observation = None
    if endpoint.kind is N.VALUE_OBSERVATION:
        observation = result['graph'].observations[endpoint.reference]
        version, mat = observation.version, observation.materialization
    elif endpoint.kind is N.VALUE_VERSION:
        version = endpoint.reference
    elif endpoint.kind is N.MATERIALIZATION:
        mat = endpoint.reference
    elif endpoint.kind is N.OBJECT:
        obj = endpoint.reference
        versions = {row.value_version for row in graph.bindings if row.object_id == obj}
        if len(versions) == 1:
            version = next(iter(versions))
        elif len(versions) > 1:
            ctx.gap('inventory_object_versions', path, 'object bindings span multiple versions; no current version is selected')
    elif endpoint.kind is N.STORAGE_REGION:
        region = endpoint.reference
    elif endpoint.kind is N.ALLOCATION:
        allocation = endpoint.reference
    if mat is not None:
        materialization = graph.materializations.get(mat)
        if materialization is None:
            ctx.issue('inventory_materialization', path, 'bundle endpoint materialization is absent from its original ValueGraph')
        else:
            version, region = materialization.value_version, materialization.region
    if region is not None:
        original = graph.regions.get(region)
        if original is None:
            ctx.issue('inventory_region', path, 'bundle endpoint region is absent from its original ValueGraph')
        else:
            allocation = original.allocation
    if version is not None and version not in graph.versions:
        ctx.issue('inventory_version', path, 'bundle endpoint version is absent from its original ValueGraph')
    if allocation is not None and allocation not in graph.allocations:
        ctx.issue('inventory_allocation', path, 'bundle endpoint allocation is absent from its original ValueGraph')
    return {**result, 'endpoint': endpoint, 'observation': observation,
            'value_version': version, 'materialization': mat, 'object': obj,
            'region': region, 'allocation': allocation,
            'values_artifact': source.values_artifact}


def target_original(ctx, target, path):
    """Return a scoped existing target facet, never a synthesized producer."""
    if type(target) is ObjectRef and target.artifact.schema == EvidenceGraph.SCHEMA:
        graph = ctx._external(target.artifact, path, EvidenceGraph, ctx.evidence_graphs)
        if graph is None:
            return None
        endpoint = EvidenceEndpoint(N.OBJECT, target.object)
        if not graph._endpoint_exists(endpoint):
            ctx.issue('inventory_bridge_target', path, 'object target is absent from its exact EvidenceGraph registry')
            return None
        return {'facet': 'object', 'identity': target.object, 'original': endpoint,
                'graph': graph, 'artifact': target.artifact}
    graph = ctx.external_values(target.artifact, path)
    if graph is None:
        return None
    if type(target) is VersionRef:
        facet, identity, original = 'value_version', target.version, graph.versions.get(target.version)
    elif type(target) is MaterializationRef:
        facet, identity = 'materialization', target.materialization
        original = graph.materializations.get(identity)
    elif type(target) is ObjectRef:
        facet, identity = 'object', target.object
        original = graph.objects.get(identity)
        if original is None:
            original = tuple(row for row in graph.bindings if row.object_id == identity) or None
    elif type(target) is RegionRef:
        facet, identity, original = 'region', target.region, graph.regions.get(target.region)
    elif type(target) is AllocationTarget:
        facet, identity = 'allocation', target.allocation
        original = graph.allocations.get(identity)
    else:
        raise TypeError('source bridge target must be a scoped ValueGraph facet')
    if original is None:
        ctx.issue('inventory_bridge_target', path, 'bridge target is absent from its exact original ValueGraph')
        return None
    return {'facet': facet, 'identity': identity, 'original': original, 'graph': graph,
            'artifact': target.artifact}


def source_bridge_errors(ctx):
    ctx.resolved_source_bridges = {}
    for row in ctx.source_bridges.values():
        path = f'source_bridges[{row.id}]'
        source = resolve_endpoint(ctx, row.endpoint, path)
        target = target_original(ctx, row.target, path)
        if source is not None and target is not None:
            source_artifact = (source['artifact'] if target['facet'] == 'object'
                               and target['artifact'].schema == EvidenceGraph.SCHEMA
                               else source['values_artifact'])
            same_scope = artifact_key(source_artifact) == artifact_key(target['artifact'])
            original = source[target['facet']]
            if same_scope and original is not None and original != target['identity']:
                ctx.issue('inventory_bridge_conflict', path, 'bridge contradicts the original endpoint identity in the same exact ValueGraph')
            elif original is None:
                ctx.gap('inventory_bridge_facet_unresolved', path, 'source endpoint does not select this facet; an association is not derivation proof')
            if not same_scope:
                ctx.gap('inventory_bridge_cross_scope_unverified', path,
                        'explicit cross-artifact association has no content/native identity proof; bare IDs are not compared')
        ctx.gap('inventory_bridge_runtime_unverified', path, 'endpoint bridge is a declared association, not runtime/capture authority')
        ctx.resolved_source_bridges[row.id] = {'row': row, 'source': source, 'target': target}


__all__ = ['source_inventory_errors', 'source_bridge_errors', 'resolve_raw',
           'resolve_edge', 'resolve_endpoint', 'target_original']
