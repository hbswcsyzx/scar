"""Verify immutable attempts, exact legacy migrations and the original scope."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from scripts.run_gate import fingerprint

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'model_async_request_body_history'
BASE = '5fd5a7f0b246f72ff708f53ba000728817a8feca'
PRODUCTS = {'scar/ir/execution/query.py', 'scar/ir/program/model.py',
    'scar/ir/program/codec.py', 'scar/ir/program/validation.py', 'scar/ir/program/__init__.py'}
ADDED = {'scar/ir/execution/stored_values.py', 'scar/ir/program/stored_values.py',
    'tests/fixtures/execution_stored_values.py', 'tests/unit/test_execution_stored_values.py',
    'tests/unit/test_program_stored_value_records.py', 'tests/unit/test_program_stored_value_codec.py'}
FUTURES = {
    'test_program_method_lookup_codec': 'test_program_graph_rejects_future_or_boolean_schema_versions',
    'test_program_session_occupancy_codec': 'test_boolean_and_next_future_versions_do_not_enable_the_subject',
    'test_program_lookup_fallback_codec': 'test_future_and_boolean_schema_versions_remain_rejected',
    'test_program_call_effect_expansion_codec': 'test_boolean_or_next_future_version_cannot_enable_effect_expansion',
    'test_program_async_initial_control_codec': 'test_boolean_or_future_schema_does_not_enable_async_initial_control',
    'test_program_await_acquisition_codec': 'test_boolean_or_future_schema_version_is_not_a_capability',
    'test_program_exception_match_codec': 'test_future_and_boolean_schema_versions_remain_rejected',
}


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def cases(path, *, green=False):
    rows = tuple(ET.parse(path).iter('testcase'))
    ids = {(row.get('classname'), row.get('name')) for row in rows}
    counts = {'rows': len(rows), 'identities': len(ids),
        'failures': sum(row.find('failure') is not None for row in rows),
        'errors': sum(row.find('error') is not None for row in rows),
        'skips': sum(row.find('skipped') is not None for row in rows)}
    assert len(ids) == len(rows) and all(all(identity) for identity in ids)
    if green:
        assert rows and counts['failures'] == counts['errors'] == counts['skips'] == 0
    return ids, counts


def migrated(identity):
    module, name = identity
    function = FUTURES.get(module.split('.')[-1])
    return (module, function + '[28]') if name == str(function) + '[27]' else identity


def legacy_migrations(baseline, current):
    """Accept exact metadata changes, never arbitrary weakened test assertions."""
    files, changes = {}, {'maximum_version': 0, 'future_version': 0, 'old_fields': 0}
    for saved in sorted((HERE / 'legacy-codec-before').glob('*.py.txt')):
        name = 'tests/unit/' + saved.name[:-4]
        assert sha(saved) == baseline[name], name
        before, after = saved.read_text().splitlines(), (ROOT / name).read_text().splitlines()
        assert len(before) == len(after), name
        edits = []
        for number, (old, new) in enumerate(zip(before, after), 1):
            if old == new:
                continue
            expected, kind = None, None
            if old.startswith('    assert ') and 'SCHEMA_VERSION == 26' in old:
                expected = old.replace('SCHEMA_VERSION == 26', 'SCHEMA_VERSION == 27')
                kind = 'maximum_version'
            elif old == "    assert codec.SCHEMA_VERSION == document['schema_version'] == 26":
                expected = "    assert codec.SCHEMA_VERSION == 27 and document['schema_version'] == 26"
                kind = 'maximum_version'
            elif old.startswith('@pytest.mark.parametrize') and 'version' in old and old.count('27') == 1:
                expected, kind = old.replace('27', '28'), 'future_version'
            elif old.startswith('    assert set(document) == ') and 'fields(ProgramGraph)' in old:
                kind = 'old_fields'
                if "{'call_effect_expansions'}" in old:
                    expected = old.replace("{'call_effect_expansions'}",
                        "{'call_effect_expansions', 'stored_value_writes', 'stored_value_reads'}")
                elif '{"call_effect_expansions"}' in old:
                    expected = old.replace('{"call_effect_expansions"}',
                        '{"call_effect_expansions", "stored_value_writes", "stored_value_reads"}')
                else:
                    expected = old.replace('== {field.name for field in fields(ProgramGraph)} |',
                        "== ({field.name for field in fields(ProgramGraph)} - {'stored_value_writes', 'stored_value_reads'}) |")
            assert expected == new, (name, number, old, new)
            changes[kind] += 1
            edits.append({'line': number, 'kind': kind, 'before': old, 'after': new})
        assert edits and current[name] != baseline[name], name
        files[name] = {'before_sha256': baseline[name], 'after_sha256': current[name], 'edits': edits}
    assert len(files) == 16
    assert changes == {'maximum_version': 15, 'future_version': 7, 'old_fields': 6}
    return files, changes


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
    diagnosis = read(HERE / 'baseline.json')
    assert len(baseline) == 907 and digest(baseline) == design['prior_source_sha256']
    assert diagnosis['sources'] == baseline and diagnosis['base_revision'] == BASE
    assert diagnosis['source_sha256_before'] == diagnosis['source_sha256_after'] == digest(baseline)
    assert diagnosis['state_preservation']['preserved'] is True
    assert not diagnosis['stored_value_api_present'] and diagnosis['native_target_executions'] == 0
    assert diagnosis['script_sha256'] == sha(HERE / 'baseline_probe.py')
    current_digest, current = fingerprint()
    assert set(baseline) <= set(current) and set(current) - set(baseline) == ADDED
    migrations, counts = legacy_migrations(baseline, current)
    assert {name for name in baseline if baseline[name] != current[name]} == PRODUCTS | set(migrations)
    assert all(current[name] == value for name, value in baseline.items()
               if name.startswith('tests/') and name not in migrations)
    old, _ = cases(HERE.parent / 'model_async_terminal_semantics/verified-current/junit.xml', green=True)
    requests, _ = cases(HERE.parent / 'model_async_finished_requests/verified-current/junit.xml', green=True)
    direct, _ = cases(PRIOR / 'verified-current/junit.xml', green=True)
    assert len(direct) == 231
    old |= requests | direct
    assert len(old) == 2135
    expected = read(HERE / 'gate-expectations.json')
    attempts = {}
    for result_path in sorted(HERE.glob('*/result.json')):
        folder = result_path.parent
        result, command = read(result_path), read(folder / 'command.json')
        before, after = read(folder / 'sources.before.json'), read(folder / 'sources.after.json')
        assert before == after and result['source_unchanged']
        assert digest(before) == result['source_sha256_before'] == result['source_sha256_after']
        assert len(before) == result['source_count'] == 913
        assert command['base_revision'] == BASE and command['cwd'] == str(ROOT)
        assert command['runner_sha256'] == sha(HERE / 'run_focused.py')
        assert command['environment'] == {'PYTHONPATH': '.', 'PYTHONDONTWRITEBYTECODE': '1'}
        snapshots = read(folder / 'source-bytes.json')
        assert set(snapshots) == {name for name in before if baseline.get(name) != before[name]}
        for name, saved in snapshots.items():
            assert sha(HERE / saved['path']) == saved['sha256'] == before[name]
        _, summary = cases(folder / 'junit.xml', green=result['returncode'] == 0)
        attempts[folder.name] = {**result, **summary}
    final, summary = cases(HERE / 'verified-current/junit.xml', green=True)
    assert read(HERE / 'verified-current/sources.after.json') == current
    assert attempts['verified-current']['source_sha256_after'] == current_digest
    command = read(HERE / 'verified-current/command.json')['command']
    assert command[4:-1] == read(HERE / 'focused-selection.json')['selectors']
    assert {migrated(identity) for identity in direct} <= final
    known = {migrated(identity) for identity in old}
    assert len(known) == len(old)
    for module, function in FUTURES.items():
        assert sum(cls.split('.')[-1] == module and name == function + '[28]'
                   for cls, name in final) == 1
    new = {identity for identity in final if identity[0].split('.')[-1] in (
        'test_program_stored_value_records', 'test_program_stored_value_codec', 'test_execution_stored_values')}
    assert len(new) == 40 and not new & old
    additional = final - known - new
    for module, _ in additional:
        source_module = next(part for part in module.split('.') if part.startswith('test_'))
        assert 'tests/unit/' + source_module + '.py' in baseline
    assert set(attempts) == set(expected['attempts'])
    for name, values in expected['attempts'].items():
        assert {key: attempts[name][key] for key in values} == values, name
    review = read(HERE / 'independent-review.json')
    assert review['source_sha256'] == current_digest and review['source_frozen']
    assert not review['unresolved_blocking_findings']
    for name, expected_sha in review['reviewed_files'].items():
        assert current[name] == expected_sha, name
    for state in design['protected'].values():
        assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=state['path'], text=True).strip() == state['head']
        assert subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=state['path'], text=True) == state['status']
    catalog = known | final
    assert len(catalog) == len(old) + len(additional) + len(new) == 2304
    catalog_record = {'kind': 'retained test obligations, not a claim all currently pass',
        'scope': 'known affected-case catalog from focused gates; not whole repository collection or phase denominator',
        'prior_catalog': len(old), 'additional_preexisting': len(additional), 'new': len(new),
        'total': len(catalog), 'currently_retested': len(final),
        'identities': [list(identity) for identity in sorted(catalog)]}
    if writing:
        (HERE / 'case-catalog.json').write_text(json.dumps(catalog_record, indent=2) + '\n')
    else:
        assert read(HERE / 'case-catalog.json') == catalog_record
    names = [path for path in HERE.rglob('*') if path.is_file() and path.name != 'checkpoint.json']
    names += [ROOT / name for name in expected['bound_documents']]
    record = {'status': 'VERIFIED_CONDITIONAL_STORED_VALUE_RELATIONS',
        'base_revision': BASE, 'source_sha256': current_digest, 'source_files': len(current),
        'current_focused': summary, 'new_case_identities': len(new),
        'prior_case_catalog_retained': len(old), 'prior_full_catalog_rerun': False,
        'previous_direct_obligations_retested': len(direct),
        'prior_catalog_identities_retested_after_explicit_migration': len(final & known),
        'additional_preexisting_case_identities_now_selected': len(additional),
        'current_case_catalog_size': len(catalog),
        'case_catalog_includes_prior_not_currently_retested_obligations': True,
        'case_catalog_is_whole_repository': False,
        'case_id_migrations': [{'before': list(before), 'after': list(migrated(before))}
                               for before in sorted(old) if before != migrated(before)],
        'legacy_test_line_migration_counts': counts, 'legacy_test_migrations': migrations,
        'all_prior_fixtures_unchanged': True, 'other_prior_tests_unchanged': True,
        'program_schema': 27, 'execution_schema': 8,
        'accepted_families': design['accepted_families'], 'open_families': design['open_families'],
        'm2_denominator': design['m2_denominator'], 'attempts': attempts,
        'f19_family_complete': False, 'first_stage_complete': False,
        'automatic_stored_reference_provenance_complete': False,
        'native_identity_verified': False, 'source_runtime_verified': False,
        'transformation_authorized': False, 'new_lewm_speedup': None,
        'files': {str(path.relative_to(ROOT)): sha(path) for path in sorted(names)}}
    if writing:
        (HERE / 'checkpoint.json').write_text(json.dumps(record, indent=2) + '\n')
    else:
        assert read(HERE / 'checkpoint.json') == record
    print(json.dumps({key: value for key, value in record.items()
                      if key not in ('files', 'legacy_test_migrations', 'attempts')}))


if __name__ == '__main__':
    main()
