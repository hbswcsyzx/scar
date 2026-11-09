"""Project source value/operation dependencies from shared F4 function bodies.

No target imports, target execution, tensor reads or optimization. Data edges
transport references/values; primitive operations remain distinct hypernodes.
The optional reach query is an overapproximation, not an executable path proof.
"""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import time
from types import SimpleNamespace

from scar.analysis.normal_graph import normal_edges, _Emitter
from scar.analysis.normal_output import write_table
from scar.analysis.source_context_query import ContextTargetGraph
from scar.analysis.source_reference_consumers import read_reference_consumers, argument_points
from scar.analysis.source_reference_slice import ReferenceSlicer, source_port
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_template_links import _json
from scar.analysis.source_world_flow import STRUCTURAL, _walk, _state
from scar.analysis.source_world_material import WorldMaterial
from scar.ir.program import source_value_flow as V, source_productions as P
from scar.ir.program import normal_graph as G, normal_links as F, normal_targets as T
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import encode, decode


def project_value_flow(material, source_function, body):
    """Keep original body operations, scoped locations and shared control."""
    plans = material.closure(body.template)
    edges = []; operations = []
    for key, plan in plans.items():
        emitter = _Emitter(plan, key, material.interfaces)
        edges.extend(normal_edges(plan, material.interfaces))
        for step in plan.steps:
            if isinstance(step.instruction, STRUCTURAL):
                continue
            inputs = tuple(V.TypedValuePort(emitter.port(step.id, G.PortKind.ARGUMENT, i),
                emitter.value(value)[1]) for i, value in enumerate(step.arguments))
            outputs = tuple(V.TypedValuePort(emitter.port(step.id, G.PortKind.RESULT, i, completion), kind)
                for completion in step.completions if emitter.allowed(completion, step.region)
                for i, kind in enumerate(completion.types))
            operations.append(V.SourceOperation(emitter.port(step.id, G.PortKind.ENTER),
                step.instruction, inputs, outputs))
    control = defaultdict(list)
    for e in edges:
        if e.kind is G.EdgeKind.CONTROL: control[e.source].append(e.target)
    reachable = _walk(G.Port(body.template, body.region, G.PortKind.ENTER), control)
    owners = {(p.template, p.owner) for p in reachable}
    inside = lambda p: (p.template, p.owner) in owners
    # DECLARE edges remain expansion links. They do not enter deferred bodies.
    edges = tuple(e for e in edges if inside(e.source) and
        (inside(e.target) or e.kind is G.EdgeKind.DECLARE))
    operations = tuple(o for o in operations if inside(o.entry))
    unit = material.fact_store.load(material.unit)
    fn = next(f for f in unit.functions if source_port(unit, f.value) == source_function)
    if T.Body(unit.unit, fn.template, fn.body) != body:
        raise ValueError('value-flow function body differs from original declaration')
    slicer = ReferenceSlicer(SimpleNamespace(fact_store=material.fact_store))
    locations = {}; calls = []; boundaries = []
    for group in unit.scope_groups:
        if group.owner != fn.body_scope.owner: continue
        for span in group.tables:
            if span.table is F.FactTable.NAMES:
                for i in range(span.start, span.stop):
                    access = unit.names[i]; point = source_port(unit, access.value).port
                    if not inside(point): continue
                    location_access = V.LocationAccess(point, slicer.fact(unit, 'names', i))
                    if access.namespace.kind is not F.NamespaceKind.LEXICAL:
                        boundaries.append(V.NameBoundary(group.owner, access.namespace, location_access,
                            access.write, 'NON_LEXICAL_NAMESPACE_CONTENT_NOT_JOINED'))
                        continue
                    writes, reads = locations.setdefault(access.namespace, ([], []))
                    (writes if access.write else reads).append(location_access)
            elif span.table is F.FactTable.CALLS:
                for i in range(span.start, span.stop):
                    call = unit.calls[i]
                    if inside(source_port(unit, call.result).port):
                        calls.append(V.SourceBodyCall(slicer.fact(unit, 'calls', i), call))
    locations = tuple(V.LexicalLocation(fn.body_scope.owner, namespace, tuple(writes), tuple(reads))
        for namespace, (writes, reads) in locations.items())
    for location in locations:
        if not location.writes:
            boundaries.extend(V.NameBoundary(location.scope, location.namespace, access, False,
                'CAPTURE_OR_LEXICAL_PRODUCER_OUTSIDE_THIS_BODY') for access in location.reads)
    material.validate_parents()
    return V.SourceBodyValueFlow(source_function, body, material.result_artifact,
        edges, operations, locations, tuple(calls), tuple(boundaries))


