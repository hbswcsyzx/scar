"""F0 source-byte acquisition, independent of parsing and program lowering."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from pathlib import Path
import argparse
import json
import multiprocessing
import os
import shutil
import tempfile
import time

from scar.analysis.source_bytes import (
    decoded_source_bytes, read_source_bytes, source_bytes_document,
)
from scar.analysis.static_sources import _Changed, _ByteBudget, _read_raw_source


def _stamps(root, descriptors):
    result = {}
    for descriptor in descriptors:
        info = (root / descriptor['path']).stat()
        result[descriptor['path']] = info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
    return result


def _remove_owned_previous(root, descriptors, expected):
    """Remove only known files; a concurrent unowned file must survive."""
    from scar.analysis.static_program import read_static_program
    try:
        read_static_program(root, verify=False)
        if _stamps(root, descriptors) != expected:
            return str(root)
    except (OSError, ValueError):
        return str(root)
    directories = {root}
    for relative in expected:
        parent = (root / relative).parent
        while parent != root:
            directories.add(parent)
            parent = parent.parent
    for relative in (*expected, 'manifest.json'):
        (root / relative).unlink()
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass
    return str(root) if root.exists() else None


def _source_envelope(unit, source):
    if (source.get('schema') != 'scar.static-source-text' or type(source.get('schema_version')) is not int
            or source['schema_version'] != 1
            or source.get('path') != unit['path'] or source.get('namespace_root') != unit['namespace_root']
            or source.get('raw_sha256') != unit['raw_sha256']
            or source.get('decoded_sha256') != unit['decoded_sha256']
            or source.get('encoding') != unit['encoding'] or type(source.get('text')) is not str
            or sha256(source['text'].encode('utf-8')).hexdigest() != unit['decoded_sha256']):
        raise ValueError('F0 original source envelope differs from its declared unit')
    sizes = [unit[name] for name in ('size_bytes', 'source_bytes') if name in unit]
    if (not sizes or any(type(n) is not int or n < 0 for n in sizes)
            or any(n != sizes[0] for n in sizes)):
        raise ValueError('F0 original unit has no consistent raw-byte count')
    return sizes[0]


def _matches(unit, source, document, size):
    raw = read_source_bytes(document)
    return (len(raw) == size and sha256(raw).hexdigest() == unit['raw_sha256']
        and document['path'] == unit['path'] and document['namespace_root'] == unit['namespace_root']
        and document['decoding']['status'] == 'DECODED'
        and document['decoding']['encoding'] == unit['encoding']
        and document['decoding']['decoded_utf8_sha256'] == unit['decoded_sha256']
        and decoded_source_bytes(document) == source['text'])


def _material(unit, read):
    source = read(unit['artifacts']['source'])
    size = _source_envelope(unit, source)
    if 'source_bytes' in unit['artifacts']:
        document = read(unit['artifacts']['source_bytes'])
        if not _matches(unit, source, document, size):
            raise ValueError('retained F0 bytes do not match the original unit/text')
        return document, 'RETAINED_RAW_BYTES', None
    current_issue = None
    try:
        raw = _read_raw_source(Path(unit['path']), size)
        document = source_bytes_document(raw, path=unit['path'], namespace_root=unit['namespace_root'])
        if _matches(unit, source, document, size):
            return document, 'FILESYSTEM_EXACT_VERSION', None
        current_issue = 'FILESYSTEM_VERSION_DIFFERS'
    except (OSError, _Changed, _ByteBudget) as error:
        current_issue = type(error).__name__ + ': ' + str(error)
    # This is a candidate, never an assumption that a codec is invertible.
    try:
        raw = source['text'].encode(unit['encoding'], errors='strict')
        if len(raw) == size and sha256(raw).hexdigest() == unit['raw_sha256']:
            document = source_bytes_document(raw, path=unit['path'], namespace_root=unit['namespace_root'])
            if _matches(unit, source, document, size):
                return document, 'RETAINED_TEXT_EXACT_RAW_DIGEST', current_issue
    except (UnicodeError, LookupError) as error:
        current_issue += '; restore: ' + type(error).__name__ + ': ' + str(error)
    return None, 'RAW_BYTES_UNAVAILABLE', current_issue


def _acquire_material(task):
    # A process owns its warning filters: codec interpretation must not race
    # with a sibling task's temporary warning policy on GIL builds.
    from scar.analysis.static_query import _Fragments
    root, unit = task
    document, origin, detail = _material(unit, _Fragments(root).read)
    return unit['key'], document, origin, detail


def archive_model_source_bytes(model, out, *, jobs=4, max_bytes=64 * 1024 * 1024):
    """Append F0 materials; preserve all original source and graph endpoints.

    The denominator is the manifest's declared source units, not undiscovered
    dependencies. Existing scan frontiers stay explicit. Readers close before
    atomic publication; no AST, symbol-table, compile, or target call is made.
    """
    from scar.analysis.static_program import _artifacts, _json, _write, read_static_program
    from scar.analysis.static_query import _Fragments
    if type(jobs) is not int or not 1 <= jobs <= 32 or type(max_bytes) is not int or max_bytes < 1:
        raise ValueError('F0 requires bounded positive jobs and byte budgets')
    started = time.monotonic()
    root, out = Path(model).absolute(), Path(out).absolute()
    if (root.resolve() != root or out.resolve() != out or out.is_relative_to(root)
            or out.exists() and (not out.is_dir() or any(out.iterdir()))):
        raise ValueError('F0 requires a canonical model and fresh external report directory')
    manifest = read_static_program(root, verify=False)
    original = (root / 'manifest.json').read_bytes()
    if json.loads(original) != manifest:
        raise ValueError('F0 model changed during initial read')
    prior_artifacts = tuple(_artifacts(manifest))
    prior_stamps = _stamps(root, prior_artifacts)
    original_units = {unit['key']: sha256(_json(unit)).hexdigest() for unit in manifest['units']}
    if len(original_units) != len(manifest['units']):
        raise ValueError('F0 source units require distinct original keys')
    sizes = [_source_envelope(unit, _Fragments(root).read(unit['artifacts']['source']))
             for unit in manifest['units']]
    total = sum(sizes)
    if total > max_bytes:
        report = {'schema': 'scar.source-material-gate', 'schema_version': 1, 'stage': 'F0',
            'input_scope': 'DECLARED_MODEL_SOURCE_UNITS', 'units': len(sizes),
            'raw_bytes': total, 'covered_units': 0, 'complete_for_declared_units': False,
            'frontier': [{'unit': unit['key'], 'kind': 'RAW_BYTE_BUDGET', 'bytes': size}
                         for unit, size in zip(manifest['units'], sizes)],
            'prior_manifest_sha256': sha256(original).hexdigest(),
            'published_manifest_sha256': sha256(original).hexdigest(),
            'max_bytes': max_bytes, 'parser_executed': False, 'lexer_executed': False,
            'target_executed': False, 'later_stages_verified': False,
            'whole_program_complete': False, 'seconds': time.monotonic() - started}
        if (root / 'manifest.json').read_bytes() != original:
            raise ValueError('F0 model changed during budget admission')
        out.mkdir(parents=True, exist_ok=True)
        with (out / 'result.json').open('xb') as stream:
            stream.write(_json(report))
        return report
    tasks = [(root, unit) for unit in manifest['units']]
    if jobs == 1:
        materials = list(map(_acquire_material, tasks))
    else:
        with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context('spawn')) as pool:
            materials = list(pool.map(_acquire_material, tasks))
    rows = [{'unit': key, 'status': 'PRESERVED' if doc is not None else 'MISSING',
             'origin': origin, 'detail': detail} for key, doc, origin, detail in materials]
    complete = all(doc is not None for _, doc, _, _ in materials)
    # Do not publish a partial byte inventory over the current graph model.
    report = {'schema': 'scar.source-material-gate', 'schema_version': 1, 'stage': 'F0',
        'input_scope': 'DECLARED_MODEL_SOURCE_UNITS', 'units': len(materials),
        'raw_bytes': total, 'covered_units': sum(doc is not None for _, doc, _, _ in materials),
        'complete_for_declared_units': complete, 'source_scan_remaining': manifest.get('remaining'),
        'source_scan_issues': manifest.get('source_issues'), 'results': rows,
        'prior_manifest_sha256': sha256(original).hexdigest(), 'target_executed': False,
        'parser_executed': False, 'lexer_executed': False, 'later_stages_verified': False,
        'whole_program_complete': False, 'jobs': jobs}
    temporary = None
    try:
        if ((root / 'manifest.json').read_bytes() != original
                or _stamps(root, prior_artifacts) != prior_stamps):
            raise ValueError('F0 model changed during acquisition')
        if complete:
            temporary = Path(tempfile.mkdtemp(prefix='.source-bytes-', dir=root.parent))
            shutil.copytree(root, temporary, dirs_exist_ok=True, copy_function=os.link)
            for unit, (key, document, _, _) in zip(manifest['units'], materials):
                if key != unit['key']:
                    raise ValueError('F0 material order changed')
                if 'source_bytes' not in unit['artifacts']:
                    unit['artifacts']['source_bytes'] = _write(temporary,
                        'units/' + key + '/source_bytes.json.gz', document)
                    original_unit = {**unit, 'artifacts': {name: item for name, item in unit['artifacts'].items()
                                                          if name != 'source_bytes'}}
                else:
                    original_unit = unit
                if sha256(_json(original_unit)).hexdigest() != original_units[key]:
                    raise ValueError('F0 changed a prior unit field or endpoint')
            manifest['source_materials'] = {'schema': 'scar.source-materials', 'schema_version': 1,
                'stage': 'F0', 'scope': 'DECLARED_MODEL_SOURCE_UNITS', 'units': len(materials),
                'raw_bytes': total, 'later_stages_verified': False, 'whole_program_complete': False}
            artifacts = tuple(_artifacts(manifest))
            manifest['storage'] = {'files': len({d['path'] for d in artifacts}),
                'compressed_bytes': sum(d['bytes'] for d in {d['path']: d for d in artifacts}.values())}
            (temporary / 'manifest.json').unlink()
            (temporary / 'manifest.json').write_bytes(_json(manifest))
            read_static_program(temporary, verify=False)
            read_static_program(root, verify=False)
            if ((root / 'manifest.json').read_bytes() != original
                    or _stamps(root, prior_artifacts) != prior_stamps):
                raise ValueError('F0 original model changed before publication')
            previous = Path(tempfile.mkdtemp(prefix='.source-bytes-replacing-', dir=root.parent))
            previous.rmdir()
            root.rename(previous)
            try:
                temporary.rename(root)
                temporary = None
            except BaseException:
                previous.rename(root)
                raise
            retained = _remove_owned_previous(previous, prior_artifacts, prior_stamps)
            if retained is not None:
                report['retained_previous_directory'] = retained
        report['published_manifest_sha256'] = sha256((root / 'manifest.json').read_bytes()).hexdigest()
        report['program_input_basis_unchanged'] = True
        report['seconds'] = time.monotonic() - started
        out.mkdir(parents=True, exist_ok=True)
        with (out / 'result.json').open('xb') as stream:
            stream.write(_json(report))
        return report
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)


def verify_model_source_bytes(model, out):
    """Freshly check all declared F0 artifacts; do not repair or run later layers."""
    from scar.analysis.static_program import _json, read_static_program
    from scar.analysis.static_query import _Fragments
    started = time.monotonic()
    root, out = Path(model).absolute(), Path(out).absolute()
    if (root.resolve() != root or out.resolve() != out or out.is_relative_to(root)
            or out.exists() and (not out.is_dir() or any(out.iterdir()))):
        raise ValueError('F0 verification requires a canonical model and fresh external report')
    manifest = read_static_program(root, verify=False)
    before = (root / 'manifest.json').read_bytes()
    if json.loads(before) != manifest:
        raise ValueError('F0 model changed during initial verification read')
    rows, total = [], 0
    reader = _Fragments(root)
    consumed = tuple(descriptor for unit in manifest['units'] for name, descriptor in unit['artifacts'].items()
                     if name in ('source', 'source_bytes'))
    stamps = _stamps(root, consumed)
    for unit in manifest['units']:
        try:
            source = reader.read(unit['artifacts']['source'])
            size = _source_envelope(unit, source)
            total += size
            if 'source_bytes' not in unit['artifacts']:
                raise ValueError('original raw bytes were not retained')
            if not _matches(unit, source, reader.read(unit['artifacts']['source_bytes']), size):
                raise ValueError('F0 original bytes/text/version mismatch')
            rows.append({'unit': unit['key'], 'status': 'VERIFIED'})
        except (OSError, ValueError, KeyError) as error:
            rows.append({'unit': unit['key'], 'status': 'INVALID',
                         'error': {'type': type(error).__name__, 'detail': str(error)}})
    if ((root / 'manifest.json').read_bytes() != before or _stamps(root, consumed) != stamps):
        raise ValueError('F0 source model changed during verification')
    report = {'schema': 'scar.source-material-verification', 'schema_version': 1, 'stage': 'F0',
        'input_scope': 'DECLARED_MODEL_SOURCE_UNITS', 'units': len(rows), 'raw_bytes': total,
        'verified_units': sum(row['status'] == 'VERIFIED' for row in rows),
        'complete_for_declared_units': all(row['status'] == 'VERIFIED' for row in rows),
        'source_scan_remaining': manifest.get('remaining'), 'source_scan_issues': manifest.get('source_issues'),
        'results': rows, 'manifest_sha256': sha256(before).hexdigest(),
        'manifest_unchanged': True, 'source_materials_unchanged': True,
        'parser_executed': False, 'lexer_executed': False, 'target_executed': False,
        'later_stages_verified': False, 'whole_program_complete': False,
        'seconds': time.monotonic() - started}
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'result.json').open('xb') as stream:
        stream.write(_json(report))
    return report


def main(argv=None):
    from scar.analysis.static_program import _json, _write
    parser = argparse.ArgumentParser(prog='scar source-bytes')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--model')
    group.add_argument('--file')
    parser.add_argument('--out', required=True)
    parser.add_argument('--namespace-root')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--max-bytes', type=int, default=64 * 1024 * 1024)
    parser.add_argument('--verify', action='store_true', help='fresh read-only F0 verification of a model')
    args = parser.parse_args(argv)
    if args.max_bytes < 1:
        parser.error('--max-bytes must be positive')
    if args.model:
        report = (verify_model_source_bytes(args.model, args.out) if args.verify else
                  archive_model_source_bytes(args.model, args.out, jobs=args.jobs, max_bytes=args.max_bytes))
        count = 'verified_units' if args.verify else 'covered_units'
        print(_json({k: report[k] for k in ('stage', 'units', count,
            'complete_for_declared_units', 'seconds', 'parser_executed', 'later_stages_verified')}).decode().strip())
        return 0 if report['complete_for_declared_units'] else 1
    if args.verify:
        parser.error('--verify requires --model')
    path, out = Path(args.file).absolute(), Path(args.out).absolute()
    namespace = str(Path(args.namespace_root).absolute()) if args.namespace_root else str(path.parent)
    if (path.resolve() != path or out.resolve() != out or path.is_relative_to(out)
            or out.exists() and (not out.is_dir() or any(out.iterdir()))):
        raise ValueError('F0 file capture requires canonical paths and a fresh output directory')
    try:
        raw = _read_raw_source(path, args.max_bytes)
    except (OSError, _ByteBudget, _Changed) as error:
        out.mkdir(parents=True, exist_ok=True)
        report = {'schema': 'scar.source-material-file', 'schema_version': 1, 'stage': 'F0',
            'path': str(path), 'artifact': None, 'material_complete': False,
            'error': {'stage': 'READ', 'type': type(error).__name__, 'detail': str(error)},
            'parser_executed': False, 'lexer_executed': False, 'target_executed': False,
            'later_stages_verified': False}
        with (out / 'result.json').open('xb') as stream:
            stream.write(_json(report))
        print(_json(report).decode().strip())
        return 1
    document = source_bytes_document(raw, path=str(path), namespace_root=namespace)
    out.mkdir(parents=True, exist_ok=True)
    descriptor = _write(out, 'source_bytes.json.gz', document)
    report = {'schema': 'scar.source-material-file', 'schema_version': 1, 'stage': 'F0',
        'artifact': descriptor, 'material_complete': True,
        'decoding_status': document['decoding']['status'],
        'parser_executed': False, 'lexer_executed': False, 'target_executed': False,
        'later_stages_verified': False}
    with (out / 'result.json').open('xb') as stream:
        stream.write(_json(report))
    print(_json(report).decode().strip())
    return 0


__all__ = ['archive_model_source_bytes', 'verify_model_source_bytes', 'main']
