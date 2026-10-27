"""Rank actual OS coverage gaps; does not change model or target."""
from collections import Counter, defaultdict
import gzip
from hashlib import sha256
import json
from pathlib import Path
import time

root = Path(__file__).resolve().parent
path = root / 'result' / 'os' / 'os-resources.json.gz'
started = time.perf_counter()
stored = path.read_bytes()
with gzip.GzipFile(fileobj=__import__('io').BytesIO(stored)) as stream:
    fragment = json.load(stream)
outside = Counter()
examples = {}
for artifact, line, classification, syscall, reason in fragment['line_classifications']:
    if reason == 'outside_fd_profile':
        outside[syscall] += 1
        examples.setdefault(syscall, {'artifact': fragment['artifacts'][artifact],
                                     'locator': '#/lines/' + str(line)})
gap_names = Counter()
gap_examples = {}
for row in fragment['gaps']:
    name = row.get('code', row.get('kind', 'UNSPECIFIED'))
    gap_names[name] += 1
    gap_examples.setdefault(name, row)
report = {'schema': 'scar.observed-os-resource-frontiers', 'schema_version': 1,
    'source': {'path': str(path), 'stored_bytes': len(stored), 'stored_sha256': sha256(stored).hexdigest()},
    'summary': fragment['summary'],
    'outside_fd_profile': [{'syscall': name, 'count': count, 'example': examples[name]}
                           for name, count in outside.most_common()],
    'resource_gaps': [{'code': name, 'count': count, 'example': gap_examples[name]}
                      for name, count in gap_names.most_common()],
    'observation_fields': sorted(fragment['observations'][0]) if fragment['observations'] else [],
    'target_executed': False, 'model_modified': False,
    'whole_model_established': False, 'elapsed_s': time.perf_counter() - started}
assert sum(outside.values()) == fragment['summary']['unconnected_line_reasons']['outside_fd_profile']
(root / 'resource-frontiers.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
print(json.dumps({'outside_fd_profile': dict(outside.most_common()), 'resource_gaps': dict(gap_names),
                  'observation_fields': report['observation_fields'], 'elapsed_s': report['elapsed_s']}, sort_keys=True))
