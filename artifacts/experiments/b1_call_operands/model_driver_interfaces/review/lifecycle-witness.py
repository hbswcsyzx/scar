"""Bounded CPython lifecycle witnesses; stdlib only, no retained frames/targets.

Events contain exact strings/integers. Weak references are held only in each
case's temporary harness; their targets, exceptions and traceback objects are
never included in results. Earlier attempts remain in the JSON history.
"""
from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
import platform
import sys
from datetime import datetime, timezone
import weakref


class CallerContext(Exception):
    pass


class BodyContext(Exception):
    pass


class BodyFailure(Exception):
    pass


class FinalizerFailure(Exception):
    pass


def active_exception():
    exc = sys.exception()
    name = "NONE" if exc is None else type(exc).__name__
    del exc
    return name


def context(events):
    return {"events": events, "owner_ref": None, "watchers": [], "world": 0}


def emit(ctx, event, **fields):
    owner = ctx["owner_ref"]() if ctx["owner_ref"] is not None else None
    if owner is None:
        state = "NO_OWNER"
    elif inspect.isgenerator(owner):
        state = inspect.getgeneratorstate(owner)
    elif inspect.iscoroutine(owner):
        state = inspect.getcoroutinestate(owner)
    elif inspect.isasyncgen(owner):
        state = inspect.getasyncgenstate(owner)
    else:
        state = "OTHER_OWNER"
    del owner
    row = {"event": event, "context": active_exception(), "owner_state": state,
           "world": ctx["world"], **fields}
    assert all(type(value) in (str, int) for value in row.values())
    ctx["events"].append(row)


class Victim:
    def __init__(self, ctx, label, action="NONE"):
        self.ctx, self.label, self.action = ctx, label, action

    def __del__(self):
        self.ctx["world"] += 1
        emit(self.ctx, self.label + ".del")
        if self.action in ("REENTER", "ALLOCATE_REENTER_RAISE"):
            owner = self.ctx["owner_ref"]()
            try:
                next(owner)
            except BaseException as exc:
                emit(self.ctx, self.label + ".reenter", result=type(exc).__name__)
            else:
                emit(self.ctx, self.label + ".reenter", result="RETURNED")
            del owner
        if self.action == "ALLOCATE_REENTER_RAISE":
            child = Victim(self.ctx, self.label + ".allocated")
            emit(self.ctx, self.label + ".allocation")
            del child
            raise FinalizerFailure("intentional bounded finalizer failure")


def watched(ctx, label, action="NONE"):
    target = Victim(ctx, label, action)
    def callback(_reference):
        emit(ctx, label + ".weak")
    reference = weakref.ref(target, callback)
    ctx["watchers"].append(reference)
    return target, reference


def event(events, name):
    found = [row for row in events if row["event"] == name]
    assert len(found) == 1, (name, len(found))
    return found[0]


def position(events, name):
    return next(index for index, row in enumerate(events) if row["event"] == name)


def normal_return(events):
    ctx = context(events)
    def body():
        local, _ = watched(ctx, "normal")
        try:
            raise BodyContext("owned")
        except BodyContext:
            yield "ready"
            emit(ctx, "normal.body-return")
            return "result"
    gen = body()
    ctx["owner_ref"] = weakref.ref(gen)
    assert next(gen) == "ready"
    try:
        raise CallerContext("caller")
    except CallerContext:
        try:
            next(gen)
        except StopIteration as stop:
            assert stop.value == "result"
        else:
            raise AssertionError("missing exhaustion")
        emit(ctx, "normal.host-returned")
    assert event(events, "normal.body-return")["context"] == "BodyContext"
    for name in ("normal.del", "normal.weak"):
        assert event(events, name)["context"] == "CallerContext"
        assert event(events, name)["owner_state"] == "GEN_CLOSED"
    assert position(events, "normal.body-return") < position(events, "normal.del")
    assert position(events, "normal.del") < position(events, "normal.weak") < position(events, "normal.host-returned")
    return {"final_state": inspect.getgeneratorstate(gen), "world": ctx["world"]}


def exceptional_escape(events):
    ctx = context(events)
    def body():
        local, _ = watched(ctx, "escape")
        yield "ready"
        emit(ctx, "escape.body-raise")
        raise BodyFailure("body")
    gen = body()
    ctx["owner_ref"] = weakref.ref(gen)
    assert next(gen) == "ready"
    reference = ctx["watchers"][0]
    try:
        raise CallerContext("caller")
    except CallerContext:
        try:
            next(gen)
        except BodyFailure:
            emit(ctx, "escape.host-caught", target_alive=int(reference() is not None))
            assert reference() is not None  # Exception's live traceback owns locals.
            assert inspect.getgeneratorstate(gen) == "GEN_CLOSED"
        else:
            raise AssertionError("missing BodyFailure")
        emit(ctx, "escape.after-handler", target_alive=int(reference() is not None))
        assert reference() is None
    assert position(events, "escape.host-caught") < position(events, "escape.del")
    assert position(events, "escape.del") < position(events, "escape.after-handler")
    assert event(events, "escape.del")["context"] == "CallerContext"
    assert event(events, "escape.weak")["owner_state"] == "GEN_CLOSED"
    return {"retained_during_handler": 1, "released_after_handler": 1}


