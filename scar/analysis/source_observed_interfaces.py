"""Observed source-code selections augment retained conditional call interfaces.

Group repeated observations by original callsite and source definition. An
equivalent parent interface keeps its original frame/fact; only missing code
targets add an interface. Observations neither erase static alternatives nor
establish future dispatch, creator instances, cell contents or pure effects.
"""
import argparse
from collections import defaultdict
from dataclasses import replace
from hashlib import sha256
import json
import inspect
from contextlib import contextmanager
from bisect import bisect_right
from pathlib import Path

from scar.analysis.source_call_view import open_function_interfaces,function_interface_fact
from scar.analysis.source_function_connections import Invocation,connect
from scar.analysis.source_field_interfaces import _InterfaceOnly
from scar.analysis.source_world_returns import _table_ref
from scar.analysis.source_value_flow import _artifact
from scar.analysis.source_symbol_variants import _table
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
from scar.analysis.source_template_links import _json
from scar.analysis.source_declared_calls import _folder
from scar.analysis.source_consumer_parents import _stamp
from scar.ir.program import source_function_interfaces as I,normal_targets as T,source_productions as P
from scar.ir.program import source_observed_calls as R
from scar.ir.program.python_call_targets import PythonTargetKind
from scar.ir.program.call_edges import CallEdgeBudget
from scar.ir.record_codec import encode,decode
from scar.trace.code_snapshot import call_instruction


SCHEMA='scar.source-observed-function-interfaces'
TABLES=('groups','observation_frontiers','interfaces','queries','frontiers')
GUARDS=('OBSERVED_CODE_AND_IMMEDIATE_ENTRY_BELONG_TO_RECORDED_RUN_AND_ATTEMPTS',
    'CURRENT_CALLABLE_SELECTS_RECORDED_SOURCE_CODE_TEMPLATE_AND_CALL_PROTOCOL',
    'ORIGINAL_CALLER_CODE_AND_SOURCE_ARGUMENT_EVALUATION_PROTOCOL_MATCH',
    'EXEC_NAMESPACE_BRANCH_REMAINS_CONDITIONAL',
    'CREATOR_CELL_CONTENT_AND_BOUND_ARGUMENT_VERSIONS_NOT_PROVEN',
    'SOURCE_ARGUMENT_ABI_HAS_NO_ADDITIONAL_UNMODELED_RECEIVER',
    'NO_FUTURE_DISPATCH_OR_EFFECT_PURITY_AUTHORITY')


def _pins():
    from scar.analysis import source_observed_calls,source_observed_codes,source_compiled_code_profiles,source_observed_protocols
    from scar.analysis import source_function_connections,static_compilation,source_observed_materials,source_fact_materials
    from scar.ir.program import source_observed_codes as code_types
    return {**source_observed_codes.request_code_pins(),
        **{name:sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in (
        ('producer',__import__(__name__,fromlist=['__file__'])),('types',R),('interfaces',I),('connections',T),
        ('callsite',source_observed_calls),('protocol_calls',source_observed_protocols),
        ('code',source_observed_codes),('compiler',source_compiled_code_profiles),
        ('binder',source_function_connections),('code_mapping',static_compilation),
        ('fact_guard',source_observed_materials),('fact_routes',source_fact_materials),('code_types',code_types))}}


def _same_connection(interface,connection):
    link=interface.link
    return (interface.activation==connection.activation and link.source_callable==connection.source_callable
        and link.body==connection.body and link.parameters==connection.parameters and link.returns==connection.returns
        and link.argument_packs==connection.argument_packs and link.projections==connection.projections
        and link.binding==connection.binding and link.input_envelope==connection.input_envelope)


