"""Keep selected caller contexts and constructor stages over shared bodies."""
import argparse
from collections import Counter, defaultdict
import gzip
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis.source_body_expansion import ExpansionParents, read_body_expansion
from scar.analysis.source_call_contexts import ContextReferenceEngine
from scar.analysis.source_constructor_interfaces import project_constructor_interfaces
from scar.analysis.source_field_interfaces import _InterfaceOnly
from scar.analysis.source_function_connections import Invocation, connect
from scar.analysis.source_reference_slice import source_port
from scar.analysis.source_world_returns import _table_ref
from scar.analysis.source_value_flow import _artifact
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_template_links import _json
from scar.ir.program import source_call_contexts as X, source_constructor_interfaces as C
from scar.ir.program import source_productions as P, source_reference_slices as S, reference_consumers as R
from scar.ir.program import declared_contexts as D, normal_targets as T
from scar.ir.record_codec import encode, decode


class CallContextParents:
    def __init__(self, path):
        started = time.monotonic(); self.root = Path(path).absolute()
        header = json.loads((self.root/'result.json').read_bytes())
        self.base = ExpansionParents(header['interfaces'])
        self.report, self.graph = read_body_expansion(self.root, parents=self.base)
        self.raw = (self.root/'result.json').read_bytes()
        if json.loads(self.raw) != self.report: raise ValueError('call context source body parent changed')
        self.artifact = _artifact(self.root/'result.json', self.report['schema'])
        self.bodies = (*self.base.values.bodies, *self.graph.bodies)
        consumer = Path(self.base.values.report['consumers'])
        self.consumer_report = json.loads((consumer/'result.json').read_bytes()); self.consumer = consumer
        if encode(_artifact(consumer/'result.json', 'scar.reference-consumer-graph')) != self.base.values.report['parent']:
            raise ValueError('call context original consumer parent differs')
        self.bindings = tuple(decode(R.SourceConsumerBinding, row, record_tags=P.PRODUCTION_RECORD_TAGS)
            for row in _table(consumer, self.consumer_report['tables']['bindings']))
        self.entries = tuple(decode(R.ConsumerBodyEntry, row, record_tags=P.PRODUCTION_RECORD_TAGS)
            for row in _table(consumer, self.consumer_report['tables']['entries']))
        self.validate(); self.certification_seconds = time.monotonic()-started

    def validate(self):
        from scar.analysis.source_body_expansion import _pins
        if self.raw != (self.root/'result.json').read_bytes() or self.report['pins'] != _pins():
            raise ValueError('call context certified body report or rules changed')
        for root, tables in ((self.root, self.report['tables']), (self.consumer, self.consumer_report['tables'])):
            for receipt in tables.values():
                raw = (root/receipt['path']).read_bytes()
                if len(raw) != receipt['bytes'] or sha256(raw).hexdigest() != receipt['sha256']:
                    raise ValueError('call context certified source table changed')
        self.base.validate()


def _function_connections(engine, queries, sites):
    result = []; mini_cache = {}
    for qi, (query, (identity, record)) in enumerate(zip(queries, sites)):
        caller = engine.slicer.unit(identity)[0]; call = record.call
        offset = engine.slicer.store.offsets[identity]
        invocation = Invocation(offset+call.callee, tuple(offset+p for p in call.positional),
            tuple((name, offset+p) for name, p in call.keywords), offset+call.result, offset+call.world,
            offset+call.result_world, None if call.positional_pack is None else offset+call.positional_pack,
            None if call.keyword_pack is None else offset+call.keyword_pack)
        for oi, origin in enumerate(query.reference.origins):
            if origin.kind is not S.ReferenceOriginKind.FUNCTION_DEFINITION: continue
            point = query.reference.states[origin.state].port
            provider, local = engine.slicer.local(point)
            fn = next(f for f in provider.functions if f.value == local)
            if point not in mini_cache: mini_cache[point] = _InterfaceOnly(engine.slicer, provider, fn)
            mini = mini_cache[point]
            connection = connect(mini, mini.offsets[provider.unit]+fn.value, invocation,
                conditions=('SELECTED_INCOMING_CALL_CONTEXT_AND_REFERENCE_ORIGIN_PATH',
                    'SOURCE_FUNCTION_CREATION_AND_DEFAULT_VERSION_MATCH_DECLARATION',
                    'PARENT_BODY_ENTRY_CONDITIONS_SELECTED_NOT_RUNTIME_ACTIVATION'))
            if connection is not None: result.append(X.ContextFunctionConnection(qi, oi, connection))
    return tuple(result)


