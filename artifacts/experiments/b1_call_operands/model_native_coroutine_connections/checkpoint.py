"""Verify original scope, source-bound attempts and acceptance; run no tests."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from scripts.run_gate import fingerprint


ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'model_state_fact_continuations'
BASE = 'f26829c126f519043943af85c0faa62a9c76dd3b'
MANIFEST = HERE / 'checkpoint.json'
ACCEPTANCE = HERE / 'original-acceptance.json'
QUERY = 'scar/ir/execution/query.py'
NEW_PRODUCTS = ('scar/ir/execution/body_state_history.py',)
NEW_FIXTURES = tuple('tests/fixtures/' + name + '.py' for name in (
    'native_coroutine_common', 'execution_coroutine_running_graphs',
    'execution_coroutine_closed_graphs', 'execution_coroutine_packets_graphs'))
NEW_TESTS = tuple('tests/unit/test_execution_coroutine_' + name + '.py'
                  for name in ('running', 'closed', 'packets'))
FINAL_SOURCE = '07028c2c92e5e915ae9e7ac9877331790ca46d9a938a2c71a8a4bb63e1680e4f'


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


def matches(selector, identities):
    path, name = selector.split('::')
    classname = path.removesuffix('.py').replace('/', '.')
    selected = sorted(identity for identity in identities if identity[0] == classname
                      and (identity[1] == name or identity[1].startswith(name + '[')))
    assert selected, selector
    return selected


def stable_attempt(folder):
    result = read(folder / 'result.json')
    before, after = read(folder / 'sources.before.json'), read(folder / 'sources.after.json')
    assert before == after and result['source_unchanged'], folder
    source_digest = hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest()
    assert source_digest == result['source_sha256_before'] == result['source_sha256_after']
    assert result['source_count'] == len(before) == 870
    command = read(folder / 'command.json')
    assert command['base_revision'] == BASE and command['cwd'] == str(ROOT)
    assert command['runner_sha256'] == sha(HERE / 'run_focused.py')
    assert command['environment'] == {'PYTHONPATH': '.', 'PYTHONDONTWRITEBYTECODE': '1'}
    return result, before


def main():
    writing = sys.argv[1:] == ['--write']
    assert writing or sys.argv[1:] == ['--check']
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
    assert len(prior_sources) == 862 and len(sources) == 870
    assert source_digest == FINAL_SOURCE
    assert set(sources) - set(prior_sources) == set((*NEW_PRODUCTS, *NEW_FIXTURES, *NEW_TESTS))
    assert set(prior_sources) <= set(sources)
    for path, previous_digest in prior_sources.items():
        if path != QUERY:
            assert sources[path] == previous_digest, path
    original_tests = {path: value for path, value in prior_sources.items() if path.startswith('tests/')}
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
    assert len(old_ids) == 1890 and old_ids <= current, 'lost previous exact test identity'
    assert len(current - old_ids) == 17 and len(current) == 1907
    modules = {path.removesuffix('.py').replace('/', '.') for path in NEW_TESTS}
    assert all(identity[0] in modules for identity in current - old_ids)
    assert {module: sum(identity[0] == module for identity in current) for module in modules} == {
        'tests.unit.test_execution_coroutine_running': 5,
        'tests.unit.test_execution_coroutine_closed': 6,
        'tests.unit.test_execution_coroutine_packets': 6}
    selection, old_selection = read(HERE / 'focused-selection.json'), read(PRIOR / 'focused-selection.json')
    assert selection['selectors'] == old_selection['selectors'] + list(NEW_TESTS)
    command = read(HERE / 'verified-final/command.json')['command']
    assert command[1:4] == ['-m', 'pytest', '-q']
    assert command[4:-1] == selection['selectors']
    original, family = read(HERE / 'original-obligations.json'), read(HERE / 'family-obligations.json')
    prior_family = read(PRIOR / 'family-obligations.json')
    assert original == read(PRIOR / 'original-obligations.json')
    assert family['reviewed'] == prior_family['reviewed']
    assert family['previous_closed'] == prior_family['previous_closed']
    assert family['previous_remaining_descriptions'] == prior_family['previous_remaining_descriptions']
    assert set(family['closed']) == set(prior_family['closed']) | {'F14'}
    assert family['newly_closed'] == ['F14']
    assert family['remaining_other_families'] == {
        key: value for key, value in prior_family['remaining_other_families'].items() if key != 'F14'}
    assert len(design['obligation_groups']) == 16 and len(family['remaining_other_families']) == 9
    assert family['F16_current_scope_review']['historical_remaining_text_retained']
    assert not family['F16_current_scope_review']['family_closed']
    matched = {}
    for row in (*original['rows'], *family['reviewed'], family['F14_review']):
        for selector in row['existing_selectors']:
            matched[selector] = matches(selector, current)
    for selector in family['F16_current_scope_review']['already_covered_selectors']:
        matched[selector] = matches(selector, current)
    running, closed, packets = NEW_TESTS
    clauses = {
        'running_reentry': running + '::test_native_same_body_is_actually_running_during_reentry_and_then_finishes',
        'completed_same_body_reuse': closed + '::test_completed_native_same_body_reuse_has_history_and_its_own_rejection_packet',
        'historical_callback_predicate': closed + '::test_native_historical_phase_bool_does_not_supply_the_current_gate_snapshot',
        'suspended_throw': packets + '::test_native_suspended_packets_follow_their_exact_normalizer_and_body_ports',
        'suspended_close': packets + '::test_native_suspended_packets_follow_their_exact_normalizer_and_body_ports'}
    clause_cases = {key: matches(value, current) for key, value in clauses.items()}
    clause_cases['suspended_throw'] = [row for row in clause_cases['suspended_throw'] if row[1].endswith('-throw]')]
    clause_cases['suspended_close'] = [row for row in clause_cases['suspended_close'] if row[1].endswith('-close]')]
    assert {key: len(value) for key, value in clause_cases.items()} == {
        'running_reentry': 1, 'completed_same_body_reuse': 2,
        'historical_callback_predicate': 2, 'suspended_throw': 2, 'suspended_close': 2}
    acceptance = {'status': 'PASS_WITH_SCOPE', 'original_family': 'F14',
        'source_sha256': source_digest, 'clauses': clause_cases, 'matched_selectors': matched,
        'new_cases': sorted(current - old_ids), 'previous_exact_identities_retained': len(old_ids),
        'scope': 'Original supplied-model conditional structural contract, not automatic source recovery/native applicability.',
        'p4_complete': False, 'm0_m2_complete': False, 'transformation_authorized': False,
        'tests_started': 0}
    # Original bytes and each failed attempt's actual pre-run overrides are
    # checked separately. Later fixture repair cannot replace historical bytes.
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
            'skips': sum(row.find('skipped') is not None for row in rows)}
    probes = {}
    for name, attempt_name in (('initial-history-probe.json', 'authored-fixture-repairs'),
                               ('capture-gap-probe-before.json', 'conditional-native-source-bridge')):
        probe = read(HERE / name)
        assert probe['tests_started'] == 0
        assert probe['source_sha256_before'] == probe['source_sha256_after']
        assert probe['source_sha256_before'] == attempts[attempt_name]['source_sha256_before']
        probes[name] = {'sha256': sha(HERE / name), 'source_attempt': attempt_name,
                        'source_sha256': probe['source_sha256_before'], 'tests_started': 0}
    reviews = read(HERE / 'independent-review.json')
    assert reviews['all_authors_frozen'] and reviews['interpreters_started_by_reviewers'] == 0
    assert reviews['original_family_structural_review'] == 'F14'
    assert not reviews['p4_complete'] and not reviews['transformation_authorized']
    assert set(reviews['reviewed_sources']) == {QUERY, *NEW_PRODUCTS, *NEW_FIXTURES, *NEW_TESTS}
    for path, reviewed_digest in reviews['reviewed_sources'].items():
        assert sha(ROOT / path) == reviewed_digest, path
    if writing:
        assert not MANIFEST.exists() and not ACCEPTANCE.exists()
        ACCEPTANCE.write_text(json.dumps(acceptance, indent=2) + '\n')
    else:
        assert read(ACCEPTANCE) == json.loads(json.dumps(acceptance))
    documents = [ROOT / name for name in (design['scope_plan'],
        'docs/M1_NATIVE_COROUTINE_PROGRESS.md', 'docs/M1_NATIVE_COROUTINE_ACCEPTANCE.md',
        'docs/M1_NATIVE_COROUTINE_NEXT_GATE.md')]
    paths = [path for path in HERE.rglob('*') if path.is_file() and path != MANIFEST
             and '__pycache__' not in path.parts] + documents
    record = {'status': 'VERIFIED_PROGRESS_NATIVE_COROUTINE_F14', 'base_revision': BASE,
        'source_sha256': source_digest, 'source_files': len(sources), 'focused_cases': len(current),
        'previous_focused_obligations_retained': len(old_ids), 'new_cases': len(current - old_ids),
        'original_tests_unchanged': original_tests, 'test_input_migrations': [],
        'attempts': attempts, 'probes': probes,
        'closed_original_A_H_structural_obligations': original['closed'],
        'completed_obligation_groups': family['closed'], 'newly_closed_obligation_groups': ['F14'],
        'remaining_other_families': family['remaining_other_families'],
        'obligation_groups': design['obligation_groups'], 'protected': design['protected'],
        'program_maximum_schema_version': 23, 'execution8_record_schema_unchanged': True,
        'program23_codec_unchanged': True, 'p4_complete': False, 'p5_complete': False,
        'm2_original_constructs': 113, 'm2_original_fields': 196, 'm0_m2_complete': False,
        'full_regression_on_this_source': False, 'source_runtime_verified': False,
        'transformation_authorized': False, 'new_backend': False, 'new_lewm_speedup': False,
        'tests_started_by_archive_check': 0,
        'files': {str(path.relative_to(ROOT)): sha(path) for path in sorted(paths)}}
    if writing:
        MANIFEST.write_text(json.dumps(record, indent=2) + '\n')
    else:
        assert read(MANIFEST) == record
    print(json.dumps({key: record[key] for key in (
        'status', 'source_sha256', 'source_files', 'focused_cases',
        'previous_focused_obligations_retained', 'new_cases', 'newly_closed_obligation_groups',
        'm0_m2_complete', 'tests_started_by_archive_check')}, indent=2))


if __name__ == '__main__':
    main()