def _argument_prefixes(index,observation,call,function,*,receiver_known=False):
    """Reuse the existing observed binder's unknown-default layout rule.

    monitoring arg0 is the first argument, not a general extra-self flag:
    https://docs.python.org/3.14/library/sys.monitoring.html
    CALL's argc excludes its separate self-or-NULL stack slot:
    https://docs.python.org/3.14/library/dis.html#opcode-CALL
    """
    if call.positional_pack is not None or call.keyword_pack is not None:return ()
    caller=index.caller_for(observation)
    instruction=call_instruction(caller.code,observation.attempt.site.offset)
    if instruction is None:return ()
    opcode,count=instruction
    if observation.rule=='DECORATOR_AFTER_DECLARED_CODE_CONSTANT':
        if receiver_known:return ()
        if opcode!='CALL' or count!=0 or len(call.positional)!=1 or call.keywords or observation.attempt.arg0_missing:return ()
        entries=[e for r in index.codes.records.values() for _,e in r.entries
            if e.caller==observation.target.caller and e.attempt_index==observation.target.attempt_index]
        frames={f.invocation:f for f in index.codes.trace.entries}
        if len(entries)!=1:return ()
        frame=frames[entries[0].callee]
        if (not frame.parameters or not observation.attempt.arg0.startswith('weak:')
                or frame.parameters[0].ref!=observation.attempt.arg0):return ()
        # The original source protocol already includes this payload argument.
        return (0,)
    if opcode not in ('CALL','CALL_KW') or count!=len(call.positional)+len(call.keywords):return ()
    unknown=object()
    signature=inspect.Signature(tuple(inspect.Parameter(name,getattr(inspect.Parameter,p.kind.value),
        default=inspect.Parameter.empty if p.kind in (P.DeferredParameterKind.VAR_POSITIONAL,P.DeferredParameterKind.VAR_KEYWORD)
            else unknown) for p,name in zip(function.environment.parameters,function.parameter_names)))
    positional=tuple(object() for _ in call.positional);keywords={name:object() for name,_ in call.keywords}
    prefixes=[]
    for prefix in ((1,) if receiver_known else (0,) if observation.attempt.arg0_missing else (0,1)):
        try:signature.bind(*((unknown,) if prefix else ()),*positional,**keywords)
        except TypeError:continue
        prefixes.append(prefix)
    return tuple(prefixes)


def _receiver_base(facts,callee):
    """Original attribute-base candidate; descriptor equality stays guarded.

    No callable reference is reused as self. A dynamic descriptor may bind
    another receiver, so this source path alone never proves its identity.
    """
    from scar.analysis.source_field_interfaces import _ancestors
    from scar.ir.program.normal_links import AttributeAction
    incoming=defaultdict(list)
    for source,target in facts.aliases:incoming[target].append(source)
    values=_ancestors(incoming,callee)
    bases={a.receiver for a in facts.attributes if a.action is AttributeAction.GET and a.value in values}
    return next(iter(bases)) if len(bases)==1 else None


