"""A reachable wrong producer differs from an unrelated terminal reject branch."""
from dataclasses import replace

import pytest

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.drivers import RawRequestKind
from scar.ir.program.protocol_flow import ProtocolFlow
from scar.ir.program.protocols import RequestProcessing
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_generator_admission_graphs import generator_admission_program
from tests.fixtures.program_generator_stopiter_graphs import stopiter_program


@pytest.mark.parametrize('kind', (RawRequestKind.NEXT, RawRequestKind.SEND))
def test_terminal_rejection_helpers_do_not_poison_direct_current_none_or_send_delivery(kind):
    graph, _ = generator_admission_program(stage='suspended', kind=kind)
    require_valid(graph)
    flow = ProtocolFlow(graph)
    drive, = graph.body_drives
    rows = [row for row in graph.protocol_operations if isinstance(row.contract, RequestProcessing)]
    assert rows
    assert all(flow.reaches(row.contract.result, drive.operation) is False for row in rows)


def test_filtering_unreachable_helpers_does_not_allow_an_old_packet_to_replace_reachable_normalization():
    graph, details = stopiter_program(route='escaping')
    require_valid(graph)
    gate_row, = graph.final_body_gates
    gate = next(op for op in graph.operations if op.id == gate_row.operation)
    delivery_id, = (gate.invoke_arguments[index] for index in gate_row.delivery_arguments)
    delivered = next(use.value for use in gate.uses if use.id == delivery_id)
    gate = replace(gate, uses=tuple(replace(use, value=details['old_packet']) if use.value == delivered else use
                                   for use in gate.uses))
    changed = replace(graph, operations=tuple(gate if op.id == gate.id else op for op in graph.operations))
    require_valid(replace(changed, protocol_scopes=(), protocol_operations=()))
    assert 'protocol_copy' in {issue.code for issue in validate(changed)}


def test_reachability_budget_exhaustion_does_not_become_a_proven_disjoint_route():
    graph, _ = generator_admission_program(stage='suspended', kind=RawRequestKind.SEND)
    row = next(row for row in graph.protocol_operations if isinstance(row.contract, RequestProcessing))
    budget = ValidityBudget(1)
    flow = ProtocolFlow(graph, budget=budget)
    assert flow.reaches(row.contract.result, graph.body_drives[0].operation) is None
    assert budget.truncated and budget.used == 1
