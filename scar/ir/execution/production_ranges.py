"""Shared original-result/actual-selector guard for work and host production.

The fixed byte-prefix profile is a declaration parser, not a native adapter.
It preserves P diagnostics and original artifact-scoped regions verbatim.
"""
from scar.ir.program.model import DataValue, LiteralOrigin
from scar.ir.program.providers import ProviderFactReference
from .common import Unresolved
from .content import StorageContent
from .content_validation import artifact_key
from .coverage import CoverageStatus, RegionRef, _ValueCatalog, _storage_coverage
from .production import BytePrefixWrite, RawRecordRef


def _profile(ctx, resolved, path):
    record = resolved['record']
    payload = record.payload
    if type(payload) is not dict:
        ctx.gap('production_profile_unavailable', path, 'raw record has no decoded JSON object payload')
        return None
    metadata = payload.get('metadata')
    keys = {'schema', 'schema_version', 'stage', 'requested_bytes', 'written_bytes'}
    if type(metadata) is not dict or 'scar_native_result' not in metadata:
        ctx.gap('production_profile_unavailable', path, 'exact raw record has no byte-prefix protocol payload')
        return None
    profile = metadata['scar_native_result']
    if (type(profile) is not dict or set(profile) != keys
            or profile['schema'] != 'scar.native.byte-prefix-write'
            or type(profile['schema_version']) is not int or profile['schema_version'] != 1
            or type(profile['stage']) is not str or not profile['stage']):
        ctx.issue('production_profile', path, 'native result must have the exact closed byte-prefix schema')
        return None
    requested, written = profile['requested_bytes'], profile['written_bytes']
    if (type(requested) is not int or type(written) is not int
            or requested < 0 or written < 0 or written > requested):
        ctx.issue('production_profile_count', path, 'native byte counts must be exact integers with 0 <= written <= requested')
        return None
    return profile


def _actual_placement(ctx, write, actual_ref, actual, path):
    """Check physical correspondence independently of a result protocol.

    Unknown write semantics cannot waive a known storage/Mat contradiction.
    Endpoint selectors need their own interpreted placement protocol.
    """
    if type(actual_ref) is not RegionRef or actual is None:
        return None
    resolved = ctx.resolved_writes.get(write.id)
    if (type(write.placement) is not StorageContent or resolved is None
            or resolved['placement'] is None):
        ctx.gap('production_actual_placement_unresolved', path,
                'actual byte region has no interpreted original storage materialization placement')
        return None
    mat, _ = resolved['placement']
    artifact = write.placement.materialization.artifact
    if artifact_key(actual_ref.artifact) != artifact_key(artifact):
        ctx.issue('production_selector_scope', path,
                  'actual and original materialization belong to different exact ValueGraphs')
        return False
    if mat.region is None:
        ctx.gap('production_actual_placement_unresolved', path,
                'original materialization has no storage region for this actual byte selector')
        return None
    graph = ctx.external_values(artifact, path)
    if graph is None:
        return None
    region = graph.regions[mat.region]
    if actual.allocation != region.allocation:
        ctx.issue('production_selector_allocation', path,
                  'actual selector belongs to another allocation incarnation')
        return False
    original = RegionRef(artifact, mat.region)
    coverage = _storage_coverage(actual_ref, (original,),
        catalog=_ValueCatalog.from_snapshots(ctx.snapshots), budget=4096)
    if coverage.status is CoverageStatus.INCOMPLETE:
        ctx.issue('production_actual_outside', path,
                  'actual selector extends outside the original materialization region')
        return False
    if coverage.status is CoverageStatus.UNRESOLVED:
        ctx.gap('production_actual_coverage_unresolved', path,
                'actual selector subset is not established within geometry budget')
        return None
    return True


def resolve_actual_range(ctx, write, actual_ref, rule, result, path):
    from .source_validation import resolve_raw

    actual = None
    if type(actual_ref) is RegionRef:
        graph = ctx.external_values(actual_ref.artifact, path)
        actual = None if graph is None else graph.regions.get(actual_ref.region)
        if graph is not None and actual is None:
            ctx.issue('production_actual_region', path, 'actual selector is absent from exact ValueGraph')
    else:
        ctx.gap('production_actual_unresolved', path, 'actual selector has no parsed byte geometry')
    placement_match = _actual_placement(ctx, write, actual_ref, actual, path)
    raw, profile, requested = None, None, None
    if type(rule) is BytePrefixWrite:
        if type(write.stage) is not RawRecordRef:
            ctx.gap('production_profile_stage_unresolved', path, 'byte-prefix profile requires an exact original raw record stage')
        else:
            raw = resolve_raw(ctx, write.stage, path)
            if raw is not None:
                profile = _profile(ctx, raw, path)
        resolved = ctx.resolved_writes.get(write.id)
        if type(write.placement) is not StorageContent:
            ctx.gap('production_profile_placement_unresolved', path, 'byte-prefix rule does not interpret endpoint or unknown placements')
        elif resolved is not None and resolved['placement'] is not None:
            mat, selector = resolved['placement']
            if selector is not None:
                graph = ctx.external_values(selector.artifact, path)
                requested = None if graph is None else graph.regions.get(selector.region)
            if requested is not None and actual is not None:
                if requested.allocation != actual.allocation:
                    ctx.issue('production_selector_allocation', path, 'actual selector belongs to another allocation incarnation')
                linear = lambda x: x.dtype == 'uint8' and x.layout == 'strided' and len(x.shape) == 1 and x.strides == (1,)
                if not linear(requested) or not linear(actual):
                    ctx.gap('production_byte_layout_unresolved', path, 'prefix rule only interprets linear rank1 uint8 byte buffers')
                elif profile is not None:
                    if requested.shape != (profile['requested_bytes'],) or actual.shape != (profile['written_bytes'],):
                        ctx.issue('production_selector_count', path, 'original selector geometry does not equal parsed requested/produced byte counts')
                    if actual.offset != requested.offset:
                        ctx.issue('production_selector_offset', path, 'actual byte prefix must start at the original request offset')
        if type(result) is ProviderFactReference and raw is not None:
            original = raw['source'].raw_artifact
            if (artifact_key(result.artifact) != artifact_key(original)
                    or result.locator != f'#L{write.stage.line}/metadata/scar_native_result'):
                ctx.issue('production_protocol_result', path, 'protocol result must reference this exact raw record payload')
        elif type(result) is not Unresolved and result in ctx.values:
            definition = ctx.core_values[ctx.values[result].value]
            if (isinstance(definition, DataValue) and isinstance(definition.origin, LiteralOrigin)
                    and type(definition.origin.value) is int and profile is not None):
                if definition.origin.value != profile['written_bytes']:
                    ctx.issue('production_protocol_result', path, 'literal protocol result conflicts with parsed produced bytes')
            else:
                ctx.gap('production_result_unresolved', path, 'original result value has no decoded exact integer payload/port correspondence')
        else:
            ctx.gap('production_result_unresolved', path, 'protocol result has no parsed exact raw/result correspondence')
    else:
        ctx.gap('production_rule_unresolved', path, rule.reason)
    return {'actual': actual, 'requested': requested, 'rawprofile': profile,
            'raw': raw, 'protocol_result': result, 'placement_match': placement_match}


__all__ = ['resolve_actual_range']
