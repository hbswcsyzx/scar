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
    StaticNamespaceCallBridge,
)


@dataclass(frozen=True, slots=True)
class QualifiedSource:
    """An existing assigned reference, with conditional cross-body support."""
    body_namespace: SourceBodyNamespace
    value: ValueID
    crossflows: tuple
    context: tuple


@dataclass(frozen=True, slots=True)
class _RegisteredCall:
    body: SourceBodyNamespace
    operation: OperationID
    callee_use: UseID


@dataclass(frozen=True, slots=True)
class _Activation:
    environment: object
    state_entry: object

    @property
    def key(self):
        r=self.environment
        return (r.caller,r.call_operation,r.callee,r.creation_body,r.creation.factory)


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

    @property
    def frontiers(self):
        return tuple(dict.fromkeys(row for rows in self._demand_frontiers.values() for row in rows))

    @property
    def fact_count(self):
        return len(self._facts)

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

    def activate_target(self,callkey,target):
        call=self._calls.get(callkey)
        if call is None:raise ValueError('target activation requires a registered original call')
        if type(target)is not StaticCallTarget:
            raise TypeError('target activation requires an existing typed conditional target')
        if target.body is None or target.state_entry is None:return False
        changed=False
        for route in target.environment_routes:
            if route.member.role is not EnvironmentRole.GLOBALS_NAMESPACE:continue
            if (route.kind is not FunctionEnvironmentRouteKind.REFERENCE_BINDING
                    or route.caller!=call.body or route.call_operation!=call.operation
                    or route.callee_use!=call.callee_use or route.callee!=target.body):
                raise ValueError('activated globals route differs from its original call/target ports')
            activation=_Activation(route,target.state_entry)
            # Include the complete qualified route in the fact key: two
            # conditional field/creation supports must not overwrite each other.
            if activation not in self._incoming[target.body]:
                self._incoming[target.body][activation]=activation
                self._outgoing[call.body].add(target.body);changed=True
        if changed:self._invalidate(target.body)
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

    def _owner_paths(self,body,target,required,seen=(),note=None):
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
            if route.member.reference!=owner or expected and route not in expected:continue
            source=route.creation_body,route.source_value
            if source==target:results.append((owner,(route,)))
            elif source not in seen:
                source_body=self._body(source[0])
                for source_owner,path in self._owner_paths(source_body,target,required,(*seen,endpoint),note):
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

    def sources(self,body,value):
        """Return real qualified STORE payloads feeding this namespace read.

        Existing same-body reaching definitions remain the local resolver's
        responsibility. Every result here has at least one actual call bridge.
        Missing incoming facts leave an open demand, never a closed empty set.
        """
        namespace=self.register_body(body);cachekey=namespace,value
        if cachekey in self._cache:return self._cache[cachekey]
        dependencies=self.namespace_for(body);read=dependencies.by_result.get(value)
        if read is None:return ()
        outputs={};demand_frontiers={}

        def note(kind,detail,source=None):
            row=StaticCallFrontier(kind,detail,source)
            demand_frontiers.setdefault(row,row)

        def walk(current,owner,key,point,world,bridges,paths,required,seen):
            self.check();current_namespace=current.namespace
            token=current_namespace,owner,key,point,world
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
                    source=QualifiedSource(current_namespace,self._payload(current,binding),(flow,),context)
                    outputs.setdefault(source,source)
            if not bridges:
                entries=local.entry_paths_to_read(read,slot)
            else:
                entries=local.entry_paths_to(owner,key,point,world)
            if not entries:return
            expected=[r for r in required if r.callee==current_namespace and r.member.reference==owner]
            incoming=[a for a in self._incoming.get(current_namespace,{}).values()
                      if a.environment.member.reference==owner and(not expected or a.environment in expected)]
            if not incoming:
                note('INCOMING_NAMESPACE_STATE_OPEN',
                    'No activated qualified G/state-entry route supplies this entry demand; an empty source set is not target-set closure.',current_namespace.source)
                return
            for activation in incoming:
                route=activation.environment;caller=self._body(route.caller)
                owner_paths=self._owner_paths(caller,(route.creation_body,route.source_value),required,note=note)
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
                             (bridge,*bridges),(entry,*paths),requirements,(*seen,token))

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
            walk(body,owner,key_value.origin.value,read.operation,read.world,(),(),(),())
        result=tuple(outputs.values());self._cache[cachekey]=result
        self._demand_frontiers[cachekey]=tuple(demand_frontiers.values())
        return result


__all__=['QualifiedSource','InterproceduralDependencies']
