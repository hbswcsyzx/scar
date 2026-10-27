"""Independent stdlib-only witnesses for synchronous Python finally semantics.

No SCAR import or model is used as an oracle. Assertions encode the expected
language behavior; actual traces and all failures are saved before exit.
"""
from __future__ import annotations

import copy
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path


CASES = []


def case(function):
    CASES.append(function)
    return function


def identity(value):
    return {"id": id(value), "type": type(value).__qualname__, "repr": repr(value)}


def record(events, event, **fields):
    # Snapshot only small local scalar/container evidence, never live objects.
    events.append({"event": event, **copy.deepcopy(fields)})


def names(events):
    return [event["event"] for event in events]


@case
def return_expression_before_finally_rebind(events, result):
    original = {"value": "original"}
    rebound = {"value": "rebound"}

    def payload(value):
        record(events, "return_expression", payload=identity(value))
        return value

    def function():
        binding = original
        try:
            return payload(binding)
        finally:
            record(events, "finally_enter", binding=identity(binding))
            binding = rebound
            record(events, "finally_rebind", binding=identity(binding))

    returned = function()
    record(events, "caller_return", returned=identity(returned))
    result.update(returned_is_original=returned is original, returned_is_rebound=returned is rebound)
    assert names(events) == ["return_expression", "finally_enter", "finally_rebind", "caller_return"]
    assert returned is original and returned is not rebound


@case
def finally_mutates_returned_object(events, result):
    payload = ["before"]

    def function():
        try:
            record(events, "return_expression", payload=identity(payload), contents=payload)
            return payload
        finally:
            payload.append("finally")
            record(events, "finally_write", payload=identity(payload), contents=payload)

    returned = function()
    record(events, "caller_return", returned=identity(returned), contents=returned)
    result.update(returned_is_payload=returned is payload, contents=returned.copy())
    assert returned is payload and returned == ["before", "finally"]
    assert events[0]["contents"] == ["before"]
    assert names(events) == ["return_expression", "finally_write", "caller_return"]


@case
def normal_finally_preserves_return_with_poststate(events, result):
    payload = object()
    state = {"version": 0}

    def function():
        try:
            record(events, "return_expression", payload=identity(payload), state=state)
            return payload
        finally:
            state["version"] += 1
            record(events, "finally_normal", state=state, active_exception=identity(sys.exception()))

    returned = function()
    record(events, "caller_return", returned=identity(returned), state=state)
    result.update(returned_is_payload=returned is payload, poststate=state.copy())
    assert returned is payload and state == {"version": 1}
    assert events[0]["state"] == {"version": 0}
    assert events[1]["active_exception"]["id"] == id(None)


@case
def normal_finally_preserves_raise_with_poststate(events, result):
    original = ValueError("original")
    state = {"version": 0}

    def function():
        try:
            record(events, "raise_original", exception=identity(original), state=state)
            raise original
        finally:
            assert sys.exception() is original
            state["version"] += 1
            record(events, "finally_normal", active_exception=identity(sys.exception()), state=state)

    try:
        function()
    except ValueError as caught:
        record(events, "caller_raise", exception=identity(caught), context=identity(caught.__context__), state=state)
        result.update(caught_is_original=caught is original, context_is_none=caught.__context__ is None,
                      poststate=state.copy())
        assert caught is original and caught.__context__ is None
    else:
        raise AssertionError("original exception did not propagate")
    assert state == {"version": 1}
    assert names(events) == ["raise_original", "finally_normal", "caller_raise"]


def check_override(events, result, pending, cleanup):
    old_payload, new_payload = object(), object()
    old_exception, new_exception = ValueError("old"), RuntimeError("new")
    state = {"version": 0}

    def function():
        try:
            record(events, "pending_" + pending,
                   payload=identity(old_payload if pending == "return" else old_exception), state=state)
            if pending == "return":
                return old_payload
            raise old_exception
        finally:
            active = sys.exception()
            assert active is (old_exception if pending == "raise" else None)
            state["version"] += 1
            record(events, "finally_" + cleanup,
                   payload=identity(new_payload if cleanup == "return" else new_exception),
                   active_exception=identity(active), state=state)
            if cleanup == "return":
                return new_payload
            raise new_exception

    if cleanup == "return":
        returned = function()
        record(events, "caller_return", returned=identity(returned), state=state)
        result.update(returned_is_new=returned is new_payload, poststate=state.copy())
        assert returned is new_payload
    else:
        try:
            function()
        except RuntimeError as caught:
            expected_context = old_exception if pending == "raise" else None
            record(events, "caller_raise", exception=identity(caught),
                   context=identity(caught.__context__), cause=identity(caught.__cause__), state=state)
            result.update(caught_is_new=caught is new_exception,
                          expected_context_identity=caught.__context__ is expected_context,
                          context_is_original=caught.__context__ is old_exception,
                          context_is_none=caught.__context__ is None, poststate=state.copy())
            assert caught is new_exception and caught.__context__ is expected_context
            assert caught.__cause__ is None and not caught.__suppress_context__
        else:
            raise AssertionError("finally exception did not propagate")
    assert state == {"version": 1}
    assert names(events) == ["pending_" + pending, "finally_" + cleanup,
                             "caller_return" if cleanup == "return" else "caller_raise"]


