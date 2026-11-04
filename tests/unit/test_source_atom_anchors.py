"""F2 occurrence/legacy-ID identity joins; no execution or optimizer proof.

Expected IDs come from the original frontend and an independent AST BFS
oracle. Synthetic occurrence mutations below exercise identity mechanics;
they are deliberately not fresh-parser evidence.
"""
import ast
import builtins
from copy import deepcopy
from dataclasses import replace
import hashlib
import sys

import pytest

from scar.analysis.source_bytes import source_bytes_document
from scar.analysis.source_syntax import source_syntax_document
from scar.analysis.source_tokens import source_tokens_document
from scar.ir.frontend_v2 import build_semantic_source_texts
from scar.ir.literals import PythonLiteral
from scar.ir.program.source_syntax import AstValue, SourceSyntaxMaterial
from scar.ir.record_codec import decode, encode
from scar.ir.v2.ids import SourceAtomID


pytestmark = pytest.mark.skipif(
    sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 14, 7),
    reason='F2 and the legacy frontend are pinned to CPython 3.14.7')

PATH = '/source/package/material.py'
ROOT = '/source'
ATOM_CLASSES = (ast.stmt, ast.expr, ast.arg, ast.alias, ast.keyword, ast.ExceptHandler)


def _api():
    from scar.analysis import source_atom_anchors
    return source_atom_anchors


def _inputs(text):
    f0 = source_bytes_document(text.encode(), path=PATH, namespace_root=ROOT)
    f1 = source_tokens_document(f0)
    f2 = source_syntax_document(f0, f1)
    syntax = decode(SourceSyntaxMaterial, f2)
    assert syntax.status == 'PARSED'
    semantic = build_semantic_source_texts([PATH], ROOT, sources={PATH: text},
        root_is_package=False).graph.to_dict()
    tree = ast.parse(text, filename=PATH, type_comments=True)
    return f0, f1, f2, syntax, semantic, tree


def _oracle(text, tree):
    """Do not obtain ordinals, IDs or selected kinds from the new bridge."""
    fingerprint = 'sha256:' + hashlib.sha256(text.encode()).hexdigest()
    rows = []
    for ordinal, node in enumerate(ast.walk(tree)):
        if isinstance(node, ATOM_CLASSES) and hasattr(node, 'lineno'):
            kind = type(node).__name__
            payload = f'package/material.py:{fingerprint}:{ordinal}:{kind}'
            atom = SourceAtomID('atom:' + hashlib.sha256(payload.encode()).hexdigest()[:24])
            rows.append((atom, ordinal, kind, (node.lineno, node.end_lineno or node.lineno,
                node.col_offset, node.end_col_offset)))
    return rows


def _field(syntax, occurrence, name, *, attributes=False):
    node = syntax.nodes[occurrence]
    schema = next(row for row in syntax.profile.ast_schema if row.name == node.constructor)
    names = schema.attributes if attributes else schema.fields
    return names.index(name), (node.attributes if attributes else node.fields)[names.index(name)]


def _reject(call):
    A = _api()
    with pytest.raises(A.SourceAnchorError) as error:
        call()
    assert error.value.code and error.value.path and error.value.detail
    return error.value


