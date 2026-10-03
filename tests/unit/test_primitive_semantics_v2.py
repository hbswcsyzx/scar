from copy import deepcopy
from dataclasses import replace
import json
from itertools import count

import pytest

from scar.analysis.primitive_semantics_v2 import (
    PrimitiveEffect,
    PrimitiveGapKind,
    PrimitiveObservationBoundary,
    PrimitiveOutputIdentity,
    PrimitiveOutputType,
    PrimitiveSemanticsReport,
    derive_primitive_semantics,
)
from scar.analysis.source_semantics_v2 import extract_source_semantics, validate_source_semantics
from scar.ir.frontend_v2 import build_semantic
from scar.ir.semantics_v2 import Opcode, SourceSemanticsGraph
from scar.ir.semantics_v2 import BoundaryKind
from scar.analysis.constants_v2 import EvaluationBudget
from scar.analysis.constants_v2 import ConstantStatus, evaluate_constants
from scar.analysis.import_values_v2 import ImportValueStatus, resolve_import_values


def capture(tmp_path, text):
    path = tmp_path / "program.py"
    path.write_text(text)
    semantic = build_semantic(path).graph
    overlay = extract_source_semantics(semantic)
    return path, semantic, overlay


def operations(overlay, opcode):
    return [item for item in overlay.operations.values() if item.opcode is opcode]


def test_is_certificate_replays_actual_operator_and_ordered_inputs(tmp_path):
    _, semantic, overlay = capture(tmp_path, "left = object()\nright = object()\nanswer = left is right\n")
    operation, = operations(overlay, Opcode.IS)
    report = derive_primitive_semantics(semantic, overlay, operation.operation)
    certificate = report.certificates[operation.operation]

    assert [(item.role, item.index) for item in certificate.inputs] == [
        ("left", 0), ("right", 1)]
    assert [item.value for item in certificate.inputs] == [item.value for item in operation.operands]
    assert certificate.result == operation.result
    assert certificate.output_type is PrimitiveOutputType.BOOL
    assert certificate.output_identity is PrimitiveOutputIdentity.BOOL_SINGLETON
    assert set(certificate.effects) == set(PrimitiveEffect)
    assert report.source_replay.value == "VALID"
    assert not hasattr(certificate, "pure")
    assert not hasattr(certificate, "status")


def test_is_not_has_same_primitive_contract_with_source_bound_opcode(tmp_path):
    _, semantic, overlay = capture(tmp_path, "answer = left is not right\n")
    operation, = operations(overlay, Opcode.IS_NOT)
    report = derive_primitive_semantics(semantic, overlay, operation.operation)

    assert report.certificates[operation.operation].opcode is Opcode.IS_NOT
    assert validate_source_semantics(overlay, semantic)["valid"]


def test_constant_and_import_value_evaluators_leave_identity_result_nonliteral(tmp_path):
    _, semantic, overlay = capture(tmp_path, "left = 1\nright = 2\nanswer = left is right\n")
    operation, = operations(overlay, Opcode.IS)
    constants = evaluate_constants(overlay, targets=(operation.result,))
    import_values = resolve_import_values(semantic, overlay, targets=(operation.result,))

    assert constants.facts[operation.result].status is ConstantStatus.NOT_CONSTANT
    fact = import_values.facts[operation.result]
    assert fact.status in {ImportValueStatus.UNRESOLVED, ImportValueStatus.BLOCKED}
    assert fact.literal is None
    assert fact.gaps


def test_call_operands_are_outside_the_certificate_scope(tmp_path):
    _, semantic, overlay = capture(tmp_path, "answer = make_left() is make_right()\n")
    comparison, = operations(overlay, Opcode.IS)
    calls = operations(overlay, Opcode.CALL)
    report = derive_primitive_semantics(
        semantic, overlay, (comparison.operation, *(item.operation for item in calls)))

    assert comparison.operation in report.certificates
    assert report.certificates[comparison.operation].excluded_regions
    assert len(report.certificates[comparison.operation].excluded_regions) == 2
    assert report.certificates[comparison.operation].scope.observation_boundaries == tuple(
        PrimitiveObservationBoundary)
    assert all(item.operation in report.gaps for item in calls)
    assert not any(item.operation in report.certificates for item in calls)


def test_identity_analysis_never_runs_user_eq_method(tmp_path):
    marker = tmp_path / "eq-was-called"
    source = f"""class Probe:
    def __eq__(self, other):
        open({str(marker)!r}, 'w').write('called')
        return True
left = Probe()
right = Probe()
answer = left is right
"""
    _, semantic, overlay = capture(tmp_path, source)
    identity, = operations(overlay, Opcode.IS)
    report = derive_primitive_semantics(semantic, overlay, identity.operation)

    assert identity.operation in report.certificates
    assert not marker.exists()


def test_chained_identity_comparison_stays_opaque_with_specific_gap(tmp_path):
    _, semantic, overlay = capture(tmp_path, "answer = left is middle is right\n")
    opaque, = [item for item in operations(overlay, Opcode.OPAQUE)
               if item.source.start_line == 1]
    report = derive_primitive_semantics(semantic, overlay, opaque.operation)

    assert opaque.operation not in report.certificates
    boundary, = [item for item in overlay.boundaries if item.operation == opaque.operation]
    assert boundary.kind is BoundaryKind.COMPARISON_SHORT_CIRCUIT
    gap = report.gaps[opaque.operation]
    assert gap.kind is PrimitiveGapKind.BLOCKED_COMPARISON
    assert "chained" in gap.reason
    assert "conditionally evaluate" in gap.required_fact


