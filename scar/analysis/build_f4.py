"""Assemble existing F4 software, evidence and resource layers in one session.

The manifest references publications; it is not another source graph. A
missing component is a reported gap, never an empty dependency proof.
"""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.ir.program.dependencies import DependencyPoint as Point,DependencyNeighborhood as Neighborhood
from scar.ir.program.dependencies import NODE_TYPES
from scar.ir.record_codec import encode


def _reports(roots):
    seen=set();rows=[]
    for root in roots:
        for path in Path(root).glob('*/result.json'):
            if path in seen or path.stat().st_size>2_000_000:continue
            seen.add(path)
            try:rows.append((path.parent,json.loads(path.read_bytes())))
            except (OSError,ValueError):continue
    return sorted(rows,key=lambda p:p[0].stat().st_mtime_ns,reverse=True)


def discover(entry,trace,*,catalog=None,cache_roots=()):
    """Choose compatible cached materials by schema and exact catalog, not names."""
    from scar.analysis.source_declared_catalog import read_source_catalog
    from scar.analysis.build import _receipt
    roots=tuple(cache_roots) or (Path(__file__).resolve().parents[2]/'artifacts/current/queries',)
    rows=_reports(roots);gaps=[];selected=None
    schemas=('scar.context-source-targets','scar.declared-source-catalog','scar.observed-source-catalog')
    candidates=[Path(catalog)] if catalog else [p for p,r in rows if r.get('schema') in schemas]
    for path in candidates:
        try:
            c=read_source_catalog(path)
            units=[u for u,r in c.fact_store.rows.items() if r['path']==str(entry)
                and u not in c.fact_store.original_source_units]
            if len(units)!=1:continue
            model=c.fact_store.model_units[units[0]]
            if model['raw_sha256']!=sha256(entry.read_bytes()).hexdigest():continue
            selected=(c,units[0]);break
        except (ValueError,OSError) as error:
            gaps.append(dict(layer='inputs',kind='CACHED_CATALOG_REJECTED',path=str(path),detail=str(error)))
    if selected is None:
        if catalog:raise ValueError('explicit F4 catalog does not contain the current entry')
        return None
    c,unit=selected
    components={};functions=[];component_pins={}
    priority={'scar.source-observed-function-interfaces':0,'scar.source-returned-function-interfaces':1,
        'scar.source-function-interface-collection':2,'scar.source-function-interfaces':3,
        'scar.source-compiled-function-interfaces':4}
    for path,r in sorted(rows,key=lambda row:priority.get(row[1].get('schema'),10)):
        schema=r.get('schema')
        if schema in priority:
            if schema=='scar.source-observed-function-interfaces' and (trace is None or r.get('trace')!=str(trace)):continue
            # Ordinary leaves record catalog in their declared-call parent;
            # let the normal reader establish that original relationship.
            if r.get('catalog') and Path(r['catalog']).resolve()!=c.path.resolve():continue
            functions.append(_receipt(path/'result.json'))
        key={'scar.source-function-creations':'creations','scar.source-call-context-graph':'protocol',
            'scar.constructor-member-contexts':'members','scar.source-binding-native-graph':'native',
            'scar.source-resource-graph':'resources','scar.configuration-state-bindings':'configuration',
            'scar.source-observed-boundaries':'observed_boundaries',
            'scar.source-body-activations':'body_activations'}.get(schema)
        if key in ('observed_boundaries','body_activations'):
            basis=r['basis']
            if (trace is None or basis['trace']!=str(trace)
                    or Path(basis['catalog']['uri']).parent.resolve()!=c.path.resolve()):continue
            if key not in component_pins:
                if key=='body_activations':
                    from scar.analysis.source_body_activations import _pins
                else:
                    from scar.analysis.source_observed_boundaries import _pins
                component_pins[key]=_pins()
            if r.get('pins')!=component_pins[key]:
                gaps.append(dict(layer=key,kind='CACHED_COMPONENT_RULES_CHANGED',path=str(path)))
                continue
        if key and key not in components:
            components[key]=_receipt(path/'result.json')
    return dict(catalog=_receipt(c.path/'result.json'),entry_unit=unit,functions=functions,
        components=components,selection_gaps=gaps)


