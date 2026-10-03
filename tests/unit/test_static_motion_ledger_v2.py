"""Source-bound fixtures and fixed-ledger tests for narrow static motion."""
from dataclasses import replace
import hashlib

import pytest

from scar.analysis.control_flow_v2 import build_source_control_flow
from scar.analysis.proof_ledger_v2 import (
    ProofContext, ProofFamily, ProofLedger, ProofOutcome, ProofQ, ProofRequest,
    QAssumption, QPredicate, derive_proof_ledger,
    static_motion_q_subject, validate_proof_ledger,
)
from scar.analysis.regions_v2 import RegionInventory, RegionView
from scar.analysis.local_statement_semantics_v2 import (
    Coverage, StatementFact, StatementKind, derive_local_statement_semantics,
)
from scar.analysis.source_fragments_v2 import derive_source_fragment
from scar.analysis.source_semantics_v2 import extract_source_semantics
from scar.ir.control_flow_v2 import (
    ControlFlowBudget, EdgeKind, InsertionKind, NodeKind, QueryMode,
    SourceControlFlowGraph, SuiteKind,
)
from scar.ir.frontend_v2 import build_semantic
from scar.ir.v2 import (
    ControlRegionID, EvidenceClaim, EvidenceGraph, EvidenceKind, IRBundle,
    ProofStatus, RegionMove, TransformDelta, ValueGraph,
)
from scar.ir.v2.optimization import StaticSourceMove


_ALIAS_SOURCE = (
    "def f():\n"
    "    token = ()\n"
    "    marker = 1 + 2\n"
    "    alias = token\n"
    "    return alias\n"
)


def _source_models(tmp_path, text=_ALIAS_SOURCE):
    source = tmp_path / "program.py"
    source.write_text(text)
    semantic = build_semantic(source).graph
    source_semantics = extract_source_semantics(semantic)
    source_control_flow = build_source_control_flow(semantic, source_semantics)
    return source, text, semantic, source_semantics, source_control_flow


def _statement(graph: SourceControlFlowGraph, line: int):
    matches = [node for node in graph.nodes.values()
               if node.kind is NodeKind.STATEMENT
               and node.source is not None
               and node.source.start_line == line]
    assert len(matches) == 1
    return matches[0]


def _motion_case(tmp_path, text=_ALIAS_SOURCE, *, moved_line=4, target_line=2):
    source, text, semantic, source_semantics, control_flow = _source_models(tmp_path, text)
    moved_statement = _statement(control_flow, moved_line)
    fragment = derive_source_fragment(
        semantic, source_semantics, control_flow, moved_statement.id,
        sources={str(source): text})
    token_statement = _statement(control_flow, target_line)
    insertion = next(item for item in control_flow.insertions.values()
                     if item.kind is InsertionKind.AFTER
                     and item.anchor == token_statement.id)
    bundle = IRBundle(semantic, EvidenceGraph(), ValueGraph(),
                      source_semantics=source_semantics)
    inventory = RegionInventory(bundle, view=RegionView.SEMANTIC)
    region = inventory.region(fragment.operation_ids)
    context = ProofContext(bundle, source_semantics, inventory, inventory.scope,
        ProofQ(inventory.scope), source_texts={str(source): text},
        source_control_flow=control_flow)
    request = ProofRequest(ProofFamily.MOTION, region,
        TransformDelta(static_moves=(StaticSourceMove(fragment, insertion.id),)))
    return source, text, semantic, source_semantics, control_flow, fragment, insertion, context, request


def _statement_report(semantic, source_semantics, control_flow, text):
    suites = [item for item in control_flow.suites.values()
              if item.kind is SuiteKind.FUNCTION]
    assert len(suites) == 1
    source_texts = {path: text for path in control_flow.sources}
    return derive_local_statement_semantics(
        semantic, source_semantics, control_flow, suites[0].id,
        source_texts=source_texts)


def _accepted_motion_q(context, text):
    control_flow = context.source_control_flow
    report = _statement_report(context.bundle.semantic, context.source_semantics,
                               control_flow, text)
    assert report.coverage is Coverage.SUPPORTED, report.gaps
    evidence = EvidenceClaim(EvidenceKind.DECLARED,
        ("test:static-motion-scoped-contract",), scope=context.scope)
    statement_conditions = (
        QPredicate.TARGET_RUNTIME_MATCH,
        QPredicate.RESOURCE_FAILURE_UNOBSERVED,
        QPredicate.ASYNC_INTERRUPTION_UNOBSERVED,
        QPredicate.FRAME_NAMESPACE_OBSERVATION_UNOBSERVED,
        QPredicate.REFERENCE_COUNT_OBSERVATION_UNOBSERVED,
        QPredicate.TRACE_EVENT_ORDER_UNOBSERVED,
    )
    assumptions = {
        (predicate, static_motion_q_subject(predicate, certificate.statement,
                                             certificate.source)):
            QAssumption(predicate, static_motion_q_subject(
                predicate, certificate.statement, certificate.source), evidence)
        for certificate in report.certificates
        for predicate in statement_conditions
    }
    from scar.ir.semantics_v2 import SourceExecutionPrecondition
    assumptions.update({
        (QPredicate.SOURCE_PRECONDITION, precondition.value):
            QAssumption(QPredicate.SOURCE_PRECONDITION, precondition.value, evidence)
        for precondition in SourceExecutionPrecondition
    })
    return replace(context, q=ProofQ(context.scope,
        tuple(assumptions[key] for key in sorted(assumptions,
            key=lambda item: (item[0].value, item[1])))))