def test_complete_legacy_atom_set_matches_independent_bfs_with_markers_and_newlines():
    A = _api()
    corpus = (
        'result = first + second * third\n',
        'value = 1 # type: int\r\nother = 2 # type: ignore[tag]\r\n',
        'import package as alias\ndef f(arg: T = 1, *, option=None):\n'
        '    try:\n        return action(arg, named=option)\n'
        '    except Error as error:\n        return error\n',
        'α = [1e999, 2j, ..., b"\\x00\\xff", u"text"]\n'
        'template = t"{α!r}"\nformatted = f"{α}"\n',
    )
    saw_non_bfs_storage = False
    for text in corpus:
        f0, f1, f2, syntax, semantic, tree = _inputs(text)
        expected = _oracle(text, tree)
        material = A.build_source_atom_anchors(f0, syntax, semantic, namespace_root=ROOT)
        assert [(row.atom, row.breadth_first_ordinal) for row in material.anchors] == [
            (atom, ordinal) for atom, ordinal, _, _ in expected]
        assert material.occurrences == sum(1 for _ in ast.walk(tree))
        assert material.input.fingerprint == 'sha256:' + hashlib.sha256(text.encode()).hexdigest()
        assert material.authority == 'SOURCE_ATOM_IDENTITY_ONLY'
        atoms = {row['id']['wire']: row for row in semantic['source_atoms']}
        view = A.SourceAtomAnchorView(syntax, material)
        for row, (atom, ordinal, kind, span) in zip(material.anchors, expected):
            assert view.atom(atom) == row and view.occurrence(row.occurrence) == row
            original = atoms[atom.wire]
            reference = original['reference']
            assert original['kind'] == syntax.nodes[row.occurrence].constructor == kind
            assert tuple(reference[name] for name in ('start_line', 'end_line', 'start_column', 'end_column')) == span
            assert row.breadth_first_ordinal == ordinal
            saw_non_bfs_storage |= row.occurrence != ordinal
        assert view.occurrence(syntax.root) is None
        name = next(row for row in material.anchors if syntax.nodes[row.occurrence].constructor == 'Name')
        site, value = view.field(name.atom, 'id')
        field_index, expected_value = _field(syntax, name.occurrence, 'id')
        assert (site.occurrence, site.group, site.ordinal, site.item_path) == (name.occurrence, 'FIELD', field_index, ())
        assert value == expected_value
    assert saw_non_bfs_storage


def test_same_span_occurrences_keep_distinct_ids_without_claiming_parser_evidence():
    A = _api()
    f0, _, _, syntax, semantic, _ = _inputs('result = first + second\n')
    original = A.build_source_atom_anchors(f0, syntax, semantic, namespace_root=ROOT)
    names = { _field(syntax, row.occurrence, 'id')[1].scalar.to_python(): row
        for row in original.anchors if syntax.nodes[row.occurrence].constructor == 'Name'}
    first, second = names['first'], names['second']
    nodes = list(syntax.nodes)
    nodes[second.occurrence] = replace(nodes[second.occurrence], attributes=nodes[first.occurrence].attributes)
    synthetic = replace(syntax, nodes=tuple(nodes))
    changed = deepcopy(semantic)
    atoms = {row['id']['wire']: row for row in changed['source_atoms']}
    for name in ('start_line', 'end_line', 'start_column', 'end_column'):
        atoms[second.atom.wire]['reference'][name] = atoms[first.atom.wire]['reference'][name]
    material = A.build_source_atom_anchors(f0, synthetic, changed, namespace_root=ROOT)
    view = A.SourceAtomAnchorView(synthetic, material)
    assert view.atom(first.atom).occurrence == first.occurrence
    assert view.atom(second.atom).occurrence == second.occurrence
    assert first.atom != second.atom and first.occurrence != second.occurrence
    assert material.authority == 'SOURCE_ATOM_IDENTITY_ONLY'


def test_whole_source_atom_equality_rejects_missing_extra_duplicate_and_drift():
    A = _api()
    f0, _, _, syntax, semantic, _ = _inputs('def first(x):\n    return x\ndef second(y):\n    return y\n')
    missing = deepcopy(semantic)
    missing['source_atoms'].pop()
    duplicate = deepcopy(semantic)
    duplicate['source_atoms'].append(deepcopy(duplicate['source_atoms'][0]))
    extra = deepcopy(semantic)
    added = deepcopy(extra['source_atoms'][0])
    added['id'] = SourceAtomID('extra-source-atom').as_dict()
    added['reference']['atom_id'] = added['id']
    extra['source_atoms'].append(added)
    drifted = deepcopy(semantic)
    drifted['source_atoms'][0]['reference']['start_column'] += 1
    for changed in (missing, extra, duplicate, drifted):
        _reject(lambda changed=changed: A.build_source_atom_anchors(f0, syntax, changed, namespace_root=ROOT))
    material = A.build_source_atom_anchors(f0, syntax, semantic, namespace_root=ROOT)
    _reject(lambda: A.SourceAtomAnchorView(syntax, replace(material, anchors=material.anchors[:-1])))


