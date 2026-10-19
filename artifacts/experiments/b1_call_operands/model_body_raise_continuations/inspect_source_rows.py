"""Inspect the original source denominator; never infer or delete a row."""
import json

from scar.ir.program.queries import ProgramIndex
from tests.fixtures.program_await_raise_sources_graphs import await_raise_source_program


for zero_cut, mode in ((True, 'preserve'), (False, 'replace_raise')):
    graph, details = await_raise_source_program('general', zero_cut, mode)
    report = ProgramIndex(graph).protocol_obligations(details['acquisition_scope'],
        budget=1_048_576)['connections']['families']['await']
    rows = tuple(row for row in report['outcomes']
        if row['drive_outcome'] == details['drive_outcome']
        and row['advance_operation'] == details['advance_operation'])
    print(json.dumps({'zero_cut': zero_cut, 'expected_source': details['source'],
        'matching_expected_source_count': sum(row['source'] == details['source'] for row in rows),
        'rows': tuple({key: row.get(key) for key in ('key', 'source', 'source_operation',
            'scope', 'input_guard', 'choices', 'drive_outcome', 'advance_operation', 'status')}
            for row in rows)}, default=str, indent=2))
