"""One source-to-call-graph check; the example program is never executed."""
from collections import deque

from scar.analysis.normal_links import _Facts, _Aliases
from scar.analysis.normal_targets import _Solver
from scar.analysis.source_productions import production_plan_document
from scar.analysis.source_root_rules import SourceRootRules
from scar.analysis.source_statement_rules import SourceStatementRules
from scar.analysis.source_template_links import build_template_graph
from scar.ir.program import normal_links as F, normal_targets as T, source_productions as P
from scar.ir.program.protocol_signatures import ExceptionABI
from scar.ir.program.source_template_links import SourceMaterialDomain as D
from scar.ir.record_codec import decode, encode
from tests.unit.test_source_expression_rules import _documents, _rules, purpose, WORLD


def source_facts(text, *, protocols=False):
    documents = _documents(text)
    expressions = _rules(documents)
    source = expressions.source
    statements = SourceStatementRules(source, world=WORLD, exception_abi=ExceptionABI.EXCEPTION_WORLD)
    roots = SourceRootRules(source, world=WORLD, exception_abi=ExceptionABI.EXCEPTION_WORLD)
    records, plans, pending, seen = [], {}, deque(), set()

    def add(domain, plan):
        line = len(records) + 1
        records.append((domain, line, production_plan_document(plan)))
        plans[domain, line] = plan
        for step in plan.steps:
            ins = step.instruction
            if type(ins) is P.EvaluateChild and ins.purpose is P.ProductionPurpose.CONDITION:
                occurrence = source.roles.locate(ins.field)[1].reference
                if occurrence not in seen:
                    seen.add(occurrence)
                    pending.append(occurrence)

    schema = {r.name: r.bases for r in source.context.syntax.profile.ast_schema}
    for occurrence, node in enumerate(source.context.syntax.nodes):
        if 'stmt' in schema[node.constructor] and statements.descriptor_owner(occurrence) is None:
            add(D.STATEMENTS, statements.build(occurrence))
        elif 'expr' in schema[node.constructor] and expressions.descriptor_owner(occurrence) is None:
            add(D.EXPRESSIONS, expressions.build(occurrence, purpose(expressions, occurrence)))
    add(D.ROOTS, roots.build(0))
    while pending:
        add(D.EXPRESSIONS, expressions.build(pending.popleft(), P.ProductionPurpose.CONDITION))
    graph = build_template_graph('construction-check', documents[2], iter(records))
    interfaces = dict(nodes={n.key: n for n in graph.templates}, links={(e.caller, e.step): e for e in graph.links})
    unit = dict(key='construction-check', path=documents[0]['path'])
    facts = _Facts(unit, documents[2], documents[6], documents[5], documents[3], documents[4])
    for node in graph.templates:
        emitter = _Aliases(plans[node.origin.domain, node.origin.line], node.key, interfaces, facts)
        emitter.run()
        emitter.describe()
    aliases = tuple(sorted(facts.aliases))
    names = ('ports', 'names', 'functions', 'classes', 'attributes', 'imports', 'constants', 'calls',
             'containers', 'items', 'updates', 'iterations', 'operations', 'activations')
    tables = {name: tuple(getattr(facts, name)) for name in names}
    result=F.UnitFacts(unit=unit['key'], module='construction_check', aliases=aliases,
        root_scope=facts.root_scope, scope_groups=facts.groups(aliases), **tables)
    if not protocols:return result
    from scar.analysis.source_suspension_interfaces import SuspensionInterfaceIndex
    original={node.key:plans[node.origin.domain,node.origin.line] for node in graph.templates}
    def reader(identity,key):
        assert identity==result.unit
        return original[key]
    return result,SuspensionInterfaceIndex(plan_reader=reader)


def test_source_new_init_and_foreign_result_preserve_protocol_interfaces():
    unit = source_facts('''
class Allocated:
    def __new__(cls, value):
        self = object.__new__(cls)
        self.before = value
        return self
    def __init__(self, value):
        self.after = value
class Foreign:
    def __new__(cls):
        return 17
    def __init__(self):
        impossible()
class Plain:
    def __init__(self, value):
        self.value = value
class Static:
    @staticmethod
    def __init__(value):
        return None
class Child(Allocated):
    pass
class Variant:
    def __init__(*args):
        return None
    if flag:
        __init__ = staticmethod(__init__)
class Open:
    __new__ = unknown
a = Allocated(23)
f = Foreign()
p = Plain(29)
s = Static(31)
c = Child(37)
v = Variant(41)
o = Open()
''')
    solver = _Solver([unit])
    assert solver.solve(100_000)
    links = tuple(solver.constructions.links.values())
    stages = {link.stage for link in links}
    interfaces = {p for link in links for p in (*link.inputs, *link.outputs)
                  if type(p) is T.ConstructionPort}
    assert interfaces == set(solver.constructions.ports.values())
    assert {T.ConstructionStage.SOURCE_NEW, T.ConstructionStage.SOURCE_INIT,
            T.ConstructionStage.OBJECT_NEW, T.ConstructionStage.EXPLICIT_OBJECT_NEW,
            T.ConstructionStage.RETURN_FOREIGN} <= stages
    foreign = [link for link in links if link.stage is T.ConstructionStage.RETURN_FOREIGN
               and ('constant', 'int', 17) in solver.values[next(
                   p for p, gp in solver.constructions.ports.items() if gp == link.inputs[0])]]
    assert foreign
    for link in foreign:
        assert not any(other.source_class == link.source_class and other.stage is T.ConstructionStage.SOURCE_INIT
                       for other in links)
    for link in links:
        assert decode(T.ConstructionLink, encode(link, record_tags=P.PRODUCTION_RECORD_TAGS),
                      record_tags=P.PRODUCTION_RECORD_TAGS) == link
        if link.stage is T.ConstructionStage.SOURCE_INIT:
            world = next(route for route in link.connection.parameters if route.kind is T.RouteKind.STATE)
            assert type(world.actuals[0]) is T.ConstructionPort
            assert world.actuals[0].role is T.ConstructionPortKind.NEW_WORLD
            assert all(target != link.result for _, target in link.connection.returns)
    static = next(link for link in links if link.stage is T.ConstructionStage.SOURCE_INIT
                  and any(route.kind is T.RouteKind.ARGUMENT and route.actuals
                          and type(route.actuals[0]) is T.GlobalPort
                          and ('constant', 'int', 31) in solver.values[unit.ports.index(route.actuals[0].port)]
                          for route in link.connection.parameters))
    assert len([r for r in static.connection.parameters if r.kind is T.RouteKind.ARGUMENT]) == 1
    variants = [link for link in links if link.stage is T.ConstructionStage.SOURCE_INIT
                and any(r.kind is T.RouteKind.PACK_POSITIONALS for r in link.connection.parameters)]
    assert {len(r.actuals) for link in variants for r in link.connection.parameters
            if r.kind is T.RouteKind.PACK_POSITIONALS} == {1, 2}


