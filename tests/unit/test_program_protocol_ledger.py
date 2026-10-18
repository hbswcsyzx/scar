from dataclasses import replace

from scar.ir.program.ids import ProtocolScopeID
from scar.ir.program.protocol_rules import required_clauses
from scar.ir.program.protocols import (
    ContractResult, OperationSiteSubject, OutcomeAdapter, ProtocolClause,
    ProtocolProfile, ProtocolScope,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import validate
from tests.fixtures.program_protocol_graphs import (
    generator_protocol_program, request_processing_program,
)


def _scope_view(ledger, scope):
    return next(item for item in ledger["scopes"] if item["scope"].id == scope)


def _obligation(view, clause):
    return next(item for item in view["obligations"] if item["clause"] is clause)


def test_fixed_clause_denominator_and_exact_invoke_edge_survive_deleted_raise_row():
    graph, details = generator_protocol_program(target="packet")
    scope = graph.protocol_scopes[0]
    clauses = required_clauses(scope.profile)

    complete = ProgramIndex(graph).protocol_obligations(scope.id)
    complete_view = _scope_view(complete, scope.id)
    assert tuple(item["clause"] for item in complete_view["obligations"]) == clauses

    kept = tuple(row for row in graph.protocol_operations
                 if not (row.clause is ProtocolClause.REQUEST_PROCESSING
                         and row.operation == details["processing"] and row.slot == 1))
    partial_graph = replace(graph, protocol_operations=kept)
    partial = ProgramIndex(partial_graph).protocol_obligations(scope.id)
    view = _scope_view(partial, scope.id)
    assert tuple(item["clause"] for item in view["obligations"]) == clauses

    request = _obligation(view, ProtocolClause.REQUEST_PROCESSING)
    missing = tuple(binding for binding in request["bindings"]
                    if binding["operation"] == details["processing"]
                    and binding["slot"] == 1 and binding["status"] == "MISSING")
    assert len(missing) == 1
    assert request["status"] == "PARTIAL"
    assert "protocol_required_edge_unbound" in request["gaps"]


def test_budget_one_preserves_complete_clause_denominator_and_cursor():
    graph, _ = request_processing_program()
    scope = graph.protocol_scopes[0]
    ledger = ProgramIndex(graph).protocol_obligations(scope.id, budget=1)
    view = _scope_view(ledger, scope.id)

    assert tuple(item["clause"] for item in view["obligations"]) == required_clauses(scope.profile)
    assert ledger["budget"]["truncated"] is True
    assert ledger["cursor"] is not None
    assert ledger["source_inventory_complete"] is False
    assert any(item["status"] == "NOT_CHECKED" for item in view["obligations"])


def test_cross_scope_contract_result_must_match_the_selected_rows_own_port():
    graph, details = request_processing_program()
    scope, process_row, packet_row = graph.protocol_scopes[0], *graph.protocol_operations
    foreign_scope = replace(scope, id=ProtocolScopeID("connection.foreign.scope"))
    foreign_process = replace(process_row, scope=foreign_scope.id)

    # The key resolves to a real row in the other scope, but the supplied port
    # is its sibling result, not the exact port declared by that row.
    wrong_result = ContractResult(
        foreign_scope.id, ProtocolClause.THROW_NORMALIZATION,
        details["processing"], 0, details["other_result"],
    )
    packet_contract = replace(packet_row.contract, exception_source=wrong_result)
    wrong_packet = replace(packet_row, contract=packet_contract)
    malformed = replace(graph,
        protocol_scopes=(*graph.protocol_scopes, foreign_scope),
        protocol_operations=(process_row, foreign_process, wrong_packet),
    )

    issues = validate(malformed)
    assert any(issue.code == "protocol_contract_result" for issue in issues)


def test_generator_return_adapter_cannot_use_request_helper_result_as_body_return():
    graph, details = generator_protocol_program(target="value")
    adapter_row = next(row for row in graph.protocol_operations
                       if type(row.contract) is OutcomeAdapter)
    helper = next(row for row in graph.protocol_operations
                  if row.operation == details["processing"]
                  and row.clause is ProtocolClause.REQUEST_PROCESSING and row.slot == 0)
    wrong_source = ContractResult(
        adapter_row.scope, helper.clause, helper.operation, helper.slot,
        helper.contract.result,
    )
    malformed_adapter = replace(adapter_row.contract, input=wrong_source)
    malformed = replace(graph, protocol_operations=tuple(
        replace(row, contract=malformed_adapter) if row is adapter_row else row
        for row in graph.protocol_operations))

    issues = validate(malformed)
    assert any(issue.code == "protocol_adapter_source"
               and issue.path == f"protocol_operations[{graph.protocol_operations.index(adapter_row)}]"
               for issue in issues)


def test_unimplemented_source_inventory_remains_explicitly_unresolved():
    graph, details = request_processing_program()
    base_scope = graph.protocol_scopes[0]
    scope = ProtocolScope(
        ProtocolScopeID("connection.await-site"), ProtocolProfile.AWAIT_SITE_V1,
        OperationSiteSubject(graph.regions[0].id, details["processing"]), base_scope.source,
    )
    graph = replace(graph, protocol_scopes=(*graph.protocol_scopes, scope))
    ledger = ProgramIndex(graph).protocol_obligations(scope.id)
    view = _scope_view(ledger, scope.id)

    assert view["source_inventory_complete"] is False
    assert ledger["source_inventory_complete"] is False
    assert any(gap["code"] == "SOURCE_SCOPE_INVENTORY_UNRESOLVED" for gap in ledger["gaps"])
    assert any(item["status"] == "MISSING" for item in view["obligations"])


def test_rule_builder_is_not_exposed_after_closed_tables_are_built():
    import scar.ir.program.protocol_rules as rules

    assert not hasattr(rules, "_allow")
    assert not hasattr(rules, "_allowed")
