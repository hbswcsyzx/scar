"""F3-A material transactions; compiler facts remain unjoined to AST scopes."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import json
import math
import multiprocessing
from pathlib import Path
import re
import time

from scar.analysis.source_materials import _stamps
from scar.analysis.source_stage import SourceStage
from scar.analysis.source_store import (
    REQUIRED_SOURCE_ARTIFACTS as _REQUIRED, source_input_basis as _basis,
    check_replay_limit as _upper, read_source_prerequisites as _prerequisites,
    material_store_members as _store_members, read_material_manifest,
    pin_material_store, check_material_store,
)
from scar.analysis.static_program import _json, _write
from scar.analysis.static_query import _Fragments


def _row(unit, descriptor, document, f1, f2):
    return {'unit': unit, 'artifact': descriptor, 'status': document['status'],
        'scopes': len(document['scopes']), 'symbols': sum(len(s['symbols']) for s in document['scopes']),
        'upstream_f1_status': f1['status'], 'upstream_f2_status': f2['status'],
        'max_scopes': document['max_scopes'], 'max_symbols': document['max_symbols'],
        'warning_count': len(document['warnings']), 'error': document['error'], 'frontiers': document['frontiers']}


def _symbol_unit(task):
    from scar.analysis.source_symbols import compiler_hash_context, read_source_symbols, source_symbols_document
    model, destination, unit, limits, existing_root, existing, standalone, expected_context = task
    if compiler_hash_context() != expected_context:
        raise ValueError('F3-A worker compiler hash context differs from its parent; '
            'start the analysis process with a fixed PYTHONHASHSEED before using multiple workers')
    reader = _Fragments(model)
    f0, f1, f2 = _prerequisites(reader, unit, limits['max_nodes'], limits['max_tokens'])
    prior = existing if existing_root is not None else unit['artifacts'].get('source_symbols')
    if prior is not None:
        document = _Fragments(existing_root or model).read(prior)
        for name in ('max_scopes', 'max_symbols'):
            _upper(document, name, limits[name], 'F3-A')
        read_source_symbols(document, f0, f1, f2)
        descriptor = prior
    elif destination is None:
        raise ValueError('F3-A source-symbol artifact is absent')
    else:
        document = source_symbols_document(f0, f1, f2,
            max_scopes=limits['max_scopes'], max_symbols=limits['max_symbols'])
        descriptor = None
    if destination is not None and (standalone or descriptor is None):
        relative = 'units/' + unit['key'] + '/source_symbols.json.gz'
        if (Path(destination) / relative).exists():
            raise FileExistsError('new F3-A material would overwrite an existing file')
        descriptor = _write(Path(destination), relative, document)
    return _row(unit['key'], descriptor, document, f1, f2)


def _covered(row):
    return (row['status'] not in ('RESOURCE_ERROR', 'BUDGET_STOPPED')
        and row['upstream_f1_status'] != 'BUDGET_STOPPED'
        and row['upstream_f2_status'] not in ('BUDGET_STOPPED', 'PARSER_RESOURCE_ERROR'))


def _report(rows, *, schema, limits, jobs):
    return {'schema': schema, 'schema_version': 1, 'stage': 'F3-A',
        'input_scope': 'DECLARED_MODEL_SOURCE_UNITS', 'units': len(rows),
        'covered_units': sum(_covered(row) for row in rows),
        'complete_for_declared_units': all(_covered(row) for row in rows),
        'all_declared_tables_captured': all(row['status'] == 'CAPTURED' for row in rows),
        'status_counts': dict(Counter(row['status'] for row in rows)),
        'scopes': sum(row['scopes'] for row in rows), 'symbols': sum(row['symbols'] for row in rows),
        'warning_count': sum(row['warning_count'] for row in rows), 'results': rows,
        'limits': limits, 'jobs': jobs, 'authority': 'PUBLIC_COMPILER_VIEW', 'ast_join': 'UNJOINED',
        'complete_lexical_scopes': False, 'target_executed': False, 'later_stages_verified': False,
        'whole_program_complete': False,
        'symtable_executed': any(row['status'] not in ('UPSTREAM_NOT_PARSED', 'UNSUPPORTED_SYMTABLE_MODE') for row in rows)}


def _check_summary(document, rows, *, file=False):
    """Validate a store's declared outcome from facts, without another replay."""
    limits, jobs = document.get('limits'), document.get('jobs')
    if (type(limits) is not dict or set(limits) != {'max_scopes', 'max_symbols', 'max_nodes', 'max_tokens'}
            or any(type(n) is not int or n < 0 for n in limits.values())
            or type(jobs) is not int or not 1 <= jobs <= 32):
        raise ValueError('invalid F3-A material limits/jobs summary')
    for row in rows:
        for name in ('max_scopes', 'max_symbols'):
            if type(row.get(name)) is not int or not 0 <= row[name] <= limits[name]:
                raise ValueError('F3-A row replay budget exceeds its material limits')
    expected = _report(rows, schema='scar.source-symbol-file' if file else 'scar.source-symbol-materials',
        limits=limits, jobs=jobs)
    if file:
        expected['input_scope'] = 'ONE_SOURCE_FILE'
    if _json({key: document.get(key) for key in expected}) != _json(expected):
        raise ValueError('F3-A material semantic summary differs from its scope facts')
    if not file:
        from scar.analysis.source_symbols import compiler_hash_context
        if (document.get('compiler_hash_context') != compiler_hash_context()
                or document.get('collect_only') is not True
                or document.get('canonical_model_published') is not False
                or document.get('manifest_unchanged') is not True):
            raise ValueError('F3-A material collection/hash-context summary differs')
        for name in ('observed_manifest_sha256', 'prior_manifest_sha256', 'published_manifest_sha256'):
            if type(document.get(name)) is not str or re.fullmatch(r'[0-9a-f]{64}', document[name]) is None:
                raise ValueError('invalid observed F3-A manifest digest')
    if 'seconds' in document and (type(document['seconds']) not in (int, float)
            or not math.isfinite(document['seconds']) or document['seconds'] < 0):
        raise ValueError('invalid observed F3-A duration')
    return limits


