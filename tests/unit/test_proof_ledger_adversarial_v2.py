"""Integration-owner adversaries: exact content cannot launder extra rewrites."""
from dataclasses import replace

import pytest

from scar.analysis.proof_ledger_v2 import (
    ProofContext, ProofFamily, ProofOutcome, ProofQ, ProofRequest,
    QAssumption, QPredicate, derive_proof_ledger,
)
from scar.analysis.regions_v2 import RegionInventory
from scar.analysis.source_semantics_v2 import extract_source_semantics
from scar.ir.frontend_v2 import build_semantic
from scar.ir.semantics_v2 import Opcode, PythonLiteral, SourceExecutionPrecondition
from scar.ir.v2 import (
    EvidenceClaim, EvidenceGraph, EvidenceKind, IRBundle, ProofStatus,
    StaticValueSubstitution, TransformDelta, ValueGraph,
)


def context_and_request(tmp_path, text, target_line, literal):
    source = tmp_path / "program.py"
    source.write_text(text)
    semantic = build_semantic(source).graph
    model = extract_source_semantics(semantic)
    bundle = IRBundle(semantic, EvidenceGraph(), ValueGraph(), source_semantics=model)
    inventory = RegionInventory(bundle)
    region = inventory.region(tuple(model.operations))
    operation = next(op for op in model.operations.values()
                     if op.opcode is Opcode.ADD and op.source.start_line == target_line)
    evidence = EvidenceClaim(EvidenceKind.DECLARED, ("test:explicit-value-contract",), scope=inventory.scope)
    assumptions = (
        QAssumption(QPredicate.TARGET_RUNTIME_MATCH, "builtin_runtime_match", evidence),
        QAssumption(QPredicate.VALUE_IDENTITY_UNOBSERVED, operation.result.wire, evidence),
    )
    q = ProofQ(inventory.scope, assumptions)
    context = ProofContext(bundle, model, inventory, inventory.scope, q)
    request = ProofRequest(ProofFamily.CONSTANT, region,
        TransformDelta(static_substitutions=(StaticValueSubstitution(
            operation.result, operation.operation, operation.source, PythonLiteral.from_python(literal)),)))
    return source, context, request


def test_constant_rule_cannot_hide_deleted_io_in_same_region(tmp_path):
    _, context, request = context_and_request(tmp_path, "answer = 2 + 3\nprint(answer)\n", 1, 5)
    call = next(op for op in context.source_semantics.operations.values() if op.opcode is Opcode.CALL)
    forged = replace(request, delta=replace(request.delta, removed_definitions=(call.operation,)))
    with pytest.raises(ValueError):
        derive_proof_ledger(context, forged)


def test_premise_binding_conditions_cannot_disappear_at_parent_arithmetic(tmp_path):
    _, context, request = context_and_request(tmp_path, "input_value = 11\nanswer = input_value + 2\n", 2, 13)
    ledger = derive_proof_ledger(context, request)
    required = [item for item in ledger.obligations if item.name == "source_precondition_in_Q"]
    subjects = {item.subject.rsplit(":", 1)[-1] for item in required}
    assert SourceExecutionPrecondition.FRESH_MODULE_NAMESPACE.value in subjects
    assert SourceExecutionPrecondition.NO_EXTERNAL_NAMESPACE_MUTATION.value in subjects
    assert all(item.status is ProofStatus.UNKNOWN for item in required)
    assert ledger.outcome is ProofOutcome.NEEDS_CONTRACT


def test_source_content_match_does_not_cover_output_identity(tmp_path):
    _, context, request = context_and_request(tmp_path, "answer = 5000 + 7\n", 1, 5007)
    q = replace(context.q, assumptions=tuple(item for item in context.q.assumptions
                                             if item.predicate is not QPredicate.VALUE_IDENTITY_UNOBSERVED))
    ledger = derive_proof_ledger(replace(context, q=q), request)
    identity = next(item for item in ledger.obligations if item.name == "replacement_identity_is_unobserved")
    assert identity.status is ProofStatus.UNKNOWN
    assert ledger.outcome is ProofOutcome.NEEDS_CONTRACT


def test_namespace_and_value_facts_do_not_cover_resource_failure_timing(tmp_path):
    _, context, request = context_and_request(tmp_path, "answer = 2 + 3\n", 1, 5)
    ledger = derive_proof_ledger(context, request)
    resource = next(item for item in ledger.obligations
                    if item.name == "replacement_resource_failures_are_unobserved")
    assert resource.status is ProofStatus.UNKNOWN
    assert ledger.outcome is ProofOutcome.NEEDS_CONTRACT


def test_bool_replacement_is_not_interchangeable_with_equal_integer(tmp_path):
    _, context, request = context_and_request(tmp_path, "answer = 0 + 1\n", 1, True)
    ledger = derive_proof_ledger(context, request)
    assert ledger.outcome is ProofOutcome.ILLEGAL
    assert next(item for item in ledger.obligations if item.name == "constant_value_matches_replacement").status is ProofStatus.DISPROVEN


def test_wrong_source_span_cannot_borrow_an_exact_constant_proof(tmp_path):
    _, context, request = context_and_request(tmp_path, "answer = 2 + 3\nother = 6 + 7\n", 1, 5)
    other = next(op for op in context.source_semantics.operations.values()
                 if op.opcode is Opcode.ADD and op.source.start_line == 2)
    substitution, = request.delta.static_substitutions
    forged = replace(request, delta=replace(request.delta,
        static_substitutions=(replace(substitution, source=other.source),)))
    try:
        ledger = derive_proof_ledger(context, forged)
    except ValueError:
        return
    assert ledger.outcome is ProofOutcome.ILLEGAL


def test_current_filesystem_change_invalidates_source_replay_before_proof(tmp_path):
    source, context, request = context_and_request(tmp_path, "answer = 2 + 3\n", 1, 5)
    source.write_text("answer = 2 + 30\n")
    with pytest.raises(ValueError, match="source replay"):
        derive_proof_ledger(context, request)
