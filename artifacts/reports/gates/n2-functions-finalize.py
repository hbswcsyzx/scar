"""Check frozen receipts and create a bounded evidence manifest."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def main():
    root = Path('artifacts/reports/gates')
    load = lambda name: json.loads((root/('n2-functions-'+name)).read_text())
    gate, full, external, legacy, comparison = map(load, (
        'verified.json','full-regression.json','lewm-receipt.json','legacy-receipt.json','lewm-comparison.json'))
    sys.path.insert(0,str(Path.cwd()))
    from scripts.run_gate import fingerprint
    assert gate['status'] == full['status'] == legacy['status'] == 'PASS'
    assert external['status'] == 'PASS_BOUND_FUNCTION_INTERFACES'
    assert len({gate['revision'],full['revision'],external['revision'],legacy['current_revision']}) == 1
    assert len({gate['source_sha256'],full['source_sha256'],external['source_sha256'],
                legacy['current_source_sha256_before'],legacy['current_source_sha256_after'],fingerprint()[0]}) == 1
    assert gate['worktree_status'] == full['worktree_status'] == external['initial_worktree'] == ''
    assert gate['source_unchanged_during_test'] and full['source_unchanged'] and legacy['require_stable_source']
    assert all(external[k] for k in ('source_unchanged','target_unchanged','trace_unchanged','all_read_sources_unchanged'))
    assert not external['file_preparation_issues'] and not external['target_executed']
    assert all(comparison[k] for k in ('same_source_snapshots','same_runtime_raw_evidence','same_inventory_budget'))
    connectivity = load('lewm-connectivity.json')
    assert connectivity['summary']['connection_issue_count'] == 0
    assert not connectivity['summary']['join_integrity_errors']
    assert connectivity['previous_signature_blockers']['same_definition_source_references']
    assert not connectivity['target_executed'] and not connectivity['edges_added']
    assert not external['summary']['expansion']['unknown_construction_costs']
    assert not external['summary']['expansion']['unavailable_contexts']
    git = lambda *a: subprocess.check_output(['git',*a],cwd=external['target_project_root'],text=True).strip()
    assert git('rev-parse','HEAD') == external['target_head'] and git('status','--porcelain') == ''
    raw_xml = gzip.decompress((root/'n2-functions-full-regression.xml.gz').read_bytes())
    assert hashlib.sha256(raw_xml).hexdigest() == full['xml_sha256']
    dev = []
    for name in ('initial','integration','repaired'):
        path = root/('n2-functions-development-'+name+'.xml')
        archive = Path(str(path)+'.gz')
        if path.exists():
            data = path.read_bytes()
            archive.write_bytes(gzip.compress(data,mtime=0))
            assert gzip.decompress(archive.read_bytes()) == data
            path.unlink()
        data = gzip.decompress(archive.read_bytes())
        dev.append({'path':str(archive),'raw_sha256':hashlib.sha256(data).hexdigest(),'raw_bytes':len(data)})
    (root/'n2-functions-development-archives.json').write_text(json.dumps(dev,indent=2)+'\n')
    suffixes = ['verified.json','verified.md','full-regression.json','full-regression.xml.gz',
        'full-regression.stdout.txt','full-regression.stderr.txt','full-regression.time.txt',
        'lewm-inventory.json.gz','lewm-receipt.json','lewm-progress.json','lewm-comparison.json',
        'lewm-connectivity.json','connectivity-audit.py',
        'legacy-receipt.json','legacy-v1.json.gz','legacy-v2.json.gz','legacy-v3.json.gz',
        'legacy-input/entry.py','legacy-input/events-v2.jsonl','legacy-input/events-v3.jsonl',
        'source-pressure.py','compare.py','legacy.py','regression.py','finalize.py','development-archives.json']
    suffixes += ['lewm-'+stage+'.'+ext for stage in ('analysis','replay') for ext in ('stdout.txt','stderr.txt','time.txt')]
    paths = [root/('n2-functions-'+name) for name in suffixes] + [Path(row['path']) for row in dev]
    paths.append(Path('artifacts/reports/maintenance/disk-cleanup-20261015.json'))
    evidence = [{'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}
                for path in paths]
    assert hashlib.sha256((root/'n2-functions-lewm-inventory.json.gz').read_bytes()).hexdigest() == external['artifact_sha256']
    cases = {(c['class'],c['name']) for row in gate['criteria'] for item in row['evidence'] for c in item['cases']}
    acceptance = {'schema':'scar.autonomous-acceptance','gate':'N2.function-interfaces',
        'status':'PASS_BOUND_FUNCTION_INTERFACES','revision':gate['revision'],'source_sha256':gate['source_sha256'],
        'gate_cases':len(cases),'regression_tests':int(full['suite']['tests']),
        'source_summary':external['summary'],'previous_signature_blocker_after_statuses':comparison['previous_signature_blocker_after_statuses'],
        'connectivity_summary':connectivity['summary'],
        'whole_program_model_established':False,'target_executed_this_gate':False,
        'live_call_binding_established':False,'transformation_authorized':False,'workload_speedup_verified':False,
        'evidence_files':evidence}
    (root/'n2-functions-acceptance.json').write_text(json.dumps(acceptance,indent=2)+'\n')
    print(json.dumps({k:v for k,v in acceptance.items() if k not in ('source_summary','evidence_files')}))


if __name__ == '__main__':
    main()
