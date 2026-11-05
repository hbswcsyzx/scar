"""Receipt-bound source fact catalog with per-unit, lazy decoding."""
from bisect import bisect_right
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
        self.sources={r['path']:r['unit'] for r in self.rows.values()}
        self.offsets={};self.starts=[];self.identities=[];self.size=0;self.loaded={}
        for row in self.rows.values():
            self.starts.append(self.size);self.identities.append(row['unit']);self.offsets[row['unit']]=self.size
            self.size+=row['counts']['ports']
        self.hints=get_type_hints(F.UnitFacts);self.expected={f.name for f in fields(F.UnitFacts)}

    def locate(self,point):
        if type(point) is not int or not 0<=point<self.size:raise ValueError('source point outside declared catalog')
        i=bisect_right(self.starts,point)-1
        return self.identities[i],point-self.starts[i]

    def load(self,identity):
        if identity in self.loaded:return self.loaded[identity]
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


class SourcePointSpace:
    def __init__(self,store,*,owners=False):self.store=store;self.owners=owners
    def __len__(self):return self.store.size
    def __getitem__(self,point):
        unit,index=self.store.locate(point)
        if self.owners:return unit
        return self.store.loaded[unit].ports[index]
