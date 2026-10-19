"""Check retained scope, exact sources and actual attempts; never run tests."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from scripts.run_gate import fingerprint


ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'model_current_async_packet'
BASE = 'fa7b769e34adf5ef39c27103c11b6cb75f796f7b'
MANIFEST = HERE / 'checkpoint.json'
QUERY = 'scar/ir/execution/query.py'
NEW_PRODUCTS = ('scar/ir/execution/state_preservation.py',
                'scar/ir/execution/request_state_history.py')
NEW_TESTS = ('tests/unit/test_execution_state_preservation.py',
             'tests/unit/test_execution_request_state_history.py')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def cases(path, *, green=False):
    rows = tuple(ET.parse(path).iter('testcase'))
    identities = {(row.get('classname'), row.get('name')) for row in rows}
    assert len(identities) == len(rows), path
    if green:
        assert rows and all(not any(row.find(tag) is not None for tag in
                                   ('failure', 'error', 'skipped')) for row in rows), path
    return identities, rows


def stable_attempt(folder):
    record = read(folder / 'result.json')
    before, after = read(folder / 'sources.before.json'), read(folder / 'sources.after.json')
    assert before == after and record['source_unchanged'], folder
    assert record['source_count'] == len(before), folder
    source_digest = hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest()
    assert source_digest == record['source_sha256_before'] == record['source_sha256_after'], folder
    command = read(folder / 'command.json')
    assert command['base_revision'] == BASE and command['cwd'] == str(ROOT)
    assert command['runner_sha256'] == sha(HERE / 'run_focused.py')
    assert command['environment'] == {'PYTHONPATH': '.', 'PYTHONDONTWRITEBYTECODE': '1'}
    return record, before


def main():
    design, previous = read(HERE / 'design-baseline.json'), read(PRIOR / 'checkpoint.json')
    assert design['base_revision'] == BASE
    assert design['prior_checkpoint_sha256'] == sha(PRIOR / 'checkpoint.json')
    assert sha(ROOT / design['scope_plan']) == design['plan_sha256']
    assert sha(ROOT / design['view_contract']) == design['view_contract_sha256']
    assert sha(ROOT / design['query_contract']) == design['query_contract_sha256']
    for path, previous_digest in previous['files'].items():
        assert sha(ROOT / path) == previous_digest, path
    prior_sources = read(PRIOR / 'verified-final/sources.after.json')
    source_digest, sources = fingerprint()
    assert len(prior_sources) == 858 and len(sources) == 862
    assert set(sources) - set(prior_sources) == set((*NEW_PRODUCTS, *NEW_TESTS))
    assert set(prior_sources) <= set(sources)
    for path, previous_digest in prior_sources.items():
        if path != QUERY:
            assert sources[path] == previous_digest, path
    original_tests = {path: value for path, value in prior_sources.items() if path.startswith('tests/')}
    for path, test_digest in original_tests.items():
        assert sha(ROOT / path) == test_digest, path
    for state in design['protected'].values():
        def git(*args):
            return subprocess.check_output(['git', *args], cwd=state['path'], text=True)
        assert git('rev-parse', 'HEAD').strip() == state['head']
        assert git('status', '--porcelain=v1') == state['status']
    result, final_sources = stable_attempt(HERE / 'verified-final')
    assert result['returncode'] == 0 and source_digest == result['source_sha256_before']
    assert final_sources == sources
    old_ids, _ = cases(PRIOR / 'verified-final/junit.xml', green=True)
    current, _ = cases(HERE / 'verified-final/junit.xml', green=True)
    assert len(old_ids) == 1865 and old_ids <= current, 'lost previous exact test identity'
    modules = {path.removesuffix('.py').replace('/', '.') for path in NEW_TESTS}
    assert len(current - old_ids) == 25 and len(current) == 1890
    assert all(identity[0] in modules for identity in current - old_ids)
    assert {module: sum(identity[0] == module for identity in current) for module in modules} == {
        'tests.unit.test_execution_state_preservation': 15,
        'tests.unit.test_execution_request_state_history': 10}
    selection, old_selection = read(HERE / 'focused-selection.json'), read(PRIOR / 'focused-selection.json')
    assert selection['selectors'] == old_selection['selectors'] + list(NEW_TESTS)
    original, family = read(HERE / 'original-obligations.json'), read(HERE / 'family-obligations.json')
    assert original == read(PRIOR / 'original-obligations.json')
    assert family == read(PRIOR / 'family-obligations.json')
    assert len(design['obligation_groups']) == 16 and len(family['remaining_other_families']) == 10
    assert set(family['closed']) == {'F12', 'F13', 'F15', 'F17', 'F21', 'F23'}
    for row in (*original['rows'], *family['reviewed']):
        for selector in row['existing_selectors']:
            path, name = selector.split('::')
            classname = path.removesuffix('.py').replace('/', '.')
            assert any(identity[0] == classname and (identity[1] == name or identity[1].startswith(name + '['))
                       for identity in current), selector
    # The only original file that changed has a baseline form as well as exact
    # pre-run override snapshots. Neither a later test repair nor a guessed
    # reconstruction can replace the failed attempt's actual source bytes.
    baseline_query = subprocess.check_output(['git', 'show', f'{BASE}:{QUERY}'], cwd=ROOT)
    assert hashlib.sha256(baseline_query).hexdigest() == prior_sources[QUERY]
    attempts = {}
    for path in sorted(HERE.glob('*/result.json')):
        attempt, attempt_sources = stable_attempt(path.parent)
        identities, rows = cases(path.parent / 'junit.xml')
        assert identities <= current, path
        assert set(attempt_sources) == set(sources), path
        snapshots = read(path.parent / 'source-bytes.json')
        assert set(snapshots) == {name for name, value in attempt_sources.items()
                                  if prior_sources.get(name) != value}, path
        for name, expected in attempt_sources.items():
            saved = snapshots.get(name)
            if saved is not None:
                assert saved['sha256'] == expected
                assert sha(HERE / saved['path']) == expected, (path, name)
            elif name == QUERY:
                assert hashlib.sha256(baseline_query).hexdigest() == expected
            else:
                assert sha(ROOT / name) == expected, (path, name)
        attempts[path.parent.name] = {**attempt, 'cases': len(rows),
            'failures': sum(row.find('failure') is not None for row in rows),
            'errors': sum(row.find('error') is not None for row in rows),
            'skips': sum(row.find('skipped') is not None for row in rows),
            'selection_error': attempt['returncode'] == 4}
    reviews = read(HERE / 'independent-review.json')
    assert reviews['all_authors_frozen'] and reviews['interpreters_started_by_reviewers'] == 0
    assert not reviews['full_family_closed'] and not reviews['transformation_authorized']
    for path, reviewed_digest in reviews['reviewed_sources'].items():
        assert sha(ROOT / path) == reviewed_digest, path
    documents = [ROOT / name for name in (design['scope_plan'],
        'docs/M1_STATE_FACT_CONTINUATION_PROGRESS.md', 'docs/M1_STATE_FACT_NEXT_GATE.md')]
    paths = [path for path in HERE.rglob('*') if path.is_file() and path != MANIFEST
             and '__pycache__' not in path.parts] + documents
    record = {'status': 'VERIFIED_PROGRESS_STATE_FACT_CONTINUATION', 'base_revision': BASE,
        'source_sha256': source_digest, 'source_files': len(sources), 'focused_cases': len(current),
        'previous_focused_obligations_retained': len(old_ids), 'new_cases': len(current - old_ids),
        'original_tests_unchanged': original_tests, 'test_input_migrations': [],
        'attempts': attempts, 'closed_original_A_H_structural_obligations': original['closed'],
        'completed_obligation_groups': family['closed'], 'newly_closed_obligation_groups': [],
        'remaining_other_families': family['remaining_other_families'],
        'obligation_groups': design['obligation_groups'], 'protected': design['protected'],
        'program_maximum_schema_version': 23, 'execution8_record_schema_unchanged': True,
        'program23_codec_unchanged': True, 'p4_complete': False, 'p5_complete': False,
        'm2_original_constructs': 113, 'm2_original_fields': 196, 'm0_m2_complete': False,
        'full_regression_on_this_source': False, 'source_runtime_verified': False,
        'transformation_authorized': False, 'new_backend': False, 'new_lewm_speedup': False,
        'tests_started_by_archive_check': 0,
        'files': {str(path.relative_to(ROOT)): sha(path) for path in sorted(paths)}}
    if sys.argv[1:] == ['--write']:
        assert not MANIFEST.exists()
        MANIFEST.write_text(json.dumps(record, indent=2) + '\n')
    else:
        assert sys.argv[1:] == ['--check']
        assert read(MANIFEST) == record
    print(json.dumps({key: record[key] for key in (
        'status', 'source_sha256', 'source_files', 'focused_cases',
        'previous_focused_obligations_retained', 'new_cases', 'completed_obligation_groups',
        'm0_m2_complete', 'tests_started_by_archive_check')}, indent=2))


if __name__ == '__main__':
    main()
