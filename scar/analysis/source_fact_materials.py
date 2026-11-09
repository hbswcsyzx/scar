"""Resolve collection-relative evidence to checked original fact shards.

Old evidence keys remain intact. Resolution follows the catalog's recorded
unit_parent selection, never a filename search, symlink or guessed provider.
This layer verifies material/locators, not the graph's semantic derivation.
"""
import argparse
from collections import defaultdict
from dataclasses import replace
import gzip
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis.source_context_query import ContextTargetGraph
from scar.analysis.source_symbol_variants import _table
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.source_fact_materials import FactMaterialRoute
from scar.ir.record_codec import decode, encode


SCHEMA = 'scar.source-fact-materials'
FACTS = 'scar.source-facts-unit'


def _artifact(path, raw, schema):
    return ProviderArtifact(str(path), sha256(raw).hexdigest(), len(raw), schema)


class FactMaterialResolver:
    def __init__(self, catalog):
        self.catalog = ContextTargetGraph(catalog)
        self.store = self.catalog.fact_store
        self.catalog_raw = (self.catalog.path/'result.json').read_bytes()
        context = _artifact(self.catalog.path/'result.json', self.catalog_raw, self.catalog.report['schema'])
        receipt = self.catalog.report['context_facts']
        directory = ProviderArtifact(str(self.catalog.path/receipt['path']), receipt['sha256'],
            receipt['bytes'], self.store.report['schema'])
        self._routes = {}; self._rows = {}
        for unit, row in self.store.rows.items():
            logical = Path(row['facts']); physical = logical; catalogs = [context, directory]
            if not logical.is_absolute():
                parent = self.store._source_parents[unit]
                logical = parent.path/logical
                while True:
                    catalogs.append(_artifact(parent.path/'result.json', parent.raw, parent.report['schema']))
                    if not parent.parents: break
                    parent = parent.parents[parent.unit_parent[unit]]
                if parent.rows[unit] != row:
                    raise ValueError('source fact material row differs from its selected primitive parent')
                physical = parent.path/row['facts']
            route = FactMaterialRoute(unit,
                ProviderArtifact(str(logical), row['sha256'], row['bytes'], FACTS),
                ProviderArtifact(str(physical), row['sha256'], row['bytes'], FACTS),
                tuple(catalogs), row.get('facts_format', 'SOURCE_FACT_JSON'))
            for key in (route.logical, route.physical):
                if key in self._routes and self._routes[key] != route:
                    raise ValueError('source evidence material has conflicting catalog routes')
                self._routes[key] = route
            self._rows[unit] = row
        self.validate_catalog()

    def validate_catalog(self):
        if self.catalog_raw != (self.catalog.path/'result.json').read_bytes():
            raise ValueError('source material context catalog changed')
        self.store.validate_parents()

    def route(self, reference):
        if type(reference) is not ProviderFactReference or reference.artifact.schema != FACTS:
            raise ValueError('expected a source fact evidence reference')
        try: return self._routes[reference.artifact]
        except KeyError: raise ValueError('source evidence is outside the recorded catalog') from None

    def verify(self, references):
        grouped = defaultdict(set)
        for reference in references: grouped[self.route(reference)].add(reference.locator)
        checked_catalogs = set()
        for route, locators in grouped.items():
            for catalog in route.catalogs:
                if catalog in checked_catalogs: continue
                raw = Path(catalog.uri).read_bytes()
                if len(raw) != catalog.size_bytes or sha256(raw).hexdigest() != catalog.sha256:
                    raise ValueError('source material catalog route receipt differs')
                checked_catalogs.add(catalog)
            raw = Path(route.physical.uri).read_bytes(); row = self._rows[route.unit]
            if len(raw) != route.physical.size_bytes or sha256(raw).hexdigest() != route.physical.sha256:
                raise ValueError('source fact physical material receipt differs')
            payload = gzip.decompress(raw)
            if len(payload) != row['decoded_bytes'] or sha256(payload).hexdigest() != row['decoded_sha256']:
                raise ValueError('source fact decoded material receipt differs')
            if route.format == 'COMPILE_CONTEXT_F4_JSONL':
                records = payload.splitlines()
                if len(records) != row['records'] or len(records) != 1:
                    raise ValueError('compiled source facts require the original one-record table')
                document = dict(records=[json.loads(records[0])]); fact = document['records'][0]
            else: document = fact = json.loads(payload)
            if fact['unit'] != route.unit: raise ValueError('source fact material belongs to another unit')
            for locator in locators:
                if not locator.startswith('#/'): raise ValueError('source fact locator is not a JSON pointer')
                value = document
                for part in locator[2:].split('/'):
                    part = part.replace('~1', '/').replace('~0', '~')
                    if isinstance(value, list):
                        if not part.isdecimal() or str(int(part)) != part:
                            raise ValueError('source fact table index is not canonical')
                        value = value[int(part)]
                    elif isinstance(value, dict): value = value[part]
                    else: raise ValueError('source fact locator traverses a scalar')
        self.validate_catalog()
        return tuple(sorted(grouped, key=lambda r: r.logical.uri))

    def resolve(self, reference):
        """Return a checked directly readable reference, preserving its locator."""
        self.verify((reference,))
        return replace(reference, artifact=self.route(reference).physical)


