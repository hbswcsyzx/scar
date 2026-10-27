"""A bounded query must not depend on process hashes or table storage order."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

from scar.ir.program.drivers import RawRequestKind
from scar.ir.program.protocol_rules import required_clauses
from scar.ir.program.protocols import ProtocolProfile
from scar.ir.program.queries import ProgramIndex
from tests.fixtures.program_generator_admission_graphs import generator_admission_program


def _query(*, reorder=False, budget=4096):
    graph, _ = generator_admission_program(stage='created', kind=RawRequestKind.CLOSE)
    scope = next(row for row in graph.protocol_scopes
                 if row.profile is ProtocolProfile.CREATED_CLOSE_V1)
    if reorder:
        # These are declaration tables, not execution or successor order.
        graph = replace(graph, operations=graph.operations[::-1], values=graph.values[::-1],
            regions=tuple(replace(region, blocks=region.blocks[::-1])
                          for region in reversed(graph.regions)))
    return scope, ProgramIndex(graph).protocol_obligations(scope.id, budget=budget)


def _snapshot(*, reorder=False):
    _, ledger = _query(reorder=reorder)
    clause, = ledger['scopes'][0]['obligations']
    original, = clause['original']
    return {
        'none_results': [route['declared_none_result'] for route in original['routes']],
        'gaps': list(clause['gaps']),
        'budget': ledger['budget'],
        'source_inventory_complete': ledger['source_inventory_complete'],
        'source_runtime_verified': original['source_runtime_verified'],
        'transformation_authorized': original['transformation_authorized'],
    }


def test_current_none_answer_and_budget_are_identical_in_eight_fresh_hash_processes():
    root = Path(__file__).resolve().parents[2]
    command = [sys.executable, '-c',
        'import json; from tests.unit.test_program_protocol_flow_determinism import _snapshot; '
        'print(json.dumps(_snapshot(), sort_keys=True))']
    observed = []
    for seed in range(8):
        environment = dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE='1',
                           PYTHONHASHSEED=str(seed))
        result = subprocess.run(command, cwd=root, env=environment,
                                capture_output=True, text=True, timeout=20, check=True)
        observed.append(json.loads(result.stdout))
    assert all(row['none_results'] == [True] for row in observed), observed
    assert all(row == observed[0] for row in observed), observed
    assert not observed[0]['budget']['truncated']
    assert observed[0]['budget']['used'] <= 4096
    assert observed[0]['source_runtime_verified'] is False
    assert observed[0]['transformation_authorized'] is False


def test_reordering_declaration_tables_preserves_current_none_and_budget_costs():
    original, reordered = _snapshot(), _snapshot(reorder=True)
    assert original['none_results'] == reordered['none_results'] == [True]
    assert original == reordered


def test_insufficient_budget_still_preserves_obligation_denominator_and_cursor():
    scope, ledger = _query(budget=1)
    clauses = ledger['scopes'][0]['obligations']
    assert tuple(row['clause'] for row in clauses) == required_clauses(scope.profile)
    assert ledger['budget']['truncated'] is True
    assert ledger['budget']['used'] == 1
    assert ledger['cursor'] is not None
    assert ledger['source_inventory_complete'] is False
    assert all(row['status'] in ('NOT_CHECKED', 'PARTIAL', 'MISSING') for row in clauses)
