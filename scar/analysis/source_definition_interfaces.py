"""Class and alias source interfaces; no runtime namespace or metaclass guess."""
from scar.ir.program import source_productions as P


def _require(condition,path,detail):
    if not condition:
        from scar.analysis.source_productions import ProductionError
        raise ProductionError('DEFINITION_INTERFACE',str(path),detail)


class DefinitionInterfaceIndex:
    def __init__(self,source):
        self.source=source
        self.classes={s.owner.occurrence:i for i,s in enumerate(source.context.material.scopes) if s.kind=='CLASS'}
        self.protocols={scope:[] for scope in self.classes.values()}
        for i,binding in enumerate(source.frontend.bindings.bindings):
            if binding.domain=='CLASS_PROTOCOL':self.protocols[binding.owner].append(i)

    def class_body(self,owner,world,exception_abi):
        _require(owner in self.classes,owner,'class requires its original C1 child scope')
        scope=self.classes[owner]
        protocols=tuple(self.protocols[scope])
        params=(P.SlotRef(owner,'FIELD',self.source.roles.fields['ClassDef']['type_params'])
            if self.source.roles.field(owner,'type_params').items else None)
        return P.ClassBodyInterface(scope,self.source.context.material.root_context.environment,
            tuple(self.source.deferred.captures[scope]),protocols,self.source.statements.declaration_docstring(owner),
            params,world,exception_abi)

    def alias(self,owner,exception_abi):
        roles=self.source.roles;nodes=self.source.context.syntax.nodes
        _require(nodes[owner].constructor=='TypeAlias',owner,'alias requires an original TypeAlias declaration')
        target=roles.field(owner,'name').reference
        _require(nodes[target].constructor=='Name',owner,'alias binder must be an original Name')
        name=P.SlotRef(target,'FIELD',roles.fields['Name']['id'])
        source=P.SlotRef(owner,'FIELD',roles.fields['TypeAlias']['value'])
        expression=self.source.type_parameters.lazy(source)
        params=P.SlotRef(owner,'FIELD',roles.fields['TypeAlias']['type_params']) if roles.field(owner,'type_params').items else None
        return P.BuildTypeAlias(name,expression,params,exception_abi)