def test_static_motion_request_uses_one_exact_semantic_statement_region(tmp_path):
    _, _, _, _, _, fragment, _, context, request = _motion_case(tmp_path)

    assert request.delta.static_moves[0].fragment == fragment
    assert request.delta.is_empty is False
    assert set(context.inventory.graph.regions[request.region].definitions) == set(
        fragment.operation_ids)
    assert derive_proof_ledger(context, request).family is ProofFamily.MOTION


def test_static_motion_rejects_forged_cfg_before_ledger_derivation(tmp_path):
    _, _, _, _, control_flow, _, _, context, request = _motion_case(tmp_path)
    control_flow.semantic_digest = "sha256:" + "0" * 64

    try:
        derive_proof_ledger(context, request)
    except ValueError as error:
        assert "control replay" in str(error)
    else:
        raise AssertionError("a CFG with a forged semantic digest was accepted")


def test_static_motion_rejects_forged_source_fragment(tmp_path):
    _, _, _, _, _, fragment, _, context, request = _motion_case(tmp_path)
    forged_fragment = replace(fragment,
        text_digest="sha256:" + hashlib.sha256(b"alias = marker").hexdigest())
    forged_move = replace(request.delta.static_moves[0], fragment=forged_fragment)
    request = replace(request,
        delta=TransformDelta(static_moves=(forged_move,)))

    with pytest.raises(ValueError, match="source fragment replay failed"):
        derive_proof_ledger(context, request)


def test_static_motion_rejects_dynamic_move_mixing_and_non_motion_use(tmp_path):
    _, _, _, _, _, _, _, context, request = _motion_case(tmp_path)
    mixed = replace(request, delta=replace(request.delta,
        moves=(RegionMove(request.region, ControlRegionID("control:legacy-from"),
                          ControlRegionID("control:legacy-to")),)))

    try:
        derive_proof_ledger(context, mixed)
    except (TypeError, ValueError) as error:
        assert "mix" in str(error) or "static source MOTION" in str(error)
    else:
        raise AssertionError("dynamic RegionMove was mixed with a static source move")

    wrong_family = replace(request, family=ProofFamily.CONSTANT)
    try:
        derive_proof_ledger(context, wrong_family)
    except ValueError as error:
        assert "MOTION requests" in str(error)
    else:
        raise AssertionError("static source move was accepted outside MOTION")


def test_local_statement_report_certifies_only_complete_alias_chain(tmp_path):
    _, text, semantic, source_semantics, control_flow, _, _, _, _ = _motion_case(tmp_path)

    report = _statement_report(semantic, source_semantics, control_flow, text)

    assert report.coverage is Coverage.SUPPORTED, [
        (gap.kind, gap.source.start_line if gap.source else None, gap.reason)
        for gap in report.gaps]
    by_line = {item.source.start_line: item for item in report.certificates}
    assert set(by_line) == {2, 3, 4, 5}
    token = by_line[2]
    alias = by_line[4]
    assert token.kind is StatementKind.ASSIGN_LITERAL
    assert alias.kind is StatementKind.ASSIGN_ALIAS
    assert alias.alias_source_binding == token.written_binding
    assert StatementFact.ALIAS_IDENTITY_PRESERVED in alias.facts
    assert by_line[5].kind is StatementKind.RETURN_LOCAL


def test_local_statement_report_does_not_certify_a_crossed_user_call(tmp_path):
    text = (
        "def f():\n"
        "    token = ()\n"
        "    marker = observe()\n"
        "    alias = token\n"
        "    return alias\n"
    )
    _, _, semantic, source_semantics, control_flow, _, _, _, _ = _motion_case(
        tmp_path, text)

    report = _statement_report(semantic, source_semantics, control_flow, text)

    assert report.coverage is Coverage.INCOMPLETE
    assert not any(item.source.start_line == 3 for item in report.certificates)


