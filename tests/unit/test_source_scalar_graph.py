"""Cross-scope scalar transfer uses source relations, without running code."""
from types import SimpleNamespace

from scar.analysis.normal_targets import _Solver
from scar.analysis.source_scalar_graph import ScalarGraphOverlay
from scar.analysis.source_scalar_values import ScalarValueFlow
from scar.ir.program import normal_targets as T, scalar_values as V, source_productions as P
from scar.ir.literals import PythonLiteral
from scar.ir.record_codec import decode, encode
from tests.unit.test_source_construction_connections import source_facts


def test_cross_call_fields_and_linear_group_index():
    unit, interfaces = source_facts('''
def add(value):
    return value + 1
def through(value):
    return add(value)
result = through(4)
def packed(*values):
    return values
pack_result = packed(11)
class Holder:
    @property
    async def deferred(self, default=17):
        return default
pending = Holder().deferred
''', protocols=True)
    solver = _Solver([unit])
    solver.generators.interfaces = interfaces
    assert solver.solve(100000)
    graph = SimpleNamespace(units={unit.unit: {}}, report={'analysis_mode':'LIBRARY_MAY_ANALYSIS'},
        fact_store=SimpleNamespace(load=lambda identity:unit),
        calls=lambda:iter(solver.links.values()),
        properties=lambda:iter(solver.descriptors.property_accesses.values()),
        constructions=lambda:iter(solver.constructions.links.values()),
        generator_advances=lambda:iter(solver.generators.advances.values()),
        namespace_lookups=lambda:iter(()), attribute_contents=lambda:iter(()),
        content_factors=lambda:iter(()))
    overlay = ScalarGraphOverlay(graph)
    overlay.collect()
    flow = overlay.connect()
    assert flow.drain()
    assert any(d.result.literal.to_python() == 5 for d in flow.derivations())
    assert any(5 in {v.to_python() for v in flow.snapshot(link.result).literals}
               for link in solver.links.values() if link.source_callable is not None)
    assert all('/STATE' not in group.role for group in flow.groups())
    packed = next(f for f in unit.functions if 'values' in f.parameter_names)
    formal = overlay.gp(unit, packed.formals[1])
    assert not flow.snapshot(formal).literals
    assert overlay.stats['non_scalar_route/PACK_POSITIONALS'] > 0
    assert overlay.stats['state_return_not_scalar'] > 0
    deferred = next(f for f in unit.functions if 'default' in f.parameter_names)
    assert not flow.snapshot(overlay.gp(unit,deferred.formals[2])).literals
    assert overlay.stats['deferred_creation_routes_not_resumed'] > 0
    assert all(not flow.snapshot(p).complete for g in flow.groups() for p in g.targets)
    for group in flow.groups():
        assert decode(V.ScalarTransferGroup, encode(group,record_tags=P.PRODUCTION_RECORD_TAGS),
                      record_tags=P.PRODUCTION_RECORD_TAGS) == group

    # The transfer index stays linear even with many equal-neighborhood
    # sources and targets. Widening cannot silently become an exact value.
    ports = tuple(T.GlobalPort(unit.unit, p) for p in unit.ports)
    sources, targets = ports[:10], ports[10:40]
    group = V.ScalarTransferGroup('content_factors',0,'selected_content',sources,targets)
    grouped = ScalarValueFlow()
    assert grouped.connect_group(('factor',0),group)
    assert not grouped.connect_group(('factor',0),group)
    for index, port in enumerate(sources):
        grouped.offer(port,PythonLiteral.from_python(index))
    assert grouped.drain()
    assert grouped.stats['connections'] == len(sources)+len(targets)
    assert grouped.stats['private_junctions'] == 1
    assert all(grouped.snapshot(p).content_open and len(grouped.snapshot(p).literals)<=4
               and not grouped.snapshot(p).complete for p in targets)
    assert not grouped.connections()  # Private junctions never leak as source IDs.
    before = grouped.stats['events']
    assert grouped.drain() and grouped.stats['events']==before
