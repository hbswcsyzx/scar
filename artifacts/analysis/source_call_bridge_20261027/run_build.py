from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis.retained_source_call_ports import build_retained_source_call_ports


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description="Build selected retained source CALL ports")
    parser.add_argument("--source-report", required=True)
    parser.add_argument("--bindings", required=True)
    parser.add_argument("--expected-report-sha256", required=True)
    parser.add_argument("--expected-bindings-sha256", required=True)
    parser.add_argument("--trace-root")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--max-selected-calls", type=int, default=1)
    parser.add_argument("--model-output", required=True)
    parser.add_argument("--build-report", required=True)
    parser.add_argument("--terminal", required=True)
    args = parser.parse_args()
    started = time.monotonic()
    terminal = {"schema": "scar.retained-source-call-port-terminal", "schema_version": 1,
                "status": "RUNNING"}
    try:
        model = build_retained_source_call_ports(
            source_report_path=args.source_report,
            bindings_path=args.bindings,
            expected_report_sha256=args.expected_report_sha256,
            expected_bindings_sha256=args.expected_bindings_sha256,
            trace_root=args.trace_root,
            pid=args.pid,
            max_selected_calls=args.max_selected_calls,
            build_report_path=args.build_report,
        )
        payload = canonical(model.to_dict()) + b"\n"
        output = Path(args.model_output).absolute()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)
        terminal.update({"status": "PASS", "model_path": str(output),
            "model_sha256": sha256(payload).hexdigest(), "model_bytes": len(payload),
            "model_summary": model.summary()})
        if model.bindings:
            code = 0
        else:
            terminal["status"] = "TRANSPORT_ONLY_ZERO_LINKS"
            code = 1
    except BaseException as error:
        terminal.update({"status": "FAIL", "error_type": type(error).__name__,
                         "error": str(error)})
        code = 1
        raise
    finally:
        terminal["elapsed_seconds"] = time.monotonic() - started
        terminal["source_stamps"] = {
            name: {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()}
            for name, path in (("retained_source_call_ports.py",
                                Path(__file__).resolve().parents[3] / "scar/analysis/retained_source_call_ports.py"),
                               ("source_return_bindings.py",
                                Path(__file__).resolve().parents[3] / "scar/analysis/source_return_bindings.py"))
        }
        terminal_path = Path(args.terminal).absolute()
        terminal_path.parent.mkdir(parents=True, exist_ok=True)
        terminal_path.write_bytes(canonical(terminal) + b"\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
