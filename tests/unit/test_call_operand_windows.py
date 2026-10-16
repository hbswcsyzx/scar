"""Focused tests for sparse CPython call-window capture."""
from __future__ import annotations

import dis
from pathlib import Path
import sys
import threading
import types

from scar.analysis.call_operand_reader import read_call_operands
from scar.ir.program.call_operands import CALL_WINDOWS_RULE, LOAD_OCCURRENCES_RULE
from scar.trace.call_edges import install as install_frames
import scar.trace.call_operands as operand_module
from scar.trace.call_operands import CallOperandObserver, install as install_operands
from scar.trace.code_snapshot import describe_code
from scar.trace.operand_bytecode import call_window_selection, load_slots


def _module(root: Path, name: str, source: str):
    path = root / (name + ".py")
    path.write_text(source, encoding="utf-8")
    namespace = {"__name__": name, "__file__": str(path), "__builtins__": __builtins__}
    exec(compile(source, str(path), "exec", dont_inherit=True), namespace)
    return types.SimpleNamespace(path=path, namespace=namespace)


def _capture(root, output, callback, *, capture="windows", max_events=100_000):
    previous, previous_thread = sys.getprofile(), threading.getprofile()
    recorder = install_frames(output, root)
    installed_profile = sys.getprofile()
    observer = install_operands(recorder, capture=capture, max_events=max_events)
    instruction_callbacks = None
    try:
        result = callback()
        # Every sparse callback either emits one selected INSTRUCTION row or
        # returns DISABLE once for a previously unseen unselected code offset.
        instruction_callbacks = observer._instruction_count + sum(
            len(state["disabled_instruction_offsets"])
            for state in observer._code_states.values())
    finally:
        observer.stop()
        if sys.getprofile() is installed_profile:
            sys.setprofile(previous)
        if threading.getprofile() is installed_profile:
            threading.setprofile(previous_thread)
        recorder.close()
        observer.close()
    return result, read_call_operands(output, root), observer, instruction_callbacks


def test_selector_preserves_fused_operand_occurrences_and_expiry_sites(tmp_path):
    source = """\
def terminal(left, right):
    return left is right
def run(value):
    return terminal(value, value)
"""
    module = _module(tmp_path, "window_source", source)
    code = module.namespace["run"].__code__
    instructions = tuple(dis.get_instructions(code))
    windows, expiry = call_window_selection(code, instructions)
    calls = [item for item in instructions if item.opname.startswith("CALL")]
    expected_continuations = {
        instructions[index + 1].offset
        for index, item in enumerate(instructions[:-1])
        if item.opname.startswith("CALL")
    }
    assert expected_continuations <= expiry
    assert set(windows) == {item.offset for item in instructions if item.opname == "CALL"}
    call = next(item for item in calls if item.opname == "CALL")
    window = windows[call.offset]
    loads = [slot for offset in window for instruction in instructions if instruction.offset == offset
             for slot in (load_slots(code, instruction) or ())]
    assert [item[2] for item in loads] == ["terminal", "value", "value"]
    assert [item[0] for item in loads] == [0, 0, 1]

    # A jump may enter the window at its first instruction, but not halfway
    # through the name/argument sequence.
    first_offset = window[0]
    first_index = next(index for index, item in enumerate(instructions) if item.offset == first_offset)
    first_entry = list(instructions)
    first_entry[first_index] = first_entry[first_index]._replace(label="synthetic-target")
    assert call.offset in call_window_selection(code, first_entry)[0]
    interior_offset = window[1]
    interior_index = next(index for index, item in enumerate(instructions) if item.offset == interior_offset)
    interior_entry = list(instructions)
    interior_entry[interior_index] = interior_entry[interior_index]._replace(label="synthetic-target")
    assert call.offset not in call_window_selection(code, interior_entry)[0]


def test_selector_keeps_exception_handlers_as_expiry_callbacks(tmp_path):
    module = _module(tmp_path, "exception_window", """\
def target(value):
    return value
def run(value):
    try:
        return target(value)
    except TypeError:
        return None
""")
    code = module.namespace["run"].__code__
    instructions = tuple(dis.get_instructions(code))
    exception_targets = {entry.target for entry in dis.Bytecode(code).exception_entries}
    _windows, expiry = call_window_selection(code, instructions)
    assert exception_targets
    assert exception_targets <= expiry


def test_selector_does_not_claim_attribute_or_keyword_call_windows(tmp_path):
    module = _module(tmp_path, "unsupported_windows", """\
def run(value):
    return value.method(argument=value)
""")
    code = module.namespace["run"].__code__
    windows, _expiry = call_window_selection(code)
    assert not windows


