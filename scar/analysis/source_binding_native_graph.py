"""Connect named source declarations to canonical native schema interfaces.

The isolated existing parser/lowerer owns native graphs. This leaf adds only
receipt-bound links and normalization dependencies, preserving original source
ABI, native world/exception interfaces and open parser/dispatch obligations.
"""
import argparse
from collections import Counter
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import gzip
import json
from pathlib import Path
import re
import time
from types import SimpleNamespace

from scar.analysis import python_bindings, software_resources, static_native_interfaces
from scar.analysis import source_named_bindings, source_declared_calls
from scar.analysis.source_native_binding_materials import read_binding_materials, _target_guard
from scar.analysis.static_native_materials import StaticNativeMaterials
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_value_flow import _artifact
from scar.analysis.source_world_returns import _table_ref
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import source_binding_native_graph as N, source_named_bindings as M
from scar.ir.program import python_bindings as B, source_productions as P
from scar.ir.program import software_resources as S
from scar.ir.program.codec import dumps as graph_dumps
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.record_codec import decode, encode


SCHEMA = 'scar.source-binding-native-graph'
NO_PROOF = ('source_relations_rederived', 'source_match_rules_rederived', 'runtime_dispatch_proven',
    'parser_acceptance_proven', 'entry_activation_proven', 'effects_complete', 'optimization_authorized',
    'reference_identity_proven', 'target_executed', 'first_stage_complete')


def _flags(report):
    if report['all_declared_overloads_retained'] is not True or any(report[key] is not False for key in (
            'source_relations_rederived', 'parser_acceptance_proven', 'native_schemas_connected',
            'runtime_dispatch_proven', 'target_executed', 'first_stage_complete')):
        raise ValueError('named binding material cannot grant source, parser or runtime authority')


class BindingNativeParents:
    """Read named-match materials and generated definitions once, without solving."""
    def __init__(self, named):
        self.path = Path(named).absolute(); self.raw = (self.path/'result.json').read_bytes()
        self.report = r = json.loads(self.raw)
        if (r['schema'], r['schema_version']) != (source_named_bindings.SCHEMA, 1) or r['pins'] != source_named_bindings._pins():
            raise ValueError('named binding producer differs')
        _flags(r)
        self.binding_root = Path(r['bindings']).absolute()
        self.binding_report, self.definitions = read_binding_materials(self.binding_root)
        self.source_root = Path(r['calls']).absolute()
        self.source_raw = (self.source_root/'result.json').read_bytes(); source = json.loads(self.source_raw)
        if ((source['schema'], source['schema_version']) != (source_declared_calls.SCHEMA, 1)
                or source['pins'] != source_declared_calls._pins()
                or set(source['shards']) != set(r['shards'])):
            raise ValueError('named bindings changed their declared source unit coverage')
        actual = [encode(_artifact(self.source_root/'result.json', source['schema'])),
            encode(_artifact(self.binding_root/'result.json', self.binding_report['schema']))]
        if actual != r['parents']: raise ValueError('named binding source or declaration report differs')
        self.binding_raw = (self.binding_root/'result.json').read_bytes()
        self.artifact = _artifact(self.path/'result.json', r['schema'])
        self.binding_artifact = _artifact(self.binding_root/'result.json', self.binding_report['schema'])
        self.by_id = {definition.id: definition for definition in self.definitions}
        self.ordinals = {definition.id: ordinal for ordinal, definition in enumerate(self.definitions)}
        if len(self.by_id) != len(self.definitions): raise ValueError('generated binding IDs are ambiguous')
        flat = {unit+'/'+name: dict(receipt, path=item['path']+'/'+receipt['path'])
            for unit, item in r['shards'].items() for name, receipt in item['tables'].items()}
        totals = Counter()
        for unit, shard in r['shards'].items():
            if shard['path'] != 'units/'+unit or set(shard['tables']) != {'matches', 'frontiers'}:
                raise ValueError('named binding shard path or tables differ')
            if any(receipt['path'] != name+'.jsonl.gz' for name, receipt in shard['tables'].items()):
                raise ValueError('named binding table leaves its original unit shard')
            totals.update(shard['counts'])
        if flat != r['tables'] or dict(totals) != r['counts']:
            raise ValueError('named binding material receipt index or counts differ')
        self.validate()

    def declaration(self, binding):
        return _table_ref(self.binding_root, self.binding_report['definitions'],
            'scar.generated-python-binding-definitions', self.ordinals[binding])

    def validate(self):
        if (self.raw != (self.path/'result.json').read_bytes()
                or self.source_raw != (self.source_root/'result.json').read_bytes()
                or self.binding_raw != (self.binding_root/'result.json').read_bytes()
                or self.report['pins'] != source_named_bindings._pins()):
            raise ValueError('binding/native parent reports or matching rules changed')

    def matches(self, unit):
        self.validate(); shard = self.report['shards'][unit]; root = self.path/shard['path']
        rows = tuple(decode(M.NamedBindingMatch, wire, record_tags=P.PRODUCTION_RECORD_TAGS)
            for wire in _table(root, shard['tables']['matches']))
        frontiers = tuple(decode(M.NamedBindingFrontier, wire) for wire in _table(root, shard['tables']['frontiers']))
        counts = dict(matches=len(rows), requests_without_generated_binding=len(frontiers),
            matched_calls=len({row.call for row in rows}), matched_symbol_units=len({row.symbol for row in rows}))
        if counts != shard['counts']: raise ValueError('named binding unit material counts differ')
        for row in rows:
            definition = self.by_id[row.candidate.binding]; site = row.candidate.site
            if (row.declaration != self.declaration(definition.id) or row.candidate.runtime_binding_verified is not False
                    or site.result.unit != unit or site.callee.unit != unit or site.world.unit != unit
                    or site.result_world.unit != unit or row.symbol not in (
                        definition.namespace+'.'+definition.name, definition.registration_container+'.'+definition.name)):
                raise ValueError('named source ABI or generated declaration identity differs')
        return rows

    def match_reference(self, unit, ordinal):
        shard = self.report['shards'][unit]
        return _table_ref(self.path/shard['path'], shard['tables']['matches'], 'scar.named-binding-matches', ordinal)


