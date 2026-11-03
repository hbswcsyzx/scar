"""Demand projections of saved static relationships into the shared graph.

The session owns all artifact loading, bounded caches and fresh original-input
validation. This provider neither collects facts nor executes source. Edges
retain original Uses and select an exact context alternative; an empty stack
is not an instruction to union all callers.
"""
from __future__ import annotations

from dataclasses import replace

from scar.ir.program.dependencies import (
    DependencyCondition as Condition, DependencyEdge as Edge,
    DependencyEvidence as Evidence, DependencyFrame as Frame,
    DependencyFrontier as Frontier, DependencyKind as Kind,
    DependencyMeaning as Meaning, DependencyNeighborhood as Neighborhood,
    DependencyPoint as Point, GraphNamespace as Namespace,
    context_frames, context_is_closed, context_push, context_pop,
)
from scar.ir.program.functions import FunctionKind
from scar.ir.program.ids import OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import ValueKind
from scar.ir.program.static_calls import (
    FunctionEnvironmentRouteKind, StaticCallContext, ValueFlowCondition,
)


def dependency_frame(context):
    """Translate one original static interface selection, never an invocation."""
    if type(context)is not StaticCallContext:raise TypeError('expected an original StaticCallContext')
    return Frame(Namespace.from_source(context.caller),context.operation,context.callee_use,
        context.callee_value,Namespace.from_source(context.callee),context.definition.definition)


def dependency_context(contexts):
    return tuple(dependency_frame(context)for context in contexts)


def _pointer(locator,pointer):
    return replace(locator,pointer=locator.pointer.rstrip('/')+'/'+pointer)


