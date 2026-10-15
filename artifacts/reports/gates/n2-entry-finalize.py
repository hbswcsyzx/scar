"""Assemble the frozen gate receipts; never runs or rewrites a target program."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def main():
    sys.path.insert(0, str(Path.cwd()))
    from scripts.run_gate import fingerprint
    root = Path('artifacts/reports/gates')
    load = lambda name: json.loads((root / name).read_text())
    gate = load('n2-entry-verified.json')
    regression = load('n2-entry-full-regression.json')
    external = load('n2-entry-lewm-receipt.json')
    assert gate['status'] == regression['status'] == 'PASS'
    assert external['status'] == 'PASS_RUNTIME_SOURCE_BRIDGE'
    assert gate['revision'] == regression['revision'] == external['revision']
    assert gate['source_sha256'] == regression['source_sha256'] == external['source_sha256'] == fingerprint()[0]
    assert gate['worktree_status'] == regression['worktree_status'] == external['initial_worktree'] == ''
    assert gate['source_unchanged_during_test'] and regression['source_unchanged'] and external['source_unchanged']
    assert external['target_unchanged'] and external['trace_unchanged'] and external['all_read_sources_unchanged']
    assert not external['target_executed'] and not external['whole_program_model_established'] and not external['optimization_verified']
    assert not external['file_preparation_issues']
    target = Path('/home/zyf/AAA/le-wm')
    git = lambda *args: subprocess.check_output(['git', *args], cwd=target, text=True).strip()
    assert git('rev-parse', 'HEAD') == external['target_head']
    assert git('status', '--porcelain') == external['target_status_after'] == ''
    raw_xml = gzip.decompress((root / 'n2-entry-full-regression.xml.gz').read_bytes())
    assert hashlib.sha256(raw_xml).hexdigest() == regression['xml_sha256']
    files = [
        'n2-entry-verified.json', 'n2-entry-verified.md',
        'n2-entry-full-regression.json', 'n2-entry-full-regression.xml.gz',
        'n2-entry-full-regression.stdout.txt', 'n2-entry-full-regression.stderr.txt',
        'n2-entry-full-regression.time.txt', 'n2-entry-lewm-receipt.json',
        'n2-entry-lewm-progress.json', 'n2-entry-lewm-inventory.json.gz',
        'n2-entry-lewm-comparison.json', 'n2-entry-trace-development.json',
        'n2-entry-source-pressure.py', 'n2-entry-compare.py', 'n2-entry-finalize.py',
        'n2-entry-development-archives.json',
    ]
    files += ['n2-entry-lewm-' + stage + '.' + ext
              for stage in ('analysis', 'replay') for ext in ('stdout.txt', 'stderr.txt', 'time.txt')]
    files += [Path(row['physical_path']).name for row in load('n2-entry-development-archives.json')]
    evidence = [{'path': str(root / name), 'sha256': hashlib.sha256((root / name).read_bytes()).hexdigest(),
                 'bytes': (root / name).stat().st_size} for name in files]
    inventory_digest = next(row['sha256'] for row in evidence if row['path'].endswith('-inventory.json.gz'))
    assert inventory_digest == external['artifact_sha256']
    gate_cases = {(case['class'], case['name']) for criterion in gate['criteria']
                  for item in criterion['evidence'] for case in item['cases']}
    report = {
        'schema': 'scar.autonomous-acceptance', 'gate': 'N2.entry', 'status': 'PASS_BOUNDED_RUNTIME_SOURCE_BRIDGE',
        'revision': gate['revision'], 'source_sha256': gate['source_sha256'],
        'gate_cases': len(gate_cases), 'regression_tests': int(regression['suite']['tests']),
        'external_status': external['status'], 'source_summary': external['summary'],
        'target_executed_this_gate': False, 'whole_program_model_established': False,
        'optimization_authorized': False, 'workload_speedup_verified': False,
        'evidence_files': evidence,
    }
    assert report['gate_cases'] == 429 and report['regression_tests'] == 1477
    (root / 'n2-entry-acceptance.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('evidence_files', 'source_summary')}))


if __name__ == '__main__':
    main()
