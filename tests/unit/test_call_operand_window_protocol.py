"""Capture rules select observation scope without changing operand authority."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import scar.analysis.call_operand_reader as reader
from scar.analysis.call_operands import CallOperandReport, link_call_operands
from scar.analysis.program_inventory import inventory_program
from scar.ir.program.call_operands import (
    CALL_WINDOWS_RULE, LOAD_OCCURRENCES_RULE, OPERAND_CAPTURE_RULES,
    CallOperandBudget, OperandCollectionMetadata,
)
from scar.ir.record_codec import decode, encode
from tests.unit.test_call_operand_reader import captured as captured, _write_sidecar
from tests.unit.test_call_operand_records import metadata


@pytest.mark.parametrize("rule", (LOAD_OCCURRENCES_RULE, CALL_WINDOWS_RULE))
def test_rule_is_an_exact_string_and_preserves_the_existing_wire_fields(rule):
    old = metadata()
    current = replace(old, rule=rule)
    document = encode(current)
    assert type(current.rule) is str
    assert set(document) == set(encode(old))
    assert document == {**encode(old), "rule": rule}
    assert decode(OperandCollectionMetadata, document) == current
    assert OPERAND_CAPTURE_RULES == frozenset((LOAD_OCCURRENCES_RULE, CALL_WINDOWS_RULE))


@pytest.mark.parametrize("rule", ("CPYTHON_CALL_WINDOWS_V2", "windows", "", True, 1, None, [], {}))
def test_unknown_or_non_string_capture_rules_are_rejected(rule):
    with pytest.raises(ValueError):
        replace(metadata(), rule=rule)
    document = {**encode(metadata()), "rule": rule}
    with pytest.raises(ValueError):
        decode(OperandCollectionMetadata, document)


def test_rule_rejects_str_subclasses_even_when_the_text_is_supported():
    class Claim(str):
        pass

    with pytest.raises(ValueError, match="text"):
        replace(metadata(), rule=Claim(CALL_WINDOWS_RULE))


def test_unknown_rule_is_rejected_before_operand_rows_are_opened(captured, monkeypatch):
    root, output, _, paths, *_ = captured
    changed = {**paths[2], "rule": "CPYTHON_CALL_WINDOWS_V999"}
    paths[1].write_text(json.dumps(changed))
    original = reader.open_binary

    def checked(path):
        assert not path.name.startswith("call-operands."), "rule must be validated before sidecar rows"
        return original(path)

    monkeypatch.setattr(reader, "open_binary", checked)
    with pytest.raises(ValueError, match="rule is unsupported"):
        reader.read_call_operands(output, root)


def _renumber(rows):
    """Protocol fixture edits preserve observation-local snapshot namespaces."""
    mapping = {row["index"]: index for index, row in enumerate(rows, 1)}

    def change(value):
        if type(value) is dict:
            return {key: change(item) for key, item in value.items()}
        if type(value) is list:
            return [change(item) for item in value]
        if type(value) is str and value.startswith("operand-snapshot:"):
            _, process, index, ordinal = value.split(":")
            return f"operand-snapshot:{process}:{mapping[int(index)]}:{ordinal}"
        return value

    result = []
    for row in rows:
        changed = change(row)
        changed["index"] = mapping[row["index"]]
        if "attempt_index" in row:
            changed["attempt_index"] = mapping[row["attempt_index"]]
        result.append(changed)
    return result


def test_intentionally_unobserved_nonwindow_instruction_is_not_a_lost_event(captured):
    root, output, rows, _, base_scan, sink = captured
    assert rows[0]["site"]["opname"] == "RESUME"
    selected = _renumber(rows[1:])
    _write_sidecar(output, root, selected, metadata_changes={"rule": CALL_WINDOWS_RULE})

    result = reader.read_call_operands(output, root)

    assert len(result.events) == len(rows) - 1
    assert not result.issues
    assert result.frame_scan == base_scan
    assert result.entries == tuple(sink.entries) and result.exits == tuple(sink.exits)
    meta, = result.metadata
    assert meta.rule == CALL_WINDOWS_RULE
    assert meta.events == meta.event_attempts == len(selected)
    assert meta.dropped_events == 0
    assert not any((meta.reference_contents_observed, meta.callable_environment_established,
                    meta.transformation_authorized))


@pytest.mark.parametrize("cancellation", ("INSTRUCTION", "GAP"))
def test_windows_cancellation_still_expires_the_exact_pending_attempt(captured, cancellation):
    root, output, rows, *_ = captured
    attempt = rows[-2]
    cancelled = {key: attempt[key] for key in (
        "process_id", "thread_id", "invocation_id", "frame_index", "hook_epoch")}
    cancelled.update(index=9999, kind=cancellation)
    if cancellation == "INSTRUCTION":
        cancelled.update(site=deepcopy(attempt["site"]), loads=[])
    else:
        cancelled["reason"] = "PROJECT_FUNCTION_CALL_DID_NOT_ENTER"
    changed = _renumber([*rows[:-1], cancelled, rows[-1]])
    _write_sidecar(output, root, changed, metadata_changes={"rule": CALL_WINDOWS_RULE})

    with pytest.raises(ValueError, match="stale|superseded"):
        reader.read_call_operands(output, root)


@pytest.mark.parametrize("field,value,issue", (
    ("dropped_events", 1, "COLLECTION_GAP"),
    ("errors", ["capture failed"], "COLLECTION_GAP"),
    ("io_failed", True, "COLLECTION_GAP"),
    ("previous_profile", True, "PREVIOUS_PROFILE"),
))
def test_windows_real_loss_or_interference_remains_a_process_boundary(captured, field, value, issue):
    root, output, rows, *_ = captured
    _write_sidecar(output, root, rows, metadata_changes={"rule": CALL_WINDOWS_RULE, field: value})

    result = reader.read_call_operands(output, root)

    matched = [item for item in result.issues if item.kind == issue]
    assert len(matched) == 1
    assert matched[0].process_id == result.metadata[0].process_id
    assert matched[0].invocation is None and matched[0].anchor is None


@pytest.mark.parametrize("field", (
    "reference_contents_observed", "callable_environment_established", "transformation_authorized",
))
def test_windows_scope_cannot_enable_an_authority_flag(captured, field):
    root, output, rows, *_ = captured
    _write_sidecar(output, root, rows, metadata_changes={"rule": CALL_WINDOWS_RULE, field: True})
    with pytest.raises(ValueError, match="grant"):
        reader.read_call_operands(output, root)


def test_windows_rows_are_still_charged_to_independent_event_budget(captured):
    root, output, rows, *_ = captured
    _write_sidecar(output, root, rows, metadata_changes={"rule": CALL_WINDOWS_RULE})
    with pytest.raises(ValueError, match="aggregate event/load/reference budget"):
        reader.read_call_operands(output, root, budget=replace(CallOperandBudget(), max_events=len(rows) - 1))


def _capture(project, trace, capture, *, public_cli=False):
    repository = Path(__file__).resolve().parents[2]
    environment = {key: value for key, value in os.environ.items() if not key.startswith("SCAR_")}
    environment.update(PYTHONPATH=str(repository), PYTHONDONTWRITEBYTECODE="1")
    script = (
        "import runpy, sys\n"
        "from scar.trace.call_edges import install as frames\n"
        "from scar.trace.call_operands import install as operands\n"
        "recorder = frames(sys.argv[1], sys.argv[2])\n"
        "observer = operands(recorder, capture=sys.argv[3])\n"
        "sys.path.insert(0, sys.argv[2])\n"
        "runpy.run_path(sys.argv[2] + '/entry.py', run_name='__main__')\n"
    )
    command = ([sys.executable, "-m", "scar.cli", "trace", "--call-operands",
                "--operand-capture", capture, "--project-root", str(project), "--out", str(trace),
                "--", sys.executable, str(project / "entry.py")] if public_cli else
               [sys.executable, "-c", script, str(trace), str(project), capture])
    executed = subprocess.run(command,
                             cwd=repository, env=environment, capture_output=True, text=True, timeout=30)
    assert executed.returncode == 0, executed.stdout + executed.stderr


@pytest.fixture
def original_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "helper.py").write_text("def leaf(left, right):\n    return left\n")
    (project / "entry.py").write_text(
        "from helper import leaf\ndef run(x, y):\n    return leaf(x, y)\n"
        "shared = []\nassert run(shared, shared) is shared\n")
    return project, tmp_path / "trace"


def test_mixed_process_capture_rules_are_preserved_independently(original_project, monkeypatch):
    project, trace = original_project
    _capture(project, trace, "instructions", public_cli=True)
    _capture(project, trace, "windows")
    monkeypatch.setenv("SCAR_OPERAND_CAPTURE", "not-a-reader-default")

    observed = reader.read_call_operands(trace, project)

    assert {meta.rule for meta in observed.metadata} == OPERAND_CAPTURE_RULES
    assert len({meta.process_id for meta in observed.metadata}) == 2
    assert not observed.issues
    for meta in observed.metadata:
        events = [event for event in observed.events if event.process_id == meta.process_id]
        assert len(events) == meta.events
        assert {event.invocation.process_id for event in events if event.invocation} == {meta.process_id}
        assert any(handshake.process_id == meta.process_id for handshake in observed.handshakes)


def test_legacy_report_public_replay_uses_raw_rule_and_rejects_changed_rule(original_project, monkeypatch):
    project, trace = original_project
    _capture(project, trace, "instructions", public_cli=True)
    inventory = inventory_program(project / "entry.py", project_root=project, calls_trace=trace)
    report = link_call_operands(trace, project, inventory)
    document = report.to_dict()
    assert {meta["rule"] for meta in document["operand_metadata"]} == {LOAD_OCCURRENCES_RULE}
    assert document["routing"]["argument_routes"] and document["routing"]["completion_routes"]
    monkeypatch.setenv("SCAR_OPERAND_CAPTURE", "windows")

    replayed = CallOperandReport.from_dict(document, inventory=inventory)

    assert replayed.to_dict() == document
    assert not any(document[name] for name in (
        "whole_program_complete", "function_environment_established", "contents_or_effects_established",
        "world_equivalence_established", "transformation_authorized"))
    changed = deepcopy(document)
    changed["operand_metadata"][0]["rule"] = CALL_WINDOWS_RULE
    with pytest.raises(ValueError, match="raw/source/inventory replay"):
        CallOperandReport.from_dict(changed, inventory=inventory)
