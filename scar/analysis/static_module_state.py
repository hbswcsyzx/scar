"""Compose conditional ReadAt/WriteAt through original G/state interfaces.

The callable's reference-source point selects a factory/owner. The namespace
contents are queried at the real CALL input world, not at that earlier point.
All output is relationship witnesses over original graphs; no target executes.
"""
from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace

from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.model import StateVersionValue, TerminatorKind, UseRole
from scar.ir.program.static_calls import (
    NamespacePathStart, StaticCallContext, StaticCallFrontier,
    StaticFunctionOwnerRoute, StaticModuleGlobalsFlow, StaticModuleNamespaceAtCall,
    StaticNamespacePathSegment, StaticReferencePoint,
    ModuleFlowCondition,MODULE_FLOW_BASE_CONDITIONS,MODULE_IMPORT_INITIALIZER_CONDITIONS,
)
from scar.analysis.static_module_attributes import (_need,validate_reference_source_path,
    _import_initializer_bindings,_uses_import_initializer_contract)


def _context(route):
    return StaticCallContext(route.caller,route.call_operation,route.callee_use,
        route.callee_value,route.creation.definition,route.callee)


def _factory_path(path,route):
    first,last=path.points[0],path.points[-1]
    return (first.body==route.caller and first.value==route.callee_value
        and last.body==route.creation_body and last.value==route.creation.normal_value)


def _segment(body,witness,owner,dependencies):
    from scar.analysis.static_crossbody_namespace import _guard_entry_path
    witness=_guard_entry_path(dependencies,witness,owner)
    return StaticNamespacePathSegment(body.namespace,NamespacePathStart.ENTRY,witness.entry,None,
        owner,witness.query_operation,witness.query_owner,witness.query_world,witness.key,
        witness.path,witness.intervening_operations,witness.conditions)