def _body_connection(mini,unit,function,invocation):
    """Retain a witnessed body when explicit argument routing is unresolved.

    Code/entry correspondence is independent of self/default/pack contents.
    Original data formals retain a conservative pre-call input envelope;
    their exact argument/receiver/default binding remains unmodeled.
    """
    offset=mini.offsets[unit.unit];gp=mini.gp
    if len(function.formals)!=len(function.environment.parameters)+2:
        raise ValueError('observed function body lacks its original environment/world ABI')
    activation=(T.FunctionActivation.NORMAL if function.environment.kind is P.DeferredBodyKind.FUNCTION
        else T.FunctionActivation.CREATE_DEFERRED_BODY)
    routes=(T.Route(gp(offset+function.formals[0]),T.RouteKind.FUNCTION_ENVIRONMENT,(gp(invocation.callee),)),
        T.Route(gp(offset+function.formals[-1]),T.RouteKind.STATE,(gp(invocation.world),)))
    returned=[]
    envelope=None
    if activation is T.FunctionActivation.NORMAL:
        envelope=T.CallInputEnvelope(gp(invocation.callee),tuple(gp(p) for p in invocation.positional),
            tuple((name,gp(p)) for name,p in invocation.keywords),
            None if invocation.positional_pack is None else gp(invocation.positional_pack),
            None if invocation.keyword_pack is None else gp(invocation.keyword_pack),gp(invocation.world),
            tuple(gp(offset+p) for p in function.formals[1:-1]))
        if invocation.result is not None and function.returns is not None:
            returned.append((gp(offset+function.returns),gp(invocation.result)))
        if function.return_world is not None:returned.append((gp(offset+function.return_world),gp(invocation.result_world)))
    return T.FunctionConnection(gp(offset+function.value),T.Body(unit.unit,function.template,function.body),
        activation,routes,tuple(returned),(*tuple(c for c in GUARDS
            if c!='SOURCE_ARGUMENT_ABI_HAS_NO_ADDITIONAL_UNMODELED_RECEIVER'),
            'EXPLICIT_ARGUMENT_RECEIVER_AND_DEFAULT_BINDING_NOT_MODELED'),
        binding=T.ArgumentBinding.NOT_MODELED,input_envelope=envelope)


def _body_entry_windows(index):
    """Index original direct frames inside each caller's actual CALL interval.

    This does not recover a receiver token. Different iterations of the same
    callsite cannot borrow each other's entries; callbacks without the exact
    captured target code and one-step caller path cannot satisfy the query.
    """
    prior=getattr(index,'_body_entry_windows',None)
    if prior is not None:return prior
    frames=defaultdict(list);limits={};last={}
    for attempt in index.codes.trace.attempts:
        previous=last.get(attempt.invocation)
        if previous is not None:limits[previous]=attempt.frame_index
        last[attempt.invocation]=(attempt.process_id,attempt.index)
    for frame in index.codes.trace.entries:
        if (frame.suspended or not frame.path_complete or len(frame.path)!=1
                or frame.caller_invocation is None or frame.caller!=frame.path[0]):continue
        frames[frame.caller_invocation,frame.code,frame.caller].append(frame)
    rows={key:(tuple(f.anchor.index for f in sorted(values,key=lambda f:f.anchor.index)),
               tuple(sorted(values,key=lambda f:f.anchor.index))) for key,values in frames.items()}
    index._body_entry_windows=rows,limits
    return rows,limits


def _body_entry(index,observation):
    rows,limits=_body_entry_windows(index)
    positions,frames=rows.get((observation.target.caller,observation.target.code,
        observation.attempt.site),((),()))
    start=bisect_right(positions,observation.attempt.frame_index)
    end=limits.get((observation.attempt.process_id,observation.attempt.index))
    stop=len(positions) if end is None else bisect_right(positions,end)
    return frames[start] if stop-start==1 else None


@contextmanager
def _parent_unit(parent,unit):
    """One checked immutable parent graph per projection, with file guards.

    Collection readers without a direct shard keep their ordinary load path.
    Nothing is cached across units or independent verification sessions.
    """
    shard=parent.report.get('shards',{}).get(unit)
    if not isinstance(shard,dict) or not {'path','tables'}<=shard.keys():
        yield None
        return
    paths=tuple(parent.path/shard['path']/table['path'] for table in shard['tables'].values())
    before={path:_stamp(path) for path in paths}
    graph=parent.load_unit(unit)
    def check():
        parent.validate()
        if any(_stamp(path)!=stamp for path,stamp in before.items()):
            raise ValueError('parent interface shard changed during observed projection')
    check()
    try:
        yield graph
    finally:
        check()