def _read_store(store, out):
    root, document, raw = read_material_manifest(store, out)
    if (document.get('schema') != 'scar.source-symbol-materials'
            or type(document.get('schema_version')) is not int or document['schema_version'] != 1
            or document.get('stage') != 'F3-A' or document.get('collect_only') is not True
            or document.get('authority') != 'PUBLIC_COMPILER_VIEW' or document.get('ast_join') != 'UNJOINED'
            or document.get('complete_lexical_scopes') is not False):
        raise ValueError('unsupported F3-A material store manifest')
    rows = document['results']
    _check_summary(document, rows)
    descriptors = [row['artifact'] for row in rows]
    pins = pin_material_store(root, descriptors, raw)
    return root, document, raw, pins


def model_source_symbols(model, out, *, jobs=4, max_scopes=100_000, max_symbols=1_000_000,
                         max_nodes=1_000_000, max_tokens=2_000_000, verify=False,
                         collect_only=False, materials=None):
    """Capture/verify F3-A; external stores bind source receipts, not model SHA."""
    limits = dict(max_scopes=max_scopes, max_symbols=max_symbols, max_nodes=max_nodes, max_tokens=max_tokens)
    if (type(jobs) is not int or not 1 <= jobs <= 32
            or any(type(n) is not int or n < 0 for n in limits.values())
            or type(verify) is not bool or type(collect_only) is not bool
            or verify and collect_only or materials is not None and not verify):
        raise ValueError('F3-A requires bounded budgets and distinct capture/verification modes')
    started = time.monotonic()
    from scar.analysis.source_symbols import compiler_hash_context
    expected_context = compiler_hash_context()
    readonly = verify or collect_only
    with SourceStage(model, out, artifact='source_symbols', verify=readonly,
            consumes=(*_REQUIRED, 'source_symbols')) as stage:
        basis = _basis(stage.manifest['units'])
        stored = store_root = store_pins = store_raw = None
        if materials is not None:
            store_root, stored, store_raw, store_pins = _read_store(materials, stage.out)
            if (_json(stored['basis']) != _json(basis)
                    or len(stored['results']) != len(stage.manifest['units'])):
                raise ValueError('F3-A material source basis differs from current prerequisite receipts')
            for row, unit in zip(stored['results'], stage.manifest['units']):
                if row['unit'] != unit['key'] or row['artifact']['path'] != stage.relative(unit):
                    raise ValueError('F3-A material row has a different original unit/path')
        replay_limits = ({name: min(limit, stored['limits'][name]) for name, limit in limits.items()}
                         if stored is not None else limits)
        destination = stage.out if collect_only else stage.staging
        if destination is not None:
            destination.mkdir(parents=True, exist_ok=True)
        tasks = [(stage.root, destination, unit, replay_limits, store_root,
            stored['results'][i]['artifact'] if stored is not None else None, collect_only, expected_context)
            for i, unit in enumerate(stage.manifest['units'])]
        if jobs == 1:
            rows = list(map(_symbol_unit, tasks))
        else:
            with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context('spawn')) as pool:
                rows = list(pool.map(_symbol_unit, tasks, chunksize=1))
        if stored is not None:
            _check_summary(stored, rows)
            check_material_store(store_root, [row['artifact'] for row in rows], store_raw, store_pins)
        schema = ('scar.source-symbol-material-verification' if stored is not None else
            'scar.source-symbol-verification' if verify else
            'scar.source-symbol-materials' if collect_only else 'scar.source-symbol-gate')
        report = _report(rows, schema=schema, limits=limits, jobs=jobs)
        report.update(collect_only=collect_only, canonical_model_published=False,
            observed_manifest_sha256=sha256(stage.original).hexdigest(), compiler_hash_context=expected_context)
        if collect_only:
            report['basis'] = basis
            _store_members(stage.out, [row['artifact'] for row in rows], result=False)
        elif not verify and report['complete_for_declared_units']:
            inventory = {key: report[key] for key in ('stage', 'units', 'scopes', 'symbols',
                'status_counts', 'authority', 'ast_join', 'complete_lexical_scopes', 'later_stages_verified', 'whole_program_complete')}
            inventory.update(schema='scar.source-symbol-inventory', schema_version=1,
                scope='DECLARED_MODEL_SOURCE_UNITS')
            stage.publish(rows, inventory)
            report['canonical_model_published'] = True
        if stored is not None:
            report.update(materials=str(store_root), materials_result_sha256=sha256(store_raw).hexdigest(),
                material_source_basis_unchanged=True)
        report['seconds'] = time.monotonic() - started
        return stage.finish(report)


