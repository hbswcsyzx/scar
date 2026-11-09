"""Namespace sources retain duplicate providers and distinct import branches."""
from types import SimpleNamespace as NS

from scar.analysis.source_namespace_references import NamespaceReferenceResolver
from scar.ir.program import source_namespace_references as N, normal_links as F, normal_graph as G
from scar.ir.program import source_productions as P, normal_targets as T
from scar.ir.program.source_template_links import SourceTemplateKey
from scar.ir.record_codec import encode, decode


def test_returned_module_exports_and_import_from_fallback_are_not_aliases():
    key=SourceTemplateKey(0,P.ProductionPurpose.VALUE); region=P.ProductionRegionID('source')
    ports=tuple(G.Port(key,region,G.PortKind.PARAMETER,i) for i in range(12))
    gp=lambda unit,i:T.GlobalPort(unit,ports[i])
    def unit(name,namespace,class_value=None):
        names=() if class_value is None else (F.NameAccess(F.Namespace(F.NamespaceKind.MODULE,0,'C'),class_value,True),)
        scopes=() if not names else (F.FactScopeGroup(F.CodeScopeRef(name,0),(F.FactRange(F.FactTable.NAMES,0,1),)),)
        return NS(unit=name,ports=ports,aliases=(),names=names,functions=(),constants=(),
            classes=() if class_value is None else (NS(value=class_value),),scope_groups=scopes,
            attributes=(),imports=(),module=namespace)
    units={'caller':unit('caller','main'), 'a':unit('a','lib',5), 'b':unit('b','lib',6),
        'sub':unit('sub','lib.sub',7),'compiled':unit('compiled','lib',8)}
    caller=units['caller'];caller.imports=(F.Import(0,'lib','lib.sub'),F.Import(2,'lib','lib'))
    caller.attributes=(F.Attribute(0,'C',1,F.AttributeAction.GET,9,10),
        F.Attribute(2,'C',3,F.AttributeAction.IMPORT_MEMBER,9,10))
    rows={name:dict(module=value.module,facts='/source/'+name+'.json',sha256='0'*64,bytes=0) for name,value in units.items()}
    store=NS(load=lambda name:units[name],rows=rows,model_units={name:{} for name in units},
        importable_units=frozenset(units)-{'compiled'},original_source_units={'compiled':'caller'})
    snapshot=NS(fact_store=store,validate_parents=lambda:None)
    resolver=NamespaceReferenceResolver(snapshot)
    normal=resolver.resolve(gp('caller',1)); imported=resolver.resolve(gp('caller',3))
    def classes(graph):
        return {graph.states[o.state].port for o in graph.origins if o.kind is N.NamespaceOriginKind.CLASS_DEFINITION}
    assert classes(normal)==classes(imported)=={gp('a',5),gp('b',6)}
    assert not any(o.kind is N.NamespaceOriginKind.MODULE_CANDIDATE for o in normal.origins)
    assert any(o.symbol=='lib.C' for o in imported.origins if o.kind is N.NamespaceOriginKind.MODULE_CANDIDATE)
    assert all(o.symbol!='lib.sub.C' for o in imported.origins)
    assert normal.frontiers and imported.frontiers  # provider/slot versions stay open
    assert any(e.kind is N.NamespaceEdgeKind.MODULE_EXPORT for e in normal.edges)
    assert any(e.kind is N.NamespaceEdgeKind.ATTRIBUTE_RECEIVER for e in normal.edges)
    assert decode(N.NamespaceReferenceSlice,encode(imported))==imported