class _LazyState:
    def __init__(self,view):self.view=view
    def _query(self,point,incoming):
        source=self.view.namespaces.get(point.namespace)
        if source is None:return Neighborhood()
        provider=self.view.state(source.unit)
        provider.content()
        return (provider.incoming if incoming else provider.outgoing)(point)
    def incoming(self,point):return self._query(point,True)
    def outgoing(self,point):return self._query(point,False)


class F4BuildSession:
    def __init__(self,path,*,_publishing=False,seconds=3600,input_bytes=16*1024**3):
        from scar.analysis.build import _check,_rules
        from scar.analysis.source_declared_catalog import read_source_catalog
        from scar.analysis.program_view import ProgramView
        self._started=time.monotonic();self._seconds=seconds;self._input_bytes=input_bytes
        self.timings={};self._admitted={}
        self.path=Path(path).resolve();self.report=json.loads((self.path/'manifest.json').read_bytes())
        if self.report['backend']!='F4' or self.report['rules']!=_rules():raise ValueError('F4 build rules differ')
        if not _publishing and not self.report['workflow_complete']:raise ValueError('F4 build not published')
        for receipt in self.report['tables'].values():self._admit(receipt)
        spec=self.report['f4'];self._admit(spec['catalog'])
        self.catalog=read_source_catalog(Path(spec['catalog']['path']).parent)
        self._checkpoint('catalog')
        self.view=ProgramView(self.catalog);self.providers={};self.gaps=list(spec['selection_gaps'])
        self._claimed=set();self.closed=False;self.observed=None
        self.entry=self.view.entry(spec['entry_unit'],context=())
        self.entries=(self.entry,);self.session=self
        self._functions(spec['functions'])
        self._checkpoint('function_interfaces')
        self._components(spec['components'])
        self._checkpoint('cross_layer_interfaces')
        self.view.register(_LazyState(self.view))
        self.view.state(spec['entry_unit']).content()
        self._checkpoint('local_state_and_content')
        from scar.analysis.build_f4_resources import LazyF4Resources
        target=self.report.get('target')
        if target is not None:self._admit(target)
        target_path=None if target is None else Path(target['path']).parent
        try:
            self.resources=LazyF4Resources(self.view,self._component_path('resources'),target=target_path)
        except (OSError,ValueError) as error:
            self.gaps.append(dict(layer='resources',kind='RESOURCE_MATERIAL_NOT_JOINED',detail=str(error)))
            self.resources=LazyF4Resources(self.view,target=target_path)
        self.resources.demand(self.entry)
        self._checkpoint('resources')

    def _checkpoint(self,layer=None):
        elapsed=time.monotonic()-self._started
        if layer is not None:self.timings[layer]=elapsed
        if elapsed>self._seconds:raise TimeoutError('F4 assembly exceeded its cooperative time budget')
        if sum(r['bytes'] for r in self._admitted.values())>self._input_bytes:
            raise OverflowError('F4 direct publication receipts exceeded the input byte budget')

    def _admit(self,receipt):
        from scar.analysis.build import _check
        _check(receipt);self._admitted[receipt['path']]=receipt
        self._checkpoint()
        return Path(receipt['path']).parent

    def _component_path(self,name):
        r=self.report['f4']['components'].get(name)
        return self._admit(r) if r is not None else None

    def _functions(self,receipts):
        from scar.analysis.source_call_view import open_function_interfaces,SourceFunctionCallProvider
        for receipt in receipts:
            try:
                store=open_function_interfaces(self._admit(receipt))
                if (store.catalog.path,store.catalog.report)!=(self.catalog.path,self.catalog.report):continue
                units=frozenset(store.report['shards'])-self._claimed
                if not units:continue
                provider=SourceFunctionCallProvider(self.view,store)
                provider.available_units=units;self._claimed.update(units)
                self.providers['functions:'+str(store.path)]=provider
            except (OSError,ValueError) as error:
                self.gaps.append(dict(layer='calls',kind='INTERFACE_MATERIAL_REJECTED',path=receipt['path'],detail=str(error)))

    def _components(self,components):
        from scar.analysis.source_declared_catalog import DeclaredSourceCatalog
        if isinstance(self.catalog,DeclaredSourceCatalog):
            self.gaps.append(dict(layer='exec',kind='COMPILED_EXEC_SELECTION_NOT_PROVIDED',
                detail='Local source declarations do not select dynamically compiled exec roots.'))
        else:
            from scar.analysis.source_exec_view import SourceExecProvider
            self.providers['exec']=SourceExecProvider(self.view,self.catalog)
        for name in ('creations','native','protocol','configuration','observed_boundaries','body_activations'):
            try:
                path=self._component_path(name)
                if path is None:
                    self.gaps.append(dict(layer=name,kind='MATERIAL_NOT_AVAILABLE'));continue
                if name=='creations':
                    from scar.analysis.source_creation_view import SourceFunctionCreationProvider
                    provider=SourceFunctionCreationProvider(self.view,path)
                elif name=='native':
                    from scar.analysis.source_native_view import SourceNativeCallProvider
                    provider=SourceNativeCallProvider(self.view,path)
                elif name=='protocol':
                    from scar.analysis.source_protocol_materials import SourceProtocolMaterials
                    from scar.analysis.source_protocol_view import SourceProtocolCallProvider
                    materials=SourceProtocolMaterials(path,self.catalog,members=self._component_path('members'))
                    provider=SourceProtocolCallProvider(self.view,materials)
                elif name=='observed_boundaries':
                    from scar.analysis.source_observed_boundaries import BoundaryStore,SourceObservedBoundaryProvider
                    indices=[p.store.index for p in self.providers.values()
                        if getattr(getattr(p,'store',None),'report',{}).get('schema')=='scar.source-observed-function-interfaces']
                    provider=SourceObservedBoundaryProvider(self.view,BoundaryStore(path,index=indices[0] if indices else None))
                elif name=='body_activations':
                    from scar.analysis.source_body_activations import SourceBodyActivationStore
                    from scar.analysis.source_body_activation_view import SourceBodyActivationProvider
                    indices=[p.store.index for p in self.providers.values()
                        if getattr(getattr(p,'store',None),'report',{}).get('schema') in (
                            'scar.source-observed-function-interfaces','scar.source-observed-boundaries')]
                    store=SourceBodyActivationStore(path,index=indices[0] if indices else None)
                    provider=SourceBodyActivationProvider(self.view,store)
                    if not store.report['coverage']['entry_coverage_complete']:
                        self.gaps.append(dict(layer=name,kind='EXECUTED_ENTRIES_WITHOUT_SOURCE_BODY',
                            missing=store.report['coverage']['missing_entries']))
                else:
                    from scar.analysis.source_configuration_view import SourceConfigurationProvider
                    provider=SourceConfigurationProvider(self.view,path)
                self.providers[name]=provider
            except (OSError,ValueError) as error:
                self.gaps.append(dict(layer=name,kind='MATERIAL_NOT_JOINED',detail=str(error)))

    def attach_trace(self):
        """Actual F4 selections already admitted through their matched leaf."""
        if self.report['trace']:
            from scar.analysis.build import _check
            for receipt in self.report['trace']['inputs']:_check(receipt)
        observations=[];boundaries=[];activations=[]
        for p in self.providers.values():
            store=getattr(p,'store',None)
            if store is not None and store.report['schema']=='scar.source-observed-function-interfaces':
                observations.append(dict(path=str(store.path),counts=store.report['counts'],run_scope=store.report['run_scope']))
            if store is not None and store.report['schema']=='scar.source-observed-boundaries':
                store.validate()
                boundaries.append(dict(path=str(store.path),counts=store.report['counts'],run_scope=store.report['basis']['run_scope']))
            if store is not None and store.report['schema']=='scar.source-body-activations':
                store.check()
                activations.append(dict(path=str(store.path),coverage=store.report['coverage'],
                    run_scope=store.report['basis']['run_scope']))
        self.observed=dict(schema='scar.build-f4-observed-selections',publications=observations,
            boundaries=boundaries,body_activations=activations,runtime_events_replaced_by_static_frames=False)
        return self.observed

    def select(self,*,file=None,entry=None,kind=None):
        file=None if file is None else str(file)
        points=[]
        for unit,row in self.catalog.fact_store.rows.items():
            if file and not (row['path']==str(Path(file).absolute()) or row['path'].endswith('/'+file)):continue
            if unit in self.catalog.fact_store.original_source_units and not file:continue
            if not file and unit!=self.report['f4']['entry_unit']:continue
            facts=self.catalog.fact_store.load(unit)
            if entry is None and kind in (None,'MODULE'):
                points.append(self.view.entry(unit,context=() if unit==self.report['f4']['entry_unit'] else None))
            if entry is not None or kind in ('FUNCTION','ASYNC_FUNCTION'):
                from scar.analysis.static_query import _Fragments
                from scar.analysis.source_roles import SyntaxRoleView
                from scar.ir.program.source_syntax import SourceSyntaxMaterial
                from scar.ir.record_codec import decode
                original=self.catalog.fact_store.original_source_units.get(unit,unit)
                model=self.catalog.fact_store.model_units[original]
                syntax=decode(SourceSyntaxMaterial,_Fragments(self.catalog.fact_store.model_for(original)).read(model['artifacts']['source_syntax']))
                roles=SyntaxRoleView(syntax)
                for fn in facts.functions:
                    try:name=roles.field(fn.template.occurrence,'name').scalar.to_python()
                    except (KeyError,AttributeError):continue
                    if entry is None or name==entry or entry.endswith('.'+name):
                        points.append(self.view.source_region(unit,fn.template,fn.body))
        return tuple(dict.fromkeys(points))

    def point(self,*,file=None,entry=None,kind=None,node):
        points=self.select(file=file,entry=entry,kind=kind)
        namespaces=tuple(dict.fromkeys(p.namespace for p in points))
        if len(namespaces)!=1:raise ValueError('select one F4 source namespace for a node query')
        prefix,raw=node.split(':',1)
        cls=next((cls for cls in NODE_TYPES if cls.prefix==prefix),None)
        if cls is None:raise ValueError('unknown typed node prefix')
        point=Point(namespaces[0],cls(raw),None);self.view.get(point);return point

    def layer_summary(self):
        return dict(unified=True,local_state=dict(bindings=True,content=True),
            cross_layer=dict(functions=any(k.startswith('functions:') for k in self.providers),
                **{k:k in self.providers for k in ('exec','creations','native','protocol','configuration','observed_boundaries','body_activations')}),resources=True,
            storage=True,readback=True,providers=sorted(self.providers),
            loaded_units=len(self.view.units),catalog_units=len(self.catalog.fact_store.rows),
            body_copies=0,loops_unrolled=False)

    def readback_publication(self,report):
        """Read serialized outputs against the same admitted immutable inputs.

        Reopening a BuildSession remains the independent replay API. Publishing
        must not repeat that entire analysis: the stores already authenticated
        their source/trace relations, and retain guards for subsequent queries.
        """
        from scar.analysis.build import _check,_rules
        import gzip
        started=time.monotonic()
        if (json.loads((self.path/'manifest.json').read_bytes())!=report
                or report['rules']!=_rules()):
            raise ValueError('publication manifest or implementation changed')
        for receipt in (*self._admitted.values(),*report['tables'].values()):_check(receipt)
        spec=report['f4']
        relationships=dict(schema='scar.build-f4-relationships',catalog=spec['catalog'],
            function_leaves=spec['functions'],components=spec['components'],copied_bodies=0)
        if json.loads((self.path/'relationships.json').read_bytes())!=relationships:
            raise ValueError('stored relationship references differ from admitted components')
        canonical=lambda value:json.loads(json.dumps(value))
        if json.loads((self.path/'observed.json').read_bytes())!=canonical(self.attach_trace()):
            raise ValueError('stored execution evidence differs from admitted observations')
        with gzip.open(self.path/'resources.json.gz','rt') as stream:resources=json.load(stream)
        if resources!=canonical(self.resources.payload()):
            raise ValueError('stored resource interfaces differ from admitted resource ports')
        stores={id(p.store):p.store for p in self.providers.values() if hasattr(p,'store')}
        for store in stores.values():
            guard=getattr(store,'validate',None) or getattr(store,'check',None)
            if guard is not None:guard()
        self.view.expand(self.entry)
        for source in self.view.units.values():source.check()
        for receipt in (*self._admitted.values(),*report['tables'].values()):_check(receipt)
        if report['rules']!=_rules():raise ValueError('publication implementation changed during readback')
        self._checkpoint()
        return dict(mode='STORED_TABLES_WITH_ADMITTED_INDEX',
            output_tables=len(report['tables']),admitted_publications=len(self._admitted),
            entry_expanded=True,indices_reconstructed=0,independent_full_analysis_repeated=False,
            seconds=time.monotonic()-started)

    def close(self):
        if self.closed:return
        self.closed=True
        self.view.dependencies.providers.clear();self.view.units.clear();self.view.namespaces.clear()


