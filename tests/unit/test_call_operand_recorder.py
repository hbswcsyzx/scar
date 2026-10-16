"""Focused runtime checks for metadata-only call operand collection."""
from __future__ import annotations

import dis
import importlib.util
import json
from pathlib import Path
import sys
import threading
import types

import pytest

from scar.analysis.call_operand_reader import read_call_operands
from scar.ir.program.call_operands import CallableKind
from scar.trace.call_edges import install as install_frames
from scar.trace.call_operands import install as install_operands
from scar.trace.code_snapshot import describe_code
from scar.trace.operand_bytecode import load_slots


@pytest.fixture
def capture(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    output = tmp_path / "trace"
    output.mkdir()
    yield root, output


def _module(root, name, source):
    path = root / (name + ".py")
    path.write_text(source, encoding="utf-8")
    namespace = {"__name__": name, "__file__": str(path), "__builtins__": __builtins__}
    exec(compile(source, str(path), "exec", dont_inherit=True), namespace)
    return types.SimpleNamespace(path=path, namespace=namespace)


def _record(root, output, run, *, observer_options=None, observer_configure=None):
    old_profile, old_thread_profile = sys.getprofile(), threading.getprofile()
    recorder = install_frames(output, root)
    installed_profile = sys.getprofile()
    observer = install_operands(recorder, **(observer_options or {}))
    if observer_configure is not None:
        observer_configure(observer)
    try:
        result = run()
    finally:
        observer.stop()
        if sys.getprofile() is installed_profile:
            sys.setprofile(old_profile)
        if threading.getprofile() is installed_profile:
            threading.setprofile(old_thread_profile)
        recorder.close()
        observer.close()
    return result, read_call_operands(output, root)


def test_real_calls_preserve_duplicate_load_occurrences_and_direct_entries(capture):
    root, output = capture
    module = _module(root, "entry", """
def terminal(left, right):
    return left is right
def relay(a, b):
    return terminal(a, b)
def relay_same(x):
    return terminal(x, x)
def run(x, y):
    return relay(x, y), relay_same(x), terminal(x, y)
""")
    left, right = object(), object()
    result, trace = _record(root, output, lambda: module.namespace["run"](left, right))
    assert result == (False, True, False)

    terminal_key = describe_code(module.namespace["terminal"].__code__)["key"]
    terminal_instructions = [
        event for event in trace.instructions
        if event.site.code == terminal_key and len(event.loads) == 2
    ]
    assert terminal_instructions
    pairs = [(event.loads[0].reference, event.loads[1].reference) for event in terminal_instructions]
    assert any(left_ref == right_ref for left_ref, right_ref in pairs)
    assert any(left_ref != right_ref for left_ref, right_ref in pairs)
    assert len(trace.handshakes) >= 4
    assert not trace.issues

    raw = json.loads((output / f"call-operand-meta.{trace.metadata[0].process_id}.json").read_text())
    assert raw["events"] == len(trace.events)
    assert raw["errors"] == [] and raw["dropped_events"] == 0
    assert raw["previous_profile"] is False


def test_no_argument_sentinel_differs_from_explicit_none_and_methods_stay_methods(capture):
    root, output = capture
    module = _module(root, "calls", """
class Box:
    def target(self, value):
        return value
def zero():
    return 10
def one(value):
    return value
def run(box):
    direct = box.target(None)
    method = box.target
    return zero(), one(None), direct, method(None)
""")
    result, trace = _record(root, output, lambda: module.namespace["run"](module.namespace["Box"]()))
    assert result == (10, None, None, None)
    target_codes = {
        describe_code(module.namespace["zero"].__code__)["key"],
        describe_code(module.namespace["one"].__code__)["key"],
    }
    attempts = [event for event in trace.attempts
                if event.dispatch.kind is CallableKind.EXACT_FUNCTION and event.dispatch.code in target_codes]
    assert any(event.arg0_missing and event.arg0 is None for event in attempts)
    assert any(not event.arg0_missing and event.arg0 is not None for event in attempts)
    # CPython's LOAD_ATTR method optimization supplies the underlying function
    # plus receiver at CALL; the raw observed object remains a FunctionType.
    assert any(event.dispatch.kind is CallableKind.EXACT_FUNCTION
               and event.arg0 is not None and not event.arg0_missing for event in trace.attempts)
    # The local read of a previously bound value remains MethodType even when
    # CPython normalizes the later CALL callback to a function plus receiver.
    assert any(load.callable_shape.kind is CallableKind.EXACT_METHOD
               for event in trace.instructions for load in event.loads)


def test_namespace_scan_limit_is_an_explicit_gap_and_target_still_runs(capture):
    root, output = capture
    module = _module(root, "bounded_names", """
padding0 = object()
padding1 = object()
def target(value):
    return value
def run(value):
    return target(value)
""")
    marker = object()
    result, trace = _record(
        root, output, lambda: module.namespace["run"](marker),
        observer_options={"max_namespace_items": 1},
    )
    assert result is marker
    assert any("GLOBAL_NAMESPACE_LOOKUP_LIMIT" in event.reason for event in trace.gaps)


def test_global_scan_rejects_custom_keys_without_calling_their_protocol(capture):
    root, output = capture
    module = _module(root, "hostile_keys", """
def target(value):
    return value
def run(value):
    return target(value)
""")

    class HostileKey:
        def __init__(self):
            self.hash_calls = self.eq_calls = 0

        def __hash__(self):
            self.hash_calls += 1
            return 7

        def __eq__(self, other):
            self.eq_calls += 1
            return False

    key = HostileKey()
    module.namespace[key] = object()
    key.hash_calls = key.eq_calls = 0
    marker = object()
    result, trace = _record(root, output, lambda: module.namespace["run"](marker))
    assert result is marker
    assert key.hash_calls == key.eq_calls == 0
    assert any("GLOBAL_NAMESPACE_HAS_NONSTRING_KEY" in event.reason for event in trace.gaps)


def test_global_scan_detects_namespace_mutation_between_bounded_passes(capture):
    root, output = capture
    module = _module(root, "changing_globals", """
def target(value):
    return value
def run(value):
    return target(value)
""")
    changed = False

    def configure(observer):
        original = observer._namespace_pass

        def mutate_after_first(mapping, name):
            nonlocal changed
            result = original(mapping, name)
            if mapping is module.namespace and not changed:
                changed = True
                mapping["concurrent_change"] = object()
            return result

        observer._namespace_pass = mutate_after_first

    marker = object()
    result, trace = _record(root, output, lambda: module.namespace["run"](marker),
                            observer_configure=configure)
    assert result is marker and changed
    assert any("GLOBAL_NAMESPACE_MUTATED_DURING_LOOKUP" in event.reason for event in trace.gaps)


def test_normal_shutdown_releases_only_the_tool_id_claimed_by_this_observer(capture):
    root, output = capture
    module = _module(root, "shutdown", "def run(value):\n    return value\n")
    monitoring = sys.monitoring
    foreign_id = next(tool_id for tool_id in range(6) if monitoring.get_tool(tool_id) is None)
    foreign_name = "test-foreign-call-operand-tool"
    monitoring.use_tool_id(foreign_id, foreign_name)
    owner = {}

    def remember_tool(observer):
        owner["id"] = observer.tool_id
        owner["name"] = observer.tool_name

    try:
        result, _trace = _record(root, output, lambda: module.namespace["run"](object()),
                                 observer_configure=remember_tool)
        assert result is not None
        assert owner["id"] != foreign_id
        assert monitoring.get_tool(foreign_id) == foreign_name
        assert monitoring.get_tool(owner["id"]) is None
    finally:
        if monitoring.get_tool(foreign_id) == foreign_name:
            monitoring.free_tool_id(foreign_id)


def test_visible_monitoring_mutation_stops_capture_without_overwriting_it(capture):
    root, output = capture
    module = _module(root, "mutate_monitor", """
import sys
def run():
    sys.monitoring.set_events(tool_id, sys.monitoring.events.INSTRUCTION)
    return 17
""")
    tool = {}

    def remember_tool(observer):
        tool["id"] = observer.tool_id
        tool["name"] = observer.tool_name
        module.namespace["tool_id"] = observer.tool_id

    result, trace = _record(root, output, lambda: module.namespace["run"](),
                            observer_configure=remember_tool)
    assert result == 17
    assert any(event.reason == "VISIBLE_HOOK_OR_MONITORING_MUTATION" for event in trace.gaps)
    assert sys.monitoring.get_tool(tool["id"]) == tool["name"]
    assert sys.monitoring.get_events(tool["id"]) == sys.monitoring.events.INSTRUCTION
    # The target changed this tool's mask. Cleanup for the fixture restores
    # its own state after confirming the observer did not overwrite it.
    sys.monitoring.set_events(tool["id"], 0)
    assert sys.monitoring.get_local_events(tool["id"], module.namespace["run"].__code__) != 0
    sys.monitoring.set_local_events(tool["id"], module.namespace["run"].__code__, 0)
    sys.monitoring.free_tool_id(tool["id"])


def test_plan_cache_is_shared_by_code_clones_and_bounded_by_event_budget(capture):
    root, output = capture
    module = _module(root, "cloned_code", """
def body(value):
    return value is value
def run(value):
    return first(value), second(value)
""")
    namespace = module.namespace
    code = namespace["body"].__code__
    namespace["first"] = types.FunctionType(code, namespace)
    namespace["second"] = types.FunctionType(code.replace(), namespace)
    observer_state = {}

    result, trace = _record(
        root, output, lambda: namespace["run"](object()),
        observer_configure=lambda observer: observer_state.update(observer=observer),
    )
    assert result == (True, True)
    observer = observer_state["observer"]
    body_key = describe_code(code)["key"]
    assert len(observer._plans) == 2  # body clone pair share one fingerprint entry; run owns the other
    assert body_key in observer._plans
    assert observer._planned_instruction_count == (
        len(tuple(dis.get_instructions(code)))
        + len(tuple(dis.get_instructions(namespace["run"].__code__)))
    )
    assert not trace.issues

    root2 = capture[0] / "small"
    root2.mkdir()
    output2 = capture[1] / "small"
    output2.mkdir()
    huge = _module(root2, "too_large", """
def run(value):
    return value is value
""")
    limited = {}
    result, limited_trace = _record(
        root2, output2, lambda: huge.namespace["run"](object()),
        observer_options={"max_events": 2},
        observer_configure=lambda observer: limited.update(observer=observer),
    )
    assert result is True
    assert limited["observer"]._planned_instruction_count == 0
    assert any("OPCODE_PLAN_INSTRUCTION_BUDGET_EXCEEDED" in event.reason
               for event in limited_trace.gaps)


def test_versioned_load_decoder_keeps_fused_order_and_rejects_unknown_fusions(capture):
    root, _ = capture
    module = _module(root, "bytecode", "def f(left, right):\n    return callee(left, right)\n")
    code = module.namespace["f"].__code__
    instructions = tuple(dis.get_instructions(code))
    dual = next((item for item in instructions
                 if item.opname == "LOAD_FAST_BORROW_LOAD_FAST_BORROW"), None)
    assert dual is not None
    assert load_slots(code, dual) == (
        (0, "FAST_LOCAL", "left", code.co_varnames.index("left")),
        (1, "FAST_LOCAL", "right", code.co_varnames.index("right")),
    )
    global_load = next(item for item in instructions if item.opname == "LOAD_GLOBAL")
    assert load_slots(code, global_load) == ((0, "GLOBAL", "callee", None),)
    ret = next(item for item in instructions if item.opname == "RETURN_VALUE")
    assert load_slots(code, ret) == ()

    fake = dis.Instruction(
        opname="LOAD_FAST_LOAD_FAST", opcode=0, arg=1, argval=("left", "right"),
        argrepr="left, right", offset=0, start_offset=0, starts_line=None,
        line_number=None, label=None, positions=None, cache_info=None,
    )
    assert load_slots(code, fake) is None
