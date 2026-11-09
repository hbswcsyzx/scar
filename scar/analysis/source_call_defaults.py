"""Current callable-default state feeding source argument binding.

The original creation expression is provenance, not a current-value alias.
Caller world and callable occurrence select a symbolic logical default slot;
the native defaults tuple/dict layout remains outside this macro interface.
"""
from collections import defaultdict
from dataclasses import replace

from scar.analysis.program_view import _digest
from scar.analysis.source_reference_slice import source_port
from scar.ir.program import source_call_defaults as D,normal_targets as T,view as V,model as M
from scar.ir.program.ids import LocationID,ValueID
from scar.ir.program.dependencies import (
    DependencyPoint as Point,DependencyEdge as Edge,DependencyCondition as Condition,
    DependencyEvidence as Evidence,DependencyKind as Kind,DependencyMeaning as Meaning,
    DependencyStrength as Strength,DependencyNeighborhood as Neighborhood,DependencyFrontier as Frontier)


class FunctionDefaultStateProvider:
    def __init__(self,view):
        self.view=view;self.addresses={};self.states={};self.reads=[];self.functions={}
        self.namespaces={};self.in_edges=defaultdict(list);self.out_edges=defaultdict(list)
        view.register(self)

    @staticmethod
    def _key(point):return point.namespace,point.node

    def _function(self,definition):
        if definition.unit not in self.functions:
            source=self.view.unit(definition.unit)
            self.functions[definition.unit]={source_port(source.facts,f.value):f for f in source.facts.functions}
        try:return self.functions[definition.unit][definition]
        except KeyError:raise ValueError('default binding lacks its original function creation fact') from None

    def _edge(self,source,target,kind,meaning,condition,locator):
        edge=Edge(source,target,kind,meaning,
            (Evidence('scar.source-call.current-default-state.v1',(locator,),(source,target)),),
            (condition,),Strength.MAY)
        if edge not in self.out_edges[self._key(source)]:
            self.out_edges[self._key(source)].append(edge);self.in_edges[self._key(target)].append(edge)

    def read(self,interface,route,frame,world):
        link=interface.link;function=self._function(link.source_callable)
        definition_source=self.view.unit(link.source_callable.unit)
        parameters=tuple(source_port(definition_source.facts,i) for i in function.formals[1:-1])
        matches=[i for i,p in enumerate(parameters) if p==route.formal]
        if len(matches)!=1:raise ValueError('default route does not select one original formal')
        index=matches[0];parameter=function.environment.parameters[index]
        initial=function.defaults[index]
        if parameter.default_source is None or initial is None:
            raise ValueError('default route lacks original creation expression')
        initial=source_port(definition_source.facts,initial)
        if route.actuals!=(initial,) or route.kind not in (T.RouteKind.INITIAL_DEFAULT,T.RouteKind.CONDITIONAL_DEFAULT):
            raise ValueError('default route differs from its original signature/default provenance')
        source=self.view.namespaces[frame.caller];namespace=source.namespace
        self.namespaces[namespace]=source
        identity=LocationID(_digest(('scar.function-default-slot.v1',source.basis,
            link.callee,link.source_callable,index,parameter)))
        slot=D.FunctionDefaultSlot(identity,link.callee,link.source_callable,index,function.parameter_names[index],parameter)
        location=Point(namespace,identity,None);self.addresses.setdefault(self._key(location),slot)
        value_id=ValueID(_digest(('scar.function-default-state.v1',identity,world)))
        state=D.FunctionDefaultState(value_id,identity,world)
        point=Point(namespace,value_id,None);self.states.setdefault(self._key(point),state)
        record=D.FunctionDefaultRead(frame.operation,identity,value_id,route.formal,initial,route.kind)
        if record not in self.reads:self.reads.append(record)
        operation=Point(namespace,frame.operation,None)
        callable=self.view.source_port(link.callee);before=self.view.source_port(world)
        if self.view.get(before).value_type.kind is not M.ValueKind.STATE:
            raise ValueError('default projection must read the original pre-call world')
        selected=Condition('scar.source-call.default','SELECTED_FUNCTION_INSTANCE_PARAMETER_AND_PRECALL_WORLD',
            operation,index,(callable,before,location))
        self._edge(callable,location,Kind.ENVIRONMENT,Meaning.STATE_INTERFACE,selected,source.locator)
        self._edge(location,point,Kind.STATE_LOCATION,Meaning.STRUCTURE,selected,source.locator)
        self._edge(before,point,Kind.PROJECTION,Meaning.STATE_INTERFACE,selected,source.locator)
        return point

    def describe(self,point):
        key=self._key(point)
        if key not in self.addresses and key not in self.states:return None
        self.namespaces[point.namespace].check(point)
        if key in self.addresses:
            return V.ProgramNode(point,V.ProgramEntityKind.STATE_LOCATION,V.ProgramNodeRole.STATE_LOCATION,None,None)
        state=self.states[key]
        return V.ProgramNode(point,V.ProgramEntityKind.VALUE,V.ProgramNodeRole.CORE_VALUE,None,
            M.ValueType(M.ValueKind.STATE,location=state.address))

    def original(self,point):
        if self.describe(point) is None:raise ValueError('default-state endpoint is not admitted')
        key=self._key(point)
        return self.addresses[key] if key in self.addresses else self.states[key]

    def expand(self,point):
        record=self.original(point)
        if type(record) is not D.FunctionDefaultSlot:return ()
        return tuple(Point(namespace,value.id,point.context) for (namespace,_),value in self.states.items()
            if namespace==point.namespace and value.address==record.id)

    def explain(self,point):
        record=self.original(point)
        return dict(node=self.describe(point),original=record,
            reads=tuple(r for r in self.reads if r.address==(record.id if type(record) is D.FunctionDefaultSlot else record.address)),
            creation_context_selected=False,current_equals_initial_proven=False,
            tensor_content_captured=False,physical_layout_asserted=False)

    def _neighbors(self,point,incoming):
        key=self._key(point);rows=(self.in_edges if incoming else self.out_edges).get(key,())
        if self.describe(point) is None:
            if not rows:return Neighborhood()
            self.view.get(point)
        edges=tuple(replace(edge,source=replace(edge.source,context=point.context),
            target=replace(edge.target,context=point.context),conditions=tuple(replace(c,
                subject=None if c.subject is None else replace(c.subject,context=point.context),
                operands=tuple(replace(p,context=point.context) for p in c.operands)) for c in edge.conditions)) for edge in rows)
        notes=(() if key not in self.states else (Frontier(point,
            'FUNCTION_DEFAULT_CREATION_INSTANCE_AND_MUTATION_HISTORY_NOT_SELECTED',
            'Current default state is read at call time; initial provenance does not prove an unchanged slot or object contents.'),))
        return Neighborhood(edges,notes)

    def incoming(self,point):return self._neighbors(point,True)
    def outgoing(self,point):return self._neighbors(point,False)
