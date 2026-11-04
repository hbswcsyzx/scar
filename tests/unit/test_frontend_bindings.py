"""F3-D composed reference/endpoint queries over pure static compiler inputs."""
from copy import deepcopy
from dataclasses import replace
import ast
import sys

import pytest

from scar.analysis.source_bytes import source_bytes_document
from scar.analysis.source_tokens import source_tokens_document
from scar.analysis.source_syntax import source_syntax_document
from scar.analysis.source_roles import source_roles_document
from scar.analysis.source_contexts import source_contexts_document
from scar.analysis.source_declarations import source_declarations_document
from scar.analysis.source_bindings import source_bindings_document
from scar.analysis.source_symbols import source_symbols_document
from scar.analysis.compiler_topology import compiler_topology_document
from scar.analysis.compiler_symbols import compiler_symbols_document
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.program.source_roles import SourceRolesMaterial
from scar.ir.program.source_contexts import SourceContextsMaterial
from scar.ir.program.source_declarations import SourceDeclarationsMaterial
from scar.ir.program.source_bindings import SourceBindingsMaterial
from scar.ir.program.source_symbols import SourceSymbolsMaterial
from scar.ir.program.compiler_topology import CompilerTopologyMaterial
from scar.ir.program.compiler_symbols import CompilerSymbolsMaterial
from scar.ir.record_codec import decode

pytestmark = pytest.mark.skipif(
    sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 14, 7),
    reason='accepted source/compiler rules are pinned to CPython 3.14.7')


def _inputs(text, mode='exec'):
    f0 = source_bytes_document(text.encode(), path='/source/frontend.py', namespace_root='/source')
    f1 = source_tokens_document(f0)
    f2 = source_syntax_document(f0, f1, mode=mode)
    b = source_roles_document(f0, f1, f2)
    c = source_contexts_document(f0, f1, f2, b)
    d = source_declarations_document(f0, f1, f2, b, c)
    q = source_bindings_document(f0, f1, f2, b, c, d)
    a = source_symbols_document(f0, f1, f2)
    t = compiler_topology_document(f0, f1, f2, b, c, a)
    s = compiler_symbols_document(f0, f1, f2, b, c, d, a, t)
    docs = f0, f1, f2, b, c, d, q, a, t, s
    typed = tuple(decode(cls, doc) for cls, doc in zip((
        SourceRolesMaterial, SourceContextsMaterial, SourceDeclarationsMaterial, SourceBindingsMaterial,
        SourceSymbolsMaterial, CompilerTopologyMaterial, CompilerSymbolsMaterial), docs[3:]))
    return docs, typed, decode(SourceSyntaxMaterial, f2)


def _occurrence(syntax, path):
    current, occurrence = syntax.nodes[syntax.root], syntax.root
    for part in path:
        value = current.fields[getattr(ast, current.constructor)._fields.index(part)] if type(part) is str else current.items[part]
        if value.kind == 'NODE':
            occurrence, current = value.reference, syntax.nodes[value.reference]
        else:
            current = value
    return occurrence


def _source(declarations, name, *, scope=None, reason=None):
    rows = [(i, row) for i, row in enumerate(declarations.contributions)
            if declarations.names[row.name].value == name
            and (scope is None or row.source_scope == scope)
            and (reason is None or row.reason == reason)]
    assert len(rows) == 1, (name, scope, reason, rows)
    return rows[0]


def _comp(topology, occurrence):
    rows = [i for i, row in enumerate(topology.blocks)
            if row.origin.occurrence == occurrence and row.origin.role == 'COMPREHENSION']
    assert len(rows) == 1
    return rows[0]