@case
def finally_return_overrides_return(events, result):
    check_override(events, result, "return", "return")


@case
def finally_raise_overrides_return(events, result):
    check_override(events, result, "return", "raise")


@case
def finally_return_overrides_raise(events, result):
    check_override(events, result, "raise", "return")


@case
def finally_raise_overrides_raise_and_chains_context(events, result):
    check_override(events, result, "raise", "raise")


@case
def finally_break_overrides_return_targets_inner_loop(events, result):
    visited, after_inner = [], []

    def function():
        for outer in range(2):
            for inner in range(2):
                try:
                    visited.append([outer, inner])
                    record(events, "return_expression", outer=outer, inner=inner)
                    return (outer, inner)
                finally:
                    record(events, "finally_break_inner", outer=outer, inner=inner)
                    break
            after_inner.append(outer)
            record(events, "after_inner_loop", outer=outer)
        return "tail"

    returned = function()
    result.update(returned=returned, visited=visited, after_inner=after_inner)
    assert returned == "tail" and visited == [[0, 0], [1, 0]] and after_inner == [0, 1]


@case
def finally_continue_overrides_return_targets_inner_loop(events, result):
    visited, after_inner = [], []

    def function():
        for outer in range(2):
            for inner in range(2):
                try:
                    visited.append([outer, inner])
                    record(events, "return_expression", outer=outer, inner=inner)
                    return (outer, inner)
                finally:
                    record(events, "finally_continue_inner", outer=outer, inner=inner)
                    continue
            after_inner.append(outer)
            record(events, "after_inner_loop", outer=outer)
        return "tail"

    returned = function()
    result.update(returned=returned, visited=visited, after_inner=after_inner)
    assert returned == "tail" and visited == [[0, 0], [0, 1], [1, 0], [1, 1]]
    assert after_inner == [0, 1]


@case
def finally_continue_overrides_pending_break(events, result):
    visited = []
    for index in range(3):
        try:
            visited.append(index)
            record(events, "pending_break", index=index)
            break
        finally:
            if index == 0:
                record(events, "finally_continue", index=index)
                continue
            record(events, "finally_normal", index=index)
    record(events, "after_loop", index=index)
    result.update(visited=visited, final_index=index)
    assert visited == [0, 1] and index == 1


@case
def finally_break_overrides_pending_continue(events, result):
    visited = []
    for index in range(3):
        try:
            visited.append(index)
            record(events, "pending_continue", index=index)
            continue
        finally:
            record(events, "finally_break", index=index)
            break
    record(events, "after_loop", index=index)
    result.update(visited=visited, final_index=index)
    assert visited == [0] and index == 0


@case
def nested_finally_runs_inner_then_outer_preserving_payload(events, result):
    payload = object()
    state = []

    def function():
        try:
            try:
                record(events, "return_expression", payload=identity(payload), state=state)
                return payload
            finally:
                state.append("inner")
                record(events, "inner_finally", state=state)
        finally:
            state.append("outer")
            record(events, "outer_finally", state=state)

    returned = function()
    record(events, "caller_return", returned=identity(returned), state=state)
    result.update(returned_is_payload=returned is payload, poststate=state.copy())
    assert returned is payload and state == ["inner", "outer"]
    assert names(events) == ["return_expression", "inner_finally", "outer_finally", "caller_return"]


@case
def bare_raise_in_finally_reraises_pending_exception(events, result):
    original = ValueError("original")

    def function():
        try:
            record(events, "raise_original", exception=identity(original))
            raise original
        finally:
            record(events, "finally_bare_raise", active_exception=identity(sys.exception()))
            assert sys.exception() is original
            raise

    try:
        function()
    except ValueError as caught:
        record(events, "caller_raise", exception=identity(caught), context=identity(caught.__context__))
        result.update(caught_is_original=caught is original, context_is_none=caught.__context__ is None)
        assert caught is original and caught.__context__ is None
    else:
        raise AssertionError("bare raise failed to propagate original")


