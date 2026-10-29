"""Consume qualified environment/state routes with a source-only work queue.

The queue owns relationship endpoints, never another program graph or a
runtime invocation. A cross-body source is emitted only after a backwards
namespace demand reaches an original STORE. Cycles cannot seed themselves;
unknown incoming state and bounded recursive contexts remain explicit gaps.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.model import LiteralOrigin, ReferenceValue
from scar.ir.program.source_call_bindings import SourceBodyNamespace
from scar.ir.program.static_calls import (
    CrossBodyNamespaceCondition as BridgeCondition,
    FunctionEnvironmentRouteKind, StaticCallFrontier, StaticCallTarget,
    StaticArgumentValueFlow, StaticCallContext, StaticCrossBodyNamespaceFlow,
    StaticNamespaceCallBridge, StaticReturnValueFlow,
)


@dataclass(frozen=True, slots=True)
class QualifiedSource:
    """An existing assigned reference, with conditional cross-body support."""
    body_namespace: SourceBodyNamespace
    value: ValueID
    crossflows: tuple
    context: tuple
    argflows: tuple = ()
    returnflows: tuple = ()
    requirements: tuple = ()


@dataclass(frozen=True, slots=True)
class _RegisteredCall:
    body: SourceBodyNamespace
    operation: OperationID
    callee_use: UseID


@dataclass(frozen=True, slots=True)
class _Activation:
    environment: object
    state_entry: object
    context: StaticCallContext
    requirements: tuple = ()

    @property
    def key(self):
        r=self.environment
        return (r.caller,r.call_operation,r.callee,r.creation_body,r.creation.factory,self.requirements)


class InterproceduralDependencies:
    """Finite may-dependence propagation over immutable source body ports.

    ``load_body(namespace)`` and ``namespace_for(body)`` are supplied by the
    enclosing bounded reader. No body/index is retained here. Registering a
    new call-entry fact invalidates dependent demands and schedules affected
    original calls; the enclosing solver drains ``pop_affected`` to a fixed
    point before publishing final call records.
    """
    def __init__(self, *, load_body, namespace_for, max_contexts=65536,
                 max_depth=64, max_facts=262144, check=None):
        if not callable(load_body) or not callable(namespace_for):
            raise TypeError('interprocedural dependencies require bounded body/index loaders')
        if any(type(n)is not int or n<1 for n in (max_contexts,max_depth,max_facts)):
            raise ValueError('interprocedural context/depth/fact budgets must be positive integers')
        self.load_body,self.namespace_for=load_body,namespace_for
        self.max_contexts,self.max_depth,self.max_facts=max_contexts,max_depth,max_facts
        self.check=check or (lambda:None)
        self._bodies=set();self._calls={};self._calls_by_body=defaultdict(set)
        self._incoming=defaultdict(dict);self._outgoing=defaultdict(set)
        self._affected=deque();self._queued=set();self._cache={}
        self._facts=set();self._contexts=set();self._demand_frontiers={}
        self._entry_stacks=defaultdict(dict);self._arguments=defaultdict(dict);self._returns=defaultdict(dict)
        self._value_flows={};self._value_frontiers={};self._watchers=defaultdict(set)

    @property
    def frontiers(self):
        return tuple(dict.fromkeys(row for rows in (*self._demand_frontiers.values(),*self._value_frontiers.values()) for row in rows))

    @property
    def fact_count(self):
        return len(self._facts)

    @property
    def namespace_fact_count(self):
        return sum(type(row)is StaticCrossBodyNamespaceFlow for row in self._facts)

    @property
    def value_fact_count(self):
        return sum(type(row)in(StaticArgumentValueFlow,StaticReturnValueFlow)for row in self._facts)

    def register_body(self,body):
        namespace=body.namespace
        if type(namespace)is not SourceBodyNamespace or namespace.region!=body.graph.root:
            raise ValueError('interprocedural body must retain its qualified original graph root')
        self._bodies.add(namespace)
        return namespace

    def register_call(self,body,operation,callee_use,*,schedule_initial=False):
        namespace=self.register_body(body)
        identity=operation if type(operation)is OperationID else operation.id
        use=callee_use if type(callee_use)is UseID else callee_use.id
        site=body.index.use_site(use)
        if (site.operation!=identity or use not in body.index.operations[identity].invoke_arguments
                or type(body.index.values[site.use.value])is not ReferenceValue):
            raise ValueError('interprocedural call must name its original callable Use')
        key=namespace,identity;record=_RegisteredCall(namespace,identity,use)
        previous=self._calls.get(key)
        if previous is not None and previous!=record:
            raise ValueError('one original call cannot acquire a different callable port')
        self._calls[key]=record;self._calls_by_body[namespace].add(key)
        if type(schedule_initial)is not bool:
            raise TypeError('initial scheduling must be explicit')
        if previous is None and schedule_initial:self._enqueue(key)
        return key

    def _enqueue(self,key):
        if key not in self._queued:
            self._queued.add(key);self._affected.append(key)

    def pop_affected(self):
        if not self._affected:return None
        key=self._affected.popleft();self._queued.remove(key)
        return key

    def _invalidate(self,namespace):
        # A new outer environment also affects already-known deeper calls.
        # This ordinary monotone work queue propagates around call-graph SCCs;
        # it does not assert an empty effect summary when an SCC is revisited.
        pending=[namespace];seen=set()
        while pending:
            self.check();current=pending.pop()
            if current in seen:continue
            seen.add(current)
            for key in self._calls_by_body.get(current,()):self._enqueue(key)
            pending.extend(self._outgoing.get(current,()))
        for key in tuple(self._cache):
            if key[0]in seen:del self._cache[key]
        for key in tuple(self._demand_frontiers):
            if key[0]in seen:del self._demand_frontiers[key]
        for (body,_,_),requesters in self._watchers.items():
            if body in seen:
                for requester in requesters:self._enqueue(requester)

    @staticmethod
    def _require_stack(namespace,requirements):
        if type(requirements)is not tuple or any(type(r)is not StaticCallContext for r in requirements):
            raise TypeError('call requirements must be an ordered typed static call context stack')
        if (any(a.callee!=b.caller for a,b in zip(requirements,requirements[1:]))
                or requirements and requirements[-1].callee!=namespace):
            raise ValueError('call requirements do not reach this exact qualified body')

    def entry_requirements(self,body):
        namespace=body if type(body)is SourceBodyNamespace else body.namespace
        return tuple(self._entry_stacks.get(namespace,{}))

    @staticmethod
    def _target_key(callkey,target,requirements):
        return callkey,target.definition,target.body,requirements

    def get_value_flows(self,callkey,target,requirements=()):
        return self._value_flows.get(self._target_key(callkey,target,requirements),((),()))

    def activate_target(self,callkey,target,requirements=()):
        call=self._calls.get(callkey)
        if call is None:raise ValueError('target activation requires a registered original call')
        if type(target)is not StaticCallTarget:
            raise TypeError('target activation requires an existing typed conditional target')
        self._require_stack(call.body,requirements)
        if requirements not in target.requirement_paths:
            raise ValueError('target activation requirements are absent from its original target alternatives')
        if target.body is None:return False
        caller=self._body(call.body);callee=self._body(target.body)
        callee_value=caller.index.use_site(call.callee_use).use.value
        context=StaticCallContext(call.body,call.operation,call.callee_use,callee_value,target.definition,target.body)
        key=self._target_key(callkey,target,requirements)
        stack=(*requirements,context)
        existing_stack=stack in self._entry_stacks.get(target.body,{})
        extra=[]
        # Refusing a new context must also refuse its argument/return indexes:
        # otherwise a stored return could push the very stack denied here.
        # Existing admitted contexts remain usable when a limit is reached.
        if not existing_stack:
            if context in requirements:
                extra.append(StaticCallFrontier('RECURSIVE_CALL_CONTEXT_OPEN',
                    'Repeated source call context requires a recursive summary; an unseeded cycle cannot create a value.',target.definition.source))
            elif len(stack)>self.max_depth:
                extra.append(StaticCallFrontier('INTERPROCEDURAL_CONTEXT_DEPTH_BUDGET',
                    'Concrete static call requirements reached their explicit depth budget.',target.definition.source))
            elif stack not in self._contexts and len(self._contexts)>=self.max_contexts:
                extra.append(StaticCallFrontier('INTERPROCEDURAL_CONTEXT_COUNT_BUDGET',
                    'Concrete static call requirements reached their explicit finite context budget.',target.definition.source))
        if extra:
            self._value_frontiers[key]=tuple(extra)
            return False
        activations=[]
        for route in target.environment_routes:
            if route.member.role is not EnvironmentRole.GLOBALS_NAMESPACE:continue
            if (route.kind is not FunctionEnvironmentRouteKind.REFERENCE_BINDING
                    or route.caller!=call.body or route.call_operation!=call.operation
                    or route.callee_use!=call.callee_use or route.callee!=target.body):
                raise ValueError('activated globals route differs from its original call/target ports')
            if target.state_entry is not None:
                activation=_Activation(route,target.state_entry,context,requirements)
                if activation not in self._incoming.get(target.body,{}):activations.append(activation)
        from scar.analysis.static_value_flows import derive_static_value_flows
        args,returns,frontiers=derive_static_value_flows(caller=caller,callee=callee,
            call_operation=call.operation,callee_use=call.callee_use,target=target,requirements=requirements,
            load_body=self._body)
        if any(flow.context!=context or flow.requirements!=requirements for flow in (*args,*returns)):
            raise ValueError('argument/return derivation changed its original call context')
        new_facts=set((*args,*returns))-self._facts
        if len(self._facts)+len(new_facts)>self.max_facts:
            # Atomic rejection: none of this activation's new value facts,
            # entry stacks or globals bridges has been committed yet.
            extra=StaticCallFrontier('INTERPROCEDURAL_VALUE_FACT_BUDGET',
                'Argument/normal-return facts exceed the remaining shared relationship budget; existing admitted facts remain available.',target.definition.source)
            self._value_frontiers[key]=tuple(dict.fromkeys((*frontiers,extra)))
            return False
        self._value_frontiers[key]=tuple(frontiers)
        previous=self._value_flows.get(key,((),()))
        self._value_flows[key]=(tuple(dict.fromkeys((*previous[0],*args))),tuple(dict.fromkeys((*previous[1],*returns))))
        changed=False
        for flow in args:
            endpoint=flow.argument.formal_body,flow.argument.formal_value
            if flow not in self._arguments[endpoint]:
                self._arguments[endpoint][flow]=flow;self._facts.add(flow);changed=True
        result_changed=False
        for flow in returns:
            endpoint=context.caller,flow.completion.landing_value
            if flow not in self._returns[endpoint]:
                self._returns[endpoint][flow]=flow;self._facts.add(flow);changed=True;result_changed=True
        if not existing_stack:
            self._entry_stacks[target.body][stack]=stack;self._contexts.add(stack);changed=True
        for activation in activations:
            self._incoming[target.body][activation]=activation;changed=True
        if changed:
            self._outgoing[call.body].add(target.body)
            self._invalidate(target.body)
        if result_changed:self._invalidate(call.body)
        return changed

    def _body(self,namespace):
        body=self.load_body(namespace)
        if body is None or body.namespace!=namespace:
            raise ValueError('qualified body loader returned another source graph namespace')
        return body

    @staticmethod
    def _global_port(body):
        if getattr(body,'module',None)is not None:
            roots=body.graph.frame_roots
            if len(roots)==1:return roots[0].entry.globals_namespace
            return None
        environments=[e for e in body.graph.environments
                      if e.region==body.graph.root and e.code_definition==body.namespace.definition]
        if len(environments)!=1:return None
        return next((m.reference for m in environments[0].members
                     if m.role is EnvironmentRole.GLOBALS_NAMESPACE),None)

    @staticmethod
    def _activation_matches(activation,requirements):
        return (not requirements or activation.context==requirements[-1]
                and activation.requirements==requirements[:-1])

    def _owner_paths(self,body,target,required,seen=(),note=None,call_requirements=()):
        """Actual incoming G routes tying this caller owner to a factory G.

        Equality is of qualified source ports under the retained creation
        conditions. It never equates arbitrary equal-looking ValueIDs across
        graphs, or skips intermediate caller stores/world transitions.
        """
        namespace=body.namespace
        if target[0]==namespace:
            value=body.index.values.get(target[1])
            if type(value)is ReferenceValue:return ((target[1],()),)
        owner=self._global_port(body)
        if owner is None:return ()
        endpoint=namespace,owner
        if endpoint in seen:
            if note is not None:note('RECURSIVE_GLOBALS_OWNER_CONTEXT_OPEN',
                'Globals-owner provenance revisits an original entry port; a cycle cannot establish its own source.',namespace.source)
            return ()
        if len(seen)>=self.max_depth:
            if note is not None:note('INTERPROCEDURAL_CONTEXT_DEPTH_BUDGET',
                'Globals-owner provenance reached the explicit finite context depth budget.',namespace.source)
            return ()
        results=[]
        expected=[r for r in required if r.callee==namespace and r.member.reference==owner]
        for activation in self._incoming.get(namespace,{}).values():
            self.check();route=activation.environment
            if (route.member.reference!=owner or expected and route not in expected
                    or not self._activation_matches(activation,call_requirements)):continue
            source=route.creation_body,route.source_value
            if source==target:results.append((owner,(route,)))
            elif source not in seen:
                source_body=self._body(source[0])
                source_requirements=(activation.requirements if route.creation_body==route.caller else())
                for source_owner,path in self._owner_paths(source_body,target,required,(*seen,endpoint),note,source_requirements):
                    if source_owner==source[1]:results.append((owner,(route,*path)))
        return tuple(dict.fromkeys(results))

    @staticmethod
    def _module_alias_allowed(body,owner):
        # Module STORE_NAME writes L while a function factory receives G.
        # Only this original L/G ABI pair can introduce an explicit alias
        # condition here; arbitrary class/function namespace owners cannot.
        if getattr(body,'module',None)is None or len(body.graph.frame_roots)!=1:return False
        return owner==body.graph.frame_roots[0].entry.globals_namespace

    def _payload(self,body,binding):
        return body.index.use_site(binding.write.payload).use.value

    def _compose(self,write_body,binding,bridges,paths,read_body,read,slot):
        from scar.analysis.static_crossbody_namespace import (
            StaticNamespaceBody,compose_cross_body_namespace_flow,
        )
        namespaces={write_body.namespace,read_body.namespace}
        for bridge in bridges:
            route=bridge.environment
            namespaces.update((route.caller,route.callee,route.creation_body))
            for owner_route in bridge.caller_owner_routes:
                namespaces.update((owner_route.caller,owner_route.callee,owner_route.creation_body))
        bodies={}
        for namespace in namespaces:
            body=write_body if namespace==write_body.namespace else read_body if namespace==read_body.namespace else self._body(namespace)
            bodies[namespace]=StaticNamespaceBody(body.graph,body.document,namespace,body.index,self.namespace_for(body))
        return compose_cross_body_namespace_flow(write_body=bodies[write_body.namespace],binding=binding,
            bridges=bridges,entry_paths=paths,read_body=bodies[read_body.namespace],read=read,
            read_slot=slot,bodies=bodies)

    def _namespace_sources(self,body,value,requirements):
        """Return real qualified STORE payloads feeding this namespace read.

        Existing same-body reaching definitions remain the local resolver's
        responsibility. Every result here has at least one actual call bridge.
        Missing incoming facts leave an open demand, never a closed empty set.
        """
        namespace=body.namespace;cachekey=namespace,value,requirements
        dependencies=self.namespace_for(body);read=dependencies.by_result.get(value)
        if read is None:return ()
        outputs={};demand_frontiers={}

        def note(kind,detail,source=None):
            row=StaticCallFrontier(kind,detail,source)
            demand_frontiers.setdefault(row,row)

        def walk(current,owner,key,point,world,bridges,paths,required,seen,call_requirements):
            self.check();current_namespace=current.namespace
            token=current_namespace,owner,key,point,world,call_requirements
            if token in seen:
                note('RECURSIVE_NAMESPACE_CONTEXT_OPEN',
                    'A repeated namespace/control demand needs a recursive summary; no cycle seeds a reaching binding.',namespace.source)
                return
            if len(bridges)>self.max_depth:
                note('INTERPROCEDURAL_CONTEXT_DEPTH_BUDGET',
                    'Cross-body namespace demand reached the explicit call-context depth budget.',namespace.source)
                return
            local=self.namespace_for(current)
            if bridges:
                bindings=local.bindings_at(owner,key,point,world,
                    allow_owner_alias=self._module_alias_allowed(current,owner))
                for binding in bindings:
                    # The module-only alias option must still refer to L/G,
                    # not a third mapping or a fabricated owner correspondence.
                    write_owner=local.index.use_site(binding.write.owners[0]).use.value
                    if write_owner!=owner and self._module_alias_allowed(current,owner):
                        if write_owner!=current.graph.frame_roots[0].entry.locals_namespace:continue
                    context=tuple((b.environment.caller,b.environment.call_operation,
                        b.environment.callee,b.environment.creation_body,b.environment.creation.factory)for b in bridges)
                    if context not in self._contexts and len(self._contexts)>=self.max_contexts:
                        note('INTERPROCEDURAL_CONTEXT_COUNT_BUDGET',
                            'Conditional namespace contexts exceeded the explicit finite context budget.',namespace.source)
                        return
                    flow=self._compose(current,binding,bridges,paths,body,read,slot)
                    if flow not in self._facts and len(self._facts)>=self.max_facts:
                        note('INTERPROCEDURAL_NAMESPACE_FACT_BUDGET',
                            'Qualified namespace relationship budget exhausted; remaining demands stay open.',namespace.source)
                        continue
                    self._facts.add(flow);self._contexts.add(context)
                    source=QualifiedSource(current_namespace,self._payload(current,binding),(flow,),context,
                                           requirements=call_requirements)
                    outputs.setdefault(source,source)
            if not bridges:
                entries=local.entry_paths_to_read(read,slot)
            else:
                entries=local.entry_paths_to(owner,key,point,world)
            if not entries:return
            expected=[r for r in required if r.callee==current_namespace and r.member.reference==owner]
            incoming=[a for a in self._incoming.get(current_namespace,{}).values()
                      if a.environment.member.reference==owner and(not expected or a.environment in expected)
                      and self._activation_matches(a,call_requirements)]
            if not incoming:
                note('INCOMING_NAMESPACE_STATE_OPEN',
                    'No activated qualified G/state-entry route supplies this entry demand; an empty source set is not target-set closure.',current_namespace.source)
                return
            for activation in incoming:
                route=activation.environment;caller=self._body(route.caller)
                caller_requirements=(call_requirements[:-1]if call_requirements else activation.requirements)
                owner_paths=self._owner_paths(caller,(route.creation_body,route.source_value),required,
                                             note=note,call_requirements=caller_requirements)
                if not owner_paths:
                    note('CALLER_GLOBALS_PROVENANCE_OPEN',
                        'Foreign factory globals has no connected original caller-owner provenance; caller locals/current builtins are not substituted.',current_namespace.source)
                    continue
                for caller_owner,owner_routes in owner_paths:
                    conditions=(BridgeCondition.CALL_SELECTS_ENVIRONMENT_ROUTE,
                                BridgeCondition.CALL_ENTRY_PRESERVES_NAMESPACE_BINDING)
                    if route.creation_body!=route.caller:
                        conditions+=(BridgeCondition.CALLER_OWNER_ALIASES_FACTORY_GLOBALS,)
                    bridge=StaticNamespaceCallBridge(route,activation.state_entry,caller_owner,owner,
                                                     conditions,owner_routes)
                    residual=tuple(r for r in required if r not in expected)
                    requirements=tuple(dict.fromkeys((*residual,*owner_routes)))
                    for entry in entries:
                        walk(caller,caller_owner,key,route.call_operation,route.call_world,
                             (bridge,*bridges),(entry,*paths),requirements,(*seen,token),caller_requirements)

        for slot,owner_use in enumerate(read.owners):
            owner=dependencies.index.use_site(owner_use).use.value
            saved_builtins=any(e.region==body.graph.root and any(
                m.role is EnvironmentRole.BUILTINS_NAMESPACE and m.reference==owner for m in e.members)
                for e in body.graph.environments)
            if saved_builtins:
                note('SAVED_BUILTINS_NAMESPACE_STATE_OPEN',
                    'This original fallback owner is the function saved builtins; a globals route cannot supply its creation-time selection or contents.',namespace.source)
                continue
            key_value=dependencies.index.values[dependencies.index.use_site(read.keys[slot]).use.value]
            if type(key_value.origin)is not LiteralOrigin or type(key_value.origin.value)is not str:
                note('STATIC_NAMESPACE_KEY_OPEN',
                    'A namespace demand lacks an original builtin-string key; no name heuristic substitutes for it.',namespace.source)
                continue
            walk(body,owner,key_value.origin.value,read.operation,read.world,(),(),(),(),requirements)
        result=tuple(outputs.values())
        self._demand_frontiers[cachekey]=tuple(demand_frontiers.values())
        return result

    def sources(self,body,value,requirements=(),requester=None):
        """Trace only explicit namespace, actual/formal and normal-return ports.

        A return demand enters exactly one source call context. A formal can
        leave it only through that call's own actual port. No computation's
        arbitrary operands become aliases of its result, and no empty-context
        summary substitutes for an unavailable concrete context.
        """
        namespace=self.register_body(body)
        self._require_stack(namespace,requirements)
        cachekey=namespace,value,requirements
        if requester is not None:
            if (type(requester)is not tuple or len(requester)!=2
                    or type(requester[0])is not SourceBodyNamespace or type(requester[1])is not OperationID):
                raise TypeError('value demand requester must be its original qualified caller/operation')
            self._watchers[cachekey].add(requester)
        if cachekey in self._cache:return self._cache[cachekey]
        outputs={row:row for row in self._namespace_sources(body,value,requirements)}
        gaps=list(self._demand_frontiers.get(cachekey,()))
        def note(kind,detail):
            gaps.append(StaticCallFrontier(kind,detail,namespace.source))
        for flow in self._arguments.get((namespace,value),{}).values():
            self.check()
            if requirements:
                if flow.context!=requirements[-1]or flow.requirements!=requirements[:-1]:continue
                remaining=requirements[:-1]
            else:
                remaining=flow.requirements
            argument=flow.argument
            result=QualifiedSource(argument.actual_body,argument.actual_value,(),(),
                                   argflows=(flow,),requirements=remaining)
            outputs.setdefault(result,result)
        for flow in self._returns.get((namespace,value),{}).values():
            self.check()
            if flow.requirements!=requirements:continue
            context=flow.context
            if context in requirements:
                note('RECURSIVE_RETURN_CONTEXT_OPEN',
                     'A repeated call context cannot establish its own returned reference; recursive summary remains open.')
                continue
            if len(requirements)>=self.max_depth:
                note('INTERPROCEDURAL_CONTEXT_DEPTH_BUDGET',
                     'Returned-reference demand reached the explicit call-context depth budget.')
                continue
            nested=(*requirements,context)
            result=QualifiedSource(context.callee,flow.terminal.value,(),(),
                                   returnflows=(flow,),requirements=nested)
            outputs.setdefault(result,result)
        # A formal without a selected actual is still open. In particular a
        # default tuple, keyword-default mapping or arbitrary initializer input
        # cannot stand in for the missing element read of the selected function.
        interface=getattr(body,'interface',None)
        if interface is not None and value in {p.value for p in interface.parameters}and not outputs:
            note('SELECTED_FORMAL_ARGUMENT_SOURCE_OPEN',
                 'No original actual port for this selected call/formal is connected; defaults require current function-field and element-read provenance.')
        result=tuple(outputs.values());self._cache[cachekey]=result
        self._demand_frontiers[cachekey]=tuple(dict.fromkeys(gaps))
        return result


__all__=['QualifiedSource','InterproceduralDependencies']
