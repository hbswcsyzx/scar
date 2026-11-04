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
    text = '\n'.join((
        'from __future__ import annotations',
        'arithmetic = left() + right()', 'conditional = yes() if condition() else no()',
        'conjunction = first() and second() and third()', 'disjunction = first() or second() or third()',
        'chain = low() < middle() < high()', 'obj.attr = assigned', 'obj[index] = assigned',
        'del name, obj.attr, obj[index]', 'sliced = obj[start:stop:stride]', 'empty = obj[:]',
        'named = (saved := source)', 'attribute = obj.attr',
        *('binary = left ' + op + ' right' for op in ('+', '-', '*', '@', '/', '%', '**', '<<', '>>', '|', '^', '&', '//')),
        *('unary = ' + op + ' operand' for op in ('~', 'not ', '+', '-')),
        *('compare = left ' + op + ' right' for op in ('==', '!=', '<', '<=', '>', '>=', 'is', 'is not', 'in', 'not in')),
        'literal = 41',
        'plain_call = function(first(), second(), x=third(), y=fourth())',
        'single_star = function(*iterable(), x=one(), y=two(), **mapping(), z=three())',
        'single_star_only = function(*iterable())', 'mapping_only = function(**mapping())',
        'multi_star = function(prefix(), *left(), middle(), *right(), tail(), **mapping())',
        'mixed_order = function(x=keyword(), *iterable())',
        'large_positional = function(' + ','.join('value()' for _ in range(31)) + ', **mapping())',
        'large_keywords = function(**mapping(), ' + ','.join('key' + str(i) + '=value()' for i in range(16)) + ')',
        'unsupported = []',
        'list_display = [first(), *iterable(), last()]',
        'tuple_display = (first(), *iterable(), last())',
        'set_display = {first(), *iterable(), last()}',
        'dict_display = {key0(): value0(), **mapping(), key1(): value1()}',
        'none_key = {None: value0(), **mapping()}',
        '[target, *rest, obj.attr] = assigned',
        'target, (nested, *tail), obj[index] = assigned',
        'del [target, obj.attr, obj[index]]',
        'large_list = [' + ','.join('part'+str(i) for i in range(31)) + ']',
        'large_set = {' + ','.join('part'+str(i) for i in range(31)) + '}',
        'large_dict = {' + ','.join('key'+str(i)+':part'+str(i) for i in range(34)) + '}',
        'formatted = f"prefix {value()!r:{spec()}} suffix"',
        'single_formatted = f"{value()}"', 'empty_formatted = f""',
        'template = t"prefix {value()!r:{spec()}} suffix"',
        'adjacent_template = t"{left}{right}"', 'empty_template = t""',
        'large_formatted = f"' + ''.join('{part'+str(i)+'}' for i in range(31)) + '"',
        'pending_comp = [item for item in iterable]',
        'set_comp = {produce(item) for item in outer() if keep(item) if other(item)}',
        'dict_comp = {key(item): value(item) for item in outer() for nested in inner(item) if check(nested)}',
        'target_comp = [nested for (item, *rest) in outer() if allow(item) for nested in rest if nested]',
        'nested_comp = [[nested for nested in inner(item)] for item in outer()]',
        'shadow_comp = [shadow for shadow in shadow]',
        'async def pending_async_comp(source):\n    return [item async for item in source]',
        'pending_generator = (item for item in iterable)',
        'def yield_forms(source):\n    received = (yield first())\n    yield\n    yield received\n    yield (yield source)',
        'async def async_yield_forms(source):\n    received = (yield source)\n    yield',
        'lambda_yield = lambda: (yield)',
        'def yield_in_header(source):\n    def nested(default=(yield source)):\n        pass\n    return nested',
        'def suppressed_annotations(source: list[missing_annotation]) -> "Result":\n    return source',
        'def delegate_forms(source):\n    return (yield from produce(source))',
        'async def await_forms(source):\n    return await produce(source)',
        'async def await_nested(source):\n    return await (await source)',
        'async def await_comp(source):\n    return [await produce(item) for item in source]',
        'async_generator_expression = (await produce(item) for item in source)',
        'lambda_formals = lambda a,b=first(),/,c=second(),*rest,d,e=third(),**kw: (a,b,c,rest,d,e,kw)',
        'def closure_builder():\n    captured = seed\n    direct = lambda value=default(): (captured,value)\n    forwarded = lambda: (lambda: captured)\n    return direct,forwarded',
        'def late_cell():\n    callback = lambda: unbound\n    unbound = make()\n    return callback',
        'generator_clauses = (produce(item,nested) for (item,*rest) in outer() if keep(item) for nested in rest if nested)',
        'nested_generators = (((row,other) for other in inner(row)) for row in outer())',
        'async def async_comps(source):\n    aset = {produce(x) async for x in source if keep(x)}\n    amap = {key(y): value(y) for row in rows async for y in row if await keep(y)}\n    mixed = [y async for row in source for y in row if y]\n    return aset,amap,mixed',
        'async_seed = (x async for x in source)',
        'async_eager_inside = ([x async for x in source] for row in rows)',
        'sync_lazy_inside = ((x async for x in source) for row in rows)',
        'async def eager_seed_phase():\n    return (x for x in [y async for y in source])',
        'def directive_forms(value):\n    global global_state\n    local = 0\n    def nested():\n        nonlocal local\n        global global_state\n        global_state = local = value\n        del local\n        return\n    return nested',
        'def structured_statements(source, flag):\n    for item in source:\n        if flag:\n            continue\n            unreachable()\n        elif item:\n            break\n    else:\n        exhausted()\n    while flag:\n        for nested in source:\n            pass\n        else:\n            if flag:\n                continue\n            break\n        flag = update(flag)\n    else:\n        return\n    if flag:\n        return result()\n        unreachable()\n    else:\n        raise Error()',
        'async def structured_async(source):\n    async for item in source:\n        if item:\n            continue\n        break\n    else:\n        return\n    return item',
        'def cleanup_transfer(source):\n    for item in source:\n        try:\n            break\n        finally:\n            return item',
        *('augmented ' + op + '= right()' for op in ('+', '-', '*', '@', '/', '%', '**', '<<', '>>', '|', '^', '&', '//')),
        'receiver().member += right()', 'receiver()[index()] += right()',
        'receiver()[start():stop()] += right()', 'receiver()[1:2] += right()',
        'receiver()[start():stop():stride()] += right()',
        'module_annotation: Missing', 'annotated_value: Missing = initial()',
        'receiver().member: Missing', 'receiver()[start():stop(), index()]: Missing',
        'def local_annotations():\n    local_only: Missing\n    local_value: Missing = initial()\n    receiver().member: Missing\n    receiver()[start():stop():stride()]: Missing',
        'assert condition()', 'assert condition(), message()',
        'def raise_forms():\n    if condition():\n        raise\n    if condition():\n        raise error()\n    raise error() from cause()',
        'import package', 'import package.child', 'import package.child.deep as alias, other as renamed',
        'from package import first, second as two', 'from . import relative', 'from ...package import private as _alias',
        'from package import *',
        'def local_imports():\n    global global_imported\n    import package as global_imported\n    import package.inner as scoped\n    from package import first as local',
        'class ImportNames:\n    import __private as __bound\n    from package import __member\n    import package.__part.deep as __alias',
    )) + '\n'
    return _documents(text)


def _documents(text):
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
    return _rules(documents)


def _rules(documents):
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


def assigned_values(rules):
    values = {}
    for occurrence in occurrences(rules, 'Assign'):
        target = rules.source.roles.field(occurrence, 'targets').items[0].reference
        if rules.source.context.syntax.nodes[target].constructor == 'Name':
            name = rules.source.roles.field(target, 'id').scalar.to_python()
            values[name] = rules.source.roles.field(occurrence, 'value').reference
    return values


def purpose(rules, occurrence):
    kind = rules.source.context.syntax.nodes[occurrence].constructor
    if kind not in ('Name', 'Attribute', 'Subscript', 'List', 'Tuple'):
        return P.ProductionPurpose.VALUE
    context = rules.source.roles.context(occurrence)
    return {'Load': P.ProductionPurpose.VALUE, 'Store': P.ProductionPurpose.STORE,
            'Del': P.ProductionPurpose.DELETE}[context]


