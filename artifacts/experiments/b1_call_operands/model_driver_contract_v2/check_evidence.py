"""Verify this design archive without running a probe or product workload."""
import hashlib
import json
from pathlib import Path


BASE = Path(__file__).resolve().parent


def read(name):
    return json.loads((BASE / name).read_text())


def main():
    manifest = read('manifest.json')
    for name, receipt in manifest['files'].items():
        path = (BASE / name).resolve()
        assert BASE in path.parents, name
        raw = path.read_bytes()
        assert len(raw) == receipt['bytes'], name
        assert hashlib.sha256(raw).hexdigest() == receipt['sha256'], name
    acceptance = read('acceptance.json')
    assert acceptance['status'] == 'D1_CONNECTION_DESIGN_ACCEPTED'
    assert acceptance['d1_product_implemented'] is False
    assert acceptance['d2_fields_frozen'] is False
    assert acceptance['full_d0_complete'] is False
    assert acceptance['full_first_stage_complete'] is False
    assert acceptance['transformation_verified'] is False
    assert acceptance['lewm_speedup_measured'] is False
    snapshot = read('source-snapshot.json')
    assert snapshot['source_sha256'] == acceptance['source_sha256']
    assert snapshot['source_file_count'] == 406
    assert len(snapshot['fixture_sha256']) == 26
    probe = read('review/corridor-probe.json')
    assert probe['status'] == 'PASS' and len(probe['cases']) == 6
    assert all(case['status'] == 'PASS' for case in probe['cases'])
    assert probe['body_drive_implemented'] is probe['runtime_gate_verified'] is False
    for attempt, code in (('initial', 1), ('corrected', 0)):
        command = read(f'review/corridor-probe.{attempt}-command.json')
        assert command['returncode'] == code
        script = 'review/corridor-probe.initial.py' if attempt == 'initial' else 'review/corridor-probe.py'
        assert command['script_sha256'] == hashlib.sha256((BASE / script).read_bytes()).hexdigest()
    assert 'AttributeError' in (BASE / 'review/corridor-probe.initial.log').read_text()
    contract = (BASE / 'review/reviewed-contract.md').read_bytes()
    assert hashlib.sha256(contract).hexdigest() == acceptance['reviewed_contract_sha256']
    for row in acceptance['final_reviews']:
        assert (BASE / row['report']).is_file()
        assert row['status'] == 'ACCEPT_D1_CONNECTION_DESIGN'
    protected = read('protected-checkouts.json')['checkouts']
    assert all(not row['worktree_status'] for row in protected.values())
    print(json.dumps({'status': 'PASS', 'files': len(manifest['files']),
        'design_checks': 6, 'source_unchanged': True,
        'd1_product_implemented': False, 'd2_fields_frozen': False}))


if __name__ == '__main__':
    main()
