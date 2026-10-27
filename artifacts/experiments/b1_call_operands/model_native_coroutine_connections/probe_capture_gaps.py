"""Concrete reviewer capture-gap checks on the now passing original graphs."""
from dataclasses import replace
import json
from pathlib import Path

from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from tests.fixtures.execution_coroutine_running_graphs import coroutine_running_execution
from tests.fixtures.execution_coroutine_closed_graphs import coroutine_closed_execution
from scripts.run_gate import fingerprint

HERE = Path(__file__).resolve().parent
before, _ = fingerprint()
rows = {}
graph, model, details = coroutine_running_execution()
example = details['instances'][0]
association = example['body_drives'][1]
drive = next(row for row in graph.body_drives if row.operation == details['static']['drivers'][1]['drive'].operation)
omitted = (association.drive, drive.scheduler_request)
changed = replace(model, uses=tuple(row for row in model.uses if (row.operation, row.use) != omitted))
read = example['extra_scopes']['inner'][2][details['static']['running']['predicate'].operation]
report = validate(changed, graph)
assert report.valid, report.issues
view = ExecutionIndex(changed, graph).body_state_history(read, budget=1048576)
candidate, = tuple(row for row in view['active_candidates'] if row['drive'].id == association.drive)
rows['missing_current_raw_use'] = {'omitted': tuple(map(str, omitted)),
    'valid_capture': report.valid, 'expected_bool': view['expected_bool'],
    'drive_supported': candidate['drive_support']['supported'], 'candidate_gaps': candidate['gaps'],
    'capture_gaps': [gap.code for gap in report.gaps]}
graph, model, details = coroutine_closed_execution()
example = details['instances'][0]
gate = next(row for row in graph.final_body_gates if row.drive == graph.body_drives[0].operation)
omitted = example['driver_scopes'][0][2][gate.operation]
changed = replace(model, transfers=tuple(row for row in model.transfers if row.operation != omitted))
report = validate(changed, graph)
assert report.valid, report.issues
view = ExecutionIndex(changed, graph).body_state_history(details['read'], budget=1048576)
candidate, = tuple(view['terminal_candidates'])
rows['missing_source_driver_gate_transfer'] = {'omitted': str(omitted),
    'valid_capture': report.valid, 'expected_bool': view['expected_bool'],
    'source_chain_supported': candidate['source_chain']['supported'],
    'candidate_gaps': candidate['gaps'], 'capture_gaps': [gap.code for gap in report.gaps]}
after, _ = fingerprint()
assert before == after
record = {'source_sha256_before': before, 'source_sha256_after': after,
          'tests_started': 0, 'cases': rows}
target = HERE / 'capture-gap-probe-before.json'
assert not target.exists()
target.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2))