class ModuleGlobalsDependencies:
    """Demand-driven address/state projection with explicit owner contexts.

    ``incoming(point)`` supplies only activated original G interfaces matching
    that point's context. Owner routes may compose through nested creators;
    a repeated factory never supplies its own provenance.
    """
    def __init__(self,*,modules,incoming=None,max_depth=64,max_facts=262144,
                 external_fact_count=None,check=None,initializer_contract=None):
        self.modules=modules;self.incoming=incoming or(lambda point:())
        self.max_depth=max_depth;self.max_facts=max_facts
        self.external_fact_count=external_fact_count or(lambda:0)
        self.check=check or(lambda:None)
        _need(initializer_contract is None or type(initializer_contract)is bool,'initializer contract must be explicit or inherited')
        self.initializer_contract=initializer_contract
        self.flows=defaultdict(dict);self.frontiers=defaultdict(dict)
        self._demands={};self._active=set();self._stack=[]
        self._flow_counts={};self._fact_count=0;self.revision=0
        self._demand_frontiers={};self._pending_frontiers={};self._frontier_counts={}

    @property
    def fact_count(self):return self._fact_count

    def _note(self,body,kind,detail,*,demand=None):
        row=StaticCallFrontier(kind,detail,body.source)
        token=demand if demand is not None else self._stack[-1]if self._stack else None
        item=body,row
        if token in self._pending_frontiers:self._pending_frontiers[token][item]=item
        elif token is not None:
            previous=dict.fromkeys(self._demand_frontiers.get(token,()))
            previous[item]=None;self._replace_frontiers(token,tuple(previous))
        else:
            # Only notes outside a qualified read demand are permanent.
            self.frontiers[body][row]=row

    def _replace_frontiers(self,token,items):
        previous=set(self._demand_frontiers.get(token,()));current=set(items)
        for item in previous-current:
            count=self._frontier_counts[item]-1
            if count:self._frontier_counts[item]=count
            else:
                del self._frontier_counts[item];self.frontiers[item[0]].pop(item[1],None)
        for item in current-previous:
            self._frontier_counts[item]=self._frontier_counts.get(item,0)+1
            self.frontiers[item[0]][item[1]]=item[1]
        self._demand_frontiers[token]=tuple(items)

    def _replace_demand(self,token,flows):
        previous=set(self._demands.get(token,()));current=set(flows)
        added=current-previous;removed=previous-current
        extra=sum(flow not in self._flow_counts for flow in added)
        released=sum(self._flow_counts[flow]==1 for flow in removed)
        if self._fact_count+extra-released+self.external_fact_count()>self.max_facts:
            raise OverflowError('shared module globals relationship budget exhausted')
        for flow in removed:
            count=self._flow_counts[flow]-1
            if count:self._flow_counts[flow]=count
            else:
                del self._flow_counts[flow];self.flows[flow.read.body].pop(flow,None);self._fact_count-=1
        for flow in added:
            if flow not in self._flow_counts:
                self._fact_count+=1;self.flows[flow.read.body][flow]=flow
            self._flow_counts[flow]=self._flow_counts.get(flow,0)+1
        self._demands[token]=tuple(flows)
        if previous!=current:self.revision+=1

    def _factory_sources(self,route,requirements,requester=None):
        caller=self.modules._body(route.caller)
        for current,path in self.modules.walk(caller,route.callee_value,requirements,requester):
            self.check()
            if _factory_path(path,route):yield path

    def _owner_origins(self,point,seen=()):
        self.check()
        if point in seen:
            self._note(point.body,'RECURSIVE_GLOBALS_OWNER_CONTEXT_OPEN',
                'A repeated owner/context cannot establish its own source module.')
            return
        if len(seen)>=self.max_depth:
            self._note(point.body,'GLOBALS_OWNER_CONTEXT_DEPTH_BUDGET',
                'Nested creator owner routing reached its explicit finite context depth budget.')
            return
        body=self.modules._body(point.body);facts=self.modules._index(body)
        if facts.module is not None and len(body.graph.frame_roots)==1:
            if body.graph.frame_roots[0].entry.globals_namespace==point.value:
                yield point,()
            return
        found=False
        for activation in self.incoming(point):
            route=activation.environment
            if route.member.reference!=point.value:continue
            expected=(*activation.requirements,activation.context)
            if point.requirements and point.requirements!=expected:continue
            for path in self._factory_sources(route,activation.requirements):
                source=StaticReferencePoint(route.creation_body,route.source_value,path.points[-1].requirements)
                step=StaticFunctionOwnerRoute(route,path)
                for origin,steps in self._owner_origins(source,(*seen,point)):
                    found=True;yield origin,(step,*steps)
        if not found:
            self._note(point.body,'GLOBALS_OWNER_ORIGIN_OPEN',
                'Original globals reference is retained; no selected, context-matching creator route yet reaches a source module.')

    @staticmethod
    def _modules_in_paths(paths):
        result={}
        for path in paths:
            for flow in path.module_attribute_flows:result[flow.module]=flow.module
            for flow in path.module_globals_flows:result[flow.projection.module]=flow.projection.module
        return tuple(result.values())

    def projections(self,activation,key,requester=None):
        route=activation.environment;caller=self.modules._body(route.caller)
        facts=self.modules._index(caller)
        for callable_path in self._factory_sources(route,activation.requirements,requester):
            source=StaticReferencePoint(route.creation_body,route.source_value,callable_path.points[-1].requirements)
            for origin,owner_routes in self._owner_origins(source):
                all_paths=(callable_path,*(s.callable_source for s in owner_routes))
                for module_route in self._modules_in_paths(all_paths):
                    if (module_route.module_body!=origin.body or module_route.globals_namespace!=origin.value):continue
                    writes=self.modules.write_routes_at(caller,key,module_route,activation.requirements,requester)
                    kills={w.operation for w,p in writes}
                    common=dict(environment=route,state_entry=activation.state_entry,callable_source=callable_path,
                        owner_routes=owner_routes,module=module_route,key=key,
                        overwrites=tuple(w for w,p in writes),overwrite_receiver_paths=tuple(p for w,p in writes))
                    for write,write_path in writes:
                        start=caller.index.operations[write.operation].terminator.successors[write.normal.successor_index].block
                        path=facts.paths.find_path(start,route.call_operation,key,kills)
                        if path is None:continue
                        yield StaticModuleNamespaceAtCall(**common,source_body=caller.namespace,
                            source_operation=write.operation,source_owner=write.receiver,source_payload=write.assigned,
                            source_world=write.world,source_normal=write.normal,
                            source_value=caller.index.use_site(write.assigned).use.value,source_key=None,
                            snapshot_operation=route.call_operation,snapshot_world=route.call_world,
                            source_path=(),source_operations=(),consumer_path=path[0],consumer_operations=path[1],
                            write=write,write_receiver_path=write_path,source_requirements=activation.requirements)
                    if module_route.body==caller.namespace:
                        start=caller.index.operations[module_route.operation].terminator.successors[module_route.normal.successor_index].block
                    else:start=caller.index.regions[caller.graph.root].entry
                    path=facts.paths.find_path(start,route.call_operation,key,kills)
                    if path is None:continue
                    module=self.modules._body(module_route.module_body);mf=self.modules._index(module)
                    if any('REQUIRED_EXPANSION'in f.kind for f in mf.module.frontiers):
                        self._note(caller.namespace,'SOURCE_MODULE_INITIALIZER_PARTIAL',
                            'Source module retains unexpanded code; no complete initial namespace snapshot is invented.')
                        continue
                    dependencies=self.modules.namespace_for(module)
                    for terminal in module.graph.operations:
                        if (terminal.terminator is None or terminal.terminator.kind is not TerminatorKind.RETURN
                                or mf.paths.owners[terminal.id][0]!=module.graph.root):continue
                        worlds=[u for u in terminal.uses if type(module.index.values[u.value])is StateVersionValue]
                        if len(worlds)!=1:continue
                        contract=(self.modules.import_initialization_contract if self.initializer_contract is None
                            else self.initializer_contract)
                        for binding in _import_initializer_bindings(dependencies,module_route,key,terminal.id,worlds[0].id,contract=contract):
                            dependencies.validate_binding(binding);write=binding.write
                            yield StaticModuleNamespaceAtCall(**common,source_body=module.namespace,
                                source_operation=write.operation,source_owner=write.owners[0],source_payload=write.payload,
                                source_world=write.world,source_normal=write.normal_edge,
                                source_value=module.index.use_site(write.payload).use.value,source_key=write.keys[0],
                                snapshot_operation=terminal.id,snapshot_world=worlds[0].id,
                                source_path=binding.path,source_operations=binding.intervening_operations,
                                consumer_path=path[0],consumer_operations=path[1],conditions=(
                                    MODULE_IMPORT_INITIALIZER_CONDITIONS if contract else MODULE_FLOW_BASE_CONDITIONS))

    def sources(self,activation,*,read_body,read,slot,entry_paths,bridges=(),requester=None):
        route=activation.environment
        key_body=self.modules._body(route.callee)
        dependencies=self.modules.namespace_for(read_body)
        key=dependencies._string(read.keys[slot])
        token=route,activation.requirements,read_body.namespace,read.operation,slot,entry_paths,bridges
        if token in self._active:
            self._note(read_body.namespace,'RECURSIVE_MODULE_GLOBALS_STATE_OPEN',
                'A state demand cannot establish its own callable or owner provenance.',demand=token)
            return ()
        if len(self._active)>=self.max_depth:
            self._note(read_body.namespace,'MODULE_GLOBALS_STATE_DEPTH_BUDGET',
                'Module state projection reached its explicit finite demand depth budget.',demand=token)
            return ()
        self._active.add(token);self._stack.append(token);self._pending_frontiers[token]={}
        previous_frontiers=self._demand_frontiers.get(token,())
        try:
            from scar.analysis.static_crossbody_namespace import _read_endpoint
            segments=[_segment(key_body,entry_paths[0],route.member.reference,self.modules.namespace_for(key_body))]
            for bridge,witness in zip(bridges,entry_paths[1:]):
                child=self.modules._body(bridge.environment.callee)
                segments.append(_segment(child,witness,bridge.callee_owner,self.modules.namespace_for(child)))
            contexts=(_context(route),*(_context(b.environment)for b in bridges))
            requirements=(*activation.requirements,*contexts)
            result=[]
            # _read_endpoint needs only the original namespace/index/dependencies.
            endpoint_body=SimpleNamespace(namespace=read_body.namespace,index=read_body.index,dependencies=dependencies)
            endpoint=_read_endpoint(endpoint_body,read,slot)
            for projection in self.projections(activation,key,requester):
                flow=StaticModuleGlobalsFlow(projection,endpoint,tuple(segments),bridges,requirements)
                result.append(flow)
            self._replace_demand(token,tuple(dict.fromkeys(result)))
            self._replace_frontiers(token,tuple(self._pending_frontiers[token]))
            return self._demands[token]
        except BaseException as error:
            kind=('MODULE_GLOBALS_TIME_BUDGET_INTERRUPTED'if isinstance(error,TimeoutError)else
                'MODULE_GLOBALS_FACT_OR_TRAVERSAL_BUDGET_INTERRUPTED'if isinstance(error,OverflowError)else
                'MODULE_GLOBALS_ANALYSIS_INTERRUPTED')
            self._note(read_body.namespace,kind,'Qualified state demand did not complete ('+
                type(error).__name__+': '+str(error)+'); previous facts and pending evidence are retained.')
            self._replace_frontiers(token,tuple(dict.fromkeys((*previous_frontiers,*self._pending_frontiers[token]))))
            raise
        finally:
            del self._pending_frontiers[token];self._stack.pop();self._active.remove(token)


