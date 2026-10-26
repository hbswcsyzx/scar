"""CLI view of published native input associations, without capture replay."""
from __future__ import annotations

import json
from pathlib import Path
import re


def query_native_inputs_cli(args):
    from scar.trace.native_input_index import query_native_input_associations

    if re.fullmatch(r"[0-9a-f]{64}", args.sha256) is None:
        raise ValueError("--sha256 requires the expected published manifest SHA256")
    for name in ("row", "node_id"):
        value = getattr(args, name)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("native input selectors must be nonnegative exact integers")
    report = query_native_input_associations(
        args.manifest, expected_sha256=args.sha256, row=args.row,
        node_id=args.node_id, associations=args.associations, limit=args.limit)
    payload = json.dumps({
        "schema": "scar.native-input-query", "schema_version": 1,
        "manifest": str(Path(args.manifest).absolute()),
        "manifest_sha256": args.sha256,
        "selector": {"row": args.row, "node_id": args.node_id,
                     "associations": args.associations, "limit": args.limit},
        **report,
    }, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.out:
        with Path(args.out).open("x", encoding="utf-8") as stream:
            stream.write(payload)
    else:
        print(payload, end="")
    return 0
