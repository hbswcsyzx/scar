from pathlib import Path
import hashlib
import json
from scar.analysis.call_operand_reader import read_call_operands
from scar.analysis.python_call_targets import read_python_call_targets

root = Path(__file__).resolve().parent
out = root / 'process_snapshot'
trace = read_call_operands(out, root)
targets = read_python_call_targets(trace)
assert not trace.issues
closes = [json.loads(p.read_text()) for p in sorted(out.glob('*.snapshot-close.json'))]
assert len(closes) == 5
writers = {c['writer_thread_id'] for c in closes}
for close in closes:
    counts = close['counts']
    assert close['complete'] and not close['writer_thread_alive']
    assert counts['accepted_records'] == counts['written_records']
    assert not any(counts['rejected'].values()) and counts['writer_error'] is None
streams = []
for p in sorted(out.glob('*.snapshot-receipt.json')):
    result = json.loads(p.read_text())
    output = result['output']
    assert result['complete'] and output['published']
    content = Path(output['uri']).read_bytes()
    assert len(content) == output['raw_bytes']
    assert hashlib.sha256(content).hexdigest() == output['sha256']
    close = json.loads(Path(str(p).replace('.snapshot-receipt.json', '.snapshot-close.json')).read_text())
    assert result['source']['sha256'] == close['source']['sha256']
    streams.append({'path': str(p), 'journal': close['source'], 'output': output})
for p in out.glob('call-events.*.jsonl'):
    for line in p.read_bytes().splitlines():
        assert json.loads(line)['thread_id'] not in writers
assert json.loads((root / 'process_snapshot.stdout').read_text()) == {'result': [46950, 645]}
result = {'status': 'VERIFIED_SCOPED_CAPTURE_TRANSPORT', 'capture_profile': 'process-ports',
    'frame_entries': len(trace.entries), 'frame_exits': len(trace.exits),
    'attempts': len(trace.attempts), 'handshakes': len(trace.handshakes),
    'observation_issues': len(trace.issues), 'targets': len(targets.targets),
    'target_entries': len(targets.entries), 'target_gaps': len(targets.gaps),
    'writer_threads_observed_as_application': False, 'all_writers_closed': True,
    'streams': streams, 'program_output': [46950, 645],
    'baseline_windows_had_observation_gap': 'INSTRUCTION_FRAME_UNAVAILABLE',
    'micro_performance_or_lewm_speedup_measured': False, 'whole_program_complete': False}
with (root / 'RESULT.json').open('x') as file:
    json.dump(result, file, indent=2)
print(json.dumps({k: v for k, v in result.items() if k != 'streams'}, indent=2))
