"""Exec namespaces and worlds follow protocol cases, not inferred aliases."""
from types import SimpleNamespace

from scar.analysis import source_execution as E
from scar.analysis.source_exec_roots import exec_root_connections
from scar.ir.program import source_exec_roots as X,source_productions as P,normal_graph as G
from scar.ir.program.control import LanguageCompletionKind as K
from scar.ir.effects import Knowledge
from scar.ir.record_codec import encode,decode
from tests.unit.test_source_construction_connections import source_facts
from tests.unit.test_source_expression_rules import _documents,WORLD,REF


def test_namespace_branches_preparation_discard_and_closure(monkeypatch):
    source=('def both(code, globals_value, locals_value):\n    exec(code, globals_value, locals_value)\n'
        'def global_only(code, globals_value):\n    exec(code, globals_value)\n'
        'def default_namespaces(code):\n    exec(code)\n')
    unit=source_facts(source);syntax=_documents(source)[2]
    monkeypatch.setattr(E,'_Fragments',lambda path:SimpleNamespace(read=lambda ref:syntax))
    store=SimpleNamespace(model_for=lambda identity:'/controlled-source',
        model_units={unit.unit:{'artifacts':{'source_syntax':{}}}})
    boundaries,_,_=E.source_builtin_boundaries(store,unit)
    assert len(boundaries)==3
    root=unit.root_scope
    template=SimpleNamespace(key=root.template,root=root.region,parameters=(REF,REF,WORLD),
        completions=(P.ProductionCompletion(K.RETURN,(REF,WORLD)),))
    candidate=SimpleNamespace(id='controlled-code-input',conditions=('CONTROLLED_COMPILED_CODE_SELECTED',))
    counts=[]
    for boundary in boundaries:
        connections,obligations=exec_root_connections(boundary,candidate,template,root,(),frame_kind='FUNCTION')
        counts.append(len(connections));assert not obligations
        for connection in connections:
            assert tuple(a.phase for a in connection.actions)==tuple(X.ExecPhase)
            assert connection.normal_result.to_python() is None
            assert all(a.external is Knowledge.UNKNOWN and a.rng is Knowledge.UNKNOWN for a in connection.actions)
            assert not any(e.target==boundary.site.result for e in connection.edges)
            preparation=connection.actions[3]
            assert any(e.kind is G.EdgeKind.STATE and e.source==preparation.world_out
                and type(e.target) is E.T.GlobalPort and e.target.port.kind is G.PortKind.PARAMETER
                and e.target.port.ordinal==2 for e in connection.edges)
            assert any(e.source==connection.actions[-1].world_out and e.target==boundary.site.result_world
                       for e in connection.edges)
            assert decode(X.ExecRootConnection,encode(connection,record_tags=P.PRODUCTION_RECORD_TAGS),
                          record_tags=P.PRODUCTION_RECORD_TAGS)==connection
            if (connection.globals.kind is X.ExecNamespaceKind.EXPLICIT_VALUE
                    and connection.locals.representation=='SAME_REFERENCE_AS_EXPLICIT_GLOBALS'):
                assert connection.globals.value==connection.locals.value
            if connection.locals.kind is X.ExecNamespaceKind.CALLER_LOCALS:
                assert connection.locals.representation=='OPTIMIZED_FRAME_LOCALS_NEW_DICT_SNAPSHOT'
                assert type(connection.locals.value) is X.ExecProtocolValue
    assert sorted(counts)==[1,2,4]
    rejected,pending=exec_root_connections(boundaries[0],candidate,template,root,('cell',),frame_kind='FUNCTION')
    assert not rejected and pending[0].reason=='ROOT_ABI_HAS_NO_CLOSURE_CELL_PARAMETERS'