def test_all_local_families_and_selector_domains_without_reparsing(rules, monkeypatch):
    catalog = rules.catalog()
    implemented = {r['constructor'] for r in catalog['rules'] if r['status'] == 'LOCAL_RULE'}
    assert implemented == {'Constant', 'Name', 'BinOp', 'UnaryOp', 'Attribute', 'Subscript',
                           'Slice', 'NamedExpr', 'IfExp', 'BoolOp', 'Compare', 'Call',
                           'List', 'Tuple', 'Set', 'Dict', 'JoinedStr', 'FormattedValue', 'TemplateStr', 'Interpolation',
                           'ListComp', 'SetComp', 'DictComp', 'Yield', 'YieldFrom', 'Await', 'Lambda', 'GeneratorExp'}
    selectors, seen = {}, set()
    for occurrence, node in enumerate(rules.source.context.syntax.nodes):
        if node.constructor not in implemented:
            continue
        if rules.descriptor_owner(occurrence) is not None:
            continue
        with monkeypatch.context() as local:
            local.setattr(ast, 'parse', lambda *a, **kw: pytest.fail('source rule reparsed the program'))
            try:
                value = rules.build(occurrence, purpose(rules, occurrence))
                result = rules.verify(value)
            except SourceRuleError as error:
                if error.code == 'SUPPRESSED_SOURCE':
                    context = rules.source.context.entry_context(occurrence)
                    assert rules.source.context.material.regions[context.region].eligibility == 'SUPPRESSED'
                    continue
                raise
        assert result['local_schedule_verified'] and result['child_interfaces_assumed']
        assert not result['effects_proven'] and not result['canonical_graph_generated']
        assert {P.SlotRef(occurrence, 'FIELD', i) for i in range(len(node.fields))} <= {s.field for s in value.slots}
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
            if rules.descriptor_owner(occurrence) is not None:
                with pytest.raises(SourceRuleError, match='PARENT_OWNED_SOURCE'):
                    rules.build(occurrence, purpose(rules, occurrence))
                continue
            context = rules.source.context.entry_context(occurrence)
            if rules.source.context.material.regions[context.region].eligibility == 'SUPPRESSED':
                with pytest.raises(SourceRuleError, match='SUPPRESSED_SOURCE'):
                    rules.build(occurrence, purpose(rules, occurrence))
                continue
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
        rules.build(occurrences(rules, 'FunctionDef')[0])
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
    counts = captured['counts']
    assert counts['suppressed_source_occurrences'] > 0
    assert counts['expression_occurrences'] == sum(counts[k] for k in (
        'local_recipes', 'rule_frontiers', 'suppressed_source_occurrences', 'parent_owned_expressions'))
    assert fresh['counts']['local_recipes'] > 0 and fresh['counts']['rule_frontiers'] == 0
    assert fresh['whole_program_graph_complete'] is fresh['target_executed'] is False
    assert (model / 'manifest.json').read_bytes() == original
    from scar.analysis.source_expression_materials import collect_source_statements
    statements = collect_source_statements(model, tmp_path / 'statements')
    replayed = collect_source_statements(model, tmp_path / 'statement-fresh', materials=tmp_path / 'statements')
    assert statements['counts'] == replayed['counts']
    count = statements['counts']
    assert count['statement_occurrences'] == sum(count[k] for k in (
        'local_recipes', 'rule_frontiers', 'suppressed_source_occurrences', 'parent_owned_statements'))
    assert count['local_recipes'] > 0 and count['rule_frontiers'] > 0
    assert statements['schema'] == 'scar.source-statement-materials' and statements['domain'] == 'statements'
    with pytest.raises(ValueError, match='previous rule material'):
        collect_source_statements(model, tmp_path / 'wrong-domain', materials=store)
    descriptor = captured['units'][0]['artifact']
    path = store / descriptor['path']
    rows = [json.loads(line) for line in gzip.decompress(path.read_bytes()).splitlines()]
    not_scheduled = [r for r in rows if r['status'] == 'SOURCE_NOT_SCHEDULED']
    assert len(not_scheduled) == counts['suppressed_source_occurrences']
    assert all(r['suppression']['reason'] and 'plan' not in r and 'error' not in r for r in not_scheduled)
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


def test_call_schedules_preserve_argument_failures_and_parent_owned_descriptors(rules, documents):
    from scar.ir.program.structured import PythonProtocolKind as K
    syntax = rules.source.context.syntax
    cases = {}
    # Original source targets select specimens only; they are not lowering keys.
    for occurrence in occurrences(rules, 'Assign'):
        target = rules.source.roles.field(occurrence, 'targets').items[0].reference
        if syntax.nodes[target].constructor != 'Name':
            continue
        name = rules.source.roles.field(target, 'id').scalar.to_python()
        if name in {'plain_call', 'single_star', 'single_star_only', 'mapping_only', 'multi_star',
                    'mixed_order', 'large_positional', 'large_keywords'}:
            value = rules.source.roles.field(occurrence, 'value').reference
            cases[name] = rules.build(value)
    def protocols(value):
        return [s.instruction.protocol for s in owned(value)[1] if type(s.instruction) is P.ApplyPythonProtocol]
    assert protocols(cases['plain_call']) == []
    assert protocols(cases['single_star_only']) == [K.CALL_FUNCTION_EX]
    assert protocols(cases['single_star']) == [K.BUILD_MAP, K.DICT_MERGE, K.BUILD_MAP, K.DICT_MERGE, K.CALL_FUNCTION_EX]
    assert protocols(cases['mapping_only']) == [K.BUILD_CALL_POSITIONALS, K.BUILD_MAP, K.DICT_MERGE, K.CALL_FUNCTION_EX]
    assert protocols(cases['multi_star']) == [K.BUILD_CALL_POSITIONAL_LIST, K.EXTEND_CALL_POSITIONALS,
        K.APPEND_CALL_POSITIONAL, K.EXTEND_CALL_POSITIONALS, K.APPEND_CALL_POSITIONAL,
        K.CALL_POSITIONALS_TO_TUPLE, K.BUILD_MAP, K.DICT_MERGE, K.CALL_FUNCTION_EX]
    assert protocols(cases['large_positional']) == [K.BUILD_CALL_POSITIONAL_LIST,
        *([K.APPEND_CALL_POSITIONAL] * 31), K.CALL_POSITIONALS_TO_TUPLE, K.BUILD_MAP, K.DICT_MERGE, K.CALL_FUNCTION_EX]
    assert protocols(cases['large_keywords']) == [K.BUILD_CALL_POSITIONALS, K.BUILD_MAP, K.DICT_MERGE,
        K.BUILD_MAP, *([K.MAP_ADD] * 16), K.DICT_MERGE, K.CALL_FUNCTION_EX]
    value = cases['mixed_order']
    _, steps = owned(value)
    evaluated = [s.instruction.field for s in steps if type(s.instruction) is P.EvaluateChild]
    assert [field_name(rules, s) for s in evaluated] == ['func', 'value', 'value']
    # The star written after the keyword is evaluated first, as a positional.
    assert syntax.nodes[evaluated[1].occurrence].constructor == 'Starred'
    assert syntax.nodes[evaluated[2].occurrence].constructor == 'keyword'
    # Failed merges must precede later keyword groups and keep their current world.
    value = cases['single_star']
    _, steps = owned(value)
    merges = [s for s in steps if type(s.instruction) is P.ApplyPythonProtocol and s.instruction.protocol is K.DICT_MERGE]
    assert len(merges) == 2
    for first, second in zip(steps, steps[1:]):
        normal = next(c for c in first.completions if c.kind.value == 'FALLTHROUGH')
        if second.arguments:  # every boundary consumes the latest state, not a stale input
            assert second.arguments[-1] == P.ProductionResult(first.id, len(normal.types)-1)
    for occurrence in (*occurrences(rules, 'Starred'), *occurrences(rules, 'keyword')):
        owner = rules.descriptor_owner(occurrence)
        assert owner is not None and syntax.nodes[owner.occurrence].constructor in ('Call', 'List', 'Tuple', 'Set')


