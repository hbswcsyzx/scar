"""Strict storage for conditional configuration algebra and read dependencies."""
import ast
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis import normal_output, source_symbol_variants
from scar.analysis import source_configuration_overrides as parent
from scar.analysis import source_configuration_composition_store as composition
from scar.analysis import source_data_material_store as data_store
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir import record_codec as codec
from scar.ir.program import configuration_values as V, configuration_composition as C

_SCHEMA = 'scar.configuration-values'
_STATUS = 'CONDITIONAL_STATIC_INPUT_VALUE_GRAPH'
_SEMANTICS = 'CONDITIONAL_STATIC_INPUT_PROJECTIONS_NOT_CURRENT_TASK_CFG_OR_OBJECT_IDENTITY'
_TABLES = dict(expressions=V.ConfigurationExpression, roots=V.ConfigurationRoot,
    projections=V.ConfigurationProjection, interpolations=V.ConfigurationInterpolation,
    read_demands=V.ConfigurationReadDemand, obligations=V.ConfigurationValueObligation)
_HEADER = ('overrides', 'profiles', 'parser_tools', 'selected_root', 'conditions', 'semantics')
_FLAGS = ('target_executed', 'current_argv_proven', 'configuration_resolved', 'first_stage_complete')
_COUNTS = dict(expression_count='expressions', root_count='roots', projection_count='projections',
    interpolation_count='interpolations', read_demand_count='read_demands', obligation_count='obligations')


def _require(condition, message):
    if not condition: raise ValueError(message)


def pins():
    directory = Path(__file__).parent
    paths = dict(producer=directory/'source_configuration_values.py', store=Path(__file__),
        query=directory/'source_configuration_value_query.py', types=Path(V.__file__), codec=Path(codec.__file__),
        interpolation=directory/'source_interpolation_syntax.py', override_syntax=directory/'source_override_syntax.py',
        parent=Path(parent.__file__), composition=Path(composition.__file__), data_store=Path(data_store.__file__),
        table_writer=Path(normal_output.__file__), table_reader=Path(source_symbol_variants.__file__))
    return {name: sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}


