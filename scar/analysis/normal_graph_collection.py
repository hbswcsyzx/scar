"""Index disjoint source graph stores without copying instructions or edges.

The directory closes the declared source-unit domain only. It does not prove
runtime dispatch, effects, logical versions, or completion of the first stage.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis import normal_graph
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import graph_collection as C
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import encode,decode


def _artifact(path,schema):
    path=Path(path).absolute()
    if path.resolve()!=path:raise ValueError('graph directory needs canonical artifact paths')
    raw=path.read_bytes()
    return ProviderArtifact(str(path),sha256(raw).hexdigest(),len(raw),schema)


def _read(artifact):
    raw=Path(artifact.uri).read_bytes()
    if len(raw)!=artifact.size_bytes or sha256(raw).hexdigest()!=artifact.sha256:
        raise ValueError('graph directory artifact differs')
    return json.loads(raw)


def _member(root,relative):
    path=root/relative
    if path.resolve()!=path or not path.is_relative_to(root):raise ValueError('graph shard path leaves its store')
    return path


def _header(root,row):
    raw=_member(root,row['header']).read_bytes()
    if len(raw)!=row['header_bytes'] or sha256(raw).hexdigest()!=row['header_sha256']:
        raise ValueError('source graph header differs')
    header=json.loads(raw)
    if header['unit']!=row['unit']:raise ValueError('source graph header selects another unit')
    return header


def _projection(directory,*,check_shards):
    parent=_read(directory.source_interfaces);parent_root=Path(directory.source_interfaces.uri).parent
    if parent['schema']!='scar.source-template-link-store' or parent['schema_version']!=1 or parent['status']!='SOURCE_INTERFACES_LINKED':
        raise ValueError('source interface graph version differs')
    source={row['unit']:row for row in parent['units']}
    if len(source)!=len(parent['units']) or len(source)!=parent['selected_sources']:
        raise ValueError('source interface units differ')
    stores={};units={};counts=Counter();compressed=0
    for store in directory.stores:
        if store.id in stores or store.id.value!=store.result.sha256:raise ValueError('duplicate or incorrect graph store identity')
        report=_read(store.result);root=Path(store.result.uri).parent
        if report['schema']!='scar.normal-program-graph' or report['schema_version']!=1 or report['profile']!='NORMAL_SUCCESS' or report['status']!='NORMAL_GRAPH_GENERATED':
            raise ValueError('normal graph profile/version differs')
        if report['implementation_sha256']!=normal_graph._pins():raise ValueError('normal graph producer differs')
        if report['source_result_sha256']!=directory.source_interfaces.sha256 or Path(report['source_interfaces']).absolute()!=parent_root:
            raise ValueError('normal graphs do not share the original source interface graph')
        if len(report['units'])!=report['selected_sources']:raise ValueError('normal graph unit count differs')
        subtotal=Counter();subbytes=0
        for row in report['units']:
            unit=row['unit']
            if unit not in source or unit in units:raise ValueError('foreign or duplicate source graph unit')
            path=Path(source[unit]['path']);suffix=path.suffix
            if suffix not in ('.py','.pyi'):raise ValueError('source role needs an explicit supported file kind')
            role=C.SourceUnitRole.PYTHON_SOURCE if suffix=='.py' else C.SourceUnitRole.TYPE_DECLARATION
            units[unit]=C.NormalGraphUnit(unit,store.id,role)
            header=_header(root,row);basis=_header(parent_root,source[unit])
            if basis['schema']!='scar.source-template-links' or basis['schema_version']!=1:
                raise ValueError('original template header version differs')
            if header['schema']!='scar.normal-program-graph-unit' or header['schema_version']!=1 or header['profile']!='NORMAL_SUCCESS':
                raise ValueError('source graph unit version/profile differs')
            if header['input']!=basis['input'] or header['counts']!=row['counts']:
                raise ValueError('source graph input or counts differ')
            if row['counts']['templates']!=basis['templates']['records'] or row['counts']['templates']!=source[unit]['templates']:
                raise ValueError('source graph template domain differs')
            edges=header['edges'];edge_count=sum(row['counts'].get(k,0) for k in ('CONTROL','DATA','STATE','DECLARE'))
            if edge_count!=edges['records'] or edges['bytes']!=row['compressed_bytes']:
                raise ValueError('source graph edge publication differs')
            if check_shards:
                payload=_member(root/Path(row['header']).parent,edges['path']).read_bytes()
                if len(payload)!=edges['bytes'] or sha256(payload).hexdigest()!=edges['sha256']:
                    raise ValueError('source graph compressed edge shard differs')
            subtotal.update(row['counts']);subbytes+=row['compressed_bytes']
        if dict(subtotal)!=report['counts'] or subbytes!=report['compressed_bytes']:
            raise ValueError('normal graph store totals differ')
        stores[store.id]=(root,report);counts.update(subtotal);compressed+=subbytes
    if set(units)!=set(source):raise ValueError('declared source graph domain is incomplete')
    if tuple(sorted(units.values(),key=lambda u:u.unit))!=directory.units:
        raise ValueError('graph directory does not select the original units/roles')
    return parent,stores,units,counts,compressed


def build_collection(templates,graphs,out):
    started=time.monotonic();out=Path(out).absolute()
    if out.exists():raise ValueError('fresh graph directory output required')
    parent=_artifact(Path(templates)/'result.json','scar.source-template-link-store')
    stores=[];units=[]
    sources={u['unit']:u for u in _read(parent)['units']}
    for graph in graphs:
        artifact=_artifact(Path(graph)/'result.json','scar.normal-program-graph')
        identity=C.NormalGraphStoreID(artifact.sha256);stores.append(C.NormalGraphStore(identity,artifact))
        for row in _read(artifact)['units']:
            source=sources.get(row['unit'])
            if source is None:raise ValueError('graph store contains a foreign source unit')
            suffix=Path(source['path']).suffix
            if suffix not in ('.py','.pyi'):raise ValueError('source role is not declared')
            role=C.SourceUnitRole.PYTHON_SOURCE if suffix=='.py' else C.SourceUnitRole.TYPE_DECLARATION
            units.append(C.NormalGraphUnit(row['unit'],identity,role))
    directory=C.NormalGraphDirectory(parent,tuple(stores),tuple(sorted(units,key=lambda u:u.unit)))
    _,_,_,counts,compressed=_projection(directory,check_shards=True)
    _read(parent)
    for store in stores:_read(store.result)
    _durable_mkdir(out)
    report=dict(schema='scar.normal-graph-collection',schema_version=1,status='DECLARED_SOURCE_GRAPH_DOMAIN_INDEXED',
        directory=encode(directory),source_units=len(units),source_roles=dict(Counter(u.role.value for u in units)),
        graph_stores=len(stores),counts=dict(counts),edge_storage_bytes=compressed,copied_edge_bytes=0,
        declared_unit_coverage_complete=True,edge_types_replayed=False,profile='NORMAL_SUCCESS',
        runtime_dispatch_verified=False,target_executed=False,first_stage_complete=False,
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),types_sha256=sha256(Path(C.__file__).read_bytes()).hexdigest(),
        seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json',_json(report),replace=False);return report


class NormalGraphCollection:
    def __init__(self,path):
        self.path=Path(path).absolute();self.report=json.loads((self.path/'result.json').read_bytes())
        if self.report['schema']!='scar.normal-graph-collection' or self.report['schema_version']!=1:
            raise ValueError('normal graph directory version differs')
        if self.report['implementation_sha256']!=sha256(Path(__file__).read_bytes()).hexdigest() or self.report['types_sha256']!=sha256(Path(C.__file__).read_bytes()).hexdigest():
            raise ValueError('normal graph directory implementation/types differ')
        self.directory=decode(C.NormalGraphDirectory,self.report['directory'])
        parent,self.stores,self.units,counts,compressed=_projection(self.directory,check_shards=False)
        roles=dict(Counter(u.role.value for u in self.units.values()))
        if counts!=self.report['counts'] or compressed!=self.report['edge_storage_bytes'] or roles!=self.report['source_roles']:
            raise ValueError('normal graph directory totals differ')
        if len(self.units)!=self.report['source_units'] or len(self.stores)!=self.report['graph_stores']:
            raise ValueError('normal graph directory domain count differs')
        self.sources={str(Path(u['path']).absolute()):u['unit'] for u in parent['units']}

    def role(self,unit):return self.units[unit].role

    def edges(self,unit):
        """Typed lazy read of one original shard, including declaration graphs."""
        reference=self.units[unit];root,_=self.stores[reference.store]
        return normal_graph.read_normal_edges(root,unit)

    def source_edges(self,source):return self.edges(self.sources[str(Path(source).absolute())])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--templates',required=True);parser.add_argument('--graph',action='append',required=True)
    parser.add_argument('--out',required=True);args=parser.parse_args()
    result=build_collection(args.templates,args.graph,args.out)
    print(json.dumps({k:result[k] for k in ('status','source_units','source_roles','graph_stores','counts','copied_edge_bytes','seconds')},indent=2))


if __name__=='__main__':main()
