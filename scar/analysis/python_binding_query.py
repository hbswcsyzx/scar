"""Read generated binding families, source candidates and original native bodies."""
import argparse
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis.normal_query import NormalCallGraph
from scar.analysis.normal_targets import propagation_pins
from scar.analysis import python_bindings
from scar.analysis import tensor_return_flow,tensor_stub_contracts,tensor_language_flow
from scar.ir.program import python_bindings as B,normal_namespaces as N,source_productions as P
from scar.ir.program import tensor_values as V,binding_returns as R
from scar.ir.program import normal_targets as T
from scar.ir.program import content_factors as C
from scar.ir.program import source_generators as D,suspension_interfaces as S
from scar.ir.program import normal_entry as E
from scar.analysis import normal_entry,normal_facts
from scar.ir.program.codec import loads as graph_loads
from scar.ir.record_codec import decode


class PythonBindingGraph:
    def __init__(self,path):
        self.path=Path(path).absolute();self.report=json.loads((self.path/'result.json').read_bytes())
        if self.report['schema']!='scar.generated-python-binding-graph' or self.report['schema_version']!=5:
            raise ValueError('unsupported generated binding graph')
        if self.report['propagation'] is not None and (
                self.report['source_propagation_pins'] != propagation_pins()
                or self.report['source_content_key_semantics'] != 'READ_SELECTOR_V1'):
            raise ValueError('binding source propagation or key semantics differ')
        if self.report['implementation_sha256']!=sha256(Path(python_bindings.__file__).read_bytes()).hexdigest():
            raise ValueError('binding graph producer differs')
        if self.report['types_sha256']!=sha256(Path(B.__file__).read_bytes()).hexdigest():
            raise ValueError('binding declarations differ')
        for field,module in (('return_flow_sha256',tensor_return_flow),('stub_collector_sha256',tensor_stub_contracts),
                ('return_types_sha256',R),('value_types_sha256',V),('language_flow_sha256',tensor_language_flow)):
            if self.report[field]!=sha256(Path(module.__file__).read_bytes()).hexdigest():raise ValueError('return interface implementation differs')
        self.source=NormalCallGraph(self.report['source_targets'])
        if sha256((self.source.path/'result.json').read_bytes()).hexdigest()!=self.report['source_result_sha256']:
            raise ValueError('source target graph differs')
        if self.report.get('analysis_mode')=='ENTRY_SCOPED_MAY_ANALYSIS':
            if tuple(self.report['entry_sources'])!=tuple(self.source.report['entry_sources']):
                raise ValueError('binding entry sources differ from the source query')
            for field,module in (('entry_implementation_sha256',normal_entry),('fact_reader_sha256',normal_facts),('entry_types_sha256',E)):
                if self.report[field]!=sha256(Path(module.__file__).read_bytes()).hexdigest():raise ValueError('entry binding implementation differs')
        self.exports={row['symbol']:row for row in self.report['exports']}
        self._definitions={};self._catalog=None;self._native={};self._lookup_streams={}

    def _table(self,row,cls,*,select=None):
        raw=(self.path/row['path']).read_bytes()
        if len(raw)!=row['bytes'] or sha256(raw).hexdigest()!=row['sha256']:raise ValueError('binding table receipt differs')
        raw=gzip.decompress(raw)
        if len(raw)!=row['decoded_bytes'] or sha256(raw).hexdigest()!=row['decoded_sha256'] or raw.count(b'\n')!=row['records']:
            raise ValueError('decoded binding table differs')
        for line in raw.splitlines():
            document=json.loads(line)
            if select is None or select(document):yield decode(cls,document,record_tags=P.PRODUCTION_RECORD_TAGS)

    def definitions(self,symbol=None):
        rows=self.exports.values() if symbol is None else (self.exports[symbol],)
        for row in rows:
            for definition in self._table(row,B.PythonBinding):
                if definition.native is not None and definition.native.selector!=definition.selector:
                    raise ValueError('binding/native selector differs')
                self._definitions[definition.id]=definition
                yield definition

    def definition(self,identity):
        if identity not in self._definitions:
            tuple(self.definitions())
        return self._definitions[identity]

    def lookup_links(self,source=None):
        unit=self.source.units_for_source(source)
        for row in self.report['units']:
            if unit is None or row['unit'] in unit:
                yield from self._table(row,B.NamespaceBindingLink)

    def original_lookup(self,link):
        artifact=link.lookup.artifact
        if artifact.sha256 not in self._lookup_streams:
            raw=Path(artifact.uri).read_bytes()
            if len(raw)!=artifact.size_bytes or sha256(raw).hexdigest()!=artifact.sha256:raise ValueError('original namespace table differs')
            self._lookup_streams[artifact.sha256]=gzip.decompress(raw).splitlines()
        index=int(link.lookup.locator.removeprefix('jsonl:'))-1
        lookup=decode(N.NamespaceLookup,json.loads(self._lookup_streams[artifact.sha256][index]),record_tags=P.PRODUCTION_RECORD_TAGS)
        if lookup.result!=link.result or lookup.receiver!=link.receiver:raise ValueError('namespace link selects another original port')
        return lookup

    def native_calls(self,source=None):
        unit=self.source.units_for_source(source)
        yield from self._table(self.report['native_calls'],B.NativeCallCandidate,
            select=None if unit is None else lambda row:row['site']['result']['unit'] in unit)

    def normalization(self,identity=None):
        select=None if identity is None else lambda row:decode(B.PythonBindingID,row['binding'])==identity
        yield from self._table(self.report['normalization'],B.NormalizationLink,select=select)

    def _source_table(self,name,cls,source,anchor):
        """Enhanced source facts from this run, independently of its parent."""
        if name not in self.report:return
        unit=self.source.units_for_source(source)
        def selected(row):
            for field in anchor.split('.'):row=row[field]
            if row is not None and 'call' in row:row=row['call']
            return row is not None and row['unit'] in unit
        yield from self._table(self.report[name],cls,select=None if unit is None else selected)

    def source_calls(self,source=None):
        yield from self._source_table('source_links',T.CallLink,source,'result')

    def source_contents(self,source=None):
        if self.report.get('source_content_encoding')=='EQUAL_NEIGHBORHOODS_V1':
            units=self.source.units_for_source(source)
            for factor in self.source_content_factors(source):
                for target in factor.targets:
                    if units is not None and target.unit not in units:continue
                    for origin in factor.sources:
                        yield T.ContentLink(origin,target,factor.container,factor.key,factor.semantics)
            return
        yield from self._source_table('source_content',T.ContentLink,source,'target')

    def source_content_factors(self,source=None):
        units=self.source.units_for_source(source)
        for factor in self._table(self.report['source_content_factors'],C.ContentFactor):
            if units is None or any(target.unit in units for target in factor.targets):yield factor

    def source_content_index_cycles(self,source=None):
        yield from self._source_table('source_content_index_cycles',C.ContentIndexCycle,source,'container')

    def source_namespace_lookups(self,source=None):
        yield from self._source_table('source_namespaces',N.NamespaceLookup,source,'result')

    def source_properties(self,source=None):
        yield from self._source_table('source_properties',T.PropertyAccess,source,'site.world')

    def source_attribute_storage(self,source=None):
        yield from self._source_table('source_attribute_storage',T.AttributeStorageAccess,source,'site.world')

    def source_attribute_contents(self,source=None):
        yield from self._source_table('source_attribute_content',T.AttributeContentLink,source,'target')

    def source_constructions(self,source=None):
        yield from self._source_table('source_constructions',T.ConstructionLink,source,'result')

    def deferred_creations(self,source=None):
        yield from self._source_table('source_deferred_creations',D.DeferredCreation,source,'origin.world')

    def iteration_interfaces(self,source=None):
        yield from self._source_table('source_iteration_interfaces',S.IterationSite,source,'value')

    def deferred_bodies(self,source=None):
        yield from self._source_table('source_deferred_bodies',S.DeferredBodySite,source,'source_callable')

    def generator_iterators(self,source=None):
        yield from self._source_table('source_generator_iterators',D.GeneratorIterator,source,'result')

    def generator_advances(self,source=None):
        yield from self._source_table('source_generator_advances',D.GeneratorAdvance,source,'iteration')

    def deferred_driver_obligations(self,source=None):
        yield from self._source_table('source_deferred_driver_obligations',D.DeferredDriverObligation,source,'origin.world')

    def entry_activations(self,source=None):
        yield from self._source_table('entry_activations',E.ScopeActivationEvidence,source,'target')

    def module_demands(self,source=None):
        yield from self._source_table('entry_module_demands',E.ModuleEntryDemand,source,'producer')

    def body_demands(self,source=None):
        yield from self._source_table('entry_body_demands',E.BodyEntryDemand,source,'producer')

    def call_demands(self,source=None):
        yield from self._source_table('entry_call_demands',E.CallEntryDemand,source,'result')

    def return_types(self,source=None):
        unit=self.source.units_for_source(source)
        yield from self._table(self.report['return_types'],V.ReturnTypeEvidence,
            select=None if unit is None else lambda row:row['target']['unit'] in unit)

    def declared_members(self,source=None):
        unit=self.source.units_for_source(source)
        yield from self._table(self.report['declared_members'],V.DeclaredMemberCall,
            select=None if unit is None else lambda row:row['site']['result']['unit'] in unit)

    def declared_protocols(self,source=None):
        unit=self.source.units_for_source(source)
        yield from self._table(self.report['declared_protocols'],V.DeclaredProtocolCall,
            select=None if unit is None else lambda row:row['receiver']['unit'] in unit)

    def declared_operators(self,source=None):
        unit=self.source.units_for_source(source)
        yield from self._table(self.report['declared_operators'],V.DeclaredOperatorCall,
            select=None if unit is None else lambda row:row['result']['unit'] in unit)

    def operator_frontiers(self,source=None):
        unit=self.source.units_for_source(source)
        yield from self._table(self.report['operator_frontiers'],V.LanguageProtocolFrontier,
            select=None if unit is None else lambda row:row['site']['result']['unit'] in unit)

    def expand_native(self,definition):
        if definition.native is None:raise ValueError('this binding has no admitted native schema graph')
        ref=definition.native.graph;artifact=ref.artifact
        if artifact.sha256 not in self._native:
            raw=Path(artifact.uri).read_bytes()
            if len(raw)!=artifact.size_bytes or sha256(raw).hexdigest()!=artifact.sha256:raise ValueError('native graph artifact differs')
            raw=gzip.decompress(raw)
            if len(raw)!=ref.decoded_bytes or sha256(raw).hexdigest()!=ref.decoded_sha256:raise ValueError('decoded native graph differs')
            self._native[artifact.sha256]=graph_loads(raw.decode())
        graph=self._native[artifact.sha256]
        if definition.native.boundary not in {b.id for b in graph.native_boundaries}:raise ValueError('native boundary absent from graph')
        return graph

    def wrapper(self,definition):
        if self._catalog is None:
            receipt=self.report['materials'];raw=Path(receipt['uri']).read_bytes()
            if len(raw)!=receipt['size_bytes'] or sha256(raw).hexdigest()!=receipt['sha256']:raise ValueError('binding materials differ')
            self._catalog=json.loads(raw)
        value=self._catalog
        for key in definition.wrapper.locator.removeprefix('#/').split('/'):
            value=value[key.replace('~1','/').replace('~0','~')]
        if sha256(value['text'].encode()).hexdigest()!=value['sha256']:raise ValueError('generated wrapper text differs')
        return value


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--graph',required=True)
    parser.add_argument('--symbol');parser.add_argument('--source');args=parser.parse_args();view=PythonBindingGraph(args.graph)
    definitions=tuple(view.definitions(args.symbol)) if args.symbol else ()
    calls=tuple(view.native_calls(args.source)) if args.source else ()
    returns=tuple(view.return_types(args.source)) if args.source else ()
    members=tuple(view.declared_members(args.source)) if args.source else ()
    protocols=tuple(view.declared_protocols(args.source)) if args.source else ()
    operators=tuple(view.declared_operators(args.source)) if args.source else ()
    frontiers=tuple(view.operator_frontiers(args.source)) if args.source else ()
    print(json.dumps(dict(symbol=args.symbol,definitions=[dict(selector=d.selector,signature=d.parser_signature,
        parser_index=d.parser_index,branch=d.branch_condition,native_status=d.native_status,
        python_return=None if d.python_return is None else d.python_return.kind.value) for d in definitions],
        source=args.source,native_call_sites=len({c.site.result for c in calls}),native_call_candidates=len(calls),
        return_type_kinds=dict(Counter(r.shape.value for r in returns)),
        declared_member_calls=len(members),declared_member_names=sorted({m.member for m in members}),
        declared_protocol_calls=len(protocols),
        declared_operator_calls=len(operators),operator_members=sorted({o.member for o in operators}),
        operator_declaration_frontiers=len(frontiers),
        conditions=view.report['conditions'],runtime_binding_verified=False,first_stage_complete=False),indent=2))


if __name__=='__main__':main()