def test_call_packing_protocol_order_matches_static_cpython_compilation(rules, documents):
    """Independent compiler oracle; no code object is executed."""
    import dis
    from scar.analysis.source_bytes import decoded_source_bytes
    from scar.ir.program.structured import PythonProtocolKind as K
    code = compile(decoded_source_bytes(documents[0]), '<static-call-oracle>', 'exec')
    instructions = list(dis.get_instructions(code))
    opcodes = {K.BUILD_CALL_POSITIONAL_LIST:'BUILD_LIST', K.EXTEND_CALL_POSITIONALS:'LIST_EXTEND',
        K.APPEND_CALL_POSITIONAL:'LIST_APPEND', K.CALL_POSITIONALS_TO_TUPLE:'CALL_INTRINSIC_1',
        K.BUILD_MAP:'BUILD_MAP', K.MAP_ADD:'MAP_ADD', K.DICT_MERGE:'DICT_MERGE', K.CALL_FUNCTION_EX:'CALL_FUNCTION_EX'}
    checked = 0
    for occurrence in occurrences(rules, 'Call'):
        value = rules.build(occurrence)
        expected = [s.instruction.protocol for s in owned(value)[1] if type(s.instruction) is P.ApplyPythonProtocol]
        if K.CALL_FUNCTION_EX not in expected:
            continue
        row = rules.source.context.syntax.nodes[occurrence]
        schema = next(s for s in rules.source.context.syntax.profile.ast_schema if s.name == 'Call')
        attrs = dict(zip(schema.attributes, row.attributes))
        span = tuple(attrs[n].scalar.to_python() for n in ('lineno', 'end_lineno', 'col_offset', 'end_col_offset'))
        # MAP_ADD's missing location may inherit a child expression's position.
        # These controlled specimens have one outer packing call per line and
        # no nested packing calls: use the complete window, not source spans,
        # as the test oracle. The producer itself never joins by positions.
        end = next(i for i, op in enumerate(instructions) if op.opname == 'CALL_FUNCTION_EX' and tuple(op.positions) == span)
        start = next(i for i, op in enumerate(instructions) if op.positions.lineno == span[0])
        observed = [op.opname for op in instructions[start:end+1] if op.opname in set(opcodes.values())]
        # BUILD_CALL_POSITIONALS includes the empty-tuple constant pool case,
        # which is intentionally not a physical-allocation assertion.
        assert observed == [opcodes[p] for p in expected if p is not K.BUILD_CALL_POSITIONALS]
        checked += 1
    assert checked >= 6


def test_container_protocols_preserve_hash_update_and_target_order(rules):
    from scar.ir.program.structured import PythonProtocolKind as K
    values = assigned_values(rules)
    plans = {name:rules.build(values[name]) for name in ('dict_display', 'large_dict', 'list_display', 'tuple_display', 'set_display')}
    def protocols(plan):
        return [s.instruction.protocol for s in owned(plan)[1] if type(s.instruction) is P.ApplyPythonProtocol]
    assert protocols(plans['dict_display']) == [K.BUILD_MAP, K.DICT_UPDATE, K.BUILD_MAP, K.DICT_UPDATE]
    assert K.DICT_MERGE not in protocols(plans['dict_display'])
    assert protocols(plans['large_dict']) == [K.BUILD_MAP, *([K.MAP_ADD]*17), K.BUILD_MAP, *([K.MAP_ADD]*17), K.DICT_UPDATE]
    assert protocols(plans['list_display']) == [K.BUILD_DISPLAY_LIST, K.EXTEND_DISPLAY, K.APPEND_DISPLAY]
    assert protocols(plans['tuple_display']) == [K.BUILD_DISPLAY_LIST, K.EXTEND_DISPLAY, K.APPEND_DISPLAY, K.DISPLAY_LIST_TO_TUPLE]
    actions = [s.instruction.action for s in plans['set_display'].steps if type(s.instruction) is P.ApplyLanguageAction]
    assert actions == [P.LanguageActionKind.SET_UPDATE, P.LanguageActionKind.SET_INSERT]
    none_key = rules.build(values['none_key'])
    _, steps = owned(none_key)
    # Literal None is a real expression; an unpack hole is metadata, not an evaluated key.
    evaluated_keys = [s.instruction.field.item_path for s in steps if type(s.instruction) is P.EvaluateChild
                      and field_name(rules, s.instruction.field) == 'keys']
    assert evaluated_keys == [(0,)]
    for kind in ('List', 'Tuple'):
        for occurrence in occurrences(rules, kind):
            if purpose(rules, occurrence) is not P.ProductionPurpose.STORE:
                continue
            root, steps = owned(rules.build(occurrence, P.ProductionPurpose.STORE))
            assert type(steps[0].instruction) is P.ApplyPythonProtocol or steps[0].instruction.action is P.LanguageActionKind.UNPACK_EXTENDED
            stores = [s for s in steps if type(s.instruction) is P.EvaluateChild]
            assert all(s.instruction.purpose is P.ProductionPurpose.STORE for s in stores)
            assert all(s.arguments[0].step == steps[0].id for s in stores)


def test_formatted_strings_convert_before_spec_and_templates_capture_without_conversion(rules):
    from scar.ir.program.structured import PythonProtocolKind as K
    values = assigned_values(rules)
    template = rules.build(values['template'])
    _, template_steps = owned(template)
    evaluated = [s for s in template_steps if type(s.instruction) is P.EvaluateChild]
    assert [rules.source.context.syntax.nodes[rules.source.roles.locate(s.instruction.field)[1].reference].constructor
            for s in evaluated] == ['Constant', 'Constant', 'Interpolation']
    assert sum(s.instruction.value.to_python() == '' for s in rules.build(values['adjacent_template']).steps
               if type(s.instruction) is P.DefineLiteral) == 3
    for occurrence in (*occurrences(rules, 'FormattedValue'), *occurrences(rules, 'Interpolation')):
        plan = rules.build(occurrence)
        _, steps = owned(plan)
        converting = [i for i,s in enumerate(steps) if type(s.instruction) is P.ApplyPythonProtocol
                      and s.instruction.protocol is K.FSTRING_CONVERT]
        formatting = [s for s in steps if type(s.instruction) is P.ApplyPythonProtocol and s.instruction.protocol is K.FSTRING_FORMAT]
        is_template = rules.source.context.syntax.nodes[occurrence].constructor == 'Interpolation'
        if is_template:
            assert not converting and not formatting
            assert any(type(s.instruction) is P.ConstructValue and s.instruction.construction is P.ConstructionKind.INTERPOLATION for s in steps)
        else:
            assert len(formatting) == 1
            spec = [i for i,s in enumerate(steps) if type(s.instruction) is P.EvaluateChild and field_name(rules,s.instruction.field)=='format_spec']
            if converting and spec:
                assert converting[0] < spec[0]
    singleton = rules.build(values['single_formatted'])
    root, steps = owned(singleton)
    assert len(steps) == 2 and steps[-1].arguments[0] == P.ProductionResult(steps[0].id, 0)
    empty = rules.build(values['empty_template'])
    assert {s.instruction.value.to_python() for s in empty.steps if type(s.instruction) is P.DefineLiteral} == {'', ()}


def test_container_and_formatting_schedules_match_static_compiler_output(rules, documents):
    import dis
    from scar.analysis.source_bytes import decoded_source_bytes
    from scar.ir.program.structured import PythonProtocolKind as K
    code = compile(decoded_source_bytes(documents[0]), '<static-display-oracle>', 'exec')
    instructions = list(dis.get_instructions(code))
    values = assigned_values(rules)
    aliases = {K.BUILD_MAP:'BUILD_MAP', K.MAP_ADD:'MAP_ADD', K.DICT_UPDATE:'DICT_UPDATE',
        K.BUILD_DISPLAY_LIST:'BUILD_LIST', K.EXTEND_DISPLAY:'LIST_EXTEND', K.APPEND_DISPLAY:'LIST_APPEND',
        K.BUILD_SET_DISPLAY:'BUILD_SET', K.DISPLAY_LIST_TO_TUPLE:'CALL_INTRINSIC_1'}
    actions = {P.LanguageActionKind.SET_INSERT:'SET_ADD', P.LanguageActionKind.SET_UPDATE:'SET_UPDATE'}
    wanted = set(aliases.values()) | set(actions.values())
    for name in ('dict_display','large_dict','list_display','tuple_display','set_display','large_set','large_list'):
        occurrence = values[name]
        node = rules.source.context.syntax.nodes[occurrence]
        schema = next(c for c in rules.source.context.syntax.profile.ast_schema if c.name == node.constructor)
        line = node.attributes[schema.attributes.index('lineno')].scalar.to_python()
        observed = [op.opname for op in instructions if op.positions.lineno==line and op.opname in wanted]
        expected = []
        for step in owned(rules.build(occurrence))[1]:
            op = step.instruction
            if type(op) is P.ApplyPythonProtocol and op.protocol in aliases:
                expected.append(aliases[op.protocol])
            elif type(op) is P.ApplyLanguageAction and op.action in actions:
                expected.append(actions[op.action])
        assert observed == expected
    def line_ops(name, wanted):
        occurrence = values[name]
        node = rules.source.context.syntax.nodes[occurrence]
        schema = next(c for c in rules.source.context.syntax.profile.ast_schema if c.name == node.constructor)
        line = node.attributes[schema.attributes.index('lineno')].scalar.to_python()
        return [op.opname for op in instructions if op.positions.lineno == line and op.opname in wanted]
    assert line_ops('formatted', {'CONVERT_VALUE','FORMAT_SIMPLE','FORMAT_WITH_SPEC','BUILD_STRING'}) == [
        'CONVERT_VALUE','FORMAT_SIMPLE','FORMAT_WITH_SPEC','BUILD_STRING']
    assert line_ops('template', {'CONVERT_VALUE','FORMAT_SIMPLE','FORMAT_WITH_SPEC','BUILD_INTERPOLATION','BUILD_TEMPLATE'}) == [
        'FORMAT_SIMPLE','BUILD_INTERPOLATION','BUILD_TEMPLATE']
    assert line_ops('large_formatted', {'BUILD_LIST','LIST_APPEND'}) == ['BUILD_LIST', *(['LIST_APPEND']*31)]