def _groups(parent,index,unit,*,original=None):
    if original is None:original=parent.load_unit(unit)
    facts=parent.catalog.fact_store.load(unit)
    by_code=defaultdict(list)
    for code in index.codes.records.values():
        by_code[code.captures[0].code.key].append(code)
    entries_by_code={code.id:{(e.caller,e.attempt_index):e for _,e in code.entries}
        for rows in by_code.values() for code in rows}
    frames={frame.invocation:frame for frame in index.codes.trace.entries}
    from scar.analysis.observed_function_interfaces import _known_receiver
    grouped=defaultdict(list);frontiers=[];selected={};body_entries={}
    for observation in index.bindings:
        if observation.unit!=unit:continue
        target=observation.target
        if target.kind not in (PythonTargetKind.FUNCTION,PythonTargetKind.BOUND_METHOD,PythonTargetKind.NORMALIZED_RECEIVER_FUNCTION):
            frontiers.append(R.ObservedSourceFunctionFrontier(observation,'OBSERVED_CALLABLE_REQUIRES_OTHER_CALL_PROTOCOL'));continue
        candidates=by_code.get(target.code,())
        if not candidates:
            frontiers.append(R.ObservedSourceFunctionFrontier(observation,'OBSERVED_TARGET_CODE_HAS_NO_RETAINED_SOURCE_BODY_CORRESPONDENCE'));continue
        for code in candidates:
            entry=entries_by_code[code.id].get((target.caller,target.attempt_index))
            if entry is None:
                frame=_body_entry(index,observation)
                if frame is None:
                    frontiers.append(R.ObservedSourceFunctionFrontier(observation,'OBSERVED_CALL_HAS_NO_MATCHED_IMMEDIATE_PYTHON_ENTRY'));continue
                # A missing weak receiver witness must not erase a witnessed
                # body. Only the world/environment/return interfaces are safe
                # until argument layout is independently established below.
                known=False
                frontiers.append(R.ObservedSourceFunctionFrontier(observation,
                    'OBSERVED_BODY_ENTRY_RETAINED_RECEIVER_IDENTITY_OPEN'))
            else:
                frame=frames[entry.callee]
                known=_known_receiver(target,entry)
            if known:
                frame=frames[entry.callee]
                if (not frame.parameters_complete or not frame.parameters or entry.receiver_reference.startswith('weak:')
                        and frame.parameters[0].ref!=entry.receiver_reference):
                    frontiers.append(R.ObservedSourceFunctionFrontier(observation,'OBSERVED_RECEIVER_FIRST_FORMAL_IDENTITY_NOT_RETAINED'));continue
            key=observation.query,code.function_fact,known
            grouped[key].append(observation);selected[key]=code
            body_entries[observation.id,code.id]=frame.anchor
    groups=[]
    for key,observations in grouped.items():
        query,_,receiver_known=key;code=selected[key];call=facts.calls[query];offset=parent.catalog.fact_store.offsets[unit]
        if any(o.call!=index.slicer.fact(facts,'calls',query) or o.owner.owner not in original.queries[query].owners
               for o in observations):raise ValueError('observed group differs from original call/scope')
        fn_unit,local=index.slicer.local(code.function)
        function=next(f for f in fn_unit.functions if f.value==local)
        if T.Body(fn_unit.unit,function.template,function.body)!=code.body or function.body_scope!=code.scope:
            raise ValueError('observed function code differs from original source body/scope')
        mini=_InterfaceOnly(index.slicer,fn_unit,function)
        invocation=Invocation(offset+call.callee,tuple(offset+x for x in call.positional),
            tuple((n,offset+x) for n,x in call.keywords),offset+call.result,offset+call.world,offset+call.result_world,
            None if call.positional_pack is None else offset+call.positional_pack,
            None if call.keyword_pack is None else offset+call.keyword_pack)
        receiver=_receiver_base(facts,call.callee) if receiver_known else None
        if receiver_known and receiver is None:
            frontiers.extend(R.ObservedSourceFunctionFrontier(o,'OBSERVED_BOUND_RECEIVER_HAS_NO_UNIQUE_SOURCE_ATTRIBUTE_BASE') for o in observations)
        guards=GUARDS if not receiver_known else (*tuple(c for c in GUARDS
            if c!='SOURCE_ARGUMENT_ABI_HAS_NO_ADDITIONAL_UNMODELED_RECEIVER'),
            'OBSERVED_BOUND_RECEIVER_SUPPLIES_FIRST_FORMAL',
            'SELECTED_BOUND_RECEIVER_IS_ORIGINAL_ATTRIBUTE_BASE',
            'ATTRIBUTE_BASE_CONTENT_AND_DESCRIPTOR_RECEIVER_IDENTITY_NOT_PROVEN')
        connection=(None if receiver_known and receiver is None else
            connect(mini,mini.offsets[fn_unit.unit]+function.value,invocation,
                None if receiver is None else offset+receiver,conditions=guards))
        if connection is None:
            frontiers.extend(R.ObservedSourceFunctionFrontier(o,'OBSERVED_CODE_REQUIRES_DIFFERENT_SOURCE_ARGUMENT_OR_DESCRIPTOR_BINDING') for o in observations)
        alternatives=tuple(_argument_prefixes(index,o,call,function,receiver_known=receiver_known) for o in observations)
        expected=(1,) if receiver_known else (0,)
        proven=connection is not None and all(p==expected for p in alternatives)
        if not proven:
            frontiers.extend(R.ObservedSourceFunctionFrontier(o,'OBSERVED_SOURCE_ARGUMENT_OR_IMPLICIT_RECEIVER_LAYOUT_OPEN')
                for o,prefixes in zip(observations,alternatives) if prefixes!=expected)
        if receiver_known:
            frontiers.extend(R.ObservedSourceFunctionFrontier(o,'OBSERVED_BOUND_RECEIVER_SOURCE_IDENTITY_REMAINS_CONDITIONAL') for o in observations)
        if not proven:connection=_body_connection(mini,fn_unit,function,invocation)
        matches=tuple(i for i,f in enumerate(original.interfaces) if f.query==query and _same_connection(f,connection))
        groups.append(R.ObservedSourceFunctionGroup(query,code,tuple(observations),connection,matches,
            tuple(sorted({p for choices in alternatives for p in choices})),proven,
            tuple(body_entries[o.id,code.id] for o in observations)))
    return tuple(groups),tuple(frontiers)


