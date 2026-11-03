"""F3-B syntax roles: independent schema and source-path expectations only."""
import _ast
import ast
import builtins
from copy import deepcopy
import json
import sys

import pytest

from scar.analysis.source_bytes import source_bytes_document
from scar.analysis.source_tokens import source_tokens_document
from scar.analysis.source_syntax import source_syntax_document
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.record_codec import decode


pytestmark = pytest.mark.skipif(
    sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 14, 7),
    reason='this role catalog is pinned to the official CPython 3.14.7 AST schema')


def _inputs(text, *, max_tokens=2_000_000, mode='exec'):
    f0 = source_bytes_document(text.encode(), path='/source/roles.py', namespace_root='/source')
    f1 = source_tokens_document(f0, max_tokens=max_tokens)
    return f0, f1, source_syntax_document(f0, f1, mode=mode)


def _occurrence(syntax, path):
    value = syntax.nodes[syntax.root]
    for part in path:
        if isinstance(part, str):
            cls = getattr(ast, value.constructor)
            value = value.fields[cls._fields.index(part)]
        else:
            value = value.items[part]
        if value.kind == 'NODE':
            index = value.reference
            value = syntax.nodes[index]
    return syntax.root if not path else index


def _slot(syntax, path, field, *, group='FIELD', item_path=()):
    from scar.ir.program.source_roles import SlotRef
    index = _occurrence(syntax, path)
    cls = getattr(ast, syntax.nodes[index].constructor)
    names = cls._fields if group == 'FIELD' else cls._attributes
    return SlotRef(index, group, names.index(field), item_path)


def _source():
    return '''x += step
plain: Type
(x): Type
assigned: Type = value
obj.attribute: Type
walrus = [(saved := item) for item in source]
type Alias = int
import package.child
import other.child as chosen
from package import member
from package import member as renamed
from package import *
from . import local
call = obj.attribute(keyword=value, **options)
forward: "Forward.Name"
commented = 0 # type: CommentType
template = t"{item.attribute + other}"
mapping = {**options}
def f(*, required, optional=None):
    pass
match subject:
    case _: pass
    case [*_]: pass
    case [captured, *tail]: pass
    case {"key": found, **rest}: pass
    case Holder(label=child): pass
    case None: pass
literal = None
'''