def test_comprehensions_use_shared_loops_and_original_scopes(rules):
    from scar.ir.program.structured import PythonProtocolKind as K
    values = assigned_values(rules)
    for name in ('pending_comp','set_comp','dict_comp','target_comp','nested_comp','shadow_comp'):
        occurrence = values[name]
        plan = rules.build(occurrence)
        root, root_steps = owned(plan)
        scope = next(r for r in plan.regions if r.kind is P.ProductionRegionKind.COMPREHENSION)
        assert scope.context.environment != root.context.environment
        assert rules.source.context.material.scopes[scope.context.environment].parent == root.context.environment
        assert type(root_steps[0].instruction) is P.EvaluateChild
        assert field_name(rules, root_steps[0].instruction.field) == 'iter'
        assert rules.source.context.context_at_slot(root_steps[0].instruction.field).state.environment == root.context.environment
        clauses = rules.source.roles.field(occurrence, 'generators').items
        loops = [r for r in plan.regions if r.kind is P.ProductionRegionKind.LOOP]
        assert len(loops) == len(clauses)  # templates count syntax clauses, not runtime iterations
        for loop in loops:
            _, steps = owned(plan, loop.id)
            assert len(steps) == 1 and type(steps[0].instruction) is P.LoopControl
            control = steps[0].instruction
            assert type(control.condition) is P.IterationCondition and control.invariant_count == 2
            body, body_steps = owned(plan, control.body)
            assert body.parameters == (*loop.parameters, REF)  # transient item has no backedge
            assert len(loop.parameters) == 3 and loop.parameters[-1] == WORLD
            assert type(body_steps[0].instruction) is P.EvaluateChild and body_steps[0].instruction.purpose is P.ProductionPurpose.STORE
            assert body_steps[0].arguments[0] == P.ProductionParameter(body.id, 3)
            advance, adv_steps = owned(plan, control.condition.advance.region)
            assert adv_steps[0].instruction.protocol is K.COMPREHENSION_NEXT
            matcher, match_steps = owned(plan, control.condition.exhausted)
            assert match_steps[0].instruction.protocol is K.MATCH_STOP_ITERATION
            assert len(matcher.completions) == 1  # only advancement exhaustion is matched, not body errors
        produced = [s for s in plan.steps if type(s.instruction) is P.ApplyPythonProtocol and s.instruction.protocol is K.COMPREHENSION_ADD]
        assert len(produced) == 1
        if name == 'dict_comp':
            before = [s for s in plan.steps if s.region == produced[0].region and type(s.instruction) is P.EvaluateChild]
            assert [field_name(rules, s.instruction.field) for s in before[-2:]] == ['key','value']
    async_comp = next(i for i in occurrences(rules,'ListComp') if any(
        rules.source.roles.field(g.reference,'is_async').scalar.to_python() for g in rules.source.roles.field(i,'generators').items))
    rules.verify(rules.build(async_comp))


def test_comprehension_clause_and_update_counts_match_static_compilation(rules, documents):
    import dis
    from scar.analysis.source_bytes import decoded_source_bytes
    instructions = list(dis.get_instructions(compile(decoded_source_bytes(documents[0]), '<static-comp-oracle>', 'exec')))
    values = assigned_values(rules)
    for name, update in (('pending_comp','LIST_APPEND'),('set_comp','SET_ADD'),('dict_comp','MAP_ADD'),('target_comp','LIST_APPEND')):
        occurrence = values[name]
        node = rules.source.context.syntax.nodes[occurrence]
        schema = next(c for c in rules.source.context.syntax.profile.ast_schema if c.name == node.constructor)
        line = node.attributes[schema.attributes.index('lineno')].scalar.to_python()
        own = [op for op in instructions if op.positions.lineno == line]
        count = len(rules.source.roles.field(occurrence,'generators').items)
        assert sum(op.opname=='FOR_ITER' for op in own) == count
        assert sum(op.opname==update for op in own) == 1


@pytest.mark.parametrize('abi', tuple(ExceptionABI))
def test_yield_uses_original_owner_and_later_value_exception_and_world(rules, abi):
    from scar.ir.program.control import LanguageCompletionKind as C
    variant = SourceExpressionRules(rules.source, world=WORLD, exception_abi=abi)
    asynchronous, bare, header = 0, 0, 0
    for occurrence in occurrences(variant, 'Yield'):
        plan = variant.build(occurrence)
        result = variant.verify(plan)
        assert not result['driver_admission_proven'] and not result['resume_state_origin_proven']
        root, steps = owned(plan)
        suspension = next(s for s in steps if type(s.instruction) is P.SuspendExecution)
        owner = variant.source.context.entry_context(occurrence).owner
        syntax = variant.source.context.syntax
        is_async = syntax.nodes[owner.occurrence].constructor == 'AsyncFunctionDef'
        asynchronous += is_async
        assert suspension.instruction.suspension is (
            P.SuspensionKind.ASYNC_YIELD if is_async else P.SuspensionKind.YIELD)
        assert suspension.instruction.saved == ()
        for route in suspension.instruction.routes:
            resumed, body = owned(plan, route.region)
            expected = (REF, WORLD) if route.kind is C.FALLTHROUGH else variant.raised
            assert resumed.kind is P.ProductionRegionKind.RESUME and resumed.parameters == expected
            assert body[-1].instruction == P.TransferCompletion(route.kind)
            assert body[-1].arguments == tuple(P.ProductionParameter(resumed.id, i) for i in range(len(expected)))
        assert steps[-1].arguments == tuple(P.ProductionResult(suspension.id, i) for i in range(2))
        if variant.source.roles.field(occurrence, 'value').kind == 'SCALAR':
            bare += 1
            assert type(steps[0].instruction) is P.DefineLiteral and steps[0].instruction.value.to_python() is None
        else:
            assert type(steps[0].instruction) is P.EvaluateChild
        # Header yield belongs to the creator function, not the nested function.
        if syntax.nodes[owner.occurrence].constructor == 'FunctionDef' and (
                variant.source.roles.field(owner.occurrence, 'name').scalar.to_python() == 'yield_in_header'):
            header += 1
        bad = replace(steps[-1], arguments=(steps[-1].arguments[0], P.ProductionParameter(root.id, 0)))
        mutated = replace(plan, steps=tuple(bad if s.id == bad.id else s for s in plan.steps))
        with pytest.raises(SourceRuleError, match='SOURCE_RULE_MISMATCH'):
            variant.verify(mutated)
    assert asynchronous == 2 and bare == 3 and header == 1


def test_yield_boundaries_match_static_compiler_without_executing_code(rules, documents):
    import dis
    from types import CodeType
    from scar.analysis.source_bytes import decoded_source_bytes
    pending = [compile(decoded_source_bytes(documents[0]), '<static-yield-oracle>', 'exec')]
    actual, wrapped, selected = 0, 0, 0
    while pending:
        code = pending.pop()
        pending.extend(c for c in code.co_consts if type(c) is CodeType)
        if code.co_name not in ('yield_forms', 'async_yield_forms', 'yield_in_header', '<lambda>'):
            continue
        instructions = list(dis.get_instructions(code))
        if code.co_name == '<lambda>' and not any(i.opname == 'YIELD_VALUE' for i in instructions):
            continue
        selected += 1
        for ordinal, op in enumerate(instructions):
            if op.opname == 'YIELD_VALUE':
                actual += 1
                assert instructions[ordinal+1].opname == 'RESUME'
                if code.co_name == 'async_yield_forms':
                    assert instructions[ordinal-1].opname == 'CALL_INTRINSIC_1'
                    assert 'ASYNC_GEN_WRAP' in instructions[ordinal-1].argrepr
                    wrapped += 1
    assert selected == 4 and wrapped == 2
    assert actual == len(occurrences(rules, 'Yield')) == 9