@pytest.mark.parametrize("expression", ["left == right", "item in container"])
def test_nonidentity_comparisons_remain_opaque_without_user_dispatch(tmp_path, expression):
    _, semantic, overlay = capture(tmp_path, f"answer = {expression}\n")
    opaque, = [item for item in operations(overlay, Opcode.OPAQUE)
               if item.source.start_line == 1]
    report = derive_primitive_semantics(semantic, overlay, opaque.operation)

    boundary, = [item for item in overlay.boundaries if item.operation == opaque.operation]
    assert boundary.kind is BoundaryKind.COMPARISON_DISPATCH
    assert report.gaps[opaque.operation].kind is PrimitiveGapKind.BLOCKED_COMPARISON
    assert opaque.operation not in report.certificates


@pytest.mark.parametrize("tamper", ["opcode", "operand_order"])
def test_source_replay_rejects_identity_opcode_or_input_order_tampering(tmp_path, tamper):
    _, semantic, overlay = capture(tmp_path, "answer = left is right\n")
    operation, = operations(overlay, Opcode.IS)
    forged = deepcopy(overlay)
    if tamper == "opcode":
        forged.operations[operation.operation] = replace(operation, opcode=Opcode.IS_NOT)
    else:
        left, right = operation.operands
        forged.operations[operation.operation] = replace(operation, operands=(
            replace(left, value=right.value), replace(right, value=left.value)))

    assert forged.validate(semantic)["valid"]
    assert not validate_source_semantics(forged, semantic)["valid"]
    with pytest.raises(ValueError, match="source replay failed"):
        derive_primitive_semantics(semantic, forged, operation.operation)


@pytest.mark.parametrize("tamper", ["rule_version", "opcode", "inputs"])
def test_report_serde_rederives_rule_version_certificate_and_current_source(tmp_path, tamper):
    path, semantic, overlay = capture(tmp_path, "answer = left is right\n")
    operation, = operations(overlay, Opcode.IS)
    report = derive_primitive_semantics(semantic, overlay, operation.operation)
    document = report.to_dict()
    expected_preconditions = tuple(sorted(
        overlay.required_preconditions, key=lambda item: item.value))
    assert report.source_preconditions == expected_preconditions
    assert report.certificates[operation.operation].scope.source_preconditions == (
        expected_preconditions)
    # from_dict normalizes the source precondition set into wire order.  Replaying
    # the report against a strictly reconstituted graph must derive identical
    # precondition tuples in both the top-level record and certificate scope.
    restored_overlay = SourceSemanticsGraph.from_dict(overlay.to_dict(), semantic)
    assert restored_overlay.to_dict() == overlay.to_dict()
    restored = PrimitiveSemanticsReport.from_dict(
        document, semantic=semantic, source_semantics=restored_overlay)
    assert restored.summary() == report.summary()
    assert report.usage.output_bytes == len(json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("utf-8"))

    tampered = deepcopy(document)
    if tamper == "rule_version":
        tampered["rule_version"] = "caller-selected-version"
    elif tamper == "opcode":
        tampered["certificates"][0]["opcode"] = Opcode.IS_NOT.value
    else:
        inputs = tampered["certificates"][0]["inputs"]
        inputs[0]["value"], inputs[1]["value"] = inputs[1]["value"], inputs[0]["value"]
    with pytest.raises(ValueError, match="differs"):
        PrimitiveSemanticsReport.from_dict(
            tampered, semantic=semantic, source_semantics=overlay)

    path.write_text("answer = left is not right\n")
    assert not report.validate()["valid"]


def test_source_semantics_schema_v1_migration_and_current_schema_stay_stable(tmp_path):
    _, semantic, overlay = capture(tmp_path, "answer = 3\n")
    current = overlay.to_dict()
    assert current["schema_version"] == SourceSemanticsGraph.SCHEMA_VERSION == 2

    legacy = deepcopy(current)
    legacy["schema_version"] = 1
    legacy.pop("boundaries")
    for item in legacy["uses"]:
        item.pop("conditional_reaching")
    restored = SourceSemanticsGraph.from_dict(legacy, semantic)
    operation, = operations(restored, Opcode.LITERAL)
    assert restored.to_dict()["schema_version"] == 2
    assert operation.opcode is Opcode.LITERAL
    assert validate_source_semantics(restored, semantic)["valid"]

    _, identity_semantic, identity_overlay = capture(tmp_path, "answer = left is right\n")
    identity_op, = operations(identity_overlay, Opcode.IS)
    assert identity_overlay.to_dict()["schema_version"] == 2
    assert validate_source_semantics(identity_overlay, identity_semantic)["valid"]
    assert identity_op.opcode is Opcode.IS


def test_verification_budget_cannot_be_raised_by_report(tmp_path):
    _, semantic, overlay = capture(tmp_path, "answer = left is right\n")
    operation, = operations(overlay, Opcode.IS)
    report = derive_primitive_semantics(semantic, overlay, operation.operation,
        budget=EvaluationBudget(max_nodes=20))
    ceiling = EvaluationBudget(max_nodes=10)

    assert not report.validate(verification_budget=ceiling)["valid"]


def test_unbounded_target_iterable_is_stopped_by_node_budget(tmp_path):
    _, semantic, overlay = capture(tmp_path, "answer = left is right\n")
    with pytest.raises(ValueError, match="target count exceeds max_nodes"):
        derive_primitive_semantics(semantic, overlay, count(),
            budget=EvaluationBudget(max_nodes=2))
