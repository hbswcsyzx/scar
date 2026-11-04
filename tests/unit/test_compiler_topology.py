"""C3-T public scope topology, independently checked without symbol projection."""
import _symtable
import ast
from copy import deepcopy
import json
import sys

import pytest

from scar.analysis.source_bytes import decoded_source_bytes, source_bytes_document
from scar.analysis.source_tokens import source_tokens_document
from scar.analysis.source_syntax import source_syntax_document
from scar.analysis.source_roles import source_roles_document
from scar.analysis.source_contexts import source_contexts_document
from scar.analysis.source_symbols import source_symbols_document
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.program.source_roles import SourceRolesMaterial
from scar.ir.program.source_contexts import SourceContextsMaterial
from scar.ir.record_codec import decode


pytestmark = pytest.mark.skipif(
    sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 14, 7),
    reason='compiler scope topology is pinned to CPython 3.14.7')


def _inputs(text, *, mode='exec', max_tokens=2_000_000):
    f0 = source_bytes_document(text.encode(), path='/source/topology.py', namespace_root='/source')
    f1 = source_tokens_document(f0, max_tokens=max_tokens)
    f2 = source_syntax_document(f0, f1, mode=mode)
    roles = source_roles_document(f0, f1, f2)
    contexts = source_contexts_document(f0, f1, f2, roles)
    return f0, f1, f2, roles, contexts, source_symbols_document(f0, f1, f2)


def _occurrence(syntax, path):
    node, index = syntax.nodes[syntax.root], syntax.root
    for part in path:
        node = node.fields[getattr(ast, node.constructor)._fields.index(part)] if isinstance(part, str) else node.items[part]
        if node.kind == 'NODE':
            index, node = node.reference, syntax.nodes[node.reference]
    return index


def _oracle(f0, mode):
    """Two-pass native metadata graph; no raw flags, parameters or pointer IDs."""
    source = decoded_source_bytes(f0).replace('\r\n', '\n').replace('\r', '\n')
    root = _symtable.symtable(source, f0['path'], mode)
    objects, local, pending = [], {}, [root]
    while pending:
        node = pending.pop(0)
        if id(node) in local:
            continue
        local[id(node)] = len(objects)
        objects.append(node)
        pending.extend(node.children)
    return tuple((node.type, node.name, node.lineno, node.nested,
                  tuple(local[id(child)] for child in node.children)) for node in objects)


def _signature_source():
    return '''@decorate(lambda: DECORATOR)
def f[T: (lambda: BOUND) = (lambda: DEFAULT)](first=(lambda: POSITIONAL), *,last=(lambda: KEYWORD)) -> (lambda: RETURN):
    return lambda: BODY
left=lambda: 1; right=lambda: 1
type A = int; type A = int
'''


def _annotations_source():
    return '''module:(lambda: MODULE)
class C:
    one:(lambda: FIRST)
    two:(lambda: SECOND)
    def plain(self): pass
    def method(self,arg:(lambda: ARG)) -> [piece for piece in RESULT]:
        local:(lambda: LOCAL)
        return arg
outside=[lambda:item for item in DATA]
gen=(lambda:item for item in DATA)
'''


