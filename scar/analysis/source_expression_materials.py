"""Stream per-source rule recipes and explicit frontiers; never run targets."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
import gzip
from hashlib import sha256
import io
import json
import multiprocessing
import os
from pathlib import Path
import time

from scar.analysis.frontend_bindings import read_frontend_bindings
from scar.analysis.source_context_view import SourceContextView
from scar.analysis.source_expression_rules import SourceExpressionRules, SourceRuleError
from scar.analysis.source_statement_rules import SourceStatementRules
from scar.analysis.source_productions import ProductionSourceIndex
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir, _sync_directory
from scar.analysis.source_store import read_source_prerequisites
from scar.analysis.static_query import _Fragments
from scar.ir.program import source_productions as P
from scar.ir.program.ids import LocationID
from scar.ir.program.model import ValueKind, ValueType
from scar.ir.program.protocol_signatures import ExceptionABI
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.record_codec import decode, encode


_PARENTS = ('source_roles', 'source_contexts', 'source_declarations', 'source_bindings',
            'source_symbols', 'compiler_topology', 'compiler_symbols')
_FRONTIERS = {'RULE_FRONTIER', 'PURPOSE_FRONTIER', 'BINDING_INTERFACE_FRONTIER', 'SUSPENSION_CONTEXT_FRONTIER',
              'STATEMENT_CONTEXT_FRONTIER'}
_WORLD = ValueType(ValueKind.STATE, location=LocationID('source-python-world'))


def _json(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False) + '\n').encode('ascii')


def _implementation():
    package = Path(__file__).resolve().parents[1]
    names = ('analysis/source_expression_materials.py', 'analysis/source_expression_rules.py',
        'analysis/source_display_rules.py', 'analysis/source_string_rules.py',
        'analysis/source_comprehension_rules.py',
        'analysis/source_suspension_rules.py',
        'analysis/source_delegation_rules.py', 'ir/program/delegation_signatures.py',
        'analysis/source_statement_interfaces.py',
        'analysis/source_callable_rules.py', 'analysis/source_deferred_interfaces.py',
        'analysis/source_statement_rules.py', 'analysis/source_statement_atoms.py', 'analysis/source_statement_imports.py',
        'analysis/source_statement_functions.py',
        'analysis/source_definition_interfaces.py', 'analysis/source_statement_definitions.py',
        'analysis/source_statement_contexts.py',
        'analysis/source_statement_exceptions.py',
        'analysis/source_type_parameter_interfaces.py', 'analysis/source_type_parameter_rules.py',
        'analysis/source_productions.py', 'analysis/program_types.py',
        'ir/program/source_productions.py', 'ir/record_codec.py')
    return {name: sha256((package / name).read_bytes()).hexdigest() for name in names}


def _basis(unit):
    key = unit['key']
    if type(key) is not str or not key or Path(key).name != key or key in ('.', '..'):
        raise ValueError('source unit identity must be one safe path component')
    names = ('source', 'source_bytes', 'source_tokens', 'source_syntax', *_PARENTS)
    return dict(unit=unit['key'], path=unit['path'], namespace_root=unit['namespace_root'],
                artifacts={name: unit['artifacts'][name] for name in names})


def _unit(task):
    model, out, unit, prior, materials, limits, pins, keep_catalog, domain = task
    started = time.monotonic()
    if _implementation() != pins:
        raise ValueError('source rule implementation changed between parent and worker')
    reader = _Fragments(Path(model))
    f0, f1, f2 = read_source_prerequisites(reader, unit, limits['nodes'], limits['tokens'])
    if f0['namespace_root'] != unit['namespace_root']:
        raise ValueError('source unit namespace differs from its original F0')
    frontend = read_frontend_bindings(f0, f1, f2, *(reader.read(unit['artifacts'][name]) for name in _PARENTS))
    syntax = decode(SourceSyntaxMaterial, f2)
    contexts = SourceContextView(syntax, frontend.roles, frontend.contexts)
    rules = (SourceExpressionRules if domain == 'expressions' else SourceStatementRules)(ProductionSourceIndex(f0, contexts, frontend),
        world=_WORLD, exception_abi=ExceptionABI.EXCEPTION_WORLD)
    catalog = rules.catalog()
    categories = {row.name: row.bases for row in syntax.profile.ast_schema if not row.abstract}
    parent_seconds = time.monotonic() - started
    relative = 'units/' + unit['key'] + '/' + domain + '.jsonl.gz'
    digest, decoded_bytes = sha256(), 0
    built, frontier, child_obligations, descriptors, suppressed = (Counter() for _ in range(5))
    expressions, parent_expressions = 0, 0
    stream_path = Path(out) / relative
    with ExitStack() as stack:
        if prior is None:
            _durable_mkdir(stream_path.parent)
            destination = stack.enter_context(stream_path.open('xb'))
            stream = stack.enter_context(gzip.GzipFile(filename='', mode='wb', fileobj=destination, compresslevel=3, mtime=0))
        else:
            descriptor = prior['artifact']
            path = Path(materials) / relative
            if descriptor['path'] != relative or path.resolve() != path:
                raise ValueError('source expression shard has an unsafe identity/path')
            payload = path.read_bytes()
            if len(payload) != descriptor['bytes'] or sha256(payload).hexdigest() != descriptor['sha256']:
                raise ValueError('source expression compressed receipt changed')
            stream = stack.enter_context(gzip.GzipFile(fileobj=io.BytesIO(payload), mode='rb'))
        for occurrence, node in enumerate(syntax.nodes):
            is_expression = ('expr' if domain == 'expressions' else 'stmt') in categories[node.constructor]
            owner = rules.descriptor_owner(occurrence)
            if not is_expression and owner is None:
                continue
            expressions += is_expression
            purpose = P.ProductionPurpose.VALUE if domain == 'expressions' else P.ProductionPurpose.STATEMENT
            if node.constructor in ('Name', 'Attribute', 'Subscript', 'List', 'Tuple'):
                purpose = {'Load': P.ProductionPurpose.VALUE, 'Store': P.ProductionPurpose.STORE,
                           'Del': P.ProductionPurpose.DELETE}[rules.source.roles.context(occurrence)]
            row = dict(occurrence=occurrence, constructor=node.constructor, purpose=purpose.value)
            if owner is not None:
                row.update(status='PARENT_SOURCE_DESCRIPTOR', purpose=P.ProductionPurpose.DESCRIPTOR.value,
                    owner=encode(owner), fields=[encode(P.SlotRef(occurrence, 'FIELD', i)) for i in range(len(node.fields))])
                descriptors[node.constructor] += 1
                parent_expressions += is_expression
            elif contexts.material.regions[contexts.entry_context(occurrence).region].eligibility == 'SUPPRESSED':
                context = contexts.entry_context(occurrence)
                region = contexts.material.regions[context.region]
                row.update(status='SOURCE_NOT_SCHEDULED', context=encode(context),
                    suppression=dict(reason=region.suppression_reason, origin=encode(region.suppression_origin)))
                suppressed[node.constructor] += 1
            else:
                try:
                    plan = rules.build(occurrence, purpose, max_steps=limits['steps'], max_regions=limits['regions'])
                    row.update(status='LOCAL_SOURCE_RULE', plan=encode(plan, record_tags=P.PRODUCTION_RECORD_TAGS))
                    built[node.constructor] += 1
                    for step in plan.steps:
                        if type(step.instruction) is P.EvaluateChild:
                            selected = rules.source.roles.locate(step.instruction.field)[1]
                            child_obligations[syntax.nodes[selected.reference].constructor] += 1
                        elif type(step.instruction) is P.PublishAnnotation and step.instruction.publication is P.AnnotationPublicationKind.DEFERRED:
                            child_obligations['ANNOTATION_REQUEST'] += 1
                        elif type(step.instruction) is P.BuildFunctionAnnotations:
                            child_obligations['FUNCTION_ANNOTATION_REQUEST'] += 1
                        elif type(step.instruction) is P.BuildLazyExpression:
                            field=rules.source.roles.locate(step.instruction.expression.source)[0].name
                            owner=syntax.nodes[step.instruction.expression.source.occurrence].constructor
                            child_obligations['TYPE_ALIAS_VALUE_REQUEST' if owner=='TypeAlias' else 'TYPE_PARAMETER_'+field.upper()+'_REQUEST'] += 1
                except SourceRuleError as error:
                    if error.code not in _FRONTIERS:
                        raise
                    row.update(status='RULE_FRONTIER', error=dict(code=error.code, path=error.path, detail=error.detail))
                    frontier[node.constructor + ':' + error.code] += 1
            raw = _json(row)
            digest.update(raw)
            decoded_bytes += len(raw)
            if prior is None:
                stream.write(raw)
            elif stream.readline(len(raw) + 1) != raw:
                raise ValueError('stored source rule/frontier differs from fresh original F2/F3 replay')
        if prior is not None and stream.read(1):
            raise ValueError('extra source expression records after the original occurrence domain')
    if expressions != sum(built.values()) + sum(frontier.values()) + sum(suppressed.values()) + parent_expressions:
        raise ValueError('expression dispositions do not partition the original expression domain')
    if prior is None:
        with stream_path.open('rb') as stream:
            os.fsync(stream.fileno())
        _sync_directory(stream_path.parent)
        payload = stream_path.read_bytes()
        descriptor = dict(path=relative, bytes=len(payload), sha256=sha256(payload).hexdigest(),
            decoded_bytes=decoded_bytes, decoded_sha256=digest.hexdigest())
    elif descriptor['decoded_bytes'] != decoded_bytes or descriptor['decoded_sha256'] != digest.hexdigest():
        raise ValueError('decoded source expression receipt changed')
    result = dict(unit=unit['key'], path=unit['path'], input=encode(rules.source.input), artifact=descriptor,
        built=dict(sorted(built.items())), frontiers=dict(sorted(frontier.items())),
        parent_descriptors=dict(sorted(descriptors.items())), **{domain: expressions},
        suppressed_sources=dict(sorted(suppressed.items())), parent_owned_expressions=parent_expressions,
        child_interface_obligations=dict(sorted(child_obligations.items())),
        parent_seconds=parent_seconds, seconds=time.monotonic()-started,
        catalog_sha256=sha256(_json(catalog)).hexdigest())
    if keep_catalog:
        result['_catalog'] = catalog
    return result


def collect_source_rules(model, out, *, domain, sources=(), materials=None, jobs=1,
                               max_nodes=1_000_000, max_tokens=2_000_000,
                               max_steps=100_000, max_regions=100_000):
    if type(domain) is not str or domain not in ('expressions', 'statements'):
        raise ValueError('expected the expression or statement source-rule domain')
    schema = 'scar.source-' + ('expression' if domain == 'expressions' else 'statement') + '-materials'
    limits = dict(nodes=max_nodes, tokens=max_tokens, steps=max_steps, regions=max_regions)
    if type(jobs) is not int or not 1 <= jobs <= 32 or any(type(v) is not int or v < 0 for v in limits.values()):
        raise ValueError('invalid source rule jobs/budgets')
    root, out = Path(model).absolute(), Path(out).absolute()
    if root.resolve() != root or out.resolve() != out or out.exists() or out.is_relative_to(root) or root.is_relative_to(out):
        raise ValueError('source rules require a canonical model and fresh independent output')
    manifest_bytes = (root / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get('schema') != 'scar.static-program' or manifest.get('schema_version') != 1:
        raise ValueError('expected an original static model')
    selected = {str(Path(p).absolute()) for p in sources}
    units = sorted((u for u in manifest['units'] if not selected or u['path'] in selected), key=lambda u: u['key'])
    if not units or selected and selected != {u['path'] for u in units} or len({u['key'] for u in units}) != len(units):
        raise ValueError('source selection must identify nonempty original source units exactly')
    basis, pins, prior, store, store_bytes = [_basis(u) for u in units], _implementation(), {}, None, None
    if materials is not None:
        store = Path(materials).absolute()
        if store.resolve() != store or out.is_relative_to(store) or store.is_relative_to(out):
            raise ValueError('fresh verification output must be independent of source materials')
        store_bytes = (store / 'result.json').read_bytes()
        previous = json.loads(store_bytes)
        if (previous.get('schema') != schema or previous.get('schema_version') != 2 or previous.get('domain') != domain
            or previous.get('implementation_sha256') != pins or previous.get('input_basis') != basis
            or previous.get('limits') != limits):
            raise ValueError('previous rule material input/implementation/limit domain differs')
        prior = {r['unit']: r for r in previous['units']}
        if len(prior) != len(units) or set(prior) != {u['key'] for u in units}:
            raise ValueError('previous source expression units do not match the selected domain')
    _durable_mkdir(out)
    started = time.monotonic()
    tasks = [(str(root), str(out), u, prior.get(u['key']), None if store is None else str(store),
              limits, pins, i == 0, domain) for i, u in enumerate(units)]
    if jobs == 1:
        rows = [_unit(task) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context('spawn')) as pool:
            rows = list(pool.map(_unit, tasks))
    catalog = rows[0].pop('_catalog')
    catalog_bytes = _json(catalog)
    if any(r['catalog_sha256'] != sha256(catalog_bytes).hexdigest() for r in rows):
        raise ValueError('source workers do not share the original rule/schema domain')
    if store is not None and (store / 'catalog.json').read_bytes() != catalog_bytes:
        raise ValueError('source rule catalog changed')
    counts = dict(units=len(rows), local_recipes=sum(sum(r['built'].values()) for r in rows),
        rule_frontiers=sum(sum(r['frontiers'].values()) for r in rows),
        **{('expression_occurrences' if domain == 'expressions' else 'statement_occurrences'):sum(r[domain] for r in rows)},
        parent_descriptors=sum(sum(r['parent_descriptors'].values()) for r in rows),
        **{('parent_owned_expressions' if domain == 'expressions' else 'parent_owned_statements'):
            sum(r['parent_owned_expressions'] for r in rows)},
        suppressed_source_occurrences=sum(sum(r['suppressed_sources'].values()) for r in rows),
        child_interface_obligations=sum(sum(r['child_interface_obligations'].values()) for r in rows))
    if store is not None and previous['counts'] != counts:
        raise ValueError('stored source rule summary differs from fresh counters')
    if (root / 'manifest.json').read_bytes() != manifest_bytes or _implementation() != pins:
        raise ValueError('model or implementation changed while processing source rules')
    if store is not None and (store / 'result.json').read_bytes() != store_bytes:
        raise ValueError('source rule material manifest changed during fresh verification')
    report = dict(schema=schema, schema_version=2, domain=domain,
        status='LOCAL_RULES_WITH_FRONTIERS' if counts['rule_frontiers'] else 'LOCAL_RULES_VERIFIED',
        mode='FRESH_VERIFICATION' if store is not None else 'COLLECTION',
        input_basis=basis, implementation_sha256=pins, model_manifest_sha256=sha256(manifest_bytes).hexdigest(),
        selected_units=len(rows), model_units=len(manifest['units']), limits=limits, jobs=jobs,
        catalog_sha256=sha256(catalog_bytes).hexdigest(), counts=counts, units=rows,
        seconds=time.monotonic()-started, local_source_rules_replayed=True,
        child_interfaces_proven=False, effects_proven=False, state_parameter_origin_proven=False,
        canonical_graph_generated=False, whole_program_graph_complete=False,
        target_executed=False, transformation_authorized=False)
    _durable_bytes(out / 'catalog.json', catalog_bytes, replace=False)
    _durable_bytes(out / 'result.json', _json(report), replace=False)
    return report


def collect_source_expressions(model, out, **options):
    return collect_source_rules(model, out, domain='expressions', **options)


def collect_source_statements(model, out, **options):
    return collect_source_rules(model, out, domain='statements', **options)


def main(argv=None, *, domain='expressions'):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--source', action='append', default=[])
    parser.add_argument('--materials', help='freshly replay and compare a prior material store')
    parser.add_argument('--jobs', type=int, default=1)
    parser.add_argument('--max-nodes', type=int, default=1_000_000)
    parser.add_argument('--max-tokens', type=int, default=2_000_000)
    parser.add_argument('--max-steps', type=int, default=100_000)
    parser.add_argument('--max-regions', type=int, default=100_000)
    args = parser.parse_args(argv)
    report = collect_source_rules(args.model, args.out, domain=domain, sources=args.source, materials=args.materials,
        jobs=args.jobs, max_nodes=args.max_nodes, max_tokens=args.max_tokens,
        max_steps=args.max_steps, max_regions=args.max_regions)
    print(json.dumps({key: report[key] for key in ('status', 'mode', 'counts', 'seconds')}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
