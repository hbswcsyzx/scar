"""Record the actual existing contract gap; execute no workload/native target."""
from dataclasses import fields
import hashlib
import json
from pathlib import Path

from scripts.run_gate import fingerprint
from scar.ir.program.model import StateAccess
from scar.ir.program.state_addresses import StateAddressRefinement
from scar.ir.execution.content import ContentRead
from scar.ir.execution.query import ExecutionIndex
from tests.unit.test_execution_state_preservation import _preservation_execution

before, sources = fingerprint()
program, model, details = _preservation_execution()
index = ExecutionIndex(model, program)
example = details['examples'][0]
result = index.state_preservation(example['start'], example['end'],
    locations=(details['world'],), budget=65536)
after, final = fingerprint()
assert sources == final and before == after
assert result['preserved'] is True
record = {
    'base_revision': '5fd5a7f0b246f72ff708f53ba000728817a8feca',
    'source_sha256_before': before, 'source_sha256_after': after,
    'source_files': len(sources), 'sources': sources,
    'contract_fields': {cls.__name__: [field.name for field in fields(cls)]
                        for cls in (StateAccess, StateAddressRefinement, ContentRead)},
    'state_preservation': {'preserved': result['preserved'],
        'reached': result['reached'], 'blockers': result['blockers'],
        'budget': result['budget']},
    'stored_value_api_present': hasattr(index, 'stored_value_sources'),
    'meaning': 'Transparent state interval does not establish any store payload to load-result relation; the inspected existing records have no such contract.',
    'native_target_executions': 0, 'transformation_authorized': False,
    'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
}
Path(__file__).with_name('baseline.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({key: value for key, value in record.items() if key != 'sources'}))
