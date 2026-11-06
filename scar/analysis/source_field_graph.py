"""Publish and verify conditional field/method subgraphs over original ports."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis import source_reference_slice, source_relation_snapshot, source_field_interfaces
from scar.analysis.source_reference_slice import ReferenceSlicer, FIELD_CONDITIONS
from scar.analysis.source_relation_snapshot import RelationSnapshot
from scar.analysis.source_field_interfaces import discover_field_calls, infer_field_method, _InterfaceOnly
from scar.analysis.source_function_connections import Invocation, connect
from scar.analysis.source_reference_slice import source_port as _gp
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.analysis.normal_output import write_table
from scar.analysis.source_symbol_variants import _table
from scar.ir.program import source_reference_slices as R, normal_targets as T, normal_links as F
from scar.ir.program import source_productions as P
from scar.ir.record_codec import encode, decode


def _pins():
    return {name: sha256(Path(path).read_bytes()).hexdigest() for name, path in {
        'publisher': __file__, 'types': R.__file__, 'slice': source_reference_slice.__file__,
        'snapshot': source_relation_snapshot.__file__, 'interfaces': source_field_interfaces.__file__}.items()}


def _counts(queries):
    slices = [s for q in queries for s in q.slices]
    return dict(queries=len(queries), slices=len(slices), states=sum(len(s.states) for s in slices),
        transitions=sum(len(s.transitions) for s in slices), origins=sum(len(s.origins) for s in slices),
        reference_frontiers=sum(len(s.frontiers) for s in slices),
        field_flows=sum(len(q.flows) for q in queries), method_interfaces=sum(len(q.methods) for q in queries))


def build_field_graph(relations, catalog, identity, out, *, calls=(), write_units=(), max_states=20_000,
        max_call_depth=32):
    started = time.monotonic(); initial = _pins(); out = Path(out).absolute()
    if out.exists():
        raise ValueError('fresh field graph output required')
    snapshot = RelationSnapshot(relations, catalog); slicer = ReferenceSlicer(snapshot)
    unit, *_ = slicer.unit(identity)
    patterns = tuple(p for p in discover_field_calls(unit) if not calls or p[0] in calls)
    queries = []
    for call, method, field in patterns:
        slices, flows, methods, domain, obligations = infer_field_method(slicer, identity, call, method, field,
            write_units=write_units, max_states=max_states, max_call_depth=max_call_depth)
        queries.append(R.FieldInterfaceQuery(identity, call, method, field, slices, flows, methods, domain, obligations))
    snapshot.validate_parents()
    if _pins() != initial:
        raise ValueError('field graph rules changed during construction')
    _durable_mkdir(out); descriptors = []
    for query in queries:
        folder = out/'units'/query.unit; folder.mkdir(parents=True, exist_ok=True)
        name = f'call-{query.call_ordinal}-{query.method_attribute_ordinal}-{query.field_attribute_ordinal}.jsonl.gz'
        receipt = write_table(folder/name, (query,))
        descriptors.append(dict(unit=query.unit, call=query.call_ordinal, method=query.method_attribute_ordinal,
            field=query.field_attribute_ordinal, folder=str(folder.relative_to(out)), table=receipt))
    report = dict(schema='scar.source-field-interface-graph', schema_version=1,
        status='CONDITIONAL_DECLARED_FIELD_AND_METHOD_GRAPH', pins=initial,
        relations=str(snapshot.path), catalog=str(snapshot.catalog.path),
        relation_parent=encode(snapshot.result_artifact), catalog_parent=encode(snapshot.catalog_artifact),
        historical_producer_sha256=snapshot.historical_producer_sha256,
        historical_status=snapshot.report['status'], historical_event_budget=snapshot.report['event_budget'],
        unit=identity, call_selection=list(calls), explicit_writer_units=list(write_units),
        limits=dict(max_states=max_states, max_call_depth=max_call_depth), shards=descriptors, counts=_counts(queries),
        writer_domain_complete=False, entry_admission_proven=False, current_field_versions_proven=False,
        runtime_dispatch_verified=False, transformation_authorized=False, target_executed=False,
        first_stage_complete=False, seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json', _json(report), replace=False)
    return report


def _index(items, ordinal):
    if type(ordinal) is not int or not 0 <= ordinal < len(items):
        raise ValueError('field graph reference is outside its original local table')
    return items[ordinal]


def _verify_query(slicer, query):
    unit, *_ = slicer.unit(query.unit)
    pattern = (query.call_ordinal, query.method_attribute_ordinal, query.field_attribute_ordinal)
    if pattern not in discover_field_calls(unit):
        raise ValueError('field method structure no longer matches original aliases and operations')
    read_site = slicer.attribute_site(unit, query.field_attribute_ordinal)
    for flow in query.flows:
        wu, *_ = slicer.unit(flow.write_site.receiver.unit)
        ordinal = int(flow.write.locator.rsplit('/', 1)[1])
        write = _index(wu.attributes, ordinal)
        if (write.action is not F.AttributeAction.SET or write.name != read_site.member
                or flow.write != slicer.fact(wu, 'attributes', ordinal)
                or flow.read != slicer.fact(unit, 'attributes', query.field_attribute_ordinal)
                or flow.write_site != slicer.attribute_site(wu, ordinal) or flow.read_site != read_site):
            raise ValueError('field flow crossed an original read/write operation or world')
        ws = _index(query.slices, flow.write_slice); rs = _index(query.slices, flow.read_slice)
        wo = _index(ws.origins, flow.write_origin); ro = _index(rs.origins, flow.read_origin)
        if (ws.states[0].port != flow.write_site.receiver or rs.states[0].port != read_site.receiver
                or wo.kind is not R.ReferenceOriginKind.ALLOCATION_SITE_CANDIDATE
                or ro.kind is not R.ReferenceOriginKind.ALLOCATION_SITE_CANDIDATE
                or ws.states[wo.state].port != rs.states[ro.state].port
                or ws.states[wo.state].port != flow.shared_allocation_candidate
                or wo.source_class != ro.source_class or wo.source_class != flow.receiver_class
                or not set((*FIELD_CONDITIONS, *wo.conditions, *ro.conditions)) <= set(flow.conditions)):
            raise ValueError('field flow lost its allocation candidates or conditional identity guards')
    method = unit.attributes[query.method_attribute_ordinal]; call = unit.calls[query.call_ordinal]
    for item in query.methods:
        flow = _index(query.flows, item.field_flow)
        vs = _index(query.slices, item.value_slice); vo = _index(vs.origins, item.value_origin)
        ms = _index(query.slices, item.member_slice); mo = _index(ms.origins, item.member_origin)
        if (item.call != slicer.fact(unit, 'calls', query.call_ordinal)
                or item.attribute != slicer.fact(unit, 'attributes', query.method_attribute_ordinal)
                or vs.states[0].port != flow.write_site.assigned
                or vo.kind is not R.ReferenceOriginKind.ALLOCATION_SITE_CANDIDATE
                or vo.source_class != item.source_class or mo.kind is not R.ReferenceOriginKind.FUNCTION_DEFINITION
                or ms.states[mo.state].port != item.connection.source_callable):
            raise ValueError('method interface lost its field content or source function origin')
        owner, local = slicer.local(item.source_class)
        cls = next(c for c in owner.classes if c.value == local)
        binding_index = int(item.class_binding.locator.rsplit('/', 1)[1])
        binding = _index(owner.names, binding_index)
        if (item.class_binding != slicer.fact(owner, 'names', binding_index) or not binding.write
                or binding.namespace != F.Namespace(F.NamespaceKind.CLASS, cls.scope, method.name)
                or ms.states[0].port != _gp(owner, binding.value)):
            raise ValueError('method declaration crossed its CLASS binding or source version')
        provider, local = slicer.local(item.connection.source_callable)
        fn = next(f for f in provider.functions if f.value == local)
        mini = _InterfaceOnly(slicer, provider, fn); offset = mini.offsets[unit.unit]
        invocation = Invocation(offset+call.callee, tuple(offset+p for p in call.positional),
            tuple((name, offset+p) for name, p in call.keywords), offset+call.result,
            offset+call.world, offset+call.result_world,
            None if call.positional_pack is None else offset+call.positional_pack,
            None if call.keyword_pack is None else offset+call.keyword_pack)
        required = (*flow.conditions, *vo.conditions, *mo.conditions,
            'ASSIGNED_REFERENCE_IS_SELECTED_FIELD_CONTENT', 'SOURCE_CLASS_NAMESPACE_SELECTS_DECLARED_MEMBER',
            'STANDARD_PYTHON_FUNCTION_INSTANCE_DESCRIPTOR_SELECTED', 'DECLARED_REFERENCE_AND_CREATION_CONTEXT_GUARDS_HOLD')
        if (not set(required) <= set(item.conditions)
                or connect(mini, mini.offsets[provider.unit]+fn.value, invocation,
                    offset+method.receiver, conditions=item.conditions) != item.connection):
            raise ValueError('declared method interface differs from its original source call ABI')
    if not {'FIELD_WRITER_SEARCH_DOMAIN_OPEN', 'FIELD_CONTENT_VERSION_AND_DISPATCH_NOT_PROVEN'} <= set(query.obligations):
        raise ValueError('field slice cannot close external writers or current versions')


def read_field_graph(path):
    from scar.analysis.source_reference_verify import verify_reference_slices
    started = time.monotonic(); path = Path(path).absolute(); raw = (path/'result.json').read_bytes()
    report = json.loads(raw)
    if ((report['schema'], report['schema_version']) != ('scar.source-field-interface-graph', 1) or report['pins'] != _pins()):
        raise ValueError('field graph version or producer differs')
    snapshot = RelationSnapshot(report['relations'], report['catalog'])
    if encode(snapshot.result_artifact) != report['relation_parent'] or encode(snapshot.catalog_artifact) != report['catalog_parent']:
        raise ValueError('field graph source parents differ')
    slicer = ReferenceSlicer(snapshot); queries = []
    for shard in report['shards']:
        values = _table(path/shard['folder'], shard['table'])
        if len(values) != 1:
            raise ValueError('one source query per shard required')
        query = decode(R.FieldInterfaceQuery, values[0], record_tags=P.PRODUCTION_RECORD_TAGS)
        if (query.unit, query.call_ordinal, query.method_attribute_ordinal, query.field_attribute_ordinal) != (
                shard['unit'], shard['call'], shard['method'], shard['field']):
            raise ValueError('field shard selects another source query')
        queries.append(query)
    queries = tuple(queries)
    if _counts(queries) != report['counts']:
        raise ValueError('field graph counts differ')
    proof = verify_reference_slices(snapshot, tuple(s for q in queries for s in q.slices))
    for query in queries:
        _verify_query(slicer, query)
    for name in ('writer_domain_complete', 'entry_admission_proven', 'current_field_versions_proven',
            'runtime_dispatch_verified', 'transformation_authorized', 'target_executed', 'first_stage_complete'):
        if report[name] is not False:
            raise ValueError('conditional field interfaces cannot grant execution or transformation authority')
    snapshot.validate_parents()
    if (path/'result.json').read_bytes() != raw:
        raise ValueError('field graph report changed during validation')
    return report, queries, dict(proof, verification_seconds=time.monotonic()-started)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--read')
    for name in ('relations', 'catalog', 'unit', 'out'):
        parser.add_argument('--'+name)
    parser.add_argument('--call', type=int, action='append', default=[])
    parser.add_argument('--write-unit', action='append', default=[])
    parser.add_argument('--max-states', type=int, default=20_000)
    parser.add_argument('--max-call-depth', type=int, default=32)
    args = parser.parse_args()
    if args.read:
        report, _, proof = read_field_graph(args.read)
        print(json.dumps(dict(counts=report['counts'], **proof)), flush=True)
    else:
        if not all((args.relations, args.catalog, args.unit, args.out)):
            parser.error('--relations --catalog --unit --out are required for construction')
        report = build_field_graph(args.relations, args.catalog, args.unit, args.out, calls=args.call,
            write_units=args.write_unit, max_states=args.max_states, max_call_depth=args.max_call_depth)
        print(json.dumps(dict(status=report['status'], counts=report['counts'], seconds=report['seconds'])), flush=True)


if __name__ == '__main__':
    main()