@pytest.mark.parametrize('abi', tuple(ExceptionABI))
def test_delegation_keeps_send_and_post_driver_completion_paths_separate(rules, abi):
    from scar.analysis.source_productions import ProductionError
    from scar.ir.program.control import LanguageCompletionKind as C
    variant = SourceExpressionRules(rules.source, world=WORLD, exception_abi=abi)
    for constructor in ('Await', 'YieldFrom'):
        for occurrence in occurrences(variant, constructor):
            plan = variant.build(occurrence)
            checked = variant.verify(plan)
            assert not checked['native_delegation_expanded'] and not checked['driver_protocol_graph_generated']
            assert plan.schema_version == 8
            _, root_steps = owned(plan)
            acquire = next(s for s in root_steps if type(s.instruction) is P.ApplyDelegationProtocol)
            assert acquire.instruction.protocol is (P.DelegationProtocolKind.AWAITABLE_ITER if constructor == 'Await'
                else P.DelegationProtocolKind.YIELD_FROM_ITER)
            loop = next(r for r in plan.regions if r.kind is P.ProductionRegionKind.LOOP)
            loop_control = owned(plan, loop.id)[1][0].instruction
            assert type(loop_control.condition) is P.RepeatCondition and loop_control.invariant_count == 1
            assert not any(r.kind is P.ProductionRegionKind.LOOP_CONDITION for r in plan.regions)
            send = [s for s in plan.steps if type(s.instruction) is P.ApplyDelegationProtocol
                and s.instruction.protocol is P.DelegationProtocolKind.SEND]
            assert len(send) == 1  # one template, no protocol-iteration unroll
            _, body = owned(plan, send[0].region)
            branch = body[-1]
            assert branch.arguments == (P.ProductionResult(send[0].id, 0),)
            assert branch.instruction.on_true.arguments == tuple(P.ProductionResult(send[0].id, i) for i in (1, 2))
            suspension = next(s for s in plan.steps if type(s.instruction) is P.SuspendExecution)
            assert suspension.instruction.delegate == P.ProductionParameter(suspension.region, 0)
            assert suspension.instruction.suspension is (P.SuspensionKind.AWAIT if constructor == 'Await'
                else P.SuspensionKind.YIELD_FROM)
            handlers = [s.instruction for s in plan.steps if type(s.instruction) is P.HandleCompletions]
            assert len(handlers) == 1
            protected = owned(plan, handlers[0].protected.region)[1]
            assert suspension in protected and send[0] not in protected
            assert handlers[0].routes[0].kind is C.RAISE
            # Initial send is None; neither fictitious iterator-item state nor
            # an evaluation of literal True is introduced for loop control.
            literals = [s.instruction.value.to_python() for s in plan.steps if type(s.instruction) is P.DefineLiteral]
            assert literals == [None]
            altered = replace(acquire, instruction=replace(acquire.instruction, protocol=(
                P.DelegationProtocolKind.YIELD_FROM_ITER if constructor == 'Await' else P.DelegationProtocolKind.AWAITABLE_ITER)))
            with pytest.raises(SourceRuleError, match='SOURCE_RULE_MISMATCH'):
                variant.verify(replace(plan, steps=tuple(altered if s.id == acquire.id else s for s in plan.steps)))
            with pytest.raises(ProductionError, match='SUSPEND_INTERFACE'):
                variant.verify(replace(plan, steps=tuple(replace(s, instruction=replace(s.instruction, delegate=None))
                    if s.id == suspension.id else s for s in plan.steps)))


def test_delegation_source_rules_match_static_compiler_boundaries(rules, documents):
    import dis
    from types import CodeType
    from scar.analysis.source_bytes import decoded_source_bytes
    pending = [compile(decoded_source_bytes(documents[0]), '<static-delegation-oracle>', 'exec')]
    gets = {'GET_AWAITABLE': 0, 'GET_YIELD_FROM_ITER': 0}
    while pending:
        code = pending.pop()
        pending.extend(c for c in code.co_consts if type(c) is CodeType)
        instructions = list(dis.get_instructions(code))
        for ordinal, op in enumerate(instructions):
            if op.opname not in gets:
                continue
            gets[op.opname] += 1
            assert instructions[ordinal+1].opname == 'LOAD_CONST' and instructions[ordinal+1].argval is None
            assert instructions[ordinal+2].opname == 'SEND'
            assert any(i.opname == 'CLEANUP_THROW' for i in instructions[ordinal+2:])
    assert gets['GET_AWAITABLE'] == len(occurrences(rules, 'Await')) >= 5
    assert gets['GET_YIELD_FROM_ITER'] == len(occurrences(rules, 'YieldFrom')) == 1


@pytest.mark.parametrize('abi', tuple(ExceptionABI))
def test_lambda_creation_retains_cells_and_defers_admitted_body_parameters(rules, abi):
    from scar.analysis.source_productions import ProductionError
    from scar.ir.program.control import LanguageCompletionKind as C
    from scar.ir.program.structured import PythonProtocolKind as K
    variant = SourceExpressionRules(rules.source, world=WORLD, exception_abi=abi)
    forwarded = False
    for occurrence in occurrences(variant, 'Lambda'):
        plan = variant.build(occurrence)
        checked = variant.verify(plan)
        assert not checked['argument_admission_proven'] and not checked['closure_layout_proven']
        root, creation = owned(plan)
        declaration = next(s for s in creation if type(s.instruction) is P.DeferRegion)
        env = declaration.instruction.environment
        body, execution = owned(plan, declaration.instruction.body)
        assert declaration.arguments == () and body.kind is P.ProductionRegionKind.DEFERRED
        assert body.parameters == (REF, *(REF for _ in env.parameters), WORLD)
        assert execution[0].instruction == P.EnterDeferredBody(env)
        assert execution[-1].instruction == P.TransferCompletion(C.RETURN)
        assert not any(type(s.instruction) is P.ApplyRegion for s in creation)
        assert not any(type(s.instruction) is P.AccessBinding for s in creation)
        cells = [s.instruction.source.relay for s in creation if type(s.instruction) is P.ReferenceEnvironment
            and type(s.instruction.source) is P.ClosureEnvironment]
        assert tuple(cells) == env.captures
        source_parameters = variant.source.deferred.parameters(occurrence)
        assert env.parameters == source_parameters
        for p in source_parameters:
            assert variant.source.frontend.roles.ports[p.binding_port].site == p.source
        make = next(s for s in creation if type(s.instruction) is P.ApplyPythonProtocol
            and s.instruction.protocol is K.MAKE_LAMBDA_FUNCTION)
        assert make.arguments[0] == P.ProductionResult(declaration.id, 0)
        if env.captures:
            forwarded |= not variant.source.frontend.bindings.scopes[env.scope].captures
            # Re-signing both declarations cannot hide a deleted capture from
            # the independent original F3 forwarding/capture inventory.
            changed_env = replace(env, captures=())
            changed = replace(plan, steps=tuple(replace(s, instruction=replace(s.instruction, environment=changed_env))
                if type(s.instruction) in (P.DeferRegion, P.EnterDeferredBody) else s for s in plan.steps))
            with pytest.raises(ProductionError, match='SOURCE_DEFERRED'):
                variant.source.match(changed)
    assert forwarded
    specific = variant.build(assigned_values(variant)['lambda_formals'])
    root, creation = owned(specific)
    env = next(s.instruction.environment for s in creation if type(s.instruction) is P.DeferRegion)
    assert [p.kind for p in env.parameters] == [P.DeferredParameterKind.POSITIONAL_ONLY]*2 + [
        P.DeferredParameterKind.POSITIONAL_OR_KEYWORD, P.DeferredParameterKind.VAR_POSITIONAL,
        P.DeferredParameterKind.KEYWORD_ONLY, P.DeferredParameterKind.KEYWORD_ONLY, P.DeferredParameterKind.VAR_KEYWORD]
    assert [p.default_source is not None for p in env.parameters] == [False, True, True, False, False, True, False]
    initial_defaults = [p.default_source for p in env.parameters if p.default_source is not None]
    evaluated = [s.instruction.field for s in creation if type(s.instruction) is P.EvaluateChild]
    assert evaluated == initial_defaults
    assert len([s for s in creation if type(s.instruction) is P.EvaluateChild]) == 3


