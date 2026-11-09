"""Project original F4 function factories without entering or executing bodies.

The result describes creation operands. Selecting a later callable, creation
context, default attribute version or captured cell instance is a separate
interface obligation. Recipes and function bodies stay in their sealed store.
"""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import gc
from hashlib import sha256
import json
import multiprocessing
import os
from pathlib import Path
import resource
import sys
import time
from types import SimpleNamespace

from scar.analysis.source_context_query import ContextTargetGraph
from scar.analysis.source_declared_calls import _NoTargets, _check_targets, _folder, _flat_tables
from scar.analysis.source_graph_material import source_graph_material
from scar.analysis.source_namespace_interfaces import NamespacePlanView
from scar.analysis.source_namespace_captures import extract_captures
from scar.analysis.source_reference_slice import ReferenceSlicer, source_port
from scar.ir.program import source_function_creations as R
from scar.ir.program import source_productions as P, normal_graph as G, normal_targets as T
from scar.ir.program.control import LanguageCompletionKind as Completion
from scar.ir.program.model import ValueKind, ValueType
from scar.ir.program.signature_patterns import CountBinding, ChoiceBinding
from scar.ir.program.structured import PythonProtocolKind as Protocol
from scar.ir.program.source_template_links import SourceTemplateKey
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import encode, decode
from scar.analysis.normal_output import write_table
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json


SCHEMA = 'scar.source-function-creations'
UNIT_SCHEMA = 'scar.source-function-creation-unit'
NO_PROOF = ('runtime_function_instances_proven', 'current_defaults_proven', 'source_scopes_activated',
    'effects_closed', 'loops_unrolled', 'target_executed', 'first_stage_complete')
_WORKER = None


_PROTOCOLS = {
    Protocol.MAKE_LAMBDA_FUNCTION: R.FunctionFactoryKind.MAKE_LAMBDA_FUNCTION,
    Protocol.MAKE_GENEXPR_FUNCTION: R.FunctionFactoryKind.MAKE_GENEXPR_FUNCTION,
    Protocol.MAKE_NESTED_FUNCTION: R.FunctionFactoryKind.MAKE_NESTED_FUNCTION,
}


class _MissingRule(Exception):
    pass


def _require(condition, detail):
    if not condition: raise ValueError('source function creation: '+detail)


def _count(instruction, name):
    rows = [b.count for b in instruction.bindings if type(b) is CountBinding and b.name == name]
    _require(len(rows) == 1 and type(rows[0]) is int and rows[0] >= 0,
        'factory lacks one exact nonnegative '+name+' binding')
    return rows[0]


def _annotation_choice(instruction):
    rows = [b.choice for b in instruction.bindings if type(b) is ChoiceBinding and b.name == 'annotation_code']
    _require(len(rows) == 1 and rows[0] in ('ABSENT', 'PRESENT'), 'factory annotation_code choice differs')
    return rows[0] == 'PRESENT'