def _overlay(parent,unit,groups,frontiers,folder,receipt,*,base=None):
    graph=parent.load_unit(unit) if base is None else base
    interfaces=list(graph.interfaces);queries=list(graph.queries);fs=list(graph.frontiers)
    for i,group in enumerate(groups):
        if group.parent_interfaces:continue
        c=group.connection;query=group.query;call=group.observations[0].call
        reference=_table_ref(folder,receipt,'scar.observed-source-function-group',i)
        original=parent.catalog.fact_store.load(unit).calls[query]
        from scar.analysis.source_reference_slice import source_port
        facts=parent.catalog.fact_store.load(unit)
        link=c.to_link(source_port(facts,original.result),source_port(facts,original.callee),
            'SOURCE_FUNCTION' if c.activation is T.FunctionActivation.NORMAL else 'CREATE_DEFERRED_BODY')
        queries[query]=replace(queries[query],interfaces=(*queries[query].interfaces,len(interfaces)))
        interfaces.append(I.SourceFunctionInterface(query,i,call,group.code.function_fact,reference,c.activation,link))
    for frontier in frontiers:
        fs.append(I.SourceFunctionInterfaceFrontier(frontier.observation.query,None,frontier.observation.call,frontier.reason))
    return replace(graph,interfaces=tuple(interfaces),queries=tuple(queries),frontiers=tuple(fs))


def _counts(graph,base,groups,frontiers):
    return dict(calls=graph.calls,interfaces=len(graph.interfaces),parent_interfaces=len(base.interfaces),
        derived_interfaces=len(graph.interfaces)-len(base.interfaces),observed_groups=len(groups),
        body_only_groups=sum(g.connection.binding is T.ArgumentBinding.NOT_MODELED for g in groups),
        annotated_parent_groups=sum(bool(g.parent_interfaces) for g in groups),observation_frontiers=len(frontiers))


