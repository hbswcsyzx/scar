"""Expand annotation publication; compiler metadata is not runtime work."""
from scar.analysis.source_expression_rules import _REF
from scar.ir.program import source_productions as P
from scar.ir.program.structured import PythonProtocolKind as K


def publish(b,region,publication,world):
    facts=b.rules.source.annotation_states
    if publication.publication is P.AnnotationPublicationKind.DEFERRED and not publication.conditional_registration:
        b.slots[publication.annotation]=P.ProductionDispositionKind.METADATA
        return world
    source=publication.annotation
    if publication.publication is P.AnnotationPublicationKind.STRINGIZED:
        value,world=b.emit(region,P.DefineAnnotationString(source,b.rules.source.evaluations.stringize(source)),
            (world,),(_REF,b.world),may_raise=False,source=source)
        namespace,world=b.emit(region,P.ReadAnnotationNamespace(facts.publication_access(publication),b.rules.exception_abi),
            (world,),(_REF,b.world),source=source)
        key,world=b.literal(region,facts.key(publication),world,source=publication.name)
        world,=b.protocol(region,K.STORE_SUBSCRIPT,(namespace,key,value),world,selectors=(source,publication.name))
        released=(value,key,namespace)
    else:
        namespace,world=b.emit(region,P.ReadAnnotationNamespace(facts.publication_access(publication),b.rules.exception_abi),
            (world,),(_REF,b.world),source=source)
        parameter=facts.parameter(publication)
        indices={r.index for variant in parameter.variants for r in variant.registrations}
        if len(indices)==1:index,world=b.literal(region,indices.pop(),world,source=source)
        else:
            index,=b.emit(region,P.ReadCompilationAnnotationIndex(parameter),(),(_REF,),may_raise=False,source=source)
        world,=b.emit(region,P.AddAnnotationIndex(publication),(namespace,index,world),(b.world,),source=source)
        released=(index,namespace)
    for reference in released:
        world,=b.protocol(region,K.FRAME_RELEASE_TEMPORARY,(reference,),world)
    return world
