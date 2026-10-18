#!/usr/bin/env python3
"""Bounded, observational CPython generator state/request matrix.

This script records standard-library behavior only. It is not a SCAR validator,
trace collector, or source/runtime correspondence test.
"""

from __future__ import annotations

import inspect
import json
import platform
import sys
import warnings


constructor_events: list[str] = []


class ConstructorFailure(Exception):
    def __init__(self, *args):
        constructor_events.append("ConstructorFailure.__init__ entered")
        raise RuntimeError("exception constructor failed")


def state_of(gen):
    try:
        return inspect.getgeneratorstate(gen)
    except BaseException as exc:
        return {"state_error": type(exc).__name__, "args": [safe_value(x) for x in exc.args]}


def safe_value(value, depth=0):
    if depth > 3:
        return {"type": type(value).__name__, "value": "<depth-limit>"}
    if value is None or type(value) in (bool, int, float, str):
        if type(value) is str and len(value) > 160:
            return {"type": "str", "value": value[:160], "truncated": True}
        return value
    if type(value) is bytes:
        return {"type": "bytes", "hex": value[:80].hex(), "truncated": len(value) > 80}
    if isinstance(value, BaseException):
        return {"type": type(value).__name__, "args": [safe_value(x, depth + 1) for x in value.args]}
    if type(value) in (tuple, list):
        return {"type": type(value).__name__, "items": [safe_value(x, depth + 1) for x in value[:12]],
                "truncated": len(value) > 12}
    if isinstance(value, type):
        return {"type": "exception_class" if issubclass(value, BaseException) else "class",
                "name": value.__qualname__}
    return {"type": type(value).__name__}


def exception_summary(exc):
    frames = []
    tb = exc.__traceback__
    while tb is not None and len(frames) < 24:
        code = tb.tb_frame.f_code
        frames.append({"function": code.co_name, "file": code.co_filename.rsplit("/", 1)[-1],
                       "line": tb.tb_lineno})
        tb = tb.tb_next
    cause = exc.__cause__
    context = exc.__context__ if cause is None else None
    return {
        "type": type(exc).__name__,
        "args": [safe_value(value) for value in exc.args],
        "cause": None if cause is None else {"type": type(cause).__name__,
                                               "args": [safe_value(value) for value in cause.args]},
        "context": None if context is None else {"type": type(context).__name__,
                                                   "args": [safe_value(value) for value in context.args]},
        "traceback_frames": frames,
        "traceback_mentions_generator_body": any(frame["function"] in
            ("catching_generator", "uncaught_stop_generator", "internal_stop_generator",
             "ignored_close_generator", "finally_yield_generator", "raising_close_generator",
             "running_generator") for frame in frames),
    }


def invoke(gen, operation, args):
    caught_warnings = []
    try:
        with warnings.catch_warnings(record=True) as rows:
            warnings.simplefilter("always")
            if operation == "NEXT":
                value = next(gen)
            elif operation == "SEND":
                value = gen.send(args[0])
            elif operation == "THROW":
                value = gen.throw(*args)
            elif operation == "CLOSE":
                value = gen.close()
            else:
                raise AssertionError(operation)
            caught_warnings = [{"category": row.category.__name__, "message": str(row.message)}
                               for row in rows]
        return {"returned": safe_value(value), "warnings": caught_warnings}
    except BaseException as exc:
        return {"raised": exception_summary(exc), "warnings": caught_warnings}


def request_shape(label, operation, args):
    shaped = []
    for value in args:
        if isinstance(value, type) and issubclass(value, BaseException):
            shaped.append({"kind": "exception-class", "name": value.__qualname__})
        elif isinstance(value, BaseException):
            shaped.append({"kind": "exception-instance", "type": type(value).__name__,
                           "args": [safe_value(x) for x in value.args]})
        else:
            shaped.append(safe_value(value))
    return {"label": label, "operation": operation, "raw_args": shaped}


def request_matrix():
    return [
        ("NEXT", "NEXT", ()),
        ("SEND_NONE", "SEND", (None,)),
        ("SEND_NON_NONE", "SEND", ("payload",)),
        ("THROW_INSTANCE", "THROW", (ValueError("instance-value"),)),
        ("THROW_CLASS", "THROW", (ValueError,)),
        ("THROW_CLASS_AND_VALUE", "THROW", (ValueError, "class-value")),
        ("THROW_INVALID_ARITY", "THROW", (ValueError, "a", None, "extra")),
        ("THROW_CONSTRUCTOR_FAILURE", "THROW", (ConstructorFailure,)),
        ("THROW_STOP_ITERATION", "THROW", (StopIteration("external-stop"),)),
        ("CLOSE", "CLOSE", ()),
    ]