def build_observed_interfaces(parent,index,out):
    parent=open_function_interfaces(parent)
    if (parent.catalog.path,parent.catalog.report)!=(index.view.catalog.path,index.view.catalog.report):
        raise ValueError('observations and interface parent use different original catalogs')
    out=Path(out).absolute()
    if out.exists():raise ValueError('fresh observed interface output required')
    _durable_mkdir(out);shards={};pins=_pins()
    observed_units={o.unit for o in index.bindings}
    selected=tuple(sorted(observed_units & parent.report['shards'].keys()))
    for unit in selected:
        with _parent_unit(parent,unit) as base:
            groups,frontiers=_groups(parent,index,unit,original=base)
            folder=out/_folder(unit);_durable_mkdir(folder)
            tables={'groups':write_table(folder/'groups.jsonl.gz',groups),
                'observation_frontiers':write_table(folder/'observation_frontiers.jsonl.gz',frontiers)}
            graph=_overlay(parent,unit,groups,frontiers,folder,tables['groups'],base=base)
            tables.update({n:write_table(folder/(n+'.jsonl.gz'),getattr(graph,n)) for n in ('interfaces','queries','frontiers')})
            original=parent.load_unit(unit) if base is None else base
            shards[unit]=dict(path=_folder(unit),tables=tables,counts=_counts(graph,original,groups,frontiers))
    parent.validate();index.check()
    if pins!=_pins():raise ValueError('observed interface rules changed')
    report=dict(schema=SCHEMA,schema_version=2,parent_path=str(parent.path),
        parent=encode(_artifact(parent.path/'result.json',parent.report['schema'])),catalog=str(parent.catalog.path),
        trace=index.codes.trace.directory,project_root=index.codes.trace.project_root,run_scope=index.codes.targets.source_sha256,
        code_units=sorted(index.codes._sources),compiled_units=[p.unit for p in index.compiled],
        target_reader_budget=index.codes.target_reader_budget,
        frame_reader_budget=encode(index.codes.trace.frame_budget),
        selection=dict(mode='OBSERVED_CALLER_UNITS',units=list(selected),
            callers_without_parent=sorted(observed_units-parent.report['shards'].keys())),
        pins=pins,shards=shards,counts={k:sum(s['counts'][k] for s in shards.values()) for k in
            ('calls','interfaces','parent_interfaces','derived_interfaces','observed_groups','body_only_groups','annotated_parent_groups','observation_frontiers')},
        origin_domain='ORIGINAL_OBSERVED_FUNCTION_GROUP_RECORDS_NOT_NAMESPACE_ORIGIN_ORDINALS',
        source_bodies_copied=False,loops_unrolled=False,future_dispatch_proven=False,
        creator_instances_proven=False,cell_contents_proven=False,first_stage_complete=False)
    _durable_bytes(out/'result.json',_json(report),replace=False);return report


