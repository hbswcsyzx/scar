"""Navigate exec boundary regions and expand their shared compiled subgraphs."""
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis import source_exec_roots as producer,source_f4_variants
from scar.analysis.source_symbol_variants import _table
from scar.ir.program import source_exec_roots as X,normal_links as F,normal_graph as G,source_productions as P
from scar.ir.program.source_template_links import SourceTemplateGraph
from scar.ir.record_codec import _decode,_record_tags


class ExecRootGraph:
    """Small reference index; body graphs stay in their compilation stores."""
    def __init__(self,path):
        self.path=Path(path).absolute();r=json.loads((self.path/'result.json').read_bytes());self.report=r
        if (r['schema'],r['schema_version'])!=('scar.source-exec-roots',1):
            raise ValueError('expected exec root graph')
        if (r['implementation_sha256']!=sha256(Path(producer.__file__).read_bytes()).hexdigest()
                or r['pins']!=producer.pins() or r['profile']!='NORMAL_SUCCESS'):
            raise ValueError('exec graph producer or normal-path scope differs')
        if sha256((Path(r['source_facts'])/'result.json').read_bytes()).hexdigest()!=r['source_facts_sha256']:
            raise ValueError('exec source fact catalog differs')
        self.parents={}
        for name in ('source_execution','compiled_sources','f4_graphs'):
            ref=r[name];root=Path(ref['path']);raw=(root/'result.json').read_bytes()
            if sha256(raw).hexdigest()!=ref['sha256']:
                raise ValueError('exec graph parent differs: '+name)
            report=json.loads(raw)
            if report['source_facts_sha256']!=r['source_facts_sha256']:
                raise ValueError('exec graph source parent differs')
            self.parents[name]=(root,report)
        root,fr=self.parents['f4_graphs']
        if (fr['implementation_sha256']!=sha256(Path(source_f4_variants.__file__).read_bytes()).hexdigest()
                or fr['pins']!=source_f4_variants.pins()):
            raise ValueError('exec body rules or source graph producer differ')
        self.tags=_record_tags(P.PRODUCTION_RECORD_TAGS)

    def connections(self):
        for wire in _table(self.path,self.report['tables']['connections']):
            value=_decode(X.ExecRootConnection,wire,self.tags)
            if value.root.owner.unit not in self.parents['f4_graphs'][1]['variants']:
                raise ValueError('exec root has no referenced subgraph')
            if value.code_use is None or value.code_use.exec_result!=value.site.result:
                raise ValueError('exec connection lost its original code-use witness')
            if value.profile!='NORMAL_SUCCESS' or value.normal_result.to_python() is not None:
                raise ValueError('exec normal-result contract differs')
            yield value

    def _rows(self,connection,table):
        root,report=self.parents['f4_graphs'];descriptor=report['variants'][connection.root.owner.unit]
        yield from _table(root/descriptor['path'],descriptor['tables'][table])

    def expand_root(self,connection):
        rows=list(self._rows(connection,'templates'))
        if len(rows)!=1:raise ValueError('exec body has multiple graph headers')
        graph=_decode(SourceTemplateGraph,rows[0],self.tags)
        root=next(n for n in graph.templates if n.key==connection.root.template)
        if graph.unit!=connection.root.owner.unit or root.root!=connection.root.region:
            raise ValueError('exec root interface differs from shared graph')
        return graph

    def root_edges(self,connection):
        for wire in self._rows(connection,'normal_edges'):
            yield _decode(G.Edge,wire,self.tags)

    def root_facts(self,connection):
        rows=list(self._rows(connection,'facts'))
        if len(rows)!=1:raise ValueError('exec body has multiple primitive fact fragments')
        facts=_decode(F.UnitFacts,rows[0],self.tags)
        if facts.root_scope!=connection.root:raise ValueError('exec primitive root witness differs')
        return facts
