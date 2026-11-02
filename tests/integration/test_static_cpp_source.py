"""C++ binding templates supply source dependencies, never runtime identities."""
from collections import deque
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import re
import sysconfig

import pytest

from scar.analysis.static_cpp_source import (CppRelationKind, CppSourceError,
    cpp_source_from_document, cpp_source_to_document, read_static_cpp_source)
from scar.ir.v2.ids import SourceAtomID


def test_original_binding_template_source_relations_and_open_fields(tmp_path):
    project = Path(__file__).resolve().parents[2]
    tool = project / '.venv/native-source/bin/python'
    if not tool.exists():
        pytest.skip('SCAR private native-source analyzer is unavailable')
    torchgen = Path(sysconfig.get_paths()['purelib']) / 'torchgen'
    source = torchgen / 'packaged/autograd/templates/python_variable_methods.cpp'
    if not source.is_file():pytest.skip('installed template materials are unavailable')
    raw = source.read_bytes()
    model = read_static_cpp_source(source, tool_python=tool, template_grammar=torchgen / 'code_template.py')
    assert model.source.sha256 == hashlib.sha256(raw).hexdigest()
    assert model.tools.isolated and model.tools.no_site and not model.tools.torch_imported
    assert model.tools.core_limit == (0, 0)
    assert model.template_grammar and model.tools.files
    index = model.index()
    assert len(index.occurrences) == len(model.occurrences)
    assert len({(n.kind,n.byte_start,n.byte_end) for n in model.occurrences}) == len(model.occurrences)
    table = next(t for t in model.tables if raw[index.occurrences[t.name].byte_start:index.occurrences[t.name].byte_end] == b'variable_methods')
    table_source = index.occurrences[table.occurrence]
    # The independent original fixed-format row inventory checks every explicit
    # literal entry, including aliases and wrappers beyond the stress examples.
    explicit_names = re.findall(rb'^\s*\{"([^"]+)"\s*,',raw[table_source.byte_start:table_source.byte_end],re.M)
    entries = {index.entries[key].python_name:index.entries[key] for key in table.entries}
    assert set(entries) == {name.decode()for name in explicit_names}
    assert len(entries) == len(explicit_names) and table.explicit_entries_enumerated
    assert not table.generated_complete and table.holes and table.terminators and model.errors
    for entry in entries.values():
        assert entry.callback and entry.flags and entry.name and entry.documentation
        assert any(e.target == entry.callback and e.role == 'callback' for e in index.outgoing(entry.occurrence))
        assert any(e.target == entry.occurrence and e.source == table.occurrence for e in index.incoming(entry.occurrence))
    assert any(r.spelling == 'THPVariable_dim' and r.candidates for r in entries['ndimension'].references)
    assert any(r.spelling == 'THPVariable_numel' and r.candidates for r in entries['nelement'].references)
    add = next(r for r in entries['__add__'].references if r.spelling == 'TypeError_to_NotImplemented_')
    radd = next(r for r in entries['__radd__'].references if r.spelling == 'TypeError_to_NotImplemented_')
    assert add.candidates == radd.candidates and add.candidates
    assert any(not r.candidates for r in entries['__add__'].references)
    def reachable(start):
        pending = deque((start,)); seen = set()
        while pending:
            current = pending.popleft()
            if current in seen:continue
            seen.add(current)
            pending.extend(edge.target for edge in index.outgoing(current))
        return seen
    for name, symbol in (('to','THPVariable_to'),('copy_','THPVariable_copy_')):
        candidate = next(r.candidates[0] for r in entries[name].references if r.spelling == symbol)
        function = index.functions[candidate]
        assert any(c.owner_function == candidate for c in model.calls)
        assert any(e.target == function.body and e.role == 'body' for e in index.outgoing(candidate))
        assert {table.occurrence, entries[name].occurrence, entries[name].callback, candidate, function.body} <= reachable(table.occurrence)
        assert all(c.occurrence in reachable(entries[name].occurrence) for c in model.calls if c.owner_function == candidate)
        assert function.open_fields and entries[name].open_fields
    overloads = [f for f in model.functions if f.symbol == 'dispatch_to']
    assert len(overloads) > 1 and len({f.declarator for f in overloads}) == len(overloads)
    assert all(e.kind in (CppRelationKind.SOURCE,CppRelationKind.STRUCTURE) for e in model.relations)
    assert any('if' in n.kind and 'control-source' in n.roles for n in model.occurrences)
    assert any('preprocessor-source' in n.roles for n in model.occurrences)
    assert any(edge.role == 'preprocessor-name' for edge in model.relations)
    assert any('return-expression' in n.roles for n in model.occurrences)
    assert any('method-name' in n.roles and 'expression-structure' in n.roles for n in model.occurrences)
    assert model.open_fields and model.holes and model.errors
    for query in (index.incoming, index.outgoing):
        with pytest.raises(CppSourceError, match='absent from this unit'):
            query(SourceAtomID('different-source-occurrence'))
    macro_source = tmp_path / 'unexpanded.cpp'
    macro_source.write_text('PyMethodDef methods[] = {\n'
        ' {"visible", callback, METH_NOARGS, nullptr},\n'
        ' MISSING_METHODS,\n {nullptr}\n};\n')
    macro_model = read_static_cpp_source(macro_source, tool_python=tool)
    macro_table, = macro_model.tables
    assert macro_table.unclassified and not macro_table.holes
    assert not macro_table.explicit_entries_enumerated and not macro_table.generated_complete
    with pytest.raises(CppSourceError,match='MISSING_ANALYZER_TOOL'):
        read_static_cpp_source(source,tool_python=tmp_path/'missing-python')
    document = cpp_source_to_document(model)
    encoded = json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    assert cpp_source_from_document(json.loads(encoded)) == model
    assert all(type(edge['source']) is int and type(edge['target']) is int for edge in document['relations'])
    assert all('source' not in row for row in document['occurrences'])
    assert encoded.count(str(source).encode()) == 1
    invalid_index = deepcopy(document); invalid_index['relations'][0]['target'] = len(document['occurrences'])
    duplicate = deepcopy(document); duplicate['occurrences'][1]['id'] = duplicate['occurrences'][0]['id']
    wrong_source = deepcopy(document); wrong_source['source']['sha256'] = '0' * 64
    for invalid in (invalid_index, duplicate, wrong_source):
        with pytest.raises(CppSourceError):cpp_source_from_document(invalid)
    print({'cpp_source_normalized_json_bytes': len(encoded), 'cpp_source_normalized_gzip_bytes': len(gzip.compress(encoded,mtime=0))})