def close_with_finally(events):
    ctx = context(events)
    def body():
        local, _ = watched(ctx, "close")
        try:
            yield "ready"
        finally:
            emit(ctx, "close.body-finally")
    gen = body()
    ctx["owner_ref"] = weakref.ref(gen)
    assert next(gen) == "ready"
    try:
        raise CallerContext("caller")
    except CallerContext:
        assert gen.close() is None
        emit(ctx, "close.host-returned")
    assert event(events, "close.body-finally")["context"] == "GeneratorExit"
    assert event(events, "close.body-finally")["owner_state"] == "GEN_RUNNING"
    for name in ("close.del", "close.weak"):
        assert event(events, name)["context"] == "CallerContext"
        assert event(events, name)["owner_state"] == "GEN_CLOSED"
    assert position(events, "close.body-finally") < position(events, "close.del") < position(events, "close.host-returned")
    return {"final_state": inspect.getgeneratorstate(gen)}


def created_close(events):
    ctx = context(events)
    def body(argument):
        emit(ctx, "created.body-entered")
        yield argument
    def create():
        argument, reference = watched(ctx, "created")
        return body(argument), reference
    gen, reference = create()  # create()'s argument local is now gone.
    ctx["owner_ref"] = weakref.ref(gen)
    assert inspect.getgeneratorstate(gen) == "GEN_CREATED"
    assert reference() is not None and not events
    try:
        raise CallerContext("caller")
    except CallerContext:
        assert gen.close() is None
        emit(ctx, "created.host-returned")
    assert reference() is None
    assert not any(row["event"] == "created.body-entered" for row in events)
    assert event(events, "created.del")["context"] == "CallerContext"
    assert event(events, "created.del")["owner_state"] == "GEN_CLOSED"
    assert position(events, "created.weak") < position(events, "created.host-returned")
    return {"body_entries": 0, "final_state": inspect.getgeneratorstate(gen)}


def overwrite_and_delete(events):
    ctx = context(events)
    def body():
        overwritten, _ = watched(ctx, "overwrite", "REENTER")
        deleted, _ = watched(ctx, "delete")
        try:
            raise BodyContext("owned")
        except BodyContext:
            yield "ready"
            emit(ctx, "attached.before-overwrite")
            overwritten = None
            emit(ctx, "attached.after-overwrite")
            del deleted
            emit(ctx, "attached.after-delete")
            yield "after"
    gen = body()
    ctx["owner_ref"] = weakref.ref(gen)
    assert next(gen) == "ready"
    try:
        raise CallerContext("caller")
    except CallerContext:
        assert next(gen) == "after"
        emit(ctx, "attached.host-yielded")
    for label in ("overwrite", "delete"):
        for suffix in ("del", "weak"):
            assert event(events, label + "." + suffix)["context"] == "BodyContext"
            assert event(events, label + "." + suffix)["owner_state"] == "GEN_RUNNING"
    assert event(events, "overwrite.reenter")["result"] == "ValueError"
    assert position(events, "attached.before-overwrite") < position(events, "overwrite.del") < position(events, "attached.after-overwrite")
    assert position(events, "attached.after-overwrite") < position(events, "delete.del") < position(events, "attached.after-delete")
    gen.close()
    return {"world": ctx["world"], "final_state": inspect.getgeneratorstate(gen)}


def terminal_reentry_allocation_unraisable(events):
    ctx = context(events)
    def hook(args):
        emit(ctx, "terminal.unraisable", exception_type=args.exc_type.__name__,
             origin_type=type(args.object).__name__)
        # Do not retain args, args.object, args.exc_value or traceback.
    def body():
        local, _ = watched(ctx, "terminal", "ALLOCATE_REENTER_RAISE")
        yield "ready"
        return "kept-return"
    gen = body()
    ctx["owner_ref"] = weakref.ref(gen)
    assert next(gen) == "ready"
    original_hook = sys.unraisablehook
    sys.unraisablehook = hook
    try:
        try:
            raise CallerContext("caller")
        except CallerContext:
            try:
                next(gen)
            except StopIteration as stop:
                assert stop.value == "kept-return"
            else:
                raise AssertionError("finalizer changed normal return")
            emit(ctx, "terminal.host-returned")
    finally:
        sys.unraisablehook = original_hook
    assert event(events, "terminal.del")["context"] == "CallerContext"
    assert event(events, "terminal.del")["owner_state"] == "GEN_CLOSED"
    assert event(events, "terminal.reenter")["result"] == "StopIteration"
    assert event(events, "terminal.unraisable")["exception_type"] == "FinalizerFailure"
    assert position(events, "terminal.unraisable") < position(events, "terminal.host-returned")
    assert ctx["world"] == 2
    assert ctx["watchers"][0]() is None
    return {"world": ctx["world"], "final_state": inspect.getgeneratorstate(gen)}


