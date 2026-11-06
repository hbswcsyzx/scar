"""Strict storage for conditional ordered configuration operations."""
import ast
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis import normal_output, source_symbol_variants
from scar.analysis import source_configuration_request_store as requests_store
from scar.analysis import source_data_material_store as data_store
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir import record_codec as codec
from scar.ir.program import configuration_composition as C


_SCHEMA = 'scar.configuration-composition'
_STATUS = 'CONDITIONAL_ORDERED_COMPOSITION_GRAPH'
_SEMANTICS = 'CONDITIONAL_ORDERED_COMPOSITION_NOT_RESOLVED_CFG_OR_RUNTIME_VALUE'
_TABLES = dict(materials=C.ConfigurationMaterial, dependencies=C.ConfigurationDependency,
    steps=C.ConfigurationStep, obligations=C.ConfigurationCompositionObligation)
_HEADER = ('request', 'source_candidate', 'file_root', 'main_resource', 'profiles',
    'root_version', 'conditions', 'semantics')
_FLAGS = ('target_executed', 'current_argv_proven', 'configuration_resolved', 'first_stage_complete')
_COUNTS = dict(material_count='materials', dependency_count='dependencies',
    step_count='steps', obligation_count='obligations')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def pins():
    paths = dict(producer=Path(__file__).with_name('source_configuration_composition.py'),
        store=Path(__file__), types=Path(C.__file__), codec=Path(codec.__file__),
        requests_store=Path(requests_store.__file__), data_store=Path(data_store.__file__),
        table_writer=Path(normal_output.__file__), table_reader=Path(source_symbol_variants.__file__))
    return {name: sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}


def _artifact(artifact, receipts):
    artifact.__post_init__()
    path = Path(artifact.uri)
    _require(path.is_absolute(), 'composition artifact requires an absolute filesystem locator')
    old = receipts.get(artifact.uri)
    _require(old is None or old == artifact, 'conflicting composition artifact receipts')
    raw = path.read_bytes()
    _require(len(raw) == artifact.size_bytes and sha256(raw).hexdigest() == artifact.sha256,
        'composition artifact receipt differs: '+artifact.uri)
    receipts[artifact.uri] = artifact
    return raw


def _parents_current(receipts, request_path, request_raw):
    _require((request_path/'result.json').read_bytes() == request_raw,
        'configuration request manifest changed')
    for artifact in receipts.values():
        raw = Path(artifact.uri).read_bytes()
        _require(len(raw) == artifact.size_bytes and sha256(raw).hexdigest() == artifact.sha256,
            'composition parent changed: '+artifact.uri)