def catching_generator(body_log):
    body_log.append("body-entry")
    while True:
        try:
            sent = yield "ready"
        except GeneratorExit:
            body_log.append("body-GeneratorExit")
            return "generator-return-during-close"
        except BaseException as exc:
            body_log.append("body-caught:" + type(exc).__name__)
            yield "caught-exception"
        else:
            body_log.append("body-sent:" + str(safe_value(sent)))
            yield "sent-value"


def generator_for_state(state_label, body_log):
    gen = catching_generator(body_log)
    setup = []
    if state_label == "CREATED":
        pass
    elif state_label == "SUSPENDED":
        setup.append({"operation": "NEXT", "outcome": invoke(gen, "NEXT", ())})
    elif state_label == "CLOSED":
        setup.append({"operation": "NEXT", "outcome": invoke(gen, "NEXT", ())})
        setup.append({"operation": "CLOSE", "outcome": invoke(gen, "CLOSE", ())})
    else:
        raise AssertionError(state_label)
    return gen, setup


def followup(gen):
    before = state_of(gen)
    outcome = invoke(gen, "NEXT", ())
    return {"operation": "NEXT", "before": before, "outcome": outcome, "after": state_of(gen)}


def run_ordinary_case(state_label, label, operation, args):
    global constructor_events
    constructor_events = []
    body_log = []
    gen, setup = generator_for_state(state_label, body_log)
    before = state_of(gen)
    body_before = list(body_log)
    constructor_before = list(constructor_events)
    outcome = invoke(gen, operation, args)
    after = state_of(gen)
    body_after = list(body_log)
    constructor_after = list(constructor_events)
    next_observation = followup(gen)
    return {
        "state_case": state_label,
        "request": request_shape(label, operation, args),
        "setup": setup,
        "state_before": before,
        "state_after_request": after,
        "body_log_before": body_before,
        "body_log_after_request": body_after,
        "constructor_log_before": constructor_before,
        "constructor_log_after_request": constructor_after,
        "outcome": outcome,
        "followup_drive": next_observation,
        "final_state": state_of(gen),
    }


def running_case(label, operation, args):
    global constructor_events
    constructor_events = []
    body_log = []
    holder = {}
    inner = {}

    def running_generator():
        body_log.append("body-entry")
        yield "armed"
        body_log.append("body-running-before-reentry")
        inner["state_before"] = state_of(holder["gen"])
        inner["outcome"] = invoke(holder["gen"], operation, args)
        inner["state_after_request"] = state_of(holder["gen"])
        body_log.append("body-running-after-reentry")
        yield "after-reentry"

    gen = running_generator()
    holder["gen"] = gen
    setup = invoke(gen, "NEXT", ())
    state_before_outer_resume = state_of(gen)
    body_before = list(body_log)
    outer_resume = invoke(gen, "SEND", ("resume-running-generator",))
    state_after_outer_resume = state_of(gen)
    body_after = list(body_log)
    ctor_after = list(constructor_events)
    next_observation = followup(gen)
    return {
        "state_case": "RUNNING_REENTRANT",
        "request": request_shape(label, operation, args),
        "setup": setup,
        "state_before_outer_resume": state_before_outer_resume,
        "body_log_before_outer_resume": body_before,
        "state_during_request": inner.get("state_before"),
        "state_after_reentrant_request_while_body_continues": inner.get("state_after_request"),
        "reentrant_outcome": inner.get("outcome"),
        "outer_resume_outcome": outer_resume,
        "state_after_outer_resume": state_after_outer_resume,
        "body_log_after_outer_resume": body_after,
        "constructor_log_after_request": ctor_after,
        "followup_drive": next_observation,
        "final_state": state_of(gen),
    }


def uncaught_stop_generator(body_log):
    body_log.append("body-entry")
    yield "armed"
    body_log.append("body-after-resume-before-StopIteration")
    raise StopIteration("body-internal-stop")


