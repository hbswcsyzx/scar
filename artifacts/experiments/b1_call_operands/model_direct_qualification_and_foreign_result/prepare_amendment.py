"""Record the frozen F12 supplement without changing the original design."""
import hashlib
import json
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = Path.cwd()
record = json.loads((HERE / 'design-amendment.json').read_text())
for field, digest in (('amendment', 'amendment_sha256'),
                      ('literal_clarification', 'literal_clarification_sha256')):
    assert hashlib.sha256((ROOT / record[field]).read_bytes()).hexdigest() == record[digest]
path = HERE / record['amended_selection']
assert not path.exists()
selection = json.loads((HERE / record['original_selection']).read_text())
original = hashlib.sha256((HERE / record['original_selection']).read_bytes()).hexdigest()
selection['selectors'].append(record['additional_test_file'])
selection['reason'] += ' Frozen F12 amendment adds only native self/noW and known bad general returns, including both original literal source representations.'
selection['amendment'] = record
path.write_text(json.dumps(selection, indent=2) + '\n')
assert original == hashlib.sha256((HERE / record['original_selection']).read_bytes()).hexdigest()
print(json.dumps({'amendment_verified': True, 'original_design_unchanged': True,
    'additional_cases_planned': record['additional_finite_cases'], 'tests_started': 0}))
