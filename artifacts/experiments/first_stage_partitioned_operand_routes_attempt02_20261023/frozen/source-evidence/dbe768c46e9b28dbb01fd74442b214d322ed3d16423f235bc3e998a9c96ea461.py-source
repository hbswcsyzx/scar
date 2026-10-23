"""Archive producer/input receipts only; no SCAR import or model construction."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXPERIMENTS = HERE.parent
BASE = EXPERIMENTS / 'first_stage_partitioned_composition_bindings_20261023'
CAPTURE = EXPERIMENTS / 'first_stage_lewm_dispatch_20261023'
CACHE = EXPERIMENTS / 'first_stage_partitioned_operand_routes_20261023/result/code-witnesses'


def receipt(path):
    path = Path(path)
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
            size += len(block)
    return {'path': str(path.resolve()), 'sha256': digest.hexdigest(), 'bytes': size}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=('prepared', 'frozen'), required=True)
    phase = parser.parse_args().phase
    destination = HERE / phase
    destination.mkdir(exist_ok=False)
    files = sorted((ROOT / 'scar').rglob('*.py'))
    files += [HERE / name for name in ('prepare.py', 'run.py', 'run.sh')]
    rows = []
    for path in files:
        row = receipt(path)
        # Candidate hashes precede imports. Save only this change's six source
        # files/scripts here; the runner archives actual imported producers.
        if path.parent == HERE or path.name in ('code_witness.py', 'source_body_access.py',
                'call_edges.py', 'call_operands.py', 'call_operand_routes.py', 'callable_environment_import.py'):
            output = destination / 'source-evidence' / (row['sha256'] + '.py-source')
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, output)
            assert receipt(output)['sha256'] == row['sha256']
        rows.append(row)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    patch = subprocess.check_output(['git', 'diff', '--binary', '--', 'scar'], cwd=ROOT)
    (destination / 'implementation.patch').write_bytes(patch)
    inputs = [BASE / 'composition/index.json.gz', BASE / 'bindings/report.json',
              BASE / 'bindings/bindings.json', BASE / 'bindings/capture-coordinates.json',
              EXPERIMENTS / 'first_stage_full_inventory_restored_20261023/result/manifest.json',
              EXPERIMENTS / 'first_stage_source_context_20261022/result/source-layers/index.json']
    inputs += [path for path in sorted((CAPTURE / 'trace').iterdir())
               if path.name.startswith(('call-codes.', 'call-events.', 'call-meta.',
                    'call-operands.', 'call-operand-meta.', 'function-environments.', 'function-environment-meta.'))]
    cache_document = json.loads((CACHE / 'manifest.json').read_text())
    inputs.append(CACHE / 'manifest.json')
    inputs.append(CACHE.parent.parent / 'stop-confirmation.json')
    for row in list(cache_document['modules'].values()) + list(cache_document['sources'].values()):
        path = CACHE / row['artifact']['path']
        actual = receipt(path)
        assert (actual['sha256'], actual['bytes']) == (row['artifact']['sha256'], row['artifact']['bytes'])
        inputs.append(path)
    input_rows = [receipt(path) for path in inputs]
    source_report = json.loads((BASE / 'bindings/report.json').read_text())
    bindings_raw = (BASE / 'bindings/bindings.json').read_bytes()
    assert hashlib.sha256(bindings_raw).hexdigest() == source_report['bindings']['raw_sha256']
    assert len(bindings_raw) == source_report['bindings']['raw_bytes']
    digest, decoded_bytes = hashlib.sha256(), 0
    with gzip.open(BASE / 'composition/index.json.gz', 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            decoded_bytes += len(block)
            assert decoded_bytes <= 512_000_000
            digest.update(block)
    assert digest.hexdigest() == source_report['composition_canonical_sha256']
    canonical_refs = {}
    for row in json.loads(bindings_raw)['bindings']:
        if row['body'] is not None:
            body = row['body']
            key = json.dumps(body['namespace'], sort_keys=True)
            canonical_refs[key] = body
    cp_receipts = []
    for body in canonical_refs.values():
        original = body['canonical_locator']['artifact']
        actual = receipt(original['uri'])
        assert (actual['sha256'], actual['bytes']) == (original['physical_sha256'], original['physical_bytes'])
        cp_receipts.append(actual)
    document = {'phase': phase, 'revision': revision, 'modules': rows,
        'inputs': input_rows, 'original_body_artifacts': cp_receipts,
        'original_body_references': list(canonical_refs.values()),
        'source_run': source_report['run'], 'source_summary': source_report['summary'],
        'composition_decoded_bytes': decoded_bytes,
        'candidate_module_receipts': True, 'source_compiled': False, 'body_loaded': False,
        'target_executed': False, 'whole_program_established': False}
    (destination / 'producer.json').write_text(json.dumps(document, indent=2) + '\n')
    print(json.dumps({'phase': phase, 'modules': len(rows), 'inputs': len(input_rows),
                      'body_receipts': len(cp_receipts), 'revision': revision}))


if __name__ == '__main__':
    main()
