"""Join exec namespace handles, ordered source accesses and captured globals.

Bodies stay shared in the F4 store. This index adds original-port relations;
it neither imports the target nor makes its exec dictionaries into modules.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis import source_namespace_interfaces as interfaces, source_namespace_contents as contents
from scar.analysis import source_namespace_captures as captures, source_exec_query as exec_query
from scar.analysis import source_compiler_symbol_variants as symbols, source_binding_variants
from scar.analysis import source_suspension_interfaces
from scar.analysis.source_symbol_variants import _table
from scar.analysis.normal_facts import SourceFactStore
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import source_namespaces as N, source_binding_variants as B
from scar.ir.program import source_productions as P
from scar.ir.record_codec import decode


_TYPES = dict(accesses=N.NamespaceAccess, explicit=N.ExplicitNamespaceAction,
    references=N.GlobalsEnvironmentReference, captures=N.FunctionGlobalsCapture,
    obligations=N.NamespaceGraphObligation, bindings=N.NamespaceInterfaceBinding,
    globals_bindings=N.GlobalsReferenceBinding, contents=N.NamespaceContentLink)


def pins():
    return {name:sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in (
        ('types',N),('interfaces',interfaces),('contents',contents),('captures',captures),
        ('exec_query',exec_query),('binding_variants',source_binding_variants),
        ('source_plan_reader',source_suspension_interfaces))}


def _report_parent(reference):
    path = Path(reference['path']); raw = (path/'result.json').read_bytes()
    if sha256(raw).hexdigest()!=reference['sha256']:
        raise ValueError('namespace parent report changed')
    return path,raw,json.loads(raw)


def build_namespace_graph(exec_roots, out, *, jobs=4):
    started = time.monotonic(); out = Path(out).absolute()
    if out.exists():
        raise ValueError('fresh namespace output required')
    graph = exec_query.ExecRootGraph(exec_roots)
    original = (graph.path/'result.json').read_bytes()
    store = SourceFactStore(graph.report['source_facts'])
    connections = tuple(graph.connections())
    f4_root,f4_report = graph.parents['f4_graphs']
    _,_,symbol_report = _report_parent(f4_report['compiler_symbols'])
    binding_ref = symbol_report['binding_variants']
    binding_root,binding_raw,binding_report = _report_parent(binding_ref)
    if (binding_report['implementation_sha256']!=sha256(Path(source_binding_variants.__file__).read_bytes()).hexdigest()
            or binding_report['pins']!=source_binding_variants.pins()
            or binding_report['source_facts_sha256']!=graph.report['source_facts_sha256']):
        raise ValueError('namespace binding variant producer or source parent differs')
    initial_pins = pins(); producer = sha256(Path(__file__).read_bytes()).hexdigest()
    snapshots = [(graph.path/'result.json',original),(binding_root/'result.json',binding_raw)]
    _durable_mkdir(out); variants = {}; totals = {name:0 for name in _TYPES}
    index = source_suspension_interfaces.SuspensionInterfaceIndex(store,jobs=jobs)
    try:
        for namespace in sorted({c.root.owner.unit for c in connections}):
            descriptor = f4_report['variants'][namespace]
            binding_document = symbols._variant(binding_root,binding_report['variants'][namespace])
            binding = decode(B.SourceBindingVariant,binding_document)
            rows = {name:[] for name in _TYPES}
            for table in ('expressions','statements','roots'):
                for wire in _table(f4_root/descriptor['path'],descriptor['tables'][table]):
                    plan = decode(P.SourceProductionPlan,wire,record_tags=P.PRODUCTION_RECORD_TAGS)
                    values = interfaces.extract_namespace_interfaces(namespace,plan,binding.bindings,binding.declarations)
                    for name,value in zip(('accesses','explicit','references','captures','obligations'),values):
                        rows[name].extend(value)
            selected = [c for c in connections if c.root.owner.unit==namespace]
            for connection in selected:
                bound,refs = interfaces.bind_exec_namespaces(connection,binding.bindings,rows['references'],rows['captures'])
                rows['bindings'].extend(bound); rows['globals_bindings'].extend(refs)
                caller = store.load(connection.owner.unit)
                rows['contents'].extend(contents.link_namespace_contents(connection,rows['accesses'],bound,refs,caller,index))
            folder = out/namespace; _durable_mkdir(folder)
            tables = {name:write_table(folder/(name+'.jsonl.gz'),value) for name,value in rows.items()}
            counts = {name:len(value) for name,value in rows.items()}
            variants[namespace] = dict(path=namespace,tables=tables,counts=counts)
            for name,count in counts.items():totals[name]+=count
        index.validate_parents()
        if (pins()!=initial_pins or sha256(Path(__file__).read_bytes()).hexdigest()!=producer
                or (store.path/'result.json').read_bytes()!=store.raw
                or any(path.read_bytes()!=raw for path,raw in snapshots)):
            raise ValueError('namespace input or rules changed during construction')
        report = dict(schema='scar.source-namespace-graph',schema_version=1,
            status='CONDITIONAL_NAMESPACE_DEPENDENCIES_CONNECTED',profile='NORMAL_SUCCESS',
            exec_roots=dict(path=str(graph.path),sha256=sha256(original).hexdigest()),
            binding_variants=binding_ref,source_facts=graph.report['source_facts'],
            source_facts_sha256=graph.report['source_facts_sha256'],variants=variants,counts=totals,
            source_plan_reads=index.stats,seconds=time.monotonic()-started,
            target_executed=False,runtime_namespace_contents_observed=False,
            global_solver_integrated=False,first_stage_complete=False,
            implementation_sha256=producer,pins=initial_pins)
        _durable_bytes(out/'result.json',_json(report),replace=False)
        return report
    finally:
        index.close()


class NamespaceGraph:
    """Stream the small typed overlay while retaining original parent graphs."""
    def __init__(self, path):
        self.path = Path(path).absolute()
        self.report = r = json.loads((self.path/'result.json').read_bytes())
        if ((r['schema'],r['schema_version'],r['profile'])!=('scar.source-namespace-graph',1,'NORMAL_SUCCESS')
                or r['implementation_sha256']!=sha256(Path(__file__).read_bytes()).hexdigest() or r['pins']!=pins()):
            raise ValueError('namespace graph producer or profile differs')
        root,_,_ = _report_parent(r['exec_roots'])
        self.exec_graph = exec_query.ExecRootGraph(root)
        self.connections = {c.id:c for c in self.exec_graph.connections()}
        _report_parent(r['binding_variants'])
        if self.exec_graph.report['source_facts_sha256']!=r['source_facts_sha256']:
            raise ValueError('namespace graph source parent differs')

    def records(self, table, *, namespace=None):
        value_type = _TYPES[table]
        for unit,descriptor in self.report['variants'].items():
            if namespace is not None and unit!=namespace:
                continue
            count = 0
            for wire in _table(self.path/descriptor['path'],descriptor['tables'][table]):
                value = decode(value_type,wire,record_tags=P.PRODUCTION_RECORD_TAGS)
                if hasattr(value,'connection') and value.connection not in self.connections:
                    raise ValueError('namespace row lost its exec branch')
                if table=='accesses' and tuple(s.ordinal for s in value.lookup)!=tuple(range(len(value.lookup))):
                    raise ValueError('namespace lookup order differs')
                count+=1; yield value
            if count!=descriptor['counts'][table]:
                raise ValueError('namespace typed row count differs')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exec-roots',required=True)
    parser.add_argument('--out',required=True)
    parser.add_argument('--jobs',type=int,default=4)
    args = parser.parse_args()
    report = build_namespace_graph(args.exec_roots,args.out,jobs=args.jobs)
    print(json.dumps(dict(status=report['status'],counts=report['counts'],seconds=report['seconds'])),flush=True)


if __name__=='__main__':main()
