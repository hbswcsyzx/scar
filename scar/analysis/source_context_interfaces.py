"""Reuse local F5 interface projection for compiled-context graph fragments."""
from hashlib import sha256
from pathlib import Path
from types import FunctionType

from scar.analysis import source_interface_build
from scar.analysis.source_interface_store import SourceInterfaceStore
from scar.analysis.source_symbol_variants import _table
from scar.ir.program import source_productions as P
from scar.ir.program.source_template_links import SourceTemplateKey
from scar.ir.record_codec import decode


class ContextInterfaceStore:
    def __init__(self, base_path, context_store, exec_graph):
        self.base = SourceInterfaceStore(base_path,context_store.base)
        self.facts,self.exec_graph = context_store,exec_graph
        self.projected = {}; self.iterations = {}; self.bodies = {}; self.mappings = {}
        self.stats = dict(context_units=0,context_templates=0,iteration_reads=0,body_reads=0,mapping_reads=0)
        # Bind the trusted, unchanged projector to this composite fact space.
        # No module globals, source AST or target function are modified.
        original = source_interface_build._project
        self.project = FunctionType(original.__code__,dict(original.__globals__,_FACTS=context_store),
            original.__name__,original.__defaults__,original.__closure__)

    def covers(self, unit):
        return unit.unit in self.facts.original_source_units or self.base.covers(unit)

    def validate_parents(self):
        self.base.validate_parents(); self.facts.validate_parents()

    @property
    def receipt(self):
        return dict(schema='scar.context-source-interface-adapter',schema_version=1,
            base=self.base.receipt,context_facts_sha256=sha256(self.facts.raw).hexdigest(),
            exec_roots_sha256=self.facts.exec_sha256,
            implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
            projector_sha256=sha256(Path(source_interface_build.__file__).read_bytes()).hexdigest())

    def _load(self, unit):
        if unit.unit in self.projected:
            return
        connection = next(c for c in self.exec_graph.connections() if c.root.owner.unit==unit.unit)
        graph = self.exec_graph.expand_root(connection)
        nodes = {n.key:n for n in graph.templates}; plans = {}
        for table in ('expressions','statements','roots'):
            for wire in self.exec_graph._rows(connection,table):
                plan = decode(P.SourceProductionPlan,wire,record_tags=P.PRODUCTION_RECORD_TAGS)
                key = SourceTemplateKey(plan.source.occurrence,plan.purpose)
                if key not in nodes or plan.root!=nodes[key].root or plan.input!=graph.input or plan.profile!=graph.profile:
                    raise ValueError('compiled interface plan differs from its source graph')
                from scar.analysis.source_productions import _digest
                if _digest(wire)!=nodes[key].origin.plan_sha256:
                    raise ValueError('compiled interface plan digest differs')
                if key in plans:
                    raise ValueError('compiled interface contains duplicate plans')
                plans[key]=plan
        if plans.keys()!=nodes.keys():
            raise ValueError('compiled local interface template coverage differs')
        source = self.facts.original_source_units[unit.unit]
        original_parent = self.facts.base
        while original_parent.parents:
            original_parent=original_parent.parents[original_parent.unit_parent[source]]
        value = self.project(unit,graph,plans,self.facts.exec_sha256,original_parent.report['model_manifest_sha256'])
        self.projected[unit.unit]=value
        self.stats['context_units']+=1; self.stats['context_templates']+=len(plans)
        for item in value.iterations:self.iterations[unit.unit,unit.iterations[item.fact]]=item.site
        for item in value.bodies:self.bodies[unit.unit,unit.functions[item.fact].value]=item.site
        for item in value.mappings:self.mappings[unit.unit,item.template]=item

    def iteration(self, unit, item):
        if unit.unit not in self.facts.original_source_units:
            return self.base.iteration(unit,item)
        self._load(unit); self.stats['iteration_reads']+=1
        return self.iterations[unit.unit,item]

    def body(self, unit, function):
        if unit.unit not in self.facts.original_source_units:
            return self.base.body(unit,function)
        self._load(unit); self.stats['body_reads']+=1
        return self.bodies[unit.unit,function.value]

    def mapping(self, unit, template):
        if unit.unit not in self.facts.original_source_units:
            return self.base.mapping(unit,template)
        self._load(unit); self.stats['mapping_reads']+=1
        return self.mappings[unit.unit,template]