def _declared_incoming(engine, binding):
    """Adapt the original declared edge without masquerading as a history row."""
    evidence = binding.interface
    if evidence.artifact.schema != 'scar.declared-context-edges':
        raise ValueError('incoming interface uses an unsupported original evidence schema')
    raw = Path(evidence.artifact.uri).read_bytes()
    if len(raw) != evidence.artifact.size_bytes or sha256(raw).hexdigest() != evidence.artifact.sha256:
        raise ValueError('declared incoming interface artifact changed')
    prefix = '#/records/'; tail = evidence.locator.removeprefix(prefix)
    if not evidence.locator.startswith(prefix) or not tail.isdecimal() or str(int(tail)) != tail:
        raise ValueError('declared incoming interface requires its original canonical record ordinal')
    rows = gzip.decompress(raw).splitlines(); ordinal = int(tail)
    if not 0 <= ordinal < len(rows): raise ValueError('declared incoming interface record is absent')
    edge = decode(D.DeclaredContextEdge, json.loads(rows[ordinal]), record_tags=P.PRODUCTION_RECORD_TAGS)
    unit = engine.slicer.unit(binding.state.actuals[0].unit)[0]
    call_ordinal = int(edge.call.locator.rsplit('/', 1)[1]); call = unit.calls[call_ordinal]
    if edge.call != engine.slicer.fact(unit, 'calls', call_ordinal):
        raise ValueError('declared incoming source call evidence belongs to a different unit')
    connection = edge.connection
    if (connection.source_callable != binding.source_callable or connection.body != binding.body
            or binding.argument not in connection.parameters or binding.state not in connection.parameters):
        raise ValueError('declared incoming body or original argument/state route differs')
    mode = 'SOURCE_CLASS_METHOD' if edge.descriptor.kind is D.DescriptorKind.CLASSMETHOD else (
        'SOURCE_BOUND_METHOD' if edge.descriptor.kind is D.DescriptorKind.FUNCTION
        and edge.receiver.kind is D.ClassValueKind.INSTANCE else 'SOURCE_FUNCTION')
    link = T.CallLink(source_port(unit, call.result), source_port(unit, call.callee),
        connection.source_callable, connection.body, mode, None, connection.parameters, connection.returns,
        tuple(dict.fromkeys((*connection.conditions, *edge.conditions))), argument_packs=connection.argument_packs,
        projections=connection.projections, binding=connection.binding)
    return engine.admit(evidence, link)


