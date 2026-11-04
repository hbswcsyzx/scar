"""C2a source declarations and symbol-visit keys; no runtime locations."""
import _symtable
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
from scar.analysis.source_contexts import source_contexts_document
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.program.source_roles import SourceRolesMaterial
from scar.ir.program.source_contexts import SourceContextsMaterial
from scar.ir.record_codec import decode


pytestmark = pytest.mark.skipif(
    sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 14, 7),
    reason='symbol-visit name projection is pinned to CPython 3.14.7')


def _inputs(text, *, mode='exec', max_tokens=2_000_000):
    f0 = source_bytes_document(text.encode(), path='/source/declarations.py', namespace_root='/source')
    f1 = source_tokens_document(f0, max_tokens=max_tokens)
    f2 = source_syntax_document(f0, f1, mode=mode)
    roles = source_roles_document(f0, f1, f2)
    return f0, f1, f2, roles, source_contexts_document(f0, f1, f2, roles)


def _occurrence(syntax, path):
    node, index = syntax.nodes[syntax.root], syntax.root
    for part in path:
        node = node.fields[getattr(ast, node.constructor)._fields.index(part)] if isinstance(part, str) else node.items[part]
        if node.kind == 'NODE':
            index = node.reference
            node = syntax.nodes[index]
    return index


def _site(syntax, path, field, item_path=()):
    from scar.ir.program.source_roles import SlotRef
    occurrence = _occurrence(syntax, path)
    cls = getattr(ast, syntax.nodes[occurrence].constructor)
    return SlotRef(occurrence, 'FIELD', cls._fields.index(field), item_path)


_LEXICAL_FIELDS = {
    ('FunctionDef', 'name'), ('AsyncFunctionDef', 'name'), ('ClassDef', 'name'),
    ('Name', 'id'), ('Global', 'names'), ('Nonlocal', 'names'),
    ('ExceptHandler', 'name'), ('arg', 'arg'), ('alias', 'name'), ('alias', 'asname'),
    ('MatchMapping', 'rest'), ('MatchStar', 'name'), ('MatchAs', 'name'),
    ('TypeVar', 'name'), ('ParamSpec', 'name'), ('TypeVarTuple', 'name'),
}


def _source():
    return '''import package.child
import other.child as renamed
from package import member
from package import member as chosen
from package import *
from . import relative
counter += step
del gone
simple: Type
(parenthesized): Type
assigned: Type = None
call = obj.attribute(keyword=argument, **options)
match subject:
    case {"key": found, **rest}: pass
    case [captured, *tail]: pass
    case _: pass
try:
    work()
except Error as caught:
    pass
def outer(items):
    shared = 0
    def inner(parameter):
        global shared_global, shared_global
        nonlocal shared, shared
        shared_global = parameter
        shared += 1
        values = [(saved := item) for item in items]
        local: (lambda: hidden_name)
        ignored: IgnoredName
        return values
    return inner
class C[__T: (__T, __U, __external), __U]:
    import __pkg.child
    import __simple as __alias
    from __module import __member as __local
    global __global
    __global = __value
    def __method(__argument): return __external, __dunder__
type Pack[*Ts, **P] = tuple[*Ts]
async def asynchronous(argument): return argument
forward: "Forward.Name"
'''