def test_windows_capture_reduces_loop_callbacks_and_keeps_actual_calls(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    module = _module(root, "loop_entry", """\
def terminal(left, right):
    return left is right
def run(left, right, count):
    total = 0
    for index in range(count):
        total += index & 1
    return terminal(left, right), total
""")
    left, right = object(), object()
    dense_out, sparse_out = tmp_path / "dense", tmp_path / "sparse"
    result_dense, dense, _, dense_callbacks = _capture(
        root, dense_out, lambda: module.namespace["run"](left, right, 300),
        capture="instructions")
    result_sparse, sparse, _, sparse_callbacks = _capture(
        root, sparse_out, lambda: module.namespace["run"](left, right, 300),
        capture="windows")

    assert result_dense == result_sparse == (False, 150)
    assert {item.rule for item in dense.metadata} == {LOAD_OCCURRENCES_RULE}
    assert {item.rule for item in sparse.metadata} == {CALL_WINDOWS_RULE}
    assert sparse_callbacks * 10 < dense_callbacks
    assert len(sparse.events) * 10 < len(dense.events)
    assert not dense.issues and not sparse.issues
    assert not sparse.gaps
    assert any(event.kind.value == "CALL_ATTEMPT" for event in sparse.events)
    assert any(event.kind.value == "ENTRY_HANDSHAKE" for event in sparse.events)


def test_windows_mask_and_disabled_offsets_persist_between_calls_until_stop(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    module = _module(root, "persistent_window", """\
def terminal(value):
    return value
def run(value, count):
    for index in range(count):
        total = index + 1
    return terminal(value)
""")
    output = tmp_path / "trace"
    previous, previous_thread = sys.getprofile(), threading.getprofile()
    recorder = install_frames(output, root)
    installed_profile = sys.getprofile()
    observer = install_operands(recorder, capture="windows")
    code = module.namespace["run"].__code__
    monitoring = sys.monitoring
    tool_id = observer.tool_id
    try:
        assert module.namespace["run"](object(), 100) is not None
        state = observer._code_states[id(code)]
        disabled_after_first = frozenset(state["disabled_instruction_offsets"])
        assert disabled_after_first
        assert state["active"] == 0
        assert state["installed"] is True
        assert state["reference"]() is code
        assert monitoring.get_local_events(tool_id, code) == (
            monitoring.events.INSTRUCTION | monitoring.events.CALL)

        assert module.namespace["run"](object(), 100) is not None
        assert observer._code_states[id(code)] is state
        assert frozenset(state["disabled_instruction_offsets"]) == disabled_after_first
        assert monitoring.get_local_events(tool_id, code) == (
            monitoring.events.INSTRUCTION | monitoring.events.CALL)
    finally:
        observer.stop()
        if sys.getprofile() is installed_profile:
            sys.setprofile(previous)
        if threading.getprofile() is installed_profile:
            threading.setprofile(previous_thread)
        recorder.close()
        observer.close()
    assert monitoring.get_tool(tool_id) is None
    trace = read_call_operands(output, root)
    assert not trace.issues and not trace.gaps


def test_stop_flushes_pending_attempt_and_post_stop_callback_does_not_disable(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    module = _module(root, "pending_window", "def run(value):\n    return value\n")
    output = tmp_path / "trace"
    previous, previous_thread = sys.getprofile(), threading.getprofile()
    recorder = install_frames(output, root)
    installed_profile = sys.getprofile()
    observer = install_operands(recorder, capture="windows")
    try:
        marker = object()
        assert module.namespace["run"](marker) is marker
        owner = recorder.invocation
        observer._pending[(threading.get_ident(), owner)] = (None, None, None, None, None, 1)
        observer.stop()
        assert observer._disabled_callback_result(module.namespace["run"].__code__) is None
    finally:
        observer.stop()
        if sys.getprofile() is installed_profile:
            sys.setprofile(previous)
        if threading.getprofile() is installed_profile:
            threading.setprofile(previous_thread)
        recorder.close()
        observer.close()
    trace = read_call_operands(output, root)
    assert any(gap.reason == "PROJECT_FUNCTION_CALL_DID_NOT_ENTER" for gap in trace.gaps)
    assert not trace.handshakes


def test_disabled_callback_result_respects_foreign_monitoring_ownership(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    module = _module(root, "foreign_window", "def run(value):\n    return value\n")
    output = tmp_path / "trace"
    previous, previous_thread = sys.getprofile(), threading.getprofile()
    recorder = install_frames(output, root)
    installed_profile = sys.getprofile()
    observer = install_operands(recorder, capture="windows")
    monitoring = sys.monitoring
    owned_id = observer.tool_id
    foreign_name = "foreign-window-tool"
    try:
        assert module.namespace["run"](object()) is not None
        monitoring.free_tool_id(owned_id)
        monitoring.use_tool_id(owned_id, foreign_name)
        assert observer._disabled_callback_result(module.namespace["run"].__code__) is None
        observer.stop()
        assert monitoring.get_tool(owned_id) == foreign_name
    finally:
        if sys.getprofile() is installed_profile:
            sys.setprofile(previous)
        if threading.getprofile() is installed_profile:
            threading.setprofile(previous_thread)
        recorder.close()
        observer.close()
        if monitoring.get_tool(owned_id) == foreign_name:
            monitoring.free_tool_id(owned_id)


def test_unknown_monitor_offset_is_a_boundary_not_an_intentionally_skipped_site(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    module = _module(root, "unknown_offset", """\
def run(observer):
    observer._on_instruction(run.__code__, 1_000_000)
    return 17
""")
    output = tmp_path / "trace"
    previous, previous_thread = sys.getprofile(), threading.getprofile()
    recorder = install_frames(output, root)
    installed_profile = sys.getprofile()
    observer = install_operands(recorder, capture="windows")
    try:
        result = module.namespace["run"](observer)
    finally:
        observer.stop()
        if sys.getprofile() is installed_profile:
            sys.setprofile(previous)
        if threading.getprofile() is installed_profile:
            threading.setprofile(previous_thread)
        recorder.close()
        observer.close()
    trace = read_call_operands(output, root)
    assert result == 17
    assert any(gap.reason == "INSTRUCTION_NOT_IN_VERIFIED_CODE" for gap in trace.gaps)


def test_window_plan_stops_decoding_at_its_remaining_instruction_budget(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    module = _module(root, "large_window_plan", """\
def run(value):
    first = value + 1
    second = first + 1
    third = second + 1
    return third
""")
    output = tmp_path / "trace"
    previous, previous_thread = sys.getprofile(), threading.getprofile()
    recorder = install_frames(output, root)
    installed_profile = sys.getprofile()
    observer = install_operands(recorder, capture="windows", max_events=2)
    import dis
    original = dis.get_instructions
    consumed = []

    def counted(code):
        for instruction in original(code):
            consumed.append(instruction)
            yield instruction

    monkeypatch.setattr(dis, "get_instructions", counted)
    try:
        result = observer._window_plan(module.namespace["run"].__code__,
                                       describe_code(module.namespace["run"].__code__)["key"])
        assert result is None
        assert len(consumed) == 3
        assert observer._planned_instruction_count == 0
    finally:
        observer.stop()
        if sys.getprofile() is installed_profile:
            sys.setprofile(previous)
        if threading.getprofile() is installed_profile:
            threading.setprofile(previous_thread)
        recorder.close()
        observer.close()


def test_stop_preserves_a_tool_slot_after_foreign_callback_registration(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    module = _module(root, "foreign_callback_window", "def run(value):\n    return value\n")
    output = tmp_path / "trace"
    previous, previous_thread = sys.getprofile(), threading.getprofile()
    recorder = install_frames(output, root)
    installed_profile = sys.getprofile()
    observer = install_operands(recorder, capture="windows")
    monitoring = sys.monitoring
    tool_id = observer.tool_id
    code = module.namespace["run"].__code__
    try:
        assert module.namespace["run"](object()) is not None
        expected_mask = monitoring.events.INSTRUCTION | monitoring.events.CALL
        assert monitoring.get_local_events(tool_id, code) == expected_mask

        def foreign_callback(*_args):
            return None

        # The profile wrapper sees this public mutation. Even if the local
        # mask still equals ours, stop must leave the changed tool slot alone.
        monitoring.register_callback(tool_id, monitoring.events.INSTRUCTION, foreign_callback)
        assert observer._monitoring_interfered
        assert observer._disabled_callback_result(code) is None
        observer.stop()
        assert monitoring.get_tool(tool_id) == observer.tool_name
        assert monitoring.get_local_events(tool_id, code) == expected_mask
    finally:
        if sys.getprofile() is installed_profile:
            sys.setprofile(previous)
        if threading.getprofile() is installed_profile:
            threading.setprofile(previous_thread)
        recorder.close()
        observer.close()
        if monitoring.get_tool(tool_id) == observer.tool_name:
            # Cleanup test-owned monitoring state after asserting preservation.
            try:
                monitoring.set_local_events(tool_id, code, 0)
                monitoring.free_tool_id(tool_id)
            except BaseException:
                pass


def test_after_fork_leaves_every_monitor_mask_untouched_if_one_is_foreign(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    module = _module(root, "foreign_fork_mask", "def run(value):\n    return value\n")
    output = tmp_path / "trace"
    previous, previous_thread = sys.getprofile(), threading.getprofile()
    recorder = install_frames(output, root)
    installed_profile = sys.getprofile()
    observer = install_operands(recorder, capture="windows")
    monitoring = sys.monitoring
    tool_id = observer.tool_id
    code = module.namespace["run"].__code__
    foreign_mask = monitoring.events.LINE
    try:
        assert module.namespace["run"](object()) is not None
        assert monitoring.get_local_events(tool_id, code) == (
            monitoring.events.INSTRUCTION | monitoring.events.CALL)

        # Simulate a mask change that the observer could not see before the
        # fork callback.  after_fork must preflight all installed masks before
        # changing any of them or freeing the tool slot.
        monitoring.set_local_events(tool_id, code, foreign_mask)
        observer._monitoring_interfered = False
        observer._interfered = False
        monkeypatch.setattr(operand_module.os, "getpid", lambda: observer.pid + 1)
        observer.after_fork()
        monkeypatch.undo()

        assert monitoring.get_tool(tool_id) == observer.tool_name
        assert monitoring.get_local_events(tool_id, code) == foreign_mask
    finally:
        monkeypatch.undo()
        if sys.getprofile() is installed_profile:
            sys.setprofile(previous)
        if threading.getprofile() is installed_profile:
            threading.setprofile(previous_thread)
        if monitoring.get_tool(tool_id) == observer.tool_name:
            try:
                monitoring.set_local_events(tool_id, code, 0)
                monitoring.free_tool_id(tool_id)
            except BaseException:
                pass
        recorder.close()
        observer.close()


def test_stop_does_not_free_the_tool_after_a_local_mask_mismatch(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    module = _module(root, "foreign_stop_mask", "def run(value):\n    return value\n")
    output = tmp_path / "trace"
    previous, previous_thread = sys.getprofile(), threading.getprofile()
    recorder = install_frames(output, root)
    installed_profile = sys.getprofile()
    observer = install_operands(recorder, capture="windows")
    monitoring = sys.monitoring
    tool_id = observer.tool_id
    code = module.namespace["run"].__code__
    foreign_mask = monitoring.events.LINE
    try:
        assert module.namespace["run"](object()) is not None
        monitoring.set_local_events(tool_id, code, foreign_mask)
        # Exercise the stop-time check when an earlier hook did not report
        # this mutation.
        observer._monitoring_interfered = False
        observer._interfered = False
        observer.stop()
        assert observer._monitoring_interfered
        assert monitoring.get_tool(tool_id) == observer.tool_name
        assert monitoring.get_local_events(tool_id, code) == foreign_mask
    finally:
        if sys.getprofile() is installed_profile:
            sys.setprofile(previous)
        if threading.getprofile() is installed_profile:
            threading.setprofile(previous_thread)
        if monitoring.get_tool(tool_id) == observer.tool_name:
            try:
                monitoring.set_local_events(tool_id, code, 0)
                monitoring.free_tool_id(tool_id)
            except BaseException:
                pass
        recorder.close()
        observer.close()


def test_disabled_offset_bookkeeping_has_an_aggregate_budget(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    module = _module(root, "disabled_offset_budget", """\
def run(value):
    first = value + 1
    second = first + 1
    return second
""")
    output = tmp_path / "trace"
    previous, previous_thread = sys.getprofile(), threading.getprofile()
    recorder = install_frames(output, root)
    installed_profile = sys.getprofile()
    observer = install_operands(recorder, capture="windows", max_events=100)
    observer._disabled_instruction_count = observer.limits.max_events
    try:
        assert module.namespace["run"](1) == 3
        assert observer._disabled_instruction_count == observer.limits.max_events
    finally:
        observer.stop()
        if sys.getprofile() is installed_profile:
            sys.setprofile(previous)
        if threading.getprofile() is installed_profile:
            threading.setprofile(previous_thread)
        recorder.close()
        observer.close()
    trace = read_call_operands(output, root)
    assert any(gap.reason == "CALL_WINDOW_DISABLED_OFFSET_BUDGET_EXCEEDED"
               for gap in trace.gaps)