def _layout(instruction, environment):
    """Return exact default/cell/annotation operand ordinals and output arity."""
    defaults = tuple(i for i,p in enumerate(environment.parameters) if p.default_source is not None)
    keyword = tuple(i for i in defaults if environment.parameters[i].kind is P.DeferredParameterKind.KEYWORD_ONLY)
    positional = tuple(i for i in defaults if i not in keyword)
    # Source rules evaluate positional defaults before nonmissing keyword
    # defaults. This is not native MAKE_FUNCTION tuple/dict ordering.
    ordered = (*positional, *keyword)
    if type(instruction) is P.BuildFunction:
        _require(instruction.environment == environment, 'BuildFunction environment differs from DeferRegion')
        annotation = 2+len(ordered)+len(environment.captures) if instruction.annotations is not None else None
        return (R.FunctionFactoryKind.BUILD_FUNCTION, ordered, 2+len(ordered), annotation,
            R.AnnotationOperandKind.ANNOTATE_CALLABLE if annotation is not None else None, 1)
    if type(instruction) is not P.ApplyPythonProtocol or instruction.protocol not in _PROTOCOLS:
        raise _MissingRule('FUNCTION_FACTORY_INSTRUCTION_NOT_SUPPORTED:'+type(instruction).__name__)
    kind = _PROTOCOLS[instruction.protocol]
    _require(_count(instruction, 'closure_count') == len(environment.captures), 'closure_count differs from source relays')
    if instruction.protocol is Protocol.MAKE_GENEXPR_FUNCTION:
        _require(not defaults and environment.kind in (P.DeferredBodyKind.GENERATOR, P.DeferredBodyKind.ASYNC_GENERATOR),
            'genexpr factory needs its deferred generator interface and no defaults')
        _require(len(environment.parameters) == 1
            and environment.parameters[0].kind is P.DeferredParameterKind.INITIAL_ITERATOR,
            'genexpr factory lacks its original initial iterator formal')
        return kind, (), 2, None, None, 5
    if instruction.protocol is Protocol.MAKE_LAMBDA_FUNCTION:
        _require(_count(instruction, 'default_count') == len(positional)
            and _count(instruction, 'keyword_default_count') == len(keyword), 'lambda default counts differ')
        return kind, ordered, 2+len(ordered), None, None, 1
    if keyword:
        raise _MissingRule('MAKE_NESTED_FUNCTION_KEYWORD_DEFAULT_LAYOUT_NOT_DECLARED')
    _require(_count(instruction, 'default_count') == len(positional), 'nested function default_count differs')
    annotation = 2+len(ordered) if _annotation_choice(instruction) else None
    return (kind, ordered, 2+len(ordered)+int(annotation is not None), annotation,
        R.AnnotationOperandKind.ANNOTATION_CODE if annotation is not None else None, 1)


def _identify(view, step, function, facts, fact, origin, capture):
    code = step.arguments[0] if step.arguments else None
    if type(code) is not P.ProductionResult or code.index != 0:
        raise _MissingRule('FUNCTION_FACTORY_CODE_IS_NOT_LOCAL_DEFER_REGION_RESULT')
    declaration = view.steps.get(code.step)
    if declaration is None or type(declaration.instruction) is not P.DeferRegion:
        raise _MissingRule('FUNCTION_FACTORY_CODE_IS_NOT_LOCAL_DEFER_REGION_RESULT')
    declared = declaration.instruction; environment = declared.environment
    _require(function.environment == environment and function.body == declared.body,
        'function fact environment/body differs from original DeferRegion')
    body_scope = view.owner(declared.body)
    _require(function.body_scope == body_scope, 'function fact body code scope differs')
    body = view.regions[declared.body]
    _require(len(environment.parameters) == len(function.defaults) == len(function.parameter_names)
        and len(function.formals) == len(body.parameters) == len(environment.parameters)+2,
        'function fact formal/default layout differs')
    _require(all(p.default_source is not None or d is None
        for p,d in zip(environment.parameters,function.defaults)), 'default expression lacks its source parameter selector')
    kind, default_parameters, cell_start, annotation, annotation_kind, outputs = _layout(step.instruction, environment)
    reference = ValueType(ValueKind.REFERENCE); world = environment.world
    expected_refs = 2+len(default_parameters)+len(environment.captures)+int(annotation is not None)
    arguments = tuple(view.emitter.value(v)[1] for v in step.arguments)
    normal = [c for c in step.completions if c.kind is Completion.FALLTHROUGH]
    _require(arguments == (*(reference for _ in range(expected_refs)), world)
        and len(normal) == 1 and normal[0].types == (*(reference for _ in range(outputs)), world),
        'factory reference/world argument or normal output ABI differs')
    _require(capture is not None and capture.site == view.site(step)
        and capture.function == view.result(step) and capture.code == view.value(code)
        and capture.globals == view.value(step.arguments[1]) and capture.body == body_scope
        and capture.owner == view.owner(step.region) and capture.globals_scope == environment.globals_scope,
        'exact original globals creation join differs')
    defaults = []
    for ordinal, parameter in enumerate(default_parameters, 2):
        expression = function.defaults[parameter]
        defaults.append(R.FunctionDefaultCapture(parameter, environment.parameters[parameter].default_source,
            ordinal, view.value(step.arguments[ordinal]), None if expression is None else source_port(facts,expression)))
    cells = tuple(R.FunctionCellCapture(relay, cell_start+i, view.value(step.arguments[cell_start+i]))
        for i,relay in enumerate(environment.captures))
    before, after = view.worlds(step)
    return R.SourceFunctionCreation(fact, kind, origin, view.site(step), view.result(step), view.value(code),
        T.Body(view.unit, view.key, declared.body), body_scope, view.owner(step.region), environment,
        view.value(step.arguments[1]), tuple(defaults), cells, view.plan.capture_transports,
        None if annotation is None else view.value(step.arguments[annotation]), annotation_kind,
        step.instruction.annotations if type(step.instruction) is P.BuildFunction else None,
        before, after, tuple(view.result(step,i) for i in range(outputs)))


