"""Shared recursive bodies and Python descriptor binding stay distinct."""
from types import SimpleNamespace as NS
from dataclasses import replace

from scar.analysis.source_declared_contexts import DeclaredResolver, expand_contexts, BUILTIN_GUARDS
from scar.analysis.source_reference_slice import ReferenceSlicer, source_port
from scar.ir.program import declared_contexts as D, normal_links as F, normal_targets as T
from scar.ir.program import normal_graph as G, source_productions as P
from scar.ir.program.source_template_links import SourceTemplateKey
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference


def test_recursive_body_staticmethod_classmethod_and_shadow_guards():
    key = SourceTemplateKey(0, P.ProductionPurpose.VALUE)
    ports = tuple(G.Port(key, P.ProductionRegionID('region'), G.PortKind.PARAMETER, i) for i in range(100))
    def fn(value, formal, scope):
        return NS(value=value, template=key, body=P.ProductionRegionID('body'+str(scope)),
            formals=(formal-1, formal, formal+1), parameter_names=('parameter',), defaults=(None,),
            environment=NS(parameters=(NS(kind=P.DeferredParameterKind.POSITIONAL_OR_KEYWORD),),
                kind=P.DeferredBodyKind.FUNCTION), returns=formal+2, return_world=formal+3,
            body_scope=NS(owner=F.CodeScopeRef('unit', scope)))
    functions = (fn(10, 12, 0), fn(20, 22, 1), fn(30, 32, 2), fn(60, 62, 3))
    names = (
        F.NameAccess(F.Namespace(F.NamespaceKind.LEXICAL, 100, 'same_name'), 12, True),
        F.NameAccess(F.Namespace(F.NamespaceKind.LEXICAL, 100, 'same_name'), 52, False),
        F.NameAccess(F.Namespace(F.NamespaceKind.LEXICAL, 200, 'same_name'), 22, True),
        F.NameAccess(F.Namespace(F.NamespaceKind.LEXICAL, 200, 'same_name'), 82, False),
        F.NameAccess(F.Namespace(F.NamespaceKind.CLASS, 90, 'f'), 20, True),
        F.NameAccess(F.Namespace(F.NamespaceKind.CLASS, 90, 's'), 45, True),
        F.NameAccess(F.Namespace(F.NamespaceKind.CLASS, 90, 'c'), 75, True),
        F.NameAccess(F.Namespace(F.NamespaceKind.CLASS, 90, 'staticmethod'), 46, False),
        F.NameAccess(F.Namespace(F.NamespaceKind.MODULE, 0, 'staticmethod'), 46, False),
        F.NameAccess(F.Namespace(F.NamespaceKind.BUILTINS, 0, 'staticmethod'), 46, False),
        F.NameAccess(F.Namespace(F.NamespaceKind.BUILTINS, 0, 'classmethod'), 76, False),
    )
    attrs = (F.Attribute(52, 'f', 53, F.AttributeAction.GET, 55, 56),
        F.Attribute(52, 's', 57, F.AttributeAction.GET, 55, 56),
        F.Attribute(52, 'c', 58, F.AttributeAction.GET, 55, 56),
        F.Attribute(82, 'f', 83, F.AttributeAction.GET, 85, 86))
    calls = (F.Call(53, (), (), 54, 55, 56), F.Call(57, (50,), (), 59, 55, 56),
        F.Call(58, (), (), 69, 55, 56), F.Call(83, (), (), 84, 85, 86),
        F.Call(46, (30,), (), 45, 47, 48), F.Call(76, (60,), (), 75, 77, 78))
    groups = (F.FactScopeGroup(F.CodeScopeRef('unit', 0),
        (F.FactRange(F.FactTable.NAMES, 0, 2), F.FactRange(F.FactTable.CALLS, 0, 3))),
        F.FactScopeGroup(F.CodeScopeRef('unit', 1),
        (F.FactRange(F.FactTable.NAMES, 2, 4), F.FactRange(F.FactTable.CALLS, 3, 4))))
    unit = NS(unit='unit', ports=ports, aliases=(), names=names, functions=functions,
        classes=(NS(value=0, scope=90),), constants=(), attributes=attrs, calls=calls, scope_groups=groups)
    store = NS(load=lambda identity: unit, offsets={'unit': 0}, original_source_units={},
        locate=lambda point: ('unit', point), rows={'unit': dict(facts='/source/facts.json.gz', sha256='0'*64, bytes=0)})
    slicer = ReferenceSlicer(NS(fact_store=store))
    resolver = DeclaredResolver(slicer); gp = lambda i: source_port(unit, i)
    root = D.DeclaredContext(gp(10), T.Body('unit', key, functions[0].body),
        (D.ClassInput(gp(12), gp(0), D.ClassValueKind.INSTANCE),))
    evidence = ProviderFactReference(ProviderArtifact('/parent', '0'*64, 0, 'test'), '#/method/0')
    entry = T.FunctionConnection(gp(10), root.body, T.FunctionActivation.NORMAL,
        (T.Route(gp(12), T.RouteKind.ARGUMENT, (gp(52),)),), (), ())
    graph = expand_contexts(resolver, ((root, entry, evidence),))
    assert len(graph.contexts) == 4 and len(graph.edges) == 4
    assert any(e.caller == e.target for e in graph.edges)  # Shared recursion; no unrolling.
    static = next(e for e in graph.edges if e.descriptor.kind is D.DescriptorKind.STATICMETHOD)
    route = next(r for r in static.connection.parameters if r.kind is T.RouteKind.ARGUMENT)
    assert route.formal == gp(32) and route.actuals == (gp(50),)  # No implicit self.
    assert set(BUILTIN_GUARDS) <= set(static.conditions)  # CLASS/MODULE shadows cannot be ignored.
    classmethod = next(e for e in graph.edges if e.descriptor.kind is D.DescriptorKind.CLASSMETHOD)
    assert graph.contexts[classmethod.target].class_inputs == (
        D.ClassInput(gp(62), gp(0), D.ClassValueKind.CLASS_OBJECT),)
    creation = expand_contexts(resolver, ((root, replace(entry, activation=T.FunctionActivation.CREATE_DEFERRED_BODY), evidence),))
    assert len(creation.contexts) == 1 and not creation.edges
    assert creation.frontiers[0].reason == 'DEFERRED_BODY_CREATION_IS_NOT_BODY_ENTRY'
