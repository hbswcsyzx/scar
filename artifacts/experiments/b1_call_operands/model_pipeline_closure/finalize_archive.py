"""Archive R3.3 evidence; starts zero tests, workloads or profilers."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PRIOR = HERE.parent / 'model_pipeline_composition'


def read(path):
    return json.loads(path.read_text())


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def witness_summary():
    capture = HERE / 'witness_capture/attempt001'
    command = read(capture / 'command.json')
    assert command['script_sha256'] == hashlib.sha256(
        (ROOT / 'scripts/witness_io_pipeline.py').read_bytes()).hexdigest()
    assert [row['case'] for row in command['commands']] == ['file', 'file_raise', 'pending_raise']
    assert all(row['returncode'] == 0 for row in command['commands'])
    result = {}
    for case in ('file', 'file_raise', 'pending_raise'):
        raw = read(capture / (case + '.stdout.json'))
        assert raw['case'] == case and raw['schema'] == 'scar.io-pipeline-witness'
        assert raw['worker_returncode'] == 0 and raw['owned_workspace_removed_after_worker_exit']
        assert not Path(raw['owned_workspace']).exists()
        assert not raw['source_runtime_verified'] and not raw['transformation_authorized']
        assert (capture / (case + '.stderr.log')).stat().st_size == 0
        observed = raw['observed']
        if case in ('file', 'file_raise'):
            assert observed['accepted_bytes'] == observed['requested_bytes'] == observed['final_bytes'] == 8
            assert observed['visible_before_explicit_flush_bytes'] == 0 and observed['closed']
            assert observed['final_sha256'] == hashlib.sha256(b'BCDEFGHI').hexdigest()
            assert observed['explicit_flush_returned'] == observed['fsync_returned'] == (case == 'file')
            assert observed['host_exception'] == (None if case == 'file' else 'HostFailure')
            if case == 'file':
                assert observed['visible_after_explicit_flush_bytes'] == 8
        else:
            assert not observed['work_done_at_host_raise'] and observed['buffer_nonzero_bytes_at_host_raise'] == 0
            assert observed['work_done'] and observed['this_view_released']
            assert observed['actual_bytes'] == 4 < observed['requested_bytes'] == 8
            assert observed['work_exception'] == 'PartialWorkFailure'
            assert observed['final_sha256'] == hashlib.sha256(b'BCDE' + bytes(4)).hexdigest()
            positions = {(r['action'], r['phase']): r['sequence'] for r in raw['events']}
            assert positions['submit_wrapper', 'raise'] < positions['work', 'partial_write']
            assert positions['work', 'partial_write'] < positions['borrow', 'release']
            assert positions['borrow', 'release'] < positions['work_observer', 'terminal']
        result[case] = observed
    return {'scope': 'Actual bounded owned OS observations; no automatic IR binding, GPU or durability proof.',
            'script_sha256': command['script_sha256'], 'observed': result,
            'source_runtime_verified': False, 'transformation_authorized': False}


def final_pipeline_budget():
    matches = []
    for case in ET.parse(HERE / 'full/results.xml').iter('testcase'):
        if case.get('classname') == 'tests.integration.test_execution_io_pipeline' and case.get('name') == 'test_complete_pipeline_uses_one_program_and_exact_dynamic_calls':
            for prop in case.findall('./properties/property'):
                if prop.get('name') == 'composition_scale_and_budget':
                    matches.append(json.loads(prop.get('value')))
    assert len(matches) == 1
    result = matches[0]
    assert result['budget']['limit'] == 131072 and not result['budget']['truncated']
    assert result['budget']['used'] <= result['budget']['limit'] and result['range_bytes'] == 8
    return result


def main():
    component, full = (read(HERE / p) for p in ('component/final/report.json', 'full/report.json'))
    before, after = (read(HERE / f'full/source.{phase}.json') for phase in ('before', 'after'))
    assert component['status'] == full['status'] == 'PASS'
    assert before == after and not before['worktree_status']
    assert before['files'] == component['tested_files']
    previous = read(PRIOR / 'full/source.before.json')
    old_cases, cases = (read(base / 'full/cases.json') for base in (PRIOR, HERE))
    identity = lambda case: (case['class'], case['name'])
    old_set, case_set = ({identity(case) for case in rows} for rows in (old_cases, cases))
    assert len(old_cases) == len(old_set) == 5011 and old_set <= case_set
    missing_sources = sorted(set(previous['files']) - set(before['files']))
    changed_fixtures = [p for p, sha in previous['fixture_sha256'].items()
                        if before['fixture_sha256'].get(p) != sha]
    assert not missing_sources and not changed_fixtures
    dump(HERE / 'witness-summary.json', witness_summary())
    dump(HERE / 'pipeline-budget.final.json', final_pipeline_budget())
    dump(HERE / 'preservation.json', {
        'previous_cases': len(old_set), 'preserved_previous_cases': len(old_set & case_set),
        'missing_cases': sorted(old_set - case_set), 'new_cases': sorted(case_set - old_set),
        'previous_source_files': len(previous['files']), 'current_source_files': len(before['files']),
        'removed_source_files': missing_sources,
        'unchanged_previous_source_files': sum(before['files'][p] == sha for p, sha in previous['files'].items()),
        'extended_previous_source_files': sorted(p for p, sha in previous['files'].items() if before['files'][p] != sha),
        'new_source_files': sorted(set(before['files']) - set(previous['files'])),
        'previous_fixtures': len(previous['fixture_sha256']), 'current_fixtures': len(before['fixture_sha256']),
        'changed_previous_fixtures': changed_fixtures,
    })
    documents = ['README.md', 'docs/STATUS.md', 'docs/ROADMAP.md',
        'docs/FIRST_STAGE_COMPLETION_MATRIX.md', 'docs/WHOLE_PROGRAM_MODEL_PLAN.md',
        'docs/M1_RESOURCE_COMPOSITION_PLAN.md', 'docs/M1_PIPELINE_COMPOSITION_PLAN.md',
        'docs/M1_PIPELINE_COMPOSITION_API.md', 'docs/M1_PIPELINE_COMPOSITION_ACCEPTANCE.md',
        'docs/M1_PIPELINE_CLOSURE_PLAN.md', 'docs/M1_PIPELINE_CLOSURE_API.md',
        'docs/M1_PIPELINE_CLOSURE_ACCEPTANCE.md']
    component_cases = {(case['class'], case['name']) for criterion in component['criteria']
                       for item in criterion['evidence'] for case in item['cases']}
    dump(HERE / 'closure.json', {
        'scope': 'R3.3 generic buffered pipeline model and bounded OS observations; complete M0-M2 and automatic recovery remain open',
        'implementation_revision': before['revision'], 'source_sha256': before['source_sha256'],
        'source_files': len(before['files']), 'criteria': len(component['criteria']),
        'component_cases': len(component_cases), 'full_cases': len(cases),
        'component_seconds': component['duration_seconds'], 'full_seconds': full['duration_seconds'],
        'scope_inventory_complete': False, 'source_runtime_verified': False,
        'value_identity_verified': False, 'transformation_authorized': False,
        'new_lewm_speedup_measurement': False,
        'documents': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in documents},
    })
    files = {str(p.relative_to(HERE)): {'bytes': p.stat().st_size,
        'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in sorted(HERE.rglob('*')) if p.is_file() and p != HERE / 'manifest.json'}
    dump(HERE / 'manifest.json', {'schema': 'scar.pipeline-closure-archive', 'schema_version': 1, 'files': files})
    print(json.dumps({'archived_files': len(files), 'component_cases': len(component_cases),
                     'full_cases': len(cases), 'preserved_previous_cases': len(old_set)}))


if __name__ == '__main__':
    main()
