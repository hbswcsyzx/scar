"""C1 source contexts: closed field routes, without name/key/runtime solving."""
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
from scar.analysis.source_roles import source_roles_document
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.record_codec import decode


pytestmark = pytest.mark.skipif(
    sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 14, 7),
    reason='the context rules are pinned to CPython 3.14.7')


def _inputs(text, *, mode='exec', max_tokens=2_000_000):
    f0 = source_bytes_document(text.encode(), path='/source/contexts.py', namespace_root='/source')
    f1 = source_tokens_document(f0, max_tokens=max_tokens)
    f2 = source_syntax_document(f0, f1, mode=mode)
    return f0, f1, f2, source_roles_document(f0, f1, f2)


def _occurrence(syntax, path):
    value = syntax.nodes[syntax.root]
    index = syntax.root
    for part in path:
        value = value.fields[getattr(ast, value.constructor)._fields.index(part)] if isinstance(part, str) else value.items[part]
        if value.kind == 'NODE':
            index = value.reference
            value = syntax.nodes[index]
    return index


def _slot(syntax, path, field, *, group='FIELD', item_path=()):
    from scar.ir.program.source_roles import SlotRef
    index = _occurrence(syntax, path)
    cls = getattr(ast, syntax.nodes[index].constructor)
    return SlotRef(index, group, (cls._fields if group == 'FIELD' else cls._attributes).index(field), item_path)


def _source():
    return '''def outer():
    @decorate((yield decorator_value))
    def inner[T: bound_name = default_name](arg: annotation_name=(yield default_value),*,kw:kwannotation_name=(yield kwdefault_value))->return_annotation:
        local:(lambda: local_annotation)
        values=[(lambda p=element_default: element_body) for item in first_source for other in later_source(item) if predicate(other)]
        gen=(piece for piece in gen_first if gen_guard(piece))
        return arg
    return inner
class __Outer:
    @__decor(__decoarg)
    class __Inner[__T: (lambda __arg:(__arg,__T,__Bound)) = __Default](__Base[__T],keyword=__Kw):
        __field:__T
        def __method(__self,__arg:__T=__default):
            return __external,__T
    class __Plain(__Base):
        pass
value:(lambda: module_annotation)
(parenthesized):(lambda: nonsimple_annotation)
obj.attribute:(lambda: attribute_annotation)
assigned:(lambda: assigned_annotation)=rhs
'''


def _special_fields():
    # Handwritten reviewed routes, independent of the producer catalog.
    groups = {
        'FunctionDef': ('args', 'body', 'decorator_list', 'returns', 'type_params'),
        'AsyncFunctionDef': ('args', 'body', 'decorator_list', 'returns', 'type_params'),
        'ClassDef': ('bases', 'keywords', 'body', 'decorator_list', 'type_params'),
        'Lambda': ('args', 'body'), 'AnnAssign': ('target', 'annotation', 'value'),
        'TypeAlias': ('name', 'type_params', 'value'),
        'arguments': ('posonlyargs', 'args', 'vararg', 'kwonlyargs', 'kw_defaults', 'kwarg', 'defaults'),
        'arg': ('annotation',), 'TypeVar': ('bound', 'default_value'),
        'TypeVarTuple': ('default_value',), 'ParamSpec': ('default_value',),
        'comprehension': ('target', 'iter', 'ifs'), 'ListComp': ('elt', 'generators'),
        'SetComp': ('elt', 'generators'), 'DictComp': ('key', 'value', 'generators'),
        'GeneratorExp': ('elt', 'generators'), 'FunctionType': ('argtypes', 'returns'),
        'NamedExpr': ('target',),
    }
    return {(constructor, field) for constructor, fields in groups.items() for field in fields}


_MARKERS = {(constructor, 'ctx') for constructor in ('Attribute', 'Subscript', 'Starred', 'Name', 'List', 'Tuple')} | {
    ('AugAssign', 'op'), ('BinOp', 'op'), ('BoolOp', 'op'), ('UnaryOp', 'op'),
    ('Compare', 'ops'), ('Module', 'type_ignores')}


