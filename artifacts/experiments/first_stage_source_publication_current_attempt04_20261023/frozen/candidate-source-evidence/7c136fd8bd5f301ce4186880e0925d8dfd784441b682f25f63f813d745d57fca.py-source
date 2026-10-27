"""Generic PyTorch micro workload used to exercise SCAR itself."""
from __future__ import annotations

import argparse
import os
import statistics
import time

import torch

from scar.backends import exact_reuse, pure


class Expensive(torch.nn.Module):
    scar_pure = True

    def __init__(self, width=256):
        super().__init__()
        self.layer = torch.nn.Sequential(torch.nn.Linear(width, width), torch.nn.GELU(),
                                         torch.nn.Linear(width, width))

    def forward(self, x):
        return self.layer(x)


@pure
def pure_function(x, work_factor=1):
    for _ in range(work_factor):
        x = torch.sin(x).square()
    return x.sum(dim=-1)


def run(loops: int = 8, device: str = "cuda" if torch.cuda.is_available() else "cpu"):
    torch.manual_seed(0)
    module = Expensive().to(device).eval()
    x = torch.randn(64, 256, device=device)
    with torch.inference_mode():
        for _ in range(loops):
            module(x)
    return module, x


def _timed(fn, x, loops, device, work_factor=1):
    if device == "cuda":
        torch.cuda.synchronize()
    started = time.perf_counter()
    with torch.inference_mode():
        values = [fn(x, work_factor=work_factor) for _ in range(loops)]
    if device == "cuda":
        torch.cuda.synchronize()
    return time.perf_counter() - started, values


def optimize(loops: int = 30, repetitions: int = 5, warmup: int = 1, work_factor: int = 1):
    if loops < 1 or repetitions < 1 or warmup < 0 or work_factor < 1:
        raise ValueError("loops/repetitions/work_factor must be positive and warmup non-negative")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    # Keep the output compact while making the avoided elementwise work large
    # enough that cache lookup and copy overhead can be measured separately.
    torch.manual_seed(0)
    x = torch.randn(65536, 256, device=device)
    input_snapshot = x.clone()
    cpu_rng = torch.random.get_rng_state()
    cuda_rng = torch.cuda.get_rng_state() if device == "cuda" else None
    wrapped = exact_reuse(pure_function)
    for _ in range(warmup):
        _timed(pure_function, x, loops, device, work_factor)
        _timed(wrapped, x, loops, device, work_factor)
    baseline_times, optimized_times = [], []
    all_equal = True
    for repetition in range(repetitions):
        if repetition % 2 == 0:
            baseline_time, baseline_value = _timed(pure_function, x, loops, device, work_factor)
            optimized_time, optimized_value = _timed(wrapped, x, loops, device, work_factor)
        else:
            optimized_time, optimized_value = _timed(wrapped, x, loops, device, work_factor)
            baseline_time, baseline_value = _timed(pure_function, x, loops, device, work_factor)
        baseline_times.append(baseline_time)
        optimized_times.append(optimized_time)
        all_equal = all_equal and all(torch.equal(a, b) for a, b in zip(baseline_value, optimized_value))
    baseline_median = statistics.median(baseline_times)
    optimized_median = statistics.median(optimized_times)
    state_equal = torch.equal(x, input_snapshot) and torch.equal(cpu_rng, torch.random.get_rng_state())
    if cuda_rng is not None:
        state_equal = state_equal and torch.equal(cuda_rng, torch.cuda.get_rng_state())
    profitable = optimized_median < baseline_median
    instrumented = bool(os.environ.get("SCAR_TRACE_DIR"))
    accepted = profitable and all_equal and state_equal and not instrumented
    reason = ("validation failed" if not (all_equal and state_equal) else
              "instrumented timing cannot select a clean benchmark winner" if instrumented else
              "measured profitable" if profitable else "not profitable")
    return {"device": device, "loops": loops, "warmup": warmup, "work_factor": work_factor,
            "gpu": torch.cuda.get_device_name() if device == "cuda" else None,
            "torch_version": torch.__version__, "cuda_version": torch.version.cuda,
            "instrumented": instrumented,
            "seed": 0, "input_shape": list(x.shape), "input_dtype": str(x.dtype),
            "guard": wrapped.guard_kind, "retained_tensor_bytes": wrapped.retained_bytes,
            "repetitions": repetitions, "baseline_s": baseline_median,
            "optimized_s": optimized_median,
            "baseline_min_s": min(baseline_times), "baseline_max_s": max(baseline_times),
            "optimized_min_s": min(optimized_times), "optimized_max_s": max(optimized_times),
            "baseline_samples_s": baseline_times, "optimized_samples_s": optimized_times,
            "baseline_variance_s2": statistics.pvariance(baseline_times),
            "optimized_variance_s2": statistics.pvariance(optimized_times),
            "speedup": baseline_median / max(optimized_median, 1e-12),
            "cache_hits": wrapped.hits, "equal": all_equal, "visible_state_equal": state_equal,
            "validation_level": 1, "profitable": profitable,
            "decision": "exact_reuse" if accepted else "noop", "reason": reason}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["pure", "optimize"], default="pure", nargs="?")
    p.add_argument("--loops", type=int, default=8)
    args = p.parse_args()
    if args.mode == "optimize":
        print(optimize(args.loops))
    else:
        run(args.loops)
