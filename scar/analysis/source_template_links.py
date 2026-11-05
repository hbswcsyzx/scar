"""Link sealed source templates by original slots, without lowering or running.

Each source unit is independent. Stored nodes reference the original recipe
bodies; edges bind actual values to ordered parameters and completion ports.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import fields, is_dataclass
from functools import lru_cache
import gzip
from hashlib import sha256
import io
import json
import multiprocessing
import os
from pathlib import Path
import re
import sysconfig
import time

from scar.analysis.source_expression_materials import _implementation, _basis
from scar.analysis.source_productions import _digest, production_type_catalog, read_production_plan
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir, _sync_directory
from scar.analysis.static_query import _Fragments
from scar.ir.program import source_productions as P
from scar.ir.program import source_template_links as T
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.model import ValueKind, ValueType
from scar.ir.record_codec import encode, decode


class TemplateLinkError(ValueError):
    pass


def _require(condition, path, detail):
    if not condition:
        raise TemplateLinkError(str(path) + ': ' + detail)


def validate_state_sequence(plan):
    """Check current-world origins in an already shape-checked local recipe.

    Types alone permit using a previous world after an effect. Read-only
    operations may inspect the current world without replacing it; a normal
    state result becomes the following steps' current world. Nested call
    operands are included, without entering their shared/deferred bodies.

    This proves local sequencing, not the physical effects of native calls,
    the value of a mutable referent, or Python reference cleanup semantics.
    """
    regions = {r.id: r for r in plan.regions}
    normal = {s.id: next((c.types for c in s.completions if c.kind is C.FALLTHROUGH), ())
        for s in plan.steps}
    steps = {s.id: s for s in plan.steps}

    def state(kind):
        return type(kind) is ValueType and kind.kind is ValueKind.STATE

    def value_type(value):
        if type(value) is P.ProductionParameter:
            return regions[value.region].parameters[value.index]
        return normal[value.step][value.index]

    def operands(step):
        # The finite instruction schema also contains nested call arguments,
        # captures and saved operands. Do not infer them from display labels.
        pending = [step.instruction, step.arguments]
        while pending:
            item = pending.pop()
            if type(item) in (P.ProductionParameter, P.ProductionResult):
                yield item
            elif type(item) is tuple:
                pending.extend(reversed(item))
            elif is_dataclass(item):
                pending.extend(getattr(item, field.name) for field in reversed(fields(item)))

    uses = results = loops = 0
    for region in plan.regions:
        incoming = [P.ProductionParameter(region.id, i) for i, kind in enumerate(region.parameters) if state(kind)]
        _require(len(incoming) <= 1, region.id, 'one current-world input is permitted per local region')
        current = incoming[0] if incoming else None
        for identity in region.steps:
            step = steps[identity]
            used = [v for v in operands(step) if state(value_type(v))]
            _require(all(v == current for v in used), identity, 'operand uses a stale or foreign world instead of the current world')
            uses += len(used)
            if type(step.instruction) is P.LoopControl:
                loops += 1
                _require(not any(state(value_type(v)) for v in step.arguments[:step.instruction.invariant_count]),
                    identity, 'current world must be loop-carried, never a loop invariant')
            produced = [i for i, kind in enumerate(normal[identity]) if state(kind)]
            _require(len(produced) <= 1, identity, 'one normal current-world result is permitted per step')
            if produced:
                _require(bool(used), identity, 'a normal world result requires a current-world operand')
                current = P.ProductionResult(identity, produced[0])
                results += 1
    return dict(regions=len(regions), steps=len(steps), state_uses=uses, state_results=results, loop_templates=loops)


def build_template_graph(unit, syntax, records, *, max_visits=1_000_000):
    """Consume (domain, one-based line, plan document), never parse source."""
    nodes = {}; contexts = {}; sites = []; common_input = common_profile = None
    syntax_digest = _digest(syntax)
    for domain, line, document in records:
        _require(type(domain) is T.SourceMaterialDomain and type(line) is int and line > 0,
            unit, 'invalid original material coordinates')
        plan = read_production_plan(document, max_visits=max_visits)
        validate_state_sequence(plan)
        _require(type(plan.source) is P.ProductionOccurrence and plan.profile is not None
            and plan.compilation_flow is not None, unit, 'expected a source-bound profiled occurrence template')
        if common_input is None:
            common_input, common_profile = plan.input, plan.profile
        _require(plan.input == common_input and plan.profile == common_profile,
            unit, 'templates mix source inputs or state/exception profiles')
        _require(plan.input.f2_sha256 == syntax_digest and plan.input.path == syntax['input']['path'], unit, 'original F2 input differs')
        key = T.SourceTemplateKey(plan.source.occurrence, plan.purpose)
        digest = _digest(document)
        if key in nodes:
            _require(nodes[key].origin.plan_sha256 == digest, key, 'conflicting templates for the same source/purpose')
            continue
        regions = {r.id: r for r in plan.regions}; steps = {s.id: s for s in plan.steps}
        root = regions[plan.root]
        nodes[key] = T.SourceTemplateNode(key, root.id, root.parameters, root.completions,
            T.SourceTemplateOrigin(domain, line, digest))
        contexts[key] = next(p for p in plan.compilation_flow.ports if p.region == plan.root)
        child_contexts = {e.step:e.target for e in plan.compilation_flow.edges if e.kind is P.CompilationEdgeKind.CHILD}
        for step in plan.steps:
            instruction = step.instruction
            if type(instruction) is not P.EvaluateChild:
                continue
            field = instruction.field
            _require(field.group == 'FIELD' and 0 <= field.occurrence < len(syntax['nodes']), step.id, 'child has no original field')
            fields = syntax['nodes'][field.occurrence]['fields']
            _require(0 <= field.ordinal < len(fields), step.id, 'child field ordinal outside original F2')
            value = fields[field.ordinal]
            for index in field.item_path:
                _require(value['kind'] == 'LIST' and 0 <= index < len(value['items']), step.id, 'child list path outside original F2')
                value = value['items'][index]
            _require(value['kind'] == 'NODE', step.id, 'child entry is not one original occurrence')
            target = T.SourceTemplateKey(value['reference'], instruction.purpose)
            arguments = []
            for argument in step.arguments:
                if type(argument) is P.ProductionParameter:
                    arguments.append(regions[argument.region].parameters[argument.index])
                else:
                    normal = next(c.types for c in steps[argument.step].completions if c.kind is C.FALLTHROUGH)
                    arguments.append(normal[argument.index])
            sites.append((key, step, target, tuple(arguments), child_contexts[step.id]))
    _require(common_input is not None, unit, 'no executable source templates in the selected material domain')
    links = []
    for caller, step, target, arguments, context in sites:
        _require(target in nodes, step.id, 'missing target template: ' + str(target))
        callee = nodes[target]
        _require(arguments == callee.parameters, step.id, 'actual arguments differ from callee parameters')
        advertised = {(c.kind, c.target): c.types for c in step.completions}
        _require(all(advertised.get((c.kind, c.target)) == c.types for c in callee.completions),
            step.id, 'callee completion is not represented by the caller interface')
        port = contexts[target]
        _require((context.source_scope, context.code_scope) == (port.source_scope, port.code_scope),
            step.id, 'child compilation environment differs from the target entry')
        links.append(T.SourceTemplateLink(caller, step.id, target, step.arguments))
    return T.SourceTemplateGraph(unit, common_input, common_profile, tuple(nodes.values()), tuple(links))


def _json(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False) + '\n').encode('ascii')


def _compiler_profile():
    header = Path(sysconfig.get_path('include')) / 'internal' / 'pycore_compile.h'
    raw = header.read_bytes()
    limits = re.findall(rb'^#define\s+_PY_STACK_USE_GUIDELINE\s+([0-9]+)\s*$', raw, re.MULTILINE)
    _require(len(limits) == 1 and int(limits[0]) > 0, header, 'current compiler profile lacks a unique positive stack guideline')
    return dict(header=str(header), header_sha256=sha256(raw).hexdigest(), stack_guideline=int(limits[0]))


class _Store:
    def __init__(self, domain, material, verification, manifest_sha256):
        self.domain = T.SourceMaterialDomain(domain)
        self.root = Path(material).absolute(); self.verification = Path(verification).absolute()
        _require(self.root.resolve() == self.root and self.verification.resolve() == self.verification,
            domain, 'parent paths must be canonical')
        raw = (self.root / 'result.json').read_bytes(); checked = (self.verification / 'result.json').read_bytes()
        a, b = json.loads(raw), json.loads(checked)
        _require(a['mode'] == 'COLLECTION' and b['mode'] == 'FRESH_VERIFICATION'
            and a['status'] == b['status'] == 'LOCAL_RULES_VERIFIED', domain, 'parent materials lack completed independent verification')
        for field in ('schema', 'schema_version', 'domain', 'input_basis', 'counts', 'limits', 'catalog_sha256', 'implementation_sha256', 'model_manifest_sha256'):
            _require(a[field] == b[field], domain, 'collection/verification differ: ' + field)
        _require(a['domain'] == domain and a['schema_version'] == 4
            and a['implementation_sha256'] == _implementation() and a['model_manifest_sha256'] == manifest_sha256,
            domain, 'parent domain, model or generator version differs')
        catalog = (self.root / 'catalog.json').read_bytes()
        _require(sha256(catalog).hexdigest() == a['catalog_sha256']
            and (self.verification / 'catalog.json').read_bytes() == catalog, domain, 'parent catalog differs')
        declaration = json.loads(catalog)
        _require(type(declaration) is dict, domain, 'parent catalog must be a record')
        self.catalog_type_sha256 = declaration.get('recipe_type_catalog_sha256')
        self.compiler_profile = declaration.get('call_compiler_profile')
        _require(self.catalog_type_sha256 == production_type_catalog()['content_sha256'],
            domain, 'parent recipe differs from the current type/support catalog')
        _require(self.compiler_profile == _compiler_profile(),
            domain, 'parent recipe differs from the current compiler profile')
        self.profile = decode(P.SourceProductionProfile,
            dict(world=declaration['state_parameter'], exception_abi=declaration['exception_abi']))
        self.rows = {u['unit']: u for u in a['units']}; self.basis = {u['unit']: u for u in a['input_basis']}
        fresh_rows = {u['unit']: u for u in b['units']}
        _require(len(self.rows) == len(a['units']) and len(self.basis) == len(a['input_basis'])
            and len(fresh_rows) == len(b['units']) and set(self.rows) == set(self.basis) == set(fresh_rows),
            domain, 'duplicate or missing parent source units')
        _require(all(self.rows[key][field] == fresh_rows[key][field] for key in self.rows
            for field in ('artifact', 'input', 'catalog_sha256')), domain, 'fresh proof refers to another unit fragment/input')
        self.generator_pins = a['implementation_sha256']
        self.receipt = dict(domain=domain, materials=str(self.root), verification=str(self.verification),
            collection_sha256=sha256(raw).hexdigest(), verification_sha256=sha256(checked).hexdigest())

    def unchanged(self):
        return (sha256((self.root / 'result.json').read_bytes()).hexdigest() == self.receipt['collection_sha256']
            and sha256((self.verification / 'result.json').read_bytes()).hexdigest() == self.receipt['verification_sha256']
            and self.catalog_type_sha256 == production_type_catalog()['content_sha256']
            and self.compiler_profile == _compiler_profile())

    def records(self, unit):
        _require(unit['key'] in self.rows and self.basis[unit['key']] == _basis(unit), unit['path'], 'parent material/input is unavailable or differs')
        row = self.rows[unit['key']]; descriptor = row['artifact']; path = self.root / descriptor['path']
        _require(path.resolve() == path and path.is_relative_to(self.root) and not path.is_symlink(), unit['path'], 'unsafe parent fragment path')
        payload = path.read_bytes()
        _require(len(payload) == descriptor['bytes'] and sha256(payload).hexdigest() == descriptor['sha256'], unit['path'], 'parent compressed receipt differs')
        digest = sha256(); size = 0
        with gzip.open(path, 'rb') as stream:
            for line, raw in enumerate(stream, 1):
                digest.update(raw); size += len(raw)
                _require(size <= descriptor['decoded_bytes'], path, 'parent decoded byte budget exceeded')
                record = json.loads(raw)
                if 'plan' in record:
                    yield self.domain, line, record['plan']
        _require(size == descriptor['decoded_bytes'] and digest.hexdigest() == descriptor['decoded_sha256'], path, 'parent decoded receipt differs')


def _stream(path, records):
    digest = sha256(); decoded_bytes = 0; count = 0
    with path.open('xb') as destination:
        with gzip.GzipFile(filename='', mode='wb', fileobj=destination, compresslevel=3, mtime=0) as stream:
            for record in records:
                raw = _json(encode(record, record_tags=P.PRODUCTION_RECORD_TAGS))
                stream.write(raw); digest.update(raw); decoded_bytes += len(raw); count += 1
        destination.flush(); os.fsync(destination.fileno())
    payload = path.read_bytes()
    return dict(path=path.name, bytes=len(payload), sha256=sha256(payload).hexdigest(),
        decoded_bytes=decoded_bytes, decoded_sha256=digest.hexdigest(), records=count)


@lru_cache(maxsize=1)
def _worker_stores(specifications, manifest_sha):
    """Process-local immutable parent indexes; no shared graph or descriptor table."""
    stores = []
    for domain, material, verification, collected_sha, verified_sha in specifications:
        store = _Store(domain, material, verification, manifest_sha)
        _require((store.receipt['collection_sha256'], store.receipt['verification_sha256'])
            == (collected_sha, verified_sha), domain, 'worker parent proof differs from its submitted snapshot')
        stores.append(store)
    return tuple(stores)


def _link_unit(task):
    unit, model, out, specifications, manifest_sha, max_visits, linker_pin, types_pin = task
    _require(linker_pin == sha256(Path(__file__).read_bytes()).hexdigest()
        and types_pin == sha256(Path(T.__file__).read_bytes()).hexdigest(), unit['path'], 'worker linker version differs')
    stores = _worker_stores(specifications, manifest_sha)
    try:
        syntax = _Fragments(Path(model)).read(unit['artifacts']['source_syntax'])
        graph = build_template_graph(unit['key'], syntax,
            (record for store in stores for record in store.records(unit)), max_visits=max_visits)
        path = Path(out) / 'units' / unit['key']; _durable_mkdir(path)
        nodes = _stream(path / 'templates.jsonl.gz', graph.templates)
        links = _stream(path / 'links.jsonl.gz', graph.links)
        header = dict(schema=graph.schema, schema_version=graph.schema_version, authority=graph.authority,
            unit=unit['key'], input=encode(graph.input), profile=encode(graph.profile), templates=nodes, links=links)
        header_bytes = _json(header)
        _durable_bytes(path / 'header.json', header_bytes, replace=False); _sync_directory(path)
        return dict(unit=unit['key'], path=unit['path'], header='units/'+unit['key']+'/header.json',
            header_bytes=len(header_bytes), header_sha256=sha256(header_bytes).hexdigest(),
            templates=nodes['records'], links=links['records'], compressed_bytes=nodes['bytes']+links['bytes'])
    except Exception as error:
        error.add_note('SCAR template interfaces source: ' + unit['path'])
        raise


def link_source_templates(model, out, parents, sources=(), *, max_visits=1_000_000, jobs=1):
    started = time.monotonic()
    _require(type(max_visits) is int and max_visits >= 0, 'max_visits', 'expected a nonnegative integer')
    _require(type(jobs) is int and 1 <= jobs <= 32, 'jobs', 'expected 1 through 32 independent source workers')
    model = Path(model).absolute(); out = Path(out).absolute()
    _require(model.resolve() == model and out.resolve() == out and not out.exists(), out, 'output must be a fresh canonical path')
    raw = (model / 'manifest.json').read_bytes(); manifest_sha = sha256(raw).hexdigest(); manifest = json.loads(raw)
    linker_pin = sha256(Path(__file__).read_bytes()).hexdigest(); types_pin = sha256(Path(T.__file__).read_bytes()).hexdigest()
    stores = sorted((_Store(*parent, manifest_sha) for parent in parents), key=lambda s:s.domain.value)
    _require(len(stores) == 3 and {s.domain for s in stores} == set(T.SourceMaterialDomain), 'parents', 'one independently verified store per domain is required')
    _require(all(not out.is_relative_to(p) and not p.is_relative_to(out) for p in
        (model, *(s.root for s in stores), *(s.verification for s in stores))), out, 'output overlaps a parent')
    wanted = {str(Path(p).absolute()) for p in sources}
    units = sorted((u for u in manifest['units'] if not wanted or u['path'] in wanted), key=lambda u:u['key'])
    _require(bool(units) and (not wanted or wanted == {u['path'] for u in units}), 'sources', 'source selection is not exact')
    _require(len({u['key'] for u in units}) == len(units), 'sources', 'duplicate source unit identity')
    _require(all(u['key'] in s.rows for u in units for s in stores), 'parents', 'selected sources lack a complete material domain')
    specifications = tuple((s.domain.value, str(s.root), str(s.verification), s.receipt['collection_sha256'],
        s.receipt['verification_sha256']) for s in stores)
    tasks = [(u, str(model), str(out), specifications, manifest_sha, max_visits, linker_pin, types_pin) for u in units]
    _durable_mkdir(out)
    if jobs == 1:
        rows = [_link_unit(task) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context('spawn')) as pool:
            rows = list(pool.map(_link_unit, tasks))
    _require((model / 'manifest.json').read_bytes() == raw, model, 'model changed during interface linking')
    _require(all(s.unchanged() and s.generator_pins == _implementation() for s in stores)
        and linker_pin == sha256(Path(__file__).read_bytes()).hexdigest()
        and types_pin == sha256(Path(T.__file__).read_bytes()).hexdigest(), out, 'parent proofs or implementation changed during linking')
    report = dict(schema='scar.source-template-link-store', schema_version=1, status='SOURCE_INTERFACES_LINKED',
        generator_sha256=stores[0].generator_pins, linker_sha256=linker_pin,
        link_types_sha256=types_pin, model_manifest_sha256=manifest_sha,
        parents=[s.receipt for s in stores], selected_sources=len(rows), units=rows, max_visits=max_visits, jobs=jobs,
        templates=sum(r['templates'] for r in rows), links=sum(r['links'] for r in rows),
        compressed_bytes=sum(r['compressed_bytes'] for r in rows),
        local_state_sequence_checked=True,
        parent_catalogs_current=True,
        canonical_graph_generated=False, child_semantics_proven=False, effects_proven=False,
        first_stage_complete=False, target_executed=False, transformation_authorized=False, seconds=time.monotonic()-started)
    _durable_bytes(out / 'result.json', _json(report), replace=False)
    return report


def _read_graph_table(path, descriptor, expected):
    fragment = path.parent / descriptor['path']
    _require(fragment.resolve() == fragment and fragment.parent == path.parent, path, 'unsafe graph table')
    payload = fragment.read_bytes()
    _require(len(payload) == descriptor['bytes'] and sha256(payload).hexdigest() == descriptor['sha256'], path, 'graph table compressed receipt differs')
    digest = sha256(); size = 0; rows = []
    with gzip.GzipFile(fileobj=io.BytesIO(payload), mode='rb') as stream:
        for raw in stream:
            digest.update(raw); size += len(raw)
            _require(size <= descriptor['decoded_bytes'], path, 'graph table decoded budget exceeded')
            rows.append(decode(expected, json.loads(raw), record_tags=P.PRODUCTION_RECORD_TAGS))
    _require(size == descriptor['decoded_bytes'] and digest.hexdigest() == descriptor['decoded_sha256']
        and len(rows) == descriptor['records'], path, 'graph table decoded receipt or record count differs')
    return tuple(rows)


def read_template_graph(store, unit):
    """Read one typed interface graph and verify its sealed parent snapshot.

    Checks stored tables, identities, interface-reference closure and current
    declarations. Source-rule semantics were checked by the producer; original
    bodies are read on expansion. No native-effect or canonical-IR proof is
    granted here. Parent indexes are process-local immutable cache entries.
    """
    store = Path(store).absolute()
    _require(store.resolve() == store and type(unit) is str and Path(unit).name == unit and unit not in ('', '.', '..'), store, 'invalid store or source unit')
    report_bytes = (store / 'result.json').read_bytes(); report = json.loads(report_bytes)
    _require(report['schema'] == 'scar.source-template-link-store' and report['schema_version'] == 1
        and report['status'] == 'SOURCE_INTERFACES_LINKED', store, 'no completed interface link publication')
    _require(report['link_types_sha256'] == sha256(Path(T.__file__).read_bytes()).hexdigest()
        and report['generator_sha256'] == _implementation(), store, 'stored interface or generator declarations differ')
    _require(len(report['units']) == report['selected_sources']
        and len({r['unit'] for r in report['units']}) == len(report['units']), store, 'source index count or identities differ')
    specifications = tuple((p['domain'], p['materials'], p['verification'], p['collection_sha256'], p['verification_sha256']) for p in report['parents'])
    _require(len(specifications) == 3 and {p[0] for p in specifications} == {d.value for d in T.SourceMaterialDomain}, store, 'one parent snapshot per domain is required')
    parents = _worker_stores(specifications, report['model_manifest_sha256'])
    entries = [r for r in report['units'] if r['unit'] == unit]
    _require(len(entries) == 1, unit, 'unit is absent or ambiguous')
    _require(entries[0]['header'] == 'units/' + unit + '/header.json', unit, 'source header identity differs')
    path = store / entries[0]['header']
    _require(path.resolve() == path and path.is_relative_to(store), unit, 'unsafe unit header')
    raw_header = path.read_bytes()
    _require(len(raw_header) == entries[0]['header_bytes'] and sha256(raw_header).hexdigest() == entries[0]['header_sha256'], unit, 'unit header receipt differs')
    header = json.loads(raw_header)
    _require((header['schema'], header['schema_version'], header['authority'], header['unit']) ==
        ('scar.source-template-links', 1, 'SOURCE_TEMPLATE_INTERFACES_ONLY', unit), unit, 'unsupported source graph header')
    _require(all(unit in p.rows and header['input'] == p.rows[unit]['input'] for p in parents), unit, 'graph input differs from its source material')
    profile = decode(P.SourceProductionProfile, header['profile'])
    _require(all(profile == p.profile for p in parents), unit, 'graph state/exception profile differs from its source material')
    templates = _read_graph_table(path, header['templates'], T.SourceTemplateNode)
    links = _read_graph_table(path, header['links'], T.SourceTemplateLink)
    _require(len(templates) == entries[0]['templates'] and len(links) == entries[0]['links']
        and entries[0]['compressed_bytes'] == header['templates']['bytes'] + header['links']['bytes'], unit, 'unit index counts differ from tables')
    keys = {n.key for n in templates}; sites = {(e.caller, e.step) for e in links}
    _require(len(keys) == len(templates) and len(sites) == len(links), unit, 'duplicate template or child-entry site')
    _require(all(e.caller in keys and e.callee in keys and all(v.index >= 0 for v in e.arguments) for e in links), unit, 'dangling template edge or negative argument ordinal')
    _require(all(n.origin.line > 0 and len(n.origin.plan_sha256) == 64
        and all(c in '0123456789abcdef' for c in n.origin.plan_sha256) for n in templates), unit, 'invalid original body coordinates')
    _require((store / 'result.json').read_bytes() == report_bytes
        and all(p.unchanged() and p.generator_pins == _implementation() for p in parents), store, 'graph or parent snapshots changed during reading')
    return T.SourceTemplateGraph(unit, decode(P.ProductionInput, header['input']),
        profile, templates, links)


def _verify_template_unit(task):
    store, unit, reader_pin = task
    _require(sha256(Path(__file__).read_bytes()).hexdigest() == reader_pin, unit, 'worker reader version differs')
    graph = read_template_graph(store, unit)
    return dict(unit=unit, templates=len(graph.templates), links=len(graph.links))


def verify_template_store(store, *, jobs=1):
    """Read every stored graph; return compact receipts, never centralized graphs.

    This checks wire storage and template-reference closure. It does not
    regenerate source rules or prove native effects or cleanup semantics.
    """
    started = time.monotonic(); store = Path(store).absolute()
    _require(type(jobs) is int and 1 <= jobs <= 32, 'jobs', 'expected 1 through 32 source workers')
    _require(store.resolve() == store, store, 'store path must be canonical')
    raw = (store / 'result.json').read_bytes(); report = json.loads(raw)
    reader_pin = sha256(Path(__file__).read_bytes()).hexdigest()
    tasks = [(str(store), row['unit'], reader_pin) for row in report['units']]
    _require(bool(tasks), store, 'no stored source graphs')
    if jobs == 1:
        rows = [_verify_template_unit(task) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context('spawn')) as pool:
            rows = list(pool.map(_verify_template_unit, tasks))
    templates = sum(r['templates'] for r in rows); links = sum(r['links'] for r in rows)
    _require(len(rows) == report['selected_sources'] and templates == report['templates']
        and links == report['links'] and sum(r['compressed_bytes'] for r in report['units']) == report['compressed_bytes'],
        store, 'global graph counts differ from stored source units')
    _require((store / 'result.json').read_bytes() == raw
        and sha256(Path(__file__).read_bytes()).hexdigest() == reader_pin, store, 'store or reader changed during verification')
    return dict(schema='scar.source-template-store-verification', schema_version=1, status='STORED_INTERFACES_VERIFIED',
        graph_result_sha256=sha256(raw).hexdigest(), reader_sha256=reader_pin,
        link_types_sha256=report['link_types_sha256'], model_manifest_sha256=report['model_manifest_sha256'],
        selected_sources=len(rows), templates=templates, links=links, compressed_bytes=report['compressed_bytes'],
        units=rows, jobs=jobs, seconds=time.monotonic()-started, parent_catalogs_current=True,
        table_receipts_checked=True, stored_template_references_closed=True,
        source_rules_replayed=False, canonical_graph_generated=False, effects_proven=False,
        first_stage_complete=False, target_executed=False, transformation_authorized=False)


def read_template_body(store, unit, key, *, max_visits=1_000_000):
    """Expand one graph node to its original typed source recipe."""
    _require(type(key) is T.SourceTemplateKey, unit, 'invalid template key')
    store = Path(store).absolute()
    graph = read_template_graph(store, unit)
    found = [n for n in graph.templates if n.key == key]
    _require(len(found) == 1, key, 'template is absent or ambiguous')
    node = found[0]
    report = json.loads((store / 'result.json').read_bytes())
    parents = [p for p in report['parents'] if p['domain'] == node.origin.domain.value]
    _require(len(parents) == 1, unit, 'missing original material domain')
    parent = parents[0]; material = _Store(parent['domain'], parent['materials'], parent['verification'], report['model_manifest_sha256'])
    _require(material.receipt == parent, unit, 'parent proof changed since interface linking')
    # _Store.records exhausts and hashes the whole original fragment before
    # the result is returned, including rows after the selected one.
    selected = None
    basis = material.basis[unit]
    for domain, line, document in material.records(dict(key=unit, **{k:v for k,v in basis.items() if k!='unit'})):
        if line == node.origin.line:
            _require(_digest(document) == node.origin.plan_sha256, key, 'original recipe body differs')
            selected = read_production_plan(document, max_visits=max_visits)
    _require(selected is not None and selected.source == P.ProductionOccurrence(key.occurrence)
        and selected.purpose is key.purpose and selected.root == node.root
        and selected.input == graph.input and selected.profile == graph.profile,
        key, 'original recipe identity/input/profile differs')
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True); parser.add_argument('--out', required=True)
    parser.add_argument('--materials', nargs=3, action='append', required=True, metavar=('DOMAIN', 'COLLECTION', 'VERIFICATION'))
    parser.add_argument('--source', action='append', default=[])
    parser.add_argument('--max-visits', type=int, default=1_000_000)
    parser.add_argument('--jobs', type=int, default=1)
    args = parser.parse_args()
    result = link_source_templates(args.model, args.out, args.materials, args.source, max_visits=args.max_visits, jobs=args.jobs)
    print(json.dumps({k:result[k] for k in ('status','selected_sources','templates','links','compressed_bytes')}, indent=2))


if __name__ == '__main__':
    main()
