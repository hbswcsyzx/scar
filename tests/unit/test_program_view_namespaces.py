"""Registered evidence graphs remain queryable beside source/core graphs."""
import pytest
from scar.analysis.program_view import ProgramView
from scar.ir.program.dependencies import GraphNamespace,DependencyPoint,DependencyNeighborhood
from scar.ir.program.ids import RegionID
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program import view as V


@pytest.mark.parametrize('core_attached',(False,True))
def test_owned_evidence_namespace_uses_its_adapter(core_attached):
    def core_loader(namespace):
        raise AssertionError('an evidence namespace must not be sent to the canonical loader')
    view=ProgramView(None,core_loader=core_loader if core_attached else None)
    artifact=ProviderArtifact('/evidence/result.json','0'*64,1,'test.evidence')
    namespace=GraphNamespace(SourceArtifactLocator(artifact,'0'*64,1,'canonical-json'),
        'test.evidence.v1',RegionID('evidence'))
    point=DependencyPoint(namespace,namespace.root,None)
    class Evidence:
        owned_namespaces=(namespace,)
        def describe(self,p):
            return V.ProgramNode(p,V.ProgramEntityKind.REGION,V.ProgramNodeRole.PROVIDER,None,None) if p==point else None
        def original(self,p):return {'code':'known','body':None}
        def expand(self,p):return ()
        def explain(self,p):return {'body_unresolved':True}
        def incoming(self,p):return DependencyNeighborhood()
        def outgoing(self,p):return DependencyNeighborhood()
    view.register(Evidence())
    assert view.get(point).kind is V.ProgramEntityKind.REGION
    assert view.original(point)=={'code':'known','body':None}
    assert view.expand(point)==()
    assert view.explain(point)['body_unresolved'] is True
    assert not view.producers(point).edges and not view.consumers(point).edges