def _validate(graph, requests_path):
    _require(type(graph) is C.ConfigurationComposition, 'typed configuration composition required')
    graph = codec.decode(C.ConfigurationComposition, codec.encode(graph))
    _require(graph.semantics == _SEMANTICS and graph.conditions,
        'configuration composition requires conditional representation semantics')
    requests_path = Path(requests_path).absolute()
    request_raw = (requests_path/'result.json').read_bytes()
    _, requests = requests_store.read_configuration_requests(requests_path)
    selected = [r for r in requests if r.id == graph.request]
    _require(len(selected) == 1, 'composition has no unique original configuration request')
    request = selected[0]
    _require(0 <= graph.source_candidate < len(request.sources), 'configuration source candidate is outside request')
    candidate = request.sources[graph.source_candidate]
    _require(candidate.protocol == 'FILE' and candidate.root is not None and candidate.resource is not None
        and (graph.file_root, graph.main_resource) == (candidate.root, candidate.resource),
        'composition changed its selected file-root or resource candidate')
    root, resource = Path(graph.file_root), Path(graph.main_resource)
    _require(root.is_absolute() and resource.is_absolute() and resource.is_relative_to(root),
        'configuration resource must belong to its absolute file-root candidate')
    _require(set((*request.conditions, *candidate.conditions)) <= set(graph.conditions),
        'composition lost its request or source-selection conditions')
    receipts, trees = {}, {}
    _require(graph.profiles, 'composition needs versioned protocol source functions')
    functions = set()
    for profile in graph.profiles:
        raw = _artifact(profile.source, receipts)
        key = profile.source.uri, profile.qualified_function
        _require(key not in functions, 'duplicate composition protocol function')
        functions.add(key)
        if profile.source.uri not in trees:
            trees[profile.source.uri] = ast.parse(raw)
        owner = trees[profile.source.uri]
        names = profile.qualified_function.split('.')
        _require(all(name.isidentifier() for name in names), 'protocol needs a source-qualified function')
        for name in names:
            matches = [node for node in owner.body if isinstance(node,
                (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
            _require(len(matches) == 1, 'qualified protocol function is absent or ambiguous')
            owner = matches[0]
        _require(isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)) and
            sha256(ast.dump(owner, include_attributes=False).encode()).hexdigest() == profile.function_ast_sha256,
            'configuration protocol function AST receipt differs')
    materials, data = {}, {}
    for material in graph.materials:
        _require(material.id and material.id not in materials, 'composition material identities differ')
        _require(Path(material.store.uri).name == 'result.json' and material.store.schema == 'scar.source-data-material',
            'configuration material requires a data-material manifest receipt')
        raw = _artifact(material.store, receipts)
        store = data_store.DataMaterialStore(Path(material.store.uri).parent)
        _require(store.manifest_raw == raw, 'material manifest changed before typed admission')
        value = store.read()
        _require(value.source == material.source and value.root == material.root_reference,
            'configuration material source or root differs from its typed store')
        materials[material.id], data[material.id] = material, value
    _require(any(m.source.uri == graph.main_resource for m in graph.materials),
        'composition omitted its selected primary source material')
    dependencies = graph.dependencies
    _require(all(d.ordinal == i for i, d in enumerate(dependencies)), 'dependency ordinals differ')
    instances, declared = {}, {}

    def bind(instance, material):
        _require(bool(instance), 'configuration instance identity is empty')
        old = instances.setdefault(instance, material)
        _require(old == material, 'configuration instance has conflicting source materials')

    for dependency in dependencies:
        _require(dependency.material in materials, 'dependency source material is absent')
        bind(dependency.instance, dependency.material)
        _require(dependency.reference is None or
            0 <= dependency.reference < len(data[dependency.material].references),
            'dependency syntax reference is outside its material')
        if dependency.child_instance is not None:
            _require(bool(dependency.child_instance), 'empty child instance declaration')
            declared.setdefault(dependency.child_instance, set()).add(dependency.ordinal)
    steps = graph.steps
    _require(steps and graph.root_version == len(steps)-1
        and all(s.ordinal == i for i, s in enumerate(steps)), 'composition root version or step ordinals differ')
    covered = set()
    for step in steps:
        _require(step.previous == (None if step.ordinal == 0 else step.ordinal-1), 'composition version chain differs')
        _require(all(step.package) and len(set(step.exclude_root_keys)) == len(step.exclude_root_keys),
            'invalid composition package or exclusion fields')
        if step.ordinal == 0:
            _require(step.kind is C.ConfigurationStepKind.EMPTY and all(value is None for value in (
                step.instance, step.dependency, step.material, step.root_reference))
                and not step.package and not step.exclude_root_keys, 'first composition version must be EMPTY')
            continue
        _require(step.kind is not C.ConfigurationStepKind.EMPTY, 'only initial composition version may be EMPTY')
        dependency = None
        if step.dependency is not None:
            _require(0 <= step.dependency < len(dependencies), 'step dependency is outside catalog')
            dependency = dependencies[step.dependency]
            _require(step.instance in (dependency.instance, dependency.child_instance),
                'step instance is unrelated to its dependency declaration')
        if step.instance is not None:
            _require(bool(step.instance), 'empty step instance')
            covered.add(step.instance)
        if step.kind is C.ConfigurationStepKind.MERGE_MATERIAL:
            _require(step.material in materials and step.instance is not None and dependency is not None,
                'merge requires its material, instance and SELF declaration')
            _require(dependency.kind is C.ConfigurationDependencyKind.SELF
                and dependency.instance == step.instance and dependency.material == step.material,
                'merge is not attached to the same instance SELF dependency')
            _require(step.root_reference == materials[step.material].root_reference
                and 'defaults' in step.exclude_root_keys, 'merge root or defaults exclusion differs')
            bind(step.instance, step.material)
        else:
            _require(step.kind is C.ConfigurationStepKind.OPEN_PROVIDER and step.material is None
                and step.root_reference is None and not step.exclude_root_keys,
                'open provider must not fabricate a material payload')
    obligations = set()
    for obligation in graph.obligations:
        _require(bool(obligation.code), 'composition obligation needs a code')
        _require(obligation.material is None or obligation.material in materials, 'obligation material is absent')
        if obligation.dependency is not None:
            _require(0 <= obligation.dependency < len(dependencies), 'obligation dependency is outside catalog')
            obligations.add(obligation.dependency)
    roots = set(instances)-set(declared)
    _require(len(roots) == 1 and materials[instances[next(iter(roots))]].source.uri == graph.main_resource,
        'configuration instances need one primary root and declared child instances')
    _require(all(step.instance is None or step.instance in roots or step.instance in declared for step in steps),
        'step uses an undeclared child instance')
    _require(all(child in covered or parents & obligations for child, parents in declared.items()),
        'declared child instance has neither a step nor an explicit dependency obligation')
    _parents_current(receipts, requests_path, request_raw)
    return graph, requests_path, request_raw, receipts


def write_configuration_composition(graph, requests_path, out):
    """Append graph tables to the builder's fresh material directory."""
    out = Path(out).absolute()
    _require(not out.exists() or out.is_dir(), 'composition output must be a directory')
    names = ('result.json', *(name+'.jsonl.gz' for name in _TABLES))
    _require(all(not (out/name).exists() for name in names), 'composition report and tables must not be overwritten')
    initial = pins()
    graph, requests_path, request_raw, receipts = _validate(graph, requests_path)
    _durable_mkdir(out)
    tables = {name: normal_output.write_table(out/(name+'.jsonl.gz'), getattr(graph, name)) for name in _TABLES}
    counts = {name: len(getattr(graph, name)) for name in (*_TABLES, 'profiles')}
    report = dict(schema=_SCHEMA, schema_version=1, status=_STATUS,
        **{name: codec.encode(getattr(graph, name)) for name in _HEADER},
        requests=dict(path=str(requests_path), sha256=sha256(request_raw).hexdigest()),
        tables=tables, counts=counts, **{name: counts[table] for name, table in _COUNTS.items()},
        implementation_sha256=initial['producer'], store_sha256=initial['store'],
        types_sha256=initial['types'], pins=initial, **{name: False for name in _FLAGS})
    _parents_current(receipts, requests_path, request_raw)
    _require(pins() == initial, 'composition producer changed during publication')
    _durable_bytes(out/'result.json', _json(report), replace=False)
    return report


def read_configuration_composition(path):
    path = Path(path).absolute()
    raw = (path/'result.json').read_bytes()
    report = json.loads(raw)
    expected = {'schema', 'schema_version', 'status', *_HEADER, 'requests', 'tables', 'counts',
        'material_count', 'dependency_count', 'step_count', 'obligation_count',
        'implementation_sha256', 'store_sha256', 'types_sha256', 'pins', *_FLAGS}
    _require(set(report) == expected and report['schema'] == _SCHEMA
        and type(report['schema_version']) is int and report['schema_version'] == 1
        and report['status'] == _STATUS, 'expected conditional ordered composition store')
    current = pins()
    _require(report['pins'] == current and report['implementation_sha256'] == current['producer']
        and report['store_sha256'] == current['store'] and report['types_sha256'] == current['types'],
        'configuration composition producer pins differ')
    _require(all(report[name] is False for name in _FLAGS), 'composition graph has no runtime or resolved-value authority')
    _require(set(report['tables']) == set(_TABLES), 'composition table coverage differs')
    parent = report['requests']
    _require(set(parent) == {'path', 'sha256'} and Path(parent['path']).is_absolute(), 'invalid request parent receipt')
    request_path = Path(parent['path'])
    _require(sha256((request_path/'result.json').read_bytes()).hexdigest() == parent['sha256'],
        'configuration request parent differs')
    document = {name: report[name] for name in _HEADER}
    for name, kind in _TABLES.items():
        receipt = report['tables'][name]
        data_store._receipt(receipt, name+'.jsonl.gz', table=True)
        rows = source_symbol_variants._table(path, receipt)
        _require(len(rows) == receipt['records'], 'composition table count differs')
        document[name] = [codec.encode(codec.decode(kind, item)) for item in rows]
    graph, _, request_raw, receipts = _validate(codec.decode(C.ConfigurationComposition, document), request_path)
    counts = {name: len(getattr(graph, name)) for name in (*_TABLES, 'profiles')}
    _require(report['counts'] == counts and all(type(value) is int for value in report['counts'].values())
        and all(type(report[key]) is int and report[key] == counts[name] for key, name in _COUNTS.items()),
        'composition counts differ')
    _parents_current(receipts, request_path, request_raw)
    _require(sha256(request_raw).hexdigest() == parent['sha256'] and (path/'result.json').read_bytes() == raw
        and pins() == current, 'composition manifest or inputs changed during reading')
    return report, graph