def _read_native(root, batches, references, definitions):
    """Re-lower retained parser output; never restart the isolated parser."""
    result = {}; spans = {}
    for batch in batches:
        folder = Path(root)/batch['path']; artifact = decode(ProviderArtifact, batch['material'])
        if artifact != _artifact(folder/'materials.json', static_native_interfaces.SCHEMA):
            raise ValueError('native parser material receipt differs')
        wire = json.loads((folder/'materials.json').read_bytes())
        if (wire.get('schema'), wire.get('schema_version')) != (static_native_interfaces.SCHEMA, 1):
            raise ValueError('native material schema differs')
        materials = decode(StaticNativeMaterials, {k: v for k, v in wire.items() if k not in ('schema', 'schema_version')})
        if (materials.package_version != definitions['package_version']
                or materials.source_revision != definitions['source_revision']
                or tuple(d.selector for d in materials.declarations) != tuple(batch['selectors'])):
            raise ValueError('native selectors or installed declaration version differs')
        sources = [*materials.package_sources, materials.parser.worker, *materials.parser.tools]
        for declaration in materials.declarations:
            sources.extend((declaration.header_source, declaration.yaml_source, declaration.schema_source))
            sources.extend(item.source for item in (*declaration.dispatch, *declaration.fields))
        for span in sources:
            if span.path not in spans:
                raw = Path(span.path).read_bytes(); spans[span.path] = raw, sha256(raw).hexdigest()
            raw, digest = spans[span.path]
            if (len(raw) != span.size_bytes or digest != span.sha256
                    or not 0 <= span.byte_start < span.byte_end <= len(raw)
                    or sha256(raw[span.byte_start:span.byte_end]).hexdigest() != span.selection_sha256):
                raise ValueError('native tool/schema source span receipt differs')
        graphs = static_native_interfaces.lower_static_native_materials(materials, artifact)
        for declaration, graph in zip(materials.declarations, graphs):
            selector = declaration.selector; reference = references[selector]
            path = folder/(sha256(selector.encode()).hexdigest()[:24]+'.json.gz')
            payload = path.read_bytes(); raw = gzip.decompress(payload); expected = graph_dumps(graph).encode()
            boundary = graph.native_boundaries[0]
            actual = B.NativeSchemaReference(selector,
                SourceArtifactLocator(_artifact(path, 'scar.program-graph'), sha256(raw).hexdigest(),
                    len(raw), 'gzip-canonical-json'), boundary.id)
            if reference != actual or raw != expected: raise ValueError('native canonical graph or reference differs')
            ports = {port.name: slot.port for port, slot in zip(declaration.inputs, boundary.inputs)}
            if len(ports) != len(boundary.inputs): raise ValueError('native input names are not unique')
            result[selector] = reference, ports, boundary
    return result