class PauseOnce:
    def __await__(self):
        yield "scheduler-pause"
        return "await-result"


def coroutine_await_lifecycle(events):
    ctx = context(events)
    async def body():
        local, _ = watched(ctx, "coroutine")
        emit(ctx, "coroutine.body-entered")
        result = await PauseOnce()
        emit(ctx, "coroutine.after-await")
        return result
    coro = body()
    ctx["owner_ref"] = weakref.ref(coro)
    wrapper = coro.__await__()
    assert inspect.getcoroutinestate(coro) == "CORO_CREATED" and not events
    assert next(wrapper) == "scheduler-pause"
    assert inspect.getcoroutinestate(coro) == "CORO_SUSPENDED"
    emit(ctx, "coroutine.wrapper-paused")
    try:
        raise CallerContext("caller")
    except CallerContext:
        try:
            wrapper.send(None)
        except StopIteration as stop:
            assert stop.value == "await-result"
        else:
            raise AssertionError("coroutine did not complete")
        emit(ctx, "coroutine.host-returned")
    assert event(events, "coroutine.del")["context"] == "CallerContext"
    assert event(events, "coroutine.del")["owner_state"] == "CORO_CLOSED"
    assert inspect.getcoroutinestate(coro) == "CORO_CLOSED"
    return {"wrapper_is_body": int(wrapper is coro), "final_state": inspect.getcoroutinestate(coro)}


def asyncgen_request_vs_body(events):
    ctx = context(events)
    async def body():
        local, _ = watched(ctx, "asyncgen")
        emit(ctx, "asyncgen.body-entered")
        await PauseOnce()
        emit(ctx, "asyncgen.after-await")
        yield "item"
        emit(ctx, "asyncgen.after-item")
    gen = body()
    ctx["owner_ref"] = weakref.ref(gen)
    request = gen.__anext__()
    assert inspect.getasyncgenstate(gen) == "AGEN_CREATED" and not events
    assert request is not gen
    assert request.send(None) == "scheduler-pause"
    emit(ctx, "asyncgen.request-paused", request_type=type(request).__name__)
    try:
        request.send(None)
    except StopIteration as stop:
        assert stop.value == "item"
    else:
        raise AssertionError("anext request did not complete at user yield")
    assert inspect.getasyncgenstate(gen) == "AGEN_SUSPENDED"
    try:
        request.send(None)
    except RuntimeError:
        emit(ctx, "asyncgen.request-exhausted-body-suspended")
    else:
        raise AssertionError("completed request was reused")
    before = len(events)
    closing = gen.aclose()
    assert len(events) == before  # Request creation did not execute body.
    try:
        raise CallerContext("caller")
    except CallerContext:
        try:
            closing.send(None)
        except StopIteration as stop:
            assert stop.value is None
        else:
            raise AssertionError("aclose request did not complete")
        emit(ctx, "asyncgen.host-closed")
    assert inspect.getasyncgenstate(gen) == "AGEN_CLOSED"
    assert event(events, "asyncgen.del")["context"] == "CallerContext"
    assert ctx["watchers"][0]() is None
    assert not any(row["event"] == "asyncgen.after-item" for row in events)
    return {"request_is_body": 0, "request_type": type(request).__name__,
            "body_final_state": inspect.getasyncgenstate(gen)}


CASES = (normal_return, exceptional_escape, close_with_finally, created_close,
         overwrite_and_delete, terminal_reentry_allocation_unraisable,
         coroutine_await_lifecycle, asyncgen_request_vs_body)


def main():
    output = Path(__file__).with_suffix(".json")
    rows = []
    for case in CASES:
        events = []
        try:
            result = case(events)
        except Exception as exc:
            row = {"case": case.__name__, "status": "FAIL", "events": events,
                   "error_type": type(exc).__name__, "message": str(exc)}
        else:
            row = {"case": case.__name__, "status": "PASS", "events": events,
                   "asserted_summary": result}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False, sort_keys=True), flush=True)
    failed = sum(row["status"] != "PASS" for row in rows)
    attempt = {"created_utc": datetime.now(timezone.utc).isoformat(),
        "runtime": {"version": sys.version, "implementation": platform.python_implementation()},
        "command": "PYTHONDONTWRITEBYTECODE=1 python " + str(Path(__file__)),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "torch_imported": int("torch" in sys.modules), "scar_imported": int("scar" in sys.modules),
        "results": rows, "passed": len(rows) - failed, "failed": failed,
        "exit_code": int(bool(failed))}
    history = json.loads(output.read_text()) if output.exists() else {
        "schema": "scar.driver-lifecycle-witness.v1", "attempts": []}
    history["attempts"].append(attempt)
    output.write_text(json.dumps(history, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"passed": len(rows) - failed, "failed": failed,
                      "exit_code": int(bool(failed))}), flush=True)
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
