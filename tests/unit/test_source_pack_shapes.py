"""Static witnesses survive caching; dynamic opening/readiness never do."""
from scar.analysis.normal_containers import ContainerFlow
from scar.analysis.normal_graph import _Emitter
from scar.analysis.normal_targets import _Solver
from scar.analysis.source_function_connections import Invocation
from scar.analysis.source_pack_shapes import StaticPackShapes, StaticPackShape, StaticPackReject
from scar.ir.program import source_productions as P
from scar.ir.program.structured import PythonProtocolKind as K
from tests.unit.test_source_construction_connections import source_facts


def test_static_pack_witnesses_match_legacy_and_recheck_nested_state():
    unit, plans = source_facts('''
def target(*items, **named): return items
target(*(11, 13), **{'left': 17})
target(**{'right': 19})
target(**{})
saved = (23, 29)
target(*saved)
''', protocols=True)
    solver = _Solver([unit])
    flow = solver.containers = ContainerFlow(solver, [unit])

    def merge_proof(source, point):
        # Same admission as the production reader, using the controlled
        # provider's original typed F4 plans; no fabricated source IDs.
        template = source.ports[point].template
        plan = plans._plan(source, template)[0]
        if any(step.region != plan.root for step in plan.steps):
            return set()
        emitter = _Emitter(plan, template, {})
        points = {port:i for i,port in enumerate(source.ports) if port.template == template}
        proof = set()
        for step in plan.steps:
            ins = step.instruction
            if type(ins) is P.ApplyPythonProtocol and ins.protocol is K.DICT_MERGE:
                target = points.get(emitter.value(step.arguments[1])[0])
                origin = points.get(emitter.value(step.arguments[2])[0])
                if target is not None and origin is not None:
                    proof.add((target, origin))
        return proof

    flow._merge_proof = merge_proof
    cached = StaticPackShapes(flow)
    queries = {(call.positional_pack, 'SEQUENCE') for call in unit.calls if call.positional_pack is not None}
    queries.update((call.keyword_pack, 'MAPPING') for call in unit.calls if call.keyword_pack is not None)
    queries.update((c.value, c.kind.value) for c in unit.containers
                   if c.kind.value in ('SEQUENCE', 'MAPPING'))
    for point, kind in queries:
        assert cached.closed(point, kind) == flow._closed_pack(point, kind)
    assert any(type(cached.shape(point,kind)) is StaticPackReject for point,kind in queries)
    assert any(type(w := cached.shape(point,kind)) is StaticPackShape and not w.contents
               for point,kind in queries)
    builds = cached.stats['shape_builds']
    metadata_items = cached.stats['metadata_items']
    for _ in range(20):
        for point, kind in queries:
            assert cached.closed(point, kind) == flow._closed_pack(point, kind)
    assert cached.stats['shape_builds'] == builds
    assert cached.stats['metadata_items'] == metadata_items

    parent, witness = next((point, w) for point,kind in queries
        if type(w := cached.shape(point,kind)) is StaticPackShape and len(w.dependencies)>1)
    child, child_kind = next(d for d in witness.dependencies if d[0] != witness.origin)
    flow.open_containers.add(('container', child, child_kind))
    assert ('container', witness.origin, witness.kind) not in flow.open_containers
    assert cached.closed(parent, witness.kind) is None
    assert flow._closed_pack(parent, witness.kind) is None
    assert type(cached.shape(parent,witness.kind)) is StaticPackShape
    flow.open_containers.remove(('container', child, child_kind))
    assert cached.closed(parent,witness.kind) == flow._closed_pack(parent,witness.kind)
    assert cached.closed(parent,witness.kind,frozenset((child,))) is None
    assert type(cached.shape(parent,witness.kind)) is StaticPackShape

    # Final argument availability is checked on every use, not memoized.
    invocation = Invocation(parent, (), (), None, parent, parent, keyword_pack=parent)
    expected = ('container', witness.origin, witness.kind)
    solver.values[parent] = {expected}
    assert cached.arguments(invocation) == flow.invocation_arguments(invocation)
    assert cached.arguments(invocation) is not None
    solver.add(parent, ('external_value', None))
    assert cached.arguments(invocation) is None and flow.invocation_arguments(invocation) is None
    assert cached.stats['readiness_refusals'] > 0