def build_f4(entry,trace,out,spec,*,source_roots=(),max_points=128,max_seconds=3600,max_input_bytes=16*1024**3,target=None):
    from scar.analysis.build import _rules,_receipt,_write,_configuration_inputs
    from scar.analysis.program_dependency_export import export_dependency_walk
    started=time.monotonic();out.mkdir(parents=True)
    trace_ref=None
    if trace:
        from scar.analysis.program_observed_dependencies import _inputs
        trace_ref=dict(path=str(trace),inputs=[_receipt(p) for p in sorted(_inputs(trace))])
    report=dict(schema='scar.program-build',schema_version=1,backend='F4',entry=str(entry),rules=_rules(),
        f4=spec,model=None,trace=trace_ref,
        target=None if target is None else _receipt(Path(target)/'result.json'),
        tables={},workflow_complete=False,first_stage_complete=False,
        target_executed=False,original_body_bytes_copied=0,loops_unrolled=False,
        limits=dict(max_seconds=max_seconds,max_input_bytes=max_input_bytes,
            byte_scope='DIRECT_PUBLICATION_RECEIPTS',time_enforcement='COOPERATIVE_STAGE_BOUNDARIES'),
        entry_probe_limits=dict(max_points=max_points,max_edges=512,max_depth=8))
    _write(out/'manifest.json',report)
    gaps=[];configuration=_configuration_inputs((entry.parent,*(Path(p).resolve() for p in source_roots)),out,gaps)
    session=F4BuildSession(out,_publishing=True,seconds=max_seconds,input_bytes=max_input_bytes)
    try:
        observed=session.attach_trace();_write(out/'observed.json',observed)
        walk=session.view.dependencies.walk((session.entry,),direction='outgoing',include_structure=True,
            max_points=max_points,max_edges=512,max_depth=8)
        _write(out/'entry-query.json',export_dependency_walk(walk))
        gaps.extend(session.gaps)
        gaps.extend(session.resources.gaps)
        gaps.extend(dict(layer='query',kind=f.kind,detail=f.detail,point=encode(f.point)) for f in walk.frontiers)
        # Persist references to original relation shards, not expanded bodies.
        _write(out/'relationships.json',dict(schema='scar.build-f4-relationships',catalog=spec['catalog'],
            function_leaves=spec['functions'],components=spec['components'],copied_bodies=0))
        payload=session.resources.payload()
        import gzip
        (out/'resources.json.gz').write_bytes(gzip.compress(json.dumps(payload,separators=(',',':')).encode(),mtime=0))
        report['layers']=session.layer_summary()
        report['assembly_elapsed_by_layer']=session.timings
        report['observed_admission']='ADMITTED' if observed['publications'] or observed['boundaries'] or observed['body_activations'] else 'NOT_JOINED'
        report['summary']=dict(source_units=len(session.catalog.fact_store.rows),loaded_units=len(session.view.units),
            configuration_inputs=len(configuration),observed_publications=len(observed['publications']),
            observed_boundary_publications=len(observed['boundaries']),
            observed_body_activation_publications=len(observed['body_activations']),
            resource_records=len(session.resources.provider.records))
        return _finish_publication(session,report,gaps,started)
    finally:session.close()


def _finish_publication(session,report,gaps,started):
    from scar.analysis.build import _receipt,_write
    out=session.path
    gaps.append(dict(layer='coverage',kind='FULL_INFERENCE_COVERAGE_UNPROVEN',
        detail='All layers are composed; this bounded entry probe and configuration trace are not a full inference execution.'))
    _write(out/'gaps.json',dict(schema='scar.build-gaps',gaps=gaps,counts=dict(Counter(g['layer'] for g in gaps))))
    report['tables']={p.name:_receipt(p) for p in out.iterdir() if p.is_file() and p.name!='manifest.json'}
    report['summary']['gaps']=len(gaps)
    _write(out/'manifest.json',report)
    session._checkpoint()
    report['publication_readback']=session.readback_publication(report)
    report['seconds']=time.monotonic()-started
    report['workflow_complete']=True;_write(out/'manifest.json',report);return report
