"""Receipt-bound source fact catalog with per-unit, lazy decoding."""
from bisect import bisect_right
from collections import Counter,defaultdict
from dataclasses import fields
import gzip
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints

from scar.analysis.normal_links import _pins
from scar.ir.program import normal_links as F, source_productions as P
from scar.ir.record_codec import decode


class SourceFactStore:
    def __init__(self,path):
        self.path=Path(path).absolute();self.raw=(self.path/'result.json').read_bytes()
        self.report=json.loads(self.raw)
        self.parents=();self.unit_parent={}
        if self.report['schema']=='scar.normal-source-fact-collection':
            self._collection();return
        if (self.report['schema'],self.report['schema_version'])!=('scar.normal-source-link-facts',6):
            raise ValueError('scope-qualified source facts required')
        if self.report['implementation_sha256']!=_pins():raise ValueError('source fact producer differs')
        self.templates=Path(self.report['templates']);self.model=Path(self.report['model'])
        if sha256((self.templates/'result.json').read_bytes()).hexdigest()!=self.report['source_result_sha256']:
            raise ValueError('source template parent differs')
        model_raw=(self.model/'manifest.json').read_bytes()
        if sha256(model_raw).hexdigest()!=self.report['model_manifest_sha256']:raise ValueError('source model differs')
        self.model_units={u['key']:u for u in json.loads(model_raw)['units']}
        self.rows={r['unit']:r for r in self.report['units']}
        self._index()

    def _index(self):
        self.source_units=defaultdict(list)
        for row in self.rows.values():self.source_units[row['path']].append(row['unit'])
        self.sources={p:units[0] for p,units in self.source_units.items() if len(units)==1}
        self.offsets={};self.starts=[];self.identities=[];self.size=0;self.loaded={}
        for row in self.rows.values():
            self.starts.append(self.size);self.identities.append(row['unit']);self.offsets[row['unit']]=self.size
            self.size+=row['counts']['ports']
        self.hints=get_type_hints(F.UnitFacts);self.expected={f.name for f in fields(F.UnitFacts)}

    def _collection(self):
        if self.report['schema_version']!=1:raise ValueError('unsupported source fact collection')
        from scar.analysis.source_template_links import _json
        if self.report['implementation_sha256']!=sha256(Path(__file__).read_bytes()).hexdigest():
            raise ValueError('source fact collection implementation differs')
        self.parents=[];rows={};self.model_units={}
        for index,receipt in enumerate(self.report['parents']):
            path=Path(receipt['path']);raw=(path/'result.json').read_bytes()
            if sha256(raw).hexdigest()!=receipt['sha256'] or json.loads(raw)['schema']!='scar.normal-source-link-facts':
                raise ValueError('collection needs pinned primitive source fact parents')
            parent=SourceFactStore(path);self.parents.append(parent)
            for identity,row in parent.rows.items():
                if identity in rows:
                    if _json(rows[identity])!=_json(row):raise ValueError('source unit has conflicting parent records')
                    continue
                rows[identity]=row;self.unit_parent[identity]=index;self.model_units[identity]=parent.model_units[identity]
        self.parents=tuple(self.parents);self.rows=rows
        if list(rows.values())!=self.report['units']:raise ValueError('collection source directory differs')
        counts=Counter()
        for row in rows.values():counts.update(row['counts'])
        if dict(counts)!=self.report['counts'] or len(rows)!=self.report['selected_sources']:
            raise ValueError('collection record denominators differ')
        self.model=self.parents[0].model;self.templates=self.parents[0].templates
        self._index()

    def model_for(self,identity):
        return self.parents[self.unit_parent[identity]].model if self.parents else self.model

    def templates_for(self,identity):
        return self.parents[self.unit_parent[identity]].templates if self.parents else self.templates

    def units_for_source(self,source):
        return tuple(self.source_units[str(Path(source).absolute())])

    def locate(self,point):
        if type(point) is not int or not 0<=point<self.size:raise ValueError('source point outside declared catalog')
        i=bisect_right(self.starts,point)-1
        return self.identities[i],point-self.starts[i]

    def document(self,identity):
        if self.parents:return self.parents[self.unit_parent[identity]].document(identity)
        row=self.rows[identity];payload=(self.path/row['facts']).read_bytes()
        if len(payload)!=row['bytes'] or sha256(payload).hexdigest()!=row['sha256']:raise ValueError('source fact stored receipt differs')
        raw=gzip.decompress(payload)
        if len(raw)!=row['decoded_bytes'] or sha256(raw).hexdigest()!=row['decoded_sha256']:raise ValueError('source fact decoded receipt differs')
        doc=json.loads(raw)
        if set(doc)!=self.expected or doc['unit']!=identity:raise ValueError('source fact fields differ')
        ports=doc['ports'];aliases=doc['aliases'];size=len(ports)
        if size!=row['counts']['ports']:raise ValueError('source port catalog differs')
        if any(len(p)!=2 or any(type(v) is not int or not 0<=v<size for v in p) for p in aliases):
            raise ValueError('source alias ordinal differs')
        return doc

    def load(self,identity):
        if identity in self.loaded:return self.loaded[identity]
        if self.parents:
            unit=self.parents[self.unit_parent[identity]].load(identity);self.loaded[identity]=unit;return unit
        doc=self.document(identity);ports=doc['ports'];aliases=doc['aliases']
        loaded={k:decode(self.hints[k],v,record_tags=P.PRODUCTION_RECORD_TAGS) for k,v in doc.items() if k not in ('ports','aliases')}
        unit=SimpleNamespace(**loaded,ports=ports,aliases=aliases)
        coverage={table:bytearray(len(getattr(unit,table.value))) for table in F.FactTable}
        for group in unit.scope_groups:
            if group.owner.unit!=identity:raise ValueError('activation group belongs to another unit')
            for span in group.tables:
                covered=coverage[span.table]
                if not 0<=span.start<span.stop<=len(covered):raise ValueError('fact activation range differs')
                for i in range(span.start,span.stop):
                    if covered[i] and span.table.value!='aliases':raise ValueError('non-transport fact has multiple activation owners')
                    covered[i]=1
        if any(0 in c for c in coverage.values()):raise ValueError('source facts missing activation ownership')
        if unit.root_scope is None or unit.root_scope.owner.unit!=identity:raise ValueError('source module root missing')
        self.loaded[identity]=unit;return unit


