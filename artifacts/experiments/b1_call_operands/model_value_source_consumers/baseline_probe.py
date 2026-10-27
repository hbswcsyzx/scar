"""Record stored support versus the deliberately original-only copy query."""
import hashlib
import json
from pathlib import Path
from dataclasses import asdict, is_dataclass

from scripts.run_gate import fingerprint
from scar.ir.execution.await_outcome_evidence import pair
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validity_budget import ValidityBudget
from tests.fixtures.execution_stored_values import stored_values_execution

before, sources = fingerprint()
program, model, details = stored_values_execution(instances=2)
index = ExecutionIndex(model, program)
example = details['examples'][0]
stored = index.stored_value_sources(details['read_rows'][0].result,
    example['reads'][0], budget=1048576)
ctx = index._content_context()
original_before = dict(ctx.body_original_copy_recipes)
ordinary = pair(ctx, example['payloads'][0], stored['read']['result'], ValidityBudget(1048576))
after, final = fingerprint()
assert before == after and sources == final
assert stored['match'] is True and ordinary['match'] is None
assert ctx.body_original_copy_recipes == original_before
record = {'base_revision': 'fff1895fd3abc312409b9b95d40affa9b2c06f86',
    'source_sha256_before': before, 'source_sha256_after': after,
    'source_files': len(sources), 'sources': sources,
    'stored_match': stored['match'], 'ordinary_match': ordinary['match'],
    'source': example['payloads'][0].id.wire, 'target': stored['read']['result'].id.wire,
    'stored_budget': stored['budget'],
    'ordinary_gaps': [asdict(gap) if is_dataclass(gap) else gap for gap in ordinary['gaps']],
    'original_copy_table_unchanged': True,
    'value_source_pair_api_present': hasattr(index, 'value_source_pair'),
    'native_target_executions': 0, 'transformation_authorized': False,
    'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
Path(__file__).with_name('baseline.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({key: value for key, value in record.items() if key != 'sources'}))