@pytest.mark.parametrize('family', ('visitor', 'annotation_and_inline', 'codec_and_budgets'))
def test_c3t_compiler_topology(family, monkeypatch):
    import _ast
    import scar.analysis.compiler_topology as api
    from scar.analysis.compiler_topology_view import CompilerTopologyView
    from scar.analysis.source_context_view import SourceContextView

    def built(source, *, mode='exec', max_tokens=2_000_000):
        inputs = _inputs(source, mode=mode, max_tokens=max_tokens)
        doc = api.compiler_topology_document(*inputs)
        material = api.read_compiler_topology(json.loads(json.dumps(doc)), *inputs)
        syntax = decode(SourceSyntaxMaterial, inputs[2])
        roles = decode(SourceRolesMaterial, inputs[3])
        contexts = decode(SourceContextsMaterial, inputs[4])
        from scar.ir.program.source_symbols import SourceSymbolsMaterial
        native = decode(SourceSymbolsMaterial, inputs[5])
        return inputs, doc, material, syntax, roles, contexts, native

    def assert_native(inputs, material, syntax, contexts):
        # Actual predictions use only source origins; the golden comes from a
        # separate official call and never from production's stored A rows.
        expected = _oracle(inputs[0], inputs[2]['mode'])
        metadata = api._block_metadata(material.blocks, syntax, contexts)
        children = api._projection_children(material.blocks)
        public = {row.public_scope: index for index, row in enumerate(material.blocks) if row.projection == 'PUBLIC'}
        assert set(public) == set(range(len(expected)))
        for native_scope, block in public.items():
            assert metadata[block] == expected[native_scope][:4]
            assert tuple(material.blocks[index].public_scope for index in children[block]) == expected[native_scope][4]

    def scope_block(material, contexts, occurrence, kind, owner_kind=None):
        candidates = [index for index, row in enumerate(contexts.scopes) if row.owner.occurrence == occurrence
                      and row.kind == kind and (owner_kind is None or row.owner.kind == owner_kind)]
        assert len(candidates) == 1, (occurrence, kind, owner_kind, candidates)
        return material.scopes[candidates[0]].block

    if family == 'visitor':
        inputs, _, material, syntax, roles, contexts, native = built(_signature_source())
        assert material.status == 'PROJECTED'
        assert_native(inputs, material, syntax, contexts)
        root = scope_block(material, contexts, syntax.root, 'ROOT_EXEC')
        function = _occurrence(syntax, ('body', 0))
        parent = scope_block(material, contexts, function, 'TYPE_PARAMETERS')
        root_origins = [material.blocks[index].origin for index in material.blocks[root].children]
        expected_root = [
            (_occurrence(syntax, ('body', 0, 'args', 'defaults', 0)), 'LAMBDA_BODY'),
            (_occurrence(syntax, ('body', 0, 'args', 'kw_defaults', 0)), 'LAMBDA_BODY'),
            (_occurrence(syntax, ('body', 0, 'decorator_list', 0, 'args', 0)), 'LAMBDA_BODY'),
            (function, 'TYPE_PARAMETERS'),
            (_occurrence(syntax, ('body', 1, 'value')), 'LAMBDA_BODY'),
            (_occurrence(syntax, ('body', 2, 'value')), 'LAMBDA_BODY'),
            (_occurrence(syntax, ('body', 3)), 'TYPE_ALIAS'),
            (_occurrence(syntax, ('body', 4)), 'TYPE_ALIAS')]
        assert [(row.occurrence, row.role) for row in root_origins] == expected_root
        parameter_children = material.blocks[parent].children
        assert [material.blocks[index].origin.role for index in parameter_children] == [
            'TYPE_PARAMETER_BOUND', 'TYPE_PARAMETER_DEFAULT', 'HEADER_ANNOTATIONS', 'FUNCTION_BODY']
        assert material.blocks[parameter_children[0]].origin != material.blocks[parameter_children[1]].origin
        for left, right in ((4, 5), (6, 7)):
            a, b = material.blocks[root].children[left], material.blocks[root].children[right]
            assert a != b and material.blocks[a].public_scope != material.blocks[b].public_scope
        # All field/constructor dispatches are closed over the official schema.
        catalog = api.compiler_topology_catalog()
        classes = {name: cls for name, cls in vars(_ast).items()
                   if isinstance(cls, type) and issubclass(cls, ast.AST) and '_field_types' in vars(cls)}
        expected_fields = {(name, group, ordinal, field) for name, cls in classes.items()
                           for group, names in (('FIELD', cls._fields), ('ATTRIBUTE', cls._attributes))
                           for ordinal, field in enumerate(names)}
        assert len(catalog['constructors']) == len(classes) == 113
        assert {row['name'] for row in catalog['constructors']} == set(classes)
        assert len(catalog['fields']) == 484
        assert {(row['constructor'], row['group'], row['ordinal'], row['name']) for row in catalog['fields']} == expected_fields
        assert all(row['dispatch'] and 'UNKNOWN' not in row['dispatch'] for row in catalog['fields'])
        return

    inputs, document, material, syntax, roles, contexts, native = built(_annotations_source())
    assert material.status == 'PROJECTED'
    assert_native(inputs, material, syntax, contexts)
    if family == 'annotation_and_inline':
        cls = _occurrence(syntax, ('body', 1))
        shared = scope_block(material, contexts, cls, 'ANNOTATION', 'VARIABLE_ANNOTATIONS')
        assert len(material.blocks[shared].children) == 2
        assert [material.blocks[index].origin.occurrence for index in material.blocks[shared].children] == [
            _occurrence(syntax, ('body', 1, 'body', 0, 'annotation')),
            _occurrence(syntax, ('body', 1, 'body', 1, 'annotation'))]
        plain = _occurrence(syntax, ('body', 1, 'body', 2))
        plain_body = scope_block(material, contexts, plain, 'FUNCTION')
        siblings = material.blocks[material.blocks[plain_body].parent].children
        header = material.blocks[siblings[siblings.index(plain_body) - 1]]
        assert header.origin.role == 'HEADER_ANNOTATIONS' and header.source_scope is None
        assert header.projection == 'PUBLIC'
        local = _occurrence(syntax, ('body', 1, 'body', 3, 'body', 0, 'annotation'))
        local_block = scope_block(material, contexts, local, 'LAMBDA')
        assert material.blocks[local_block].projection == 'PUBLIC'
        visible_comp = _occurrence(syntax, ('body', 1, 'body', 3, 'returns'))
        visible_block = scope_block(material, contexts, visible_comp, 'COMPREHENSION')
        assert material.blocks[visible_block].projection == 'PUBLIC'
        parent = material.blocks[visible_block].parent
        assert material.blocks[parent].can_see_class_scope
        outside = _occurrence(syntax, ('body', 2, 'value'))
        inline = scope_block(material, contexts, outside, 'COMPREHENSION')
        child = scope_block(material, contexts, _occurrence(syntax, ('body', 2, 'value', 'elt')), 'LAMBDA')
        assert material.blocks[inline].projection == 'INLINED' and material.blocks[inline].public_scope is None
        assert material.blocks[child].parent == inline
        projected = api._projection_children(material.blocks)
        assert child in projected[material.blocks[inline].parent] and inline not in projected[material.blocks[inline].parent]
        generator = scope_block(material, contexts, _occurrence(syntax, ('body', 3, 'value')), 'GENERATOR_EXPRESSION')
        assert material.blocks[generator].projection == 'PUBLIC'
        future_source = 'from __future__ import annotations\n' + _annotations_source()
        future = built(future_source)
        assert_native(future[0], future[2], future[3], future[5])
        future_material, future_syntax, future_contexts = future[2], future[3], future[5]
        detached_comp = scope_block(future_material, future_contexts,
            _occurrence(future_syntax, ('body', 2, 'body', 3, 'returns')), 'COMPREHENSION')
        assert future_material.blocks[detached_comp].projection == 'DETACHED_DESCENDANT'
        assert future_material.blocks[detached_comp].public_scope is None
        assert any(row.projection == 'FUTURE_DETACHED' for row in future_material.blocks)
        return

    view = CompilerTopologyView(roles, contexts, native, material,
                               contexts=SourceContextView(syntax, roles, contexts))
    report = view.verify()
    assert report['scopes'] == len(contexts.scopes) and report['regions'] == len(contexts.regions)
    assert [row.scope for row in material.scopes] == list(range(len(contexts.scopes)))
    for index, row in enumerate(material.scopes):
        assert view.scope(index) == row
    for index in range(len(contexts.regions)):
        assert view.region(index) in material.scopes
    for index in range(len(roles.ports)):
        assert view.port(index) in material.scopes
    assert material.symbol_origin_projection == material.parameter_projection == 'NOT_COMPUTED_IN_C3T'
    assert material.runtime_execution == 'NOT_OBSERVED'
    for limit in ('max_blocks', 'max_rewrites', 'max_visit_steps'):
        stopped = api.compiler_topology_document(*inputs, **{limit: 0})
        assert stopped['status'] == 'BUDGET_STOPPED' and stopped['blocks'] == [] and stopped['scopes'] == []
        assert api.read_compiler_topology(stopped, *inputs).status == 'BUDGET_STOPPED'
    for mode, source in (('eval', 'lambda: value'), ('single', 'f=lambda: value\n'), ('func_type', '(int) -> str')):
        tiny = built(source, mode=mode)
        assert tiny[2].status == ('SOURCE_ONLY_MODE' if mode == 'func_type' else 'PROJECTED')
        if mode == 'func_type':
            assert not tiny[2].blocks and all(row.disposition == 'GRAMMAR_ONLY' for row in tiny[2].scopes)
        else:
            assert_native(tiny[0], tiny[2], tiny[3], tiny[5])
    for source, tokens, expected in (('x=1\n', 0, 'UPSTREAM_NOT_CONTEXTUALIZED'),
                                      ('def f(x,x):pass\n', 2_000_000, 'UPSTREAM_NOT_CAPTURED')):
        upstream = built(source, max_tokens=tokens)
        assert upstream[2].status == expected and not upstream[2].blocks
    for route, replacement in (
        (('symbol_origin_projection',), 'COMPUTED'), (('parameter_projection',), 'COMPUTED'),
        (('runtime_execution',), 'OBSERVED'), (('blocks', 0, 'public_scope'), True),
        (('blocks', 0, 'children'), [0]), (('scopes', 0, 'block'), 10**6),
        (('blocks', 0, 'extra'), None), (('extra',), [])):
        changed = deepcopy(document)
        target = changed
        for part in route[:-1]:
            target = target[part]
        target[route[-1]] = replacement
        with pytest.raises((TypeError, ValueError)):
            api.read_compiler_topology(changed, *inputs)