def project_creations(catalog, unit, templates=None):
    """Batch-read selected original factory plans and project every F.Function.

    ``templates=None`` selects the distinct templates in this unit's function
    facts. Explicit templates select that material domain only; omitted units,
    plans and unsupported factories remain outside the result's coverage.
    No old call table, namespace solver or core snapshot is loaded. Original
    source-fact evidence keys are retained, including collection routing keys;
    consumers materializing them must use the existing fact-material resolver.
    """
    material = source_graph_material(catalog, unit); facts = material.fact_store.load(unit)
    keys = ({f.template for f in facts.functions} if templates is None else set(templates))
    if any(type(k) is not SourceTemplateKey or k not in material.interfaces['nodes'] for k in keys):
        raise ValueError('source creation template is absent from original unit materials')
    keys = tuple(sorted(keys, key=lambda k:(k.occurrence,k.purpose.value)))
    plans = material.plans(keys)
    slicer = ReferenceSlicer(SimpleNamespace(fact_store=material.fact_store))
    references = {}; selected = [(i,f) for i,f in enumerate(facts.functions) if f.template in keys]
    for key,plan in plans.items():
        view = NamespacePlanView(unit, plan)
        _, captures, pending = extract_captures(view)
        by_function = {}
        for capture in captures:
            _require(capture.function not in by_function, 'duplicate function globals capture')
            by_function[capture.function] = capture
        references[key] = view, by_function, pending
    creations = []; obligations = []
    for ordinal,function in selected:
        fact = slicer.fact(facts, 'functions', ordinal); point = source_port(facts,function.value)
        view, captures, pending = references[function.template]; step = view.steps.get(point.port.owner)
        site = None if step is None else view.site(step)
        def missing(rule):
            obligations.append(R.FunctionCreationObligation(fact,point,function.template,site,rule))
        if step is None:
            missing('FUNCTION_FACT_HAS_NO_LOCAL_FACTORY_STEP'); continue
        _require(point == view.result(step), 'function fact is not the factory normal reference result')
        if not (type(step.instruction) is P.BuildFunction or type(step.instruction) is P.ApplyPythonProtocol
                and step.instruction.protocol in _PROTOCOLS):
            missing('FUNCTION_FACTORY_INSTRUCTION_NOT_SUPPORTED:'+type(step.instruction).__name__+(
                ':'+step.instruction.protocol.value if type(step.instruction) is P.ApplyPythonProtocol else ''))
            continue
        if point not in captures:
            # The existing pure extractor preserves the exact missing rule.
            reasons = tuple(row.reason for row in pending if row.site == site)
            for reason in reasons or ('FUNCTION_GLOBALS_CREATION_RELATION_NOT_EXTRACTED',): missing(reason)
            continue
        try:
            record = _identify(view,step,function,facts,fact,material.interfaces['nodes'][function.template].origin,captures[point])
        except _MissingRule as error:
            missing(str(error)); continue
        # Verify fact-side formals and preserve missing expression ports as an
        # explicit obligation; never substitute a factory parameter for them.
        body = view.regions[function.body]
        _require(tuple(source_port(facts,p) for p in function.formals) == tuple(
            view.gp(view.emitter.port(body.id,G.PortKind.PARAMETER,i)) for i in range(len(body.parameters))),
            'original function formal ports differ from declared body')
        creations.append(record)
        for default in record.defaults:
            if default.expression is None: missing('INITIAL_DEFAULT_EXPRESSION_PORT_NOT_RETAINED_IN_FUNCTION_FACT')
    material.validate_parents()
    return R.SourceFunctionCreationGraph(unit,material.result_artifact,keys,tuple(creations),tuple(obligations))