@case
def bare_raise_without_active_exception_overrides_pending_return(events, result):
    payload = object()

    def function():
        try:
            record(events, "pending_return", payload=identity(payload))
            return payload
        finally:
            assert sys.exception() is None
            record(events, "finally_bare_raise", active_exception=identity(sys.exception()))
            raise

    try:
        function()
    except RuntimeError as caught:
        record(events, "caller_raise", exception=identity(caught), context=identity(caught.__context__))
        result.update(exception_type=type(caught).__name__, message=str(caught),
                      context_is_none=caught.__context__ is None)
        assert str(caught) == "No active exception to reraise" and caught.__context__ is None
    else:
        raise AssertionError("bare raise without active exception should fail")


@case
def bare_raise_uses_ambient_handler_context_despite_pending_return(events, result):
    ambient = ValueError("ambient")
    payload = object()

    def function():
        try:
            raise ambient
        except ValueError:
            record(events, "ambient_handler", active_exception=identity(sys.exception()))
            try:
                record(events, "pending_return", payload=identity(payload))
                return payload
            finally:
                record(events, "finally_bare_raise", active_exception=identity(sys.exception()))
                assert sys.exception() is ambient
                raise

    try:
        function()
    except ValueError as caught:
        record(events, "caller_raise", exception=identity(caught), context=identity(caught.__context__))
        result.update(caught_is_ambient=caught is ambient, context_is_none=caught.__context__ is None)
        assert caught is ambient and caught.__context__ is None
    else:
        raise AssertionError("ambient exception was not reraised")


@case
def caught_exception_inside_finally_restores_pending_exception_context(events, result):
    original, temporary = ValueError("pending"), KeyError("temporary")

    def function():
        try:
            raise original
        finally:
            record(events, "finally_enter", active_exception=identity(sys.exception()))
            try:
                raise temporary
            except KeyError as caught:
                record(events, "cleanup_handler", active_exception=identity(sys.exception()),
                       context=identity(caught.__context__))
                assert sys.exception() is temporary and caught.__context__ is original
            record(events, "cleanup_handler_exit", active_exception=identity(sys.exception()))
            assert sys.exception() is original

    try:
        function()
    except ValueError as caught:
        record(events, "caller_raise", exception=identity(caught), context=identity(caught.__context__))
        result.update(caught_is_original=caught is original,
                      temporary_context_is_original=temporary.__context__ is original)
        assert caught is original and caught.__context__ is None
    else:
        raise AssertionError("pending exception was lost after cleanup's handler")


def check_finally_call_failure(events, result, pending):
    original, cleanup_exception = ValueError("pending"), LookupError("cleanup call")
    payload, state = object(), {"version": 0}

    def cleanup():
        record(events, "callee_enter", state=state, active_exception=identity(sys.exception()))
        state["version"] += 1
        record(events, "callee_write_then_raise", state=state, exception=identity(cleanup_exception))
        raise cleanup_exception

    def function():
        try:
            record(events, "pending_" + pending,
                   payload=identity(payload if pending == "return" else original), state=state)
            if pending == "return":
                return payload
            raise original
        finally:
            record(events, "finally_before_call", state=state)
            cleanup()
            record(events, "unreachable_after_call")

    try:
        function()
    except LookupError as caught:
        record(events, "caller_raise", exception=identity(caught),
               context=identity(caught.__context__), state=state)
        expected = original if pending == "raise" else None
        result.update(caught_is_cleanup_exception=caught is cleanup_exception,
                      expected_context_identity=caught.__context__ is expected, poststate=state.copy())
        assert caught is cleanup_exception and caught.__context__ is expected
    else:
        raise AssertionError("exception from finally call was lost")
    assert state == {"version": 1}
    assert "unreachable_after_call" not in names(events)


@case
def finally_call_exception_overrides_return_with_partial_state(events, result):
    check_finally_call_failure(events, result, "return")


@case
def finally_call_exception_overrides_raise_with_partial_state(events, result):
    check_finally_call_failure(events, result, "raise")


def main():
    cases = []
    for function in CASES:
        entry = {"case": function.__name__, "events": [], "observed": {}}
        try:
            function(entry["events"], entry["observed"])
        except BaseException as error:
            entry.update(status="FAIL", failure=identity(error))
        else:
            entry["status"] = "PASS"
        cases.append(entry)
    source = Path(__file__)
    run = {
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "implementation": platform.python_implementation(),
        "executable": sys.executable,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "stdlib_only": True,
        "scar_imported": any(name == "scar" or name.startswith("scar.") for name in sys.modules),
        "cases": cases,
        "passed": sum(case["status"] == "PASS" for case in cases),
        "failed": sum(case["status"] == "FAIL" for case in cases),
    }
    destination = source.with_name("results.json")
    history = json.loads(destination.read_text()) if destination.exists() else {"runs": []}
    history["runs"].append(run)
    destination.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: run[key] for key in ("python", "passed", "failed", "scar_imported")}))
    if run["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