def derive_contexts(parents):
    snapshot = parents.base.values.snapshot; engine = ContextReferenceEngine(snapshot)
    inputs = []
    for ordinal, entry in enumerate(parents.entries):
        binding = parents.bindings[entry.binding]
        inputs.append((entry.body, binding, _table_ref(parents.consumer,
            parents.consumer_report['tables']['entries'], 'scar.consumer-body-entries', ordinal)))
    for ordinal, entry in enumerate(parents.graph.entries):
        binding = parents.base.graph.bindings[entry.binding]
        inputs.append((entry.body, binding, _table_ref(parents.root, parents.report['tables']['entries'],
            'scar.expanded-body-entries', ordinal)))
    units = {b.body.unit for b in parents.bodies}
    units.update(actual.unit for _, binding, _ in inputs for actual in binding.state.actuals)
    engine.index(units)
    grouped = {}; roots = []
    for body_index, binding, entry in inputs:
        if binding.interface not in engine.ids: _declared_incoming(engine, binding)
        incoming = engine.ids[binding.interface]; link = engine.interfaces[incoming].link
        body = parents.bodies[body_index]
        if link.source_callable != body.source_function or link.body != body.body:
            raise ValueError('call context incoming interface belongs to a different shared body')
        grouped.setdefault((body_index, incoming), []).append(entry)
    for (body, incoming), entries in grouped.items():
        roots.append(X.CallContextRoot(body, incoming, tuple(entries)))
    requested = []; metadata = []; sites = []
    for root_id, root in enumerate(roots):
        body = parents.bodies[root.body]; unit = engine.slicer.unit(body.body.unit)[0]
        for record in body.calls:
            point = source_port(unit, record.call.callee)
            requested.append((root.incoming, point)); metadata.append((root_id, root.incoming, record.fact, point))
            sites.append((body.body.unit, record))
    references = engine.solve(requested)
    queries = tuple(X.CallContextQuery(incoming, fact, point, reference, root)
        for (root, incoming, fact, point), reference in zip(metadata, references))
    assessments = []
    for qi, (query, (identity, record)) in enumerate(zip(queries, sites)):
        known = {query.reference.states[o.state].port for o in query.reference.origins
            if o.kind in (S.ReferenceOriginKind.FUNCTION_DEFINITION, S.ReferenceOriginKind.CLASS_DEFINITION)}
        result = source_port(engine.slicer.unit(identity)[0], record.call.result)
        for candidate in engine.by_result.get(result, ()):
            link = engine.interfaces[candidate].link
            if link.callee != query.callee: continue
            relation = 'ORIGIN_MATCH_UNDER_PATH_CONDITIONS' if link.source_callable in known else (
                'CONTEXT_OPEN' if query.reference.frontiers else 'NOT_IN_CLOSED_SOURCE_ORIGINS')
            assessments.append(X.ContextTargetEvidence(qi, candidate, relation))
    functions = _function_connections(engine, queries, sites)
    # Constructor protocols cover every distinct original body call, including
    # those not selected as a callee query in a particular incoming context.
    unique = {}; constructor_sites = []
    for body in parents.bodies:
        for record in body.calls:
            key = body.body.unit, record.fact
            if key not in unique:
                unique[key] = True; constructor_sites.append((body.body.unit, record))
    constructors = project_constructor_interfaces(snapshot, tuple(constructor_sites))
    parents.validate()
    return dict(interfaces=tuple(engine.interfaces), roots=tuple(roots), queries=queries,
        assessments=tuple(assessments), functions=functions,
        constructor_sites=constructors.sites, constructor_steps=constructors.steps,
        constructor_entries=constructors.entries, constructor_frontiers=constructors.frontiers)


CLASSES = dict(interfaces=X.CallInterfaceRecord, roots=X.CallContextRoot, queries=X.CallContextQuery,
    assessments=X.ContextTargetEvidence, functions=X.ContextFunctionConnection,
    constructor_sites=C.ConstructorInterfaceSite, constructor_steps=C.ConstructorInterfaceStep,
    constructor_entries=C.ConstructorBodyEntry, constructor_frontiers=C.ConstructorInterfaceFrontier)