def data_reach(flow, formal, entry, body_index, unit):
    """Linear sparse may-dependency closure; state is kept but never tainted.

    Locations and operations are worklist vertices, so no input/output or
    writer/reader cross product is allocated. This is intentionally weaker
    than a balanced, branch-sensitive path or a state-version proof.
    """
    if formal.unit != flow.body.unit or unit.unit != formal.unit:
        raise ValueError('value-flow query formal belongs to a different source unit')
    adjacency = defaultdict(list)
    for edge in flow.edges:
        if edge.kind is G.EdgeKind.DATA: adjacency[edge.source].append(edge.target)
    for i, op in enumerate(flow.operations):
        node = ('operation', i)
        for value in op.inputs:
            if not _state(value.value_type): adjacency[value.port].append(node)
        for value in op.outputs:
            if not _state(value.value_type): adjacency[node].append(value.port)
    for i, location in enumerate(flow.locations):
        node = ('location', i)
        for access in location.writes: adjacency[access.value].append(node)
        for access in location.reads: adjacency[node].append(access.value)
    reached = _walk(formal.port, adjacency)
    calls = []
    for record in flow.calls:
        for role, ordinal, keyword, actual in argument_points(record.call):
            port = source_port(unit, actual)
            if port.port in reached:
                calls.append(V.DependentCallInput(record.fact, role.value, ordinal, keyword, port))
    return V.SourceDataReach(entry, body_index, formal,
        sum(type(p) is G.Port for p in reached),
        tuple(i for i in range(len(flow.operations)) if ('operation', i) in reached), tuple(calls))


def _artifact(path, schema):
    path = Path(path).absolute(); raw = path.read_bytes()
    return ProviderArtifact(str(path), sha256(raw).hexdigest(), len(raw), schema)


def _source_catalog(root, report):
    """Follow exact ancestor links already certified by the consumer reader."""
    records = {Path(root)/'result.json': (Path(root)/'result.json').read_bytes()}
    def parent(folder, reference, schema):
        path = Path(folder).absolute()/'result.json'; raw = path.read_bytes()
        if encode(_artifact(path, schema)) != reference: raise ValueError('value-flow ancestor receipt differs')
        records[path] = raw
        return json.loads(raw)
    returns = parent(report['returns'], report['parent'], 'scar.world-return-graph')
    world = parent(returns['world'], returns['parent'], 'scar.source-world-flow')
    join = parent(world['join'], world['parent'], 'scar.declared-state-connections')
    declared = parent(join['contexts'], join['parents']['contexts'], 'scar.declared-context-graph')
    fields = parent(declared['parent'], declared['parent_ref'], 'scar.source-field-interface-graph')
    catalog_path = Path(fields['catalog']).absolute()
    expected = decode(ProviderArtifact, fields['catalog_parent'])
    if _artifact(catalog_path/'result.json', expected.schema) != expected:
        raise ValueError('value-flow catalog differs from certified source parent')
    records[catalog_path/'result.json'] = (catalog_path/'result.json').read_bytes()
    catalog = ContextTargetGraph(catalog_path)
    def validate():
        if any(path.read_bytes() != raw for path, raw in records.items()):
            raise ValueError('value-flow parent changed during projection')
        catalog.fact_store.validate_parents()
    validate()
    return catalog, validate


def _derive(consumers, timings=None):
    started = time.monotonic()
    report, graph = read_reference_consumers(consumers)
    if timings is not None: timings['certified_parent_seconds'] = time.monotonic()-started
    started = time.monotonic()
    catalog, validate = _source_catalog(consumers, report)
    if timings is not None: timings['source_catalog_seconds'] = time.monotonic()-started
    started = time.monotonic()
    materials = {}; bodies = []
    for body in graph.bodies:
        unit = body.source_function.unit
        if unit not in materials: materials[unit] = WorldMaterial(catalog, unit)
        bodies.append(project_value_flow(materials[unit], body.source_function, body.flow.caller_body))
    if timings is not None: timings['body_projection_seconds'] = time.monotonic()-started
    started = time.monotonic()
    reaches = tuple(data_reach(bodies[e.body], e.formal, i, e.body,
        catalog.fact_store.load(e.formal.unit)) for i, e in enumerate(graph.entries))
    validate()
    if timings is not None: timings['data_queries_seconds'] = time.monotonic()-started
    return tuple(bodies), reaches