def _file(model_file, out, args):
    from scar.analysis.source_symbols import read_source_symbols, source_symbols_document
    path, out = Path(model_file).absolute(), Path(out).absolute()
    if (out.resolve() != out or out.exists() and (not out.is_dir() or any(out.iterdir()))):
        raise ValueError('F3-A file mode requires a fresh canonical report directory')
    if args.verify:
        if args.materials is None:
            raise ValueError('F3-A file verification requires --materials')
        store = Path(args.materials).absolute()
        if store.resolve() != store or out.is_relative_to(store):
            raise ValueError('F3-A file verification needs an independent canonical store')
        if (store / 'result.json').is_symlink() or (store / 'result.json').resolve() != store / 'result.json':
            raise ValueError('F3-A file manifest cannot traverse a symlink')
        initial = _stamps(store, ({'path': 'result.json'},))
        raw = (store / 'result.json').read_bytes()
        if _stamps(store, ({'path': 'result.json'},)) != initial:
            raise ValueError('F3-A file manifest changed during read')
        header = json.loads(raw)
        if (header.get('schema') != 'scar.source-symbol-file' or header.get('stage') != 'F3-A'
                or type(header.get('schema_version')) is not int or header['schema_version'] != 1
                or header.get('authority') != 'PUBLIC_COMPILER_VIEW' or header.get('ast_join') != 'UNJOINED'
                or header.get('complete_lexical_scopes') is not False):
            raise ValueError('unsupported F3-A file material store')
        stored_limits = _check_summary(header, header['results'], file=True)
        descriptors = [header[name] for name in ('source_bytes', 'source_tokens', 'source_syntax', 'artifact')]
        _store_members(store, descriptors)
        pins = _stamps(store, (*descriptors, {'path': 'result.json'}))
    else:
        from scar.analysis.source_parsing import main as parse_main
        command = ['--file', str(path), '--out', str(out), '--max-bytes', str(args.max_bytes),
            '--max-nodes', str(args.max_nodes), '--max-tokens', str(args.max_tokens)]
        if args.namespace_root:
            command += ['--namespace-root', args.namespace_root]
        code = parse_main(command)
        store = out
        header = json.loads((out / 'result.json').read_bytes())
        if header.get('schema') != 'scar.source-syntax-file':
            return code
        header['source_syntax'] = header['artifact']
    reader = _Fragments(store)
    f0, f1, f2 = (reader.read(header[name]) for name in ('source_bytes', 'source_tokens', 'source_syntax'))
    if f0['path'] != str(path):
        raise ValueError('F3-A file label differs from its original F0 material')
    _upper(f1, 'max_tokens', min(args.max_tokens, stored_limits['max_tokens']) if args.verify else args.max_tokens, 'F1')
    _upper(f2, 'max_nodes', min(args.max_nodes, stored_limits['max_nodes']) if args.verify else args.max_nodes, 'F2')
    if args.verify:
        document = reader.read(header['artifact'])
        _upper(document, 'max_scopes', min(args.max_scopes, stored_limits['max_scopes']), 'F3-A')
        _upper(document, 'max_symbols', min(args.max_symbols, stored_limits['max_symbols']), 'F3-A')
        read_source_symbols(document, f0, f1, f2)
        if (_stamps(store, (*descriptors, {'path': 'result.json'})) != pins
                or (store / 'result.json').read_bytes() != raw):
            raise ValueError('F3-A file materials changed during verification')
        artifact = header['artifact']
    else:
        document = source_symbols_document(f0, f1, f2, max_scopes=args.max_scopes, max_symbols=args.max_symbols)
        if (out / 'source_symbols.json.gz').exists():
            raise FileExistsError('F3-A file material already exists')
        artifact = _write(out, 'source_symbols.json.gz', document)
    row = _row('file', artifact, document, f1, f2)
    if args.verify:
        _check_summary(header, [row], file=True)
    report = _report([row], schema='scar.source-symbol-file-verification' if args.verify else 'scar.source-symbol-file',
        limits={name: getattr(args, name) for name in ('max_nodes', 'max_tokens', 'max_scopes', 'max_symbols')}, jobs=1)
    report.update(input_scope='ONE_SOURCE_FILE', artifact=artifact,
        **{name: header[name] for name in ('source_bytes', 'source_tokens', 'source_syntax')})
    out.mkdir(parents=True, exist_ok=True)
    if args.verify:
        report['materials_result_sha256'] = sha256(raw).hexdigest()
        with (out / 'result.json').open('xb') as stream:
            stream.write(_json(report))
    else:
        (out / 'result.json').write_bytes(_json(report))
    print(_json(report).decode().strip())
    return 0 if report['complete_for_declared_units'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scar source-symbols')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--model')
    group.add_argument('--file')
    parser.add_argument('--out', required=True)
    parser.add_argument('--materials')
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--collect-only', action='store_true')
    parser.add_argument('--namespace-root')
    parser.add_argument('--jobs', type=int, default=4)
    for name, default in (('scopes', 100_000), ('symbols', 1_000_000), ('nodes', 1_000_000), ('tokens', 2_000_000), ('bytes', 64 * 1024 * 1024)):
        parser.add_argument('--max-' + name, type=int, default=default)
    args = parser.parse_args(argv)
    if (any(getattr(args, 'max_' + name) < 0 for name in ('scopes', 'symbols', 'nodes', 'tokens'))
            or not 1 <= args.jobs <= 32 or args.max_bytes < 1
            or args.materials and not args.verify or args.verify and args.collect_only):
        parser.error('invalid budgets or capture/verification options')
    if args.file:
        return _file(args.file, args.out, args)
    report = model_source_symbols(args.model, args.out, jobs=args.jobs, max_scopes=args.max_scopes,
        max_symbols=args.max_symbols, max_nodes=args.max_nodes, max_tokens=args.max_tokens,
        verify=args.verify, collect_only=args.collect_only, materials=args.materials)
    print(_json({key: report[key] for key in ('stage', 'units', 'scopes', 'symbols',
        'status_counts', 'complete_for_declared_units', 'canonical_model_published')}).decode().strip())
    return 0 if report['complete_for_declared_units'] else 1


__all__ = ['model_source_symbols', 'main']
