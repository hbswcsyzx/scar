"""Source-replayed local statement certificates for the narrow MOVE subset."""
from dataclasses import replace
import json

import pytest

from scar.analysis.constants_v2 import EvaluationBudget
from scar.analysis.control_flow_v2 import build_source_control_flow
from scar.analysis.local_statement_semantics_v2 import (
    Coverage, GapKind, LocalStatementSemanticsReport, RequiredCondition,
    StatementFact, StatementKind, derive_local_statement_semantics,
    validate_local_statement_semantics,
)
from scar.analysis.source_semantics_v2 import extract_source_semantics
from scar.ir.control_flow_v2 import ControlFlowBudget, SuiteKind
from scar.ir.frontend_v2 import build_semantic


def _case(tmp_path, text):
    path = tmp_path / "program.py"
    path.write_text(text)
    semantic = build_semantic(path).graph
    source_semantics = extract_source_semantics(semantic)
    control_flow = build_source_control_flow(semantic, source_semantics)
    suites = [item for item in control_flow.suites.values()
              if item.kind is SuiteKind.FUNCTION]
    assert len(suites) == 1
    texts = {str(path): text}
    report = derive_local_statement_semantics(
        semantic, source_semantics, control_flow, suites[0].id,
        source_texts=texts)
    return semantic, source_semantics, control_flow, suites[0].id, texts, report


def test_closed_straight_line_function_certifies_assign_alias_and_return(tmp_path):
    semantic, source_semantics, cfg, suite, texts, report = _case(tmp_path,
        "def f():\n"
        "    token = ()\n"
        "    marker = 1 + 2\n"
        "    alias = token\n"
        "    return alias\n")

    assert report.coverage is Coverage.SUPPORTED
    assert [item.kind for item in report.certificates] == [
        StatementKind.ASSIGN_LITERAL,
        StatementKind.ASSIGN_CONSTANT,
        StatementKind.ASSIGN_ALIAS,
        StatementKind.RETURN_LOCAL,
    ]
    assert report.certificates[1].ordered_reads == ()
    alias, returned = report.certificates[2:]
    assert alias.alias_source_binding == report.certificates[0].written_binding
    assert alias.facts.count(StatementFact.ALIAS_IDENTITY_PRESERVED) == 1
    assert returned.alias_source_binding == alias.written_binding
    assert alias.required_conditions == tuple(RequiredCondition)
    assert RequiredCondition.FRAME_AND_BINDING_TIMING_UNOBSERVED in alias.required_conditions
    assert RequiredCondition.REFCOUNT_AND_FINALIZER_OBSERVATION_UNOBSERVED in alias.required_conditions
    assert all("value_identity_unobserved" not in
               {condition.value for condition in item.required_conditions}
               for item in report.certificates)
    assert validate_local_statement_semantics(
        report, semantic, source_semantics, cfg, suite,
        source_texts=texts)["valid"]


def test_unused_first_local_is_allowed_but_duplicate_write_is_not(tmp_path):
    _, _, _, _, _, positive = _case(tmp_path,
        "def f():\n    marker = 1 + 2\n    return 7\n")
    assert positive.coverage is Coverage.SUPPORTED

    _, _, _, _, _, negative = _case(tmp_path,
        "def f():\n    marker = 1\n    marker = 2\n    return marker\n")
    assert negative.coverage is Coverage.INCOMPLETE
    assert any(item.kind is GapKind.REBOUND_LOCAL for item in negative.gaps)


@pytest.mark.parametrize("body, gap", [
    ("return x", GapKind.UNRESOLVED_READ),
    ("x = 1\n    x = 2\n    return x", GapKind.REBOUND_LOCAL),
    ("x = []\n    return x", GapKind.UNSUPPORTED_EXPRESSION),
    ("x = opaque()\n    return x", GapKind.UNSUPPORTED_EXPRESSION),
    ("x = 1 // 0\n    return x", GapKind.KNOWN_EXCEPTION),
    ("if True:\n        x = 1\n    return 2", GapKind.CONTROL_FLOW_GAP),
    ("while False:\n        x = 1\n    return 2", GapKind.CONTROL_FLOW_GAP),
    ("global x\n    x = 1\n    return x", GapKind.UNSUPPORTED_FUNCTION),
])
def test_unsupported_or_unresolved_body_never_gets_complete_coverage(tmp_path, body, gap):
    _, _, _, _, _, report = _case(tmp_path, "def f():\n    " + body.replace("\n    ", "\n    ") + "\n")
    assert report.coverage is Coverage.INCOMPLETE
    assert any(item.kind is gap for item in report.gaps)


