"""Builtin boundaries follow original references, not user-local spellings."""
from pathlib import Path
from types import SimpleNamespace

from scar.analysis import source_execution as analysis
from scar.ir.program import source_execution as X, source_productions as P
from scar.ir.record_codec import encode, decode
from tests.unit.test_source_construction_connections import source_facts
from tests.unit.test_source_expression_rules import _documents


def test_builtin_alias_shadow_defaults_and_original_code_flow(monkeypatch):
    source='''
from builtins import compile as make
code = make('pass', 'virtual.py', 'exec')
exec(code, {})
def separate():
    return compile('pass', 'isolated.py', 'exec', dont_inherit=True, optimize=2)
def shadow(compile, exec):
    compile('pass', 'shadow.py', 'exec')
    exec(code)
'''
    unit=source_facts(source)
    syntax=_documents(source)[2]
    # Controlled F2 document provider, with the actual original facts and
    # typed source IDs; this does not claim a sealed filesystem receipt.
    monkeypatch.setattr(analysis,'_Fragments',lambda root:SimpleNamespace(read=lambda ref:syntax))
    store=SimpleNamespace(model_for=lambda identity:Path('/controlled-f2'),
        model_units={unit.unit:{'artifacts':{'source_syntax':{}}}})
    boundaries,contexts,uses=analysis.source_builtin_boundaries(store,unit)
    assert sum(b.builtin is X.SourceBuiltin.COMPILE for b in boundaries)==2
    assert sum(b.builtin is X.SourceBuiltin.EXEC for b in boundaries)==1
    assert len(uses)==1 and len(contexts)==2
    assert any(c.inherited_future_flags is None for c in contexts)
    assert any(c.dont_inherit is True and c.inherited_future_flags==0
               and c.effective_optimize==2 for c in contexts)
    for b in boundaries:
        assert b.owner in {g.owner for g in unit.scope_groups}
        assert b.site.world != b.site.result_world
        assert decode(X.SourceBuiltinInvocation,encode(b,record_tags=P.PRODUCTION_RECORD_TAGS),
                      record_tags=P.PRODUCTION_RECORD_TAGS)==b
    execution=next(b for b in boundaries if b.builtin is X.SourceBuiltin.EXEC)
    assert execution.normal_result is not None and execution.normal_result.to_python() is None
    assert uses[0].exec_result==execution.site.result
    assert all(c.source_future_flags is None and c.effective_flags is None for c in contexts)