@pytest.mark.parametrize('family', ('schema', 'contexts', 'coverage_and_gates'))
def test_f3b_closed_source_field_roles(family, monkeypatch):
    from dataclasses import replace
    import _symtable
    import scar.analysis.source_roles as api
    from scar.ir.program.source_roles import SlotRef
    from scar.ir.program.source_syntax import AstOccurrence, AstValue

    catalog = api.source_role_catalog()
    rules = catalog['rules']
    keys = {(row['constructor'], row['group'], row['ordinal'], row['name']) for row in rules}
    classes = {name: cls for name, cls in vars(_ast).items()
               if isinstance(cls, type) and issubclass(cls, ast.AST) and '_field_types' in vars(cls)}
    expected = {(name, group, ordinal, field) for name, cls in classes.items()
                for group, fields in (('FIELD', cls._fields), ('ATTRIBUTE', cls._attributes))
                for ordinal, field in enumerate(fields)}
    assert len(classes) == 113 and len(expected) == len(keys) == len(rules) == 484
    assert keys == expected and [row['rule'] for row in rules] == list(range(484))
    constructors = {row['name']: row for row in catalog['constructors']}
    assert len(catalog['constructors']) == len(constructors) == 113 and constructors.keys() == classes.keys()
    rule_ids = {(row['constructor'], row['group'], row['ordinal']): row['rule'] for row in rules}
    for name, cls in classes.items():
        assert constructors[name]['fields'] == [rule_ids[name, 'FIELD', i] for i in range(len(cls._fields))]
        assert constructors[name]['attributes'] == [rule_ids[name, 'ATTRIBUTE', i] for i in range(len(cls._attributes))]
    assert sum(row['group'] == 'FIELD' for row in rules) == 196
    assert sum(row['group'] == 'ATTRIBUTE' for row in rules) == 288

    if family == 'schema':
        # Independent official field types, not the producer's role table.
        from types import UnionType
        from typing import get_args, get_origin
        def shape(kind):
            origin, args = get_origin(kind), get_args(kind)
            if origin is list:
                return ('LIST_NODE' if issubclass(args[0], ast.AST) else 'LIST_SCALAR'), args[0].__name__
            if origin is UnionType:
                child = next(value for value in args if value is not type(None))
                return ('OPTIONAL_NODE' if issubclass(child, ast.AST) else 'OPTIONAL_SCALAR'), child.__name__
            return ('NODE' if issubclass(kind, ast.AST) else 'SCALAR'), kind.__name__
        carriers = []
        for row in rules:
            cls = classes[row['constructor']]
            if row['group'] == 'FIELD':
                assert (row['shape'], row['family']) == shape(cls._field_types[row['name']])
                if row['family'] in ('str', 'object'):
                    carriers.append(row)
            else:
                assert (row['shape'], row['family']) == ('ATTRIBUTE', 'int')
                assert row['role'] == {'lineno': 'SOURCE_START_LINE', 'col_offset': 'SOURCE_START_UTF8_COLUMN',
                    'end_lineno': 'SOURCE_END_LINE', 'end_col_offset': 'SOURCE_END_UTF8_COLUMN'}[row['name']]
        assert len(carriers) == 33
        assert {kind: sum((row['shape'], row['family']) == kind for row in carriers) for kind in
                (('SCALAR', 'str'), ('OPTIONAL_SCALAR', 'str'), ('LIST_SCALAR', 'str'), ('SCALAR', 'object'))} == {
                    ('SCALAR', 'str'): 11, ('OPTIONAL_SCALAR', 'str'): 16,
                    ('LIST_SCALAR', 'str'): 3, ('SCALAR', 'object'): 3}
        ignore = next(row for row in rules if (row['constructor'], row['name']) == ('TypeIgnore', 'lineno'))
        assert ignore['group'] == 'FIELD' and ignore['role'] == 'TYPE_IGNORE_LINE'
        # ABSENT codec probes exercise all slots, without claiming source validity.
        base = decode(SourceSyntaxMaterial, _inputs('')[2])
        absent, queried = AstValue('ABSENT', None, (), None), 0
        for name, cls in classes.items():
            syntax = replace(base, root=0, nodes=(AstOccurrence(name,
                (absent,) * len(cls._fields), (absent,) * len(cls._attributes)),))
            result = api.classify_syntax_roles(syntax)
            assert result.status == 'CLASSIFIED' and result.slots == len(cls._fields) + len(cls._attributes)
            assert sum(row.absent for row in result.counts) == result.slots
            assert all(port.projection == 'NO_VALUE' for port in result.ports)
            for group, names in (('FIELD', cls._fields), ('ATTRIBUTE', cls._attributes)):
                for ordinal, _ in enumerate(names):
                    answer = api.role_at_slot(syntax, SlotRef(0, group, ordinal))
                    assert answer.state == 'ABSENT' and answer.role and 'UNKNOWN' not in answer.role
                    queried += 1
        assert queried == 484
        return

    inputs = _inputs(_source())
    syntax = decode(SourceSyntaxMaterial, inputs[2])
    document = api.source_roles_document(*inputs)
    material = api.read_source_roles(json.loads(json.dumps(document)), *inputs)
    assert material.status == 'CLASSIFIED' and material.authority == 'SYNTAX_FIELD_ROLES'
    assert material.scope_binding == 'NOT_COMPUTED_IN_F3B' and material.runtime_effects == 'NOT_CLAIMED'
    if family == 'contexts':
        # Handwritten expectations from source syntax; no production rules supply the oracle.
        checks = [
            (('body', 0, 'target'), 'id', (), 'AUGMENTED_BINDING_SYNTAX'),
            (('body', 0, 'value'), 'id', (), 'REFERENCE_SYNTAX'),
            (('body', 1, 'target'), 'id', (), 'DECLARATION_ONLY'),
            (('body', 2, 'target'), 'id', (), 'DECLARATION_ONLY'),
            (('body', 3, 'target'), 'id', (), 'BINDING_SYNTAX'),
            (('body', 4, 'target'), 'attr', (), 'ATTRIBUTE_LABEL'),
            (('body', 4, 'target', 'value'), 'id', (), 'REFERENCE_SYNTAX'),
            (('body', 5, 'value', 'elt', 'target'), 'id', (), 'NAMED_EXPR_BINDING_SYNTAX'),
            (('body', 5, 'value', 'generators', 0, 'target'), 'id', (), 'BINDING_SYNTAX'),
            (('body', 6, 'name'), 'id', (), 'TYPE_ALIAS_BINDING_SYNTAX'),
            (('body', 7, 'names', 0), 'name', (), 'IMPORT_MODULE_SPEC'),
            (('body', 8, 'names', 0), 'asname', (), 'IMPORT_BINDING_SYNTAX'),
            (('body', 9, 'names', 0), 'name', (), 'IMPORT_MEMBER_SPEC'),
            (('body', 11, 'names', 0), 'name', (), 'IMPORT_WILDCARD_SPEC'),
            (('body', 12), 'module', (), 'RELATIVE_MODULE_MARKER'),
            (('body', 13, 'value', 'keywords', 0), 'arg', (), 'KEYWORD_LABEL'),
            (('body', 13, 'value', 'keywords', 1), 'arg', (), 'KEYWORD_UNPACK_MARKER'),
            (('body', 17, 'value'), 'keys', (0,), 'DICT_UNPACK_KEY_MARKER'),
            (('body', 18, 'args'), 'kw_defaults', (0,), 'REQUIRED_KWONLY_DEFAULT_MARKER'),
            (('body', 19, 'cases', 0, 'pattern'), 'name', (), 'PATTERN_WILDCARD'),
            (('body', 19, 'cases', 1, 'pattern', 'patterns', 0), 'name', (), 'PATTERN_WILDCARD'),
            (('body', 19, 'cases', 2, 'pattern', 'patterns', 0), 'name', (), 'PATTERN_AS_BINDING_SYNTAX'),
            (('body', 19, 'cases', 3, 'pattern'), 'rest', (), 'PATTERN_MAPPING_BINDING_SYNTAX'),
            (('body', 19, 'cases', 4, 'pattern'), 'kwd_attrs', (0,), 'PATTERN_ATTRIBUTE_LABEL'),
        ]
        for path, field, item_path, role in checks:
            answer = api.role_at_slot(syntax, _slot(syntax, path, field, item_path=item_path))
            assert answer.role == role, (path, field, answer)
        view = api.SyntaxRoleView(syntax)
        expected_answers = [(site := _slot(syntax, path, field, item_path=item_path),
                             api.role_at_slot(syntax, site)) for path, field, item_path, _ in checks]
        def no_new_view(*args, **kwargs):
            raise AssertionError('repeated queries must reuse the already indexed view')
        with monkeypatch.context() as patch:
            patch.setattr(api.SyntaxRoleView, '__init__', no_new_view)
            for site, expected_answer in expected_answers:
                assert view.resolve(site) == api.role_at_slot(view, site) == expected_answer
        simple = api.role_at_slot(syntax, _slot(syntax, ('body', 1, 'target'), 'id'))
        parenthesized = api.role_at_slot(syntax, _slot(syntax, ('body', 2, 'target'), 'id'))
        assert 'ANNASSIGN_SIMPLE' in simple.qualifiers and 'ANNASSIGN_NON_SIMPLE' in parenthesized.qualifiers
        attribute = api.role_at_slot(syntax, _slot(syntax, ('body', 4, 'target'), 'attr'))
        assert 'DECLARATION_ONLY' in attribute.qualifiers
        assert attribute.context_owner == _occurrence(syntax, ('body', 4))
        walrus = api.role_at_slot(syntax, _slot(syntax, ('body', 5, 'value', 'elt', 'target'), 'id'))
        assert walrus.context_owner == _occurrence(syntax, ('body', 5, 'value', 'elt'))
        for body, projection in ((7, 'IMPORT_HEAD'), (9, 'IDENTITY')):
            site = _slot(syntax, ('body', body, 'names', 0), 'name')
            assert any(port.site == site and port.role == 'IMPORT_BINDING_SYNTAX'
                       and port.projection == projection for port in material.ports)
        for body in (8, 11):
            site = _slot(syntax, ('body', body, 'names', 0), 'name')
            assert not any(port.site == site and port.role == 'IMPORT_BINDING_SYNTAX' for port in material.ports)
        for path, field, role in (
            (('body', 14, 'annotation'), 'value', 'LITERAL_PAYLOAD'),
            (('body', 15), 'type_comment', 'TYPE_COMMENT_TEXT'),
            (('body', 16, 'value', 'values', 0), 'str', 'INTERPOLATION_SOURCE_TEXT')):
            site = _slot(syntax, path, field)
            assert api.role_at_slot(syntax, site).role == role
            assert not any(port.site == site for port in material.ports)
        for path, role in ((('body', 20, 'value'), 'LITERAL_PAYLOAD'),
                           (('body', 19, 'cases', 5, 'pattern'), 'PATTERN_SINGLETON_VALUE')):
            answer = api.role_at_slot(view, _slot(syntax, path, 'value'))
            assert answer.state == 'NONE' and answer.role == role and answer.projection == 'IDENTITY'
        for path, field in ((('body', 13, 'value', 'keywords', 1), 'arg'),
                            (('body', 12), 'module')):
            answer = api.role_at_slot(view, _slot(syntax, path, field))
            assert answer.state == 'NONE' and answer.projection == 'NO_VALUE'
        return

    with pytest.raises((TypeError, ValueError)):
        SlotRef(0, 'FIELD', 0, [])
    # Count every original slot and list item independently of classifier counters.
    expected_counts = {key: [0, 0, 0, 0, 0, 0] for key in keys}
    for node in syntax.nodes:
        cls = classes[node.constructor]
        for group, names, values in (('FIELD', cls._fields, node.fields), ('ATTRIBUTE', cls._attributes, node.attributes)):
            for ordinal, (name, value) in enumerate(zip(names, values)):
                row = expected_counts[node.constructor, group, ordinal, name]
                state = 1 if value.kind == 'ABSENT' else 2 if value.kind == 'SCALAR' and value.scalar.to_python() is None else 3 if value.kind == 'LIST' and not value.items else 4
                row[0] += 1; row[state] += 1
                row[5] += len(value.items) if value.kind == 'LIST' else 0
    for rule, counted in zip(rules, material.counts):
        assert [counted.slots, counted.absent, counted.none, counted.empty_list, counted.values, counted.list_items] == expected_counts[rule['constructor'], rule['group'], rule['ordinal'], rule['name']]
    assert material.slots == sum(len(node.fields) + len(node.attributes) for node in syntax.nodes)
    assert material.list_items == sum(row[5] for row in expected_counts.values())
    assert len(material.ports) < material.slots
    assert all(set(port) == {'site', 'rule', 'role', 'projection', 'context_owner', 'qualifiers'} for port in document['ports'])
    wire = json.dumps(document)
    assert all(payload not in wire for payload in ('Forward.Name', 'CommentType', 'item.attribute + other'))
    original_compile = builtins.compile
    def only_ast(source, filename, mode, flags=0, **kwargs):
        assert flags & ast.PyCF_ONLY_AST
        return original_compile(source, filename, mode, flags=flags, **kwargs)
    def forbidden(*args, **kwargs):
        raise AssertionError('F3-B must not invoke symbol analysis')
    with monkeypatch.context() as patch:
        patch.setattr(builtins, 'compile', only_ast)
        patch.setattr(_symtable, 'symtable', forbidden)
        assert api.read_source_roles(api.source_roles_document(*inputs), *inputs) == material
        for mode, text in (('exec', 'x=1\n'), ('eval', 'value'), ('single', 'x=1\n'),
                           ('func_type', '(int) -> str'), ('exec', 'return value\n'), ('exec', 'nonlocal value\n')):
            assert api.source_roles_document(*_inputs(text, mode=mode))['status'] == 'CLASSIFIED'
    for limit in (dict(max_ports=0), dict(max_slots=0)):
        stopped = api.source_roles_document(*inputs, **limit)
        assert stopped['status'] == 'BUDGET_STOPPED' and stopped['ports'] == [] and stopped['slots'] == 0
        assert stopped['frontiers'][0]['code'] == ('PORT_BUDGET' if 'max_ports' in limit else 'SLOT_BUDGET')
        assert api.read_source_roles(stopped, *inputs).status == 'BUDGET_STOPPED'
    for source, max_tokens in (('x = if :\n', 2_000_000), ('x=(\n', 2_000_000), ('x=1\n', 0)):
        upstream = _inputs(source, max_tokens=max_tokens)
        result = api.source_roles_document(*upstream)
        assert result['status'] == 'UPSTREAM_NOT_PARSED' and result['ports'] == []
        assert api.read_source_roles(result, *upstream).slots == 0
    for route, replacement in (
        (('runtime_effects',), 'PROVEN'), (('scope_binding',), 'BOUND'),
        (('profile', 'catalog_sha256'), '0' * 64),
        (('ports', 0, 'site', 'occurrence'), True),
        (('ports', 0, 'projection'), 'IMPORT_HEAD'),
        (('ports', 0, 'extra'), None), (('slots',), 0), (('extra',), [])):
        changed = deepcopy(document)
        target = changed
        for part in route[:-1]:
            target = target[part]
        target[route[-1]] = replacement
        with pytest.raises((TypeError, ValueError)):
            api.read_source_roles(changed, *inputs)
