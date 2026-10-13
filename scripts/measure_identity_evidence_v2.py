"""Execute an explicit reference-comparison fixture and measure evidence cost.

This driver executes the supplied module and calls its selected two-argument
function. Source analysis inside SCAR never imports the target. No target is
rewritten, no result is reused, and the measurements are not speedup evidence.
"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import tokenize

from scar.analysis.execution_occurrences_v2 import query_execution_result_use
from scar.analysis.regions_v2 import build_regions
from scar.analysis.source_semantics_v2 import extract_source_semantics
from scar.cli import _compressed_document
from scar.ir.frontend_v2 import build_semantic
from scar.ir.identity_execution_v2 import IdentityExecutionSnapshot
from scar.ir.record_codec import encode
from scar.trace.identity_v2 import IdentityExecutionObserver
from scripts.measure_import_values_v2 import process_peak_rss


class Reference:
    def __eq__(self, other):
        raise AssertionError("the evidence collector must not compare object contents")

    def __hash__(self):
        raise AssertionError("the evidence collector must not hash user objects")

    def __repr__(self):
        raise AssertionError("the evidence collector must not render user objects")


def summarize(samples):
    return {"samples": samples, "median": statistics.median(samples),
            "min": min(samples), "max": max(samples),
            "variance": statistics.pvariance(samples)}


def identity_evidence_report(source, function_name, *, warmup=2, repetitions=7,
                             include_torch=True):
    if type(warmup) is not int or warmup < 0 or type(repetitions) is not int or repetitions < 1:
        raise ValueError("warmup must be nonnegative and repetitions positive")
    source = Path(source).resolve()
    original = source.read_bytes()
    with tokenize.open(source) as stream:
        text = stream.read()
    started = time.perf_counter()
    semantic = build_semantic(source).graph
    source_texts = {str(source): text}
    source_semantics = extract_source_semantics(semantic, sources=source_texts)
    # Only this explicit benchmark driver executes the requested module. Keep
    # its compiled tree alive, as disclosed by the exact correspondence policy.
    code = compile(text, str(source), "exec", dont_inherit=True, optimize=0)
    namespace = {"__name__": "scar_external_reference_fixture", "__file__": str(source)}
    exec(code, namespace)
    function = namespace[function_name]
    preparation_seconds = time.perf_counter() - started
    options = dict(semantic=semantic, source_semantics=source_semantics, source_texts=source_texts)
    left, right = Reference(), Reference()
    observer = IdentityExecutionObserver(function, **options)
    cases = []
    environment = {"python": sys.version, "torch": None, "cuda": None, "gpu": None}
    capture_started = time.perf_counter()
    try:
        def sample(label, a, b):
            value = observer.call(a, b)
            cases.append({"label": label, "result": value, "call_index": len(observer.calls) - 1})

        sample("same_reference", left, left)
        sample("another_reference_same_result", right, right)
        sample("different_references", left, right)
        sample("bool_input_and_bool_result", True, True)
        if include_torch:
            import numpy as np
            import torch
            environment.update(torch=torch.__version__, cuda=torch.version.cuda)
            array = np.zeros(4, dtype=np.float32)
            tensor = torch.from_numpy(array)
            sample("cpu_tensor_before_foreign_write", tensor, tensor)
            array[:] = 3  # No content payload or equality check enters SCAR.
            sample("cpu_tensor_after_foreign_write", tensor, tensor)
            sample("different_tensor_view_objects", tensor, tensor.view(2, 2))
            if torch.cuda.is_available():
                environment["gpu"] = torch.cuda.get_device_name(torch.cuda.current_device())
                gpu_tensor = torch.ones(4, device="cuda")
                sample("gpu_tensor_before_write", gpu_tensor, gpu_tensor)
                gpu_tensor.add_(2)
                sample("gpu_tensor_after_write", gpu_tensor, gpu_tensor)
        validation = observer.validate()
        attested = observer.attest()
        if not validation["valid"] or not attested:
            raise ValueError(f"actual capture failed validation: {validation}")
        snapshot = observer.snapshot()
        if IdentityExecutionSnapshot.from_json(snapshot.to_json()).to_dict() != snapshot.to_dict():
            raise ValueError("historical snapshot roundtrip changed evidence")
        queries = []
        for call in observer.calls:
            query = query_execution_result_use(observer.bundle, call.return_instance,
                call.result_occurrence.observation_id, scope=snapshot.scope)
            if query.producers != (call.operator_instance,):
                raise ValueError("Return use did not resolve to its own primitive occurrence")
            queries.append({"result_use": encode(query),
                            "ordered_inputs": [encode(operand) for operand in call.operands]})
        regions = build_regions(observer.bundle, view="execution",
            roots=tuple(call.function_instance for call in observer.calls), max_depth=1)
        regions.assert_valid()
        captured = {"snapshot": snapshot.to_dict(), "bundle": observer.bundle.to_dict(),
                    "objects": observer.object_observer.model.to_dict(),
                    "source_model": observer.source_model.to_dict(),
                    "return_queries": queries, "regions": regions.to_dict(),
                    "validation": validation, "active_capture_attested": attested}
    finally:
        observer.close()
    capture_seconds = time.perf_counter() - capture_started
    # Two separate populations: a batched original call and a whole bounded
    # collection (setup, one actual call, validation, teardown). Do not divide
    # them into an 'optimization speedup'.
    clean, instrumented = [], []
    batch = 10_000
    for iteration in range(warmup + repetitions):
        start = time.perf_counter_ns()
        for _ in range(batch):
            function(left, right)
        elapsed = (time.perf_counter_ns() - start) / batch
        if iteration >= warmup:
            clean.append(elapsed)
        start = time.perf_counter()
        one = IdentityExecutionObserver(function, **options)
        try:
            one.call(left, right)
            if not one.validate()["valid"] or not one.attest():
                raise ValueError("measurement capture lost its evidence")
        finally:
            one.close()
        if iteration >= warmup:
            instrumented.append(time.perf_counter() - start)
    if source.read_bytes() != original:
        raise ValueError("fixture source changed during evidence collection")
    return {
        "schema": "scar.reference-identity-evidence-measurement", "schema_version": 1,
        "scope": "Captured reference/operand/result occurrences only; no future guard, transform, or workload speedup.",
        "source": str(source), "source_sha256": hashlib.sha256(original).hexdigest(),
        "source_text": text, "function": function_name, "environment": environment,
        "cases": cases, "evidence": captured,
        "decision": {"reuse": "NOT_YET_SUPPORTED", "selection": "NOT_SELECTED", "applied": False},
        "measurement": {"preparation_seconds": preparation_seconds,
            "capture_validation_report_seconds": capture_seconds,
            "warmup": warmup, "repetitions": repetitions, "clean_batch_size": batch,
            "clean_original_call_nanoseconds": summarize(clean),
            "one_call_collector_setup_capture_validate_close_seconds": summarize(instrumented),
            "note": "No GPU kernels or physical transfers are profiled here; GPU inputs are reference samples only."},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--function", required=True)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--without-torch", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parents[1], text=True).strip()
    report = identity_evidence_report(args.source, args.function, warmup=args.warmup,
        repetitions=args.repetitions, include_torch=not args.without_torch)
    output = _compressed_document(args.out, report)
    peak, method = process_peak_rss()
    summary = {"revision": revision, "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": report["source_sha256"], "scope": report["scope"],
        "environment": report["environment"], "measurement": report["measurement"],
        "decision": report["decision"], "cases": report["cases"],
        "calls": len(report["evidence"]["snapshot"]["calls"]),
        "peak_rss_kib": peak, "peak_rss_source": method,
        "peak_rss_scope": "Whole measurement process, including optional Torch/CUDA initialization",
        "report": str(output), "report_bytes": output.stat().st_size,
        "report_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
    output.with_suffix(".measurement.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