def _pins():
    from scar.analysis import normal_graph, source_world_material, source_reference_consumers, source_world_flow
    return {name: sha256(Path(path).read_bytes()).hexdigest() for name, path in (
        ('producer', __file__), ('types', V.__file__), ('emitter', normal_graph.__file__),
        ('materials', source_world_material.__file__), ('consumers', source_reference_consumers.__file__),
        ('world_rules', source_world_flow.__file__))}


def _counts(bodies, reaches):
    return dict(shared_bodies=len(bodies), edges=sum(len(b.edges) for b in bodies),
        edge_kinds=dict(Counter(e.kind.value for b in bodies for e in b.edges)),
        operations=sum(len(b.operations) for b in bodies),
        lexical_locations=sum(len(b.locations) for b in bodies),
        location_accesses=sum(len(l.writes)+len(l.reads) for b in bodies for l in b.locations),
        name_boundaries=sum(len(b.name_boundaries) for b in bodies),
        calls=sum(len(b.calls) for b in bodies), entries=len(reaches),
        dependent_call_inputs=sum(len(r.call_inputs) for r in reaches),
        backedges=sum(e.transition is G.Transition.BACKEDGE for b in bodies for e in b.edges))


def build_value_flow(consumers, out):
    started = time.monotonic(); out = Path(out).absolute(); consumers = Path(consumers).absolute(); pins = _pins()
    if out.exists(): raise ValueError('fresh value-flow output required')
    parent = _artifact(consumers/'result.json', 'scar.reference-consumer-graph')
    timings = {}; bodies, reaches = _derive(consumers, timings)
    if pins != _pins() or parent != _artifact(consumers/'result.json', parent.schema):
        raise ValueError('value-flow rules or parent changed')
    _durable_mkdir(out)
    tables = {name: write_table(out/(name+'.jsonl.gz'), rows)
        for name, rows in (('bodies', bodies), ('reaches', reaches))}
    report = dict(schema='scar.source-value-flow', schema_version=1, status='SOURCE_OPERATION_VALUE_DEPENDENCIES',
        consumers=str(consumers), parent=encode(parent), pins=pins, tables=tables, counts=_counts(bodies, reaches),
        loops_unrolled=False, alias_or_content_identity_proven=False, target_executed=False,
        first_stage_complete=False, seconds=time.monotonic()-started, timings=timings)
    _durable_bytes(out/'result.json', _json(report), replace=False)
    return report


def read_value_flow(path):
    path = Path(path).absolute(); raw = (path/'result.json').read_bytes(); report = json.loads(raw)
    if (report['schema'], report['schema_version']) != ('scar.source-value-flow', 1) or report['pins'] != _pins():
        raise ValueError('value-flow producer differs')
    if report['parent'] != encode(_artifact(Path(report['consumers'])/'result.json', 'scar.reference-consumer-graph')):
        raise ValueError('value-flow parent differs')
    records = tuple(tuple(decode(cls, row, record_tags=P.PRODUCTION_RECORD_TAGS)
        for row in _table(path, report['tables'][name])) for name, cls in
        (('bodies', V.SourceBodyValueFlow), ('reaches', V.SourceDataReach)))
    if records != _derive(report['consumers']) or _counts(*records) != report['counts']:
        raise ValueError('value-flow operations, locations or dependencies differ from source')
    if any(report[k] is not False for k in ('loops_unrolled', 'alias_or_content_identity_proven',
            'target_executed', 'first_stage_complete')):
        raise ValueError('source dependencies cannot prove content identity or completion')
    if raw != (path/'result.json').read_bytes(): raise ValueError('value-flow graph changed during verification')
    return report, records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--consumers'); parser.add_argument('--out'); parser.add_argument('--read')
    args = parser.parse_args()
    if args.read: report, _ = read_value_flow(args.read)
    else:
        if not args.consumers or not args.out: parser.error('--consumers and --out required')
        report = build_value_flow(args.consumers, args.out)
    print(json.dumps(dict(status=report['status'], counts=report['counts'], seconds=report['seconds'])), flush=True)


if __name__ == '__main__': main()
