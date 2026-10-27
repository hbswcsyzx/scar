"""Inspect the actual failed body-history joins; no tests or source edits."""
import json
from pathlib import Path

from scar.ir.execution.await_links import project_await_links, await_identity_errors
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validity_budget import ValidityBudget
from tests.fixtures.execution_coroutine_running_graphs import coroutine_running_execution
from tests.fixtures.execution_coroutine_closed_graphs import coroutine_closed_execution
from scripts.run_gate import fingerprint

HERE = Path(__file__).resolve().parent
before, _ = fingerprint()
record = {'source_sha256_before': before, 'tests_started': 0, 'examples': {}}
for label, factory in (('running', coroutine_running_execution), ('closed', coroutine_closed_execution)):
    graph, model, captured = factory()
    index = ExecutionIndex(model, graph)
    if label == 'running':
        read = captured['instances'][0]['extra_scopes']['inner'][2][captured['static']['running']['predicate'].operation]
    else:
        read = captured['read']
    result = index.body_state_history(read, budget=1048576)
    rows = result['active_candidates'] if label == 'running' else result['terminal_candidates']
    observed = []
    for row in rows:
        support = row['drive_support']
        chain = row.get('call_chain') or row.get('read_chain')
        observed.append({'drive': str(row['drive'].id) if row['drive'] else None,
            'expected_bool': row['expected_bool'], 'post_established': row.get('post_established'),
            'gaps': row['gaps'], 'subject_match': row['subject_binding']['match'],
            'drive_supported': None if support is None else support['supported'],
            'creation_match': None if support is None else support['creation_binding']['match'],
            'port_failures': [] if support is None else [item['kind'] for item in support['ports']
                                                        if item['binding']['match'] is not True],
            'chain_supported': None if chain is None else chain['supported'],
            'entry_order': bool(row.get('entry_order')), 'outcome_order': bool(row.get('outcome_order'))})
    ctx, shared = index._content_context(), ValidityBudget(1048576)
    project_await_links(ctx, captured['static']['acquisition_scope'], shared)
    await_identity_errors(ctx, shared)
    links = []
    for job in ctx.await_jobs:
        for occurrence in job['occurrences']:
            for route in occurrence['routes']:
                links.append({'drive': str(route['drive_occurrence'].id),
                    'advance_selected': occurrence['advance_selected'], 'case_selected': occurrence['case_selected'],
                    'derived_checked': occurrence['derived_checked'],
                    'gaps': [getattr(gap, 'code', str(gap)) for gap in occurrence['gaps']],
                    'matched_sources': len(occurrence.get('matched_sources', ())),
                    'iterator_original_copy': [item['original_copy'] for item in occurrence['bindings']],
                    'projection': [{'none': item['projection'] is None,
                        'bindings': [value['original_copy'] for value in item['bindings']]}
                        for item in route.get('projections', ())]})
    record['examples'][label] = {'expected_bool': result['expected_bool'], 'budget': result['budget'],
        'candidates': observed, 'await_links': links, 'projection_budget_truncated': shared.truncated}
record['source_sha256_after'], _ = fingerprint()
assert record['source_sha256_before'] == record['source_sha256_after']
destination = HERE / 'initial-history-probe.json'
assert not destination.exists()
destination.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2))
