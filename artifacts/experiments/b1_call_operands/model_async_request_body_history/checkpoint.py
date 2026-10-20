"""Check current-object/F history evidence; execute no tests or native targets."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from scripts.run_gate import fingerprint

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'model_async_finished_requests'
BASE = '0bf37d2a422f51eec2955fb44611760ef75d868e'
FINAL = 'verified-current'
PRODUCTS = {'scar/ir/execution/body_state_history.py', 'scar/ir/execution/query.py'}


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def cases(path, *, green=False):
    rows = tuple(ET.parse(path).iter('testcase'))
    identities = {(row.get('classname'), row.get('name')) for row in rows
                  if row.get('classname') and row.get('name')}
    counts = {'rows': len(rows), 'named_identities': len(identities),
        'failures': sum(row.find('failure') is not None for row in rows),
        'errors': sum(row.find('error') is not None for row in rows),
        'skips': sum(row.find('skipped') is not None for row in rows)}
    if green:
        assert rows and len(identities) == len(rows)
        assert counts['failures'] == counts['errors'] == counts['skips'] == 0
    return identities, counts


def main():
    writing = sys.argv[1:] == ['--write']
    assert writing or sys.argv[1:] == ['--check']
    design = read(HERE / 'design-baseline.json')
    assert design['base_revision'] == BASE
    assert sha(ROOT / design['scope_plan']) == design['plan_sha256']
    assert sha(ROOT / design['prior_checkpoint']) == design['prior_checkpoint_sha256']
    prior = read(PRIOR / 'checkpoint.json')
    for name, expected in prior['files'].items():
        assert sha(ROOT / name) == expected, name
    baseline = read(PRIOR / 'verified-current/sources.after.json')
    assert len(baseline) == 904 and digest(baseline) == design['prior_source_sha256']
    current_digest, current = fingerprint()
    assert set(baseline) <= set(current)
    assert {name for name in baseline if current[name] != baseline[name]} == PRODUCTS
    assert all(current[name] == value for name, value in baseline.items()
               if name.startswith('tests/'))
    added = set(current) - set(baseline)
    assert added == set(read(HERE / 'gate-expectations.json')['added_source_files'])
    direct_prior, _ = cases(PRIOR / 'verified-current/junit.xml', green=True)
    assert len(direct_prior) == 196
    earlier_ids, _ = cases(HERE.parent / 'model_async_terminal_semantics/verified-current/junit.xml', green=True)
    assert len(earlier_ids) == 2104
    old_ids = direct_prior | earlier_ids
    assert len(old_ids) == 2121
    diagnosis = read(HERE / 'baseline-diagnosis.json')
    assert diagnosis['base_revision'] == BASE and diagnosis['sources'] == baseline
    assert diagnosis['source_sha256_before'] == diagnosis['source_sha256_after'] == digest(baseline)
    assert diagnosis['script_sha256'] == sha(HERE / 'diagnose_history.py')
    assert diagnosis['observed_branch'] is True and diagnosis['expected_bool'] is None
    assert diagnosis['native_target_executions'] == 0 and not diagnosis['transformation_authorized']
    attempts = {}
    for result_path in sorted(HERE.glob('*/result.json')):
        folder = result_path.parent
        result, command = read(result_path), read(folder / 'command.json')
        before, after = read(folder / 'sources.before.json'), read(folder / 'sources.after.json')
        assert before == after and result['source_unchanged'], folder
        assert digest(before) == result['source_sha256_before'] == result['source_sha256_after']
        assert len(before) == result['source_count']
        assert command['base_revision'] == BASE and command['cwd'] == str(ROOT)
        assert command['runner_sha256'] == sha(HERE / 'run_focused.py')
        assert command['environment'] == {'PYTHONPATH': '.', 'PYTHONDONTWRITEBYTECODE': '1'}
        snapshots = read(folder / 'source-bytes.json')
        assert set(snapshots) == {name for name in before if baseline.get(name) != before[name]}
        for name, saved in snapshots.items():
            assert sha(HERE / saved['path']) == saved['sha256'] == before[name]
        _, counts = cases(folder / 'junit.xml', green=result['returncode'] == 0)
        attempts[folder.name] = {**result, **counts}
    final, final_counts = cases(HERE / FINAL / 'junit.xml', green=True)
    assert attempts[FINAL]['returncode'] == 0
    assert read(HERE / FINAL / 'sources.after.json') == current
    assert attempts[FINAL]['source_sha256_after'] == current_digest
    command = read(HERE / FINAL / 'command.json')['command']
    assert command[4:-1] == read(HERE / 'focused-selection.json')['selectors']
    # Direct affected selection, with all196 immediately previous cases retained.
    assert direct_prior <= final
    assert final - old_ids
    expected = read(HERE / 'gate-expectations.json')
    assert len(final - old_ids) == expected['new_case_count']
    assert set(attempts) == set(expected['attempts'])
    for name, values in expected['attempts'].items():
        assert {key: attempts[name][key] for key in values} == values, name
    review = read(HERE / 'independent-review.json')
    assert review['source_sha256'] == current_digest and review['source_frozen']
    assert not review['unresolved_blocking_findings']
    for name, expected_digest in review['reviewed_files'].items():
        assert current[name] == expected_digest, name
    for state in design['protected'].values():
        assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=state['path'], text=True).strip() == state['head']
        assert subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=state['path'], text=True) == state['status']
    names = [path for path in HERE.rglob('*') if path.is_file() and path.name != 'checkpoint.json']
    names += [ROOT / name for name in expected['bound_documents']]
    record = {'status': 'VERIFIED_CONDITIONAL_CURRENT_FRAME_IDENTITY_AND_HISTORY',
        'base_revision': BASE, 'final_attempt': FINAL,
        'source_sha256': current_digest, 'source_files': len(current),
        'prior_test_fixture_bytes_unchanged': True,
        'prior_case_catalog_retained': len(old_ids),
        'prior_full_selection_rerun': False,
        'current_focused': final_counts,
        'current_prior_identities_retested': len(final & old_ids),
        'new_identities': len(final - old_ids), 'attempts': attempts,
        'original_family_denominator': design['original_family_denominator'],
        'accepted_families': design['accepted_before'],
        'open_families': design['open_before_and_after_this_batch'],
        'm2_denominator': design['m2_denominator'],
        'f19_family_complete': False, 'first_stage_complete': False,
        'automatic_stored_reference_provenance_complete': False,
        'native_identity_verified': False,
        'native_applicability_verified': False, 'source_runtime_verified': False,
        'transformation_authorized': False, 'new_lewm_speedup': None,
        'files': {str(path.relative_to(ROOT)): sha(path) for path in sorted(names)}}
    if writing:
        (HERE / 'checkpoint.json').write_text(json.dumps(record, indent=2) + '\n')
    else:
        assert read(HERE / 'checkpoint.json') == record
    print(json.dumps({key: value for key, value in record.items() if key != 'files'}))


if __name__ == '__main__':
    main()
