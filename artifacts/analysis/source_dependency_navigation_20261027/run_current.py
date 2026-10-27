"""One real retained-run dependency navigation, without target execution."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import resource
import time
from scar.analysis.source_dependencies import SourceDependencySession

parser = argparse.ArgumentParser()
parser.add_argument('--model', required=True)
parser.add_argument('--sha256', required=True)
parser.add_argument('--out', required=True)
args = parser.parse_args()
out = Path(args.out)
out.mkdir(parents=True, exist_ok=False)
files = [Path('scar/analysis/source_dependencies.py'), Path('scar/analysis/source_return_bindings.py'),
         Path('scar/analysis/retained_source_call_ports.py'), Path('scar/cli.py')]
before = {str(p): sha256(p.read_bytes()).hexdigest() for p in files}
start = time.perf_counter()
session = SourceDependencySession(args.model, expected_sha256=args.sha256)
results = {}
for label, ordinal, actual, receiver in [('explicit', 0, 0, False), ('receiver', 1, None, True)]:
    result = session.argument_origins(ordinal, actual, receiver=receiver)
    (out / (label + '.json')).write_text(json.dumps(result, indent=2) + '\n')
    results[label] = {'nodes': len(result['nodes']), 'routes': len(result['routes']),
        'route_kinds': dict(Counter(r['kind'] for r in result['routes'])),
        'frontiers': dict(Counter(r['reason'] for r in result['frontiers'])),
        'caller_result_consumers': len(result['caller_result_consumers']),
        'truncated': result['truncated'], 'costs': result['costs']}
after = {str(p): sha256(p.read_bytes()).hexdigest() for p in files}
if before != after:
    raise RuntimeError('source changed during the query')
report = {'status': 'PASS', 'model': args.model, 'model_sha256': args.sha256,
          'source_sha256': before, 'results': results,
          'elapsed_seconds': time.perf_counter() - start,
          'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
          'new_capture_or_target_execution': False, 'producer_inputs_replayed': False,
          'whole_program_complete': False, 'transformation_authorized': False}
(out / 'RESULT.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