def normalize_unit(parents, unit, links, natives):
    inputs = []; outputs = []
    for ordinal, row in enumerate(parents.matches(unit)):
        candidate = row.candidate; definition = parents.by_id[candidate.binding]; link = links[definition.id]
        reference, ports, boundary = natives[definition.selector]; evidence = parents.match_reference(unit, ordinal)
        if link.native != reference or link.declaration != row.declaration:
            raise ValueError('source match changed its binding/native schema link')
        conditions = tuple(dict.fromkeys((*candidate.conditions,
            'ORIGINAL_NAMED_MATCH_AND_BINDING_SCHEMA_LINK_SELECTED',
            'NATIVE_SCHEMA_PORT_DEPENDENCY_NOT_PARSER_OR_DISPATCH_PROOF')))
        site = candidate.site
        positional = tuple(argument for argument in definition.arguments if not argument.keyword_only)
        variadic = positional[0] if (len(positional) == 1 and positional[0].position == 0
            and re.fullmatch(r'(?:int|SymInt)\[\d*\]\??', positional[0].type)) else None
        shift = 1 if candidate.receiver_mode is B.ReceiverMode.UNBOUND else 0
        grouped = tuple(site.positional[shift:])
        for name, port in ports.items():
            operand = SimpleNamespace(boundary=boundary.id, port=port)
            for dependency in software_resources._input_sources(definition, operand, name,
                    result=site.result, positional=site.positional, keywords=site.keywords,
                    positional_pack=site.positional_pack, keyword_pack=site.keyword_pack,
                    receiver=candidate.receiver, receiver_mode=candidate.receiver_mode, conditions=conditions):
                aggregation = None
                if (variadic is not None and dependency.parser_parameter == variadic.name
                        and dependency.kind is S.OperandSourceKind.POSITIONAL and len(grouped) > 1
                        and variadic.name not in dict(site.keywords)
                        and site.positional_pack is None and site.keyword_pack is None):
                    # The generated single-positional int/SymInt list API can
                    # consume multiple scalar positionals as one array. Keep
                    # every dimension; this is aggregation, never an alias.
                    exact = variadic.type in ('int[]', 'SymInt[]')
                    dependency = replace(dependency, actuals=grouped,
                        kind=dependency.kind if exact else S.OperandSourceKind.CONVERSION_OPEN,
                        conditions=(*dependency.conditions,
                            'GENERATED_SINGLE_INTLIST_VARARG_FORM_SELECTED' if exact else
                            'POSITIONAL_ARRAY_VARARG_OR_SCALAR_BROADCAST_FORM_OPEN',
                            'POSITIONAL_ARRAY_AGGREGATION_NOT_VALUE_OR_STORAGE_ALIAS'))
                    aggregation = 'VARIADIC_INTLIST' if exact else 'POSITIONAL_ARRAY_FORM_OPEN'
                inputs.append(N.SourceOperandNormalization(evidence, dependency, aggregation))
        native_worlds = tuple(slot.port for slot in boundary.core_inputs)
        normal_worlds = tuple(slot.port for slot in boundary.core_outputs if slot.port.exit_name == 'normal')
        if len(native_worlds) != 1 or len(normal_worlds) != 1 or normal_worlds[0].index != len(boundary.outputs):
            raise ValueError('canonical native normal state interface differs from its separate core slots')
        outputs.append(N.SourceOutputNormalization(evidence, definition.id, row.declaration, boundary.id,
            site.result, site.world, site.result_world, native_worlds[0], normal_worlds[0],
            boundary.outputs, definition.python_return,
            definition.native_returns, (*conditions, 'DECLARED_WRAPPER_NORMAL_RETURN_PATH_SELECTED',
                'NATIVE_AND_PYTHON_RETURN_SLOTS_NOT_ASSUMED_ONE_TO_ONE',
                'WRAPPER_PRE_POST_NATIVE_EFFECTS_REMAIN_OPEN',
                'SOURCE_NATIVE_STATE_DEPENDENCY_NOT_LOGICAL_STATE_VERSION_EQUALITY',
                'NO_NATIVE_PYTHON_OBJECT_OR_STORAGE_IDENTITY_PROOF'),
            'PYTHON_RETURN_WRAPPING_UNRESOLVED' if definition.python_return is None else None))
    return N.SourceNormalizationUnit(unit, tuple(inputs), tuple(outputs))


