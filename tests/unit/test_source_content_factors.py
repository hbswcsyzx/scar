"""Connectivity compression must not add edges between unequal neighborhoods."""
from scar.analysis.normal_targets import _Solver
from scar.analysis.source_content_factors import factor_records,expand_factor,write_factors
from scar.ir.program import source_productions as P,content_factors as C
from scar.ir.record_codec import encode,decode
from scar.analysis.source_template_links import _json
from tests.unit.test_source_construction_connections import source_facts


def test_factorization_preserves_labeled_edges_and_direct_defaults(tmp_path):
    unit=source_facts('''
def first(): return 1
def second(): return 2
def third(): return 3
def fallback(): return 4
data = {}
x = first()
y = second()
z = third()
''')
    solver=_Solver([unit]);flow=solver.containers
    sources=[f.value for f in unit.functions]
    targets=[call.result for call in unit.calls]
    container=unit.containers[0].value
    a,b,c,default=sources;x,y,z=targets
    key=('str','key')
    for source,target in ((a,x),(a,y),(b,x),(b,y),(c,y),(c,z),(default,x)):
        flow.link(source,target,container,key)
    flow.link(c,x,container,None)
    flow.link(b,z,container,('NoneType',None))
    factors=tuple(factor_records(flow))
    expanded=tuple(link for factor in factors for link in expand_factor(factor))
    wire=lambda item:_json(encode(item,record_tags=P.PRODUCTION_RECORD_TAGS))
    assert {wire(link) for link in expanded}=={wire(link) for link in flow.links.values()}
    assert len(expanded)==len(flow.links)==9 and len(factors)==5
    assert any(set(f.sources)=={solver.gp(a),solver.gp(b)} and set(f.targets)=={solver.gp(x),solver.gp(y)} for f in factors)
    assert not any(link.source==solver.gp(a) and link.target==solver.gp(z) for link in expanded)
    for factor in factors:
        assert decode(C.ContentFactor,encode(factor,record_tags=P.PRODUCTION_RECORD_TAGS),
                      record_tags=P.PRODUCTION_RECORD_TAGS)==factor
    metadata=write_factors(flow,tmp_path)
    assert metadata['content_factor_stats']['expanded_pairs']==9
    assert metadata['content_factor_stats']['factors']==5