def run_uncaught_stop_case(state_label, operation, args, internal=False):
    body_log = []
    if internal:
        gen = uncaught_stop_generator(body_log)
        setup = [{"operation": "NEXT", "outcome": invoke(gen, "NEXT", ())}]
        operation, args, label = "SEND", ("trigger-body-stop",), "BODY_INTERNAL_STOPITERATION"
    else:
        gen = uncaught_stop_generator(body_log)
        setup = []
        if state_label == "SUSPENDED":
            setup = [{"operation": "NEXT", "outcome": invoke(gen, "NEXT", ())}]
        label = "EXTERNAL_THROW_STOPITERATION_UNCAUGHT"
    before = state_of(gen)
    outcome = invoke(gen, operation, args)
    after = state_of(gen)
    return {
        "state_case": "SUSPENDED" if internal else state_label,
        "request": request_shape(label, operation, args),
        "setup": setup,
        "state_before": before,
        "body_log_after_request": list(body_log),
        "outcome": outcome,
        "state_after_request": after,
        "followup_drive": followup(gen),
        "final_state": state_of(gen),
    }


def ignored_close_generator(body_log):
    body_log.append("body-entry")
    try:
        yield "armed"
    except GeneratorExit:
        body_log.append("caught-GeneratorExit-and-yielded")
        yield "ignored-close-yield"
        body_log.append("resumed-after-ignored-yield")


def finally_yield_generator(body_log):
    body_log.append("body-entry")
    try:
        yield "armed"
    finally:
        body_log.append("finally-before-yield")
        yield "yielded-from-finally"
        body_log.append("finally-after-yield")


def raising_close_generator(body_log):
    body_log.append("body-entry")
    try:
        yield "armed"
    except GeneratorExit:
        body_log.append("caught-GeneratorExit-then-raise")
        raise RuntimeError("close cleanup failed")


def run_close_retry(kind):
    body_log = []
    factory = ignored_close_generator if kind == "ignored-yield" else finally_yield_generator
    gen = factory(body_log)
    setup = invoke(gen, "NEXT", ())
    state_before = state_of(gen)
    first = invoke(gen, "CLOSE", ())
    state_after_first = state_of(gen)
    log_after_first = list(body_log)
    second = invoke(gen, "CLOSE", ())
    state_after_second = state_of(gen)
    log_after_second = list(body_log)
    after = followup(gen)
    return {
        "case": "CLOSE_IGNORED_YIELD_RETRY" if kind == "ignored-yield" else "CLOSE_YIELD_FROM_FINALLY_RETRY",
        "setup": setup,
        "state_before_close": state_before,
        "first_close": first,
        "state_after_first_close": state_after_first,
        "body_log_after_first_close": log_after_first,
        "second_close": second,
        "state_after_second_close": state_after_second,
        "body_log_after_second_close": log_after_second,
        "later_drive": after,
        "final_state": state_of(gen),
    }


def run_raising_close():
    body_log = []
    gen = raising_close_generator(body_log)
    setup = invoke(gen, "NEXT", ())
    before = state_of(gen)
    outcome = invoke(gen, "CLOSE", ())
    after = state_of(gen)
    return {"case": "CLOSE_PROPAGATED_BODY_FAILURE", "setup": setup,
            "state_before_close": before, "outcome": outcome,
            "body_log_after_close": body_log, "state_after_close": after,
            "followup_drive": followup(gen), "final_state": state_of(gen)}


def run_matrix():
    rows = []
    for state_label in ("CREATED", "SUSPENDED", "CLOSED"):
        for label, operation, args in request_matrix():
            rows.append(run_ordinary_case(state_label, label, operation, args))
    for label, operation, args in request_matrix():
        rows.append(running_case(label, operation, args))
    return rows


def main():
    special = [
        run_uncaught_stop_case("CREATED", "THROW", (StopIteration("external-stop"),)),
        run_uncaught_stop_case("SUSPENDED", "THROW", (StopIteration("external-stop"),)),
        run_uncaught_stop_case("SUSPENDED", "SEND", (), internal=True),
        run_close_retry("ignored-yield"),
        run_close_retry("finally-yield"),
        run_raising_close(),
    ]
    report = {
        "schema": "scar.cpython-generator-matrix-observation.v1",
        "scope": "Synchronous Python generators only; small stdlib CPU observations; no SCAR execution or assertion of expected protocol semantics.",
        "python": sys.version,
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "matrix_rows": run_matrix(),
        "special_rows": special,
        "assertions": 0,
        "source_runtime_correspondence_verified": False,
        "transformation_authorized": False,
    }
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
