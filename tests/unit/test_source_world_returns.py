"""Worlds continue across returns even when the tracked reference does not."""
from types import SimpleNamespace as NS

from scar.analysis import source_world_returns as M
from scar.ir.program import normal_targets as T, normal_links as F, normal_graph as G, source_productions as P
from scar.ir.program import source_world_flow as W, source_address_paths as A
from scar.ir.program.source_template_links import SourceTemplateKey
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import encode


def test_reference_return_is_separate_from_state_return(monkeypatch):
    key = SourceTemplateKey(0, P.ProductionPurpose.VALUE)
    ports = tuple(G.Port(key, P.ProductionRegionID('r'), G.PortKind.PARAMETER, i) for i in range(40))
    units = {name: NS(unit=name, ports=ports) for name in ('a', 'b', 'c')}
    gp = lambda name, i: T.GlobalPort(name, ports[i])
    def function(name):
        return NS(value=7, template=key, body=P.ProductionRegionID('body'), formals=(1, 2, 3), returns=4,
            return_world=5, body_scope=NS(owner=F.CodeScopeRef(name, 0)), environment=NS(kind=P.DeferredBodyKind.FUNCTION))
    functions = {name: function(name) for name in units}
    artifact = ProviderArtifact('/source/parent', '0'*64, 0, 'test')
    evidence = ProviderFactReference(artifact, '#/records/0')
    def flow(name, anchor):
        return W.SourceWorldFlow(evidence, artifact, name, T.Body(name, key, functions[name].body),
            anchor, gp(name, 5), (), (), (), True, ())
    calls = {name: F.Call(10, (), (), 11, 12, 13) for name in ('b', 'c')}
    def connection(source, target):
        return T.FunctionConnection(gp(source, 7), T.Body(source, key, functions[source].body), T.FunctionActivation.NORMAL,
            (T.Route(gp(source, 3), T.RouteKind.STATE, (gp(target, 12),)),),
            ((gp(source, 4), gp(target, 11)), (gp(source, 5), gp(target, 13))), ())
    class Interfaces:
        # b is an already admitted compiled-context caller. Its original
        # world-argument/return routes remain usable through the common F4 API.
        slicer = NS(store=NS(original_source_units={'b':'original-b'}))
        snapshot = NS(catalog=None, validate_parents=lambda: None)
        def function(self, point): return units[point.unit], functions[point.unit]
        def caller(self, unit, index): return functions[unit.unit]
        def parents(self, point, context):
            target = {'a': 'b', 'b': 'c'}.get(point.unit)
            if target:
                yield units[target], 0, calls[target], connection(point.unit, target), evidence, evidence, None
    class Addresses:
        def __init__(self, store, unit, scope): self.unit = unit
        def paths(self, local, **kwargs):
            # a returns its tracked object; b returns an unrelated call result.
            root = gp('a', 0) if self.unit.unit == 'a' else gp('b', 30)
            return (A.AddressPath(root, A.AddressRootKind.CALL_RESULT, (), (), ('SELECTED_SOURCE_PATH',)),)
    material_units=[]
    def material(catalog,unit):
        material_units.append(unit)
        return None
    monkeypatch.setattr(M, '_caller_material', material)
    monkeypatch.setattr(M, 'project_world_flow', lambda material, body, witness, anchor, end, **kw: flow(body.unit, anchor))
    monkeypatch.setattr(M, 'AddressResolver', Addresses)
    graph = M.compose_returns(Interfaces(), ((gp('a', 7), None, gp('a', 0), flow('a', gp('a', 8))),))
    assert len(graph.nodes) == 3 and len(graph.edges) == 2
    assert material_units == ['b','c']
    assert not any(f.reason == 'COMPILED_CALLER_WORLD_MATERIAL_ADAPTER_PENDING' for f in graph.frontiers)
    first, second = graph.edges
    assert first.reference_forwarded and not second.reference_forwarded
    assert graph.nodes[first.caller].tracked_reference == gp('b', 11)
    assert graph.nodes[second.caller].tracked_reference is None
    assert second.state_return == (gp('b', 5), gp('c', 13))
    assert second.data_return == (gp('b', 4), gp('c', 11))
    assert 'WORLD_RETURN_IS_NOT_CONTENT_PRESERVATION' in second.conditions
    assert any(f.reason == 'TRACKED_REFERENCE_RETURN_PATH_UNRESOLVED' for f in graph.frontiers)
    # Two different source functions in one unit share one complete table scan.
    units['b'].__dict__.update(aliases=(), names=(), functions=(), constants=(), classes=(), calls=(calls['b'],))
    store = NS(load=lambda identity: units[identity],
        rows={'b': dict(facts='/source/b.json.gz', sha256='0'*64, bytes=0)})
    links = tuple(T.CallLink(gp('b', 11), gp('b', 10), gp('a', f), T.Body('a', key, functions['a'].body),
        'SOURCE_FUNCTION', None) for f in (7, 17))
    class Snapshot:
        fact_store = store
        scans = 0
        def rows(self, table, predicate, record_type):
            self.scans += 1
            return tuple((i, link, evidence) for i, link in enumerate(links) if predicate(encode(link)))
    snapshot = Snapshot()
    parents = M.ReturnInterfaces(snapshot, '/source', {}, None, '/source', {}, ())
    assert len(tuple(parents.parents(gp('a', 7), None))) == 1
    assert len(tuple(parents.parents(gp('a', 17), None))) == 1
    assert snapshot.scans == 1