def _artifact(path, schema):
    path = Path(path).absolute(); raw = path.read_bytes()
    return ProviderArtifact(str(path), sha256(raw).hexdigest(), len(raw), schema)


def _stamp(path):
    s = path.stat()
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


def _pins():
    from scar.analysis import source_graph_material as materials, source_world_material
    from scar.analysis import source_namespace_interfaces, source_namespace_captures, source_reference_slice
    from scar.analysis import source_symbol_variants, normal_output, source_declared_calls, source_stage
    from scar.ir import record_codec
    from scar.ir.program import normal_links, protocol_signatures, signature_patterns, model, source_template_links
    return {name:sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in (
        ('producer', sys.modules[__name__]), ('types', R), ('materials', materials),
        ('ordinary_materials', source_world_material), ('namespace_ports', source_namespace_interfaces),
        ('globals_captures', source_namespace_captures), ('facts', source_reference_slice),
        ('fact_types', normal_links), ('target_types', T), ('graph_types', G), ('production_types', P),
        ('template_types', source_template_links), ('protocol_abi', protocol_signatures),
        ('signature_types', signature_patterns), ('value_types', model), ('tables', source_symbol_variants),
        ('output', normal_output), ('catalog_reader', source_declared_calls),
        ('durable_output', source_stage), ('codec', record_codec))}


def _selection(catalog, units=()):
    if isinstance(units, str): units = (units,)
    requested = tuple(units or ())
    if any(type(u) is not str or u not in catalog.fact_store.rows for u in requested):
        raise ValueError('function creation unit is outside the original catalog')
    return tuple(sorted(set(requested) if requested else catalog.fact_store.rows))


def _counts(graph):
    created = {r.function_fact for r in graph.creations}
    gaps = {r.function_fact for r in graph.obligations}
    return dict(source_function_facts=len(created | gaps), creations=len(graph.creations),
        projected_functions=len(created), functions_with_rule_gaps=len(gaps),
        unprojected_functions=len(gaps-created), templates=len(graph.templates),
        defaults=sum(len(r.defaults) for r in graph.creations),
        cell_handles=sum(len(r.captures) for r in graph.creations),
        annotations=sum(r.annotation is not None for r in graph.creations),
        factory_reference_outputs=sum(len(r.factory_results) for r in graph.creations),
        obligations=len(graph.obligations), factory_kinds=dict(Counter(r.factory.value for r in graph.creations)),
        missing_rules=dict(Counter(r.rule for r in graph.obligations)))


def _totals(shards):
    result = Counter(source_function_facts=sum(s['source_function_facts'] for s in shards.values()))
    factories = Counter(); rules = Counter(); states = Counter(s['status'] for s in shards.values())
    for shard in shards.values():
        if shard['status'] == 'FAILED': continue
        for key,value in shard['counts'].items():
            if key == 'factory_kinds': factories.update(value)
            elif key == 'missing_rules': rules.update(value)
            elif key != 'source_function_facts': result[key] += value
    return dict(result, units=len(shards), projected_units=states['PROJECTED'],
        rule_gap_units=states['RULE_GAPS'], failed_units=states['FAILED'],
        failed_source_function_facts=sum(s['source_function_facts'] for s in shards.values() if s['status']=='FAILED'),
        factory_kinds=dict(factories), missing_rules=dict(rules))


def _release(catalog):
    # Same release rule as the source coverage inventory. Compiled variants
    # retain their explicitly admitted facts; ordinary units reload per task.
    keep = set(catalog.fact_store.original_source_units); seen = set()
    def release(parent):
        if id(parent) in seen: return
        seen.add(id(parent))
        for unit in tuple(parent.loaded):
            if unit not in keep: del parent.loaded[unit]
        for child in getattr(parent, 'parents', ()): release(child)
    release(catalog.fact_store)
    for parent in catalog.fact_store._source_parents.values(): release(parent)