class ObservedFunctionInterfaceStore:
    def __init__(self,path):
        self.path=Path(path).absolute();self.raw=(self.path/'result.json').read_bytes();self.report=r=json.loads(self.raw)
        if (r['schema'],r['schema_version'],r['pins'])!=(SCHEMA,2,_pins()):raise ValueError('observed interface schema or rules differ')
        self.parent=open_function_interfaces(r['parent_path']);self.catalog=self.parent.catalog
        from scar.analysis.program_view import ProgramView
        from scar.analysis.source_observed_codes import ObservedSourceCodeProvider
        from scar.analysis.source_compiled_code_profiles import CompiledCodeProfiles
        from scar.analysis.source_observed_calls import ObservedSourceCallsiteIndex
        view=ProgramView(self.catalog)
        profiles=tuple(CompiledCodeProfiles(self.catalog,u) for u in r['compiled_units'])
        codes=ObservedSourceCodeProvider(view,r['trace'],r['project_root'],units=r['code_units'],
            compiled=profiles,frame_budget=decode(CallEdgeBudget,r.get('frame_reader_budget',encode(CallEdgeBudget()))),
            **r.get('target_reader_budget',{}))
        self.index=ObservedSourceCallsiteIndex(codes,compiled=profiles)
        observed_units={o.unit for o in self.index.bindings}
        expected_units=tuple(sorted(observed_units & self.parent.report['shards'].keys()))
        expected_selection=dict(mode='OBSERVED_CALLER_UNITS',units=list(expected_units),
            callers_without_parent=sorted(observed_units-self.parent.report['shards'].keys()))
        if (codes.targets.source_sha256!=r['run_scope'] or str(self.catalog.path)!=r['catalog']
                or encode(_artifact(self.parent.path/'result.json',self.parent.report['schema']))!=r['parent']
                or tuple(r['shards'])!=expected_units or r.get('selection')!=expected_selection
                or any(r[n] is not False for n in ('source_bodies_copied','loops_unrolled','future_dispatch_proven',
                    'creator_instances_proven','cell_contents_proven','first_stage_complete'))):
            raise ValueError('observed interface parents, scope or proof flags differ')
        totals={k:sum(s['counts'][k] for s in r['shards'].values()) for k in r['counts']}
        if (r['counts']!=totals or r['origin_domain']!='ORIGINAL_OBSERVED_FUNCTION_GROUP_RECORDS_NOT_NAMESPACE_ORIGIN_ORDINALS'):
            raise ValueError('observed coverage or origin domain differs')
        self._cache={};self._loaded={};self.validate()

    def validate(self):
        if (self.raw!=(self.path/'result.json').read_bytes() or self.report['pins']!=_pins()
                or any(_stamp(path)!=stamp for path,stamp in self._loaded.items())):
            raise ValueError('observed interface material or rules changed')
        self.parent.validate();self.index.check()

    def read_unit(self,unit):
        self.validate()
        if unit not in self._cache:
            s=self.report['shards'][unit];folder=self.path/s['path']
            if s['path']!=_folder(unit) or set(s['tables'])!=set(TABLES):raise ValueError('observed unit layout differs')
            def rows(n,kind):
                if s['tables'][n]['path']!=n+'.jsonl.gz':raise ValueError('observed table path differs')
                path=folder/s['tables'][n]['path'];stamp=_stamp(path)
                result=tuple(decode(kind,w,record_tags=P.PRODUCTION_RECORD_TAGS) for w in _table(folder,s['tables'][n]))
                if _stamp(path)!=stamp:raise ValueError('observed table changed while reading')
                self._loaded[path]=stamp;return result
            with _parent_unit(self.parent,unit) as base:
                groups=rows('groups',R.ObservedSourceFunctionGroup);frontiers=rows('observation_frontiers',R.ObservedSourceFunctionFrontier)
                expected=_groups(self.parent,self.index,unit,original=base)
                if (groups,frontiers)!=expected:raise ValueError('observed groups differ from original trace and call binder')
                graph=_overlay(self.parent,unit,groups,frontiers,folder,s['tables']['groups'],base=base)
                original=self.parent.load_unit(unit) if base is None else base
                if (graph.interfaces!=rows('interfaces',I.SourceFunctionInterface) or graph.queries!=rows('queries',I.SourceFunctionInterfaceQuery)
                        or graph.frontiers!=rows('frontiers',I.SourceFunctionInterfaceFrontier)
                        or s['counts']!=_counts(graph,original,groups,frontiers)):
                    raise ValueError('observed interfaces differ from original records')
            self._cache[unit]=graph
        self.validate();return self._cache[unit]

    def load_unit(self,unit):return self.read_unit(unit)

    def load_declarations(self,unit):
        getter=getattr(self.parent,'load_declarations',None)
        return getter(unit) if callable(getter) else self.parent.parents.calls.load_unit(unit)

    def interface_fact(self,unit,i):
        self.validate();s=self.report['shards'][unit]
        if type(i) is not int or not 0<=i<s['counts']['interfaces']:raise ValueError('observed interface ordinal outside original unit')
        if i<s['counts']['parent_interfaces']:return function_interface_fact(self.parent,unit,i)
        return _table_ref(self.path/s['path'],s['tables']['interfaces'],'scar.source-function-interface-record',i)

    def callable_provenance(self,unit,i):
        self.interface_fact(unit,i)
        if i<self.report['shards'][unit]['counts']['parent_interfaces']:
            getter=getattr(self.parent,'callable_provenance',None)
            return getter(unit,i) if callable(getter) else None
        return None

    def provenance_locator(self,unit,i):
        self.interface_fact(unit,i)
        if i<self.report['shards'][unit]['counts']['parent_interfaces']:
            getter=getattr(self.parent,'provenance_locator',None)
            return getter(unit,i) if callable(getter) else None
        return None


