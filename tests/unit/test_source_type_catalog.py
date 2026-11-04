"""Two finite input-shape checks; no target parsing or execution."""
import ast
import builtins
from copy import deepcopy
from dataclasses import replace
import _symtable
import sys

import pytest

from scar.analysis import source_type_catalog as api
from scar.analysis.source_roles import source_role_catalog
from scar.analysis.source_syntax import _schema_and_digests
from scar.ir.record_codec import encode

pytestmark = pytest.mark.skipif(sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 14, 7),
                               reason='reviewed official F2 schema')


def test_input_sort_and_original_field_reference_conservation(monkeypatch):
    def forbidden(*args, **kwargs):raise AssertionError('input signature catalog must not run a target frontend')
    with monkeypatch.context() as patch:
        patch.setattr(ast, 'parse', forbidden);patch.setattr(builtins, 'compile', forbidden)
        patch.setattr(_symtable, 'symtable', forbidden)
        catalog = api.source_type_catalog()
        assert api.read_source_type_catalog(deepcopy(catalog)) == catalog
    schema = _schema_and_digests()[0];roles = source_role_catalog()
    concrete = [(i, row) for i, row in enumerate(schema) if not row.abstract]
    assert len(catalog['sorts']) == 13 and len(catalog['constructors']) == len(concrete) == 113
    assert len(catalog['slots']) == len(roles['rules']) == 484
    by_sort = {row['name']: row['constructors'] for row in catalog['sorts']}
    assert set(by_sort) == {row.bases[0] for _, row in concrete}
    assert sorted(i for row in by_sort.values() for i in row) == list(range(113))
    consumed = []
    for index, ((schema_index, source), row) in enumerate(zip(concrete, catalog['constructors'])):
        assert row['name'] == source.name and row['source_schema_index'] == schema_index
        assert catalog['sorts'][row['sort']]['name'] == source.bases[0] and index in by_sort[source.bases[0]]
        for group, names, ids in (('FIELD', source.fields, row['fields']), ('ATTRIBUTE', source.attributes, row['attributes'])):
            assert len(ids) == len(names)
            for ordinal, (name, slot_id) in enumerate(zip(names, ids)):
                slot = catalog['slots'][slot_id];rule = roles['rules'][slot['role_rule']]
                assert (slot['constructor'], slot['group'], slot['ordinal']) == (index, group, ordinal)
                assert (rule['constructor'], rule['group'], rule['ordinal'], rule['name']) == (source.name, group, ordinal, name)
                assert slot['type'] == (encode(source.field_types[ordinal].type) if group == 'FIELD' else None)
                consumed.append(slot['role_rule'])
    assert sorted(consumed) == list(range(484))
    assert sum(row['group'] == 'FIELD' for row in catalog['slots']) == 196
    assert sum(row['group'] == 'ATTRIBUTE' for row in catalog['slots']) == 288
    assert catalog['authority'] == 'SOURCE_INPUT_SHAPE_CLOSURE' and catalog['graph_realization'] == 'NOT_PERFORMED'
    assert catalog['context_inference'] == catalog['phase_inference'] == 'NOT_COMPUTED'
    assert catalog['execution_semantics'] == 'NOT_CLAIMED'
    independent = api.read_source_type_catalog(catalog)
    independent['sorts'][0]['constructors'].clear()
    assert api.read_source_type_catalog(catalog) == catalog


def test_catalog_rejects_tamper_and_unreviewed_schema(monkeypatch):
    catalog = api.source_type_catalog()
    bad_digest = deepcopy(catalog);bad_digest['content_sha256']='0'*64
    with pytest.raises(ValueError, match='differs'):api.read_source_type_catalog(bad_digest)
    mutations = (
        lambda doc: doc['slots'][0].update(ordinal=False),
        lambda doc: doc['slots'][0]['type'].update(kind='UNKNOWN'),
        lambda doc: doc['sorts'][0]['constructors'].append(0),
        lambda doc: doc.update(execution_semantics='PURE'),
        lambda doc: doc.update(extra_schema_field=None),
        lambda doc: doc['constructors'].append(deepcopy(doc['constructors'][0])),
    )
    for mutation in mutations:
        changed = deepcopy(catalog);mutation(changed)
        # Re-signing arbitrary bytes cannot upgrade the reviewed rule domain.
        changed['content_sha256'] = api._digest({key:value for key,value in changed.items() if key!='content_sha256'})
        with pytest.raises(ValueError, match='differs'):api.read_source_type_catalog(changed)
    schema, ast_sha, literal_sha = _schema_and_digests()
    future = replace(schema[-1], name='FutureForm', bases=('AST',), abstract=False,
        fields=(), attributes=(), field_types=())
    monkeypatch.setattr(api, '_schema_and_digests', lambda: (schema+(future,), ast_sha, literal_sha))
    with pytest.raises(ValueError, match='reviewed'):api.source_type_catalog()
