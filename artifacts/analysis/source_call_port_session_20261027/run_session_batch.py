from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scar.analysis.retained_source_call_ports import RetainedSourceCallPortSession
from scar.analysis.retained_source_call_publication import publish_retained_source_call_port_shards


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description="Read one retained CALL trace and publish typed source-port shards")
    parser.add_argument("--source-report", required=True)
    parser.add_argument("--bindings", required=True)
    parser.add_argument("--expected-report-sha256", required=True)
    parser.add_argument("--expected-bindings-sha256", required=True)
    parser.add_argument("--trace-root")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--max-candidate-pairs", type=int, default=512)
    parser.add_argument("--max-selected-calls-per-shard", type=int, default=32)
    parser.add_argument("--max-candidate-pairs-per-shard", type=int, default=64)
    parser.add_argument("--body-limit", type=int, default=128_000_000)
    parser.add_argument("--body-cache-decoded-byte-budget", type=int, default=64_000_000)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output = Path(args.output_dir).absolute()
    output.mkdir(parents=True, exist_ok=True)
    terminal_path = output / "terminal.json"
    started = time.monotonic()
    terminal = {"schema": "scar.retained-source-call-port-session-terminal",
        "schema_version": 1, "status": "RUNNING", "python": "lewm-env/-B"}
    try:
        session = RetainedSourceCallPortSession(
            source_report_path=args.source_report,
            bindings_path=args.bindings,
            expected_report_sha256=args.expected_report_sha256,
            expected_bindings_sha256=args.expected_bindings_sha256,
            trace_root=args.trace_root,
            pid=args.pid,
            max_candidate_pairs=args.max_candidate_pairs,
            body_limit=args.body_limit,
            max_live_body_decoded_bytes=args.body_cache_decoded_byte_budget,
        )
        result = publish_retained_source_call_port_shards(session, output,
            max_selected_calls_per_shard=args.max_selected_calls_per_shard,
            max_candidate_pairs_per_shard=args.max_candidate_pairs_per_shard)
        terminal.update({"status": result["manifest"]["status"],
            "manifest_path": result["manifest_path"],
            "manifest_sha256": result["manifest_sha256"],
            "manifest_bytes": result["manifest_bytes"],
            "totals": result["manifest"]["totals"],
            "session": result["manifest"]["session"]})
        code = 0
    except BaseException as error:
        terminal.update({"status": "FAIL", "error_type": type(error).__name__, "error": str(error)})
        code = 1
        raise
    finally:
        terminal["elapsed_seconds"] = time.monotonic() - started
        payload = canonical(terminal) + b"\n"
        with terminal_path.open("xb") as stream:
            stream.write(payload)
        terminal["terminal_sha256"] = sha256(payload).hexdigest()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