class StaticCallDependencyProvider:
    """Incoming/outgoing edges over session-verified original relation shards.

    ``relation_shards``, ``call_shards_for`` and ``load_call_shard`` must replay
    the saved reader's original-input checks before yielding typed records.
    Only a light source-endpoint -> locator index is retained here; graphs,
    typed shards, source text and signatures belong to the shared session.
    """
    relation_kinds = frozenset((Kind.ARGUMENT, Kind.CALL_TARGET, Kind.COMPLETION, Kind.ENVIRONMENT,
        Kind.FIELD_INITIALIZER, Kind.STATE_INTERFACE, Kind.STATE_VALUE))
    def __init__(self,session):
        self.session=session
        self._outbound={};self._creation_contexts={}
        self._indexed=False;self._index_issue=None
        self._namespaces={};self._frames={};self._contexts={}
        self._reference_limit=4096

    def _reference(self,table,key,value):
        # Only immutable DTO/port references are retained, never core graphs,
        # typed shards or a successful-validation flag across input scopes.
        if key not in table and len(table)>=self._reference_limit:table.pop(next(iter(table)))
        table[key]=value
        return value

    def _namespace(self,body):
        key=(body.graph.artifact.uri,body.graph.decoded_sha256,body.graph.pointer,
            body.graph_representation,body.region)
        result=self._namespaces.get(key)
        if result is None:
            result=self._reference(self._namespaces,key,Namespace.from_source(body))
        return result

    def _ports_frame(self,caller,operation,callee_use,callee_value,target,definition):
        caller,target=self._namespace(caller),self._namespace(target)
        key=caller,operation,callee_use,callee_value,target,definition
        result=self._frames.get(key)
        if result is None:
            result=self._reference(self._frames,key,Frame(*key))
        return result

    def _context(self,contexts):
        result=self._contexts.get(contexts)
        if result is None:
            result=tuple(self._ports_frame(c.caller,c.operation,c.callee_use,c.callee_value,
                c.callee,c.definition.definition)for c in contexts)
            self._reference(self._contexts,contexts,result)
        return result

    def _frame(self,call,target):
        return self._ports_frame(call.caller,call.operation,call.callee_use,call.callee_value,
            target.body,target.definition.definition)

    def _route_frame(self,route):
        return self._ports_frame(route.caller,route.call_operation,route.callee_use,route.callee_value,
            route.callee,route.creation.definition.definition)

    def _environment_key(self,route):
        return (self._namespace(route.caller),route.call_operation,route.callee_use,route.callee_value,
            self._namespace(route.callee),self._namespace(route.creation_body),route.creation.factory,
            route.creation.normal_value,route.creation.definition.definition)

    def incoming(self,point):return self._neighbors(point,False)

    def outgoing(self,point):return self._neighbors(point,True)

    def _remember_creation(self,route,path):
        caller=self._context(path.points[0].requirements)
        creation=self._context(path.points[-1].requirements)
        key=self._environment_key(route),caller
        alternatives=self._creation_contexts.get(key)
        if alternatives is None:alternatives=self._reference(self._creation_contexts,key,{})
        self._reference(alternatives,creation,None)

    def _creation_sources(self,shard):
        for flow in shard.module_globals_flows:
            projection=flow.projection
            self._remember_creation(projection.environment,projection.callable_source)
            for step in projection.owner_routes:self._remember_creation(step.environment,step.callable_source)

    def _index_source(self,body,node,locator):
        key=self._namespace(body),node
        self._outbound.setdefault(key,{})[locator]=None

    def _ensure_outbound_index(self):
        if self._indexed:return
        try:
            for shard,locator in self.session.relation_shards():
                self.session.check();self._creation_sources(shard)
                for call in shard.calls:
                    self._index_source(call.caller,call.operation,locator)
                    for target in call.targets:
                        for argument in target.arguments:self._index_source(argument.actual_body,argument.actual_use,locator)
                        for completion in target.completions:
                            for terminal in completion.terminals:self._index_source(target.body,terminal.use,locator)
                        for route in target.environment_routes:
                            self._index_source(route.creation_body,route.source_use or route.source_value,locator)
                    for qualified in call.qualified_namespace_flows:
                        self._index_source(qualified.body,qualified.flow.assigned_reference,locator)
                    for flow in call.cross_body_namespace_flows:
                        self._index_source(flow.write.body,flow.write.assigned_reference,locator)
                for flow in shard.module_attribute_flows:
                    self._index_source(flow.source_body,flow.source_payload,locator)
                for flow in shard.module_globals_flows:
                    self._index_source(flow.projection.source_body,flow.projection.source_payload,locator)
            self._indexed=True;self._index_issue=None
        except (OverflowError,TimeoutError)as error:
            # A scanned prefix is useful, but it is not a closed consumer set.
            self._index_issue=type(error).__name__+': '+str(error)

    def _validate_point(self,point,indices=None):
        key=(point.namespace.identity,point.namespace.graph.declaration,point.namespace.source_body)
        index=indices.get(key)if indices is not None else None
        if index is None:
            index=self.session.index(point.namespace)
            if indices is not None:indices[key]=index
        node=point.node
        if type(node)is UseID:index.use_site(node)
        elif type(node)is ValueID:
            if node not in index.values:raise ValueError('static dependency Value is absent from its original graph')
        elif type(node)is OperationID:
            if node not in index.operations:raise ValueError('static dependency operation is absent from its original graph')
        elif type(node)is RegionID:
            if node not in index.regions:raise ValueError('static dependency region is absent from its original graph')
        frames=context_frames(point.context)
        if frames and frames[-1].target!=point.namespace:
            raise ValueError('static dependency context does not end at its original endpoint body')
        return index

    def _neighbors(self,point,outgoing):
        if type(point)is not Point:raise TypeError('static dependency query needs a DependencyPoint')
        indices={};index=self._validate_point(point,indices)
        if not outgoing and type(point.node)not in(ValueID,RegionID):
            # All existing cross-fragment targets are original value ports
            # or the selected body Region. Uses/operations are source ports;
            # their incoming local edges belong to LocalDependencyProvider.
            return Neighborhood()
        if not outgoing and type(point.node)is ValueID:
            from scar.ir.program.model import LiteralOrigin,ExactLiteralOrigin
            value=index.values[point.node]
            if type(value.origin)in(LiteralOrigin,ExactLiteralOrigin)and not any(
                    point.node==member.reference for env in index.graph.environments for member in env.members):
                # A canonical literal already has its exact local definition.
                # It cannot be a normal landing, namespace read, or formal.
                # Do not pay for unrelated CALL shards merely to return none.
                return Neighborhood()
        edges={};frontiers={};locators={};enumerated=True
        def note(kind,detail):
            row=Frontier(point,kind,detail);frontiers[row]=None
        def emit(source,target,kind,meaning,locator,conditions=(),anchors=(),rule='STATIC_RELATION_EDGE_V1'):
            if (source if outgoing else target)!=point:return
            self._validate_point(source,indices);self._validate_point(target,indices)
            sources=tuple(dict.fromkeys((locator,source.namespace.graph,target.namespace.graph)))
            edge=Edge(source,target,kind,meaning,(Evidence(rule,sources,tuple(anchors)),),tuple(dict.fromkeys(conditions)))
            edges[edge]=None
            if not context_is_closed(source.context) or not context_is_closed(target.context):
                note('RELATION_CONTEXT_UNRESOLVED','Original endpoints/suffixes are known; their complete creation or caller prefix is not selected.')
        try:
            for shard,locator in self.session.call_shards_for(point):
                self._creation_sources(shard);locators[locator]=None
                # A later global-routing budget cannot erase a known original
                # interface.  Project the selected local/caller shards first.
                self._project(shard,locator,point,outgoing,emit,note)
            if outgoing:
                routing=getattr(self.session,'outbound_call_locators',None)
                if routing is not None:
                    routed,complete,issue=routing(point)
                    locators.update((locator,None)for locator in routed)
                    if not complete:
                        note('OUTGOING_RELATION_INDEX_PARTIAL',issue or 'Saved raw relationship routing is not fully enumerated.')
                        enumerated=False
                else:
                    # Older/fake sessions retain their conservative typed
                    # prefix behavior; they cannot assert a raw closed index.
                    self._ensure_outbound_index()
                    locators.update(self._outbound.get((point.namespace,point.node),{}))
                    if self._index_issue:
                        note('OUTGOING_RELATION_INDEX_PARTIAL',self._index_issue);enumerated=False
            # Replaying an already projected local shard is intentional:
            # selected foreign witnesses can refine a creator context.  Edges
            # are deduplicated and every selected shard remains fresh-checked.
            for locator in locators:
                self.session.check()
                self._creation_sources(self.session.load_call_shard(locator))
            for locator in locators:
                self.session.check()
                shard=self.session.load_call_shard(locator)
                self._project(shard,locator,point,outgoing,emit,note)
            relevant=self._scope_frontier(point,outgoing,tuple(edges),note)
            if relevant and not context_is_closed(point.context):enumerated=False
            publication=getattr(self.session,'call_publication',None)
            if relevant and (not publication or publication.get('complete')is not True
                    or publication.get('scope',{}).get('canonical_call_denominator_complete',publication.get('complete'))is not True):
                enumerated=False
        except (OverflowError,TimeoutError)as error:
            note('STATIC_RELATION_QUERY_BUDGET',type(error).__name__+': '+str(error));enumerated=False
        except ValueError as error:
            if str(error).startswith('CALL_RELATIONS_NOT_PUBLISHED:'):
                if self._scope_frontier(point,outgoing,tuple(edges),note):
                    note('CALL_RELATIONS_NOT_PUBLISHED',str(error));enumerated=False
            else:raise
        return Neighborhood(tuple(edges),tuple(frontiers),enumerated=enumerated)

    def _scope_frontier(self,point,outgoing,edges,note):
        """Absence of a saved interface edge is not a no-dependence proof.

        Scope notes apply to original call/state/entry interfaces, not every
        literal or unrelated operation in a partially analyzed source file.
        """
        body=self.session.load(point.namespace)
        if not hasattr(body,'document'):return False
        roles=set();node=point.node
        interface=getattr(body,'interface',None)
        if type(node)is RegionID and node==body.graph.root and interface is not None:
            roles.add('CALL_BODY_ENTRY')
        if interface is not None and (node==interface.world or any(node==p.value for p in interface.parameters)):
            roles.add('ENTRY_INTERFACE')
        if any(node==member.reference for env in body.graph.environments for member in env.members):
            roles.add('ENVIRONMENT_INTERFACE')
        dependencies=body.dependencies
        if node in dependencies.by_result:roles.add('NAMESPACE_READ')
        sources=body.module if getattr(body,'module',None)is not None else body.metadata
        call_operations={row.operation for row in sources.use_links if row.role=='callee'}
        call_operations.update(row.operation for row in body.metadata.call_targets)
        if type(node)is OperationID and node in call_operations:roles.add('CALL_OPERATION')
        if type(node)is UseID:
            site=body.index.use_site(node)
            if site.operation in call_operations:roles.add('CALL_OPERAND')
            if (site.operation in dependencies.writes and dependencies.writes[site.operation].payload==node
                    or any(row.use==node and row.role=='assigned-reference'for row in sources.use_links)):
                roles.add('STATE_PAYLOAD')
        if type(node)is ValueID:
            # Produced landing formals retain their actual predecessor/slot;
            # no fake CALL or result is introduced to report an open boundary.
            from scar.ir.program.model import BlockArgument,CompletionResult
            origin=body.index.values[node].origin
            if type(origin)is BlockArgument:
                for operation in body.graph.operations:
                    if operation.id not in call_operations or operation.terminator is None:continue
                    for edge in operation.terminator.successors:
                        if (edge.block==origin.block and origin.index<len(edge.arguments)
                                and type(edge.arguments[origin.index])is CompletionResult):roles.add('CALL_COMPLETION')
        if not roles:return False
        publication=getattr(self.session,'call_publication',None)
        scope=(publication or{}).get('scope',{})
        enumerated=bool(publication and publication.get('complete')is True
            and scope.get('canonical_call_denominator_complete',publication.get('complete'))is True)
        if not enumerated:
            note('STATIC_RELATION_SCOPE_OPEN','Saved call/state publication is partial for this original '+
                '/'.join(sorted(roles))+' point; missing records do not prove absent dependencies.')
        elif not edges and (not outgoing or 'CALL_OPERATION'in roles or'STATE_PAYLOAD'in roles):
            note('STATIC_RELATION_SCOPE_OPEN','No saved interface relationship supplies this exact '+
                '/'.join(sorted(roles))+' point/context; complete CALL enumeration does not close bindings, state or aliases.')
        if not context_is_closed(point.context):
            note('STATIC_RELATION_CONTEXT_PREFIX_OPEN',
                'Known interface suffixes do not select the closed requirement paths of saved call/state witnesses.')
        if (not outgoing and roles&{'ENTRY_INTERFACE','ENVIRONMENT_INTERFACE','CALL_BODY_ENTRY'}
                and not context_frames(point.context)):
            note('UNBOUND_CALL_CONTEXT','Original entry/environment port has no selected caller frame; input identity is preserved without a caller union.')
        if outgoing and 'STATE_PAYLOAD'in roles and not scope.get('source_attribute_scope_complete',False):
            note('STATIC_RELATION_SCOPE_OPEN','Potential consumers of this original state payload depend on unclosed alias/escape/attribute scope.')
        if not outgoing and 'NAMESPACE_READ'in roles and not scope.get('source_attribute_scope_complete',False):
            note('NAMESPACE_STATE_CLOSURE_OPEN','Stored reaching bindings remain conditional on lookup, owner alias and intervening effects; enumeration is distinct from state closure.')
        return True

    def _project(self,shard,locator,query,outgoing,emit,note):
        def point(body,node,context):return Point(self._namespace(body),node,context)
        def enums(values):return tuple(Condition.from_enum(value)for value in values)
        for ci,call in enumerate(shard.calls):
            call_locator=_pointer(locator,'calls/'+str(ci))
            same_caller=query.namespace==self._namespace(call.caller)
            if same_caller and query.node==call.operation:
                for frontier in call.frontiers:note(frontier.kind,frontier.detail)
            for ti,target in enumerate(call.targets):
                target_locator=_pointer(call_locator,'targets/'+str(ti))
                if target.body is None:
                    if same_caller and query.node==call.operation:note('CALLEE_BODY_UNAVAILABLE','Selected definition has no original body ports.')
                    continue
                if call.callee_use is None or call.callee_value is None:
                    if same_caller and query.node==call.operation:note('CALL_CALLEE_PORT_OPEN','Original callable Use/value is unavailable; no context frame is invented.')
                    continue
                frame=self._frame(call,target)
                # Each stored requirement path is an independent alternative.
                for requirements in target.requirement_paths:
                    caller_context=self._context(requirements);callee_context=context_push(caller_context,frame)
                    call_point=point(call.caller,call.operation,caller_context)
                    callee_point=point(target.body,target.body.region,callee_context)
                    guards=(Condition.from_enum(ValueFlowCondition.CALL_TARGET_SELECTED),
                        Condition.from_enum(ValueFlowCondition.CONTEXT_REQUIREMENTS_SATISFIED))
                    emit(call_point,callee_point,Kind.CALL_TARGET,Meaning.STRUCTURE,target_locator,guards,
                        (point(call.caller,call.callee_use,caller_context),),rule='STATIC_CALL_TARGET_V1')
                    relevant=query in (call_point,callee_point)
                    for argument in target.arguments:
                        relevant|=((query.namespace,query.node)==(self._namespace(argument.actual_body),argument.actual_use)
                            if outgoing else(query.namespace,query.node)==(self._namespace(argument.formal_body),argument.formal_value))
                    for completion in target.completions:
                        if outgoing:
                            relevant|=query.namespace==self._namespace(target.body)and any(query.node==t.use for t in completion.terminals)
                        else:relevant|=(query.namespace,query.node)==(self._namespace(call.caller),completion.landing_value)
                    if target.state_entry is not None:
                        relevant|=((query.namespace,query.node)==(self._namespace(call.caller),target.state_entry.caller_use)
                            if outgoing else(query.namespace,query.node)==(self._namespace(target.body),target.state_entry.callee_value))
                    for route in target.environment_routes:
                        relevant|=((query.namespace,query.node)==(self._namespace(route.creation_body),route.source_use or route.source_value)
                            if outgoing else(query.namespace,query.node)==(self._namespace(route.callee),route.member.reference))
                    if not relevant:continue
                    callee=self.session.load_body(target.body)
                    signature=self.session.signature_for(target.definition,callee)
                    if signature.kind is not FunctionKind.SYNC:
                        if query==call_point or query==callee_point:
                            note('DEFERRED_BODY_ACTIVATION_OPEN','Async/generator creation is not synchronous body execution; no return or state interface is invented.')
                        continue
                    bound=(*guards,Condition.from_enum(ValueFlowCondition.CALL_ENTRY_BINDING_VALID))
                    for ai,argument in enumerate(target.arguments):
                        source=point(argument.actual_body,argument.actual_use,caller_context)
                        destination=point(argument.formal_body,argument.formal_value,callee_context)
                        if (not outgoing and query.namespace==destination.namespace
                                and query.node==destination.node and not context_frames(query.context)):
                            note('UNBOUND_CALL_CONTEXT','A formal has no selected caller frame; other call contexts are not unioned into its source.')
                        emit(source,destination,Kind.ARGUMENT,Meaning.REFERENCE,
                            _pointer(target_locator,'arguments/'+str(ai)),
                            (*bound,Condition.from_enum(ValueFlowCondition.ACTUAL_REFERENCE_BOUND_TO_FORMAL)),
                            (point(argument.actual_body,argument.actual_value,caller_context),call_point),
                            rule='STATIC_ACTUAL_FORMAL_V1')
                    for ri,completion in enumerate(target.completions):
                        meaning=Meaning.STATE_INTERFACE if completion.value_kind is ValueKind.STATE else (
                            Meaning.REFERENCE if completion.value_kind is ValueKind.REFERENCE else Meaning.VALUE)
                        for xi,terminal in enumerate(completion.terminals):
                            source=point(target.body,terminal.use,callee_context)
                            destination=point(call.caller,completion.landing_value,caller_context)
                            condition=Condition('scar.static-call-completion','CALL_'+completion.kind.value+'_EDGE_SELECTED',
                                call_point,completion.caller_edge.successor_index)
                            selected=Condition('scar.static-call-completion','CALLEE_EXIT_SITE_SELECTED',
                                point(target.body,terminal.operation,callee_context),completion.completion_index)
                            emit(source,destination,Kind.COMPLETION,meaning,
                                _pointer(target_locator,'completions/'+str(ri)),(*bound,condition,selected),
                                (point(target.body,terminal.value,callee_context),call_point),rule='STATIC_COMPLETION_PORT_V1')
                    if target.state_entry is not None:
                        state=target.state_entry
                        emit(point(call.caller,state.caller_use,caller_context),
                            point(target.body,state.callee_value,callee_context),Kind.STATE_INTERFACE,Meaning.STATE_INTERFACE,
                            _pointer(target_locator,'state_entry'),(*bound,
                                Condition('scar.static-state-entry',state.basis)),(call_point,),rule='STATIC_CALL_STATE_ENTRY_V1')
                    for ei,route in enumerate(target.environment_routes):
                        contexts=self._creation_contexts.get((self._environment_key(route),caller_context),{})
                        if not contexts:contexts={None:None}
                        for creation_context in contexts:
                            source=point(route.creation_body,route.source_use or route.source_value,creation_context)
                            destination=point(route.callee,route.member.reference,callee_context)
                            initializer=route.kind is FunctionEnvironmentRouteKind.FIELD_INITIALIZER_DEPENDENCE
                            emit(source,destination,Kind.FIELD_INITIALIZER if initializer else Kind.ENVIRONMENT,
                                Meaning.DEPENDENCE if initializer else Meaning.REFERENCE,
                                _pointer(target_locator,'environment_routes/'+str(ei)),(*bound,*enums(route.conditions)),
                                (call_point,point(route.creation_body,route.creation.factory,creation_context)),
                                rule='STATIC_FACTORY_ENVIRONMENT_V1')
            for ni,flow in enumerate(call.namespace_flows):
                if query.namespace==self._namespace(call.caller):
                    self._namespace_flow(flow,call.caller,query.context,_pointer(call_locator,'namespace_flows/'+str(ni)),emit)
            for ni,qualified in enumerate(call.qualified_namespace_flows):
                if query.namespace==self._namespace(qualified.body):
                    self._namespace_flow(qualified.flow,qualified.body,query.context,
                        _pointer(call_locator,'qualified_namespace_flows/'+str(ni)),emit)
            for ni,flow in enumerate(call.cross_body_namespace_flows):
                self._cross_namespace(flow,_pointer(call_locator,'cross_body_namespace_flows/'+str(ni)),query,outgoing,emit,note)
            for ni,flow in enumerate(call.module_globals_flows):
                self._globals(flow,_pointer(call_locator,'module_globals_flows/'+str(ni)),emit,note,query)
        for ni,flow in enumerate(shard.module_attribute_flows):
            source=point(flow.source_body,flow.source_payload,self._context(flow.source_requirements))
            target=point(flow.read.body,flow.read.result,self._context(flow.requirements))
            if query not in (source,target):continue
            guards=enums(flow.conditions)
            if flow.write is None and not any(c.name=='SOURCE_IMPORT_INITIALIZER_USES_MODULE_DICT'for c in guards):
                owner=self.session.load_body(flow.source_body).index.use_site(flow.source_owner).use.value
                if owner==flow.module.locals_namespace and owner!=flow.module.globals_namespace:
                    guards+=(Condition('scar.module-namespace','MODULE_LOCALS_ALIASES_GLOBALS'),)
                    if query in (source,target):note('MODULE_L_G_ALIAS_CONTRACT_OPEN',
                        'Original module L binding feeds a module attribute only under an unresolved module namespace alias contract.')
            emit(source,target,Kind.STATE_VALUE,Meaning.REFERENCE,_pointer(locator,'module_attribute_flows/'+str(ni)),
                guards,(point(flow.read.body,flow.read.world,target.context),),rule='STATIC_MODULE_ATTRIBUTE_VALUE_V1')
        for ni,flow in enumerate(shard.module_globals_flows):
            self._globals(flow,_pointer(locator,'module_globals_flows/'+str(ni)),emit,note,query)

    def _namespace_flow(self,flow,body,context,locator,emit):
        namespace=self._namespace(body)
        source=Point(namespace,flow.assigned_reference,context)
        target=Point(namespace,flow.read_result,context)
        emit(source,target,Kind.STATE_VALUE,Meaning.REFERENCE,locator,
            tuple(Condition.from_enum(c)for c in flow.conditions),
            (Point(namespace,flow.write_world,context),Point(namespace,flow.read_world,context)),
            rule='STATIC_NAMESPACE_BINDING_VALUE_V1')

    def _cross_namespace(self,flow,locator,query,outgoing,emit,note):
        source_namespace=self._namespace(flow.write.body);target_namespace=self._namespace(flow.read.body)
        frames=tuple(self._route_frame(bridge.environment)for bridge in flow.bridges)
        selected_endpoint=(source_namespace,flow.write.assigned_reference) if outgoing else (target_namespace,flow.read.result)
        if (query.namespace,query.node)!=selected_endpoint:return
        if query.context is not None and not context_is_closed(query.context):
            note('STATIC_RELATION_CONTEXT_PREFIX_OPEN',
                'An open interface suffix cannot authorize this saved cross-body state witness.')
            return
        if outgoing:
            source_context=query.context
            target_context=None if source_context is None else context_push(source_context,*frames)
        else:
            target_context=query.context
            if target_context is None:source_context=None
            else:
                popped=context_pop(target_context,frames)
                if not popped.matched:
                    if not context_frames(target_context):note('UNBOUND_CALL_CONTEXT','Cross-body namespace dependence requires its ordered original caller frames.')
                    return
                source_context=popped.remaining
        source=Point(source_namespace,flow.write.assigned_reference,source_context)
        target=Point(target_namespace,flow.read.result,target_context)
        anchors=[]
        for n,bridge in enumerate(flow.bridges):
            context=None if source_context is None else context_push(source_context,*frames[:n])
            anchors.append(Point(self._namespace(bridge.environment.caller),bridge.environment.call_world,context))
        emit(source,target,Kind.STATE_VALUE,Meaning.REFERENCE,locator,
            tuple(Condition.from_enum(c)for c in flow.conditions),tuple(anchors),rule='STATIC_CROSS_BODY_NAMESPACE_VALUE_V1')

    def _globals(self,flow,locator,emit,note,query):
        projection=flow.projection
        source=Point(self._namespace(projection.source_body),projection.source_payload,
            self._context(projection.source_requirements))
        target=Point(self._namespace(flow.read.body),flow.read.result,self._context(flow.requirements))
        if ((query.namespace,query.node)==(target.namespace,target.node)
                and (not context_is_closed(query.context) or not context_frames(query.context))):
            note('UNBOUND_CALL_CONTEXT','The recorded globals demand belongs to an exact caller stack; no unbound-context union is used.')
        if query not in (source,target):return
        route=projection.environment;caller_context=self._context(projection.callable_source.points[0].requirements)
        anchors=[Point(self._namespace(route.caller),route.call_world,caller_context)]
        guards=tuple(Condition.from_enum(c)for c in projection.conditions)
        guards+=tuple(dict.fromkeys(Condition.from_enum(c)for segment in flow.segments for c in segment.conditions))
        # Legacy witnesses do not carry v8's explicit import-interpretation
        # premise. Preserve their pending alias rather than upgrading them.
        if projection.write is None and not any(c.name=='SOURCE_IMPORT_INITIALIZER_USES_MODULE_DICT'for c in guards):
            owner=self.session.load_body(projection.source_body).index.use_site(projection.source_owner).use.value
            if owner==projection.module.locals_namespace and owner!=projection.module.globals_namespace:
                guards+=(Condition('scar.module-namespace','MODULE_LOCALS_ALIASES_GLOBALS'),)
                if query in (source,target):
                    note('MODULE_L_G_ALIAS_CONTRACT_OPEN','Initialized L binding is projected into function G only under an explicit unresolved alias condition.')
        emit(source,target,Kind.STATE_VALUE,Meaning.REFERENCE,locator,guards,tuple(anchors),
            rule='STATIC_MODULE_GLOBALS_VALUE_V1')


__all__=['StaticCallDependencyProvider','dependency_frame','dependency_context']