def _validate_environment_state(route,state,*,modules,check_context,requirements):
    from scar.analysis.static_function_environment import validate_function_environment_route
    from scar.ir.program.static_calls import StaticQualifiedFunctionCreation
    caller,callee=modules._body(route.caller),modules._body(route.callee)
    validate_function_environment_route(route,caller_graph=caller.graph,caller_document=caller.document,
        caller_namespace=caller.namespace,callee_graph=callee.graph,callee_document=callee.document,
        callee_namespace=callee.namespace,definition=route.creation.definition,
        call_operation=route.call_operation,callee_use=route.callee_use,creations=(),
        qualified_creations=(StaticQualifiedFunctionCreation(route.creation_body,route.creation),),
        load_creation_body=modules._body,caller_index=caller.index,callee_index=callee.index)
    target=check_context(_context(route),requirements)if check_context is not None else None
    if target is not None:
        _need(route in target.environment_routes and (state is None or state==target.state_entry),
            'globals state environment is not selected by its original target/context')
    if state is None:return
    state.__post_init__();site=caller.index.use_site(state.caller_use)
    before,after=caller.index.values.get(state.caller_value),callee.index.values.get(state.callee_value)
    _need(site.operation==route.call_operation and site.use.value==state.caller_value
        and site.use.role is UseRole.STATE_CONTENT and state.caller_use in caller.index.operations[route.call_operation].invoke_arguments
        and type(before)is StateVersionValue and type(after)is StateVersionValue
        and before.location==state.caller_location and after.location==state.callee_location,
        'globals state bridge changed an original world Use/value/location')
    from scar.ir.record_codec import decode
    from scar.ir.program.functions import BodyEntryInterface
    interface=decode(BodyEntryInterface,callee.document['interface'])
    _need(interface.world==state.callee_value,'globals state bridge changed its original callee entry world')


