"""Audit exact sources, original obligations and immutable attempts; run no tests."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from scripts.run_gate import fingerprint


ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'model_async_session_ownership'
BASE = '51a6eb3354eb05f7c02c9ff189239166f2cd4081'
MANIFEST = HERE / 'checkpoint.json'
ACCEPTANCE = HERE / 'original-acceptance.json'
OLD_PRODUCTS = tuple('scar/ir/' + name for name in (
    'program/__init__.py', 'program/model.py', 'program/validation.py',
    'program/queries.py', 'program/codec.py', 'execution/state_preservation.py',
    'execution/flow.py'))
NEW_PRODUCT = 'scar/ir/program/call_effect_expansion.py'
NEW_FIXTURES = tuple('tests/fixtures/' + name + '.py' for name in (
    'program_call_effect_expansion_graphs', 'execution_call_effect_expansion_graphs'))
NEW_TESTS = tuple('tests/unit/' + name + '.py' for name in (
    'test_program_call_effect_expansion', 'test_program_call_effect_expansion_codec',
    'test_execution_call_effect_expansion'))
EXTRA_REGRESSION = 'tests/unit/test_execution_call_order.py'
DOCUMENTS = tuple('docs/M1_CALL_EFFECT_EXPANSION_' + name + '.md' for name in (
    'PLAN', 'CODEC_MIGRATION', 'TEST_PREMISE', 'STATE_FLOW', 'PROGRESS', 'NEXT_GATE'))


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(sources):
    return hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()


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
    module = path.removesuffix('.py').replace('/', '.')
    found = sorted(identity for identity in identities if identity[0] == module and
                   (identity[1] == name or identity[1].startswith(name + '[')))
    assert found, selector
    return found


def migrations(prior_sources):
    """Replay exactly24 declared literals, never exempt whole existing files."""
    declaration = read(HERE / 'test-input-migrations.json')
    assert declaration['base_revision'] == BASE
    assert sha(ROOT / declaration['amendment']) == declaration['amendment_sha256']
    maximum = declaration['reader_maximum']
    replacements = {}
    for key, before, after in (
        ('codec_prefix_files', 'codec_prefix_before', 'codec_prefix_after'),
        ('bare_files', 'bare_before', 'bare_after')):
        for path in maximum[key]:
            replacements.setdefault(path, []).append((maximum[before], maximum[after]))
    moved = {}
    for row in declaration['future_version']:
        replacements.setdefault(row['file'], []).append((row['before'], row['after']))
        module = row['file'].removesuffix('.py').replace('/', '.')
        moved[(module, row['old_case'])] = (module, row['new_case'])
    for row in declaration['legacy_field_sets']:
        replacements.setdefault(row['file'], []).append((row['before'], row['after']))
    assert len(replacements) == declaration['expected_old_files'] == 16
    assert sum(map(len, replacements.values())) == declaration['expected_literal_replacements'] == 24
    assert len(moved) == declaration['expected_explicit_identity_migrations'] == 5
    for path, changes in replacements.items():
        original = subprocess.check_output(['git', 'show', f'{BASE}:{path}'], cwd=ROOT)
        assert hashlib.sha256(original).hexdigest() == prior_sources[path], path
        expected = original.decode()
        for before, after in changes:
            assert expected.count(before) == 1, (path, before)
            expected = expected.replace(before, after, 1)
        assert (ROOT / path).read_bytes() == expected.encode(), path
    return declaration, replacements, moved


def stable_attempt(folder, prior_sources):
    result = read(folder / 'result.json')
    before, after = read(folder / 'sources.before.json'), read(folder / 'sources.after.json')
    assert before == after and result['source_unchanged'], folder
    assert digest(before) == result['source_sha256_before'] == result['source_sha256_after']
    assert result['source_count'] == len(before) == 884
    command = read(folder / 'command.json')
    assert command['base_revision'] == BASE and command['cwd'] == str(ROOT)
    assert command['runner_sha256'] == sha(HERE / 'run_focused.py')
    assert command['environment'] == {'PYTHONPATH': '.', 'PYTHONDONTWRITEBYTECODE': '1'}
    snapshots = read(folder / 'source-bytes.json')
    assert set(snapshots) == {name for name, value in before.items() if prior_sources.get(name) != value}
    for name, expected in before.items():
        if name in snapshots:
            saved = snapshots[name]
            assert saved['sha256'] == expected
            assert sha(HERE / saved['path']) == expected, (folder, name)
        else:
            assert prior_sources[name] == expected, (folder, name)
    return result, before


def probe(name, script, bound_sources):
    value = read(HERE / name)
    assert value['script_sha256'] == sha(HERE / script)
    assert value['sources'] == bound_sources
    assert value['source_sha256_before'] == value['source_sha256_after'] == digest(bound_sources)
    assert value['tests_started'] == 0
    return value


def main():
    writing = sys.argv[1:] == ['--write']
    assert writing or sys.argv[1:] == ['--check']
    design, previous = read(HERE / 'design-baseline.json'), read(PRIOR / 'checkpoint.json')
    assert design['base_revision'] == BASE
    assert design['prior_checkpoint_sha256'] == sha(PRIOR / 'checkpoint.json')
    for field, hash_field in (('scope_plan', 'plan_sha256'), ('codec_migration', 'codec_migration_sha256')):
        assert sha(ROOT / design[field]) == design[hash_field]
    for path, expected in previous['files'].items():
        assert sha(ROOT / path) == expected, path
    prior_sources = read(PRIOR / 'verified-final/sources.after.json')
    source_digest, sources = fingerprint()
    assert len(prior_sources) == 878 and len(sources) == 884
    assert design['previous_source_sha256'] == digest(prior_sources)
    added_sources = (NEW_PRODUCT, *NEW_FIXTURES, *NEW_TESTS)
    assert set(sources) - set(prior_sources) == set(added_sources)
    assert set(prior_sources) <= set(sources)
    migration, changed_tests, moved = migrations(prior_sources)
    assert {path for path, value in prior_sources.items() if sources[path] != value} == set(OLD_PRODUCTS) | set(changed_tests)
    for state in design['protected'].values():
        assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=state['path'], text=True).strip() == state['head']
        assert subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=state['path'], text=True) == state['status']
    result, final_sources = stable_attempt(HERE / 'verified-final', prior_sources)
    assert result['returncode'] == 0 and final_sources == sources
    assert result['source_sha256_before'] == source_digest
    old, _ = cases(PRIOR / 'verified-final/junit.xml', green=True)
    current, _ = cases(HERE / 'verified-final/junit.xml', green=True)
    assert len(old) == 1956
    assert set(moved) <= old and not set(moved) & current
    assert set(moved.values()) <= current and not set(moved.values()) & old
    exact = old - set(moved)
    retained = exact | set(moved.values())
    assert len(exact) == 1951 and len(retained) == 1956 and retained <= current
    modules = {path.removesuffix('.py').replace('/', '.') for path in NEW_TESTS}
    new = {identity for identity in current - retained if identity[0] in modules}
    extra = current - retained - new
    assert len(current) == 2016 and len(new) == 45 and len(extra) == 15
    assert {module: sum(identity[0] == module for identity in new) for module in modules} == {
        'tests.unit.test_program_call_effect_expansion': 12,
        'tests.unit.test_program_call_effect_expansion_codec': 20,
        'tests.unit.test_execution_call_effect_expansion': 13}
    assert all(identity[0] == EXTRA_REGRESSION.removesuffix('.py').replace('/', '.') for identity in extra)
    scope = read(HERE / 'flow-regression-scope.json')
    assert scope['selector'] == EXTRA_REGRESSION and scope['expected_cases'] == len(extra)
    assert scope['sha256'] == prior_sources[EXTRA_REGRESSION] == sha(ROOT / EXTRA_REGRESSION)
    assert not scope['new_implementation_tests'] and not scope['production_changes']
    selection = read(HERE / 'focused-selection.json')
    assert selection['selectors'] == read(PRIOR / 'focused-selection.json')['selectors'] + [*NEW_TESTS, EXTRA_REGRESSION]
    command = read(HERE / 'verified-final/command.json')['command']
    assert command[1:4] == ['-m', 'pytest', '-q']
    assert command[4:-1] == selection['selectors']
    assert selection['previous_focused_cases'] == 1956
    original, family = read(HERE / 'original-obligations.json'), read(HERE / 'family-obligations.json')
    assert original == read(PRIOR / 'original-obligations.json')
    assert family == read(PRIOR / 'family-obligations.json')
    assert family['newly_closed'] == [] and len(family['closed']) == 7
    assert len(family['remaining_other_families']) == 9 and len(design['obligation_groups']) == 16
    assert design['m2_original_constructs'] == 113 and design['m2_original_fields'] == 196
    matched = {}
    for row in (*original['rows'], *family['reviewed'], family['F14_review']):
        for selector in row['existing_selectors']:
            matched[selector] = matches(selector, current)
    for selector in family['F16_current_scope_review']['already_covered_selectors']:
        matched[selector] = matches(selector, current)
    clauses = {}
    for name in (
        'test_outside_writes_do_not_pollute_the_actual_suffix_caller_prefix',
        'test_complete_expansion_refines_the_unknown_summary_without_rewriting_it',
        'test_an_independent_interval_writer_cannot_hide_behind_source_relative_consumers',
        'test_a_real_opaque_primitive_inside_the_interval_is_not_an_expansion',
        'test_missing_this_instances_required_edge_does_not_borrow_a_complete_sibling',
        'test_a_real_prefix_does_not_require_its_future_completion',
        'test_budget_one_keeps_endpoints_and_never_grants_an_unchecked_expansion',
        'test_a_checked_prefix_does_not_replace_the_remainder_of_the_actual_interval',
        'test_ordinary_calls_keep_data_state_ordinals_without_requiring_future_results'):
        clauses[name] = matches(NEW_TESTS[2] + '::' + name, current)
    attempts, attempt_sources = {}, {}
    expected_attempts = {
        'initial-explicit-contract': (45, 14),
        'corrected-cfg-original-query': (14, 11),
        'ordinary-current-version-counterexample': (1, 1),
        'precise-expansion-and-current-state': (45, 0),
        'verified-final': (2016, 0)}
    for folder in sorted(HERE.glob('*/result.json')):
        attempt, snapshot = stable_attempt(folder.parent, prior_sources)
        identities, rows = cases(folder.parent / 'junit.xml')
        assert {moved.get(identity, identity) for identity in identities} <= current, folder
        assert set(snapshot) == set(sources), folder
        attempt_sources[folder.parent.name] = snapshot
        attempts[folder.parent.name] = {**attempt, 'cases': len(rows),
            'failures': sum(row.find('failure') is not None for row in rows),
            'errors': sum(row.find('error') is not None for row in rows),
            'skips': sum(row.find('skipped') is not None for row in rows)}
    assert set(attempts) == set(expected_attempts)
    for name, expected in expected_attempts.items():
        assert (attempts[name]['cases'], attempts[name]['failures']) == expected, name
        assert attempts[name]['errors'] == attempts[name]['skips'] == 0
        assert (attempts[name]['returncode'] == 0) == (expected[1] == 0)
    counter = attempt_sources['ordinary-current-version-counterexample']
    for path in ('scar/ir/execution/flow.py', 'scar/ir/execution/state_preservation.py'):
        assert counter[path] == prior_sources[path], path
    assert attempt_sources['precise-expansion-and-current-state'] == final_sources
    before_sources = attempt_sources['corrected-cfg-original-query']
    before = probe('interval-before.json', 'probe_interval.py', before_sources)
    after = probe('interval-after.json', 'probe_interval.py', final_sources)
    assert [row['name'] for row in before['scenarios']] == [row['name'] for row in after['scenarios']]
    assert len(before['scenarios']) == len(after['scenarios']) == 6
    assert all(row['preserved'] is None for row in before['scenarios'])
    assert all(row['preserved'] is True and not row['blockers'] for row in after['scenarios'])
    for rows in (before['scenarios'], after['scenarios']):
        assert all(not row['source_runtime_verified'] and not row['transformation_authorized'] for row in rows)
    assert [row['raw_parent_complete'] for row in before['scenarios']] == [row['raw_parent_complete'] for row in after['scenarios']]
    baseline = probe('subclass-baseline-probe.json', 'probe_subclass_baseline.py', before_sources)
    assert baseline['base_revision'] == BASE and baseline['returncode'] == 0
    observation = baseline['observation']
    assert observation['reader_maximum'] == 24
    assert [row['code'] for row in observation['issues']] == ['address_graph']
    assert observation['public_index']['kind'] == 'ValueError'
    validator = 'scar/ir/program/state_address_validation.py'
    assert observation['address_validator_sha256'] == prior_sources[validator] == sources[validator]
    reviews = read(HERE / 'independent-review.json')
    assert reviews['all_authors_frozen'] and reviews['interpreters_started_by_reviewers'] == 0
    assert set(reviews['reviewed_sources']) == set((*OLD_PRODUCTS, *added_sources))
    for path, expected in reviews['reviewed_sources'].items():
        assert sha(ROOT / path) == expected, path
    for path, expected in reviews['frozen_supplements'].items():
        assert sha(ROOT / path) == expected, path
    assert reviews['whole_program_scope_review']['tests_started'] == 0
    for path, expected in reviews['whole_program_scope_review']['design_references'].items():
        assert sha(ROOT / path) == expected, path
    assert not reviews['automatic_source_recovery'] and not reviews['transformation_authorized']
    remaining_review = read(HERE / 'remaining-source-review.json')
    assert remaining_review['source_sha256'] == source_digest
    assert remaining_review['kind'] == 'READ_ONLY_SOURCE_REVIEW_NOT_FAMILY_ACCEPTANCE'
    assert remaining_review['tests_started'] == 0 and remaining_review['newly_closed'] == []
    assert remaining_review['all_nine_families_remain_open']
    assert {row['id'] for row in remaining_review['rows']} == {
        'F18', 'F19', 'F20', 'F22', 'F24', 'X25', 'X26', 'X27'}
    for path, expected in remaining_review['source_hashes'].items():
        assert sources[path] == expected, path
    for row in remaining_review['rows']:
        assert row['status'] == 'OPEN_SOURCE_REVIEW_ONLY'
        for evidence in row['evidence']:
            identities = {tuple(identity) for identity in evidence['current_final_cases']}
            assert identities <= current
            assert evidence['current_final_retested'] == bool(identities)
            if identities:
                assert identities == set(matches(evidence['selector'], current))
    acceptance = {
        'status': 'VERIFIED_PROGRESS_CALL_EFFECT_EXPANSION_NOT_FAMILY_ACCEPTANCE',
        'source_sha256': source_digest, 'clauses': clauses, 'matched_selectors': matched,
        'new_cases': sorted(new), 'newly_included_existing_cases': sorted(extra),
        'previous_exact_identities_retained': len(exact),
        'explicit_identity_migrations': [{'old': old_id, 'new': new_id} for old_id, new_id in sorted(moved.items())],
        'previous_focused_obligations_retained': len(retained),
        'scope': 'Conditional supplied complete-effect declarations and exact callee intervals; automatic recovery and original primitive boundaries remain open.',
        'newly_closed_families': [], 'f16_complete': False, 'p4_complete': False,
        'm0_m2_complete': False, 'transformation_authorized': False, 'tests_started': 0}
    if writing:
        assert not MANIFEST.exists() and not ACCEPTANCE.exists()
        ACCEPTANCE.write_text(json.dumps(acceptance, indent=2) + '\n')
    else:
        assert read(ACCEPTANCE) == json.loads(json.dumps(acceptance))
    paths = [path for path in HERE.rglob('*') if path.is_file() and path != MANIFEST
             and '__pycache__' not in path.parts] + [ROOT / path for path in DOCUMENTS]
    record = {
        'status': acceptance['status'], 'base_revision': BASE,
        'source_sha256': source_digest, 'source_files': len(sources), 'focused_cases': len(current),
        'previous_focused_obligations_retained': len(retained),
        'previous_exact_identities_retained': len(exact), 'explicit_identity_migrations': len(moved),
        'new_cases': len(new), 'newly_included_existing_cases': len(extra),
        'test_input_migrations': migration,
        'original_tests_unchanged_except_exact_migrations': {
            path: value for path, value in prior_sources.items()
            if path.startswith('tests/') and path not in changed_tests},
        'attempts': attempts, 'query_before_after_scenarios': 6,
        'closed_original_A_H_structural_obligations': original['closed'],
        'completed_obligation_groups': family['closed'], 'newly_closed_obligation_groups': [],
        'remaining_other_families': family['remaining_other_families'],
        'obligation_groups': design['obligation_groups'], 'protected': design['protected'],
        'program_maximum_schema_version': 25, 'legacy_wire_meaning_preserved': True,
        'execution8_record_schema_unchanged': True, 'f16_complete': False,
        'p4_complete': False, 'p5_complete': False,
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
        'previous_focused_obligations_retained', 'previous_exact_identities_retained',
        'explicit_identity_migrations', 'new_cases', 'newly_included_existing_cases',
        'newly_closed_obligation_groups', 'm0_m2_complete', 'tests_started_by_archive_check')}, indent=2))


if __name__ == '__main__':
    main()
