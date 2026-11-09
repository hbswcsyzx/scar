"""Connect admitted source environments to original logical binding addresses.

The address formula is shared with SourceStateProvider. The selected frame
qualifies the callee environment; it never identifies the creator activation
or an actual outer cell. Capture references select handles, not their contents.
"""
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from scar.analysis.program_view import _digest
from scar.analysis.source_consumer_parents import _stamp
from scar.analysis.source_name_access_anchors import _bindings
from scar.analysis.source_reference_slice import ReferenceSlicer, source_port
from scar.ir.program import source_call_captures as C, source_state as S
from scar.ir.program import source_productions as P, source_bindings as B
from scar.ir.program import normal_targets as T, view as V
from scar.ir.program.source_function_interfaces import SourceFunctionInterface
from scar.ir.program.ids import LocationID, RegionID
from scar.ir.program.dependencies import (
    DependencyPoint as Point, DependencyFrame as Frame, DependencyEdge as Edge,
    DependencyCondition as Condition, DependencyEvidence as Evidence,
    DependencyKind as Kind, DependencyMeaning as Meaning, DependencyStrength as Strength,
    DependencyNeighborhood as Neighborhood, DependencyFrontier as Frontier,
    context_pop, context_is_closed)


def _require(condition, detail):
    if not condition: raise ValueError('source capture binding: '+detail)


def _index(value, size, label):
    _require(type(value) is int and 0 <= value < size, label+' lies outside original C2 material')
    return value


def _name(declarations, reference):
    if reference.kind == 'SOURCE':
        return declarations.names[_index(reference.index,len(declarations.names),'name')].value
    _require(reference.kind == 'LANGUAGE' and reference.symbol is not None,
        'binding key lacks its original source/language name reference')
    return reference.symbol


def _resolve(bindings, plan, environment, reference):
    transports = {}
    for row in plan.capture_transports:
        _require(row.reference not in transports, 'derived capture transport is duplicated')
        transports[row.reference] = row
    path = []; seen = set(); current = reference; binding = None
    while current is not None:
        _require(current not in seen, 'capture relay chain contains a cycle')
        seen.add(current)
        if type(current) is int:
            row = bindings.relays[_index(current,len(bindings.relays),'relay')]
            scope, target, parent = row.scope, row.binding, row.parent
            path.append(C.CaptureRelaySelection(current,row,None))
        else:
            _require(type(current) is P.DerivedCaptureRef and current in transports,
                'derived capture does not select one original sealed transport')
            row = transports[current]
            _require(row.reference == current and (row.compiler_slots or row.implicit_requirements),
                'derived capture lacks its original compiler/implicit witnesses')
            for witness in row.compiler_slots:
                _require(type(witness) is int and witness >= 0, 'compiler capture witness is malformed')
            scope, target, parent = current.scope, current.binding, row.parent
            for index in row.implicit_requirements:
                implicit = bindings.implicit[_index(index,len(bindings.implicit),'implicit capture requirement')]
                _require(implicit.binding == target, 'implicit capture witness names another binding')
            path.append(C.CaptureRelaySelection(current,None,row))
        _index(scope,len(bindings.scopes),'relay source scope')
        _index(target,len(bindings.bindings),'relay binding')
        if binding is None:
            _require(scope == environment.scope, 'capture does not start at its original callee source scope')
            binding = target
        _require(target == binding, 'relay path changes its original binding')
        _require(scope != bindings.bindings[target].owner, 'relay forwards inside its own binding owner')
        current = parent
    _require(path and binding is not None, 'callee capture lacks its original relay path')
    slot = bindings.bindings[binding]
    _index(slot.owner,len(bindings.scopes),'binding owner source scope')
    return binding, slot, tuple(path)


