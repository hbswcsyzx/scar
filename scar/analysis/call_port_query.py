"""Read retained, version-qualified source argument paths without raw replay."""
from __future__ import annotations

from hashlib import sha256
import gzip
from io import BytesIO
from pathlib import Path
import re
import time

from scar.ir.record_codec import encode, loads as strict_loads


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
    text = raw.decode("utf-8")
    document = strict_loads(text)
    if (type(document) is not dict or type(document.get("schema")) is not str
            or type(document.get("schema_version")) is not int):
        raise ValueError("unsupported source port model schema/version")
    transport = document["schema"], document["schema_version"]
    if transport == ("scar.source-call-port-bindings", 1):
        model = SourceCallPortModel.from_dict(document)
        del document
        version = 1
    elif transport == ("scar.python-source-port-bindings", 2):
        from scar.ir.program.python_call_targets import PythonSourcePortModel
        # Its normal strict reader is the sole transport authority. Release
        # header-dispatch JSON before parsing the bounded v2 payload there.
        del document
        model = PythonSourcePortModel.loads(text)
        version = 2
    else:
        raise ValueError("unsupported source port model schema/version")
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError("source port model changed during query")
    bindings, issues, matched, issue_count = [], [], 0, 0
    for binding in model.bindings:
        owner = getattr(binding, direction) if version == 1 else getattr(binding.entry, direction)
        if invocation is not None and owner != invocation:
            continue
        if attempt_index is not None and binding.attempt.index != attempt_index:
            continue
        original_ports = binding.ports if version == 1 else binding.arguments
        ports = tuple(p for p in original_ports if actual_index is None or p.index == actual_index)
        if actual_index is not None and not ports:
            continue
        matched += 1
        if len(bindings) < limit:
            item = encode(binding)
            item["ports" if version == 1 else "arguments"] = encode(ports)
            # v2 receiver is an independent callable projection. It retains
            # no actual index and is never shifted into explicit arguments.
            bindings.append(item)
    # Issues only identify callers. A callee selector cannot establish their
    # missing destination, so the query does not invent one.
    if direction == "caller":
        targets = ({} if version == 1 else
                   dict(zip(model.observed.target_anchors, model.observed.targets)))
        for issue in model.issues:
            target = None if version == 1 else targets[issue.target_anchor]
            caller = issue.caller if version == 1 else target.caller
            index = issue.attempt.index if version == 1 else issue.attempt_index
            if invocation is not None and caller != invocation:
                continue
            if attempt_index is not None and index != attempt_index:
                continue
            issue_count += 1
            if len(issues) < limit:
                item = encode(issue)
                if version == 2:
                    item["observed_target"] = encode(target)
                issues.append(item)
    result = {"schema": "scar.source-call-port-query", "schema_version": version,
            "artifact": {"uri": str(path), "stored_bytes": len(stored),
                         "stored_sha256": expected_sha256, "decoded_bytes": len(raw),
                         "decoded_sha256": sha256(raw).hexdigest()},
            "selector": {"invocation": encode(invocation), "direction": direction,
                         "attempt_index": attempt_index, "actual_index": actual_index},
            "summary": model.summary(), "matched_bindings": matched,
            "bindings": bindings, "matching_caller_issues": issue_count, "issues": issues,
            "truncated": matched > len(bindings) or issue_count > len(issues),
            "qualification": ("RETAINED_CONDITIONAL_SOURCE_USE_TO_FORMAL_PORTS" if version == 1 else
                              "RETAINED_CONDITIONAL_PYTHON_SOURCE_PORTS_V2"),
            "transport_validated": True, "producer_inputs_replayed": False,
            "reference_identity_established": False, "contents_state_ready_established": False,
            "return_routes_implied": False, "whole_program_complete": False,
            "transformation_authorized": False,
            "costs": {"stored_bytes": len(stored), "decoded_bytes": len(raw),
                      "elapsed_s": time.monotonic() - started}}
    if version == 2:
        result["model_transport"] = {"schema": transport[0], "schema_version": transport[1]}
        result["selector"]["actual_index_role"] = "EXPLICIT_SOURCE_ARGUMENT_INDEX"
        result["receiver_selection"] = "INDEPENDENT_CALLABLE_RECEIVER_PORT"
    return result


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