@pytest.mark.parametrize('family', ('routes_and_protocols', 'boundaries_and_rejection'))
def test_frontend_bindings(family):
    from scar.analysis.frontend_bindings import FrontendBindingView, read_frontend_bindings

    if family == 'routes_and_protocols':
        docs, typed, syntax = _inputs('''def outer(DATA, *rest, key=1, **named_args):
    global exported
    shared = 0
    nested = [[token for token in row] for row in DATA]
    named = [(captured := element) for element in DATA]
    keep = [shared for shared in DATA]
    class Inner:
        field: shared
        def method(self): return super, __class__
    return nested
class Magic:
    first = [__class__ for first_item in DATA]
    second = [__class__ for second_item in DATA]
obj.shared
''')
        b, c, d, q, a, t, s = typed
        view = read_frontend_bindings(*docs)
        assert view.verify()['ports'] == len(b.ports)
        assert view.verify()['sources'] == len(d.contributions)
        # Every query starts at the exact original B ordinal/site, including
        # labels whose text happens to match a real compiler name.
        for p, original in enumerate(b.ports):
            path = view.port(p)
            declaration = d.ports[p].contribution
            assert (path.port, path.site, path.namespace) == (p, original.site, p)
            assert path.declaration == declaration
            assert (path.source_scope, path.region) == (d.ports[p].source_scope, d.ports[p].region)
            assert path.raw_events == (() if declaration is None else s.sources[declaration].contributions)
        attribute = _occurrence(syntax, ('body', 2, 'value'))
        label = next(i for i, port in enumerate(b.ports)
                     if port.site.occurrence == attribute and port.role == 'ATTRIBUTE_LABEL')
        label_path = view.port(label)
        assert label_path.compiler_state == 'NO_CONTRIBUTION' and not label_path.raw_events
        label_query = view.endpoints(label)
        assert label_query.complete and not label_query.endpoints
        assert [x.reason for x in label_query.boundaries] == ['NO_CONTRIBUTION']

        # Parameter ordinals come from the original compiler append order:
        # keyword-only parameters precede *args, unlike source signature order.
        for name, expected_ordinal in (('DATA', 0), ('key', 1), ('rest', 2), ('named_args', 3)):
            _, parameter_source = _source(d, name, reason='PARAMETER_BINDING_SYNTAX')
            query = view.endpoints(parameter_source.port)
            assert query.complete and len(query.endpoints) == 1
            endpoint = query.endpoints[0]
            assert endpoint.parameter_ordinal == expected_ordinal
            projection = view.parameter(endpoint.native_scope, endpoint.parameter_ordinal)
            assert projection in s.parameters and projection.slot == endpoint.slot
            assert (projection.native_scope, projection.ordinal) == (endpoint.native_scope, expected_ordinal)
            assert a.scopes[endpoint.native_scope].varnames[expected_ordinal] == name

        global_id, global_decl = _source(d, 'exported', reason='GLOBAL_DECLARATION_SYNTAX')
        global_query = view.endpoints(global_decl.port)
        assert global_query.complete and len(global_query.endpoints) == 2
        assert {x.raw_event for x in global_query.endpoints} == set(s.sources[global_id].contributions)
        assert any(x.native_scope == 0 for x in global_query.endpoints)
        assert all(x.parameter_ordinal is None for x in global_query.endpoints)
        walrus_id, walrus = _source(d, 'captured', reason='NAMED_EXPR_BINDING_SYNTAX')
        assert walrus.home != walrus.source_scope
        assert len(view.port(walrus.port).raw_events) == 3
        # A zero budget must summarize all three pending raw sources in one
        # frontier record instead of constructing one record per source.
        for budget in ({'max_steps': 0}, {'max_results': 0}):
            limited = view.endpoints(walrus.port, **budget)
            assert not limited.complete and limited.steps == 0 and not limited.endpoints
            assert len(limited.frontier) == 1
            frontier = limited.frontier[0]
            assert frontier.remaining == len(view.port(walrus.port).raw_events) == 3
            assert frontier.raw_event == view.port(walrus.port).raw_events[0]
            assert not frontier.transforms

        walrus_query = view.endpoints(walrus.port)
        assert walrus_query.complete and walrus_query.endpoints
        assert any(e.association for e in walrus_query.endpoints)
        assert any(not e.transforms for e in walrus_query.endpoints)

        inner = _comp(t, _occurrence(syntax, ('body', 0, 'body', 2, 'value', 'elt')))
        token_id, token = _source(d, 'token', scope=t.blocks[inner].source_scope, reason='BINDING_SYNTAX')
        token_query = view.endpoints(token.port)
        assert token_query.complete and token_query.endpoints
        assert any(len(e.transforms) == 2 for e in token_query.endpoints)
        assert all(not e.association for e in token_query.endpoints)
        assert all(e.parameter_ordinal is None for e in token_query.endpoints)
        for endpoint in token_query.endpoints:
            assert all(s.transforms[i].rule == 'COPY' for i in endpoint.transforms)
            proof = view.why(endpoint.native_scope, endpoint.ordinal)
            assert token_id in proof['source_contributions']
        keep = _comp(t, _occurrence(syntax, ('body', 0, 'body', 4, 'value')))
        _, shared = _source(d, 'shared', scope=t.blocks[keep].source_scope, reason='BINDING_SYNTAX')
        keep_query = view.endpoints(shared.port)
        assert keep_query.complete and keep_query.endpoints
        assert all(e.association and any(s.transforms[i].rule == 'KEEP_PARENT' for i in e.transforms)
                   for e in keep_query.endpoints)

        # A source slot deleted after projection still has a real COPY/KEEP
        # route. Treating DELETED as an early terminal would lose these edges.
        for child, expected_rule, association in ((0, 'COPY', False), (1, 'KEEP_PARENT', True)):
            comp = _comp(t, _occurrence(syntax, ('body', 1, 'body', child, 'value')))
            _, magic = _source(d, '__class__', scope=t.blocks[comp].source_scope, reason='REFERENCE_SYNTAX')
            query = view.endpoints(magic.port)
            assert query.complete and query.endpoints
            assert any(x.reason == 'DELETED' for x in query.boundaries)
            assert all(e.association == association for e in query.endpoints)
            assert any(any(s.transforms[i].rule == expected_rule for i in e.transforms) for e in query.endpoints)
        mapping = {'SUPER_CLASS_REQUIREMENT': 'SUPER_CLASS_USE',
                   'CLASS_ANNOTATION_PROTOCOL': 'CLASSDICT_USE',
                   'CONDITIONAL_ANNOTATION_REQUIREMENT': 'CONDITIONAL_ANNOTATION_USE'}
        for i, demand in enumerate(q.implicit):
            path = view.implicit(i)
            assert path.requirement == i and path.rule == demand.rule and path.outcome == 'MATCHED'
            assert s.contributions[path.raw_event].rule == mapping[demand.rule]
        assert any(p.requirement is None and p.outcome == 'COMPILER_ONLY_HEADER'
                   for p in view.compiler_only_implicit())
        return

    docs, typed, syntax = _inputs('''from __future__ import annotations
class Future:
    obj.attr: 1
    field: (lambda: super)
def function():
    local: MISSING
''')
    b, c, d, q, a, t, s = typed
    view = read_frontend_bindings(*docs)
    _, missing = _source(d, 'MISSING', reason='REFERENCE_SYNTAX')
    missing_query = view.endpoints(missing.port)
    assert missing_query.complete and not missing_query.endpoints
    assert [x.reason for x in missing_query.boundaries] == ['IGNORED_LOCAL_ANNOTATION']
    _, super_load = _source(d, 'super', reason='REFERENCE_SYNTAX')
    detached_query = view.endpoints(super_load.port)
    assert detached_query.complete and not detached_query.endpoints
    assert all(x.reason == 'DETACHED_TEMPLATE' for x in detached_query.boundaries)
    compiler_only = view.compiler_only_implicit()
    assert any(p.rule == 'COMPILER_ONLY_DETACHED_SUPER_USE' and p.outcome == 'DETACHED_COMPILER_PROTOCOL'
               and s.contributions[p.raw_event].rule == 'SUPER_CLASS_USE' for p in compiler_only)
    assert any(view.implicit(i).outcome == 'OMITTED_FUTURE_STRINGIZATION' for i in range(len(q.implicit)))

    # Budgets return explicit, non-complete frontiers instead of an empty
    # result that could be mistaken for no dependency.
    for kwargs in ({'max_steps': 0}, {'max_results': 0}):
        query = view.endpoints(super_load.port, **kwargs)
        assert not query.complete and len(query.frontier) == 1 and not query.endpoints
        assert query.frontier[0].remaining == len(view.port(super_load.port).raw_events)
    with pytest.raises(ValueError):
        view.endpoints(super_load.port, max_steps=True)
    with pytest.raises(ValueError):
        view.port(True)
    for frontier in view.endpoints(super_load.port, max_steps=0).frontier:
        assert frontier.raw_event in view.port(super_load.port).raw_events

    # Typed construction is not a certificate for changed source joins.
    bad_port = replace(q.ports[super_load.port], declref=(q.ports[super_load.port].declref + 1) % len(d.contributions))
    bad_q = replace(q, ports=tuple(bad_port if i == super_load.port else p for i, p in enumerate(q.ports)))
    with pytest.raises(ValueError):
        FrontendBindingView(b, c, d, bad_q, a, t, s).verify()
    bad_docs = deepcopy(docs)
    bad_docs[6]['input']['c2a_document_sha256'] = '0' * 64
    with pytest.raises(ValueError):
        read_frontend_bindings(*bad_docs)

    grammar_docs, grammar_typed, _ = _inputs('(T) -> R', mode='func_type')
    grammar = read_frontend_bindings(*grammar_docs)
    assert grammar.verify()['source_only']
    for p in range(len(grammar_typed[0].ports)):
        path = grammar.port(p)
        assert path.compiler_state == 'GRAMMAR_ONLY' and not path.raw_events
        result = grammar.endpoints(p)
        assert result.complete and not result.endpoints
        assert [x.reason for x in result.boundaries] == ['GRAMMAR_ONLY']
