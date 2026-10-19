"""Record exact query blockers before/after implementation; start no tests."""
import hashlib
import json
from pathlib import Path
import sys

from scripts.run_gate import fingerprint
from tests.fixtures.execution_call_effect_expansion_graphs import (
    call_effect_expansion_execution, ordinary_call_effect_expansion_execution,
)
from tests.unit.test_execution_state_preservation import _index


HERE = Path(__file__).resolve().parent
destination = HERE / sys.argv[1]
assert destination.parent == HERE and not destination.exists()
before, sources = fingerprint()
scenarios = []
for name, factory, options in (
    ('normal-suffix-prefix', call_effect_expansion_execution, {}),
    ('raise-suffix-prefix', call_effect_expansion_execution, {'raised': True}),
    ('unknown-aggregate-expansion', call_effect_expansion_execution, {'outer_complete': False}),
    ('prefix-without-future-completion', call_effect_expansion_execution, {'missing': 'prefix-completion'}),
    ('ordinary-call', ordinary_call_effect_expansion_execution, {}),
    ('ordinary-without-future-results', ordinary_call_effect_expansion_execution, {'future_missing': True}),
):
    graph, model, details = factory(**options)
    example = details.get('examples', (details,))[0]
    index = _index(graph, model)
    view = index.state_preservation(example['start'], example['end'],
        locations=details['static']['locations'], budget=262144)
    scenarios.append({'name': name, 'preserved': view['preserved'], 'reached': view['reached'],
        'start': str(view['start']), 'end': str(view['end']),
        'operations': [str(row['definition'].id) for row in view['operations']],
        'raw_parent_complete': [call.effects_complete for call in details['static']['calls']],
        'blockers': [{'code': row['code'], 'operation': str(row['operation']), 'reason': row['reason']}
                     for row in view['blockers']],
        'budget': view['budget'], 'cursor': None if view['cursor'] is None else str(view['cursor']),
        'source_runtime_verified': view['source_runtime_verified'],
        'transformation_authorized': view['transformation_authorized']})
after, final = fingerprint()
assert before == after and sources == final
record = {'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'command': [sys.executable, str(Path(__file__).relative_to(Path.cwd())), sys.argv[1]],
    'python': sys.version, 'source_sha256_before': before, 'source_sha256_after': after,
    'sources': sources, 'scenarios': scenarios, 'tests_started': 0}
destination.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({'source_sha256': before, 'tests_started': 0, 'scenarios': [
    {'name': row['name'], 'preserved': row['preserved'],
     'blockers': sorted(set(item['code'] for item in row['blockers']))} for row in scenarios]}, indent=2))