def _validate(graph):
    _require(type(graph) is V.ConfigurationValues, 'typed configuration values required')
    graph = codec.decode(V.ConfigurationValues, codec.encode(graph))
    _require(graph.semantics == _SEMANTICS and graph.conditions, 'configuration value graph needs conditional semantics')
    receipts, payloads = {}, {}
    def artifact(value):
        if value.uri not in payloads: payloads[value.uri] = composition._artifact(value, receipts)
        _require(receipts[value.uri] == value, 'conflicting value-graph artifact receipts')
        return payloads[value.uri]
    _require(Path(graph.overrides.uri).name == 'result.json' and graph.overrides.schema == 'scar.configuration-overrides',
        'configuration values require an override graph manifest')
    raw = artifact(graph.overrides)
    report, overrides = parent.read_configuration_overrides(Path(graph.overrides.uri).parent)
    _require(json.loads(raw) == report and set(overrides.conditions) <= set(graph.conditions), 'override snapshot or conditions differ')
    base_path = Path(overrides.composition.uri).parent
    base = json.loads(artifact(overrides.composition))
    materials = {m.id: m for m in (codec.decode(C.ConfigurationMaterial, row)
        for row in source_symbol_variants._table(base_path, base['tables']['materials']))}
    steps = tuple(codec.decode(C.ConfigurationStep, row)
        for row in source_symbol_variants._table(base_path, base['tables']['steps']))
    limits = {key: json.loads(artifact(m.store))['tables']['references']['records'] for key, m in materials.items()}
    trees, functions = {}, set()
    _require(graph.profiles and graph.parser_tools, 'configuration value interpretation needs profiles and parser tools')
    for profile in graph.profiles:
        source = artifact(profile.source); key = profile.source.uri, profile.qualified_function
        _require(key not in functions, 'duplicate configuration value protocol function'); functions.add(key)
        if profile.source.uri not in trees: trees[profile.source.uri] = ast.parse(source)
        node = trees[profile.source.uri]
        for part in profile.qualified_function.split('.'):
            matches = [n for n in node.body if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == part]
            _require(part.isidentifier() and len(matches) == 1, 'qualified value protocol function differs'); node = matches[0]
        _require(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and
            sha256(ast.dump(node, include_attributes=False).encode()).hexdigest() == profile.function_ast_sha256,
            'configuration value protocol AST differs')
    for tool in graph.parser_tools: artifact(tool)
    def input_ref(source):
        _require(source.ordinal >= 0 and ((source.table == 'MATERIAL_REFERENCE' and source.owner in limits
            and source.ordinal < limits[source.owner]) or (source.table == 'OVERRIDE_EXPRESSION'
            and source.owner == graph.overrides.sha256 and source.ordinal < len(overrides.expressions))), 'input source is outside its parent table')
    expressions = graph.expressions; size = len(expressions); E = V.ConfigurationExpressionKind
    arities = {E.EMPTY: (0,), E.INPUT: (0,), E.OPEN_PROVIDER: (0,), E.EMBED: (1,),
        E.MERGE: (2,), E.ASSIGN: (2,), E.UPDATE: (2,), E.DELETE: (1, 2)}
    for i, expression in enumerate(expressions):
        _require(expression.ordinal == i and all(0 <= n < i for n in expression.inputs)
            and len(expression.inputs) in arities[expression.kind], 'expression ordinal, DAG inputs or arity differ')
        _require(expression.parent_stage in ('COMPOSITION', 'OVERRIDE') and (expression.parent_ordinal is None or
            0 <= expression.parent_ordinal < (len(steps) if expression.parent_stage == 'COMPOSITION' else len(overrides.overrides))),
            'expression lost its original parent stage or row')
        _require((expression.source is not None) == (expression.kind is E.INPUT), 'only INPUT expressions carry source references')
        expected_exclusions = ()
        if expression.source is not None:
            source = expression.source; input_ref(source)
            if source.table == 'MATERIAL_REFERENCE':
                _require(expression.parent_stage == 'COMPOSITION' and expression.parent_ordinal is not None,
                    'material input needs its original composition step')
                step = steps[expression.parent_ordinal]
                _require(step.material == source.owner, 'material input belongs to another composition step')
                if source.ordinal == materials[source.owner].root_reference: expected_exclusions = step.exclude_root_keys
            else: _require(expression.parent_stage == 'OVERRIDE', 'override input has another parent stage')
        _require(expression.exclude_root_keys == expected_exclusions, 'material root exclusions differ from original merge step')
    roots = {(root.stage, root.version): root.expression for root in graph.roots}
    expected = {('COMPOSITION', n) for n in range(len(steps))} | {('OVERRIDE', n) for n in range(overrides.root_version+1)}
    _require(len(roots) == len(graph.roots) and set(roots) == expected and all(0 <= n < size for n in roots.values()),
        'configuration root stages, versions or expressions differ')
    _require(roots['OVERRIDE', 0] == roots['COMPOSITION', overrides.composition_version]
        and graph.selected_root == roots['OVERRIDE', overrides.root_version], 'selected root is not the final override version')
    projections = graph.projections; count = len(projections)
    for i, projection in enumerate(projections):
        _require(projection.ordinal == i and 0 <= projection.root < size and all(0 <= n < count for n in projection.dependencies)
            and all(0 <= n < size for n in projection.evidence), 'projection references differ')
        _require(projection.literal is None or projection.kind is V.ConfigurationValueKind.SCALAR, 'non-scalar projection has a literal')
        _require((type(projection.members_complete) is bool) if projection.kind in (
            V.ConfigurationValueKind.MAPPING, V.ConfigurationValueKind.SEQUENCE) else projection.members_complete is None,
            'container membership completeness must be explicit')
        for source in projection.origins: input_ref(source)
    text_tables = {}
    def source_text(source):
        if source.table == 'OVERRIDE_EXPRESSION':
            literal = overrides.expressions[source.ordinal].literal
            return None if literal is None else literal.to_python()
        if source.owner not in text_tables:
            material = materials[source.owner]; folder = Path(material.store.uri).parent
            header = json.loads(payloads[material.store.uri])
            text_tables[source.owner] = tuple(source_symbol_variants._table(folder, header['tables'][name])
                for name in ('references', 'nodes'))
        references, nodes = text_tables[source.owner]
        return nodes[references[source.ordinal]['target']]['scalar_text']
    for i, interpolation in enumerate(graph.interpolations):
        _require(interpolation.ordinal == i and 0 <= interpolation.projection < count
            and all(0 <= n < count for n in interpolation.dependencies), 'interpolation projection references differ')
        _require(0 <= interpolation.character_start < interpolation.character_end
            and interpolation.character_end-interpolation.character_start == len(interpolation.syntax)
            and interpolation.phase == 'LAZY_SELECTED_ROOT', 'invalid lazy interpolation span or phase')
        texts = [source_text(source) for source in projections[interpolation.projection].origins]
        texts = [text for text in texts if type(text) is str]
        _require(not texts or any(interpolation.character_end <= len(text) and
            text[interpolation.character_start:interpolation.character_end] == interpolation.syntax for text in texts),
            'interpolation span differs from its original scalar text')
    for i, demand in enumerate(graph.read_demands):
        _require(demand.ordinal == i and 0 <= demand.operation < size and (demand.snapshot is None or 0 <= demand.snapshot < size)
            and (demand.projection is None or 0 <= demand.projection < count), 'intermediate read references differ')
        if demand.source is not None: input_ref(demand.source)
        operation = expressions[demand.operation]
        if demand.phase == 'UPDATE_INTERMEDIATE':
            _require(operation.kind in (E.UPDATE, E.ASSIGN, E.DELETE) and demand.snapshot == operation.inputs[0]
                and (demand.projection is None or (projections[demand.projection].root == demand.snapshot
                    and projections[demand.projection].path == demand.path and (demand.source is None or
                    demand.source in projections[demand.projection].origins))), 'UPDATE read snapshot or source differs')
        else:
            _require(demand.phase == 'MERGE_INTERNAL_STATE_PENDING' and operation.kind in (E.MERGE, E.UPDATE)
                and demand.snapshot is None and demand.projection is None, 'unresolved merge read fabricated a snapshot')
    for obligation in graph.obligations:
        _require(obligation.code and (obligation.expression is None or 0 <= obligation.expression < size)
            and (obligation.projection is None or 0 <= obligation.projection < count), 'value obligation references differ')
    return graph, receipts


