"""Verify this finite source-bound archive without starting any tests."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
import xml.etree.ElementTree as ET

from scripts.run_gate import fingerprint

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'model_await_reevaluation'
BASE = '7aee713c1b700f504ba3ebb8606fa2a4456c4e1c'
MANIFEST = HERE / 'checkpoint.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args, cwd=ROOT):
    return subprocess.check_output(['git', *args], cwd=cwd)


def cases(path, *, green=False):
    rows = tuple(ET.parse(path).iter('testcase'))
    identities = {(row.get('classname'), row.get('name')) for row in rows}
    assert len(identities) == len(rows), path
    if green:
        assert rows and all(not any(row.find(tag) is not None
            for tag in ('failure', 'error', 'skipped')) for row in rows), path
    return identities, rows


def evidence(current, selectors):
    found = {}
    for selector in selectors:
        filename, name = selector.split('::')
        classname = filename.removesuffix('.py').replace('/', '.')
        matches = sorted(item for item in current if item[0] == classname
            and (item[1] == name or item[1].startswith(name + '[')))
        assert matches, selector
        found[selector] = [list(item) for item in matches]
    return found


def stable_attempt(folder):
    result = json.loads((folder / 'result.json').read_text())
    before = json.loads((folder / 'sources.before.json').read_text())
    after = json.loads((folder / 'sources.after.json').read_text())
    assert before == after and result['source_unchanged'], folder
    bound = hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest()
    assert bound == result['source_sha256_before'] == result['source_sha256_after'], folder
    assert len(before) == result['source_count'], folder
    return result


def main():
    design = json.loads((HERE / 'design-baseline.json').read_text())
    assert design['base_revision'] == BASE
    assert sha(ROOT / design['scope_plan']) == design['plan_sha256']
    amendment = json.loads((HERE / 'design-amendment.json').read_text())
    assert amendment['base_revision'] == BASE and amendment['initial_design_unchanged']
    assert sha(ROOT / amendment['amendment']) == amendment['amendment_sha256']
    assert sha(ROOT / amendment['literal_clarification']) == amendment['literal_clarification_sha256']
    original_selection = json.loads((HERE / amendment['original_selection']).read_text())
    amended_selection = json.loads((HERE / amendment['amended_selection']).read_text())
    assert amended_selection['selectors'] == original_selection['selectors'] + [amendment['additional_test_file']]
    assert amended_selection['amendment'] == amendment
    assert sha(ROOT / design['view_contract']) == design['view_contract_sha256']
    assert sha(ROOT / design['query_contract']) == design['query_contract_sha256']
    assert sha(PRIOR / 'checkpoint.json') == design['prior_checkpoint_sha256']
    prior = json.loads((PRIOR / 'checkpoint.json').read_text())
    assert len(design['obligation_groups']) == 16
    assert prior['focused_cases'] == design['previous_focused_cases'] == 1845
    assert prior['protected'] == design['protected']
    for state in design['protected'].values():
        assert git('rev-parse', 'HEAD', cwd=state['path']).decode().strip() == state['head']
        assert git('status', '--porcelain=v1', cwd=state['path']).decode() == state['status']
    original_tests = {}
    for name in git('ls-tree', '-r', '--name-only', BASE, 'tests').decode().splitlines():
        before = git('show', BASE + ':' + name)
        assert (ROOT / name).read_bytes() == before, name
        original_tests[name] = hashlib.sha256(before).hexdigest()
    for name in git('ls-tree', '-r', '--name-only', BASE, 'docs').decode().splitlines():
        if name in ('docs/MODEL.md', 'docs/ROADMAP.md'):
            continue
        assert (ROOT / name).read_bytes() == git('show', BASE + ':' + name), name
    for name in ('scar/ir/execution/model.py', 'scar/ir/execution/codec.py',
                 'scar/ir/execution/resumables.py', 'scar/ir/program/model.py',
                 'scar/ir/program/codec.py'):
        assert (ROOT / name).read_bytes() == git('show', BASE + ':' + name), name
    for name, digest in prior['files'].items():
        assert sha(ROOT / name) == digest, name
    final = HERE / 'verified-final'
    result = stable_attempt(final)
    digest, sources = fingerprint()
    assert result['returncode'] == 0 and digest == result['source_sha256_before']
    assert len(sources) == result['source_count']
    previous, _ = cases(PRIOR / 'verified-final/junit.xml', green=True)
    current, _ = cases(final / 'junit.xml', green=True)
    assert len(previous) == 1845 and previous <= current, 'lost previous exact identity'
    authored_modules = {
        'tests.unit.test_program_await_direct_qualification',
        'tests.unit.test_program_await_foreign_drive_result',
        'tests.unit.test_program_await_native_and_general_sources'}
    authored = {item for item in current - previous if item[0] in authored_modules}
    related = current - previous - authored
    assert authored and not related, related
    ledger = json.loads((HERE / 'original-obligations.json').read_text())
    previous_ledger = json.loads((PRIOR / 'original-obligations.json').read_text())
    assert [row['id'] for row in ledger['rows']] == list('ABCDEFGH')
    assert set(previous_ledger['closed']) <= set(ledger['closed'])
    obligation_evidence = {}
    old_rows = {row['id']: row for row in previous_ledger['rows']}
    for row in ledger['rows']:
        assert set(old_rows[row['id']]['existing_selectors']) <= set(row['existing_selectors'])
        if row['id'] in previous_ledger['closed']:
            assert row == old_rows[row['id']]
        obligation_evidence[row['id']] = {
            'executed_structural_evidence': evidence(current, row['existing_selectors']),
            'remaining': row['remaining'], 'closed': row['id'] in ledger['closed']}
    families = json.loads((HERE / 'family-obligations.json').read_text())
    old_families = json.loads((PRIOR / 'family-obligations.json').read_text())
    assert set(old_families['closed']) <= set(families['closed'])
    assert len(families['closed']) == len(set(families['closed']))
    assert {row['id'] for row in families['reviewed']} == set(families['closed'])
    assert not set(families['remaining_other_families']) & set(families['closed'])
    assert set(families['remaining_other_families']) | set(families['closed']) == set(design['obligation_groups'])
    for old_row in old_families['reviewed']:
        assert old_row in families['reviewed']
    family_evidence = {}
    for row in families['reviewed']:
        assert row['remaining'] is None
        family_evidence[row['id']] = {
            'executed_structural_evidence': evidence(current, row['existing_selectors']),
            'remaining': None, 'closed': True}
    acceptance = json.loads((HERE / 'structural-acceptance.json').read_text())
    assert acceptance == runpy.run_path(str(HERE / 'accept_structural_scope.py'))['evaluate']()
    assert acceptance['source_sha256'] == digest and acceptance['focused_cases'] == len(current)
    assert acceptance['closed_A_H'] == ledger['closed']
    assert acceptance['closed_families'] == families['closed']
    for group, roles in acceptance['required_clauses'].items():
        assert roles
        for role, selectors in roles.items():
            assert selectors and evidence(current, selectors)
    attempts, probes = {}, {}
    for result_path in sorted(HERE.glob('*/result.json')):
        folder = result_path.parent
        attempt = stable_attempt(folder)
        if (folder / 'junit.xml').exists():
            ids, rows = cases(folder / 'junit.xml')
            ordinary = {item for item in ids if item[0] and item[0].startswith('tests.unit.')}
            assert ordinary <= current, folder
            attempts[folder.name] = {**attempt, 'tests': len(rows),
                'failures': sum(row.find('failure') is not None for row in rows),
                'errors': sum(row.find('error') is not None for row in rows),
                'skips': sum(row.find('skipped') is not None for row in rows)}
        else:
            command = json.loads((folder / 'command.json').read_text())
            script = Path(command['command'][1])
            assert sha(script) == command['script_sha256'], script
            probes[folder.name] = {**attempt, 'acceptance_test': False}
    docs = [ROOT / name for name in (
        'docs/M1_DIRECT_QUALIFICATION_AND_RESULT_PLAN.md',
        'docs/M1_DIRECT_QUALIFICATION_AND_RESULT_PROGRESS.md',
        'docs/M1_DIRECT_RESULT_F12_AMENDMENT.md',
        'docs/M1_DIRECT_RESULT_LITERAL_CLARIFICATION.md',
        'docs/M1_AWAIT_SOURCE_FAMILY_ACCEPTANCE.md',
        'docs/M1_COROUTINE_REQUEST_NEXT_REVIEW.md')]
    paths = [path for path in HERE.rglob('*') if path.is_file() and path != MANIFEST
             and '__pycache__' not in path.parts] + docs
    record = {'status': 'PROGRESS_ORIGINAL_STRUCTURAL_OBLIGATIONS', 'base_revision': BASE,
        'source_sha256': digest, 'source_files': len(sources), 'focused_cases': len(current),
        'previous_focused_obligations_retained': len(previous), 'new_cases': len(current - previous),
        'newly_authored_cases': len(authored), 'newly_covered_existing_cases': len(related),
        'original_A_H_partial_evidence': obligation_evidence,
        'closed_original_A_H_structural_obligations': ledger['closed'],
        'family_structural_acceptance': family_evidence,
        'structural_acceptance': acceptance,
        'remaining_other_families': families['remaining_other_families'],
        'original_tests_unchanged': original_tests, 'test_input_migrations': [],
        'attempts': attempts, 'diagnostic_probes': probes,
        'program_maximum_schema_version': 23, 'execution8_record_schema_unchanged': True,
        'program23_codec_unchanged': True, 'protected': design['protected'],
        'obligation_groups': design['obligation_groups'], 'completed_obligation_groups': families['closed'],
        'full_A_H_complete': set(ledger['closed']) == set('ABCDEFGH'),
        'p4_complete': False, 'm0_m2_complete': False,
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
    print(json.dumps({key: record[key] for key in (
        'status', 'source_sha256', 'source_files', 'focused_cases',
        'previous_focused_obligations_retained', 'new_cases',
        'closed_original_A_H_structural_obligations', 'completed_obligation_groups',
        'm0_m2_complete', 'tests_started_by_archive_check')}, indent=2))


if __name__ == '__main__':
    main()