def main():
    import sys
    from scar.analysis.source_declared_calls import _NoTargets,_check_targets
    sys.meta_path.insert(0,_NoTargets());parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent');parser.add_argument('--trace');parser.add_argument('--project-root')
    parser.add_argument('--unit',action='append',default=[]);parser.add_argument('--compiled-unit',action='append',default=[])
    parser.add_argument('--target-max-bytes',type=int,default=32_000_000)
    parser.add_argument('--target-max-rows',type=int,default=100_000)
    parser.add_argument('--frame-max-events',type=int,default=100_000)
    parser.add_argument('--out');parser.add_argument('--read')
    parser.add_argument('--boundaries-out',help='also connect non-Python CALL interfaces using this same checked trace index')
    parser.add_argument('--activations-out',help='join every recorded body entry, including root/class/resume protocols')
    parser.add_argument('--graph-check-out',help='verify saved body graph with this same admitted index')
    args=parser.parse_args()
    if args.read:
        store=ObservedFunctionInterfaceStore(args.read)
        for unit in store.report['shards']:store.read_unit(unit)
        report=store.report
        index=store.index
    else:
        if not all((args.parent,args.trace,args.project_root,args.out)):parser.error('--parent --trace --project-root --out required')
        parent=open_function_interfaces(args.parent)
        from scar.analysis.program_view import ProgramView
        from scar.analysis.source_observed_codes import ObservedSourceCodeProvider
        from scar.analysis.source_compiled_code_profiles import CompiledCodeProfiles
        from scar.analysis.source_observed_calls import ObservedSourceCallsiteIndex
        profiles=tuple(CompiledCodeProfiles(parent.catalog,u) for u in args.compiled_unit)
        view=ProgramView(parent.catalog);codes=ObservedSourceCodeProvider(view,args.trace,args.project_root,
            units=args.unit,compiled=profiles,target_max_bytes=args.target_max_bytes,target_max_rows=args.target_max_rows,
            frame_budget=replace(CallEdgeBudget(),max_events=args.frame_max_events))
        index=ObservedSourceCallsiteIndex(codes,compiled=profiles)
        report=build_observed_interfaces(parent,index,args.out)
    if args.boundaries_out:
        from scar.analysis.source_observed_boundaries import build_boundaries
        build_boundaries(index,args.boundaries_out)
    if args.activations_out:
        from scar.analysis.source_body_activations import build_body_activations
        build_body_activations(index,args.activations_out)
        if args.graph_check_out:
            from scar.analysis.source_body_activation_view import verify_body_activations
            verify_body_activations(args.activations_out,args.graph_check_out,index=index)
    _check_targets();print(json.dumps(report['counts']),flush=True)


if __name__=='__main__':main()
