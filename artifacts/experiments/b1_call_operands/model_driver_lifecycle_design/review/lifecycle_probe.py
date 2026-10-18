"""Bounded CPython lifecycle observations for the D2 design review.

Only standard-library generators/coroutines/async generators are exercised.
The probe stores text, state names, and identity booleans; it keeps no frame,
locals, or traceback references and imports no project or workload modules.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import platform
import sys
import weakref
from pathlib import Path


def main() -> None:
    observations: dict[str, object] = {}

    # close() on a never-started generator succeeds without entering its body.
    log: list[str] = []

    def never_started():
        log.append("body-enter")
        try:
            yield "unreachable"
        finally:
            log.append("body-finally")

    gen = never_started()
    before = inspect.getgeneratorstate(gen)
    close_result = gen.close()
    observations["created_close_no_body"] = {
        "before": before,
        "close_result_is_none": close_result is None,
        "after": inspect.getgeneratorstate(gen),
        "body_log": list(log),
    }

    # Closing an unstarted generator can also drop captured arguments. A
    # reentrant destructor sees the already-closed state, even though no body
    # instruction ran.
    created_drop_events: list[dict[str, object]] = []
    created_holder: dict[str, object] = {}

    class DropOnUnstartedClose:
        def __del__(self):
            parent = created_holder["generator_ref"]()
            created_drop_events.append({
                "observed_state": inspect.getgeneratorstate(parent),
            })

    def argument_generator(argument):
        yield argument

    argument = DropOnUnstartedClose()
    gen = argument_generator(argument)
    created_holder["generator_ref"] = weakref.ref(gen)
    argument = None
    gen.close()
    observations["created_close_releases_capture_after_commit"] = {
        "final_state": inspect.getgeneratorstate(gen),
        "release_callbacks": list(created_drop_events),
    }

    # A finally block which yields makes close() fail, leaves the generator
    # suspended, and permits a later close to finish it.
    close_log: list[str] = []

    def yields_during_close():
        try:
            yield "ready"
        finally:
            close_log.append("finally-enter")
            yield "cleanup-yield"
            close_log.append("finally-resumed")

    gen = yields_during_close()
    first = next(gen)
    try:
        gen.close()
    except BaseException as exc:
        first_close_error = type(exc).__name__
    else:
        first_close_error = None
    after_failed_close = inspect.getgeneratorstate(gen)
    try:
        retry_result = gen.close()
    except BaseException as exc:
        retry_error = type(exc).__name__
        retry_result = None
    else:
        retry_error = None
    observations["close_yield_then_retry"] = {
        "first_yield": first,
        "first_close_error": first_close_error,
        "state_after_failed_close": after_failed_close,
        "retry_error": retry_error,
        "retry_result_is_none": retry_result is None,
        "final_state": inspect.getgeneratorstate(gen),
        "body_log": list(close_log),
    }

    # When a generator returns, clearing its frame can drop a local whose
    # __del__ re-enters the generator. That callback observes CLOSED already.
    release_events: list[dict[str, object]] = []
    holder: dict[str, object] = {}

    class ReenterOnDrop:
        def __del__(self):
            parent = holder["generator_ref"]()
            state = inspect.getgeneratorstate(parent)
            try:
                parent.send(None)
            except BaseException as exc:
                outcome = type(exc).__name__
            else:
                outcome = "returned"
            release_events.append({"observed_state": state, "reentry_result": outcome})

    def terminal_generator():
        local = ReenterOnDrop()
        yield "first"
        return "done"

    gen = terminal_generator()
    holder["generator_ref"] = weakref.ref(gen)
    first = next(gen)
    try:
        next(gen)
    except StopIteration as exc:
        terminal_value = exc.value
    else:
        terminal_value = "no-stop-iteration"
    observations["terminal_frame_drop_reentry"] = {
        "first_yield": first,
        "terminal_value": terminal_value,
        "state_after_return": inspect.getgeneratorstate(gen),
        "release_callbacks": list(release_events),
    }

    async def async_observations() -> dict[str, object]:
        ag_log: list[str] = []

        async def async_body():
            ag_log.append("body-enter")
            value = yield "item-1"
            ag_log.append("body-resumed:" + str(value))
            yield "item-2"
            ag_log.append("body-after-item-2")

        ag = async_body()
        request = ag.__anext__()
        created_state = inspect.getasyncgenstate(ag)
        log_at_request_creation = list(ag_log)
        first_item = await request
        state_after_request = inspect.getasyncgenstate(ag)
        close_request = ag.aclose()
        state_before_close_await = inspect.getasyncgenstate(ag)
        await close_request
        return {
            "created_state": created_state,
            "body_log_at_request_creation": log_at_request_creation,
            "first_item": first_item,
            "state_after_anext_request_completed": state_after_request,
            "body_log_after_first_request": list(ag_log),
            "state_when_aclose_request_created": state_before_close_await,
            "state_after_aclose_await": inspect.getasyncgenstate(ag),
            "body_log_after_aclose": list(ag_log),
        }

    observations["asyncgen_request_vs_body"] = asyncio.run(async_observations())

    async def async_close_retry() -> dict[str, object]:
        log: list[str] = []

        async def body():
            try:
                yield "ready"
            finally:
                log.append("finally-enter")
                yield "cleanup-yield"
                log.append("finally-resumed")

        ag = body()
        first = await ag.__anext__()
        try:
            await ag.aclose()
        except BaseException as exc:
            close_error = type(exc).__name__
        else:
            close_error = None
        after_error = inspect.getasyncgenstate(ag)
        try:
            await ag.aclose()
        except BaseException as exc:
            retry_error = type(exc).__name__
        else:
            retry_error = None
        return {
            "first_yield": first,
            "first_close_error": close_error,
            "state_after_failed_close": after_error,
            "retry_error": retry_error,
            "final_state": inspect.getasyncgenstate(ag),
            "body_log": list(log),
        }

    observations["asyncgen_close_yield_then_retry"] = asyncio.run(async_close_retry())

    result = {
        "schema": "scar.driver-lifecycle-probe.v1",
        "runtime": {
            "implementation": platform.python_implementation(),
            "version": sys.version,
        },
        "scope": "stdlib CPU lifecycle witness; no SCAR, torch, target workload, frame retention, or payload values",
        "observations": observations,
    }
    out = Path(__file__).with_suffix(".json")
    out.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