def test_generator_creation_keeps_eager_iterator_and_lazy_shared_body_separate(rules):
    from scar.ir.program.structured import PythonProtocolKind as K
    for occurrence in occurrences(rules, 'GeneratorExp'):
        env = rules.source.deferred.interface(occurrence, WORLD, ExceptionABI.EXCEPTION_WORLD)
        plan = rules.build(occurrence)
        rules.verify(plan)
        root, creation = owned(plan)
        declaration = next(s for s in creation if type(s.instruction) is P.DeferRegion)
        body, execution = owned(plan, declaration.instruction.body)
        assert body.parameters == (REF, REF, WORLD) and len(env.parameters) == 1
        assert env.parameters[0].kind is P.DeferredParameterKind.INITIAL_ITERATOR
        assert env.parameters[0].binding_port is None
        protocols = [s.instruction.protocol for s in creation if type(s.instruction) is P.ApplyPythonProtocol]
        clauses = rules.source.roles.field(occurrence, 'generators')
        first_async = rules.source.roles.field(clauses.items[0].reference, 'is_async').scalar.to_python()
        assert protocols == ([K.MAKE_GENEXPR_FUNCTION, K.CREATE_GENEXPR] if first_async else
            [K.MAKE_GENEXPR_FUNCTION, K.GET_ITERATOR, K.CREATE_GENEXPR])
        assert not any(type(s.instruction) is P.SuspendExecution for s in creation)
        assert type(execution[0].instruction) is P.EnterDeferredBody
        loops = [s.instruction for s in plan.steps if type(s.instruction) is P.LoopControl
            and type(s.instruction.condition) is P.IterationCondition]
        assert len(loops) == len(clauses.items)
        assert all(loop.invariant_count == 1 and loop.condition.world_parameter == 1 for loop in loops)
        yields = [s for s in plan.steps if type(s.instruction) is P.SuspendExecution and s.instruction.delegate is None]
        assert len(yields) == 1 and yields[0].instruction.suspension is (
            P.SuspensionKind.ASYNC_YIELD if env.kind is P.DeferredBodyKind.ASYNC_GENERATOR else P.SuspensionKind.YIELD)
        assert not any(type(s.instruction) is P.ApplyPythonProtocol and s.instruction.protocol is K.COMPREHENSION_ADD for s in plan.steps)


def test_deferred_source_parameter_order_is_not_native_frame_layout(rules):
    import dis
    from types import CodeType
    source = 'lambda a,b=first(),/,c=second(),*rest,d,e=third(),**kw: (a,b,c,rest,d,e,kw)'
    code = compile(source, '<static-lambda-oracle>', 'eval')
    instructions = list(dis.get_instructions(code))
    make = next(i for i, op in enumerate(instructions) if op.opname == 'MAKE_FUNCTION')
    assert sum(op.opname == 'CALL' for op in instructions[:make]) == 3
    native = next(c for c in code.co_consts if type(c) is CodeType)
    assert native.co_varnames == ('a','b','c','d','e','rest','kw')
    occurrence = assigned_values(rules)['lambda_formals']
    names = [rules.source.roles.locate(p.source)[1].scalar.to_python() for p in rules.source.deferred.parameters(occurrence)]
    assert names == ['a','b','c','rest','d','e','kw']


@pytest.mark.parametrize('abi', tuple(ExceptionABI))
def test_async_advancement_awaits_a_qualified_iterator_and_only_catches_its_exhaustion(rules, abi):
    variant = SourceExpressionRules(rules.source, world=WORLD, exception_abi=abi)
    checked = 0
    for kind in ('ListComp','SetComp','DictComp','GeneratorExp'):
        for occurrence in occurrences(variant, kind):
            clauses = variant.source.roles.field(occurrence, 'generators').items
            if not any(variant.source.roles.field(c.reference, 'is_async').scalar.to_python() for c in clauses):
                continue
            plan = variant.build(occurrence); variant.verify(plan)
            regions = {r.id:r for r in plan.regions}
            for step in plan.steps:
                if type(step.instruction) is not P.LoopControl or type(step.instruction.condition) is not P.IterationCondition:
                    continue
                control = step.instruction
                _, advancement = owned(plan, control.condition.advance.region)
                if not any(type(s.instruction) is P.ApplyDelegationProtocol and
                        s.instruction.protocol is P.DelegationProtocolKind.GET_ASYNC_NEXT for s in advancement):
                    continue
                checked += 1
                assert advancement[0].instruction.protocol is P.DelegationProtocolKind.GET_ASYNC_NEXT
                assert not any(type(s.instruction) is P.ApplyDelegationProtocol and
                    s.instruction.protocol is P.DelegationProtocolKind.AWAITABLE_ITER for s in advancement)
                _, matcher = owned(plan, control.condition.exhausted)
                assert matcher[0].instruction.protocol is P.DelegationProtocolKind.MATCH_STOP_ASYNC_ITERATION
                body = regions[control.body]
                assert body.parent == step.region and body.parameters == (*regions[step.region].parameters, REF)
                # Advance, including its shared await loop, is the protected
                # condition. Target/filter/body failures do not use its matcher.
                assert regions[control.condition.exhausted].parent == step.region
                assert body.id != control.condition.advance.region
    assert checked >= 6


def test_async_status_follows_eager_evaluation_but_not_lazy_generator_creation(rules):
    values = assigned_values(rules)
    def kind(occurrence):
        return rules.source.deferred.interface(occurrence, WORLD, ExceptionABI.EXCEPTION_WORLD).kind
    assert kind(values['async_eager_inside']) is P.DeferredBodyKind.ASYNC_GENERATOR
    assert kind(values['sync_lazy_inside']) is P.DeferredBodyKind.GENERATOR
    inner = rules.source.roles.field(values['sync_lazy_inside'], 'elt').reference
    assert kind(inner) is P.DeferredBodyKind.ASYNC_GENERATOR
    # The eager first iterable is evaluated by the creator, not by the lazy
    # body, so an async comprehension there does not change that body's kind.
    candidates = [i for i in occurrences(rules,'GeneratorExp')
        if rules.source.context.syntax.nodes[rules.source.roles.field(
            rules.source.roles.field(i,'generators').items[0].reference,'iter').reference].constructor == 'ListComp']
    assert len(candidates) == 1 and kind(candidates[0]) is P.DeferredBodyKind.GENERATOR


def test_async_loop_boundaries_match_static_cpython_without_running_target_code():
    import dis
    from types import CodeType
    samples = ('(x async for x in source)', '([x async for x in source] for y in outer)',
        '((x async for x in source) for y in outer)')
    flags = []
    for source in samples:
        code = compile(source, '<static-async-protocol-oracle>', 'eval')
        body = next(c for c in code.co_consts if type(c) is CodeType)
        flags.append(bool(body.co_flags & 0x200))
        pending = [body]
        while pending:
            current = pending.pop();pending.extend(c for c in current.co_consts if type(c) is CodeType)
            instructions = list(dis.get_instructions(current))
            for ordinal, op in enumerate(instructions):
                if op.opname == 'GET_ANEXT':
                    assert instructions[ordinal+1].opname == 'LOAD_CONST' and instructions[ordinal+1].argval is None
                    assert instructions[ordinal+2].opname == 'SEND'
                    assert any(i.opname == 'END_ASYNC_FOR' for i in instructions[ordinal+2:])
    assert flags == [True,True,False]


def test_structured_statement_rules_preserve_source_fields_and_completion_interfaces(rules, monkeypatch):
    from scar.analysis.source_statement_rules import SourceStatementRules
    statements = SourceStatementRules(rules.source, world=WORLD, exception_abi=ExceptionABI.EXCEPTION_WORLD)
    supported = {r['constructor'] for r in statements.catalog()['rules'] if r['status'] == 'LOCAL_STATEMENT_RULE'}
    assert supported == {'Expr','Pass','Assign','Delete','Return','Global','Nonlocal',
        'If','While','For','AsyncFor','Break','Continue','AnnAssign','AugAssign','Assert','Raise','Import','ImportFrom'}
    seen = set()
    for occurrence, node in enumerate(rules.source.context.syntax.nodes):
        if node.constructor not in supported:continue
        with monkeypatch.context() as current:
            current.setattr(ast,'parse',lambda *a,**kw:pytest.fail('statement rule reparsed target'))
            plan = statements.build(occurrence)
            result = statements.verify(plan)
        assert plan.purpose is P.ProductionPurpose.STATEMENT
        assert result['local_schedule_verified'] and not result['canonical_graph_generated']
        assert {P.SlotRef(occurrence,'FIELD',i) for i in range(len(node.fields))} <= {s.field for s in plan.slots}
        seen.add(node.constructor)
    assert seen == supported


