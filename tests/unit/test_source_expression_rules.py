"""Static-only scheduling oracles: expressions below are parsed, never run."""
import ast
from dataclasses import replace
import sys

import pytest

from scar.analysis.source_expression_rules import SourceExpressionRules, SourceRuleError
from scar.analysis.source_productions import ProductionSourceIndex
from scar.ir.program import source_productions as P
from scar.ir.program.ids import LocationID
from scar.ir.program.model import ValueKind, ValueType
from scar.ir.program.protocol_signatures import ExceptionABI


pytestmark = pytest.mark.skipif(sys.version_info[:3] != (3, 14, 7), reason='pinned original frontend profile')
WORLD = ValueType(ValueKind.STATE, location=LocationID('test-source-world'))
REF = ValueType(ValueKind.REFERENCE)


@pytest.fixture(scope='module')
def documents():
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
    text = '\n'.join((
        'arithmetic = left() + right()', 'conditional = yes() if condition() else no()',
        'conjunction = first() and second() and third()', 'disjunction = first() or second() or third()',
        'chain = low() < middle() < high()', 'obj.attr = assigned', 'obj[index] = assigned',
        'del name, obj.attr, obj[index]', 'sliced = obj[start:stop:stride]', 'empty = obj[:]',
        'named = (saved := source)', 'attribute = obj.attr',
        *('binary = left ' + op + ' right' for op in ('+', '-', '*', '@', '/', '%', '**', '<<', '>>', '|', '^', '&', '//')),
        *('unary = ' + op + ' operand' for op in ('~', 'not ', '+', '-')),
        *('compare = left ' + op + ' right' for op in ('==', '!=', '<', '<=', '>', '>=', 'is', 'is not', 'in', 'not in')),
        'literal = 41',
    )) + '\n'
    f0 = source_bytes_document(text.encode(), path='/source/schedules.py', namespace_root='/source')
    f1 = source_tokens_document(f0)
    f2 = source_syntax_document(f0, f1)
    b = source_roles_document(f0, f1, f2)
    c = source_contexts_document(f0, f1, f2, b)
    d = source_declarations_document(f0, f1, f2, b, c)
    q = source_bindings_document(f0, f1, f2, b, c, d)
    a = source_symbols_document(f0, f1, f2)
    t = compiler_topology_document(f0, f1, f2, b, c, a)
    s = compiler_symbols_document(f0, f1, f2, b, c, d, a, t)
    return f0, f1, f2, b, c, d, q, a, t, s


@pytest.fixture(scope='module')
def rules(documents):
    from scar.analysis.frontend_bindings import read_frontend_bindings
    from scar.analysis.source_context_view import SourceContextView
    from scar.ir.program.source_syntax import SourceSyntaxMaterial
    from scar.ir.record_codec import decode
    f0, f1, f2, b, c, d, q, a, t, s = documents
    frontend = read_frontend_bindings(f0, f1, f2, b, c, d, q, a, t, s)
    context = SourceContextView(decode(SourceSyntaxMaterial, f2), frontend.roles, frontend.contexts)
    return SourceExpressionRules(ProductionSourceIndex(f0, context, frontend),
                                 world=WORLD, exception_abi=ExceptionABI.EXCEPTION_WORLD)


def occurrences(rules, kind):
    return [i for i, n in enumerate(rules.source.context.syntax.nodes) if n.constructor == kind]


def owned(plan, identity=None):
    region = next(r for r in plan.regions if r.id == (plan.root if identity is None else identity))
    steps = {s.id: s for s in plan.steps}
    return region, [steps[s] for s in region.steps]


def field_name(rules, site):
    return rules.source.roles.locate(site)[0].name


def purpose(rules, occurrence):
    kind = rules.source.context.syntax.nodes[occurrence].constructor
    if kind not in ('Name', 'Attribute', 'Subscript'):
        return P.ProductionPurpose.VALUE
    context = rules.source.roles.context(occurrence)
    return {'Load': P.ProductionPurpose.VALUE, 'Store': P.ProductionPurpose.STORE,
            'Del': P.ProductionPurpose.DELETE}[context]


