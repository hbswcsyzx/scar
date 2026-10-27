"""Archive supplied-IR continuation evidence; never starts tests/workloads."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET

from scripts.run_gate import fingerprint

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'model_pending_payloads'
BASE = 'f2b4781a9afc399352a534517bc2e26a8b12b794'
FINAL = HERE / 'final-focused'
MANIFEST = HERE / 'checkpoint.json'
DOCS = ('docs/M1_PACKET_CONTINUATION_PLAN.md', 'docs/M1_PACKET_CONTINUATION_PROGRESS.md',
        'docs/MODEL.md', 'docs/STATUS.md', 'docs/ROADMAP.md')


def git(*args, cwd=ROOT):
    return subprocess.check_output(['git', *args], cwd=cwd)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cases(path, *, passed=True):
    rows = list(ET.parse(path).iter('testcase'))
    assert rows
    if passed:
        assert all(not any(row.find(tag) is not None for tag in ('failure', 'error', 'skipped'))
                   for row in rows), path
    identities = {(row.get('classname'), row.get('name')) for row in rows}
    assert len(identities) == len(rows), path
    return identities


def main():
    design = json.loads((HERE / 'design-baseline.json').read_text())
    assert design['base_revision'] == BASE
    assert sha(ROOT / DOCS[0]) == design['plan_sha256']
    prior = json.loads((PRIOR / 'checkpoint.json').read_text())
    assert design['protected'] == prior['protected']
    assert design['obligation_groups'] == prior['obligation_groups']
    for state in prior['protected'].values():
        assert git('rev-parse', 'HEAD', cwd=state['path']).decode().strip() == state['head']
        assert git('status', '--porcelain=v1', cwd=state['path']).decode() == state['status']
    fixtures = {}
    with tarfile.open(fileobj=io.BytesIO(git('archive', BASE, 'tests/fixtures'))) as archive:
        for entry in archive.getmembers():
            if entry.isfile():
                content = archive.extractfile(entry).read()
                assert (ROOT / entry.name).read_bytes() == content, entry.name
                fixtures[entry.name] = hashlib.sha256(content).hexdigest()
    frozen = ('docs/M1_PROTOCOL_CONTRACT.md', 'docs/M1_PROTOCOL_CONNECTION_CONTRACT.md',
              'docs/M1_PENDING_PAYLOAD_PLAN.md', 'docs/M1_REMAINING_PROTOCOL_PLAN.md',
              'docs/M1_CLEANUP_INTERFACES.md', 'scar/ir/program/codec.py',
              'scar/ir/program/model.py')
    for name in frozen:
        assert (ROOT / name).read_bytes() == git('show', f'{BASE}:{name}'), name
    assert not git('diff', BASE, '--', 'scar/ir/execution').strip()
    assert (PRIOR / 'checkpoint.json').read_bytes() == git(
        'show', f'{BASE}:{PRIOR.relative_to(ROOT)}/checkpoint.json')
    for name, digest in prior['files'].items():
        if name.startswith('artifacts/'):
            assert sha(ROOT / name) == digest, name
    result = json.loads((FINAL / 'result.json').read_text())
    digest, sources = fingerprint()
    assert result['returncode'] == 0 and result['source_unchanged']
    assert digest == result['source_sha256_before'] == result['source_sha256_after']
    previous = cases(PRIOR / 'final-focused/junit.xml')
    current = cases(FINAL / 'junit.xml')
    assert len(previous) == 1018 and previous <= current, 'original obligation ID lost'
    attempts = {}
    for path in sorted(HERE.rglob('junit.xml')):
        identities = cases(path, passed=False)
        assert identities <= current, path
        attempts[str(path.relative_to(HERE))] = len(identities)
    new_files = {'tests.unit.test_program_packet_continuations',
                 'tests.unit.test_program_packet_continuation_edges'}
    added = {case for case in current if case[0] in new_files}
    assert added and not added & previous
    paths = [path for path in HERE.rglob('*') if path.is_file() and path != MANIFEST
             and '__pycache__' not in path.parts] + [ROOT / name for name in DOCS]
    record = {'status': 'PASS_WITH_SCOPE_WIP_ARCHIVE', 'base_revision': BASE,
        'source_sha256': digest, 'source_files': len(sources), 'focused_cases': len(current),
        'previous_focused_obligations_retained': len(previous),
        'unchanged_previous_case_identities': len(previous & current),
        'new_test_file_cases': len(added),
        'existing_test_assertion_migration': json.loads(
            (HERE / 'existing-test-migration.json').read_text()),
        'additional_preexisting_affected_cases': len(current - previous - added),
        'attempt_case_identities_retained': attempts, 'original_fixtures': fixtures,
        'wire_implementation_unchanged': True, 'protected': prior['protected'],
        'obligation_groups': prior['obligation_groups'], 'completed_obligation_groups': [],
        'p4_complete': False, 'm0_m2_complete': False, 'full_regression_on_this_source': False,
        'source_runtime_verified': False, 'transformation_authorized': False,
        'new_lewm_speedup': False, 'new_backend': False, 'tests_started_by_archive_check': 0,
        'files': {str(path.relative_to(ROOT)): sha(path) for path in sorted(paths)}}
    if sys.argv[1:] == ['--write']:
        assert not MANIFEST.exists()
        MANIFEST.write_text(json.dumps(record, indent=2) + '\n')
    else:
        assert sys.argv[1:] == ['--check']
        assert record == json.loads(MANIFEST.read_text())
    print(json.dumps({key: record[key] for key in ('status', 'source_sha256', 'source_files',
        'focused_cases', 'previous_focused_obligations_retained', 'new_test_file_cases',
        'p4_complete', 'm0_m2_complete', 'full_regression_on_this_source',
        'tests_started_by_archive_check')}, indent=2))


if __name__ == '__main__':
    main()
