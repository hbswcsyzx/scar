"""One generic graph covers balanced calls, custom new, and field candidates."""
from types import SimpleNamespace

from scar.analysis.source_reference_slice import ReferenceSlicer
from scar.ir.program import normal_targets as T, normal_links as F, normal_graph as G
from scar.ir.program import source_productions as P
from scar.ir.program.source_template_links import SourceTemplateKey
from scar.ir.record_codec import encode


def test_balanced_returns_custom_new_and_conditional_field_flow():
    key = SourceTemplateKey(0, P.ProductionPurpose.VALUE)
    ports = tuple(G.Port(key, P.ProductionRegionID('r'), G.PortKind.PARAMETER, i) for i in range(20))
    gp = lambda i: T.GlobalPort('unit', ports[i])
    body = T.Body('unit', key, P.ProductionRegionID('fn'))
    fn = SimpleNamespace(value=18, template=key, body=body.region, formals=(6,))
    def invoke(result, actual, target=None, mode='SOURCE_FUNCTION'):
        return T.CallLink(gp(result), gp(17), gp(18), body, mode, None,
            (T.Route(gp(6), T.RouteKind.ARGUMENT, (gp(actual),)),),
            ((gp(7), gp(result) if target is None else target),), binding=T.ArgumentBinding.DIRECT)
    new = T.ConstructionPort(gp(11), gp(12), T.ConstructionPortKind.NEW_RESULT)
    calls = [invoke(8, 0), invoke(9, 1), invoke(11, 0, new, 'SOURCE_NEW')]
    constructions = [T.ConstructionLink(gp(i), gp(17), gp(12), T.ConstructionStage.EXPLICIT_OBJECT_NEW,
        (), (gp(i),), None, ()) for i in (0, 1)]
    constructions.append(T.ConstructionLink(gp(11), gp(17), gp(12), T.ConstructionStage.RETURN_FOREIGN,
        (new,), (gp(11),), None, ('NEW_RESULT_IS_NOT_CLASS_INSTANCE',)))
    attributes = (F.Attribute(2, 'slot', 4, F.AttributeAction.SET, 13, 14),
        F.Attribute(3, 'slot', 5, F.AttributeAction.GET, 15, 16),
        F.Attribute(1, 'slot', 10, F.AttributeAction.SET, 13, 14))
    unit = SimpleNamespace(unit='unit', ports=ports, aliases=((0, 2), (0, 3), (6, 7)),
        names=(), functions=(fn,), constants=(), classes=(), attributes=attributes)
    store = SimpleNamespace(load=lambda identity: unit,
        rows={'unit': dict(facts='/source/facts.json.gz', sha256='0'*64, bytes=0)})
    class Snapshot:
        fact_store = store
        def rows(self, name, predicate, record_type):
            from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
            artifact = ProviderArtifact('/source/'+name, '0'*64, 0, 'test')
            records = calls if name == 'calls' else constructions
            return tuple((i, item, ProviderFactReference(artifact, '#/records/'+str(i)))
                for i, item in enumerate(records) if predicate(encode(item)))
        def validate_parents(self): pass
    slicer = ReferenceSlicer(Snapshot())
    def roots(result):
        return {result.states[o.state].port for o in result.origins if o.kind == 'ALLOCATION_SITE_CANDIDATE'}
    assert roots(slicer.slice(gp(8))) == {gp(0)}
    assert roots(slicer.slice(gp(9))) == {gp(1)}
    # A custom __new__ returning its input is not a fresh allocation.
    assert roots(slicer.slice(gp(11))) == {gp(0)}
    slices, flows, domain = slicer.fields('unit', 1)
    assert len(flows) == 1 and domain == ('unit',)
    flow = flows[0]
    assert flow.write_site.assigned == gp(4) and flow.read_site.result == gp(5)
    assert flow.write_site.world == gp(13) and flow.read_site.world == gp(15)
    assert 'SAME_DYNAMIC_RECEIVER_INSTANCE_AND_INVOCATION_SELECTED' in flow.conditions
    assert 'MAY_REACHING_STORE_NOT_SELECTED_STATE_VERSION' in flow.conditions
    assert roots(slices[flow.write_slice]) == roots(slices[0]) == {gp(0)}
    assert any(f.reason == 'REFERENCE_STATE_BUDGET_FRONTIER' for f in slicer.slice(gp(8), max_states=1).frontiers)
