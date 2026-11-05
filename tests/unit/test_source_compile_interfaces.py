"""A query-local compiler binding must not alter source or other rules."""
from types import SimpleNamespace
import __future__

from scar.analysis.source_compile_interfaces import ContextCompiler,_bind_query


class Query:
    def _collect(self):
        return compile('def fn(value: Missing): return value','original.py','exec',
                       dont_inherit=True,optimize=0)


def test_query_binding_uses_context_flags_without_mutating_module_globals():
    flag=__future__.annotations.compiler_flag
    context=SimpleNamespace(mode='exec',filename='declared.py',compiler_input_flags=flag,optimize=0)
    compiler=ContextCompiler(context,'original.py')
    original=Query();bound=_bind_query(Query(),compiler)
    assert not original._collect().co_flags & flag
    code=bound._collect()
    assert code.co_flags & flag and code.co_filename=='declared.py'
    assert not original._collect().co_flags & flag
    assert 'compile' not in Query._collect.__globals__