@pytest.mark.parametrize('family', ('coverage', 'matrix', 'codec_and_budgets'))
def test_c2a_source_declarations(family, monkeypatch):
    import scar.analysis.source_declarations as api
    from scar.analysis.source_context_view import SourceContextView

    inputs = _inputs(_source())
    syntax = decode(SourceSyntaxMaterial, inputs[2])
    roles = decode(SourceRolesMaterial, inputs[3])
    contexts = decode(SourceContextsMaterial, inputs[4])
    original_native = _symtable.symtable
    def forbidden(*args, **kwargs):
        raise AssertionError('C2a production must not invoke the compiler symbol solver')
    with monkeypatch.context() as patch:
        patch.setattr(_symtable, 'symtable', forbidden)
        document = api.source_declarations_document(*inputs)
        material = api.read_source_declarations(json.loads(json.dumps(document)), *inputs)
    assert material.status == 'DECLARED' and material.authority == 'SOURCE_NAME_DECLARATIONS'
    assert material.lookup_resolution == 'NOT_COMPUTED_IN_C2A'
    assert material.profile.projection_phase == 'SYMBOL_VISIT_PROJECTION'
    assert len(material.ports) == len(roles.ports)

    def at(path, field, *, role=None, item_path=()):
        site = _site(syntax, path, field, item_path)
        matches = [i for i, port in enumerate(roles.ports) if port.site == site and (role is None or port.role == role)]
        assert len(matches) == 1, (path, field, role, matches)
        disposition = material.ports[matches[0]]
        contribution = None if disposition.contribution is None else material.contributions[disposition.contribution]
        return disposition, contribution

    def named(path, field, value, **kwargs):
        disposition, contribution = at(path, field, **kwargs)
        assert disposition.name is not None and material.names[disposition.name].value == value
        return disposition, contribution

    if family == 'coverage':
        catalog = api.source_declaration_catalog()
        fields = {(row['constructor'], row['name']) for row in catalog['lexical_fields']}
        assert fields == _LEXICAL_FIELDS and len(catalog['lexical_fields']) == 16
        assert len({constructor for constructor, _ in fields}) == 15
        assert catalog['projection_phase'] == 'SYMBOL_VISIT_PROJECTION'
        assert set(catalog['visit_flags']) == {'USE', 'DEF_LOCAL', 'DEF_PARAM', 'DEF_TYPE_PARAM',
            'DEF_IMPORT', 'DEF_ANNOT', 'DEF_COMP_ITER', 'DEF_GLOBAL', 'DEF_NONLOCAL'}
        seen = {(syntax.nodes[port.site.occurrence].constructor,
                 getattr(ast, syntax.nodes[port.site.occurrence].constructor)._fields[port.site.ordinal])
                for port in roles.ports if port.site.group == 'FIELD'}
        assert _LEXICAL_FIELDS <= seen
        assert [row.port for row in material.ports] == list(range(len(roles.ports)))
        assert len({row.value for row in material.names}) == len(material.names)
        assert all(row.phase == 'SYMBOL_VISIT_PROJECTION' for row in material.names)
        view = SourceContextView(syntax, roles, contexts)
        for index, row in enumerate(material.ports):
            state = view.port_context(index).state
            assert row.source_scope == state.environment and row.region == state.region
            if row.contribution is not None:
                contribution = material.contributions[row.contribution]
                assert contribution.port == index and contribution.site == roles.ports[index].site
                assert contribution.name == row.name and contribution.source_scope == row.source_scope
                assert 0 <= contribution.home < len(contexts.scopes)
                assert set(contribution.visit_flags) <= set(catalog['visit_flags'])
        assert sorted(row.contribution for row in material.ports if row.contribution is not None) == list(range(len(material.contributions)))
        assert {row.name for row in material.ports if row.name is not None} == set(range(len(material.names)))
        homes = {row.scope: row for row in material.scopes}
        assert len(homes) == len(material.scopes)
        for index, contribution in enumerate(material.contributions):
            assert index in homes[contribution.home].contributions
            assert contribution.name in homes[contribution.home].names
        for value in ('*', 'None', 'Forward.Name', 'attribute', 'keyword'):
            assert value not in {name.value for name in material.names}
        return

    if family == 'matrix':
        for body, role, disposition in ((0, 'IMPORT_MODULE_SPEC', 'IMPORT_SPECIFICATION'),
                                        (2, 'IMPORT_MEMBER_SPEC', 'IMPORT_SPECIFICATION'),
                                        (4, 'IMPORT_WILDCARD_SPEC', 'WILDCARD_IMPORT')):
            row, contribution = at(('body', body, 'names', 0), 'name', role=role)
            assert row.disposition == disposition and row.name is None and contribution is None
        head, contribution = named(('body', 0, 'names', 0), 'name', 'package', role='IMPORT_BINDING_SYNTAX')
        assert head.projection.value_rule == 'IMPORT_HEAD' and set(contribution.visit_flags) == {'DEF_IMPORT'}
        for body, field, value in ((1, 'asname', 'renamed'), (2, 'name', 'member'), (3, 'asname', 'chosen')):
            _, contribution = named(('body', body, 'names', 0), field, value, role='IMPORT_BINDING_SYNTAX')
            assert 'DECLARE' in contribution.operations and set(contribution.visit_flags) == {'DEF_IMPORT'}
        star, _ = at(('body', 4, 'names', 0), 'name')
        assert star.port in next(row for row in material.scopes if row.scope == star.source_scope).wildcards
        _, augmented = named(('body', 6, 'target'), 'id', 'counter')
        assert 'USE_SYNTAX' in augmented.operations and set(augmented.visit_flags) == {'DEF_LOCAL'}
        _, deleted = named(('body', 7, 'targets', 0), 'id', 'gone')
        assert set(deleted.visit_flags) == {'DEF_LOCAL'} and 'DELETE_CANDIDATE' in deleted.operations
        for body, value in ((8, 'simple'), (10, 'assigned')):
            _, declaration = named(('body', body, 'target'), 'id', value)
            assert set(declaration.visit_flags) == {'DEF_LOCAL', 'DEF_ANNOT'}
        _, nonsimple = at(('body', 9, 'target'), 'id')
        assert nonsimple is None or ('DECLARE' not in nonsimple.operations and not nonsimple.visit_flags)
        for path, field, value in (
            (('body', 12, 'cases', 0, 'pattern'), 'rest', 'rest'),
            (('body', 12, 'cases', 0, 'pattern', 'patterns', 0), 'name', 'found'),
            (('body', 12, 'cases', 1, 'pattern', 'patterns', 0), 'name', 'captured'),
            (('body', 12, 'cases', 1, 'pattern', 'patterns', 1), 'name', 'tail')):
            _, contribution = named(path, field, value)
            assert set(contribution.visit_flags) == {'DEF_LOCAL'}
        wildcard, contribution = at(('body', 12, 'cases', 2, 'pattern'), 'name')
        assert wildcard.name is None and contribution is None
        _, caught = named(('body', 13, 'handlers', 0), 'name', 'caught')
        assert caught.cleanup_policy == 'CLEAR_ON_HANDLER_EXIT'
        outer, inner = ('body', 14), ('body', 14, 'body', 1)
        global_row, global_ = named((*inner, 'body', 0), 'names', 'shared_global', item_path=(0,))
        nonlocal_row, nonlocal_ = named((*inner, 'body', 1), 'names', 'shared', item_path=(0,))
        assert set(global_.visit_flags) == {'DEF_GLOBAL'} and set(nonlocal_.visit_flags) == {'DEF_NONLOCAL'}
        assert 'DECLARE' not in global_.operations and 'DECLARE' not in nonlocal_.operations
        assert global_.home == nonlocal_.home
        repeated_global, _ = named((*inner, 'body', 0), 'names', 'shared_global', item_path=(1,))
        repeated_nonlocal, _ = named((*inner, 'body', 1), 'names', 'shared', item_path=(1,))
        assert repeated_global.name == global_row.name and repeated_nonlocal.name == nonlocal_row.name
        directives = next(row for row in material.scopes if row.scope == global_.home).directives
        assert {global_row.contribution, nonlocal_row.contribution, repeated_global.contribution,
                repeated_nonlocal.contribution} <= set(directives)
        assert contexts.scopes[global_.home].owner.occurrence == _occurrence(syntax, inner)
        _, formal = named((*inner, 'args', 'args', 0), 'arg', 'parameter')
        assert set(formal.visit_flags) == {'DEF_PARAM'} and 'PARAMETER_INTERFACE' in formal.operations
        comp = (*inner, 'body', 4, 'value')
        _, iteration = named((*comp, 'generators', 0, 'target'), 'id', 'item')
        assert iteration.home == iteration.source_scope and set(iteration.visit_flags) == {'DEF_LOCAL', 'DEF_COMP_ITER'}
        _, saved = named((*comp, 'elt', 'target'), 'id', 'saved')
        assert contexts.scopes[saved.home].owner.occurrence == _occurrence(syntax, inner)
        assert contexts.scopes[saved.source_scope].owner.occurrence == _occurrence(syntax, comp)
        assert saved.home != saved.source_scope and set(saved.visit_flags) == {'DEF_LOCAL'}
        _, hidden = named((*inner, 'body', 5, 'annotation', 'body'), 'id', 'hidden_name')
        assert hidden.analysis_visibility == 'SYMBOL_VISIT' and set(hidden.visit_flags) == {'USE'}
        assert contexts.regions[hidden.region].eligibility == 'SUPPRESSED'
        _, ignored = named((*inner, 'body', 6, 'annotation'), 'id', 'IgnoredName')
        assert ignored.analysis_visibility == 'IGNORED_LOCAL_ANNOTATION' and not ignored.visit_flags
        klass = ('body', 15)
        first = (*klass, 'type_params', 0)
        for path, value in (((*first, 'bound', 'elts', 0), '_C__T'),
                            ((*first, 'bound', 'elts', 1), '__U'),
                            ((*first, 'bound', 'elts', 2), '__external')):
            row, contribution = named(path, 'id', value)
            assert row.projection.private_mode == 'SELECTIVE' and row.projection.prefix_count == 1
        row, contribution = named((*klass, 'type_params', 1), 'name', '_C__U')
        assert row.projection.prefix_count == 2 and set(contribution.visit_flags) == {'DEF_LOCAL', 'DEF_TYPE_PARAM'}
        for path, field, value, role in (
            ((*klass, 'body', 0, 'names', 0), 'name', '_C__pkg', 'IMPORT_BINDING_SYNTAX'),
            ((*klass, 'body', 1, 'names', 0), 'asname', '_C__alias', 'IMPORT_BINDING_SYNTAX'),
            ((*klass, 'body', 2, 'names', 0), 'asname', '_C__local', 'IMPORT_BINDING_SYNTAX'),
            ((*klass, 'body', 3), 'names', '_C__global', None),
            ((*klass, 'body', 5, 'args', 'args', 0), 'arg', '_C__argument', None),
            ((*klass, 'body', 5, 'body', 0, 'value', 'elts', 0), 'id', '_C__external', None),
            ((*klass, 'body', 5, 'body', 0, 'value', 'elts', 1), 'id', '__dunder__', None)):
            row, _ = named(path, field, value, role=role, item_path=(0,) if field == 'names' else ())
            assert row.projection.private_mode == 'ALL'
        # Independent native key oracle only; no scope flags become addresses.
        oracle = original_native('class C[__T:(__T,__U,__external),__U]: pass\n', '/oracle.py', 'exec')
        parameters = next(row for row in oracle.children if row.type == _symtable.TYPE_TYPE_PARAMETERS)
        bound = next(row for row in parameters.children if row.type == _symtable.TYPE_TYPE_VARIABLE)
        assert set(bound.symbols) == {'.format', '_C__T', '__U', '__external'}
        return

    for limits in (dict(max_names=0), dict(max_contributions=0)):
        stopped = api.source_declarations_document(*inputs, **limits)
        assert stopped['status'] == 'BUDGET_STOPPED' and stopped['names'] == [] and stopped['contributions'] == []
        assert api.read_source_declarations(stopped, *inputs).status == 'BUDGET_STOPPED'
    conflicting = _inputs('def invalid(parameter):\n    global parameter\n    return parameter\n')
    conflicts = api.source_declarations_document(*conflicting)
    assert conflicts['status'] == 'DECLARED' and conflicts['conflicts']
    bounded = api.source_declarations_document(*conflicting, max_conflicts=0)
    assert bounded['status'] == 'BUDGET_STOPPED' and bounded['conflicts'] == []
    assert api.read_source_declarations(bounded, *conflicting).status == 'BUDGET_STOPPED'
    original_compile = builtins.compile
    def only_ast(source, filename, mode, flags=0, **kwargs):
        assert flags & ast.PyCF_ONLY_AST
        return original_compile(source, filename, mode, flags=flags, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(_symtable, 'symtable', forbidden)
        patch.setattr(builtins, 'compile', only_ast)
        assert api.read_source_declarations(api.source_declarations_document(*inputs), *inputs) == material
    for source, max_tokens in (('x = if :\n', 2_000_000), ('x=1\n', 0)):
        upstream = _inputs(source, max_tokens=max_tokens)
        rejected = api.source_declarations_document(*upstream)
        assert rejected['status'] == 'UPSTREAM_NOT_CONTEXTUALIZED'
        assert api.read_source_declarations(rejected, *upstream).names == ()
    for route, replacement in (
        (('lookup_resolution',), 'RESOLVED'), (('names', 0, 'phase'), 'CODEGEN'),
        (('names', 0, 'value'), 'changed-name'),
        (('ports', 0, 'port'), True), (('ports', 0, 'source_scope'), 10**6),
        (('contributions', 0, 'home'), True), (('ports', 0, 'extra'), None),
        (('max_names',), False), (('extra',), [])):
        changed = deepcopy(document)
        target = changed
        for part in route[:-1]:
            target = target[part]
        target[route[-1]] = replacement
        with pytest.raises((TypeError, ValueError)):
            api.read_source_declarations(changed, *inputs)