def _counts(graph):
    return dict(matches=len(graph.outputs), input_dependencies=len(graph.inputs), output_dependencies=len(graph.outputs),
        input_actual_references=sum(len(row.dependency.actuals) for row in graph.inputs),
        matched_calls=len({row.result for row in graph.outputs}),
        open_inputs=sum(row.dependency.kind.value in ('CONVERSION_OPEN', 'RECEIVER_OPEN') for row in graph.inputs),
        pack_dependencies=sum(row.dependency.kind.value == 'PACK_DEPENDENCY' for row in graph.inputs),
        variadic_intlist_dependencies=sum(row.aggregation == 'VARIADIC_INTLIST' for row in graph.inputs),
        positional_array_form_open=sum(row.aggregation == 'POSITIONAL_ARRAY_FORM_OPEN' for row in graph.inputs),
        open_outputs=sum(row.frontier is not None for row in graph.outputs))


def _pins():
    from scar.analysis import static_native_materials, source_native_binding_materials, normal_output
    from scar.ir.program import software_resources as S, binding_returns as R, native, model, codec, validation
    from scar.ir import record_codec
    result = dict(producer=sha256(Path(__file__).read_bytes()).hexdigest())
    result.update({name: sha256(Path(module.__file__).read_bytes()).hexdigest() for name, module in (
        ('types', N), ('bindings', B), ('named_types', M), ('named', source_named_bindings),
        ('binding_materials', source_native_binding_materials), ('binding_producer', python_bindings),
        ('native_materials', static_native_materials), ('native_lowering', static_native_interfaces),
        ('normalization', software_resources), ('normalization_types', S), ('return_types', R),
        ('native_types', native), ('core_types', model), ('core_codec', codec), ('core_validation', validation),
        ('record_codec', record_codec), ('output', normal_output))})
    result['parser_worker'] = sha256(Path(static_native_materials.__file__).with_name('_static_native_parser_worker.py').read_bytes()).hexdigest()
    result.update({'generated_'+name: value for name, value in source_native_binding_materials._pins().items()})
    return result


def _totals(shards):
    counts = Counter()
    for shard in shards.values(): counts.update(shard['counts'])
    return dict(counts)