class FunctionCaptureStateProvider:
    relation_kinds = frozenset((Kind.ENVIRONMENT,))

    def __init__(self, view):
        self.view=view; self.bindings=[]; self.locations={}; self.sources={}
        self.incoming_index=defaultdict(list); self.outgoing_index=defaultdict(list)
        self._units={}; self._ids={}; self._guard={}
        view.register(self)

    @staticmethod
    def _key(point): return point.namespace,point.node

    def _unit(self, source):
        if source.unit not in self._units:
            remembered={}; bindings,declarations,materials=_bindings(source.material,remembered)
            for path,raw in remembered.items():
                before=_stamp(path)
                _require(path.read_bytes()==raw and before==_stamp(path),'C2 material changed while being admitted')
                self._guard[path]=before
            self._units[source.unit]=bindings,declarations,materials
        self.sources[source.namespace]=source
        return self._units[source.unit]

    def check(self, point=None):
        if point is not None and point.namespace in self.sources:
            self.sources[point.namespace].check(point)
        elif point is None:
            for source in self.sources.values(): source.check()
        if any(_stamp(path)!=stamp for path,stamp in self._guard.items()):
            raise ValueError('source capture original C2 materials changed')

    def bind(self, interface, env_route, frame):
        """Return handle-selection records for one NORMAL incoming interface.

        No creation-frame selection, contents read or caller/creator identity
        edge is added. Deferred creation/resume needs its separate interface.
        """
        if type(interface) is not SourceFunctionInterface or type(env_route) is not T.Route or type(frame) is not Frame:
            raise TypeError('capture binding needs original typed source interface, route and frame')
        if interface.activation is not T.FunctionActivation.NORMAL: return ()
        link=interface.link
        _require(env_route in link.parameters and env_route.kind is T.RouteKind.FUNCTION_ENVIRONMENT
            and len(env_route.actuals)==1 and type(env_route.actuals[0]) is T.GlobalPort,
            'callee environment route differs from its original interface')
        source=self.view.unit(link.source_callable.unit)
        functions=[(i,f) for i,f in enumerate(source.facts.functions)
            if source_port(source.facts,f.value)==link.source_callable]
        _require(len(functions)==1,'target is not one original source function')
        ordinal,function=functions[0]
        _require(function.environment.kind is P.DeferredBodyKind.FUNCTION
            and link.body==T.Body(source.unit,function.template,function.body)
            and function.formals and env_route.formal==source_port(source.facts,function.formals[0])
            and frame.target==source.namespace and frame.entry==source._identity(RegionID,function.template,function.body),
            'NORMAL environment/formal/body/frame differs from original function')
        if not function.environment.captures: return ()
        self.check(); source._expand((function.template,))
        plan=source.plans[function.template]
        bindings,declarations,materials=self._unit(source)
        slicer=ReferenceSlicer(SimpleNamespace(fact_store=source.material.fact_store))
        _require(interface.definition==slicer.fact(source.facts,'functions',ordinal),
            'source function fact evidence differs')
        environment=self.view.source_port(env_route.formal); records=[]
        for capture,relay in enumerate(function.environment.captures):
            binding,slot,path=_resolve(bindings,plan,function.environment,relay)
            key=_name(declarations,slot.name)
            descriptor=B.EnvironmentInterface('LEXICAL_BINDING',slot.owner,binding)
            identity=LocationID(_digest(('scar.source-binding-location.v1',source.basis,descriptor,key)))
            location=S.BindingLocationTemplate(identity,source.unit,descriptor,key)
            point=Point(source.namespace,identity,None); old=self.locations.setdefault(self._key(point),location)
            _require(old==location,'canonical captured binding address differs')
            state=self.view.state_providers.get(source.unit)
            if state is not None and identity in state.locations:
                _require(state.locations[identity]==location,'existing SourceState binding address differs')
            conditions=(*link.conditions,'CALLEE_ENVIRONMENT_SELECTS_RECORDED_RELAY_CELL_HANDLE',
                'CAPTURE_LAYOUT_AND_SOURCE_BINDING_OWNER_MATCH_SELECTED_FUNCTION')
            record=C.FunctionCaptureBinding(interface.definition,interface.call,interface.reference,link.source_callable,
                link.body,frame,env_route.formal,env_route.actuals[0],capture,relay,path,binding,slot.owner,key,
                location,materials,conditions)
            if record not in self._ids:
                index=len(self.bindings);self._ids[record]=index;self.bindings.append(record)
                self.outgoing_index[self._key(environment)].append(index)
                self.incoming_index[self._key(point)].append(index)
            records.append(record)
        self.check();return tuple(records)

    def describe(self, point):
        if self._key(point) not in self.locations:return None
        self.check(point)
        return V.ProgramNode(point,V.ProgramEntityKind.STATE_LOCATION,V.ProgramNodeRole.STATE_LOCATION,None,None)

    def original(self, point):
        if self.describe(point) is None:raise ValueError('capture binding location is not admitted')
        return self.locations[self._key(point)]

    def expand(self, point):
        location=self.original(point);state=self.view.state_providers.get(location.unit)
        return state.expand(point) if state is not None and location.id in state.locations else ()

    def explain(self, point):
        location=self.original(point)
        return dict(node=self.describe(point),original=location,
            bindings=tuple(r for r in self.bindings if r.location==location),
            creator_instance_selected=False,outer_cell_alias_proven=False,
            cell_contents_read=False,runtime_dispatch_proven=False)

    def _neighbors(self, point, incoming):
        key=self._key(point);indices=(self.incoming_index if incoming else self.outgoing_index).get(key,())
        if not indices and key not in self.locations:return Neighborhood()
        self.check(point);self.view.get(point);edges=[]
        for index in indices:
            record=self.bindings[index]
            if not context_pop(point.context,(record.frame,)).matched:continue
            source=self.view.source_port(record.environment,context=point.context)
            target=Point(source.namespace,record.location.id,point.context)
            conditions=tuple(Condition('scar.source-call.capture',name,source,index,(source,target))
                for name in record.conditions)
            evidence=Evidence('scar.source-call.captured-binding-handle.v1',
                (self.sources[source.namespace].locator,),(source,target))
            edges.append(Edge(source,target,Kind.ENVIRONMENT,Meaning.STATE_INTERFACE,(evidence,),conditions,Strength.MAY))
        reasons={'FUNCTION_CAPTURE_CREATION_INSTANCE_AND_OUTER_CELL_IDENTITY_NOT_SELECTED'}
        if indices and not edges:reasons.add('FUNCTION_CAPTURE_CALLEE_ENVIRONMENT_FRAME_NOT_SELECTED')
        if edges and not context_is_closed(point.context):reasons.add('FUNCTION_CAPTURE_CONTEXT_PREFIX_OPEN')
        return Neighborhood(tuple(dict.fromkeys(edges)),tuple(Frontier(point,reason,
            'The callee environment selects a logical cell handle; creator frame, outer cell identity and contents remain open.')
            for reason in sorted(reasons)))

    def incoming(self, point):return self._neighbors(point,True)
    def outgoing(self, point):return self._neighbors(point,False)