def test_input_lineage_namespace_and_strict_document_pins_are_not_self_authorizing():
    A = _api()
    text = 'result = first + second\n'
    f0, f1, f2, syntax, semantic, _ = _inputs(text)
    document = A.source_atom_anchors_document(f0, f1, f2, semantic, namespace_root=ROOT)
    view = A.read_source_atom_anchors(document, f0, f1, f2, semantic, namespace_root=ROOT)
    expected = A.build_source_atom_anchors(f0, syntax, semantic, namespace_root=ROOT)
    assert view.atom(expected.anchors[0].atom) == expected.anchors[0]
    for root in ('/source/package', '/different', '/source/../source'):
        _reject(lambda root=root: A.build_source_atom_anchors(f0, syntax, semantic, namespace_root=root))
    _reject(lambda: A.build_source_atom_anchors(f0,
        replace(syntax, input=replace(syntax.input, f0_document_sha256='0' * 64)), semantic, namespace_root=ROOT))
    for field in ('f0_sha256', 'f2_sha256', 'semantic_sha256', 'fingerprint', 'namespace_root'):
        changed = deepcopy(document)
        changed['input'][field] = '/different' if field == 'namespace_root' else (
            'sha256:' + '0' * 64 if field == 'fingerprint' else '0' * 64)
        _reject(lambda changed=changed: A.read_source_atom_anchors(changed, f0, f1, f2,
            semantic, namespace_root=ROOT))
    # Same-kind/span scalar changes are the upstream F2 reader's obligation,
    # not something the legacy Atom identity fields can independently detect.
    scalar_change = deepcopy(f2)
    name = next(i for i, row in enumerate(syntax.nodes) if row.constructor == 'Name')
    ordinal, _ = _field(syntax, name, 'id')
    scalar_change['nodes'][name]['fields'][ordinal]['scalar'] = encode(
        PythonLiteral.from_python('different', exact=True))
    _reject(lambda: A.read_source_atom_anchors(document, f0, f1, scalar_change, semantic, namespace_root=ROOT))


def test_bfs_structure_and_attributes_are_checked_against_original_references():
    A = _api()
    f0, _, _, syntax, semantic, _ = _inputs('first = left + right\nsecond = other\n')
    root = syntax.nodes[syntax.root]
    body_index, body = _field(syntax, syntax.root, 'body')
    fields = list(root.fields)
    fields[body_index] = replace(body, items=tuple(reversed(body.items)))
    nodes = list(syntax.nodes)
    nodes[syntax.root] = replace(root, fields=tuple(fields))
    _reject(lambda: A.build_source_atom_anchors(f0, replace(syntax, nodes=tuple(nodes)),
        semantic, namespace_root=ROOT))
    name = next(i for i, row in enumerate(syntax.nodes) if row.constructor == 'Name')
    ctx_index, _ = _field(syntax, name, 'ctx')
    missing_marker = list(syntax.nodes[name].fields)
    missing_marker[ctx_index] = AstValue('ABSENT', None, (), None)
    nodes = list(syntax.nodes)
    nodes[name] = replace(nodes[name], fields=tuple(missing_marker))
    _reject(lambda: A.build_source_atom_anchors(f0, replace(syntax, nodes=tuple(nodes)),
        semantic, namespace_root=ROOT))
    shortened = list(syntax.nodes)
    shortened[name] = replace(shortened[name], fields=shortened[name].fields[:-1])
    _reject(lambda: A.build_source_atom_anchors(f0, replace(syntax, nodes=tuple(shortened)),
        semantic, namespace_root=ROOT))


def test_pure_identity_kernel_never_parses_walks_or_restores_ast(monkeypatch):
    A = _api()
    f0, _, _, syntax, semantic, tree = _inputs('def f(x):\n    return x + x\n')
    expected = _oracle('def f(x):\n    return x + x\n', tree)
    from scar.analysis import source_syntax
    # Resolve SCAR's own postponed type annotations before forbidding compile;
    # this is separate from parsing or restoring any target-source AST.
    A.build_source_atom_anchors(f0, syntax, semantic, namespace_root=ROOT)

    def forbidden(*args, **kwargs):
        raise AssertionError('the pure identity kernel attempted AST parsing/restoration/traversal')

    for name in ('parse', 'walk', 'iter_child_nodes', 'iter_fields'):
        monkeypatch.setattr(ast, name, forbidden)
    monkeypatch.setattr(builtins, 'compile', forbidden)
    monkeypatch.setattr(source_syntax, '_restore_ast', forbidden)
    monkeypatch.setattr(source_syntax, '_produce', forbidden)
    material = A.build_source_atom_anchors(f0, syntax, semantic, namespace_root=ROOT)
    assert [(row.atom, row.breadth_first_ordinal) for row in material.anchors] == [
        (atom, ordinal) for atom, ordinal, _, _ in expected]