def build_binding_native_graph(named, out, *, jobs=4, parents=None):
    with _target_guard():
        started = time.monotonic(); pins = _pins(); out = Path(out).absolute()
        if out.exists(): raise ValueError('fresh binding/native output required')
        if type(jobs) is not int or jobs < 1: raise ValueError('positive isolated native parser job count required')
        parents = parents if parents is not None else BindingNativeParents(named)
        if parents.path != Path(named).absolute(): raise ValueError('binding/native named parent differs')
        used = set()
        for unit in parents.report['shards']: used.update(row.candidate.binding for row in parents.matches(unit))
        identities = tuple(sorted(used, key=lambda identity: identity.value))
        selectors = tuple(sorted({parents.by_id[identity].selector for identity in identities}))
        _durable_mkdir(out); tasks = [(Path(parents.binding_report['site']), out, i, selectors[start:start+64])
            for i, start in enumerate(range(0, len(selectors), 64))]
        generated = {}
        if tasks:
            with ThreadPoolExecutor(max_workers=min(jobs, len(tasks))) as pool:
                for batch in pool.map(python_bindings._native_batch, tasks):
                    if generated.keys() & batch.keys(): raise ValueError('native selector batches overlap')
                    generated.update(batch)
        if set(generated) != set(selectors): raise ValueError('native parser omitted a requested full selector')
        batches = [dict(path='native/'+f'{i:04d}', selectors=list(task[3]),
            material=encode(_artifact(out/'native'/f'{i:04d}'/'materials.json', static_native_interfaces.SCHEMA)))
            for i, task in enumerate(tasks)]
        references = {selector: value[0] for selector, value in generated.items()}
        natives = _read_native(out, batches, references, parents.binding_report)
        if any(generated[selector][1] != natives[selector][1] for selector in selectors):
            raise ValueError('native parser input-port interface differs from canonical lowering')
        links = tuple(N.BindingSchemaLink(identity, parents.declaration(identity), references[parents.by_id[identity].selector])
            for identity in identities)
        link_table = write_table(out/'links.jsonl.gz', links); by_id = {link.binding: link for link in links}; shards = {}
        for unit in parents.report['shards']:
            graph = normalize_unit(parents, unit, by_id, natives); folder = out/'units'/unit; _durable_mkdir(folder)
            tables = {name: write_table(folder/(name+'.jsonl.gz'), getattr(graph, name)) for name in ('inputs', 'outputs')}
            shards[unit] = dict(path='units/'+unit, tables=tables, counts=_counts(graph))
        parents.validate()
        if pins != _pins(): raise ValueError('binding/native projection rules changed')
        tables = dict(links=link_table, **{unit+'/'+name: dict(receipt, path=shard['path']+'/'+receipt['path'])
            for unit, shard in shards.items() for name, receipt in shard['tables'].items()})
        report = dict(schema=SCHEMA, schema_version=1, status='SOURCE_NORMALIZATION_TO_CANONICAL_NATIVE_SCHEMAS',
            named=str(parents.path), bindings=str(parents.binding_root),
            parents=[encode(parents.artifact), encode(parents.binding_artifact)], pins=pins,
            batches=batches, shards=shards, tables=tables, jobs=jobs,
            vararg_rule=encode(_artifact(Path(parents.binding_report['site'])/'torchgen/api/python.py',
                'scar.torchgen-python-signatures-source')),
            counts=dict(_totals(shards), units=len(shards), binding_links=len(links), selectors=len(selectors)),
            native_schemas_connected=True, **{name: False for name in NO_PROOF}, seconds=time.monotonic()-started)
        _durable_bytes(out/'result.json', _json(report), replace=False)
        return report


