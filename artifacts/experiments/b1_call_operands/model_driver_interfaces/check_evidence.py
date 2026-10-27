"""Check this bounded review/query archive without rerunning experiments."""
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
    component, full = read('component/final.json'), read('full/report.json')
    before, after = read('full/source.before.json'), read('full/source.after.json')
    assert acceptance['status'] == component['status'] == full['status'] == 'PASS'
    assert acceptance['driver_field_review'] == 'REVISE'
    assert before == after and not before['worktree_status']
    assert before['revision'] == full['revision_before'] == full['revision_after'] == acceptance['implementation_revision']
    assert acceptance['source_sha256'] == component['source_sha256'] == before['source_sha256']
    assert component['tested_files'] == before['files']
    assert len(before['files']) == acceptance['source_file_count'] == 406
    assert component['source_unchanged_during_test'] and full['source_unchanged_during_test']
    cases = {(case['class'], case['name']) for row in component['criteria']
             for evidence in row['evidence'] for case in evidence['cases']}
    assert len(component['criteria']) == 9 and all(row['status'] == 'PASS' for row in component['criteria'])
    assert len(cases) == acceptance['component_checks'] == 517
    added = component['criteria'][0]
    assert added['id'] == 'first-outcome-frontier-canonical-payload-and-exact-body-ingress'
    assert sum(len(e['cases']) for e in added['evidence']) == acceptance['new_query_checks'] == 7
    assert component['returncode'] == full['returncode'] == 0
    assert full['counts'] == acceptance['full_counts']
    assert not any(full['counts'][k] for k in ('failed', 'error', 'skipped'))
    assert len(before['fixture_sha256']) == acceptance['fixture_file_count']
    assert full['basetemp_cleanup'].startswith('removed exclusively owned')
    assert not Path(full['basetemp']).exists()
    witness = read('review/lifecycle-witness.json')['attempts']
    assert len(witness) == 1 and witness[0]['passed'] == 8 and witness[0]['failed'] == 0
    assert witness[0]['exit_code'] == witness[0]['torch_imported'] == witness[0]['scar_imported'] == 0
    probe = read('review/body-outcome-probe.json')
    assert probe['status'] == 'PASS' and len(probe['cases']) == 9
    assert all(case['status'] == 'PASS' for case in probe['cases'])
    assert probe['cases'][-1]['scope'].startswith('Signature-only')
    assert all(acceptance[name] is False for name in (
        'full_first_stage_complete', 'full_c2_complete', 'driver_implemented',
        'source_recovery_verified', 'runtime_resumption_verified',
        'transformation_verified', 'lewm_speedup_measured'))
    print(json.dumps({'status': 'PASS', 'files': len(manifest['files']),
        'component_checks': len(cases), 'new_query_checks': 7, 'full_counts': full['counts'],
        'driver_field_review': 'REVISE', 'source_unchanged': True}))


if __name__ == '__main__':
    main()