def test_all_local_families_and_selector_domains_without_reparsing(rules, monkeypatch):
    monkeypatch.setattr(ast, 'parse', lambda *a, **kw: pytest.fail('source rule reparsed the program'))
    catalog = rules.catalog()
    implemented = {r['constructor'] for r in catalog['rules'] if r['status'] == 'LOCAL_RULE'}
    assert implemented == {'Constant', 'Name', 'BinOp', 'UnaryOp', 'Attribute', 'Subscript',
                           'Slice', 'NamedExpr', 'IfExp', 'BoolOp', 'Compare'}
    selectors, seen = {}, set()
    for occurrence, node in enumerate(rules.source.context.syntax.nodes):
        if node.constructor not in implemented:
            continue
        value = rules.build(occurrence, purpose(rules, occurrence))
        result = rules.verify(value)
        assert result['local_schedule_verified'] and result['child_interfaces_assumed']
        assert not result['effects_proven'] and not result['canonical_graph_generated']
        assert len(value.slots) == len(node.fields)
        seen.add(node.constructor)
        for step in value.steps:
            if type(step.instruction) is P.ApplyLanguageAction:
                for site in step.instruction.selectors:
                    if field_name(rules, site) in ('op', 'ops'):
                        selected = rules.source.roles.locate(site)[1]
                        selectors.setdefault(node.constructor, set()).add(
                            rules.source.context.syntax.nodes[selected.reference].constructor)
    assert seen == implemented
    assert len(selectors['BinOp']) == 13 and len(selectors['UnaryOp']) == 4 and len(selectors['Compare']) == 10
    assert 'BoolOp' not in selectors  # boolean selectors choose control paths, not rich-comparison actions


def test_arithmetic_order_and_state_mutations_require_source_replay(rules):
    value = rules.build(occurrences(rules, 'BinOp')[0])
    root, steps = owned(value)
    left, right, binary, finish = steps
    assert [field_name(rules, s.instruction.field) for s in (left, right)] == ['left', 'right']
    assert right.arguments == (P.ProductionResult(left.id, 1),)
    assert binary.arguments == (P.ProductionResult(left.id, 0), P.ProductionResult(right.id, 0), P.ProductionResult(right.id, 1))
    assert len(root.completions) == 2  # early failure survives the final normal transfer
    for corrupted in (
        replace(left, instruction=P.EvaluateChild(right.instruction.field, P.ProductionPurpose.VALUE)),
        replace(right, arguments=(P.ProductionParameter(root.id, 0),)),
    ):
        changed = replace(value, steps=tuple(corrupted if s.id == corrupted.id else s for s in value.steps))
        rules.source.match(changed)  # original refs/types alone cannot prove evaluation order
        with pytest.raises(SourceRuleError, match='SOURCE_RULE_MISMATCH'):
            rules.verify(changed)


def test_short_circuit_and_conditional_keep_subgraphs_and_original_value_identity(rules):
    for occurrence in occurrences(rules, 'BoolOp'):
        value = rules.build(occurrence)
        root, steps = owned(value)
        evaluate, truth, branch = steps
        assert type(evaluate.instruction) is P.EvaluateChild and evaluate.instruction.field.item_path == (0,)
        assert truth.instruction.action is P.LanguageActionKind.TRUTH
        assert len(value.regions) == 5  # 3 source operands, no runtime-iteration expansion
        operator = rules.source.roles.field(occurrence, 'op')
        selector = rules.source.context.syntax.nodes[operator.reference].constructor
        short = branch.instruction.on_false if selector == 'And' else branch.instruction.on_true
        follow = branch.instruction.on_true if selector == 'And' else branch.instruction.on_false
        assert short.arguments == (P.ProductionResult(evaluate.id, 0), P.ProductionResult(truth.id, 1))
        assert follow.arguments == (P.ProductionResult(truth.id, 1),)
        returned, body = owned(value, short.region)
        assert body[0].arguments[0] == P.ProductionParameter(returned.id, 0)
        assert returned.parameters[0] == REF
    value = rules.build(occurrences(rules, 'IfExp')[0])
    _, steps = owned(value)
    assert [field_name(rules, s.instruction.field) for s in steps if type(s.instruction) is P.EvaluateChild] == ['test']
    branch = steps[-1].instruction
    for call, name in ((branch.on_true, 'body'), (branch.on_false, 'orelse')):
        _, body = owned(value, call.region)
        assert field_name(rules, body[0].instruction.field) == name


def test_comparison_carries_middle_operand_once_and_returns_rich_result(rules):
    occurrence = next(i for i in occurrences(rules, 'Compare')
        if len(rules.source.roles.field(i, 'ops').items) == 2)
    value = rules.build(occurrence)
    _, steps = owned(value)
    left, middle, compare, truth, branch = steps
    assert compare.instruction.action is P.LanguageActionKind.COMPARE
    assert branch.instruction.on_true.arguments == (P.ProductionResult(middle.id, 0), P.ProductionResult(truth.id, 1))
    assert branch.instruction.on_false.arguments == (P.ProductionResult(compare.id, 0), P.ProductionResult(truth.id, 1))
    continued, body = owned(value, branch.instruction.on_true.region)
    assert body[1].arguments[0] == P.ProductionParameter(continued.id, 0)
    evaluations = [s for s in value.steps if type(s.instruction) is P.EvaluateChild]
    assert len(evaluations) == 3
    assert len({s.instruction.field for s in evaluations}) == 3