def _current(receipts):
    for value in receipts.values():
        raw = Path(value.uri).read_bytes()
        _require(len(raw) == value.size_bytes and sha256(raw).hexdigest() == value.sha256, 'configuration value input changed')


def write_configuration_values(graph, out):
    out = Path(out).absolute(); _require(not out.exists(), 'fresh configuration value output required')
    initial = pins(); graph, receipts = _validate(graph); _durable_mkdir(out)
    tables = {name: normal_output.write_table(out/(name+'.jsonl.gz'), getattr(graph, name)) for name in _TABLES}
    counts = {name: len(getattr(graph, name)) for name in _TABLES}
    report = dict(schema=_SCHEMA, schema_version=1, status=_STATUS,
        **{name: codec.encode(getattr(graph, name)) for name in _HEADER}, tables=tables, counts=counts,
        **{name: counts[table] for name, table in _COUNTS.items()}, pins=initial,
        implementation_sha256=initial['producer'], types_sha256=initial['types'], store_sha256=initial['store'],
        **{name: False for name in _FLAGS})
    _current(receipts); _require(pins() == initial, 'configuration value producer changed')
    _durable_bytes(out/'result.json', _json(report), replace=False)
    return report


def read_configuration_values(path):
    path = Path(path).absolute(); raw = (path/'result.json').read_bytes(); report = json.loads(raw)
    expected = {'schema', 'schema_version', 'status', *_HEADER, 'tables', 'counts', *_COUNTS,
        'pins', 'implementation_sha256', 'types_sha256', 'store_sha256', *_FLAGS}
    _require(set(report) == expected and report['schema'] == _SCHEMA and type(report['schema_version']) is int
        and report['schema_version'] == 1 and report['status'] == _STATUS, 'expected conditional configuration value store')
    current = pins()
    _require(report['pins'] == current and all(report[key] == current[name] for key, name in (
        ('implementation_sha256', 'producer'), ('types_sha256', 'types'), ('store_sha256', 'store'))), 'configuration value producer pins differ')
    _require(all(report[name] is False for name in _FLAGS) and set(report['tables']) == set(_TABLES), 'value store has no runtime authority')
    document = {name: report[name] for name in _HEADER}
    for name, kind in _TABLES.items():
        receipt = report['tables'][name]; data_store._receipt(receipt, name+'.jsonl.gz', table=True)
        rows = source_symbol_variants._table(path, receipt)
        _require(len(rows) == receipt['records'], 'configuration value table count differs')
        document[name] = [codec.encode(codec.decode(kind, row)) for row in rows]
    graph, receipts = _validate(codec.decode(V.ConfigurationValues, document))
    counts = {name: len(getattr(graph, name)) for name in _TABLES}
    _require(report['counts'] == counts and all(type(n) is int for n in report['counts'].values())
        and all(type(report[name]) is int and report[name] == counts[table] for name, table in _COUNTS.items()), 'value counts differ')
    _current(receipts)
    _require((path/'result.json').read_bytes() == raw and pins() == current, 'configuration value manifest or producer changed')
    return report, graph
