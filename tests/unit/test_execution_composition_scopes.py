from dataclasses import replace

import pytest

from scar.ir.execution.composition import CompositionScope
from scar.ir.execution.composition_requirements import (
    prepare_scopes, requirements, validate_scopes,
)
from scar.ir.execution.ids import ObservationRequirementID, ObservationRootID, RunID
from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.execution.validation import _analyze
from scar.ir.v2.ids import ContractID
from tests.fixtures.execution_composition_scopes import composition_scope_execution
from tests.fixtures.execution_observation_graphs import observation_execution


class _StringSubclass(str):
    pass


def _context(*, owner_kind="run", output=True, **kwargs):
    program, model, semantic_graphs, scope, details = composition_scope_execution(
        owner_kind=owner_kind, output=output, **kwargs)
    report, ctx = _analyze(model, program, semantic_graphs=semantic_graphs)
    assert report.valid, report.issues
    return program, model, semantic_graphs, scope, details, ctx


def _derive(ctx, scope, budget=128):
    return requirements(ctx, (scope,), budget=ValidityBudget(budget))


def _obligation(result, kind):
    return next(row for row in result["obligations"] if row["kind"] == kind)


def test_prepare_scope_checks_owner_without_loading_contract_artifact():
    *_, scope, details, ctx = _context()
    calls = []
    ctx.external_semantic = lambda artifact, path: calls.append((artifact, path))
    prepared, = prepare_scopes(ctx, (scope,))
    assert prepared["scope"] is scope
    assert prepared["owner"] == details["owner"]
    assert prepared["run"] == details["owner"]
    assert "contract" not in prepared
    assert calls == []


def test_explicit_scope_preserves_contract_denominator_and_distinguishes_missing_requirement_and_root():
    _, _, _, scope, _, ctx = _context(
        include_requirement=False, include_root=False)
    result = _derive(ctx, scope)
    row, = result["scopes"]
    assert row["contract"] is not None
    assert row["expected_outputs"] == row["contract"].required_outputs
    output = _obligation(result, "OUTPUT")
    assert output["status"] == "REQUIREMENT_MISSING"
    assert result["scope_status"] == "PARTIAL"
    assert result["scope_complete_for_request"] is False

    _, _, _, scope, _, ctx = _context(include_root=False)
    result = _derive(ctx, scope)
    output = _obligation(result, "OUTPUT")
    assert output["status"] == "ROOT_MISSING"
    assert any(gap.code == "composition_root_missing" for gap in result["gaps"])


def test_exact_run_activation_and_operation_scopes_do_not_collapse_owners():
    for owner_kind in ("run", "activation", "operation"):
        _, _, _, scope, _, ctx = _context(owner_kind=owner_kind)
        result = _derive(ctx, scope)
        output = _obligation(result, "OUTPUT")
        assert output["status"] == "ROOT_PRESENT_OUTPUT_SLOT_UNVERIFIED"
        assert output["roots"]
        # The fixture contract also declares a required facet whose target
        # cardinality the current contract schema does not define.
        assert result["scope_status"] == "PARTIAL"

    # A root observed in another activation of the same run stays unresolved;
    # it is not merged into the selected activation or declared outside it.
    _, _, _, scope, _, ctx = _context(
        owner_kind="activation", activations=2, anchor_activation=1, owner_activation=0)
    result = _derive(ctx, scope)
    output = _obligation(result, "OUTPUT")
    assert output["status"] == "ROOT_SCOPE_UNRESOLVED"
    assert output["unresolved_roots"]
    assert result["scope_status"] == "PARTIAL"


def test_required_facet_keeps_uninterpreted_target_cardinality_even_when_rows_are_absent():
    _, _, _, scope, _, ctx = _context(
        owner_kind="run", output=False, include_requirement=False, include_root=False)
    result = _derive(ctx, scope)
    facet = _obligation(result, "FACET")
    assert facet["kind"] == "FACET"
    assert facet["status"] == "FACET_TARGETS_UNINTERPRETED:NO_ENDPOINT_CANDIDATE"
    assert result["scope_status"] == "PARTIAL"
    assert any(gap.code == "composition_facet_targets_uninterpreted" for gap in result["gaps"])