def collect_fact_stores(parents,out):
    """Reference immutable per-unit stores; never copy/re-sign their bodies."""
    from scar.analysis.source_template_links import _json
    from scar.analysis.source_stage import _durable_mkdir,_durable_bytes
    stores=[]
    for path in parents:
        store=SourceFactStore(path)
        stores.extend(store.parents or (store,))
    unique={str(s.path):s for s in stores};stores=tuple(unique.values())
    if not stores:raise ValueError('source fact parents required')
    rows={};counts=Counter()
    for store in stores:
        for identity,row in store.rows.items():
            if identity in rows:
                if _json(rows[identity])!=_json(row):raise ValueError('conflicting source unit identity')
                continue
            rows[identity]=row;counts.update(row['counts'])
    out=Path(out).absolute()
    if out.exists():raise ValueError('fresh source collection output required')
    result=dict(schema='scar.normal-source-fact-collection',schema_version=1,
        parents=[dict(path=str(s.path),sha256=sha256(s.raw).hexdigest()) for s in stores],
        units=list(rows.values()),counts=dict(counts),selected_sources=len(rows),
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        copied_fact_bytes=0,target_executed=False,first_stage_complete=False)
    _durable_mkdir(out);_durable_bytes(out/'result.json',_json(result),replace=False)
    return result


class SourcePointSpace:
    def __init__(self,store,*,owners=False):self.store=store;self.owners=owners
    def __len__(self):return self.store.size
    def __getitem__(self,point):
        unit,index=self.store.locate(point)
        if self.owners:return unit
        return self.store.loaded[unit].ports[index]


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent',action='append',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args();r=collect_fact_stores(args.parent,args.out)
    print(json.dumps({k:r[k] for k in ('schema','selected_sources','copied_fact_bytes')},indent=2))