def test_static_motion_positive_recomputes_all_six_obligations(tmp_path, monkeypatch):
    import scar.analysis.control_flow_v2 as control_flow_analysis

    _, text, _, _, control_flow, _, _, context, request = _motion_case(tmp_path)
    context = _accepted_motion_q(context, text)
    original_graph = control_flow.to_dict()
    queried_modes = []
    original_query = control_flow_analysis.query_dominance

    def record_mode(*args, **kwargs):
        queried_modes.append(kwargs.get("mode"))
        return original_query(*args, **kwargs)

    monkeypatch.setattr(control_flow_analysis, "query_dominance", record_mode)

    ledger = derive_proof_ledger(context, request)

    assert ledger.outcome is ProofOutcome.CONDITIONALLY_LEGAL
    assert {item.name for item in ledger.obligations} == {
        "all_inputs_state_available_at_target",
        "control_dominance_and_zero_iteration",
        "effects_rng_exceptions_and_ordering",
        "alias_lifetime_readiness_autograd_hooks",
        "consumer_call_control_closure",
        "precise_insertion_point_and_delta",
    }
    assert all(item.status is ProofStatus.PROVEN for item in ledger.obligations)
    assert all(item.conditions for item in ledger.obligations)
    assert all(assumption.evidence.kind is EvidenceKind.DECLARED
               for item in ledger.obligations for assumption in item.conditions)
    assert queried_modes and set(queried_modes) == {QueryMode.ALL_PATHS}
    assert any(edge.kind is EdgeKind.MAY_RAISE for edge in control_flow.edges.values())
    assert control_flow.to_dict() == original_graph
    assert validate_proof_ledger(ledger, context, request)["valid"]
    assert ProofLedger.from_json(ledger.to_json(), context=context,
                                 request=request) == ledger
    forged_obligations = list(ledger.obligations)
    forged_obligations[-1] = replace(forged_obligations[-1],
        status=ProofStatus.UNKNOWN, reason="forged stored status")
    assert not validate_proof_ledger(replace(ledger,
        obligations=tuple(forged_obligations)), context, request)["valid"]


@pytest.mark.parametrize("predicate", [
    QPredicate.TARGET_RUNTIME_MATCH,
    QPredicate.RESOURCE_FAILURE_UNOBSERVED,
    QPredicate.ASYNC_INTERRUPTION_UNOBSERVED,
    QPredicate.FRAME_NAMESPACE_OBSERVATION_UNOBSERVED,
    QPredicate.TRACE_EVENT_ORDER_UNOBSERVED,
    QPredicate.REFERENCE_COUNT_OBSERVATION_UNOBSERVED,
])
def test_static_motion_requires_each_precise_observation_condition(tmp_path, predicate):
    _, text, _, _, _, _, _, context, request = _motion_case(tmp_path)
    context = _accepted_motion_q(context, text)
    report = _statement_report(context.bundle.semantic, context.source_semantics,
                               context.source_control_flow, text)
    moved_source = request.delta.static_moves[0].fragment.source
    moved = next(item for item in report.certificates
                 if item.source == moved_source)
    subject = static_motion_q_subject(predicate, moved.statement, moved.source)
    assumptions = tuple(item for item in context.q.assumptions
                        if not (item.predicate is predicate and item.subject == subject))
    context = replace(context, q=replace(context.q, assumptions=assumptions))

    ledger = derive_proof_ledger(context, request)

    assert ledger.outcome is not ProofOutcome.CONDITIONALLY_LEGAL
    assert not all(item.status is ProofStatus.PROVEN for item in ledger.obligations)
    assert any(predicate.value in item.reason for item in ledger.obligations)


def test_static_motion_without_source_cfg_or_source_precondition_q_stays_unknown(tmp_path):
    _, text, _, _, _, _, _, context, request = _motion_case(tmp_path)
    context = _accepted_motion_q(context, text)
    no_cfg = replace(context, source_control_flow=None)

    no_cfg_ledger = derive_proof_ledger(no_cfg, request)

    assert no_cfg_ledger.outcome is ProofOutcome.NOT_YET_SUPPORTED
    assert all(item.status is ProofStatus.UNKNOWN for item in no_cfg_ledger.obligations)

    assumption = next(item for item in context.q.assumptions
                      if item.predicate is QPredicate.SOURCE_PRECONDITION
                      and item.subject == "standard_function_locals")
    context = replace(context, q=replace(context.q, assumptions=tuple(
        item for item in context.q.assumptions if item != assumption)))
    missing_precondition = derive_proof_ledger(context, request)
    assert missing_precondition.outcome is not ProofOutcome.CONDITIONALLY_LEGAL
    assert any("standard_function_locals" in item.reason
               for item in missing_precondition.obligations)