@pytest.mark.parametrize('family', ('schema', 'matrix', 'coverage_and_gates'))
def test_c1_source_context_routes(family, monkeypatch):
    from scar.analysis.source_roles import source_role_catalog
    from scar.ir.program.source_roles import SourceRolesMaterial
    import scar.analysis.source_contexts as api

    base_rules = source_role_catalog()['rules']
    catalog = api.source_context_catalog()
    rules = catalog['rules']
    assert len(rules) == 484 and [row['rule'] for row in rules] == list(range(484))
    if family == 'schema':
        from typing import get_args
        def child_type(kind):
            return isinstance(kind, type) and issubclass(kind, ast.AST) or any(child_type(x) for x in get_args(kind))
        classes = {name: cls for name, cls in vars(_ast).items()
                   if isinstance(cls, type) and issubclass(cls, ast.AST) and '_field_types' in vars(cls)}
        children = {(name, field) for name, cls in classes.items()
                    for field, kind in cls._field_types.items() if child_type(kind)}
        expected = {(name, group, ordinal, field) for name, cls in classes.items()
                    for group, fields in (('FIELD', cls._fields), ('ATTRIBUTE', cls._attributes))
                    for ordinal, field in enumerate(fields)}
        assert len(classes) == 113 and len(expected) == 484
        assert {(row['constructor'], row['group'], row['ordinal'], row['name']) for row in base_rules} == expected
        assert len(children) == 157 and len(_special_fields()) == 50 and len(_MARKERS) == 12
        special, markers, inherited, payload = set(), set(), set(), set()
        for original, route in zip(base_rules, rules):
            key = original['constructor'], original['name']
            if original['group'] == 'FIELD' and key in children:
                if route['selector'] == 'INHERIT':
                    inherited.add(key)
                elif route['selector'] == 'NO_EVALUATION':
                    markers.add(key)
                    assert route['content_policy'] == 'SYNTAX_MARKER'
                else:
                    special.add(key)
            else:
                payload.add((original['constructor'], original['group'], original['name']))
                assert route['selector'] in ('PAYLOAD', 'FORMAL_NAME')
                assert route['content_policy'] == 'METADATA'
        assert special == _special_fields() and markers == _MARKERS
        assert inherited == children - _special_fields() - _MARKERS and len(inherited) == 95
        assert len(payload) == 327
        for name in ('Module', 'Interactive', 'Expression'):
            index = next(row['rule'] for row in base_rules if (row['constructor'], row['group'], row['name']) == (name, 'FIELD', 'body'))
            assert rules[index]['selector'] == 'INHERIT'
        return

    inputs = _inputs(_source())
    syntax = decode(SourceSyntaxMaterial, inputs[2])
    roles = decode(SourceRolesMaterial, inputs[3])
    document = api.source_contexts_document(*inputs)
    material = api.read_source_contexts(json.loads(json.dumps(document)), *inputs)
    view = api.SourceContextView(syntax, roles, material)
    assert material.status == 'CONTEXTUALIZED' and material.authority == 'SOURCE_CONTEXT_TEMPLATES'
    assert material.compiler_projection == 'NOT_COMPUTED_IN_C1' and material.runtime_frames == 'NOT_RECORDED'

    def query(path, field, item_path=()):
        return view.resolve(_slot(syntax, path, field, item_path=item_path))

    def context(path, field, item_path=()):
        resolution = query(path, field, item_path)
        state = resolution.state
        return (resolution, material.scopes[state.environment], material.regions[state.region],
                material.private_contexts[state.private_context])

    if family == 'matrix':
        outer = ('body', 0)
        function = (*outer, 'body', 0)
        parameter = (*function, 'type_params', 0)
        # These expected source paths and protocols are handwritten.
        checks = [
            ((*function, 'args', 'args', 0), 'arg', 'FUNCTION', function, 'FORMAL_INTERFACE'),
            ((*function, 'args', 'defaults', 0, 'value'), 'id', 'FUNCTION', outer, 'DECLARATION_TIME'),
            ((*function, 'args', 'kw_defaults', 0, 'value'), 'id', 'FUNCTION', outer, 'DECLARATION_TIME'),
            ((*function, 'decorator_list', 0, 'args', 0, 'value'), 'id', 'FUNCTION', outer, 'DECLARATION_TIME'),
            ((*function, 'args', 'args', 0, 'annotation'), 'id', 'ANNOTATION', function, 'ANNOTATION_REQUEST'),
            ((*function, 'returns'), 'id', 'ANNOTATION', function, 'ANNOTATION_REQUEST'),
            ((*parameter, 'bound'), 'id', 'TYPE_PARAMETER_EVALUATOR', parameter, 'TYPE_PARAMETER_BOUND_REQUEST'),
            ((*parameter, 'default_value'), 'id', 'TYPE_PARAMETER_EVALUATOR', parameter, 'TYPE_PARAMETER_DEFAULT_REQUEST'),
            ((*function, 'body', 3, 'value'), 'id', 'FUNCTION', function, 'FUNCTION_INVOCATION'),
        ]
        for path, field, kind, owner, trigger in checks:
            resolution, scope, region, _ = context(path, field)
            assert scope.kind == kind and scope.owner.occurrence == _occurrence(syntax, owner), path
            assert region.trigger == trigger and region.eligibility == 'ELIGIBLE', path
            assert resolution.content_policy == 'METADATA'
        formal = query((*function, 'args', 'args', 0), 'arg').state
        assert formal.owner.kind == 'FORMAL_INTERFACE' and formal.owner.occurrence == _occurrence(syntax, function)
        # A direct yield in a nested definition's default belongs to outer.
        default_state = query((*function, 'args', 'defaults', 0, 'value'), 'id').state
        assert default_state.owner.occurrence == _occurrence(syntax, outer)
        ancestry, index = [], default_state.region
        while index is not None:
            ancestry.append(material.regions[index].trigger)
            index = material.regions[index].parent
        assert 'GENERATOR_RESUMPTION' in ancestry
        comp = (*function, 'body', 1, 'value')
        first = context((*comp, 'generators', 0, 'iter'), 'id')
        later = context((*comp, 'generators', 1, 'iter', 'func'), 'id')
        assert first[1].owner.occurrence == _occurrence(syntax, function)
        assert later[1].kind == 'COMPREHENSION' and later[1].owner.occurrence == _occurrence(syntax, comp)
        lambda_node = (*comp, 'elt')
        lambda_default = context((*lambda_node, 'args', 'defaults', 0), 'id')
        lambda_body = context((*lambda_node, 'body'), 'id')
        assert lambda_default[1].owner.occurrence == _occurrence(syntax, comp)
        assert lambda_body[1].kind == 'LAMBDA' and lambda_body[1].owner.occurrence == _occurrence(syntax, lambda_node)
        gen = (*function, 'body', 2, 'value')
        assert context((*gen, 'generators', 0, 'iter'), 'id')[1].owner.occurrence == _occurrence(syntax, function)
        assert context((*gen, 'elt'), 'id')[2].trigger == 'GENERATOR_EXPRESSION_RESUMPTION'
        for path, reason in (
            ((*function, 'body', 0, 'annotation', 'body'), 'FUNCTION_LOCAL_ANNOTATION'),
            (('body', 3, 'annotation', 'body'), 'NON_SIMPLE_ANNOTATION'),
            (('body', 4, 'annotation', 'body'), 'NON_SIMPLE_ANNOTATION')):
            resolution, _, region, _ = context(path, 'id')
            assert resolution.content_policy == 'METADATA'
            assert region.trigger == 'FUNCTION_INVOCATION' and region.eligibility == 'SUPPRESSED'
            assert region.suppression_reason == reason and region.suppression_origin is not None
        assert context(('body', 4, 'target', 'value'), 'id')[2].eligibility == 'ELIGIBLE'
        assert context(('body', 5, 'value'), 'id')[1].kind == 'ROOT_EXEC'
        assert context(('body', 2, 'annotation', 'body'), 'id')[2].eligibility == 'ELIGIBLE'
        klass = ('body', 1, 'body', 0)
        private_checks = [
            ((*klass, 'decorator_list', 0, 'func'), 'id', 'ALL', ('body', 1)),
            ((*klass, 'bases', 0, 'value'), 'id', 'SELECTIVE', klass),
            ((*klass, 'type_params', 0, 'bound', 'args', 'args', 0), 'arg', 'SELECTIVE', klass),
            ((*klass, 'body', 1, 'args', 'defaults', 0), 'id', 'ALL', klass),
            (('body', 1, 'body', 1, 'bases', 0), 'id', 'ALL', ('body', 1)),
        ]
        for path, field, mode, owner in private_checks:
            _, _, _, private = context(path, field)
            assert private.mode == mode and private.class_owner.occurrence == _occurrence(syntax, owner)
            if mode == 'SELECTIVE':
                assert material.scopes[private.parameter_group].kind == 'TYPE_PARAMETERS'
        future_inputs = _inputs('from __future__ import annotations\n' + _source())
        future_syntax = decode(SourceSyntaxMaterial, future_inputs[2])
        future_material = api.read_source_contexts(api.source_contexts_document(*future_inputs), *future_inputs)
        future_view = api.SourceContextView(future_syntax, decode(SourceRolesMaterial, future_inputs[3]), future_material)
        answer = future_view.resolve(_slot(future_syntax, ('body', 3, 'annotation', 'body'), 'id'))
        region = future_material.regions[answer.state.region]
        assert answer.content_policy == 'METADATA' and region.eligibility == 'SUPPRESSED'
        assert region.trigger == 'FUNCTION_INVOCATION' and region.suppression_reason == 'FUTURE_ANNOTATION_STRINGIZED'
        single = _inputs('from __future__ import annotations; value: SomeType\n', mode='single')
        single_syntax = decode(SourceSyntaxMaterial, single[2])
        single_material = api.read_source_contexts(api.source_contexts_document(*single), *single)
        single_view = api.SourceContextView(single_syntax, decode(SourceRolesMaterial, single[3]), single_material)
        single_state = single_view.resolve(_slot(single_syntax, ('body', 1, 'annotation'), 'id')).state
        single_region = single_material.regions[single_state.region]
        assert single_region.eligibility == 'SUPPRESSED'
        assert single_region.suppression_reason == 'FUTURE_ANNOTATION_STRINGIZED'
        return
    else:
        answers = [(port, view.resolve(port.site)) for port in roles.ports]
        def no_new_view(*args, **kwargs):
            raise AssertionError('repeated queries must reuse the source context view')
        with monkeypatch.context() as patch:
            patch.setattr(api.SourceContextView, '__init__', no_new_view)
            for port, expected_answer in answers:
                assert view.resolve(port.site) == view.port_context(port) == expected_answer
            for boundary in material.boundaries:
                assert view.resolve(boundary.site).state == boundary.state
        # Count original slots independently; boundaries are only the sparse overlay.
        expected_counts = [[0] * 5 for _ in rules]
        by_key = {(row['constructor'], row['group'], row['ordinal']): row['rule'] for row in base_rules}
        for node in syntax.nodes:
            for group, values in (('FIELD', node.fields), ('ATTRIBUTE', node.attributes)):
                for ordinal, value in enumerate(values):
                    row = expected_counts[by_key[node.constructor, group, ordinal]]
                    state = 1 if value.kind == 'ABSENT' else 2 if value.kind == 'SCALAR' and value.scalar.to_python() is None else 3 if value.kind == 'LIST' and not value.items else 4
                    row[0] += 1; row[state] += 1
        assert material.slots == sum(len(node.fields) + len(node.attributes) for node in syntax.nodes)
        for actual, expected in zip(material.counts, expected_counts):
            assert [actual.slots, actual.absent, actual.none, actual.empty_list, actual.values] == expected
        assert len(material.boundaries) < material.slots
        assert sum(row.boundaries for row in material.counts) == len(material.boundaries)
        wire = json.dumps(document)
        assert all(text not in wire for text in ('_Inner__T', '_Outer__decor', 'local_annotation'))
        for limits in (dict(max_scopes=0), dict(max_regions=0), dict(max_boundaries=0), dict(max_slots=0)):
            stopped = api.source_contexts_document(*inputs, **limits)
            assert stopped['status'] == 'BUDGET_STOPPED' and stopped['root_context'] is None
            assert stopped['slots'] == 0 and stopped['boundaries'] == []
            assert api.read_source_contexts(stopped, *inputs).status == 'BUDGET_STOPPED'
        original_compile = builtins.compile
        def only_ast(source, filename, mode, flags=0, **kwargs):
            assert flags & ast.PyCF_ONLY_AST
            return original_compile(source, filename, mode, flags=flags, **kwargs)
        def forbidden(*args, **kwargs):
            raise AssertionError('C1 must not enter symbol-table analysis or runtime')
        import _symtable
        with monkeypatch.context() as patch:
            patch.setattr(builtins, 'compile', only_ast)
            patch.setattr(_symtable, 'symtable', forbidden)
            assert api.read_source_contexts(api.source_contexts_document(*inputs), *inputs) == material
            for mode, text in (('exec', 'x=1\n'), ('eval', 'value'), ('single', 'x=1\n'),
                               ('func_type', '(int) -> str'), ('exec', 'return value\n')):
                assert api.source_contexts_document(*_inputs(text, mode=mode))['status'] == 'CONTEXTUALIZED'
        for source, max_tokens in (('x = if :\n', 2_000_000), ('x=(\n', 2_000_000), ('x=1\n', 0)):
            upstream = _inputs(source, max_tokens=max_tokens)
            result = api.source_contexts_document(*upstream)
            assert result['status'] == 'UPSTREAM_NOT_CLASSIFIED'
            assert api.read_source_contexts(result, *upstream).slots == 0
        bounded = list(_inputs('x=1\n'))
        bounded[3] = source_roles_document(*bounded[:3], max_ports=0)
        assert api.source_contexts_document(*bounded)['status'] == 'UPSTREAM_NOT_CLASSIFIED'
        for route, replacement in (
            (('runtime_frames',), 'CAPTURED'), (('compiler_projection',), 'JOINED'),
            (('profile', 'context_catalog_sha256'), '0' * 64),
            (('root_context', 'environment'), True),
            (('boundaries', 0, 'state', 'environment'), 10**6),
            (('regions', 0, 'eligibility'), 'SUPPRESSED'),
            (('slots',), 0), (('extra',), [])):
            changed = deepcopy(document)
            target = changed
            for part in route[:-1]:
                target = target[part]
            target[route[-1]] = replacement
            with pytest.raises((TypeError, ValueError)):
                api.read_source_contexts(changed, *inputs)
