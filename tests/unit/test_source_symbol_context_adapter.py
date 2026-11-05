"""Explicit future flags reach the official symtable without editing source."""
from __future__ import annotations

import _symtable
import __future__
import sys

import pytest

from scar.analysis.source_symbol_context_adapter import DEFAULT, SymbolContextAdapter, SymbolContextError
from scar.analysis.source_symbols import capture_raw_view


@pytest.mark.skipif(sys.implementation.name!='cpython' or sys.version_info[:3]!=(3,14,7),
                    reason='official native raw schema is pinned to CPython 3.14.7')
def test_official_symbol_context_flags_and_unmodified_source():
    if not (DEFAULT/'result.json').exists():
        pytest.skip('build the isolated symtable adapter explicitly before this native fixture')
    text = 'def function(value: Missing):\n    return value\n'
    flag = __future__.annotations.compiler_flag
    with SymbolContextAdapter() as adapter:
        zero = adapter.capture(text,'original.py')
        future = adapter.capture(text,'original.py',flags=flag)
        inherited = adapter.capture(text,'original.py',dont_inherit=False,inherited_flags=flag)
        assert zero.scopes == capture_raw_view(_symtable.symtable(text,'original.py','exec'))
        assert len(zero.scopes)==3 and len(future.scopes)==2
        assert inherited.scopes == future.scopes
        assert zero.request['text_utf8_sha256']==future.request['text_utf8_sha256']
        assert zero.request['effective_flags']==0 and future.request['effective_flags']==flag
        assert any(s.name=='__annotate__' for s in zero.scopes)
        assert all(s.name!='__annotate__' for s in future.scopes)
        assert adapter.capture('left + right','expression.py','eval').scopes == capture_raw_view(
            _symtable.symtable('left + right','expression.py','eval'))
        with pytest.raises(ValueError,match='explicitly supplied caller future flags'):
            adapter.capture(text,'original.py',dont_inherit=False)
        with pytest.raises((SymbolContextError,SyntaxError)):
            adapter.capture('def broken(:\n','broken.py')
