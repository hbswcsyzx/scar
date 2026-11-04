"""Annotation namespace origins and finite compiler inputs over original IDs."""
from scar.ir.program import source_productions as P


def _require(condition,path,detail):
    if not condition:
        from scar.analysis.source_productions import ProductionError
        raise ProductionError('ANNOTATION_STATE_INTERFACE',str(path),detail)


class AnnotationStateIndex:
    def __init__(self,source):
        self.source=source;self._parameters={}

    def access(self,creator,name,*,request=False):
        source=self.source;kind=source.context.material.scopes[creator].kind
        _require(kind in ('ROOT_EXEC','ROOT_INTERACTIVE','CLASS'),creator,'annotation state requires its original class/root scope')
        if name is P.AnnotationStateName.CONDITIONAL and kind=='CLASS':
            rows=[(i,r) for i,r in enumerate(source.frontend.bindings.implicit)
                if r.scope==creator and source.frontend.namespace.name(r.name)==name.value and r.binding is not None]
            _require(len(rows)==1,creator,'class registry requires its original implicit protocol binding')
            index,row=rows[0];binding=source.frontend.bindings.bindings[row.binding]
            _require(binding.owner==creator and binding.domain=='CLASS_PROTOCOL',creator,'registry must use the original class protocol cell')
            return P.AnnotationStateAccess(creator,P.AnnotationLookupKind.CLASS_PROTOCOL_CELL,name,row.binding,index,row.read_plan)
        lookup=P.AnnotationLookupKind.GLOBALS_CHAIN if request else P.AnnotationLookupKind.LOCALS_CHAIN
        return P.AnnotationStateAccess(creator,lookup,name)

    def publication_access(self,publication):
        scope=self.source.context.entry_context(publication.annotation.occurrence).environment
        name=(P.AnnotationStateName.ANNOTATIONS if publication.publication is P.AnnotationPublicationKind.STRINGIZED
            else P.AnnotationStateName.CONDITIONAL)
        return self.access(scope,name)

    def request_access(self,scope):
        creator=self.source.context.material.scopes[scope].parent
        return self.access(creator,P.AnnotationStateName.CONDITIONAL,request=True)

    def key(self,publication):
        source=self.source
        names={source.frontend.declarations.names[row.name].value for i,row in enumerate(source.frontend.declarations.ports)
            if source.frontend.roles.ports[i].site==publication.name and row.name is not None}
        _require(len(names)==1,publication.name,'annotation key needs its original projected declaration name')
        return names.pop()

    def parameter(self,publication):
        _require(publication.publication is P.AnnotationPublicationKind.DEFERRED and publication.conditional_registration,
            publication.annotation,'only conditional declarations have compiler registration indices')
        if publication in self._parameters:return self._parameters[publication]
        scope=self.source.context.context_at_slot(publication.annotation).state.environment
        request=self.source.scope_annotations.request(scope);variants=[]
        for variant in request.variants:
            selected=tuple(e.registration for e in variant.entries if e.source==publication.annotation and e.registration is not None)
            _require(bool(selected),publication.annotation,'compiler query omitted a conditional source registration')
            status,sites,unverified=self.source.compilation_contexts.sites(scope,variant.optimization_level,emitted=variant.emitted_in_original_unit)
            variants.append(P.AnnotationEmissionVariant(variant.optimization_level,selected,variant.emitted_in_original_unit,
                tuple(site for site in sites if site.registration in selected),status,unverified))
        result=P.AnnotationEmissionParameter(publication,tuple(variants));self._parameters[publication]=result
        return result

    def verify_access(self,access,*,request=False):
        _require(access==self.access(access.scope,access.name,request=request),access,
            'namespace/cell source or original implicit/read-plan reference differs')
        return access
