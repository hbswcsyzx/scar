"""Check immutable gate receipts and archive only the bounded S0 evidence."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def main():
    root = Path('artifacts/reports/gates')
    load = lambda name: json.loads((root / ('n2-schedule-' + name)).read_text())
    gate, regression, external, legacy, comparison = map(load, (
        'verified.json', 'full-regression.json', 'lewm-receipt.json',
        'legacy-receipt.json', 'lewm-comparison.json'))
    sys.path.insert(0, str(Path.cwd()))
    from scripts.run_gate import fingerprint
    assert gate['status'] == regression['status'] == legacy['status'] == 'PASS'
    assert external['status'] == 'PASS_GLOBAL_DEMAND_SCHEDULE'
    assert len({gate['revision'], regression['revision'], external['revision'], legacy['current_revision']}) == 1
    assert len({gate['source_sha256'], regression['source_sha256'], external['source_sha256'], legacy['source_sha256'], fingerprint()[0]}) == 1
    assert gate['worktree_status'] == regression['worktree_status'] == external['initial_worktree'] == ''
    assert gate['source_unchanged_during_test'] and regression['source_unchanged'] and legacy['source_unchanged']
    assert all(external[key] for key in ('source_unchanged','target_unchanged','trace_unchanged','all_read_sources_unchanged'))
    assert not external['file_preparation_issues'] and not external['target_executed']
    assert comparison['same_runtime_raw_evidence']
    assert len(comparison['previously_budget_deferred_observed_transitions']) == 27
    assert 'NOT_ATTEMPTED' not in comparison['previously_budget_deferred_now_statuses']
    assert not external['summary']['expansion']['unavailable_contexts']
    git = lambda *args: subprocess.check_output(['git',*args],cwd='/home/zyf/AAA/le-wm',text=True).strip()
    assert git('rev-parse','HEAD') == external['target_head'] and git('status','--porcelain') == ''
    raw_xml = gzip.decompress((root/'n2-schedule-full-regression.xml.gz').read_bytes())
    assert hashlib.sha256(raw_xml).hexdigest() == regression['xml_sha256']
    suffixes = ['verified.json','verified.md','full-regression.json','full-regression.xml.gz',
        'full-regression.stdout.txt','full-regression.stderr.txt','full-regression.time.txt',
        'lewm-inventory.json.gz','lewm-receipt.json','lewm-progress.json','lewm-comparison.json',
        'legacy-receipt.json','legacy-v2.json.gz','legacy-input/entry.py','legacy-input/events.jsonl',
        'source-pressure.py','compare.py','legacy.py','finalize.py','development-archives.json']
    suffixes += ['lewm-' + stage + '.' + ext for stage in ('analysis','replay')
                 for ext in ('stdout.txt','stderr.txt','time.txt')]
    paths = [root / ('n2-schedule-' + name) for name in suffixes]
    paths += [Path(row['physical_path']) for row in load('development-archives.json')]
    evidence = [{'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                 'bytes':path.stat().st_size} for path in paths]
    assert hashlib.sha256((root/'n2-schedule-lewm-inventory.json.gz').read_bytes()).hexdigest() == external['artifact_sha256']
    gate_cases = {(c['class'],c['name']) for criterion in gate['criteria']
                  for item in criterion['evidence'] for c in item['cases']}
    report = {'schema':'scar.autonomous-acceptance','gate':'N2.schedule',
        'status':'PASS_BOUNDED_GLOBAL_DEMAND_SCHEDULE','revision':gate['revision'],
        'source_sha256':gate['source_sha256'],'gate_cases':len(gate_cases),
        'regression_tests':int(regression['suite']['tests']),
        'previously_budget_deferred_now_statuses':comparison['previously_budget_deferred_now_statuses'],
        'source_summary':external['summary'],'whole_program_model_established':False,
        'target_executed_this_gate':False,'transformation_authorized':False,
        'workload_speedup_verified':False,'evidence_files':evidence}
    assert report['gate_cases'] == 457 and report['regression_tests'] == 1505
    (root/'n2-schedule-acceptance.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:value for key,value in report.items() if key not in ('evidence_files','source_summary')}))


if __name__ == '__main__':
    main()