class BindingNativeStore:
    def __init__(self, path, *, parents=None):
        self.path = Path(path).absolute(); self.raw = (self.path/'result.json').read_bytes()
        self.report = r = json.loads(self.raw)
        if (r['schema'], r['schema_version']) != (SCHEMA, 1) or r['pins'] != _pins():
            raise ValueError('binding/native producer differs')
        self.parents = parents if parents is not None else BindingNativeParents(r['named'])
        if r['vararg_rule'] != encode(_artifact(Path(self.parents.binding_report['site'])/'torchgen/api/python.py',
                'scar.torchgen-python-signatures-source')):
            raise ValueError('generated positional array aggregation rule source differs')
        if (str(self.parents.path) != r['named'] or str(self.parents.binding_root) != r['bindings']
                or r['parents'] != [encode(self.parents.artifact), encode(self.parents.binding_artifact)]
                or set(r['shards']) != set(self.parents.report['shards'])):
            raise ValueError('binding/native original source/declaration inputs or unit coverage differ')
        self.links = tuple(decode(N.BindingSchemaLink, wire) for wire in _table(self.path, r['tables']['links']))
        self.by_id = {}; references = {}
        for link in self.links:
            definition = self.parents.by_id[link.binding]
            if (link.binding in self.by_id or link.declaration != self.parents.declaration(link.binding)
                    or link.native.selector != definition.selector):
                raise ValueError('binding/native link changed its original declaration or selector')
            self.by_id[link.binding] = link
            if link.native.selector in references and references[link.native.selector] != link.native:
                raise ValueError('native selector has conflicting canonical references')
            references[link.native.selector] = link.native
        declared = []
        for i, batch in enumerate(r['batches']):
            if batch['path'] != 'native/'+f'{i:04d}' or not 1 <= len(batch['selectors']) <= 64:
                raise ValueError('native batch path or selector budget differs')
            declared.extend(batch['selectors'])
        if tuple(declared) != tuple(sorted(references)) or len(declared) != len(set(declared)):
            raise ValueError('native selector batch coverage differs')
        self.natives = _read_native(self.path, r['batches'], references, self.parents.binding_report)
        flat = dict(links=r['tables']['links'])
        for unit, shard in r['shards'].items():
            if (shard['path'] != 'units/'+unit or set(shard['tables']) != {'inputs', 'outputs'}
                    or any(v['path'] != name+'.jsonl.gz' for name, v in shard['tables'].items())
                    or shard['counts']['matches'] != self.parents.report['shards'][unit]['counts']['matches']):
                raise ValueError('normalization shard path or original source match coverage differs')
            flat.update({unit+'/'+name: dict(receipt, path=shard['path']+'/'+receipt['path'])
                for name, receipt in shard['tables'].items()})
        counts = dict(_totals(r['shards']), units=len(r['shards']), binding_links=len(self.links), selectors=len(references))
        if counts != r['counts'] or flat != r['tables']:
            raise ValueError('binding/native global table directory or counts differ')
        if r['native_schemas_connected'] is not True or any(r[name] is not False for name in NO_PROOF):
            raise ValueError('native schema dependencies cannot grant runtime, parser, effect or optimization authority')
        self.validate()

    def validate(self):
        self.parents.validate()
        if self.raw != (self.path/'result.json').read_bytes() or self.report['pins'] != _pins():
            raise ValueError('binding/native report or projection rules changed')

    def read_unit(self, unit):
        with _target_guard():
            self.validate(); shard = self.report['shards'][unit]; folder = self.path/shard['path']
            graph = N.SourceNormalizationUnit(unit,
                tuple(decode(N.SourceOperandNormalization, wire, record_tags=P.PRODUCTION_RECORD_TAGS)
                    for wire in _table(folder, shard['tables']['inputs'])),
                tuple(decode(N.SourceOutputNormalization, wire, record_tags=P.PRODUCTION_RECORD_TAGS)
                    for wire in _table(folder, shard['tables']['outputs'])))
            if graph != normalize_unit(self.parents, unit, self.by_id, self.natives) or _counts(graph) != shard['counts']:
                raise ValueError('source actuals, normalization or declared native/Python returns differ')
            self.validate()
            return graph


def read_binding_native_graph(path, *, unit, parents=None):
    store = BindingNativeStore(path, parents=parents)
    return store.report, store.read_unit(unit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--named'); parser.add_argument('--out'); parser.add_argument('--read'); parser.add_argument('--unit')
    parser.add_argument('--jobs', type=int, default=4); args = parser.parse_args()
    if args.read:
        if not args.unit: parser.error('--read requires --unit')
        report, _ = read_binding_native_graph(args.read, unit=args.unit)
    else:
        if not args.named or not args.out: parser.error('--named and --out required')
        report = build_binding_native_graph(args.named, args.out, jobs=args.jobs)
    print(json.dumps(dict(status=report['status'], counts=report['counts'], seconds=report['seconds'])), flush=True)


if __name__ == '__main__':
    main()
