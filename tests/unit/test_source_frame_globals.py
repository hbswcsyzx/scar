"""Selected factory/callee provenance survives late frame-global resolution."""
from types import SimpleNamespace

from scar.analysis.normal_targets import _Solver
from scar.analysis.source_frame_globals import FrameGlobalsFlow
from scar.analysis.source_namespace_captures import extract_captures
from scar.analysis.source_namespace_interfaces import NamespacePlanView,CallerReferencePaths
from scar.ir.program import normal_links as F,normal_graph as G,source_productions as P
from scar.ir.record_codec import decode,encode
from tests.unit.test_source_construction_connections import source_facts


def test_nested_factory_globals_preserve_two_selected_callees(monkeypatch):
    unit,index=source_facts('''
payload = 7
def factory():
    def inner():
        return globals()
    return inner
first = factory()
second = factory()
one = first()
two = second()
''',protocols=True)
    plans={key:index._plan(unit,key)[0] for key in
        {unit.root_scope.template,*(f.template for f in unit.functions)}}
    references=[];captures=[];witnesses=[]
    for key,plan in plans.items():
        refs,created,pending=extract_captures(NamespacePlanView(unit.unit,plan))
        assert not pending
        references.extend(refs);captures.extend(created)
        witnesses.extend(index._witness(unit,key,next(s for s in plan.steps if s.id==r.site.port.owner))
            for r in (*refs,*created))
    material=SimpleNamespace(root=unit.root_scope,references=tuple(references),captures=tuple(captures),
        witnesses=tuple(witnesses),obligations=())
    class ControlledIndex:
        def __init__(self,*args,**kwargs):pass
        def load(self,identity):
            assert identity==unit.unit
            return material
        def close(self):pass
        def validate_parents(self):return 0
    monkeypatch.setattr('scar.analysis.source_frame_globals.FrameCaptureIndex',ControlledIndex)
    solver=_Solver([unit]);solver.analysis_jobs=1
    solver.store=SimpleNamespace(load=lambda identity:unit,original_source_units={})
    solver.namespace_graph=SimpleNamespace(exec_graph=None)
    solver.frames=frames=FrameGlobalsFlow(solver)
    solver.activate_function=frames.activate_function
    paths=CallerReferencePaths(unit)
    inner=next(f for f in unit.functions if any(span.table is F.FactTable.CALLS
        for group in unit.scope_groups if group.owner==f.body_scope.owner for span in group.tables))
    call_index=next(i for group in unit.scope_groups if group.owner==inner.body_scope.owner
        for span in group.tables if span.table is F.FactTable.CALLS for i in range(span.start,span.stop))
    call=unit.calls[call_index]
    assert not frames.read_globals(inner.body_scope.owner,paths.ports[call.result],paths.ports[call.world])
    solver.solve()
    reads=list(frames.reads.values())
    assert len(reads)==2 and not frames.obligations
    assert len({r.function.callee for r in reads})==2
    assert all(r.function.source_callable==paths.ports[inner.value] for r in reads)
    assert all(r.source==r.function.capture.globals for r in reads)
    root_input=frames.roots[unit.unit].globals
    root_point=solver.original_point(root_input)
    assert any(v[0]=='source_root_namespace' for v in solver.values[root_point])
    assert not any(v[0] in ('module','namespace_mapping') for v in solver.values[root_point])
    for row in reads:
        assert row.function.capture_witness.step==row.function.capture.site.port.owner
        assert decode(type(row),encode(row,record_tags=P.PRODUCTION_RECORD_TAGS),record_tags=P.PRODUCTION_RECORD_TAGS)==row