def test_parameter_target_and_capture_are_not_local_first_bindings(tmp_path):
    _, _, _, _, _, parameter = _case(tmp_path,
        "def f(x):\n    x = 2\n    return x\n")
    assert parameter.coverage is Coverage.INCOMPLETE
    assert any(item.kind is GapKind.NONLOCAL_OR_PARAMETER for item in parameter.gaps)

    path = tmp_path / "capture.py"
    path.write_text("seed = 1\ndef f():\n    return seed\n")
    semantic = build_semantic(path).graph
    source_semantics = extract_source_semantics(semantic)
    cfg = build_source_control_flow(semantic, source_semantics)
    suite = next(item for item in cfg.suites.values() if item.kind is SuiteKind.FUNCTION)
    report = derive_local_statement_semantics(
        semantic, source_semantics, cfg, suite.id, source_texts={str(path): path.read_text()})
    assert report.coverage is Coverage.INCOMPLETE
    assert any(item.kind in {GapKind.EXTERNAL_OR_CLOSURE_READ, GapKind.UNRESOLVED_READ}
               for item in report.gaps)


def test_report_serde_recomputes_and_rejects_forged_stale_or_reordered_records(tmp_path):
    semantic, source_semantics, cfg, suite, texts, report = _case(tmp_path,
        "def f():\n    value = 2\n    return value\n")
    document = report.to_dict()
    decoded = LocalStatementSemanticsReport.from_dict(
        document, semantic=semantic, source_semantics=source_semantics,
        control_flow=cfg, suite=suite, source_texts=texts)
    assert decoded.to_dict() == document

    forged = json.loads(json.dumps(document))
    forged["report"]["coverage"] = Coverage.INCOMPLETE.value
    with pytest.raises(ValueError):
        LocalStatementSemanticsReport.from_dict(
            forged, semantic=semantic, source_semantics=source_semantics,
            control_flow=cfg, suite=suite, source_texts=texts)

    reordered = json.loads(json.dumps(document))
    reordered["report"]["certificates"].reverse()
    with pytest.raises(ValueError):
        LocalStatementSemanticsReport.from_dict(
            reordered, semantic=semantic, source_semantics=source_semantics,
            control_flow=cfg, suite=suite, source_texts=texts)

    stale_texts = {next(iter(texts)): texts[next(iter(texts))].replace("value = 2", "value = 3")}
    assert not validate_local_statement_semantics(
        report, semantic, source_semantics, cfg, suite,
        source_texts=stale_texts)["valid"]


def test_verification_budget_cannot_be_raised_by_report(tmp_path):
    semantic, source_semantics, cfg, suite, texts, report = _case(tmp_path,
        "def f():\n    value = 2\n    return value\n")
    small = EvaluationBudget(max_nodes=1, max_steps=1, max_work=1,
        max_int_bits=1, max_sequence_items=1, max_bytes=1,
        max_total_output_bytes=1, max_literal_depth=1)
    assert not validate_local_statement_semantics(
        report, semantic, source_semantics, cfg, suite, source_texts=texts,
        verification_budget=small)["valid"]


def test_float_arithmetic_requires_an_unavailable_environment_q_but_literal_is_replayed(tmp_path):
    _, _, _, _, _, arithmetic = _case(tmp_path,
        "def f():\n    value = 1.25 + 2.0\n    return value\n")
    assert arithmetic.coverage is Coverage.INCOMPLETE
    assert any("floating-environment Q" in item.reason for item in arithmetic.gaps)

    _, _, _, _, _, literal = _case(tmp_path,
        "def f():\n    value = 1.25\n    return value\n")
    assert literal.coverage is Coverage.SUPPORTED
    assert literal.certificates[0].immutable_type == "float64"


@pytest.mark.parametrize("expression", ["locals()", "getrefcount(value)"])
def test_frame_and_reference_count_introspection_are_not_certified(tmp_path, expression):
    body = "value = 1\n    observed = " + expression + "\n    return observed"
    _, _, _, _, _, report = _case(tmp_path, "def f():\n    " + body + "\n")
    assert report.coverage is Coverage.INCOMPLETE
    assert any(item.kind is GapKind.UNSUPPORTED_EXPRESSION for item in report.gaps)
