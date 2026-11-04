"""Type-parameter scopes and lazy requests over original F2/F3 references."""
from collections import defaultdict
from scar.ir.program import source_productions as P


def _require(condition,path,detail):
    if not condition:
        from scar.analysis.source_productions import ProductionError
        raise ProductionError('TYPE_PARAMETER_INTERFACE',str(path),detail)


class TypeParameterInterfaceIndex:
    def __init__(self,source):
        self.source=source
        self.scopes={scope.owner.occurrence:i for i,scope in enumerate(source.context.material.scopes) if scope.kind=='TYPE_PARAMETERS'}
        self.ports=defaultdict(list)
        for i,port in enumerate(source.frontend.roles.ports):self.ports[port.site].append(i)
        self._specs={}

    def lazy(self,site,*,allow_starred=False):
        _,value=self.source.roles.locate(site)
        if value.kind!='NODE':return None
        context=self.source.context.context_at_slot(site).state
        scope=self.source.context.material.scopes[context.environment]
        _require(scope.kind in ('TYPE_PARAMETER_EVALUATOR','TYPE_ALIAS') and scope.anchor==site,site,
            'lazy expression requires its original type-parameter/alias evaluator scope')
        starred=self.source.context.syntax.nodes[value.reference].constructor=='Starred'
        _require(not starred or allow_starred,site,'starred evaluator is permitted only for TypeVarTuple defaults')
        return P.LazyExpressionInterface(site,context.environment,
            tuple(self.source.deferred.captures[context.environment]),starred)

    def spec(self,occurrence):
        if occurrence in self._specs:return self._specs[occurrence]
        roles=self.source.roles;nodes=self.source.context.syntax.nodes
        kind=nodes[occurrence].constructor
        kinds={'TypeVar':P.TypeParameterKind.TYPE_VAR,'TypeVarTuple':P.TypeParameterKind.TYPE_VAR_TUPLE,'ParamSpec':P.TypeParameterKind.PARAM_SPEC}
        _require(kind in kinds,occurrence,'expected an original type-parameter constructor')
        name=P.SlotRef(occurrence,'FIELD',roles.fields[kind]['name'])
        scope=self.source.context.entry_context(occurrence).environment
        data=self.source.frontend.bindings;decl=self.source.frontend.declarations
        ports=[]
        for p in self.ports[name]:
            port=data.ports[p]
            if port.declref is None or port.resolution is None:continue
            binding=data.resolutions[port.resolution].binding
            if 'TYPE_PARAMETER_INTERFACE' in decl.contributions[port.declref].operations and binding is not None and data.bindings[binding].owner==scope:
                ports.append(p)
        _require(len(ports)==1,name,'type parameter needs one original declaration/resolution interface')
        bound=self.lazy(P.SlotRef(occurrence,'FIELD',roles.fields[kind]['bound'])) if kind=='TypeVar' else None
        default=self.lazy(P.SlotRef(occurrence,'FIELD',roles.fields[kind]['default_value']),allow_starred=kind=='TypeVarTuple')
        constraints=bound is not None and nodes[roles.locate(bound.source)[1].reference].constructor=='Tuple'
        result=P.TypeParameterSpec(name,kinds[kind],ports[0],bound,default,constraints)
        self._specs[occurrence]=result
        return result

    def environment(self,owner,world,exception_abi):
        _require(owner in self.scopes,owner,'definition has no original type-parameter scope')
        roles=self.source.roles;nodes=self.source.context.syntax.nodes
        parameters=tuple(self.spec(item.reference) for item in roles.field(owner,'type_params').items)
        _require(bool(parameters),owner,'type-parameter factory requires nonempty original parameters')
        seen=False
        for p in parameters:
            _require(not seen or p.default is not None,p.name,'non-default type parameter follows a default')
            seen|=p.default is not None
        inputs=(tuple(p.default_source for p in self.source.deferred.parameters(owner) if p.default_source is not None)
            if nodes[owner].constructor in ('FunctionDef','AsyncFunctionDef') else ())
        scope=self.scopes[owner]
        return P.TypeParameterEnvironment(scope,tuple(self.source.deferred.captures[scope]),parameters,inputs,world,exception_abi,
            self.source.capture_paths.owned_cells(scope))
