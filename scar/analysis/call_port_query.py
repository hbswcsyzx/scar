"""Read retained, version-qualified source argument paths without raw replay."""
from __future__ import annotations

from hashlib import sha256
import gzip
from io import BytesIO
from pathlib import Path
import re
import time

from scar.ir.record_codec import encode


def query_call_ports(model_path, *, expected_sha256, invocation=None,
                     direction="caller", attempt_index=None, actual_index=None,
                     limit=20, max_stored_bytes=64_000_000,
                     max_decoded_bytes=256_000_000):
    """Select original conditional actual-Use → formal routes.

    Strict transport validation checks retained model structure, not a fresh
    replay of its producer inputs. All references stay scoped to this artifact.
    """
    from scar.ir.program.call_edges import InvocationKey
    from scar.ir.program.source_call_bindings import SourceCallPortModel

    started = time.monotonic()
    if (type(expected_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
            or direction not in ("caller", "callee")
            or type(limit) is not int or not 1 <= limit <= 1000
            or any(type(n) is not int or n < 1 for n in (max_stored_bytes, max_decoded_bytes))):
        raise ValueError("invalid source port query bounds or selector")
    for selector in (attempt_index, actual_index):
        if selector is not None and (type(selector) is not int or selector < 0):
            raise ValueError("source port indices must be nonnegative exact integers")
    if invocation is not None and type(invocation) is not InvocationKey:
        raise TypeError("invocation requires the exact typed process/thread/invocation key")
    path = Path(model_path).absolute()
    if path.is_symlink() or not path.is_file():
        raise ValueError("source port model must be a regular retained file")
    before = path.stat()
    if before.st_size > max_stored_bytes:
        raise ValueError("source port model exceeds stored byte limit")
    with path.open("rb") as stream:
        stored = stream.read(max_stored_bytes + 1)
    if len(stored) != before.st_size or sha256(stored).hexdigest() != expected_sha256:
        raise ValueError("source port model stored receipt differs")
    if path.suffix == ".gz":
        with gzip.GzipFile(fileobj=BytesIO(stored)) as stream:
            raw = stream.read(max_decoded_bytes + 1)
    else:
        raw = stored
    if len(raw) > max_decoded_bytes:
        raise ValueError("source port model exceeds decoded byte limit")
    model = SourceCallPortModel.loads(raw.decode("utf-8"))
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError("source port model changed during query")
    bindings, issues, matched, issue_count = [], [], 0, 0
    for binding in model.bindings:
        if invocation is not None and getattr(binding, direction) != invocation:
            continue
        if attempt_index is not None and binding.attempt.index != attempt_index:
            continue
        ports = tuple(p for p in binding.ports if actual_index is None or p.index == actual_index)
        if actual_index is not None and not ports:
            continue
        matched += 1
        if len(bindings) < limit:
            item = encode(binding)
            item["ports"] = encode(ports)
            bindings.append(item)
    # Issues only identify callers. A callee selector cannot establish their
    # missing destination, so the query does not invent one.
    if direction == "caller":
        for issue in model.issues:
            if invocation is not None and issue.caller != invocation:
                continue
            if attempt_index is not None and issue.attempt.index != attempt_index:
                continue
            issue_count += 1
            if len(issues) < limit:
                issues.append(encode(issue))
    return {"schema": "scar.source-call-port-query", "schema_version": 1,
            "artifact": {"uri": str(path), "stored_bytes": len(stored),
                         "stored_sha256": expected_sha256, "decoded_bytes": len(raw),
                         "decoded_sha256": sha256(raw).hexdigest()},
            "selector": {"invocation": encode(invocation), "direction": direction,
                         "attempt_index": attempt_index, "actual_index": actual_index},
            "summary": model.summary(), "matched_bindings": matched,
            "bindings": bindings, "matching_caller_issues": issue_count, "issues": issues,
            "truncated": matched > len(bindings) or issue_count > len(issues),
            "qualification": "RETAINED_CONDITIONAL_SOURCE_USE_TO_FORMAL_PORTS",
            "transport_validated": True, "producer_inputs_replayed": False,
            "reference_identity_established": False, "contents_state_ready_established": False,
            "return_routes_implied": False, "whole_program_complete": False,
            "transformation_authorized": False,
            "costs": {"stored_bytes": len(stored), "decoded_bytes": len(raw),
                      "elapsed_s": time.monotonic() - started}}


def query_call_ports_cli(args):
    import json
    from scar.ir.program.call_edges import InvocationKey

    invocation = None
    if args.invocation is not None:
        if re.fullmatch(r"[0-9]+:[0-9]+:[0-9]+", args.invocation) is None:
            raise ValueError("--invocation requires PID:TID:INVOCATION")
        invocation = InvocationKey(*(int(v) for v in args.invocation.split(":")))
    report = query_call_ports(args.model, expected_sha256=args.sha256,
                              invocation=invocation, direction=args.direction,
                              attempt_index=args.attempt_index, actual_index=args.actual_index,
                              limit=args.limit, max_stored_bytes=args.max_stored_bytes,
                              max_decoded_bytes=args.max_decoded_bytes)
    payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.out:
        with Path(args.out).open("x", encoding="utf-8") as stream:
            stream.write(payload)
    else:
        print(payload, end="")
    return 0