def validate_module_globals_flow(flow,*,engine,check_support,check_context=None):
    """Fresh input/port/path replay; producer-side validity caches are unused."""
    flow.__post_init__();projection=flow.projection;route=projection.environment
    modules=engine.modules
    paths=[projection.callable_source,*(step.callable_source for step in projection.owner_routes),
        *projection.overwrite_receiver_paths]
    if projection.write_receiver_path is not None:paths.append(projection.write_receiver_path)
    for path in paths:
        for point in path.points:
            if check_context is not None:
                for n,context in enumerate(point.requirements):check_context(context,point.requirements[:n])
        validate_reference_source_path(path,load_body=modules._body,
            namespace_for=modules.namespace_for,check_support=check_support)
    _validate_environment_state(route,projection.state_entry,modules=modules,check_context=check_context,
        requirements=projection.callable_source.points[0].requirements)
    for step in projection.owner_routes:
        _validate_environment_state(step.environment,None,modules=modules,check_context=check_context,
            requirements=step.callable_source.points[0].requirements)
    # Replay the reference ports from these already checked support witnesses;
    # the fresh module engine independently rederives stores and CFG kills.
    def reference_sources(body,value,requirements,requester):
        for path in paths:
            for before,after in zip(path.points,path.points[1:]):
                if (before.body,before.value,before.requirements)!=(body.namespace,value,requirements):continue
                cross=tuple(f for f in path.cross_body_namespace_flows if f.read.body==before.body
                    and f.read.result==before.value and f.write.body==after.body
                    and modules._body(after.body).index.use_site(f.write.assigned_reference).use.value==after.value)
                args=tuple(f for f in path.argument_flows if f.argument.formal_body==before.body
                    and f.argument.formal_value==before.value and f.argument.actual_body==after.body
                    and f.argument.actual_value==after.value)
                returns=tuple(f for f in path.return_flows if f.context.caller==before.body
                    and f.completion.landing_value==before.value and f.context.callee==after.body
                    and f.terminal.value==after.value)
                globalsflows=tuple(f for f in path.module_globals_flows if f.read.body==before.body
                    and f.read.result==before.value and f.projection.source_body==after.body
                    and f.projection.source_value==after.value)
                if cross or args or returns or globalsflows:
                    yield SimpleNamespace(body_namespace=after.body,value=after.value,requirements=after.requirements,
                        crossflows=cross,argflows=args,returnflows=returns,globalsflows=globalsflows)
    from scar.analysis.static_module_attributes import ModuleAttributeDependencies,validate_import_module_route
    fresh_modules=ModuleAttributeDependencies(load_body=modules.load_body,source_context=modules.source_context,
        module_bodies=modules.module_bodies,namespace_for=modules.namespace_for,reference_sources=reference_sources,
        max_steps=modules.max_steps,max_facts=modules.max_facts,check=modules.check,
        import_initialization_contract=_uses_import_initializer_contract(flow))
    validate_import_module_route(projection.module,engine=fresh_modules,check_context=check_context)
    def incoming(point):
        for step in projection.owner_routes:
            r=step.environment;requirements=step.callable_source.points[0].requirements
            if r.callee==point.body and r.member.reference==point.value:
                yield SimpleNamespace(environment=r,requirements=requirements,context=_context(r))
    fresh=ModuleGlobalsDependencies(modules=fresh_modules,incoming=incoming,
        max_depth=engine.max_depth,max_facts=engine.max_facts,check=engine.check,
        initializer_contract=ModuleFlowCondition.SOURCE_IMPORT_INITIALIZER_USES_MODULE_DICT in projection.conditions)
    activation=SimpleNamespace(environment=route,state_entry=projection.state_entry,
        context=_context(route),requirements=projection.callable_source.points[0].requirements)
    _need(projection in fresh.projections(activation,projection.key),
        'module CALL state source/owner/world/payload/snapshot/overwrite differs from original inputs')
    from scar.analysis.static_namespace import NamespaceEntryPathWitness
    from scar.analysis.static_crossbody_namespace import StaticNamespaceBody,_validate_bridge
    from scar.analysis.static_function_environment import _EnvironmentFacts
    read_body=modules._body(flow.read.body);dependencies=modules.namespace_for(read_body)
    read=dependencies.by_result.get(flow.read.result)
    _need(read is not None and flow.read.owner in read.owners,'globals flow changed its original namespace read')
    slot=read.owners.index(flow.read.owner)
    entries=[]
    for n,segment in enumerate(flow.segments):
        body=modules._body(segment.body);deps=modules.namespace_for(body)
        last=n==len(flow.segments)-1
        witness=NamespaceEntryPathWitness(segment.body.region,segment.start_block,segment.query_owner,
            segment.query_operation,segment.query_world,segment.key,segment.path,segment.intervening_operations,
            segment.conditions,read if last else None,slot if last else None,segment.start_owner)
        deps.validate_entry_path(witness,entry_owner=segment.start_owner);entries.append(witness)
    endpoints={}
    for bridge in flow.bridges:
        r=bridge.environment
        for ns in (r.caller,r.callee,r.creation_body,*(x.creation_body for x in bridge.caller_owner_routes),
                *(x.caller for x in bridge.caller_owner_routes),*(x.callee for x in bridge.caller_owner_routes)):
            body=modules._body(ns)
            endpoints[ns]=StaticNamespaceBody(body.graph,body.document,ns,body.index,modules.namespace_for(body))
        _validate_bridge(bridge,endpoints,_EnvironmentFacts())
    replay=fresh.sources(activation,read_body=read_body,read=read,slot=slot,entry_paths=tuple(entries),bridges=flow.bridges)
    _need(flow in replay,'globals state read/entry/context/ordered bridge differs from original inputs')
    return True


__all__=['ModuleGlobalsDependencies','validate_module_globals_flow']
