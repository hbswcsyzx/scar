"""Archive one original pending-payload checkpoint; performs no tests or source execution."""
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
BASE = 'cd25456357ec3e569d32ad246bd5890ef8fc628f'
PRIOR = HERE.parent / 'model_lookup_fallback'
MANIFEST = HERE / 'checkpoint.json'
FINAL = HERE / 'final-focused'
DOCS = ('docs/M1_PENDING_PAYLOAD_PLAN.md', 'docs/M1_PENDING_PAYLOAD_PROGRESS.md',
        'docs/MODEL.md', 'docs/STATUS.md', 'docs/ROADMAP.md')
NEW_GOLDENS = ()
MIGRATION = {}
ATTEMPT_MIGRATION = {
    ('tests.unit.test_program_pending_cleanup',
     'test_second_cut_cannot_present_the_old_pending_token_as_fresh_replacement'):
    ('tests.unit.test_program_pending_cleanup',
     'test_second_cut_cannot_replace_raise_with_the_old_return_pending_token'),
}


def git(*args, cwd=ROOT):
    return subprocess.run(['git', *args], cwd=cwd, capture_output=True, check=True).stdout


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cases(path, *, require_pass=True):
    rows = list(ET.parse(path).iter('testcase'))
    assert rows
    if require_pass:
        assert all(not any(row.find(tag) is not None for tag in ('failure', 'error', 'skipped'))
                   for row in rows)
    identities = {(row.get('classname'), row.get('name')) for row in rows}
    assert len(identities) == len(rows)
    return identities


def main():
    design = json.loads((HERE / 'design-baseline.json').read_text())
    assert design['base_revision'] == BASE
    assert sha(ROOT / 'docs/M1_PENDING_PAYLOAD_PLAN.md') == design['plan_sha256']
    prior_record = json.loads((PRIOR / 'checkpoint.json').read_text())
    assert design['protected'] == prior_record['protected']
    assert design['obligation_groups'] == prior_record['obligation_groups']
    for state in prior_record['protected'].values():
        assert git('rev-parse', 'HEAD', cwd=state['path']).decode().strip() == state['head']
        assert git('status', '--porcelain=v1', cwd=state['path']).decode() == state['status']
    original_fixtures = {}
    with tarfile.open(fileobj=io.BytesIO(git('archive', BASE, 'tests/fixtures'))) as archive:
        for member in archive.getmembers():
            if member.isfile():
                content = archive.extractfile(member).read()
                assert (ROOT / member.name).read_bytes() == content, member.name
                original_fixtures[member.name] = hashlib.sha256(content).hexdigest()
    for name in ('docs/M1_PROTOCOL_CONTRACT.md', 'docs/M1_PROTOCOL_CONNECTION_CONTRACT.md',
                 'docs/M1_PROTOCOL_FOLLOWUP_PLAN.md', 'docs/M1_CALL_RETURN_PLAN.md',
                 'docs/M1_CALL_COMPOSITION_PLAN.md', 'docs/M1_EXCEPTION_MATCH_PLAN.md',
                 'docs/M1_LOOKUP_FALLBACK_PLAN.md', 'docs/M1_CLEANUP_INTERFACES.md'):
        assert (ROOT / name).read_bytes() == git('show', f'{BASE}:{name}'), name
    assert (PRIOR / 'checkpoint.json').read_bytes() == git('show', f'{BASE}:{PRIOR.relative_to(ROOT)}/checkpoint.json')
    for name, digest in prior_record['files'].items():
        if name.startswith('artifacts/'):
            assert sha(ROOT / name) == digest, name
    for name in ('scar/ir/program/codec.py', 'scar/ir/program/model.py'):
        assert (ROOT / name).read_bytes() == git('show', f'{BASE}:{name}'), name
    assert not git('diff', BASE, '--', 'scar/ir/execution').strip()
    result = json.loads((FINAL / 'result.json').read_text())
    digest, sources = fingerprint()
    assert result['returncode'] == 0 and result['source_unchanged']
    assert digest == result['source_sha256_before'] == result['source_sha256_after']
    current = cases(FINAL / 'junit.xml')
    previous = cases(PRIOR / 'final-focused-repair/junit.xml')
    assert set(MIGRATION) <= previous and not set(MIGRATION) & current
    mapped = {MIGRATION.get(case, case) for case in previous}
    assert len(mapped) == len(previous) and mapped <= current
    assert previous - current == set(MIGRATION), 'unexplained old case loss'
    introduced = {case for case in current if case[0] in (
        'tests.unit.test_program_pending_payloads', 'tests.unit.test_program_pending_cleanup')}
    assert introduced and not introduced & previous
    assert not set(ATTEMPT_MIGRATION) & (previous | current)
    assert set(ATTEMPT_MIGRATION.values()) <= introduced
    attempts = {}
    observed_attempt_ids = set()
    for path in sorted(HERE.rglob('junit.xml')):
        identities = cases(path, require_pass=False)
        observed_attempt_ids.update(identities)
        retained = {ATTEMPT_MIGRATION.get(case, case) for case in identities}
        assert len(retained) == len(identities) and retained <= current, str(path)
        attempts[str(path.relative_to(HERE))] = len(identities)
    assert set(ATTEMPT_MIGRATION) <= observed_attempt_ids
    paths = [path for path in HERE.rglob('*') if path.is_file() and path != MANIFEST
             and '__pycache__' not in path.parts] + [ROOT / name for name in (*DOCS, *NEW_GOLDENS)]
    record = {'status': 'PASS_WITH_SCOPE_WIP_ARCHIVE', 'base_revision': BASE,
        'source_sha256': digest, 'source_files': len(sources), 'focused_cases': len(current),
        'previous_focused_obligations_retained': len(mapped),
        'unchanged_previous_case_identities': len(previous & current),
        'necessary_case_identity_migration': [{'from': list(old), 'to': list(new)} for old, new in MIGRATION.items()],
        'new_focused_cases': len(current - mapped),
        'new_test_file_cases': len(introduced),
        'additional_preexisting_affected_cases': len(current - mapped - introduced),
        'attempt_case_identity_migration': [{'from': list(old), 'to': list(new)}
                                            for old, new in ATTEMPT_MIGRATION.items()],
        'wire_implementation_unchanged': True,
        'attempt_case_identities_retained': attempts,
        'original_fixtures': original_fixtures, 'new_goldens': {name: sha(ROOT / name) for name in NEW_GOLDENS},
        'protected': prior_record['protected'], 'obligation_groups': prior_record['obligation_groups'],
        'completed_obligation_groups': [], 'p4_complete': False, 'm0_m2_complete': False,
        'full_regression_on_this_source': False, 'source_runtime_verified': False,
        'transformation_authorized': False, 'new_lewm_speedup': False, 'new_backend': False,
        'tests_started_by_archive_check': 0,
        'files': {str(path.relative_to(ROOT)): sha(path) for path in sorted(paths)}}
    if sys.argv[1:] == ['--write']:
        assert not MANIFEST.exists()
        MANIFEST.write_text(json.dumps(record, indent=2) + '\n')
    else:
        assert sys.argv[1:] == ['--check']
        assert record == json.loads(MANIFEST.read_text())
    print(json.dumps({key: record[key] for key in ('status', 'source_sha256', 'source_files',
        'focused_cases', 'previous_focused_obligations_retained', 'unchanged_previous_case_identities',
        'new_focused_cases', 'p4_complete', 'm0_m2_complete', 'full_regression_on_this_source',
        'tests_started_by_archive_check')}, indent=2))


if __name__ == '__main__':
    main()
