#!/usr/bin/env python3
"""Small stdlib-only Python 3.14 suspension protocol witness; no frames retained."""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path


def run_probe() -> dict[str, object]:
    observations: dict[str, object] = {}

    log: list[object] = []

    def simple_generator(events: list[object]):
        events.append("body-enter")
        sent = yield "yielded-item"
        events.append(["resumed-with", sent])
        return "generator-return"

    gen = simple_generator(log)
    observations["generator_created"] = {"state": inspect.getgeneratorstate(gen), "body_log": list(log)}
    observations["generator_first_next"] = {"value": next(gen), "state": inspect.getgeneratorstate(gen), "body_log": list(log)}
    try:
        gen.send("sent-value")
    except StopIteration as stop:
        observations["generator_terminal"] = {
            "stop_iteration_value": stop.value,
            "state": inspect.getgeneratorstate(gen),
            "body_log": list(log),
        }

    close_log: list[object] = []

    def not_started(events: list[object]):
        try:
            events.append("body-enter")
            yield "unused"
        finally:
            events.append("finally")

    never_started = not_started(close_log)
    never_started.close()
    observations["close_before_first_entry"] = {
        "state": inspect.getgeneratorstate(never_started),
        "body_log": list(close_log),
    }

    close_yield_log: list[object] = []

    def yields_during_close(events: list[object]):
        try:
            yield "ready"
        finally:
            events.append("finally-entered")
            yield "illegal-after-close"

    close_yield = yields_during_close(close_yield_log)
    first = next(close_yield)
    try:
        close_yield.close()
    except RuntimeError as error:
        observations["yield_during_close"] = {
            "first_yield": first,
            "error_type": type(error).__name__,
            "state_after_error": inspect.getgeneratorstate(close_yield),
            "body_log": list(close_yield_log),
        }
    close_yield.close()

    delegation_log: list[object] = []

    def child(events: list[object]):
        try:
            sent = yield "child-yield"
            events.append(["child-send", sent])
            return "child-return"
        finally:
            events.append("child-finally")

    def parent(events: list[object]):
        result = yield from child(events)
        events.append(["parent-yield-from-result", result])
        return "parent-return"

    delegated = parent(delegation_log)
    first = next(delegated)
    try:
        delegated.send("delegated-send")
    except StopIteration as stop:
        observations["yield_from"] = {
            "first_yield": first,
            "parent_stop_iteration_value": stop.value,
            "log": list(delegation_log),
            "state": inspect.getgeneratorstate(delegated),
        }

    shared = {"revision": "before-resume"}

    def reads_shared_on_each_resume(state):
        sent = yield ["first", state["revision"]]
        yield ["second", sent, state["revision"]]

    shared_gen = reads_shared_on_each_resume(shared)
    first = next(shared_gen)
    shared["revision"] = "changed-between-resumes"
    second = shared_gen.send("current-send")
    observations["mutable_shared_state_between_resumes"] = {
        "first_yield": first,
        "second_yield": second,
        "state": inspect.getgeneratorstate(shared_gen),
    }

    class OneTurn:
        def __await__(self):
            inbound = yield "scheduler-token"
            return ["await-result", inbound]

    coroutine_log: list[object] = []

    async def one_await(events: list[object]):
        events.append("body-enter")
        result = await OneTurn()
        events.append(["await-expression-result", result])
        return "coroutine-return"

    coro = one_await(coroutine_log)
    observations["coroutine_created"] = {"state": inspect.getcoroutinestate(coro), "body_log": list(coroutine_log)}
    scheduler_token = coro.send(None)
    observations["coroutine_suspended"] = {
        "scheduler_token": scheduler_token,
        "state": inspect.getcoroutinestate(coro),
        "body_log": list(coroutine_log),
    }
    try:
        coro.send("resume-value")
    except StopIteration as stop:
        observations["coroutine_terminal"] = {
            "stop_iteration_value": stop.value,
            "state": inspect.getcoroutinestate(coro),
            "body_log": list(coroutine_log),
        }

    asyncgen_log: list[object] = []

    async def async_generator(events: list[object]):
        try:
            events.append("body-enter")
            received = yield "async-item"
            events.append(["async-resumed-with", received])
            yield "second-item"
        finally:
            events.append("async-finally")

    async def await_request(request):
        return await request

    agen = async_generator(asyncgen_log)
    request = agen.asend(None)
    observations["asyncgen_request_created"] = {
        "state": inspect.getasyncgenstate(agen),
        "request_type": type(request).__name__,
        "body_log": list(asyncgen_log),
    }
    request_driver = await_request(request)
    try:
        request_driver.send(None)
    except StopIteration as stop:
        observations["asyncgen_request_awaited"] = {
            "awaitable_stop_iteration_value": stop.value,
            "state": inspect.getasyncgenstate(agen),
            "body_log": list(asyncgen_log),
        }
    close_request = agen.aclose()
    observations["asyncgen_aclose_request_created"] = {
        "state": inspect.getasyncgenstate(agen),
        "body_log": list(asyncgen_log),
    }
    close_driver = await_request(close_request)
    try:
        close_driver.send(None)
    except StopIteration as stop:
        observations["asyncgen_aclose_awaited"] = {
            "awaitable_stop_iteration_value": stop.value,
            "state": inspect.getasyncgenstate(agen),
            "body_log": list(asyncgen_log),
        }

    cancel_log: list[object] = []

    async def suppress_cancel(events: list[object]):
        try:
            events.append("body-enter")
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            events.append("cancel-caught")
            return "suppressed-result"

    async def cancel_task() -> dict[str, object]:
        task = asyncio.create_task(suppress_cancel(cancel_log))
        await asyncio.sleep(0)
        task.cancel()
        result = await task
        return {
            "task_result": result,
            "task_cancelled": task.cancelled(),
            "pending_cancel_count": task.cancelling(),
            "body_log": list(cancel_log),
        }

    observations["asyncio_cancel_request"] = asyncio.run(cancel_task())
    return observations


if __name__ == "__main__":
    result_path = Path(__file__).with_name("language-runtime-probe.json")
    report = {
        "schema": "scar.language-resume-probe.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "runtime": {
            "implementation": platform.python_implementation(),
            "version": sys.version,
            "inspect_path": inspect.__file__,
        },
        "scope": "stdlib CPU witness only; no torch, SCAR import, target workload, frame retention, or tensor payload",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "observations": run_probe(),
    }
    result_path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True, indent=2))
