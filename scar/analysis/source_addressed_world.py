"""Attach source receiver/field/index paths to the shared world graph."""
import argparse
from collections import Counter
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis.source_world_flow import read_world_flow
from scar.analysis.source_context_query import ContextTargetGraph
from scar.analysis.source_reference_slice import ReferenceSlicer, source_port
from scar.analysis.source_address_paths import AddressResolver
from scar.analysis.normal_output import write_table
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import addressed_world_flow as A, source_address_paths as L
from scar.ir.program import source_productions as P, normal_targets as T
from scar.ir.program.providers import ProviderArtifact
from scar.ir.literals import PythonLiteral
from scar.ir.record_codec import encode, decode


def _artifact(path, schema):
    path = Path(path).absolute(); raw = path.read_bytes()
    return ProviderArtifact(str(path), sha256(raw).hexdigest(), len(raw), schema)


def _pins():
    from scar.analysis import source_address_paths
    return {name: sha256(Path(path).read_bytes()).hexdigest() for name, path in (
        ('publisher', __file__), ('types', A.__file__), ('paths', source_address_paths.__file__), ('path_types', L.__file__))}


def _derive(world, catalog, limits):
    report, queries = read_world_flow(world); catalog = ContextTargetGraph(catalog)
    store = catalog.fact_store; slicer = ReferenceSlicer(type('SourceOnly', (), {'fact_store': store})())
    result = []
    for query_ordinal, query in enumerate(queries):
        material = _artifact(Path(query.source_templates.uri), query.source_templates.schema)
        if material != query.source_templates: raise ValueError('address graph source templates changed')
        unit = store.load(query.unit)
        fn = next(f for f in unit.functions if T.Body(unit.unit, f.template, f.body) == query.caller_body)
        resolver = AddressResolver(store, unit, fn.body_scope.owner)
        records = []
        for access_ordinal, access in enumerate(query.accesses):
            ordinal = int(access.fact.locator.rsplit('/', 1)[1])
            if access.fact != slicer.fact(unit, access.table, ordinal): raise ValueError('address input selects foreign source facts')
            row = getattr(unit, access.table)[ordinal]
            before, after = source_port(unit, row.world), source_port(unit, row.result_world)
            if before != access.world_before or after != access.world_after: raise ValueError('address projection changed original worlds')
            locations = (); inputs = []
            if access.table == 'calls':
                def argument(role, position, value, name=None):
                    inputs.append(A.CallAddressInput(role, position, name, source_port(unit, value),
                        resolver.paths(value, **limits)))
                argument('CALLEE', 0, row.callee)
                for i, point in enumerate(row.positional): argument('POSITIONAL', i, point)
                for i, (name, point) in enumerate(row.keywords): argument('KEYWORD', i, point, name)
                if row.positional_pack is not None: argument('POSITIONAL_PACK', 0, row.positional_pack)
                if row.keyword_pack is not None: argument('KEYWORD_PACK', 0, row.keyword_pack)
                effect = 'CALL_READ_WRITE_ESCAPE_RNG_AND_EXTERNAL_EFFECTS_OPEN'
            else:
                if access.table == 'attributes':
                    selector = L.FieldSelector(row.name)
                    guards = ('DEFAULT_ATTRIBUTE_LOCATION_PATH_SELECTED', 'DESCRIPTOR_EFFECTS_NOT_PROVEN')
                elif access.table == 'items':
                    key = row.key if type(row.key) is PythonLiteral else source_port(unit, row.key)
                    selector = L.ItemSelector(key)
                    guards = ('DEFAULT_INDEX_LOCATION_PATH_SELECTED', 'INDEX_PROTOCOL_EFFECTS_NOT_PROVEN')
                else: raise ValueError('unsupported original world access table')
                locations = tuple(replace(path, selectors=(*path.selectors, selector),
                    evidence=(*path.evidence, access.fact), conditions=(*path.conditions, *guards))
                    for path in resolver.paths(row.receiver, **limits))
                effect = guards[-1]
            records.append(A.AddressedAccess(access_ordinal, access.fact, access.table, access.action,
                before, after, locations, tuple(inputs), effect))
        result.append(A.AddressedWorld(query_ordinal, query.unit, query.anchor, query.normal_exit, tuple(records)))
    store.validate_parents(); return tuple(result)


