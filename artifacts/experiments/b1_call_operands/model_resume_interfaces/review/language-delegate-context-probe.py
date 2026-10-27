#!/usr/bin/env python3
"""Probe delegated callbacks under parent and caller exception contexts.

CPython 3.14.7, standard library only. Retains no Python frames/locals in output.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path


class ParentError(Exception):
    pass


class CallerError(Exception):
    pass


class InjectedError(Exception):
    pass


def summarize_context(method: str, parent_exc, caller_exc, received_exc=None):
    active = sys.exception()
    return {
        "method": method,
        "active_type": type(active).__name__ if active is not None else None,
        "is_parent_exception": active is parent_exc,
        "is_caller_exception": active is caller_exc,
        "is_received_exception": received_exc is not None and active is received_exc,
    }


class ProbeDelegate:
    def __init__(self, log, *, throw_mode="yield"):
        self.log = log
        self.parent_exc = None
        self.caller_exc = None
        self.throw_mode = throw_mode
        self.next_count = 0

    def __iter__(self):
        return self

    def __next__(self):
        self.next_count += 1
        self.log.append(summarize_context("__next__", self.parent_exc, self.caller_exc))
        if self.next_count == 1:
            return "delegate-first-item"
        if self.next_count == 2:
            return "delegate-next-item"
        raise StopIteration("delegate-finished")

    def send(self, value):
        self.log.append(summarize_context("send", self.parent_exc, self.caller_exc))
        return ["delegate-send-item", value]

    def throw(self, exc):
        self.log.append(summarize_context("throw", self.parent_exc, self.caller_exc, exc))
        if self.throw_mode == "yield":
            return "delegate-throw-item"
        if self.throw_mode == "raise_received":
            raise exc
        raise AssertionError("unknown throw_mode")

    def close(self):
        self.log.append(summarize_context("close", self.parent_exc, self.caller_exc))


def make_parent(delegate, parent_log, *, catch_delegate_throw=False):
    try:
        raise ParentError("parent-A")
    except ParentError as parent_exc:
        delegate.parent_exc = parent_exc
        if catch_delegate_throw:
            try:
                yield from delegate
            except InjectedError as caught:
                parent_log.append({
                    "site": "caught_delegate_throw",
                    "active_type": type(sys.exception()).__name__ if sys.exception() is not None else None,
                    "is_caught_exception": sys.exception() is caught,
                    "is_parent_exception": sys.exception() is parent_exc,
                })
            parent_log.append({
                "site": "after_delegate_throw_handler",
                "active_type": type(sys.exception()).__name__ if sys.exception() is not None else None,
                "is_parent_exception": sys.exception() is parent_exc,
            })
            yield "parent-after-delegate-throw"
        else:
            yield from delegate
            parent_log.append({
                "site": "after_delegation",
                "active_type": type(sys.exception()).__name__ if sys.exception() is not None else None,
                "is_parent_exception": sys.exception() is parent_exc,
            })
            yield "parent-after-delegation"


def run_probe():
    results = {}

    # Resume by next and non-None send while the caller handles B. The delegate
    # is called from the resumed parent body, unlike the special throw/close
    # delegation fast paths.
    log = []
    parent_log = []
    delegate = ProbeDelegate(log)
    gen = make_parent(delegate, parent_log)
    initial = next(gen)
    try:
        raise CallerError("caller-B-next")
    except CallerError as caller_exc:
        delegate.caller_exc = caller_exc
        after_next = next(gen)
        caller_restored_after_next = sys.exception() is caller_exc
    try:
        raise CallerError("caller-B-send")
    except CallerError as caller_exc:
        delegate.caller_exc = caller_exc
        after_send = gen.send("sent-value")
        caller_restored_after_send = sys.exception() is caller_exc
    gen.close()
    results["normal_next_and_send"] = {
        "initial_yield": initial,
        "next_yield": after_next,
        "send_yield": after_send,
        "delegate_callbacks": log,
        "caller_context_restored": caller_restored_after_next and caller_restored_after_send,
    }

    # Parent.throw delegates directly to iterator.throw when available. The
    # callback records the context it actually sees before choosing to yield.
    log = []
    parent_log = []
    delegate = ProbeDelegate(log, throw_mode="yield")
    gen = make_parent(delegate, parent_log)
    initial = next(gen)
    try:
        raise CallerError("caller-B-throw-yield")
    except CallerError as caller_exc:
        delegate.caller_exc = caller_exc
        thrown = InjectedError("injected-X")
        returned = gen.throw(thrown)
        caller_restored = sys.exception() is caller_exc
    gen.close()
    results["throw_returns_delegate_yield"] = {
        "initial_yield": initial,
        "throw_result": returned,
        "delegate_callbacks": log,
        "caller_context_restored": caller_restored,
    }

    # A delegate.throw callback raises the injected exception; the parent then
    # resumes inside its own handler, catches it locally, and continues.
    log = []
    parent_log = []
    delegate = ProbeDelegate(log, throw_mode="raise_received")
    gen = make_parent(delegate, parent_log, catch_delegate_throw=True)
    initial = next(gen)
    try:
        raise CallerError("caller-B-throw-raise")
    except CallerError as caller_exc:
        delegate.caller_exc = caller_exc
        thrown = InjectedError("injected-Y")
        returned = gen.throw(thrown)
        caller_restored = sys.exception() is caller_exc
    gen.close()
    results["throw_delegate_raises_parent_continues"] = {
        "initial_yield": initial,
        "throw_result": returned,
        "delegate_callbacks": log,
        "parent_callbacks": parent_log,
        "caller_context_restored": caller_restored,
    }

    # Closing a suspended parent first calls delegate.close where present;
    # then GeneratorExit is injected into the parent body.
    log = []
    parent_log = []
    delegate = ProbeDelegate(log)
    gen = make_parent(delegate, parent_log)
    initial = next(gen)
    try:
        raise CallerError("caller-B-close")
    except CallerError as caller_exc:
        delegate.caller_exc = caller_exc
        gen.close()
        caller_restored = sys.exception() is caller_exc
    results["close_forwarded_to_delegate"] = {
        "initial_yield": initial,
        "delegate_callbacks": log,
        "caller_context_restored": caller_restored,
        "final_state": inspect.getgeneratorstate(gen),
    }

    return results


if __name__ == "__main__":
    script = Path(__file__)
    result = {
        "schema": "scar.language-delegate-context-probe.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "runtime": {
            "implementation": platform.python_implementation(),
            "version": sys.version,
        },
        "scope": "stdlib CPU witness only; no SCAR/PyTorch/target workload; output stores types and identity booleans, no frames",
        "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "observations": run_probe(),
    }
    Path(__file__).with_suffix(".json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True, indent=2))
