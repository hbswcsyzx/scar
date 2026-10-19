"""Inspect real conditional raw/ordinal receipts without changing graph facts."""
import hashlib
import json
from pathlib import Path
import sys

from scripts.run_gate import fingerprint
from tests.fixtures.program_async_initial_control_graphs import async_initial_control_program
from tests.unit.test_program_async_initial_control import _report, _selected_route


def report(value):
    return {'match': value['match'], 'gaps': value.get('gaps'),
            'routes': tuple({'choices': str(row.get('choices')), 'match': row.get('match'),
                             'gaps': row.get('gaps')} for row in value.get('routes', ())) }


before, sources = fingerprint()
rows = []
for raised in (False, True):
    graph, details = async_initial_control_program(scenario='created-reject', reject_raised=raised)
    joint = _report(graph)['initial_asend']
    route = _selected_route(joint, details['drivers'][0], terminal=True)
    selected = next(item for item in route['processing_views']
                    if item['record'].contract.result.edge.successor_index == int(raised))
    rows.append({'raised': raised, 'gaps': selected['gaps'],
        'source_binding': report(selected['source_binding']),
        'sources': tuple({'raw': report(item['raw_binding']),
                         'operands': tuple(report(value) for value in item['operand_bindings']),
                         'binding': report(item['binding'])} for item in selected['source_bindings']),
        'operands': tuple({'raw': report(item['raw_operand_binding']), 'effective': report(item['report'])}
                          for item in selected['operand_bindings']),
        'predicates': tuple({'kind': type(item['record'].contract.subject).__name__,
            'view_complete': item['view'].get('complete'),
            'effective_complete': item['view'].get('effective_sources', {}).get('source_inventory_complete'),
            'view_binding': report(item['view'].get('binding', item['binding'])),
            'path_binding': report(item['binding']),
            'sources': tuple({'scheduler': source['projection'].get('scheduler'),
                             'definition_kind': source['definition'].kind.value,
                             'projection_complete': source['projection'].get('source_inventory_complete')}
                            for source in item['view'].get('operand_bindings', ()))}
            for item in route['predicates'])})
after, final = fingerprint()
assert before == after and sources == final
result = {'source_sha256_before': before, 'source_sha256_after': after, 'sources': sources,
          'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'tests_started': 0, 'scenarios': rows}
Path(sys.argv[1]).write_text(json.dumps(result, indent=2, default=str) + '\n')
print(json.dumps({'source_sha256': before, 'scenarios': rows}, indent=2, default=str))
