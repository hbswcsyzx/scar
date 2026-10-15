"""Small standard-Python probes only; not a collector or product implementation."""
import functools
import json
import sys
import types
import weakref
from pathlib import Path


def closure_pair(value):
    cell_value = value

    def get():
        return cell_value

    def put(value):
        nonlocal cell_value
        cell_value = value

    return get, put


def alternate_closure(value):
    differently_named = value

    def get():
        return differently_named

    return get


def inspect_cells():
    first, setter = closure_pair(object())
    second, _ = closure_pair(object())
    cell = first.__closure__[0]
    try:
        weakref.ref(cell)
    except TypeError:
        cell_weakrefable = False
    else:
        cell_weakrefable = True
    clone = types.FunctionType(first.__code__, first.__globals__, closure=(cell,))
    old_code = first.__code__
    alternate = alternate_closure(None)
    old_names = first.__code__.co_freevars
    first.__code__ = alternate.__code__
    result = {
        "cell_weakrefable": cell_weakrefable,
        "function_weakrefable": weakref.ref(first)() is first,
        "same_code_different_cells": old_code is second.__code__ and cell is not second.__closure__[0],
        "get_set_share_cell": cell is setter.__closure__[0],
        "clone_same_cell": clone.__closure__[0] is cell,
        "same_owner_code_changed_cell_unchanged": first.__code__ is not old_code and first.__closure__[0] is cell,
        "before_freevars": old_names,
        "after_freevars": first.__code__.co_freevars,
    }
    first.__code__ = old_code
    replacement = object()
    setter(replacement)
    result["setter_updates_shared_content"] = first() is clone() is replacement
    external = object()
    cell.cell_contents = external
    result["external_cell_assignment_visible"] = first() is clone() is external
    del cell.cell_contents
    try:
        first()
    except NameError:
        result["empty_cell_read_raises_nameerror"] = True
    try:
        first.__closure__ = second.__closure__
    except AttributeError:
        result["function_closure_readonly"] = True
    return result


def inspect_defaults_globals():
    old, new = object(), object()

    def function(a, b=old, *, k=old):
        return a, b, k

    function.__defaults__ = (new,)
    function.__kwdefaults__["k"] = new
    result = {"rewritten_defaults_are_used": function(old) == (old, new, new)}
    function.__defaults__ = None
    try:
        function(old)
    except TypeError:
        result["cleared_default_changes_call_compatibility"] = True
    namespace = {}
    exec("def read():\n    return marker\n", namespace)
    code = namespace["read"].__code__
    left = types.FunctionType(code, {"marker": "left"})
    right = types.FunctionType(code, {"marker": "right"})
    result["same_code_different_globals_results"] = [left(), right()]
    cached = {"__builtins__": {"len": lambda value: "original builtins"}}
    exec("def read_builtin():\n    return len(())\n", cached)
    builtin_reader = cached["read_builtin"]
    cached["__builtins__"] = {"len": lambda value: "replaced globals entry"}
    result["function_retains_builtins_mapping"] = builtin_reader() == "original builtins"
    return result


def inspect_monitoring():
    if not hasattr(sys, "monitoring"):
        return {"available": False}
    events = []
    first, second = object(), object()

    def target(x, y=None):
        return x

    class Owner:
        def method(self, x):
            return x

    owner = Owner()
    bound = owner.method
    partial = functools.partial(target, first)

    def driver(function, x, y, bound, owner, partial):
        function(x, y=y)
        bound(x)
        owner.method(x)
        partial(y)

    def called(code, offset, function, arg0):
        kind = type(function)
        name = function.__name__ if kind in (types.FunctionType, types.MethodType) else kind.__name__
        events.append({"event": "CALL", "caller": code.co_name, "offset": offset,
                       "callable_type": kind.__name__, "callable_name": name,
                       "arg0_is_first": arg0 is first, "arg0_is_receiver": arg0 is owner,
                       "callback_parent": sys._getframe(1).f_code.co_name})

    def started(code, offset):
        events.append({"event": "PY_START", "code": code.co_name})

    monitoring = sys.monitoring
    tool = next(i for i in range(6) if monitoring.get_tool(i) is None)
    monitoring.use_tool_id(tool, "scar-c1-environment-audit")
    try:
        monitoring.register_callback(tool, monitoring.events.CALL, called)
        monitoring.register_callback(tool, monitoring.events.PY_START, started)
        monitoring.set_local_events(tool, driver.__code__, monitoring.events.CALL)
        monitoring.set_local_events(tool, target.__code__, monitoring.events.PY_START)
        monitoring.set_local_events(tool, Owner.method.__code__, monitoring.events.PY_START)
        driver(target, first, second, bound, owner, partial)
    finally:
        monitoring.set_events(tool, 0)
        for code in (driver.__code__, target.__code__, Owner.method.__code__):
            monitoring.set_local_events(tool, code, 0)
        monitoring.register_callback(tool, monitoring.events.CALL, None)
        monitoring.register_callback(tool, monitoring.events.PY_START, None)
        monitoring.free_tool_id(tool)
    return {"available": True, "events": events}


def inspect_failure_stages():
    starts, effects = [], []

    def body(x):
        effects.append("body effect")
        raise RuntimeError("body failure")

    class BrokenExpansion:
        def __iter__(self):
            effects.append("expansion effect")
            raise RuntimeError("expansion failure")

    async def coroutine(x):
        effects.append("async body")
        return x

    def profile(frame, event, arg):
        if event == "call" and frame.f_code in (body.__code__, coroutine.__code__):
            starts.append(frame.f_code.co_name)

    previous = sys.getprofile()
    outcomes = {}
    try:
        sys.setprofile(profile)
        for label, invoke in (
            ("packing", lambda: body(*BrokenExpansion())),
            ("binding", lambda: body()),
            ("body", lambda: body(None)),
        ):
            starts.clear(); effects.clear()
            try:
                invoke()
            except Exception as error:
                outcomes[label] = {"exception": type(error).__name__, "body_starts": list(starts),
                                   "effects": list(effects)}
        starts.clear(); effects.clear()
        suspended = coroutine(None)
        outcomes["async_creation"] = {"body_starts": list(starts), "effects": list(effects)}
        try:
            suspended.send(None)
        except StopIteration:
            pass
        outcomes["async_resume"] = {"body_starts": list(starts), "effects": list(effects)}
        suspended.close()
    finally:
        sys.setprofile(previous)
    return outcomes


if __name__ == "__main__":
    result = {"python": sys.version, "implementation": sys.implementation.name,
              "cells": inspect_cells(), "defaults_globals": inspect_defaults_globals(),
              "monitoring": inspect_monitoring(), "failure_stages": inspect_failure_stages()}
    destination = Path(__file__).with_name("probe_results.json")
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
