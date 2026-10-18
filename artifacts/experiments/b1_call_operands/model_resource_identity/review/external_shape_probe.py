"""Malformed supplied mutable external graph must remain an invalid input."""
import hashlib
import json
from pathlib import Path
import sys

from scar.ir.execution.validation import validate
from tests.fixtures.execution_resource_graphs import resource_execution_with_allocation

files = ('scar/ir/execution/validation.py', 'scar/ir/v2/values.py', 'scar/ir/v2/_validation.py')
result = {'python': sys.version, 'source_hashes': {
    name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in files}}
program, model, catalog = resource_execution_with_allocation()
next(iter(catalog.values())).allocations = []
try:
    report = validate(model, program, value_graphs=catalog)
    result['result'] = {'valid': report.valid, 'issues': [row.code for row in report.issues]}
except Exception as error:
    result['result'] = {'exception': type(error).__name__, 'message': str(error)}
result['source_hashes_after'] = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in files}
result['torch_imported'] = 'torch' in sys.modules
text = json.dumps(result, indent=2, sort_keys=True) + '\n'
Path(__file__).with_name('external_shape_results.json').write_text(text)
print(text, end='')
