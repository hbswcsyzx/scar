"""Store ordered source base operands and conditional namespace provenance.

Class roots are analysis queries into a retained source catalog. Selecting a
query never establishes program entry, a live class object or runtime MRO.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import time
from types import SimpleNamespace

from scar.analysis.source_class_bases import project_class_bases
from scar.analysis.source_context_query import ContextTargetGraph
from scar.analysis.source_reference_slice import source_port
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_value_flow import _artifact
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import source_class_bases as B, source_constructor_contexts as C, source_productions as P
from scar.ir.program import normal_targets as T
from scar.ir.record_codec import encode, decode


def _catalog(path):
    catalog = ContextTargetGraph(path)
    def validate():
        if _artifact(catalog.path/'result.json', catalog.report['schema']) != artifact:
            raise ValueError('class base catalog changed')
        catalog.fact_store.validate_parents(); catalog.interface_store.validate_parents()
    artifact = _artifact(catalog.path/'result.json', catalog.report['schema'])
    return catalog, SimpleNamespace(fact_store=catalog.fact_store, validate_parents=validate), artifact


def _pins():
    from scar.analysis import source_class_bases, source_namespace_references, source_address_paths
    from scar.ir.program import source_namespace_references as N
    return {name: sha256(Path(path).read_bytes()).hexdigest() for name, path in (
        ('producer', __file__), ('bases', source_class_bases.__file__), ('types', B.__file__),
        ('namespaces', source_namespace_references.__file__), ('namespace_types', N.__file__),
        ('addresses', source_address_paths.__file__))}


def _counts(graph):
    namespaces = [slot.namespace for slot in graph.slots if slot.namespace is not None]
    return dict(declarations=len(graph.declarations), slots=len(graph.slots),
        packed_declarations=sum(d.bases_pack is not None for d in graph.declarations),
        no_explicit_bases=sum(d.no_explicit_bases for d in graph.declarations),
        slots_with_class_candidates=sum(bool(s.source_classes) for s in graph.slots),
        class_candidates=sum(len(s.source_classes) for s in graph.slots),
        namespace_states=sum(len(g.states) for g in namespaces), namespace_edges=sum(len(g.edges) for g in namespaces),
        namespace_origins=dict(Counter(o.kind.value for g in namespaces for o in g.origins)),
        frontiers=len(graph.frontiers), frontier_reasons=dict(Counter(f.reason for f in graph.frontiers)))


def build_class_base_graph(catalog, source_classes, out):
    started=time.monotonic(); pins=_pins(); out=Path(out).absolute()
    if out.exists(): raise ValueError('fresh class base output required')
    catalog, snapshot, parent=_catalog(catalog)
    graph=project_class_bases(snapshot, source_classes); snapshot.validate_parents()
    if pins!=_pins(): raise ValueError('class base rules changed')
    _durable_mkdir(out)
    tables={name:write_table(out/(name+'.jsonl.gz'),getattr(graph,name)) for name in ('declarations','slots','frontiers')}
    report=dict(schema='scar.source-class-base-graph',schema_version=1,status='ORDERED_BASE_OPERANDS_AND_NAMESPACE_SOURCES',
        catalog=str(catalog.path),parent=encode(parent),pins=pins,tables=tables,
        source_classes=[encode(d.source_class) for d in graph.declarations],counts=_counts(graph),
        roots_are_query_selection_not_entry_admission=True,current_namespace_versions_proven=False,
        runtime_bases_proven=False,mro_proven=False,target_executed=False,first_stage_complete=False,
        seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json',_json(report),replace=False);return report


def read_class_base_graph(path):
    path=Path(path).absolute();raw=(path/'result.json').read_bytes();report=json.loads(raw)
    if (report['schema'],report['schema_version'])!=('scar.source-class-base-graph',1) or report['pins']!=_pins():
        raise ValueError('class base producer differs')
    _,snapshot,parent=_catalog(report['catalog'])
    if report['parent']!=encode(parent):raise ValueError('class base original catalog differs')
    graph=B.ClassBaseGraph(**{name:tuple(decode(cls,row,record_tags=P.PRODUCTION_RECORD_TAGS)
        for row in _table(path,report['tables'][name])) for name,cls in
        (('declarations',B.ClassBaseDeclaration),('slots',B.ClassBaseSlot),('frontiers',B.ClassBaseFrontier))})
    roots=tuple(decode(T.GlobalPort,row) for row in report['source_classes'])
    if graph!=project_class_bases(snapshot,roots) or _counts(graph)!=report['counts']:
        raise ValueError('class operands or namespace reference sources differ from original facts')
    if (report['roots_are_query_selection_not_entry_admission'] is not True or any(report[k] is not False for k in (
            'current_namespace_versions_proven','runtime_bases_proven','mro_proven','target_executed','first_stage_complete'))):
        raise ValueError('class base source queries cannot prove runtime identity or inheritance')
    snapshot.validate_parents()
    if raw!=(path/'result.json').read_bytes():raise ValueError('class base graph changed during verification')
    return report,graph


def query_classes_from_inputs(path):
    """Read query roots, without treating their selection as entry evidence."""
    path=Path(path).absolute();raw=(path/'result.json').read_bytes();report=json.loads(raw)
    if report['schema']=='scar.constructor-class-input-projection':name='roots'
    elif report['schema']=='scar.constructor-member-contexts':name='class_roots'
    else:raise ValueError('expected constructor class input query selection')
    roots=tuple(decode(C.ConstructorClassInputRoot,row,record_tags=P.PRODUCTION_RECORD_TAGS)
        for row in _table(path,report['tables'][name]))
    if raw!=(path/'result.json').read_bytes():raise ValueError('class query selection changed')
    return tuple(dict.fromkeys(value.source_class for root in roots for value in root.context.class_inputs))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog');parser.add_argument('--inputs');parser.add_argument('--out');parser.add_argument('--read')
    parser.add_argument('--class-value',nargs=2,action='append',metavar=('UNIT','LOCAL_PORT'),default=[])
    args=parser.parse_args()
    if args.read:report,_=read_class_base_graph(args.read)
    else:
        if not args.catalog or not args.out:parser.error('--catalog and --out required')
        roots=list(query_classes_from_inputs(args.inputs)) if args.inputs else []
        if args.class_value:
            catalog=ContextTargetGraph(args.catalog)
            roots.extend(source_port(catalog.fact_store.load(unit),int(local)) for unit,local in args.class_value)
        if not roots:parser.error('--inputs or --class-value required')
        report=build_class_base_graph(args.catalog,roots,args.out)
    print(json.dumps(dict(status=report['status'],counts=report['counts'],seconds=report['seconds'])),flush=True)


if __name__=='__main__':main()
