"""Describe actual unqualified provider slots from retained metadata only."""
from collections import Counter
import gzip
import json
import math
from pathlib import Path

root = Path(__file__).resolve().parent
meta_path = next((root / 'trace').glob('tensor-physical-meta.*.json'))
meta = json.loads(meta_path.read_bytes())
raw_path = Path(meta['file']['path'])
if not raw_path.exists():
    raw_path = raw_path.with_name(raw_path.name + '.gz')
opener = gzip.open if raw_path.suffix == '.gz' else open
groups, examples = Counter(), {}
total = missing = 0
with opener(raw_path, 'rb') as stream:
    for line in stream:
        row = json.loads(line)
        if row['kind'] != 'MARKER':
            continue
        for argument in row['arguments']:
            total += 1
            tensor = argument['metadata']
            if (type(tensor.get('provider_allocation_id')) is int
                and tensor['provider_allocation_id'] > 0
                and type(tensor.get('storage_data_ptr')) is int
                and tensor['storage_data_ptr'] > 0
                and tensor.get('status') == 'OBSERVED' and not tensor.get('gaps')):
                continue
            missing += 1
            sizes = tensor.get('sizes')
            empty = (type(sizes) is list and all(type(size) is int and size >= 0 for size in sizes)
                     and math.prod(sizes) == 0)
            features = {'device': tensor.get('device', {}).get('text'),
                'status': tensor.get('status'), 'empty_shape': empty,
                'storage_data_ptr': tensor.get('storage_data_ptr'),
                'provider_allocation_id': tensor.get('provider_allocation_id'),
                'gaps': tensor.get('gaps')}
            key = json.dumps(features, sort_keys=True)
            groups[key] += 1
            examples.setdefault(key, {'artifact': meta['file'], 'line': row['index'],
                'pointer_within_line': '/arguments/' + str(argument['argument_ordinal'])})
assert total == meta['counts']['marker_argument_slots']
report = {'schema': 'scar.physical-slot-frontier-description', 'schema_version': 1,
    'source': str(raw_path), 'original_total_slots': total, 'unqualified_slots': missing,
    'groups': [{'features': json.loads(key), 'count': count, 'example': examples[key]}
               for key, count in groups.items()],
    'tensor_contents_read': False, 'target_executed': False,
    'allocation_mapping_invented': False, 'whole_model_established': False}
(root / 'physical-frontiers.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
print(json.dumps({key: value for key, value in report.items() if key != 'source'}, sort_keys=True))