def test_unknown_pack_keeps_known_body_and_symbolic_content_projections():
    unit = source_facts('''
def leaf():
    return 7
def select(value, *, key):
    return value
def forward(*args, **kwargs):
    return select(*args, **kwargs)
def independent(required):
    return leaf
def keyword_required(*, missing):
    return leaf
def deferred(value):
    yield value
result = forward(leaf, key=leaf)
known_return = independent(*unknown)
bad = keyword_required(*unknown)
g = deferred(*unknown)
''')
    solver = _Solver([unit])
    assert solver.solve(100_000)
    symbolic = [c for c in solver.links.values() if c.binding is T.ArgumentBinding.SYMBOLIC_PACK]
    assert symbolic and any(c.projections for c in symbolic)
    module = lambda name: solver.ns_values[unit.unit, F.NamespaceKind.MODULE.value, 0, name]
    leaf = next(value for value in module('leaf') if value[0] == 'function')
    assert leaf in module('known_return')
    assert leaf in module('result')
    assert not module('bad')
    assert any(c.mode == 'CREATE_DEFERRED_BODY' for c in symbolic)
    for call in symbolic:
        assert 'CALL_SIGNATURE_ACCEPTANCE' in call.conditions
        assert call.argument_packs is not None
        assert decode(T.CallLink, encode(call, record_tags=P.PRODUCTION_RECORD_TAGS),
                      record_tags=P.PRODUCTION_RECORD_TAGS) == call
        for projection in call.projections:
            pack = unit.ports.index(projection.pack.port)
            formal = unit.ports.index(projection.formal.port)
            assert formal not in solver.adj.get(pack, ())


def test_generator_creation_and_advance_keep_yield_sent_and_return_separate():
    source='''
def leaf():
    return 1
def terminal():
    return 2
def stream(value):
    sent = yield value
    return terminal
g = stream(leaf)
'''
    unit,index=source_facts(source,protocols=True)
    solver=_Solver([unit]);solver.generators.interfaces=index
    assert solver.solve(100_000)
    assert len(solver.generators.creations)==1 and not solver.generators.advances
    frame=next(iter(solver.generators.states.values()))
    fid=frame[0];function=solver.functions[fid][1]
    leaf=next(v for v in solver.ns_values[unit.unit,F.NamespaceKind.MODULE.value,0,'leaf'] if v[0]=='function')
    assert leaf not in solver.values[function.formals[1]]

    unit,index=source_facts(source+'for item in g:\n    result = item\n',protocols=True)
    solver=_Solver([unit]);solver.generators.interfaces=index
    assert solver.solve(100_000)
    module=lambda name:solver.ns_values[unit.unit,F.NamespaceKind.MODULE.value,0,name]
    leaf=next(v for v in module('leaf') if v[0]=='function')
    terminal=next(v for v in module('terminal') if v[0]=='function')
    assert leaf in module('result') and terminal not in module('result')
    assert solver.generators.getters and solver.generators.advances
    from scar.ir.program import source_generators as D
    for driven in solver.generators.advances.values():
        assert driven.connection.activation is T.FunctionActivation.RESUME_BODY
        assert not driven.connection.returns
        assert decode(D.GeneratorAdvance,encode(driven,record_tags=P.PRODUCTION_RECORD_TAGS),
                      record_tags=P.PRODUCTION_RECORD_TAGS)==driven
        site=solver.generators.iterations[driven.iteration]
        state=next(r for r in driven.connection.parameters if r.kind is T.RouteKind.STATE)
        assert state.actuals==(site.world,)
        assert driven.exhaustion is not None and driven.exhaustion.value!=site.value
        for yielded in driven.yielded:
            assert yielded.exported!=yielded.sent and yielded.sent_literal.to_python() is None
            assert ('constant','NoneType',None) in solver.values[solver.original_point(yielded.sent)]