def _write_unit(catalog, unit, out, pins, parent):
    started = time.monotonic(); folder = Path(out)/_folder(unit); _durable_mkdir(folder)
    source = catalog.fact_store.rows[unit]
    report = dict(schema=UNIT_SCHEMA, schema_version=1, unit=unit, source=source['path'],
        module=source['module'], parent=encode(parent), pins=pins,
        source_function_facts=source['counts']['functions'], namespace_semantics_rederived=False,
        source_bodies_copied=False, **{name:False for name in NO_PROOF})
    try:
        graph = project_creations(catalog, unit); counts = _counts(graph)
        if counts['source_function_facts'] != report['source_function_facts']:
            raise ValueError('function creation records omitted an original function fact')
        tables = {name:write_table(folder/(name+'.jsonl.gz'), getattr(graph,name))
            for name in ('creations', 'obligations')}
        report.update(status='RULE_GAPS' if graph.obligations else 'PROJECTED',
            source_templates=encode(graph.source_templates), templates=encode(graph.templates), tables=tables, counts=counts)
        _check_targets()
    except Exception as error:
        # A failed unit has no admitted graph, even if a partial table was
        # written. Failure is not an UNKNOWN origin or a successful rule gap.
        report.update(status='FAILED', tables={}, counts=None, error_type=type(error).__name__, error=str(error))
    if pins != _pins(): raise ValueError('function creation rules changed while projecting a unit')
    report.update(seconds=time.monotonic()-started, worker_pid=os.getpid(),
        worker_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    _durable_bytes(folder/'result.json', _json(report), replace=False)
    shard = {name:report[name] for name in ('status','source_function_facts','tables','counts',
        'seconds','worker_pid','worker_peak_rss_kib')}
    shard.update(path=_folder(unit), result=encode(_artifact(folder/'result.json', UNIT_SCHEMA)))
    _release(catalog); gc.collect()
    return shard


def _initialize(catalog, out, pins, parent):
    global _WORKER
    sys.meta_path.insert(0, _NoTargets()); _check_targets()
    source = ContextTargetGraph(catalog)
    if pins != _pins() or encode(_artifact(source.path/'result.json',source.report['schema'])) != parent:
        raise ValueError('function creation worker producer or catalog differs')
    _WORKER = source, out, pins, decode(ProviderArtifact,parent)


def _worker(unit):
    catalog,out,pins,parent = _WORKER
    return unit,_write_unit(catalog,unit,out,pins,parent)


def build_creations(catalog, out, *, units=(), jobs=16):
    """Extract all catalog units by default; publish only independent shards."""
    started = time.monotonic(); out = Path(out).absolute(); pins = _pins(); _check_targets()
    if out.exists(): raise ValueError('fresh function creation output required')
    if type(jobs) is not int or jobs < 1: raise ValueError('positive function creation worker count required')
    source = catalog if isinstance(catalog,ContextTargetGraph) else ContextTargetGraph(catalog)
    selected = _selection(source,units); parent = _artifact(source.path/'result.json',source.report['schema'])
    ordered = sorted(selected,key=lambda u:(-source.fact_store.rows[u]['counts']['ports'],u))
    _durable_mkdir(out); shards = {}
    if jobs == 1:
        tasks = ((u,_write_unit(source,u,out,pins,parent)) for u in ordered)
        for unit,shard in tasks:
            shards[unit]=shard
            print(json.dumps(dict(done=len(shards),total=len(selected),unit=unit,status=shard['status'],
                seconds=round(shard['seconds'],3))),flush=True)
    else:
        with ProcessPoolExecutor(max_workers=min(jobs,len(selected)),mp_context=multiprocessing.get_context('spawn'),
                initializer=_initialize,initargs=(str(source.path),str(out),pins,encode(parent))) as pool:
            tasks = {pool.submit(_worker,u):u for u in ordered}
            for task in as_completed(tasks):
                unit,shard=task.result();shards[unit]=shard
                print(json.dumps(dict(done=len(shards),total=len(selected),unit=unit,status=shard['status'],
                    seconds=round(shard['seconds'],3))),flush=True)
    counts = _totals(shards)
    if pins != _pins() or _artifact(source.path/'result.json',parent.schema) != parent:
        raise ValueError('function creation producer or catalog changed')
    source.fact_store.validate_parents(); source.interface_store.validate_parents()
    report = dict(schema=SCHEMA,schema_version=1,
        status='INCOMPLETE_EXTRACTION' if counts['failed_units'] else 'SELECTED_SOURCE_FUNCTION_CREATIONS_EXTRACTED',
        catalog=str(source.path),parent=encode(parent),pins=pins,
        selection=dict(mode='EXPLICIT_UNITS' if units else 'CATALOG',units=list(selected)),
        denominator=dict(catalog_units=len(source.fact_store.rows),selected_units=len(selected),
            catalog_source_function_facts=sum(r['counts']['functions'] for r in source.fact_store.rows.values()),
            selected_source_function_facts=sum(source.fact_store.rows[u]['counts']['functions'] for u in selected)),
        shards=shards,tables=_flat_tables(shards),counts=counts,jobs=jobs,
        seconds=time.monotonic()-started,namespace_semantics_rederived=False,source_bodies_copied=False,
        scope='DECLARED_FACTORY_OPERANDS_AND_CELL_HANDLES_NOT_CURRENT_DEFAULTS_OR_CALLABLE_INSTANCES',
        **{name:False for name in NO_PROOF})
    _durable_bytes(out/'result.json',_json(report),replace=False)
    return report


class SourceFunctionCreationStore:
    """Receipt/type loading or explicit unit-level original-material replay."""
    def __init__(self,path,catalog=None):
        self.path=Path(path).absolute();self.raw=(self.path/'result.json').read_bytes();self.report=r=json.loads(self.raw)
        if (r['schema'],r['schema_version'])!=(SCHEMA,1) or r['pins']!=_pins():
            raise ValueError('function creation schema or producer differs')
        self.catalog=(catalog if isinstance(catalog,ContextTargetGraph) else ContextTargetGraph(r['catalog'] if catalog is None else catalog))
        self._catalog_raw=(self.catalog.path/'result.json').read_bytes(); self._loaded={}
        if (str(self.catalog.path)!=r['catalog'] or encode(_artifact(self.catalog.path/'result.json',
                self.catalog.report['schema']))!=r['parent']):
            raise ValueError('function creation original catalog differs')
        selection=r['selection']
        if selection['mode'] not in ('CATALOG','EXPLICIT_UNITS'):
            raise ValueError('function creation selection mode differs')
        selected=_selection(self.catalog,() if selection['mode']=='CATALOG' else selection['units'])
        denominator=dict(catalog_units=len(self.catalog.fact_store.rows),selected_units=len(selected),
            catalog_source_function_facts=sum(x['counts']['functions'] for x in self.catalog.fact_store.rows.values()),
            selected_source_function_facts=sum(self.catalog.fact_store.rows[u]['counts']['functions'] for u in selected))
        if (selection['units']!=list(selected) or tuple(r['shards'])!=selected or r['denominator']!=denominator
                or r['counts']!=_totals(r['shards']) or r['tables']!=_flat_tables(r['shards'])
                or r['status']!=('INCOMPLETE_EXTRACTION' if r['counts']['failed_units'] else 'SELECTED_SOURCE_FUNCTION_CREATIONS_EXTRACTED')
                or r['namespace_semantics_rederived'] is not False or r['source_bodies_copied'] is not False
                or r['scope']!='DECLARED_FACTORY_OPERANDS_AND_CELL_HANDLES_NOT_CURRENT_DEFAULTS_OR_CALLABLE_INSTANCES'
                or any(r[n] is not False for n in NO_PROOF)):
            raise ValueError('function creation selection, receipt index, counts or proof flags differ')
        for unit,shard in r['shards'].items():
            if (shard['path']!=_folder(unit) or shard['source_function_facts']!=self.catalog.fact_store.rows[unit]['counts']['functions']
                    or shard['status'] not in ('FAILED','PROJECTED','RULE_GAPS')
                    or set(shard['tables'])!=(set() if shard['status']=='FAILED' else {'creations','obligations'})
                    or any(t['path']!=name+'.jsonl.gz' for name,t in shard['tables'].items())):
                raise ValueError('function creation shard identity, denominator or tables differ')
        self.validate()

    def validate(self):
        if (self.raw!=(self.path/'result.json').read_bytes() or self.report['pins']!=_pins()
                or self._catalog_raw!=(self.catalog.path/'result.json').read_bytes()
                or json.loads(self._catalog_raw)!=self.catalog.report
                or any(_stamp(p)!=stamp for p,stamp in self._loaded.items())):
            raise ValueError('function creation rules, reports or loaded tables changed')
        self.catalog.fact_store.validate_parents();self.catalog.interface_store.validate_parents();_check_targets()

    def load_unit(self,unit):
        """Decode sealed tables and original receipts; semantic replay is separate."""
        self.validate();shard=self.report['shards'][unit];folder=self.path/shard['path']
        path=folder/'result.json';before=_stamp(path);raw=path.read_bytes();report=json.loads(raw)
        if (encode(_artifact(path,UNIT_SCHEMA))!=shard['result'] or _stamp(path)!=before
                or report['pins']!=self.report['pins'] or report['parent']!=self.report['parent']
                or report['schema']!=UNIT_SCHEMA or report['schema_version']!=1 or report['unit']!=unit
                or report['source']!=self.catalog.fact_store.rows[unit]['path']
                or report['module']!=self.catalog.fact_store.rows[unit]['module']
                or report['namespace_semantics_rederived'] is not False or report['source_bodies_copied'] is not False
                or any(report[n] is not False for n in NO_PROOF)
                or any(report[k]!=shard[k] for k in ('status','source_function_facts','tables','counts',
                    'seconds','worker_pid','worker_peak_rss_kib'))):
            raise ValueError('function creation unit report receipt or metadata differs')
        self._loaded[path]=before
        if report['status']=='FAILED':
            raise ValueError('function creation unit failed: '+report['error_type']+': '+report['error'])
        artifact=decode(ProviderArtifact,report['source_templates']); material=Path(artifact.uri);stamp=_stamp(material)
        if _artifact(material,artifact.schema)!=artifact or _stamp(material)!=stamp:
            raise ValueError('function creation original template receipt differs')
        self._loaded[material]=stamp
        def rows(name,kind):
            table=folder/report['tables'][name]['path'];before=_stamp(table)
            result=tuple(decode(kind,row,record_tags=P.PRODUCTION_RECORD_TAGS) for row in _table(folder,report['tables'][name]))
            if before!=_stamp(table):raise ValueError('function creation table changed while decoding')
            self._loaded[table]=before;return result
        graph=R.SourceFunctionCreationGraph(unit,artifact,tuple(decode(SourceTemplateKey,k) for k in report['templates']),
            rows('creations',R.SourceFunctionCreation),rows('obligations',R.FunctionCreationObligation))
        if (_counts(graph)!=report['counts'] or report['counts']['source_function_facts']!=report['source_function_facts']
                or report['status']!=('RULE_GAPS' if graph.obligations else 'PROJECTED')
                or any(x.function.unit!=unit for x in (*graph.creations,*graph.obligations))):
            raise ValueError('function creation typed unit counts, status or source identities differ')
        self.validate();return graph

    def read_unit(self,unit):
        graph=self.load_unit(unit)
        if graph!=project_creations(self.catalog,unit):
            raise ValueError('function creation records differ from original F4 factories/function facts')
        self.validate();return graph


def read_creations(path, *, unit, catalog=None):
    store=SourceFunctionCreationStore(path,catalog)
    return store.report,store.read_unit(unit)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog');parser.add_argument('--out');parser.add_argument('--read')
    parser.add_argument('--unit',action='append',default=[]);parser.add_argument('--jobs',type=int,default=16)
    args=parser.parse_args();sys.meta_path.insert(0,_NoTargets());_check_targets()
    if args.read:
        if not args.unit:parser.error('--read requires explicit --unit for bounded original-material replay')
        store=SourceFunctionCreationStore(args.read,args.catalog)
        result={u:_counts(store.read_unit(u)) for u in _selection(store.catalog,args.unit)}
        print(json.dumps(dict(status='SOURCE_FUNCTION_CREATIONS_REDERIVED',units=result,target_executed=False)),flush=True)
    else:
        if not args.catalog or not args.out:parser.error('--catalog and --out required')
        report=build_creations(args.catalog,args.out,units=args.unit,jobs=args.jobs)
        print(json.dumps({k:report[k] for k in ('status','counts','denominator','seconds')}),flush=True)


if __name__=='__main__':main()
