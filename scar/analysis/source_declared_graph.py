"""Store shared declared method contexts; never fabricate runtime call rows."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis import source_declared_contexts as engine
from scar.analysis.source_declared_contexts import DeclaredResolver, expand_contexts
from scar.analysis.source_field_graph import read_field_graph
from scar.analysis.source_reference_slice import ReferenceSlicer, source_port
from scar.analysis.source_relation_snapshot import RelationSnapshot
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_template_links import _json
from scar.ir.program import declared_contexts as D, normal_targets as T, source_productions as P
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import encode, decode


def _pins():
    return {name: sha256(Path(path).read_bytes()).hexdigest() for name, path in (
        ('publisher', __file__), ('contexts', engine.__file__), ('types', D.__file__))}


def _parent(path):
    path = Path(path).absolute(); raw = (path/'result.json').read_bytes()
    return ProviderArtifact(str(path/'result.json'), sha256(raw).hexdigest(), len(raw), 'scar.source-field-interface-graph')


def _derive(parent, limits):
    report, queries, proof = read_field_graph(parent)
    snapshot = RelationSnapshot(report['relations'], report['catalog'])
    slicer = ReferenceSlicer(snapshot); roots = []
    for shard, query in zip(report['shards'], queries):
        receipt = shard['table']
        artifact = ProviderArtifact(str(Path(parent).absolute()/shard['folder']/receipt['path']),
            receipt['sha256'], receipt['bytes'], 'scar.field-interface-query')
        unit, *_ = slicer.unit(query.unit)
        receiver = source_port(unit, unit.attributes[query.method_attribute_ordinal].receiver)
        for index, method in enumerate(query.methods):
            connection = method.connection
            inputs = tuple(D.ClassInput(route.formal, method.source_class, D.ClassValueKind.INSTANCE)
                for route in connection.parameters if route.kind is T.RouteKind.ARGUMENT and receiver in route.actuals)
            if not inputs: raise ValueError('parent instance method has no receiver argument route')
            context = D.DeclaredContext(connection.source_callable, connection.body, inputs)
            roots.append((context, connection, ProviderFactReference(artifact, '#/records/0/methods/'+str(index))))
    graph = expand_contexts(DeclaredResolver(slicer), tuple(roots), **limits)
    snapshot.validate_parents()
    return graph, proof


def _counts(graph):
    return dict(contexts=len(graph.contexts), entries=len(graph.entries), edges=len(graph.edges),
        frontiers=len(graph.frontiers), descriptors=dict(Counter(e.descriptor.kind.value for e in graph.edges)),
        shared_recursive_edges=sum(e.caller == e.target for e in graph.edges))


def build_declared_graph(parent, out, *, max_contexts=64, max_edges=1024):
    started = time.monotonic(); before = _pins(); parent = Path(parent).absolute(); out = Path(out).absolute()
    if out.exists(): raise ValueError('fresh declared context graph output required')
    parent_ref = _parent(parent); limits = dict(max_contexts=max_contexts, max_edges=max_edges)
    graph, proof = _derive(parent, limits)
    if _parent(parent) != parent_ref or _pins() != before: raise ValueError('declared graph inputs changed')
    _durable_mkdir(out)
    tables = {name: write_table(out/(name+'.jsonl.gz'), getattr(graph, name))
        for name in ('contexts', 'entries', 'edges', 'frontiers')}
    report = dict(schema='scar.declared-context-graph', schema_version=1,
        status='GUARDED_SOURCE_BODY_CONTEXTS_CONNECTED', pins=before, parent=str(parent),
        parent_ref=encode(parent_ref), tables=tables, counts=_counts(graph), limits=limits, semantics=graph.semantics,
        parent_witnesses_checked=proof['original_fact_reference_checks'],
        source_regions_shared=True, iteration_unrolled=False, historical_call_rows_modified=False,
        entry_admission_proven=False, current_state_versions_proven=False, runtime_dispatch_verified=False,
        transformation_authorized=False, target_executed=False, first_stage_complete=False,
        seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json', _json(report), replace=False)
    return report


def read_declared_graph(path):
    started = time.monotonic(); path = Path(path).absolute(); raw = (path/'result.json').read_bytes(); r = json.loads(raw)
    if ((r['schema'], r['schema_version']) != ('scar.declared-context-graph', 1) or r['pins'] != _pins()
            or encode(_parent(r['parent'])) != r['parent_ref']): raise ValueError('declared graph producer or parent differs')
    hints = dict(contexts=D.DeclaredContext, entries=D.DeclaredContextEntry, edges=D.DeclaredContextEdge,
        frontiers=D.ContextFrontier)
    records = {name: tuple(decode(hints[name], row, record_tags=P.PRODUCTION_RECORD_TAGS)
        for row in _table(path, r['tables'][name])) for name in hints}
    graph = D.DeclaredContextGraph(**records)
    expected, proof = _derive(r['parent'], r['limits'])
    if graph != expected or _counts(graph) != r['counts'] or r['semantics'] != graph.semantics:
        raise ValueError('declared class inputs, descriptors, paths, scopes or call interfaces differ')
    if (r['source_regions_shared'] is not True or r['iteration_unrolled'] is not False
            or r['historical_call_rows_modified'] is not False): raise ValueError('declared graph cannot clone runtime or source call identity')
    for name in ('entry_admission_proven', 'current_state_versions_proven', 'runtime_dispatch_verified',
            'transformation_authorized', 'target_executed', 'first_stage_complete'):
        if r[name] is not False: raise ValueError('declared graph cannot grant runtime or transformation authority')
    if (path/'result.json').read_bytes() != raw: raise ValueError('declared graph changed during validation')
    return r, graph, dict(parent_original_fact_reference_checks=proof['original_fact_reference_checks'],
        verification_seconds=time.monotonic()-started)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent'); parser.add_argument('--out'); parser.add_argument('--read')
    parser.add_argument('--max-contexts', type=int, default=64); parser.add_argument('--max-edges', type=int, default=1024)
    args = parser.parse_args()
    if args.read:
        report, _, proof = read_declared_graph(args.read)
        print(json.dumps(dict(counts=report['counts'], **proof)), flush=True)
    else:
        if not args.parent or not args.out: parser.error('--parent and --out required')
        report = build_declared_graph(args.parent, args.out, max_contexts=args.max_contexts, max_edges=args.max_edges)
        print(json.dumps(dict(status=report['status'], counts=report['counts'], seconds=report['seconds'])), flush=True)


if __name__ == '__main__': main()