def test_all_original_inventory_rows_survive_scope_filter_and_budget_truncation():
    _, model, _, scope, _, ctx = _context(include_content_read=True)
    result = _derive(ctx, scope, budget=128)
    assert result["requirements"] is model.observation_requirements
    assert result["roots"] is model.observation_roots
    assert result["content_reads"] is model.content_reads
    output = _obligation(result, "OUTPUT")
    read_link, = output["root_content_reads"]
    assert read_link["content_reads"] == model.content_reads
    assert read_link["status"] == "DECLARED_READS"

    _, model, _, scope, _, ctx = _context(include_content_read=True)
    result = _derive(ctx, scope, budget=1)
    scope_row, = result["scopes"]
    assert scope_row["expected_outputs"] == (scope_row["contract"].required_outputs[0],)
    assert scope_row["pending_obligations"][0] == ("OUTPUT", scope_row["expected_outputs"][0])
    assert result["requirements"] is model.observation_requirements
    assert result["roots"] is model.observation_roots
    assert result["content_reads"] is model.content_reads
    assert result["scope_status"] == "TRUNCATED"
    assert result["budget_truncated"] is True
    assert result["pending"]["roots"] == len(model.observation_roots)


def test_root_owner_join_cursor_names_current_and_later_requirement_groups():
    program, model, semantic_graphs = observation_execution(output=True)
    requirement = model.observation_requirements[0]
    root = model.observation_roots[0]
    requirements = [requirement]
    roots = [root]
    for index in (1, 2):
        cloned_requirement = replace(
            requirement, id=ObservationRequirementID(f"required.{index}"))
        cloned_root = replace(
            root, id=ObservationRootID(f"actual.{index}"),
            requirement=cloned_requirement.id)
        requirements.append(cloned_requirement)
        roots.append(cloned_root)
    model = replace(model, observation_requirements=tuple(requirements),
                    observation_roots=tuple(roots))
    report, ctx = _analyze(model, program, semantic_graphs=semantic_graphs)
    assert report.valid, report.issues
    scope = CompositionScope(requirement.contract, model.runs[0].id,
                             model.runs[0].source)

    result = _derive(ctx, scope, budget=8)
    output = _obligation(result, "OUTPUT")
    assert result["cursor"]["stage"] == "root_owner_joins"
    assert result["cursor"]["requirement"] == requirements[1].id
    assert result["cursor"]["requirement_ordinal"] == 1
    assert result["cursor"]["index"] == 0
    assert result["cursor"]["pending_root_joins"] == 1
    assert result["cursor"]["pending_requirement_groups"] == 1
    assert output["pending_root_joins"] == 1
    assert output["pending_requirement_groups"] == 1
    assert output["requirements"] == tuple(requirements)
    assert result["scope_status"] == "TRUNCATED"


def test_no_content_read_is_protocol_unclassified_not_a_no_dependency_claim():
    _, _, _, scope, _, ctx = _context()
    result = _derive(ctx, scope)
    output = _obligation(result, "OUTPUT")
    root_read, = output["root_content_reads"]
    assert root_read["content_reads"] == ()
    assert root_read["status"] == "NO_CONTENT_READ_DECLARED_PROTOCOL_UNCLASSIFIED"
    assert any(gap.code == "composition_content_protocol_unclassified" for gap in result["gaps"])
    assert output["status"] == "ROOT_PRESENT_OUTPUT_SLOT_UNVERIFIED"


def test_no_scope_keeps_raw_q_inventory_but_does_not_turn_empty_request_into_success():
    _, model, _, _, _, ctx = _context(include_content_read=True)
    budget = ValidityBudget(128)
    result = requirements(ctx, (), budget=budget)
    assert result["scopes"] == ()
    assert result["obligations"] == ()
    assert result["requirements"] is model.observation_requirements
    assert result["roots"] is model.observation_roots
    assert result["content_reads"] is model.content_reads
    assert result["scope_status"] == "UNRESOLVED"
    assert result["scope_complete_for_request"] is False
    assert budget.used == 0


def test_missing_external_contract_is_unresolved_and_bad_contract_foreign_key_fails():
    _, _, _, scope, _, ctx = _context(include_semantic=False)
    result = _derive(ctx, scope)
    row, = result["scopes"]
    assert row["contract"] is None
    assert row["expected_outputs"] is None
    assert row["ledger_status"] == "UNRESOLVED"
    assert result["scope_status"] == "PARTIAL"

    _, _, _, scope, _, ctx = _context()
    bad = replace(scope, contract=replace(scope.contract, contract=ContractID("absent")))
    with pytest.raises(KeyError, match="unknown contract"):
        _derive(ctx, bad)


def test_scope_validation_rechecks_exact_nested_owner_and_requires_exact_unique_tuple():
    _, _, _, scope, details, ctx = _context()
    with pytest.raises(TypeError):
        validate_scopes([scope])
    with pytest.raises(ValueError, match="duplicated"):
        validate_scopes((scope, scope))
    forged = RunID("forged")
    object.__setattr__(forged, "value", _StringSubclass("forged"))
    with pytest.raises(ValueError, match="exact string"):
        CompositionScope(scope.contract, forged, scope.source)

    with pytest.raises(KeyError, match="unknown composition run"):
        prepare_scopes(ctx, (CompositionScope(scope.contract, RunID("absent"), scope.source),))
