#!/usr/bin/env python3
"""Record a few static CPython 3.14 disassembly shapes; never executes bodies."""
from __future__ import annotations

import dis
import hashlib
import inspect
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path


def plain_generator(value):
    received = yield value
    return received


def delegated_generator(iterator):
    result = yield from iterator
    return result


async def coroutine(awaitable):
    result = await awaitable
    return result


async def asynchronous_generator(value):
    yield value


def code_record(function):
    code = function.__code__
    mask = inspect.CO_GENERATOR | inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR | inspect.CO_ITERABLE_COROUTINE
    return {
        "code_name": code.co_name,
        "code_flags": code.co_flags,
        "kind_bits": {
            "generator": bool(code.co_flags & inspect.CO_GENERATOR),
            "coroutine": bool(code.co_flags & inspect.CO_COROUTINE),
            "async_generator": bool(code.co_flags & inspect.CO_ASYNC_GENERATOR),
            "iterable_coroutine": bool(code.co_flags & inspect.CO_ITERABLE_COROUTINE),
        },
        "suspension_instructions": [
            {"offset": row.offset, "opname": row.opname, "arg": row.arg, "argrepr": row.argrepr}
            for row in dis.get_instructions(code)
            if row.opname in {"RETURN_GENERATOR", "GET_AWAITABLE", "SEND", "YIELD_VALUE", "RESUME", "ASYNC_GEN_WRAP"}
        ],
        "instruction_count": sum(1 for _ in dis.get_instructions(code)),
        "mask_for_reference": mask,
    }


if __name__ == "__main__":
    report_path = Path(__file__).with_name("language-bytecode-probe.json")
    report = {
        "schema": "scar.language-bytecode-probe.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "runtime": {
            "implementation": platform.python_implementation(),
            "version": sys.version,
            "dis_path": dis.__file__,
        },
        "scope": "stdlib static disassembly only; functions are not invoked; no torch, SCAR, target workload, or frame retention",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "codes": {
            function.__name__: code_record(function)
            for function in (plain_generator, delegated_generator, coroutine, asynchronous_generator)
        },
    }
    report_path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True, indent=2))