def test_targets_slice_holes_frontiers_and_budgets(rules):
    for kind in ('Name', 'Attribute', 'Subscript'):
        for occurrence in occurrences(rules, kind):
            selected = purpose(rules, occurrence)
            value = rules.build(occurrence, selected)
            root, steps = owned(value)
            expected = (REF, WORLD) if selected is P.ProductionPurpose.STORE else (WORLD,)
            assert root.parameters == expected
            if selected is P.ProductionPurpose.STORE:
                action = next(s for s in steps if type(s.instruction) in (P.AccessBinding, P.ApplyLanguageAction))
                assert P.ProductionParameter(root.id, 0) in action.arguments
    holes = next(i for i in occurrences(rules, 'Slice') if all(
        rules.source.roles.field(i, n).kind == 'SCALAR' for n in ('lower', 'upper', 'step')))
    _, steps = owned(rules.build(holes))
    assert not any(type(s.instruction) is P.EvaluateChild for s in steps)
    assert len(steps[0].instruction.payload) == 3  # None positions retained, no guessed arity
    with pytest.raises(SourceRuleError, match='RULE_FRONTIER'):
        rules.build(occurrences(rules, 'Call')[0])
    with pytest.raises(SourceRuleError, match='BUDGET_FRONTIER'):
        rules.build(occurrences(rules, 'BinOp')[0], max_steps=1)
    with pytest.raises(SourceRuleError, match='BUDGET_FRONTIER'):
        rules.build(occurrences(rules, 'IfExp')[0], max_regions=1)


def test_streamed_store_replays_source_even_if_tampered_receipts_are_resigned(documents, tmp_path):
    import gzip
    from hashlib import sha256
    import json
    from scar.analysis.source_anchor_materials import _write
    from scar.analysis.source_bytes import decoded_source_bytes
    from scar.analysis.source_expression_materials import collect_source_expressions
    model = tmp_path / 'model'
    model.mkdir()
    f0 = documents[0]
    text = decoded_source_bytes(f0)
    source = dict(schema='scar.static-source-text', schema_version=1, path=f0['path'],
        namespace_root=f0['namespace_root'], raw_sha256=f0['raw']['sha256'],
        decoded_sha256=sha256(text.encode()).hexdigest(), encoding='utf-8', text=text)
    names = ('source_bytes', 'source_tokens', 'source_syntax', 'source_roles', 'source_contexts',
             'source_declarations', 'source_bindings', 'source_symbols', 'compiler_topology', 'compiler_symbols')
    artifacts = {name: _write(model, name + '.json.gz', doc)
        for name, doc in dict(source=source, **dict(zip(names, documents))).items()}
    unit = dict(key='fixture', path=f0['path'], namespace_root=f0['namespace_root'],
        raw_sha256=source['raw_sha256'], decoded_sha256=source['decoded_sha256'],
        encoding='utf-8', source_bytes=len(text.encode()), artifacts=artifacts)
    original = json.dumps(dict(schema='scar.static-program', schema_version=1, units=[unit])).encode()
    (model / 'manifest.json').write_bytes(original)
    store = tmp_path / 'store'
    captured = collect_source_expressions(model, store)
    fresh = collect_source_expressions(model, tmp_path / 'fresh', materials=store)
    assert captured['counts'] == fresh['counts']
    assert fresh['counts']['local_recipes'] > 0 and fresh['counts']['rule_frontiers'] > 0
    assert fresh['whole_program_graph_complete'] is fresh['target_executed'] is False
    assert (model / 'manifest.json').read_bytes() == original
    descriptor = captured['units'][0]['artifact']
    path = store / descriptor['path']
    rows = [json.loads(line) for line in gzip.decompress(path.read_bytes()).splitlines()]
    binary = next(r['plan'] for r in rows if r['constructor'] == 'BinOp' and 'plan' in r)
    binary['steps'][0]['instruction']['field'] = binary['steps'][1]['instruction']['field']
    raw = b''.join(json.dumps(r, sort_keys=True, separators=(',', ':')).encode() + b'\n' for r in rows)
    payload = gzip.compress(raw, mtime=0)
    path.write_bytes(payload)
    descriptor.update(bytes=len(payload), sha256=sha256(payload).hexdigest(),
        decoded_bytes=len(raw), decoded_sha256=sha256(raw).hexdigest())
    (store / 'result.json').write_text(json.dumps(captured))
    with pytest.raises(ValueError, match='fresh original F2/F3 replay'):
        collect_source_expressions(model, tmp_path / 'reject', materials=store)
