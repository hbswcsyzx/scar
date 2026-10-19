"""Original zero/two-cut consumers; no execution or native claim from labels."""
from dataclasses import replace

from scar.ir.program.model import TerminatorKind
from scar.ir.program.protocol_rules import required_clauses
from scar.ir.program.protocols import OutcomeAdapterRule, ProtocolClause, ProtocolProfile
from scar.ir.program.resumption import ResumableKind, SuspendTerminator
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_await_resume_graphs import await_resume_program, with_final_adapter


def test_two_cut_direct_and_await_calls_share_one_original_body_and_keep_final_extraction():
    graph, details = await_resume_program()
    require_valid(graph)
    assert len(details['drivers']) == 3
    assert details['drivers'][0]['direct'] is True
    assert all(not item['direct'] for item in details['drivers'][1:])
    assert graph.resumable_bodies[0].kind is ResumableKind.GENERATOR_COROUTINE
    assert len(graph.resumable_bodies) == 1
    assert len(graph.resumable_creates) == 2
    assert graph.resumable_creates[0].body == graph.resumable_creates[1].body
    assert len([op for op in graph.operations if type(op.terminator) is SuspendTerminator]) == 2
    assert len(details['handoffs']) == 2
    assert details['drivers'][-1]['host_terminal'].terminator.kind is TerminatorKind.RAISE
    assert details['extract'].terminator.kind is TerminatorKind.INVOKE
    assert details['final'].terminator.kind is TerminatorKind.RETURN
    assert details['extract_input'].operation == details['extract'].id
    assert details['final_value'] not in {use.value for op in details['handoffs'] for use in op.uses}


def test_self_acquisition_accepts_the_existing_accurate_final_extraction_contract():
    graph, details = await_resume_program(zero_cut=True)
    require_valid(graph)
    attached, rows = with_final_adapter(graph, details)
    # A real existing contract/profile seam: no synthetic lookup/call, no new
    # producer. Root runs this red before deciding the narrow profile change.
    require_valid(attached)
    assert len(rows) == 2


def test_optional_final_adapter_does_not_replace_required_acquisition_or_core_consumer():
    graph, details = await_resume_program(zero_cut=True)
    attached, rows = with_final_adapter(graph, details)
    require_valid(attached)
    assert required_clauses(ProtocolProfile.AWAIT_ACQUISITION_V1) == (ProtocolClause.AWAIT_ACQUISITION,)
    removed = replace(attached,
        protocol_operations=tuple(row for row in attached.protocol_operations if row not in rows),
        protocol_result_consumers=graph.protocol_result_consumers)
    require_valid(removed)
    assert removed == graph
    extraction = next(op for op in removed.operations if op.id == details['extract'].id)
    assert details['extract_input'].use in extraction.invoke_arguments
    assert any(details['extract_input'] in receipt.targets
               for receipt in removed.protocol_result_consumers)
    assert tuple(row for row in removed.protocol_operations
                 if row.scope == details['acquisition_scope']
                 and row.clause is ProtocolClause.AWAIT_ACQUISITION) == details['get_rows']


def test_optional_final_adapter_does_not_admit_a_different_protocol_rule():
    graph, details = await_resume_program(zero_cut=True)
    attached, rows = with_final_adapter(graph, details)
    require_valid(attached)
    wrong = replace(attached, protocol_operations=tuple(
        replace(row, contract=replace(row.contract,
            rule=OutcomeAdapterRule.GENERATOR_RETURN_TO_STOP_ITERATION))
        if row in rows else row for row in attached.protocol_operations))
    # Metadata-only change: the extraction, selected edge and every core Use
    # remain the same; allowing the optional clause does not admit this rule.
    assert wrong.operations == attached.operations
    assert 'protocol_rule' in {issue.code for issue in validate(wrong)}
