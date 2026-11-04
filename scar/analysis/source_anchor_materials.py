"""Read-only, per-unit collection/fresh verification of source identity links."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from hashlib import sha256
import gzip
import json
import multiprocessing
from pathlib import Path
import time

from scar.analysis.source_atom_anchors import (
    SourceAnchorError, _digest, source_atom_anchors_document, read_source_atom_anchors,
)
from scar.analysis.source_syntax import read_source_syntax_material
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_store import read_source_prerequisites
from scar.analysis.static_query import _Fragments


_INPUTS = ('source', 'source_bytes', 'source_tokens', 'source_syntax', 'semantic')


def _json(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=True, allow_nan=False) + '\n').encode('ascii')


def _implementation():
    package = Path(__file__).resolve().parents[1]
    paths = ('analysis/source_anchor_materials.py', 'analysis/source_atom_anchors.py',
             'ir/program/source_anchors.py', 'ir/frontend_v2.py')
    return {name: sha256((package / name).read_bytes()).hexdigest() for name in paths}


def _basis(unit):
    return dict(unit=unit['key'], path=unit['path'], namespace_root=unit['namespace_root'],
                artifacts={name: unit['artifacts'].get(name) for name in _INPUTS})


def _write(root, relative, document):
    raw = _json(document)
    payload = gzip.compress(raw, compresslevel=3, mtime=0)
    path = root / relative
    _durable_mkdir(path.parent)
    _durable_bytes(path, payload, replace=False)
    return dict(path=relative, bytes=len(payload), sha256=sha256(payload).hexdigest(),
                decoded_bytes=len(raw), decoded_sha256=sha256(raw).hexdigest())


def _unit(task):
    model, out, unit, stored, materials, limits, implementation = task
    started = time.monotonic()
    if _implementation() != implementation:
        raise ValueError('source identity worker implementation differs from parent')
    reader = _Fragments(Path(model))
    f0, f1, f2 = read_source_prerequisites(reader, unit, limits['nodes'], limits['tokens'])
    if f0['namespace_root'] != unit['namespace_root']:
        raise ValueError('original F0 namespace differs from its source unit')
    if 'semantic' not in unit['artifacts']:
        # No old ID domain exists to join. This does not discard this source,
        # synthesize a legacy graph, or claim that the file cannot execute.
        syntax = read_source_syntax_material(f2, f0, f1)
        if syntax.status != 'PARSED':
            raise SourceAnchorError('UPSTREAM_NOT_PARSED', unit['path'], 'source-only F2 input is incomplete')
        source_input = dict(f0_sha256=_digest(f0), f2_sha256=_digest(f2),
                            namespace_root=unit['namespace_root'], semantic_artifact=None)
        if stored is not None and (stored['status'] != 'NO_SAVED_LEGACY_DOMAIN'
                                   or stored['source_input'] != source_input):
            raise ValueError('source-only disposition or original input changed')
        return dict(unit=unit['key'], path=unit['path'], status='NO_SAVED_LEGACY_DOMAIN',
                    source_input=source_input, occurrences=len(syntax.nodes), atoms=0,
                    seconds=time.monotonic()-started)
    semantic = reader.read(unit['artifacts']['semantic'])
    try:
        if stored is None:
            document = source_atom_anchors_document(f0, f1, f2, semantic,
                                                   namespace_root=unit['namespace_root'])
            # Namespace and original F2 digest participate even if two source
            # units happen to have identical bare legacy Atom IDs.
            key = sha256(_json(document['input'])).hexdigest()
            descriptor = _write(Path(out), 'units/' + key + '/source_anchors.json.gz', document)
            occurrences, atoms = document['occurrences'], len(document['anchors'])
        else:
            document = _Fragments(Path(materials)).read(stored['artifact'])
            view = read_source_atom_anchors(document, f0, f1, f2, semantic,
                                            namespace_root=unit['namespace_root'])
            descriptor = stored['artifact']
            occurrences, atoms = view.material.occurrences, len(view.material.anchors)
    except SourceAnchorError as error:
        return dict(unit=unit['key'], path=unit['path'], status='REJECTED_INPUT',
                    error=dict(code=error.code, path=error.path, detail=error.detail),
                    seconds=time.monotonic() - started)
    return dict(unit=unit['key'], path=unit['path'], status='VERIFIED_IDENTITY',
                occurrences=occurrences, atoms=atoms, artifact=descriptor,
                input=document['input'], seconds=time.monotonic() - started)


def collect_source_anchors(model, out, *, materials=None, jobs=1,
                           max_nodes=1_000_000, max_tokens=2_000_000):
    """Keep the canonical model unchanged and own only fresh external outputs.

    Fresh verification replays upstream F2 once per unit and rebuilds the
    identity table. It does not copy the material store or execute a target.
    """
    if (type(jobs) is not int or not 1 <= jobs <= 32
            or any(type(n) is not int or n < 0 for n in (max_nodes, max_tokens))):
        raise ValueError('jobs must be 1..32 and input budgets exact nonnegative integers')
    root, out = Path(model).absolute(), Path(out).absolute()
    if root.resolve() != root or out.resolve() != out or out.exists() or out.is_relative_to(root):
        raise ValueError('source identity collection requires a canonical model and fresh external output')
    manifest_bytes = (root / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get('schema') != 'scar.static-program' or manifest.get('schema_version') != 1:
        raise ValueError('expected an original static program manifest')
    units = sorted(manifest['units'], key=lambda unit: unit['key'])
    if len({unit['key'] for unit in units}) != len(units):
        raise ValueError('source unit keys must be unique')
    if any(any(name not in unit['artifacts'] for name in _INPUTS[:-1]) for unit in units):
        raise ValueError('declared source units require their original source/F0/F1/F2 materials')
    basis = [_basis(unit) for unit in units]
    implementation = _implementation()
    stored, store_root = {}, None
    store_bytes = None
    if materials is not None:
        store_root = Path(materials).absolute()
        if (store_root.resolve() != store_root or out.is_relative_to(store_root)
                or store_root.is_relative_to(out)):
            raise ValueError('verification output must be independent of the canonical material store')
        store_bytes = (store_root / 'result.json').read_bytes()
        prior = json.loads(store_bytes)
        if (prior.get('schema') != 'scar.source-anchor-materials' or prior.get('schema_version') != 1
                or prior.get('status') != 'VERIFIED_DECLARED_SOURCE_DOMAIN'
                or prior.get('input_basis') != basis or prior.get('implementation_sha256') != implementation):
            raise ValueError('source identity inputs or implementation differ from accepted material')
        stored = {row['unit']: row for row in prior['units']}
        if len(stored) != len(units) or set(stored) != {unit['key'] for unit in units}:
            raise ValueError('material unit domain does not equal the declared source domain')
        expected = {'result.json'} | {row['artifact']['path'] for row in stored.values() if 'artifact' in row}
        actual = set()
        for path in store_root.rglob('*'):
            if path.is_symlink():
                raise ValueError('source identity material may not contain symlinks')
            if path.is_file():
                actual.add(path.relative_to(store_root).as_posix())
        if actual != expected:
            raise ValueError('source identity store has missing or unowned files')
    _durable_mkdir(out)
    started = time.monotonic()
    tasks = [(str(root), str(out), unit, stored.get(unit['key']),
              str(store_root) if store_root else None, dict(nodes=max_nodes, tokens=max_tokens),
              implementation) for unit in units]
    rows = []
    if jobs == 1:
        results = map(_unit, tasks)
        for row in results:
            rows.append(row)
    else:
        with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context('spawn')) as pool:
            futures = [pool.submit(_unit, task) for task in tasks]
            for future in as_completed(futures):
                rows.append(future.result())
                if len(rows) % 50 == 0 or len(rows) == len(units):
                    print(json.dumps(dict(completed=len(rows), units=len(units),
                                          seconds=round(time.monotonic() - started, 2))), flush=True)
    if (root / 'manifest.json').read_bytes() != manifest_bytes or _implementation() != implementation:
        raise ValueError('model or implementation changed during source identity collection')
    if store_root and (store_root / 'result.json').read_bytes() != store_bytes:
        raise ValueError('source identity material manifest changed during verification')
    rows.sort(key=lambda row: row['unit'])
    identities = sum(row['status'] == 'VERIFIED_IDENTITY' for row in rows)
    source_only = sum(row['status'] == 'NO_SAVED_LEGACY_DOMAIN' for row in rows)
    failures = [row for row in rows if row['status'] not in ('VERIFIED_IDENTITY', 'NO_SAVED_LEGACY_DOMAIN')]
    report = dict(schema='scar.source-anchor-materials', schema_version=1,
        status='INCOMPLETE' if failures else 'VERIFIED_DECLARED_SOURCE_DOMAIN',
        mode='FRESH_VERIFICATION' if store_root else 'COLLECTION',
        model=str(root), model_manifest_sha256=sha256(manifest_bytes).hexdigest(),
        input_basis=basis, implementation_sha256=implementation,
        jobs=jobs, max_nodes=max_nodes, max_tokens=max_tokens,
        units=rows, counts=dict(units=len(rows), verified=identities, source_only=source_only, failed=len(failures),
            occurrences=sum(row.get('occurrences', 0) for row in rows),
            atoms=sum(row.get('atoms', 0) for row in rows)),
        seconds=time.monotonic()-started, target_executed=False, canonical_model_modified=False,
        authority='SOURCE_ATOM_IDENTITY_ONLY', source_productions_verified=False,
        dependency_discovery_complete=False, first_stage_complete=False)
    _durable_bytes(out / 'result.json', _json(report), replace=False)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--materials', help='freshly verify a complete previous material store')
    parser.add_argument('--jobs', type=int, default=1)
    parser.add_argument('--max-nodes', type=int, default=1_000_000)
    parser.add_argument('--max-tokens', type=int, default=2_000_000)
    args = parser.parse_args(argv)
    report = collect_source_anchors(args.model, args.out, materials=args.materials, jobs=args.jobs,
                                    max_nodes=args.max_nodes, max_tokens=args.max_tokens)
    print(json.dumps({key: report[key] for key in ('status', 'mode', 'counts', 'seconds')}, indent=2))
    return 0 if report['status'] == 'VERIFIED_DECLARED_SOURCE_DOMAIN' else 1


if __name__ == '__main__':
    raise SystemExit(main())