def _references(value, selected):
    if isinstance(value, dict):
        if set(value) == {'artifact', 'locator'} and value['artifact'].get('schema') == FACTS:
            selected.add(decode(ProviderFactReference, value)); return
        for child in value.values(): _references(child, selected)
    elif isinstance(value, list):
        for child in value: _references(child, selected)


def _inputs(paths):
    sources = []; references = set()
    for path in dict.fromkeys(Path(p).absolute() for p in paths):
        raw = (path/'result.json').read_bytes(); report = json.loads(raw)
        sources.append(dict(path=str(path), report=encode(_artifact(path/'result.json', raw, report['schema']))))
        _references(report, references)
        for receipt in report['tables'].values():
            for row in _table(path, receipt): _references(row, references)
        if raw != (path/'result.json').read_bytes(): raise ValueError('source graph changed during evidence collection')
    return sources, references


def _pins():
    from scar.ir.program import source_fact_materials
    return dict(producer=sha256(Path(__file__).read_bytes()).hexdigest(),
        types=sha256(Path(source_fact_materials.__file__).read_bytes()).hexdigest())


def build_fact_materials(catalog, graphs, out):
    started = time.monotonic(); pins = _pins(); out = Path(out).absolute()
    if out.exists(): raise ValueError('fresh fact material output required')
    resolver = FactMaterialResolver(catalog); sources, references = _inputs(graphs)
    routes = resolver.verify(references); _durable_mkdir(out)
    table = write_table(out/'routes.jsonl.gz', routes)
    report = dict(schema=SCHEMA, schema_version=1, status='SOURCE_FACT_MATERIALS_AND_LOCATORS_VERIFIED',
        catalog=str(resolver.catalog.path), sources=sources, pins=pins, tables=dict(routes=table),
        counts=dict(graphs=len(sources), references=len(references), materials=len(routes),
            relocated_materials=sum(r.logical != r.physical for r in routes),
            compressed_material_bytes=sum(r.physical.size_bytes for r in routes)),
        reference_coverage='ALL_SOURCE_FACT_REFERENCES_STORED_IN_LISTED_GRAPH_REPORTS_AND_TABLES',
        original_evidence_keys_retained=True, locators_physically_verified=True,
        source_relations_rederived=False, target_executed=False, first_stage_complete=False,
        seconds=time.monotonic()-started)
    if pins != _pins(): raise ValueError('source fact material rules changed')
    _durable_bytes(out/'result.json', _json(report), replace=False); return report


def read_fact_materials(path):
    path = Path(path).absolute(); raw = (path/'result.json').read_bytes(); report = json.loads(raw)
    if (report['schema'], report['schema_version']) != (SCHEMA, 1) or report['pins'] != _pins():
        raise ValueError('source fact material producer differs')
    resolver = FactMaterialResolver(report['catalog'])
    sources, references = _inputs(source['path'] for source in report['sources'])
    routes = tuple(decode(FactMaterialRoute, row) for row in _table(path, report['tables']['routes']))
    if sources != report['sources'] or routes != resolver.verify(references):
        raise ValueError('source evidence catalog routes or physical locators differ')
    counts = dict(graphs=len(sources), references=len(references), materials=len(routes),
        relocated_materials=sum(r.logical != r.physical for r in routes),
        compressed_material_bytes=sum(r.physical.size_bytes for r in routes))
    if counts != report['counts'] or any(report[k] is not False for k in (
            'source_relations_rederived', 'target_executed', 'first_stage_complete')):
        raise ValueError('source fact material verification cannot grant graph semantics or execution')
    if report['original_evidence_keys_retained'] is not True or report['locators_physically_verified'] is not True:
        raise ValueError('source evidence resolution contract differs')
    if report['reference_coverage'] != 'ALL_SOURCE_FACT_REFERENCES_STORED_IN_LISTED_GRAPH_REPORTS_AND_TABLES':
        raise ValueError('source evidence reference coverage differs')
    if raw != (path/'result.json').read_bytes(): raise ValueError('source fact material index changed')
    return report, resolver


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog'); parser.add_argument('--graph', action='append', default=[])
    parser.add_argument('--out'); parser.add_argument('--read'); args = parser.parse_args()
    if args.read: report, _ = read_fact_materials(args.read)
    else:
        if not args.catalog or not args.graph or not args.out: parser.error('--catalog, --graph, --out required')
        report = build_fact_materials(args.catalog, args.graph, args.out)
    print(json.dumps(dict(status=report['status'], counts=report['counts'], seconds=report['seconds'])), flush=True)


if __name__ == '__main__': main()
