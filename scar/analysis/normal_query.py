"""Read conditional source-call edges and expand their original shared bodies.

No new program nodes are constructed. A fixed point is not complete dispatch
coverage, and source candidates never grant transformation authority.
"""
import argparse
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path
from dataclasses import fields
from typing import get_type_hints
from types import SimpleNamespace

from scar.analysis.normal_links import _pins
from scar.analysis import normal_targets
from scar.analysis import normal_containers
from scar.analysis import normal_namespaces
from scar.analysis import source_descriptors,source_function_connections,source_construction
from scar.analysis.source_template_links import read_template_body
from scar.ir.program import normal_targets as T
from scar.ir.program import source_productions as P
from scar.ir.program import normal_namespaces as N
from scar.ir.program import normal_graph as G
from scar.ir.program import normal_links as F
from scar.ir.program.python_bindings import SourceCallSite
from scar.ir.record_codec import decode


class NormalCallGraph:
    """Small report index; bodies and value tables remain in their unit stores."""

    def __init__(self, targets):
        self.path = Path(targets).absolute()
        self.report = json.loads((self.path / 'result.json').read_bytes())
        if self.report['schema'] != 'scar.normal-source-targets' or self.report['schema_version'] != 8:
            raise ValueError('expected current source target graph')
        if self.report['types_sha256'] != sha256(Path(T.__file__).read_bytes()).hexdigest():
            raise ValueError('call edge declarations differ')
        if self.report['implementation_sha256'] != sha256(Path(normal_targets.__file__).read_bytes()).hexdigest():
            raise ValueError('call target producer differs')
        if self.report['container_implementation_sha256'] != sha256(Path(normal_containers.__file__).read_bytes()).hexdigest():
            raise ValueError('container flow producer differs')
        if self.report['namespace_implementation_sha256'] != sha256(Path(normal_namespaces.__file__).read_bytes()).hexdigest():
            raise ValueError('namespace relationship producer differs')
        if self.report['namespace_types_sha256'] != sha256(Path(N.__file__).read_bytes()).hexdigest():
            raise ValueError('namespace declarations differ')
        for field,module in (('descriptor_implementation_sha256',source_descriptors),
                ('invocation_implementation_sha256',source_function_connections),
                ('construction_implementation_sha256',source_construction)):
            if self.report[field]!=sha256(Path(module.__file__).read_bytes()).hexdigest():raise ValueError('source invocation/descriptor implementation differs')
        self.facts = Path(self.report['source_facts'])
        raw = (self.facts / 'result.json').read_bytes()
        if sha256(raw).hexdigest() != self.report['source_facts_sha256']:
            raise ValueError('source fact result differs')
        from scar.analysis.normal_facts import SourceFactStore
        self.fact_store=SourceFactStore(self.facts);self.inputs=self.fact_store.report
        self.units=self.fact_store.rows;self.sources=self.fact_store.sources
        self.templates=self.fact_store.templates
        if self.report.get('analysis_mode')=='ENTRY_SCOPED_MAY_ANALYSIS':
            from scar.analysis import normal_entry,normal_facts
            from scar.ir.program import normal_entry as E
            for field,module in (('entry_implementation_sha256',normal_entry),('fact_reader_sha256',normal_facts),('entry_types_sha256',E)):
                if self.report[field]!=sha256(Path(module.__file__).read_bytes()).hexdigest():raise ValueError('entry scope implementation differs')

    def _documents(self, table, source, occurrence, anchor):
        unit = self.units_for_source(source)
        receipt = self.report[table]
        payload = (self.path / receipt['path']).read_bytes()
        if len(payload) != receipt['bytes'] or sha256(payload).hexdigest() != receipt['sha256']:
            raise ValueError('call fragment differs')
        raw = gzip.decompress(payload)
        if len(raw) != receipt['decoded_bytes'] or sha256(raw).hexdigest() != receipt['decoded_sha256']:
            raise ValueError('decoded call fragment differs')
        if raw.count(b'\n') != receipt['records']:
            raise ValueError('call record count differs')
        for line in raw.splitlines():
            document = json.loads(line)
            endpoint=document[anchor]
            if endpoint is not None and 'call' in endpoint:endpoint=endpoint['call']
            if unit is not None and (endpoint is None or endpoint['unit'] not in unit):
                continue
            if occurrence is not None and (endpoint is None or endpoint['port']['template']['occurrence'] != occurrence):
                continue
            yield document

    def calls(self, source=None, *, occurrence=None):
        """Validate the whole fragment receipt; decode selected unit edges only."""
        for document in self._documents('calls', source, occurrence, 'result'):
            link = decode(T.CallLink, document, record_tags=P.PRODUCTION_RECORD_TAGS)
            if link.result.unit not in self.units or link.callee.unit != link.result.unit:
                raise ValueError('call source is not in its input domain')
            if link.body is not None:
                if link.source_callable is None or link.body.unit != link.source_callable.unit or link.body.unit not in self.units:
                    raise ValueError('call body has no qualified source')
                if any(route.formal.unit != link.body.unit for route in link.parameters):
                    raise ValueError('formal parameters belong to another body source')
                if any(p.formal.unit != link.body.unit or p.pack.unit != link.result.unit for p in link.projections):
                    raise ValueError('argument projection is not owned by its original call/body')
            if link.binding is T.ArgumentBinding.SYMBOLIC_PACK and link.argument_packs is None:
                raise ValueError('symbolic binding needs its original parameter packs')
            yield link

    def contents(self, source=None, *, occurrence=None):
        """Possible content edges selected by the consuming source unit."""
        for document in self._documents('content', source, occurrence, 'target'):
            link = decode(T.ContentLink, document, record_tags=P.PRODUCTION_RECORD_TAGS)
            if any(port.unit not in self.units for port in (link.source,link.target,link.container)):
                raise ValueError('content endpoint is outside the input domain')
            yield link

    def constructions(self, source=None, *, occurrence=None):
        """Allocation, compatible-instance test and init interfaces per class call."""
        for row in self._documents('constructions', source, occurrence, 'result'):
            link=decode(T.ConstructionLink,row,record_tags=P.PRODUCTION_RECORD_TAGS)
            if any(p.unit not in self.units for p in (link.result,link.callee,link.source_class)):
                raise ValueError('construction anchors outside source catalog')
            for endpoint in (*link.inputs,*link.outputs):
                if endpoint.unit not in self.units:raise ValueError('construction endpoint outside source catalog')
                if type(endpoint) is T.ConstructionPort and (endpoint.call!=link.result or endpoint.source_class!=link.source_class):
                    raise ValueError('construction interface has another call/class anchor')
            yield link

    def namespace_lookups(self, source=None, *, occurrence=None):
        """Known receiver/member origins, including still-open native bindings."""
        for document in self._documents('namespaces',source,occurrence,'result'):
            link=decode(N.NamespaceLookup,document,record_tags=P.PRODUCTION_RECORD_TAGS)
            if any(port.unit not in self.units for port in (link.receiver,link.result)):
                raise ValueError('namespace endpoint is outside the input domain')
            if any(unit not in self.units for unit in link.source_units):
                raise ValueError('namespace source is outside the input domain')
            yield link

    def properties(self,source=None):
        unit=self.units_for_source(source)
        for row in self._documents('properties',None,None,'site'):
            if unit is None or row['site']['world']['unit'] in unit:
                yield decode(T.PropertyAccess,row,record_tags=P.PRODUCTION_RECORD_TAGS)

    def attribute_storage(self,source=None):
        unit=self.units_for_source(source)
        for row in self._documents('attribute_storage',None,None,'site'):
            if unit is None or row['site']['world']['unit'] in unit:
                yield decode(T.AttributeStorageAccess,row,record_tags=P.PRODUCTION_RECORD_TAGS)

    def entry_activations(self,source=None):
        """Scopes admitted by entry analysis; never runtime invocation records."""
        from scar.ir.program.normal_entry import ScopeActivationEvidence
        if 'entry_activations' not in self.report:return
        for row in self._documents('entry_activations',source,None,'target'):
            yield decode(ScopeActivationEvidence,row,record_tags=P.PRODUCTION_RECORD_TAGS)

    def module_demands(self,source=None):
        from scar.ir.program.normal_entry import ModuleEntryDemand
        if 'entry_module_demands' not in self.report:return
        unit=self.units_for_source(source)
        for row in self._documents('entry_module_demands',None,None,'producer'):
            producer=row['producer']
            if producer is not None and 'call' in producer:producer=producer['call']
            if unit is None or producer is not None and producer['unit'] in unit:
                yield decode(ModuleEntryDemand,row,record_tags=P.PRODUCTION_RECORD_TAGS)

    def body_demands(self,source=None):
        from scar.ir.program.normal_entry import BodyEntryDemand
        if 'entry_body_demands' not in self.report:return
        for row in self._documents('entry_body_demands',source,None,'producer'):
            yield decode(BodyEntryDemand,row,record_tags=P.PRODUCTION_RECORD_TAGS)

    def call_demands(self,source=None):
        from scar.ir.program.normal_entry import CallEntryDemand
        if 'entry_call_demands' not in self.report:return
        for row in self._documents('entry_call_demands',source,None,'result'):
            yield decode(CallEntryDemand,row,record_tags=P.PRODUCTION_RECORD_TAGS)

    def units_for_source(self,source=None):
        return None if source is None else frozenset(self.fact_store.units_for_source(source))

    def _fact_documents(self,source=None):
        selected=self.units_for_source(source)
        for identity,row in self.units.items():
            if selected is None or identity in selected:
                yield row,self.fact_store.document(identity)

    def call_sites(self, source=None):
        """Read all original calls; decode only their referenced source ports."""
        for row,document in self._fact_documents(source):
            ports=document['ports'];cache={}
            def port(index):
                if type(index) is not int or not 0<=index<len(ports):raise ValueError('call-site port ordinal differs')
                if index not in cache:cache[index]=T.GlobalPort(row['unit'],decode(G.Port,ports[index],record_tags=P.PRODUCTION_RECORD_TAGS))
                return cache[index]
            for wire in document['calls']:
                call=decode(F.Call,wire)
                yield SourceCallSite(port(call.callee),tuple(port(p) for p in call.positional),
                    tuple((name,port(p)) for name,p in call.keywords),port(call.result),port(call.world),port(call.result_world),
                    None if call.positional_pack is None else port(call.positional_pack),
                    None if call.keyword_pack is None else port(call.keyword_pack))

    def language_operations(self,source=None):
        """Original operator/world ABI, including unresolved protocol targets."""
        for row,document in self._fact_documents(source):
            ports=document['ports'];cache={}
            def port(index):
                if type(index) is not int or not 0<=index<len(ports):raise ValueError('operator port ordinal differs')
                if index not in cache:cache[index]=T.GlobalPort(row['unit'],decode(G.Port,ports[index],record_tags=P.PRODUCTION_RECORD_TAGS))
                return cache[index]
            for wire in document['operations']:
                operation=decode(F.LanguageOperation,wire)
                yield T.LanguageOperationSite(operation.action,operation.selector,tuple(map(port,operation.operands)),
                    port(operation.result),port(operation.world),port(operation.result_world))

    def attribute_sites(self,source=None):
        for row,document in self._fact_documents(source):
            ports=document['ports'];cache={}
            def port(index):
                if type(index) is not int or not 0<=index<len(ports):raise ValueError('attribute port ordinal differs')
                if index not in cache:cache[index]=T.GlobalPort(row['unit'],decode(G.Port,ports[index],record_tags=P.PRODUCTION_RECORD_TAGS))
                return cache[index]
            for wire in document['attributes']:
                a=decode(F.Attribute,wire);read=a.action in (F.AttributeAction.GET,F.AttributeAction.IMPORT_MEMBER)
                yield T.AttributeSite(T.AttributeOrigin.IMPORT_MEMBER if a.action is F.AttributeAction.IMPORT_MEMBER else T.AttributeOrigin.ATTRIBUTE,
                    a.action,port(a.receiver),a.name,port(a.value) if read else None,
                    port(a.value) if a.action is F.AttributeAction.SET else None,port(a.world),port(a.result_world))

    def unit_facts(self):
        """Read each unit against its own immutable parent receipt."""
        for identity in self.units:yield self.fact_store.load(identity)

    def expand(self, link):
        """Return the sealed original plan containing this candidate body.

        The caller selects link.body.region within that plan. Deferred bodies
        are definitions; expansion does not mean they execute at creation.
        """
        if link.body is None:
            raise ValueError('this edge has no source body')
        plan = read_template_body(self.fact_store.templates_for(link.body.unit), link.body.unit, link.body.template)
        if link.body.region not in {region.id for region in plan.regions}:
            raise ValueError('candidate region absent from original plan')
        return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--targets', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--occurrence', type=int)
    parser.add_argument('--content', action='store_true', help='also count possible container-content edges')
    parser.add_argument('--namespaces',action='store_true',help='also show inferred namespace/member relationships')
    args = parser.parse_args()
    view = NormalCallGraph(args.targets)
    links = tuple(view.calls(args.source, occurrence=args.occurrence))
    print(json.dumps(dict(source=str(Path(args.source).absolute()), candidate_links=len(links),
        modes=dict(Counter(link.mode for link in links)),
        source_targets=sorted({view.units[link.body.unit]['path'] for link in links if link.body is not None}),
        packed_links=sum(link.argument_packs is not None for link in links),
        content_links=sum(1 for _ in view.contents(args.source,occurrence=args.occurrence)) if args.content else None,
        namespace_lookups=[dict(namespace=l.namespace,member=l.member,kind=l.kind.value,
            inferred_source_values=l.inferred_source_values,binding_proven=l.binding_proven)
            for l in view.namespace_lookups(args.source,occurrence=args.occurrence)] if args.namespaces else None,
        runtime_dispatch_verified=False, first_stage_complete=False), indent=2))


if __name__ == '__main__':
    main()
