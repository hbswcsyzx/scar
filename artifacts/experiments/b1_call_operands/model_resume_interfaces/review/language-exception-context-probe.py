#!/usr/bin/env python3
"""Probe CPython handled-exception context across generator drive boundaries."""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path


def label(error):
    return type(error).__name__ if error is not None else None


def drive_inside_handler(generator, exception):
    try:
        raise exception
    except BaseException as caller_error:
        before = sys.exception()
        value = next(generator)
        after = sys.exception()
        return {
            "generator_value": value,
            "caller_before_type": label(before),
            "caller_after_type": label(after),
            "caller_context_restored": before is caller_error and after is caller_error,
        }


def run_probe():
    observations = {}

    def no_internal_handler():
        for _ in range(3):
            current = sys.exception()
            yield label(current)

    no_handler = no_internal_handler()
    observations["caller_context_inherited_per_drive"] = [
        drive_inside_handler(no_handler, ValueError("outer-one")),
        drive_inside_handler(no_handler, LookupError("outer-two")),
        drive_inside_handler(no_handler, IndexError("outer-three")),
    ]

    inner = KeyError("generator-owned")

    def owns_handler_across_yield():
        try:
            raise inner
        except KeyError as caught:
            yield {"type": label(sys.exception()), "is_owned_exception": sys.exception() is caught}
            yield {"type": label(sys.exception()), "is_owned_exception": sys.exception() is caught}

    own_handler = owns_handler_across_yield()
    observations["generator_handler_saved_across_yield"] = [
        drive_inside_handler(own_handler, ValueError("caller-one")),
        drive_inside_handler(own_handler, OSError("caller-two")),
    ]

    def after_internal_handler():
        try:
            raise KeyError("caught-and-cleared")
        except KeyError:
            pass
        yield label(sys.exception())

    observations["after_internal_handler_cleared"] = drive_inside_handler(
        after_internal_handler(), RuntimeError("new-caller-context"))

    pending_error = KeyError("pending-finally-error")

    def yield_in_finally_with_pending_raise():
        try:
            raise pending_error
        finally:
            current = sys.exception()
            yield {"type": label(current), "is_pending_error": current is pending_error}

    in_finally = yield_in_finally_with_pending_raise()
    first = drive_inside_handler(in_finally, ValueError("caller-before-finally"))
    try:
        raise IndexError("caller-before-propagation")
    except BaseException as caller_error:
        try:
            next(in_finally)
        except BaseException as propagated:
            propagated_record = {
                "type": label(propagated),
                "is_pending_error": propagated is pending_error,
                "inside_catch_is_propagated": sys.exception() is propagated,
            }
        caller_restored = sys.exception() is caller_error
    observations["yield_in_finally_with_pending_raise"] = {
        "first_drive": first,
        "propagation": propagated_record,
        "outer_caller_restored_after_nested_catch": caller_restored,
    }

    def return_through_finally():
        try:
            return "body-return"
        finally:
            yield {"no_handled_exception": sys.exception() is None}

    pending_return = return_through_finally()
    observations["yield_in_finally_with_pending_return"] = drive_inside_handler(
        pending_return, ArithmeticError("caller-with-pending-return"))
    try:
        next(pending_return)
    except StopIteration as stop:
        observations["yield_in_finally_with_pending_return"]["terminal_value"] = stop.value

    return observations


if __name__ == "__main__":
    report_path = Path(__file__).with_name("language-exception-context-probe.json")
    report = {
        "schema": "scar.language-exception-context-probe.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "runtime": {
            "implementation": platform.python_implementation(),
            "version": sys.version,
        },
        "scope": "stdlib CPU witness; logs exception type and identity booleans only; no frame/local retention, torch, SCAR, or target workload",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "observations": run_probe(),
    }
    report_path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True, indent=2))
