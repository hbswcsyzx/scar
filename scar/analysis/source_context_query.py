"""Read context-qualified call graphs without source-only schema coercion."""
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis import normal_query as Q,source_context_build as producer
from scar.analysis.normal_facts import SourceFactStore
from scar.analysis.source_context_fact_store import ContextFactStore
from scar.analysis.source_context_interfaces import ContextInterfaceStore
from scar.analysis.source_namespace_graph import NamespaceGraph
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_productions import _digest
from scar.ir.program import source_exec_roots as X
from scar.ir.program import source_builtin_namespaces as B
from scar.ir.record_codec import decode,encode


class ContextTargetGraph(Q.NormalCallGraph):
    """Reuse typed relation readers; compilation bodies keep their own store."""
    def __init__(self, path):
        self.path=Path(path).absolute()
        self.report=r=json.loads((self.path/'result.json').read_bytes())
        if ((r['schema'],r['schema_version'],r['profile'])!=('scar.context-source-targets',1,'NORMAL_SUCCESS')
                or r['implementation_sha256']!=sha256(Path(producer.__file__).read_bytes()).hexdigest()
                or r['extension_pins']!=producer.pins()):
            raise ValueError('context graph producer differs')
        if r['propagation_pins']!=Q.normal_targets.propagation_pins() or r['content_key_semantics']!='READ_SELECTOR_V1':
            raise ValueError('original relation rules differ')
        modules=(('source_only_publisher_sha256',Q.normal_targets),('types_sha256',Q.T),
            ('container_implementation_sha256',Q.normal_containers),('namespace_implementation_sha256',Q.normal_namespaces),
            ('namespace_types_sha256',Q.N),('descriptor_implementation_sha256',Q.source_descriptors),
            ('invocation_implementation_sha256',Q.source_function_connections),
            ('construction_implementation_sha256',Q.source_construction),
            ('generator_implementation_sha256',Q.source_generators),('generator_types_sha256',Q.D),
            ('suspension_interface_implementation_sha256',Q.source_suspension_interfaces),('suspension_interface_types_sha256',Q.S))
        if any(r[name]!=sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in modules):
            raise ValueError('context relation declarations or original implementation differ')
        expected={name:sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in
            (('batch',Q.source_template_batch),('workers',Q.source_template_workers),('output',Q.normal_output),
             ('interfaces',Q.source_interface_store),('interface_types',Q.L),
             ('content_factors',Q.source_content_factors),('content_factor_types',Q.C))}
        if r['source_reader_pins']!=expected:
            raise ValueError('context relation table reader differs')
        self.facts=Path(r['source_facts']); base=SourceFactStore(self.facts)
        if sha256(base.raw).hexdigest()!=r['source_facts_sha256']:
            raise ValueError('context base source catalog differs')
        for name in ('namespace_graph','script_entry'):
            ref=r[name]
            if sha256((Path(ref['path'])/'result.json').read_bytes()).hexdigest()!=ref['sha256']:
                raise ValueError('context graph parent differs: '+name)
        self.namespace_graph=NamespaceGraph(r['namespace_graph']['path'])
        self.fact_store=ContextFactStore(base,self.namespace_graph.exec_graph)
        receipt=r['context_facts']; raw=(self.path/receipt['path']).read_bytes()
        if (len(raw)!=receipt['bytes'] or sha256(raw).hexdigest()!=receipt['sha256'] or raw!=self.fact_store.raw):
            raise ValueError('context source catalog receipt differs')
        self.inputs=self.fact_store.report; self.units=self.fact_store.rows; self.sources=self.fact_store.sources
        self.templates=base.templates
        self.interface_store=ContextInterfaceStore(r['interface_summary']['base']['path'],self.fact_store,self.namespace_graph.exec_graph)
        if self.interface_store.receipt!=r['interface_summary']:
            raise ValueError('context local interfaces differ')

    def units_for_source(self, source=None):
        if source is None:return None
        selected=set(self.fact_store.units_for_source(source)); path=str(Path(source).absolute())
        selected.update(unit for unit in self.fact_store.original_source_units if self.units[unit]['path']==path)
        return frozenset(selected)

    def _fact_documents(self, source=None):
        selected=self.units_for_source(source)
        for unit,row in self.units.items():
            if selected is not None and unit not in selected:continue
            if unit in self.fact_store.original_source_units:
                document=encode(self.fact_store.load(unit),record_tags=Q.P.PRODUCTION_RECORD_TAGS)
            else:
                document=self.fact_store.base.document(unit)
            yield row,document

    def exec_connections(self, source=None):
        for document in self._documents('exec_connections',source,None,'site.result'):
            value=decode(X.ExecRootConnection,document,record_tags=Q.P.PRODUCTION_RECORD_TAGS)
            if value.root.owner.unit not in self.fact_store.original_source_units:
                raise ValueError('exec root is outside compilation contexts')
            yield value

    def builtin_candidates(self, source=None):
        for document in self._documents('builtin_candidates',source,None,'access'):
            yield decode(B.GuardedBuiltinCandidate,document,record_tags=Q.P.PRODUCTION_RECORD_TAGS)

    def builtin_selections(self, source=None):
        for document in self._documents('builtin_selections',source,None,'access'):
            yield decode(B.BuiltinNamespaceSelection,document,record_tags=Q.P.PRODUCTION_RECORD_TAGS)

    def expand(self, link):
        if link.body is None:raise ValueError('this edge has no source body')
        if link.body.unit not in self.fact_store.original_source_units:
            return super().expand(link)
        connection=next(c for c in self.namespace_graph.exec_graph.connections() if c.root.owner.unit==link.body.unit)
        graph=self.namespace_graph.exec_graph.expand_root(connection)
        node=next(n for n in graph.templates if n.key==link.body.template)
        root,report=self.namespace_graph.exec_graph.parents['f4_graphs']
        descriptor=report['variants'][link.body.unit]
        wire=_table(root/descriptor['path'],descriptor['tables'][node.origin.domain.value])[node.origin.line-1]
        if _digest(wire)!=node.origin.plan_sha256:
            raise ValueError('context body plan digest differs')
        plan=decode(Q.P.SourceProductionPlan,wire,record_tags=Q.P.PRODUCTION_RECORD_TAGS)
        if link.body.region not in {region.id for region in plan.regions}:
            raise ValueError('context body region absent from shared source plan')
        return plan
