#!/usr/bin/env python3
"""Small CPython 3.14 yield-from SEND/THROW/CLOSE witness."""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path


def name(obj):
    return type(obj).__name__ if obj is not None else None


def run_probe():
    rows = {}

    def catches_delegated_throw(log):
        try:
            sent = yield "child-start"
            log.append(["child-send-result", sent])
        except LookupError as error:
            log.append(["child-caught-throw", name(error)])
            yield "child-after-throw"
        finally:
            log.append("child-finally")
        return "child-final-value"

    def parent(iterator, log):
        try:
            result = yield from iterator
        finally:
            log.append("parent-finally")
        log.append(["parent-expression-result", result])
        return "parent-return-value"

    log = []
    delegated = parent(catches_delegated_throw(log), log)
    first = next(delegated)
    after_throw = delegated.throw(LookupError("delegated"))
    try:
        next(delegated)
    except StopIteration as stop:
        rows["throw_forwarded_to_delegate"] = {
            "first_yield": first,
            "throw_result_yield": after_throw,
            "terminal_value": stop.value,
            "log": list(log),
        }

    missing_log = []

    def catches_missing_delegate_throw(iterator, events):
        try:
            yield from iterator
        except LookupError as error:
            events.append(["parent-caught-missing-delegate-throw", name(error)])
            yield "parent-handled"
        return "parent-finished"

    missing = catches_missing_delegate_throw(iter(("only-item",)), missing_log)
    missing_first = next(missing)
    after_missing_throw = missing.throw(LookupError("no-delegate-throw"))
    try:
        next(missing)
    except StopIteration as stop:
        rows["missing_delegate_throw_enters_parent"] = {
            "first_yield": missing_first,
            "throw_result_yield": after_missing_throw,
            "terminal_value": stop.value,
            "log": list(missing_log),
        }

    close_log = []

    def child_with_finally(events):
        try:
            yield "child-ready"
        finally:
            events.append("child-finally")

    closing = parent(child_with_finally(close_log), close_log)
    ready = next(closing)
    close_result = closing.close()
    rows["close_forwarded_through_delegation"] = {
        "first_yield": ready,
        "close_result": close_result,
        "log": list(close_log),
    }
    return rows


if __name__ == "__main__":
    path = Path(__file__).with_name("language-delegation-probe.json")
    report = {
        "schema": "scar.language-delegation-probe.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "runtime": {"implementation": platform.python_implementation(), "version": sys.version},
        "scope": "stdlib CPU witness; only text and return results recorded; no frame/local retention, torch, SCAR, or target workload",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "observations": run_probe(),
    }
    path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True, indent=2))