def _counts(graph):
    return dict(interfaces=len(graph['interfaces']), roots=len(graph['roots']), queries=len(graph['queries']),
        reference_states=sum(len(q.reference.states) for q in graph['queries']),
        reference_edges=sum(len(q.reference.edges) for q in graph['queries']),
        reference_origins=sum(len(q.reference.origins) for q in graph['queries']),
        context_frontiers=sum(len(q.reference.frontiers) for q in graph['queries']),
        frontier_reasons=dict(Counter(f.reason for q in graph['queries'] for f in q.reference.frontiers)),
        assessments=dict(Counter(a.relation for a in graph['assessments'])),
        source_function_connections=len(graph['functions']),
        constructor_sites=len(graph['constructor_sites']), constructor_steps=len(graph['constructor_steps']),
        constructor_entries=len(graph['constructor_entries']), constructor_frontiers=len(graph['constructor_frontiers']),
        constructor_stages=dict(Counter(s.link.stage.value for s in graph['constructor_steps'])))


def _pins():
    from scar.analysis import source_call_contexts, source_constructor_interfaces, source_function_connections
    return {name: sha256(Path(path).read_bytes()).hexdigest() for name, path in (
        ('producer', __file__), ('types', X.__file__), ('constructor_types', C.__file__),
        ('declared_types', D.__file__),
        ('contexts', source_call_contexts.__file__), ('constructors', source_constructor_interfaces.__file__),
        ('function_connections', source_function_connections.__file__))}


def _parent(path, parents):
    parents = parents if parents is not None else CallContextParents(path)
    if parents.root != Path(path).absolute(): raise ValueError('call context parent path differs')
    parents.validate(); return parents


def build_call_context_graph(path, out, *, parents=None):
    started = time.monotonic(); pins = _pins(); out = Path(out).absolute()
    if out.exists(): raise ValueError('fresh call context output required')
    parents = _parent(path, parents); graph = derive_contexts(parents)
    if pins != _pins(): raise ValueError('call context rules changed')
    _durable_mkdir(out)
    tables = {name: write_table(out/(name+'.jsonl.gz'), rows) for name, rows in graph.items()}
    report = dict(schema='scar.source-call-context-graph', schema_version=1,
        status='SELECTED_SOURCE_CALL_CONTEXTS_AND_CONSTRUCTOR_INTERFACES', body_expansion=str(parents.root),
        parent=encode(parents.artifact), tables=tables, pins=pins, counts=_counts(graph),
        all_historical_candidates_retained=True, runtime_dispatch_proven=False,
        content_versions_proven=False, target_executed=False, first_stage_complete=False,
        seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json', _json(report), replace=False); return report


def read_call_context_graph(path, *, parents=None):
    path = Path(path).absolute(); raw = (path/'result.json').read_bytes(); report = json.loads(raw)
    if (report['schema'], report['schema_version']) != ('scar.source-call-context-graph', 1) or report['pins'] != _pins():
        raise ValueError('call context producer differs')
    parents = _parent(report['body_expansion'], parents)
    if report['parent'] != encode(parents.artifact): raise ValueError('call context original parent differs')
    graph = {name: tuple(decode(cls, row, record_tags=P.PRODUCTION_RECORD_TAGS)
        for row in _table(path, report['tables'][name])) for name, cls in CLASSES.items()}
    if graph != derive_contexts(parents) or _counts(graph) != report['counts']:
        raise ValueError('selected caller references or constructor interfaces differ from original evidence')
    if (report['all_historical_candidates_retained'] is not True or any(report[k] is not False for k in (
            'runtime_dispatch_proven', 'content_versions_proven', 'target_executed', 'first_stage_complete'))):
        raise ValueError('call contexts cannot prove runtime dispatch or state contents')
    parents.validate()
    if (path/'result.json').read_bytes() != raw: raise ValueError('call context graph changed during verification')
    return report, graph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bodies'); parser.add_argument('--out'); parser.add_argument('--read')
    args = parser.parse_args()
    if args.read: report, _ = read_call_context_graph(args.read)
    else:
        if not args.bodies or not args.out: parser.error('--bodies and --out required')
        report = build_call_context_graph(args.bodies, args.out)
    print(json.dumps(dict(status=report['status'], counts=report['counts'], seconds=report['seconds'])), flush=True)


if __name__ == '__main__': main()
