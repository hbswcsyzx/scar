"""Bounded terminal-record review; does not replay source or execute the target."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode()


def load(path):
    return json.loads(path.read_text())


def main():
    summary = load(HERE / 'summary.json')
    manifest = load(HERE / 'worker/manifest.json')
    records = [json.loads(line) for line in (HERE / 'worker/attempts.jsonl').read_text().splitlines()]
    assert 'Exit status: 0' in (HERE / 'run.time.txt').read_text()
    assert len(records) == 12 and manifest['program_paths'] == []
    observed, emitted, keys = Counter(), 0, set()
    for row in records:
        terminal_path = Path(row['result_artifact']['path'])
        payload = terminal_path.read_bytes()
        assert sha256(payload).hexdigest() == row['result_artifact']['sha256']
        assert len(payload) == row['result_artifact']['bytes']
        assert json.loads(payload) == {k: v for k, v in row.items() if k != 'result_artifact'}
        assert row['work_key'] == sha256(canonical(row['work_input'])).hexdigest()
        assert row['work_key'] not in keys
        keys.add(row['work_key'])
        returned = load(terminal_path.parent / 'returned-metadata.json')
        ready = load(terminal_path.parent / 'ready.json')
        assert ready['code_type_verified'] and row['code_type_verified']
        assert row['code_witness']['captured'] == row['work_input']['captured']
        assert not row['code_witness']['runtime_code_instance_established']
        assert row['program'] is None and not returned['graph_present']
        assert returned['operations_emitted'] == row['operations_emitted'] == row['budget_charge']
        assert row['status'] == 'UNSUPPORTED' and not row['target_executed']
        observed[row['status']] += 1
        emitted += row['operations_emitted']
    assert dict(observed) == manifest['counts'] == {'UNSUPPORTED': 12}
    assert emitted == manifest['budget_operation_charge'] == 1163
    assert summary['plan_summary']['bodies'] == 2217
    assert summary['plan_summary']['current_groups'] == 817
    assert summary['plan_summary']['current_calls'] == 100438
    assert manifest['code_witness_counts']['compile_attempts'] == 0
    assert not manifest['first_stage_complete'] and not manifest['current_run_integrated']
    result = {'status': 'PASS_TERMINAL_RECORD_CONSERVATION_ONLY', 'attempts': len(records),
              'actual_emitted_operations': emitted, 'successful_programs': 0,
              'source_replayed': False, 'target_executed': False,
              'first_stage_complete': False}
    (HERE / 'root-terminal-review.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