def test_linear_statements_evaluate_rhs_once_order_writes_and_release_only_owned_temporaries(rules):
    from scar.analysis.source_statement_rules import SourceStatementRules
    from scar.ir.program.control import LanguageCompletionKind as C
    from scar.ir.program.structured import PythonProtocolKind as K
    statements = SourceStatementRules(rules.source, world=WORLD, exception_abi=ExceptionABI.EXCEPTION_WORLD)
    occurrence = next(i for i in occurrences(rules,'Assign') if len(rules.source.roles.field(i,'targets').items)==2)
    plan = statements.build(occurrence); root, steps = owned(plan)
    evaluated = [s for s in steps if type(s.instruction) is P.EvaluateChild]
    assert len(evaluated)==3 and [s.instruction.purpose for s in evaluated] == [
        P.ProductionPurpose.VALUE,P.ProductionPurpose.STORE,P.ProductionPurpose.STORE]
    assert evaluated[1].arguments[0] == evaluated[2].arguments[0] == P.ProductionResult(evaluated[0].id,0)
    assert evaluated[2].arguments[1] == P.ProductionResult(evaluated[1].id,0)
    assert steps[-2].instruction.protocol is K.FRAME_RELEASE_TEMPORARY
    assert steps[-2].arguments == (P.ProductionResult(evaluated[0].id,0),P.ProductionResult(evaluated[2].id,0))
    for kind in ('Global','Nonlocal'):
        _, directive = owned(statements.build(occurrences(rules,kind)[0]))
        assert len(directive)==1 and directive[0].instruction == P.TransferCompletion(C.FALLTHROUGH)
    for index in occurrences(rules,'Return'):
        root, returned = owned(statements.build(index))
        assert returned[-1].instruction == P.TransferCompletion(C.RETURN)
        assert not any(type(s.instruction) is P.ApplyPythonProtocol and s.instruction.protocol is K.FRAME_RELEASE_TEMPORARY for s in returned)


def test_statement_control_templates_preserve_source_targets_and_completion_boundaries(rules):
    from scar.analysis.source_statement_rules import SourceStatementRules
    from scar.analysis.source_productions import ProductionError
    from scar.ir.program.control import LanguageCompletionKind as C
    from scar.ir.program.structured import PythonProtocolKind as K
    for abi in ExceptionABI:
        statements = SourceStatementRules(rules.source, world=WORLD, exception_abi=abi)
        for kind in ('For', 'While', 'AsyncFor'):
            for occurrence in occurrences(rules, kind):
                plan = statements.build(occurrence)
                statements.verify(plan)
                loops = [s for s in plan.steps if type(s.instruction) is P.LoopControl and s.instruction.source_loop is not None]
                assert len(loops) == 1  # one source template, regardless of runtime iteration count
                control = loops[0].instruction
                assert control.source_loop == P.SourceLoopTarget(occurrence)
                region, _ = owned(plan, loops[0].region)
                body, body_steps = owned(plan, control.body)
                assert control.invariant_count == (0 if kind == 'While' else 1)
                assert region.parameters == ((WORLD,) if kind == 'While' else (REF, WORLD))
                assert body.parameters == (region.parameters if kind == 'While' else (*region.parameters, REF))
                assert not any(c.target == control.source_loop for c in region.completions)
                if kind != 'While':
                    assert type(control.condition) is P.IterationCondition
                    assert body_steps[0].instruction.purpose is P.ProductionPurpose.STORE
                    assert body_steps[0].arguments[0] == P.ProductionParameter(body.id, 2)
                if kind == 'AsyncFor':
                    assert any(type(s.instruction) is P.ApplyDelegationProtocol
                        and s.instruction.protocol is P.DelegationProtocolKind.GET_ASYNC_NEXT for s in plan.steps)
                    assert any(type(s.instruction) is P.SuspendExecution
                        and s.instruction.suspension is P.SuspensionKind.AWAIT for s in plan.steps)
                else:
                    assert sum(type(s.instruction) is P.LoopControl for s in plan.steps) == 1
        terminal = [statements.build(i) for i in occurrences(rules, 'If')]
        terminal = [p for p in terminal if not any(c.kind is C.FALLTHROUGH for c in owned(p)[0].completions)]
        assert terminal and any(s.disposition is P.ProductionDispositionKind.NO_NORMAL_PREDECESSOR
            for p in terminal for s in p.slots)
        assert any({c.kind for c in owned(p)[0].completions} == {C.RETURN, C.RAISE} for p in terminal)
    # The inner for's else has left that loop; its continue belongs to while.
    statements = SourceStatementRules(rules.source, world=WORLD, exception_abi=ExceptionABI.EXCEPTION_WORLD)
    continued = [(i, rules.source.statements.active_loop(P.ProductionOccurrence(i))) for i in occurrences(rules, 'Continue')]
    index, target = next((i, t) for i, t in continued if rules.source.context.syntax.nodes[t.occurrence].constructor == 'While')
    jump = statements.build(index)
    assert owned(jump)[1][-1].instruction == P.TransferCompletion(C.CONTINUE, target)
    different = next(i for i in occurrences(rules, 'For') if i != target.occurrence)
    step = jump.steps[-1]
    altered = replace(jump, regions=(replace(jump.regions[0], completions=(replace(step.completions[0], target=P.SourceLoopTarget(different)),)),),
        steps=(replace(step, instruction=P.TransferCompletion(C.CONTINUE, P.SourceLoopTarget(different)),
            completions=(replace(step.completions[0], target=P.SourceLoopTarget(different)),)),))
    with pytest.raises(ProductionError, match='SOURCE_LOOP'):
        rules.source.match(altered)
    # Finally-return replaces the protected break in the source interface;
    # this does not claim that the Try producer or cleanup implementation exists.
    tried = occurrences(rules, 'Try')[0]
    interface = rules.source.statements.completions(tried)
    assert {kind for kind, _ in interface} == {C.RETURN, C.RAISE}


def test_atomic_statement_addresses_world_and_terminal_completions(rules):
    from scar.analysis.source_statement_rules import SourceStatementRules
    from scar.ir.program.control import LanguageCompletionKind as C
    from scar.ir.program.structured import PythonProtocolKind as K
    operators = set()
    for abi in ExceptionABI:
        statements = SourceStatementRules(rules.source, world=WORLD, exception_abi=abi)
        for occurrence in occurrences(rules, 'AugAssign'):
            plan = statements.build(occurrence)
            statements.verify(plan)
            _, steps = owned(plan)
            inplace = next(s for s in steps if type(s.instruction) is P.ApplyInplaceOperator)
            selector = rules.source.roles.locate(inplace.instruction.operator)[1].reference
            operators.add(rules.source.context.syntax.nodes[selector].constructor)
            target = rules.source.roles.field(occurrence, 'target').reference
            assert rules.descriptor_owner(target) is not None
            with pytest.raises(SourceRuleError, match='PARENT_OWNED_SOURCE'):
                rules.build(target, P.ProductionPurpose.STORE)
            evaluations = [s for s in steps if type(s.instruction) is P.EvaluateChild]
            assert sum(s.instruction.field == P.SlotRef(occurrence, 'FIELD', rules.source.roles.fields['AugAssign']['value']) for s in evaluations)==1
            assert not any(s.instruction.field == P.SlotRef(occurrence, 'FIELD', rules.source.roles.fields['AugAssign']['target']) for s in evaluations)
            if rules.source.context.syntax.nodes[target].constructor == 'Name':
                accesses = [s for s in steps if type(s.instruction) is P.AccessBinding]
                assert [s.instruction.action for s in accesses] == [P.BindingActionKind.READ, P.BindingActionKind.WRITE]
                assert accesses[0].instruction.port == accesses[1].instruction.port
            else:
                receiver = P.SlotRef(target, 'FIELD', rules.source.roles.fields[rules.source.context.syntax.nodes[target].constructor]['value'])
                assert sum(s.instruction.field == receiver for s in evaluations)==1
            sliced = [s for s in steps if type(s.instruction) is P.ApplyPythonProtocol and s.instruction.protocol is K.STORE_SLICE]
            if sliced:
                assert sliced[0].arguments[0] == P.ProductionResult(inplace.id, 0)
        for occurrence in occurrences(rules, 'Raise'):
            plan = statements.build(occurrence)
            root, steps = owned(plan)
            assert {c.kind for c in root.completions} == {C.RAISE}
            evaluations = [s for s in steps if type(s.instruction) is P.EvaluateChild]
            assert [field_name(rules, s.instruction.field) for s in evaluations] in ([], ['exc'], ['exc','cause'])
            assert steps[-1].instruction == P.TransferCompletion(C.RAISE)
            assert steps[-1].completions[0].types == statements.raised
        for occurrence in occurrences(rules, 'Assert'):
            plan = statements.build(occurrence)
            root, steps = owned(plan)
            assert type(steps[0].instruction) is P.ReadCompilationOption
            enabled = next(s for s in steps if type(s.instruction) is P.BranchControl).instruction.on_true.region
            _, enabled_steps = owned(plan, enabled)
            truth = next(s for s in enabled_steps if type(s.instruction) is P.ApplyLanguageAction and s.instruction.action is P.LanguageActionKind.TRUTH)
            branch = next(s for s in enabled_steps if type(s.instruction) is P.BranchControl)
            assert branch.instruction.on_true.arguments == branch.instruction.on_false.arguments == (P.ProductionResult(truth.id, 1),)
            for step in plan.steps:
                if type(step.instruction) is P.EvaluateChild and field_name(rules, step.instruction.field)=='msg':
                    assert step.region == branch.instruction.on_false.region
    assert len(operators)==13


