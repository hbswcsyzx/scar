"""Symbolic selectors preserve dynamic keys, lookup scope and opaque calls."""
from types import SimpleNamespace as NS

from scar.analysis.source_address_paths import AddressResolver
from scar.analysis.source_reference_slice import source_port
from scar.ir.program import normal_links as F, normal_graph as G, source_productions as P
from scar.ir.program import source_address_paths as A
from scar.ir.program.source_template_links import SourceTemplateKey
from scar.ir.record_codec import encode, decode


def test_paths_keys_scope_and_call_results_are_distinct():
    key = SourceTemplateKey(0, P.ProductionPurpose.VALUE)
    ports = tuple(G.Port(key, P.ProductionRegionID('r'), G.PortKind.PARAMETER, i) for i in range(40))
    scope = F.CodeScopeRef('unit', 7); foreign = F.CodeScopeRef('unit', 9)
    binding = F.Namespace(F.NamespaceKind.LEXICAL, 88, 'data')
    different = F.Namespace(F.NamespaceKind.LEXICAL, 99, 'data')
    names = (F.NameAccess(binding, 0, True), F.NameAccess(binding, 1, False),
        F.NameAccess(binding, 32, True), F.NameAccess(different, 8, False))
    unit = NS(unit='unit', ports=ports, aliases=((1, 2), (6, 7), (10, 11), (11, 10)), names=names,
        functions=(NS(value=35, formals=(38, 0, 39), body_scope=NS(owner=scope)),), classes=(), constants=(),
        attributes=(F.Attribute(2, 'slot', 3, F.AttributeAction.GET, 25, 26),),
        items=(F.ItemAccess(3, 4, 5, False, 25, 26),),
        calls=(F.Call(30, (0,), (), 6, 25, 26),),
        scope_groups=(F.FactScopeGroup(scope, (F.FactRange(F.FactTable.NAMES, 0, 2), F.FactRange(F.FactTable.NAMES, 3, 4))),
            F.FactScopeGroup(foreign, (F.FactRange(F.FactTable.NAMES, 2, 3),))))
    store = NS(load=lambda identity: unit, _source_parents={},
        rows={'unit': dict(facts='/source/facts.gz', sha256='0'*64, bytes=0)})
    resolver = AddressResolver(store, unit, scope)
    paths = resolver.paths(5, max_depth=32)
    path = next(p for p in paths if p.root_kind is A.AddressRootKind.FUNCTION_PARAMETER)
    assert path.root == source_port(unit, 0)
    assert path.selectors == (A.FieldSelector('slot'), A.ItemSelector(source_port(unit, 4)))
    assert decode(A.AddressPath, encode(path, record_tags=P.PRODUCTION_RECORD_TAGS), record_tags=P.PRODUCTION_RECORD_TAGS) == path
    assert any(p.frontier == 'CAPTURE_CONTEXT_UNRESOLVED' for p in paths)
    assert all(p.root_kind is A.AddressRootKind.OPEN_PRODUCER for p in resolver.paths(8))
    returned = resolver.paths(7)
    assert len(returned) == 1 and returned[0].root_kind is A.AddressRootKind.CALL_RESULT
    assert returned[0].root == source_port(unit, 6)  # Never alias call result to its input.
    assert any(p.frontier == 'REFERENCE_CYCLE_UNRESOLVED' for p in resolver.paths(10))
    assert any(p.frontier == 'ADDRESS_STATE_BUDGET_FRONTIER' for p in resolver.paths(5, max_states=1))
