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
                           'ListComp', 'SetComp', 'DictComp'}
    selectors, seen = {}, set()
    for occurrence, node in enumerate(rules.source.context.syntax.nodes):
        if node.constructor not in implemented:
            continue
        with monkeypatch.context() as local:
            local.setattr(ast, 'parse', lambda *a, **kw: pytest.fail('source rule reparsed the program'))
            try:
                value = rules.build(occurrence, purpose(rules, occurrence))
                result = rules.verify(value)
            except SourceRuleError as error:
                assert node.constructor in ('ListComp', 'SetComp', 'DictComp') and error.code == 'ASYNC_COMPREHENSION_FRONTIER'
                continue
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
        rules.build(occurrences(rules, 'GeneratorExp')[0])
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
    with pytest.raises(SourceRuleError, match='ASYNC_COMPREHENSION_FRONTIER'):
        rules.build(async_comp)


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