def test_annotation_phases_and_compilation_options_are_static_not_runtime_guesses(rules):
    import dis
    from scar.analysis.source_statement_rules import SourceStatementRules
    from scar.ir.program.structured import PythonProtocolKind as K
    for selected in (rules, _rules(_documents('module: Missing\nif condition:\n    conditional: Missing\nclass C:\n    plain: Missing\n    if condition:\n        conditional: Missing\n    with_value: Missing = initial()\n    def method(self):\n        local: Missing\n'))):
        statements = SourceStatementRules(selected.source, world=WORLD, exception_abi=ExceptionABI.EXCEPTION_WORLD)
        publications = []
        for occurrence in occurrences(selected, 'AnnAssign'):
            plan = statements.build(occurrence)
            statements.verify(plan)
            published = [s.instruction for s in plan.steps if type(s.instruction) is P.PublishAnnotation]
            publications.extend(published)
            assert not any(type(s.instruction) is P.EvaluateChild and field_name(selected,s.instruction.field)=='annotation' for s in plan.steps)
            if selected.source.roles.field(occurrence, 'value').kind != 'NODE':
                assert not any(type(s.instruction) is P.AccessBinding for s in plan.steps)
                assert not any(type(s.instruction) is P.ApplyLanguageAction and s.instruction.action in (
                    P.LanguageActionKind.ATTRIBUTE_GET,P.LanguageActionKind.ATTRIBUTE_SET,
                    P.LanguageActionKind.ITEM_GET,P.LanguageActionKind.ITEM_SET) for s in plan.steps)
                for step in plan.steps:
                    if type(step.instruction) is P.EvaluateChild:
                        child = selected.source.roles.locate(step.instruction.field)[1].reference
                        assert selected.source.context.syntax.nodes[child].constructor not in ('Slice','Tuple')
        assert publications
        if selected is rules:
            assert all(p.publication is P.AnnotationPublicationKind.STRINGIZED for p in publications)
        else:
            assert all(p.publication is P.AnnotationPublicationKind.DEFERRED for p in publications)
            choices = [(selected.source.roles.locate(p.name)[1].scalar.to_python(),p.conditional_registration) for p in publications]
            assert sorted(choices) == sorted([('module',True),('conditional',True),('plain',False),('conditional',True),('with_value',False)])
    # Compile-only oracle: optimization selects whether assert work exists;
    # analyzer flags must not silently decide the target's compilation option.
    for optimize in (0,1,2):
        code=compile('assert condition(), message()', '<static-assert-oracle>', 'exec', dont_inherit=True, optimize=optimize)
        instructions=list(dis.get_instructions(code))
        assert any(s.opname=='RAISE_VARARGS' for s in instructions) == (optimize==0)
        assert ('condition' in code.co_names) == (optimize==0)
    augmented=compile('receiver()[start():stop()] += right()', '<static-augmented-oracle>', 'exec', dont_inherit=True)
    instructions=list(dis.get_instructions(augmented))
    assert [s.argval for s in instructions if s.opname=='LOAD_NAME'] == ['receiver','start','stop','right']
    assert sum(s.opname=='BINARY_SLICE' for s in instructions)==1
    assert sum(s.opname=='STORE_SLICE' for s in instructions)==1


def test_import_source_paths_binding_projections_and_namespace_effects(rules):
    import dis
    from types import CodeType
    from scar.analysis.source_statement_rules import SourceStatementRules
    from scar.analysis.source_productions import ProductionError
    from scar.ir.program.control import LanguageCompletionKind as C
    observed=set()
    for abi in ExceptionABI:
        statements=SourceStatementRules(rules.source,world=WORLD,exception_abi=abi)
        for occurrence in (*occurrences(rules,'Import'),*occurrences(rules,'ImportFrom')):
            plan=statements.build(occurrence)
            checked=statements.verify(plan)
            assert not checked['importer_dispatch_proven'] and not checked['module_initialization_observed']
            root,steps=owned(plan)
            assert {c.kind for c in root.completions}=={C.FALLTHROUGH,C.RAISE}
            aliases=rules.source.statements.node_items(occurrence,'names')
            requests=[s for s in steps if type(s.instruction) is P.ImportRequest]
            bindings=[s for s in steps if type(s.instruction) is P.AccessBinding]
            kind=rules.source.context.syntax.nodes[occurrence].constructor
            assert len(requests)==(len(aliases) if kind=='Import' else 1)
            for alias in aliases:
                assert rules.descriptor_owner(alias)==rules.source.roles.parents[alias]
            if kind=='Import':
                assert all(s.instruction.from_names is None and s.instruction.fromlist is None
                    and s.instruction.relative_level==0 for s in requests)
                assert len(bindings)==len(aliases)
                for alias,request,binding in zip(aliases,requests,bindings):
                    raw=rules.source.roles.field(alias,'name').scalar.to_python()
                    renamed=rules.source.roles.field(alias,'asname').scalar.to_python() is not None
                    members=[s for s in steps if type(s.instruction) is P.ImportMember and s.source==P.ProductionOccurrence(alias)]
                    assert [s.instruction.component for s in members]==(list(range(1,len(raw.split('.')))) if renamed else [])
                    owner=P.ProductionResult(request.id,0)
                    for member in members:
                        assert member.arguments[0]==owner
                        assert member.instruction.member_name==raw.split('.')[member.instruction.component]
                        owner=P.ProductionResult(member.id,0)
                    assert binding.arguments[0]==owner
                    observed.add('dotted-as' if members else 'head')
                    if raw=='__private':
                        assert request.instruction.requested_name=='_ImportNames__private'
                        observed.add('private-request')
            else:
                request=requests[0]
                names=tuple(rules.source.roles.field(alias,'name').scalar.to_python() for alias in aliases)
                assert request.instruction.from_names==names
                assert request.instruction.relative_level==rules.source.roles.field(occurrence,'level').scalar.to_python()
                if request.instruction.relative_level:
                    observed.add('relative')
                stars=[s for s in steps if type(s.instruction) is P.ImportStar]
                members=[s for s in steps if type(s.instruction) is P.ImportMember]
                assert all(s.arguments[0]==P.ProductionResult(request.id,0) for s in (*members,*stars))
                if names==('*',):
                    assert len(stars)==1 and not bindings and not members
                    assert stars[0].instruction.environment==root.context.environment
                    observed.add('star')
                else:
                    assert len(members)==len(bindings)==len(aliases) and not stars
                    assert all(s.instruction.component is None for s in members)
                    for member,binding in zip(members,bindings):
                        assert binding.arguments[0]==P.ProductionResult(member.id,0)
                        if member.instruction.member_name=='_ImportNames__member':
                            name=rules.source.frontend.declarations.ports[binding.instruction.port].name
                            assert rules.source.frontend.declarations.names[name].value=='_ImportNames__member'
                            assert names==('__member',)  # from-list remains unmangled
                            observed.add('private-member')
            altered=replace(plan,steps=tuple(replace(s,instruction=replace(s.instruction,
                requested_name='wrong-source-name')) if s.id==requests[0].id else s for s in plan.steps))
            with pytest.raises(ProductionError,match='SOURCE_IMPORT'):
                rules.source.match(altered)
    assert observed=={'head','dotted-as','private-request','relative','star','private-member'}
    # Independent CPython compiler oracle; imported programs do not exist and
    # none of these code objects is executed.
    samples={'import a.b as c':[('IMPORT_NAME','a.b'),('IMPORT_FROM','b'),('STORE_NAME','c')],
        'import a.b':[('IMPORT_NAME','a.b'),('STORE_NAME','a')],
        'from ..a import x,y as z':[('IMPORT_NAME','a'),('IMPORT_FROM','x'),('STORE_NAME','x'),('IMPORT_FROM','y'),('STORE_NAME','z')]}
    for text,expected in samples.items():
        code=compile(text,'<static-import-oracle>','exec',dont_inherit=True)
        assert [(s.opname,s.argval) for s in dis.get_instructions(code) if s.opname in ('IMPORT_NAME','IMPORT_FROM','STORE_NAME')]==expected
    code=compile('class C:\n import __package as __name\n from a import __member\n import a.__part as __alias',
        '<static-import-private-oracle>','exec',dont_inherit=True)
    body=next(c for c in code.co_consts if type(c) is CodeType)
    assert [(s.opname,s.argval) for s in dis.get_instructions(body) if s.opname in ('IMPORT_NAME','IMPORT_FROM')]==[
        ('IMPORT_NAME','_C__package'),('IMPORT_NAME','a'),('IMPORT_FROM','_C__member'),('IMPORT_NAME','a.__part'),('IMPORT_FROM','__part')]