def test_static_motion_cannot_move_before_its_local_input(tmp_path):
    _, text, _, _, control_flow, fragment, _, context, request = _motion_case(tmp_path)
    context = _accepted_motion_q(context, text)
    entry_insertion = next(item for item in control_flow.insertions.values()
                           if item.kind is InsertionKind.ENTRY
                           and item.suite == fragment.suite)
    request = replace(request, delta=TransformDelta(static_moves=(
        StaticSourceMove(fragment, entry_insertion.id),)))

    ledger = derive_proof_ledger(context, request)

    availability = next(item for item in ledger.obligations
                        if item.name == "all_inputs_state_available_at_target")
    assert availability.status is ProofStatus.DISPROVEN
    assert ledger.outcome is ProofOutcome.ILLEGAL


def test_static_motion_keeps_unknown_for_opaque_crossed_statement(tmp_path):
    text = (
        "def f():\n"
        "    token = ()\n"
        "    marker = observe()\n"
        "    alias = token\n"
        "    return alias\n"
    )
    _, _, _, _, _, _, _, context, request = _motion_case(tmp_path, text)

    ledger = derive_proof_ledger(context, request)

    assert ledger.outcome is ProofOutcome.NOT_YET_SUPPORTED
    assert all(item.status is ProofStatus.UNKNOWN for item in ledger.obligations)


@pytest.mark.parametrize("text, moved_line, target_line", [
    (
        "def f():\n"
        "    token = ()\n"
        "    token = ()\n"
        "    alias = token\n"
        "    return alias\n",
        4, 2,
    ),
    (
        "def f():\n"
        "    token = ()\n"
        "    if True:\n"
        "        marker = 1 + 2\n"
        "    alias = token\n"
        "    return alias\n",
        5, 2,
    ),
    (
        "def f():\n"
        "    token = ()\n"
        "    try:\n"
        "        marker = 1 + 2\n"
        "    finally:\n"
        "        pass\n"
        "    alias = token\n"
        "    return alias\n",
        7, 2,
    ),
    (
        "def f():\n"
        "    token = ()\n"
        "    for item in ():\n"
        "        pass\n"
        "    alias = token\n"
        "    return alias\n",
        5, 2,
    ),
    (
        "def f():\n"
        "    token = []\n"
        "    marker = 1 + 2\n"
        "    alias = token\n"
        "    return alias\n",
        4, 2,
    ),
])
def test_static_motion_rejects_rebind_branch_finally_loop_and_mutable_gaps(
        tmp_path, text, moved_line, target_line):
    _, _, _, _, _, _, _, context, request = _motion_case(
        tmp_path, text, moved_line=moved_line, target_line=target_line)

    ledger = derive_proof_ledger(context, request)

    assert ledger.outcome is not ProofOutcome.CONDITIONALLY_LEGAL
    assert not all(item.status is ProofStatus.PROVEN for item in ledger.obligations)


def test_static_motion_rejects_insertion_from_a_different_lexical_suite(tmp_path):
    _, text, _, _, control_flow, fragment, _, context, request = _motion_case(tmp_path)
    context = _accepted_motion_q(context, text)
    other_suite_entry = next(item for item in control_flow.insertions.values()
        if item.kind is InsertionKind.ENTRY and item.suite != fragment.suite)
    request = replace(request, delta=TransformDelta(static_moves=(
        StaticSourceMove(fragment, other_suite_entry.id),)))

    ledger = derive_proof_ledger(context, request)

    precise = next(item for item in ledger.obligations
                   if item.name == "precise_insertion_point_and_delta")
    assert precise.status is ProofStatus.DISPROVEN
    assert ledger.outcome is ProofOutcome.ILLEGAL


def test_static_motion_rejects_nonupward_insertion_and_low_query_budget(tmp_path):
    _, text, _, _, control_flow, fragment, _, context, request = _motion_case(tmp_path)
    context = _accepted_motion_q(context, text)
    after_original = next(item for item in control_flow.insertions.values()
                          if item.kind is InsertionKind.AFTER
                          and item.anchor == fragment.statement)
    same_position = replace(request, delta=TransformDelta(static_moves=(
        StaticSourceMove(fragment, after_original.id),)))

    ledger = derive_proof_ledger(context, same_position)
    precise = next(item for item in ledger.obligations
                   if item.name == "precise_insertion_point_and_delta")
    assert precise.status is ProofStatus.DISPROVEN
    assert ledger.outcome is ProofOutcome.ILLEGAL

    bounded = replace(context,
        control_verification_budget=ControlFlowBudget(max_query_work=1))
    bounded_ledger = derive_proof_ledger(bounded, request)
    assert bounded_ledger.outcome is not ProofOutcome.CONDITIONALLY_LEGAL
    assert not all(item.status is ProofStatus.PROVEN
                   for item in bounded_ledger.obligations)