def _counts(rows):
    accesses = [a for q in rows for a in q.accesses]
    paths = [p for a in accesses for p in (*a.locations, *(p for i in a.call_inputs for p in i.paths))]
    return dict(queries=len(rows), accesses=len(accesses), addressed_accesses=sum(bool(a.locations) for a in accesses),
        call_sites=sum(bool(a.call_inputs) for a in accesses), paths=len(paths),
        path_roots=dict(Counter(p.root_kind.value for p in paths)), unresolved_paths=sum(p.frontier is not None for p in paths),
        effect_frontiers=dict(Counter(a.effect_frontier for a in accesses)))


def build_addressed_world(world, catalog, out, *, max_states=1000, max_depth=128):
    started = time.monotonic(); world = Path(world).absolute(); catalog = Path(catalog).absolute(); out = Path(out).absolute()
    if out.exists(): raise ValueError('fresh addressed-world output required')
    pins = _pins(); parents = dict(world=_artifact(world/'result.json', 'scar.source-world-flow'),
        catalog=_artifact(catalog/'result.json', 'scar.context-source-targets'))
    limits = dict(max_states=max_states, max_depth=max_depth); rows = _derive(world, catalog, limits)
    if pins != _pins(): raise ValueError('source address rules changed')
    for name, root in (('world', world), ('catalog', catalog)):
        if _artifact(root/'result.json', parents[name].schema) != parents[name]: raise ValueError('addressed world parent changed')
    _durable_mkdir(out); table = write_table(out/'queries.jsonl.gz', rows)
    report = dict(schema='scar.addressed-source-world', schema_version=1, status='SYMBOLIC_LOCATIONS_CONNECTED_TO_WORLDS',
        world=str(world), catalog=str(catalog), parents={k: encode(v) for k, v in parents.items()}, pins=pins, limits=limits,
        table=table, counts=_counts(rows), current_content_versions_proven=False, runtime_identity_proven=False,
        effects_discharged=False, target_executed=False, first_stage_complete=False, seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json', _json(report), replace=False); return report


def read_addressed_world(path):
    path = Path(path).absolute(); raw = (path/'result.json').read_bytes(); r = json.loads(raw)
    if (r['schema'], r['schema_version']) != ('scar.addressed-source-world', 1) or r['pins'] != _pins(): raise ValueError('address graph producer differs')
    for name in ('world', 'catalog'):
        ref = r['parents'][name]
        if encode(_artifact(Path(r[name])/'result.json', ref['schema'])) != ref: raise ValueError('address graph parent differs')
    rows = tuple(decode(A.AddressedWorld, w, record_tags=P.PRODUCTION_RECORD_TAGS) for w in _table(path, r['table']))
    if rows != _derive(r['world'], r['catalog'], r['limits']) or _counts(rows) != r['counts']: raise ValueError('address paths or original worlds differ')
    if any(r[k] is not False for k in ('current_content_versions_proven', 'runtime_identity_proven', 'effects_discharged',
            'target_executed', 'first_stage_complete')): raise ValueError('source address graph cannot grant current content proof')
    if (path/'result.json').read_bytes() != raw: raise ValueError('address graph changed during verification')
    return r, rows


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--world'); p.add_argument('--catalog'); p.add_argument('--out'); p.add_argument('--read')
    a = p.parse_args()
    if a.read: report, _ = read_addressed_world(a.read)
    else:
        if not a.world or not a.catalog or not a.out: p.error('--world --catalog --out required')
        report = build_addressed_world(a.world, a.catalog, a.out)
    print(json.dumps(dict(status=report['status'], counts=report['counts'])), flush=True)


if __name__ == '__main__': main()
