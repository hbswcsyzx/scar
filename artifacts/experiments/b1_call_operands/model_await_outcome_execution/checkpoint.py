"""Verify a source-bound progress archive; starts no tests or workloads."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from scripts.run_gate import fingerprint

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'model_await_outcome_links'
BASE = '287c906c95658d25200d057fe9002fc3d1f8479c'
MANIFEST = HERE / 'checkpoint.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args, cwd=ROOT):
    return subprocess.check_output(['git', *args], cwd=cwd)


def cases(path, *, green=False):
    rows = tuple(ET.parse(path).iter('testcase'))
    assert rows, path
    if green:
        assert all(not any(row.find(tag) is not None for tag in ('failure', 'error', 'skipped'))
                   for row in rows), path
    identities = {(row.get('classname'), row.get('name')) for row in rows}
    assert len(identities) == len(rows), path
    return identities, rows


def main():
    design = json.loads((HERE / 'design-baseline.json').read_text())
    assert design['base_revision'] == BASE
    assert sha(ROOT / design['scope_plan']) == design['plan_sha256']
    assert sha(ROOT / design['view_contract']) == design['view_contract_sha256']
    assert len(design['obligation_groups']) == 16 and design['completed_obligation_groups'] == []
    prior = json.loads((PRIOR / 'checkpoint.json').read_text())
    assert prior['protected'] == design['protected']
    for state in design['protected'].values():
        assert git('rev-parse', 'HEAD', cwd=state['path']).decode().strip() == state['head']
        assert git('status', '--porcelain=v1', cwd=state['path']).decode() == state['status']
    original_tests = {}
    for name in git('ls-tree', '-r', '--name-only', BASE, 'tests').decode().splitlines():
        before = git('show', BASE + ':' + name)
        assert (ROOT / name).read_bytes() == before, name
        original_tests[name] = hashlib.sha256(before).hexdigest()
    for name in ('scar/ir/execution/model.py', 'scar/ir/execution/codec.py',
                 'scar/ir/execution/resumables.py', 'scar/ir/program/model.py',
                 'scar/ir/program/codec.py', 'docs/M1_AWAIT_ACQUISITION_PLAN.md',
                 'docs/M1_AWAIT_ACQUISITION_CONTRACT.md', 'docs/M1_AWAIT_COMPOSITION_PLAN.md',
                 'docs/M1_AWAIT_COMPOSITION_AMENDMENT.md', 'docs/M1_AWAIT_QUALIFICATION_CONTRACT.md',
                 'docs/M1_AWAIT_OUTCOME_VIEW_CONTRACT.md'):
        assert (ROOT / name).read_bytes() == git('show', BASE + ':' + name), name
    for name, digest in prior['files'].items():
        assert sha(ROOT / name) == digest, name
    final = HERE / 'accepted-final'
    result = json.loads((final / 'result.json').read_text())
    digest, sources = fingerprint()
    assert result['returncode'] == 0 and result['source_unchanged']
    assert digest == result['source_sha256_before'] == result['source_sha256_after']
    assert len(sources) == result['source_count']
    previous, _ = cases(PRIOR / 'accepted-focused/junit.xml', green=True)
    current, _ = cases(final / 'junit.xml', green=True)
    assert len(previous) == design['previous_focused_cases'] == 1477
    assert previous <= current, 'lost prior exact case identity'
    attempts = {}
    for path in sorted(HERE.rglob('junit.xml')):
        ids, rows = cases(path)
        ordinary = {item for item in ids if item[0] and item[0].startswith('tests.unit.')}
        assert ordinary <= current, path
        attempt = json.loads((path.parent / 'result.json').read_text())
        assert attempt['source_unchanged'], path
        attempts[str(path.relative_to(HERE))] = {
            'tests': len(rows), 'failures': sum(row.find('failure') is not None for row in rows),
            'errors': sum(row.find('error') is not None for row in rows),
            'source_sha256': attempt['source_sha256_before']}
    docs = [ROOT / name for name in (
        'docs/M1_AWAIT_OUTCOME_EXECUTION_CONTRACT.md', 'docs/M1_AWAIT_OUTCOME_EXECUTION_PROGRESS.md')]
    paths = [path for path in HERE.rglob('*') if path.is_file() and path != MANIFEST
             and '__pycache__' not in path.parts] + docs
    record = {'status': 'PROGRESS_COMPLETE_AWAIT_UNIT_STILL_OPEN', 'base_revision': BASE,
        'source_sha256': digest, 'source_files': len(sources), 'focused_cases': len(current),
        'previous_focused_obligations_retained': len(previous), 'new_cases': len(current - previous),
        'original_tests_unchanged': original_tests, 'test_input_migrations': [], 'attempts': attempts,
        'program_maximum_schema_version': 23, 'execution8_record_schema_unchanged': True,
        'program23_codec_unchanged': True,
        'protected': design['protected'], 'obligation_groups': design['obligation_groups'],
        'completed_obligation_groups': [], 'full_A_H_complete': False, 'p4_complete': False,
        'm0_m2_complete': False, 'full_regression_on_this_source': False,
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
        'focused_cases', 'previous_focused_obligations_retained', 'new_cases',
        'full_A_H_complete', 'p4_complete', 'm0_m2_complete', 'tests_started_by_archive_check')}, indent=2))


if __name__ == '__main__':
    main()
