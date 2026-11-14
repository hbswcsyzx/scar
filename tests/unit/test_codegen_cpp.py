"""One native expression, its persistent ABI, and invocation guards."""
from dataclasses import replace
import ctypes
import os
import platform
from pathlib import Path
import shutil

import numpy as np
import pytest

from scar.codegen import GuardFailure, build, load
from scar.codegen.cpp import _Array
from scar.compiler.model import ArrayRegion, CpuPlacement, ExecutionPlan, Expr, SourceRef


@pytest.mark.parametrize("cpu_threads", [1, 2])
def test_cpp_strided_expression_and_guards(tmp_path, cpu_threads):
    if shutil.which("g++") is None:
        pytest.skip("g++ required for the C++20 backend")
    capacity = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    if cpu_threads > capacity:
        pytest.skip("parallel example requires two available CPUs")
    source = SourceRef(str(tmp_path / "expression.py"), "0" * 64, "expression", 1, 0, "test-code")
    region = ArrayRegion("expression", source, ("a", "b"), (
        Expr("a", "input", attrs={"name": "a"}),
        Expr("b", "input", attrs={"name": "b"}),
        Expr("av", "slice", ("a",), {"bounds": [[1, -1], [None, -1]]}),
        Expr("bv", "slice", ("b",), {"bounds": [[1, -1], [None, -1]]}),
        Expr("sum", "add", ("av", "bv")),
        Expr("scale", "const", attrs={"value": 0.25}),
        Expr("scaled", "mul", ("sum", "scale")),
        Expr("negative", "neg", ("scaled",)),
        Expr("difference", "sub", ("negative", "bv")),
        Expr("result", "div", ("difference", "av")),
    ), "result")
    plan = ExecutionPlan(region, cpu_threads=cpu_threads)
    artifact = build(plan, tmp_path / "native")
    a = (np.arange(120, dtype=np.float64).reshape(10, 12) + 1)[::-2, 1::2]
    b = np.arange(120, dtype=np.float64).reshape(12, 10).T[::-2, 1::2]
    before_a, before_b = a.copy(), b.copy()
    expected = (-((a[1:-1, :-1] + b[1:-1, :-1]) * 0.25) - b[1:-1, :-1]) / a[1:-1, :-1]
    result = artifact.run(a, b)
    np.testing.assert_array_equal(result.view(np.uint64), expected.view(np.uint64))
    assert not np.shares_memory(result, a) and not np.shares_memory(result, b)
    np.testing.assert_array_equal(a, before_a)
    np.testing.assert_array_equal(b, before_b)
    np.testing.assert_array_equal(load(artifact.directory).run(a, b), expected)
    assert artifact.report["operator_abi_version"] == 1
    assert "-ffp-contract=off" in artifact.compiler_options
    assert ("-fopenmp" in artifact.compiler_options) == (cpu_threads > 1)
    assert artifact.source_path.exists() and artifact.library_path.exists()
    assert artifact.run(a[:0], b[:0]).shape == (0, 5)

    with pytest.raises(GuardFailure, match="identical shapes"):
        artifact.run(a, b[:, :1])
    with pytest.raises(GuardFailure, match="float64"):
        artifact.run(a.astype(np.float32), b)
    with pytest.raises(GuardFailure, match="float64"):
        artifact.run(a.astype(np.dtype("float64").newbyteorder("S")), b)
    with pytest.raises(GuardFailure, match="rank-two"):
        artifact.run(a.ravel(), b)
    with pytest.raises(GuardFailure, match="count"):
        artifact.run(a)
    class Derived(np.ndarray):
        pass
    with pytest.raises(GuardFailure, match="exact"):
        artifact.run(a.view(Derived), b)
    bad_bounds = np.lib.stride_tricks.as_strided(a, shape=(1000, 1000))
    with pytest.raises(GuardFailure, match="allocation"):
        artifact.run(bad_bounds, b)
    unaligned = np.ndarray((5, 6), dtype=np.float64, buffer=bytearray(5 * 6 * 8 + 1), offset=1)
    with pytest.raises(GuardFailure, match="aligned"):
        artifact.run(unaligned, b)
    # The ABI rejects invalid descriptors before dereferencing their pointers.
    invalid = (_Array * 2)(_Array(1, 2, (3, 3), (24, 8), 1, 2), _Array())
    output = _Array(1, 2, (3, 3), (24, 8), 1, 2)
    assert artifact._run(invalid, 2, ctypes.byref(output)) == 1

    mode = np.geterr().copy()
    with np.errstate(all="raise"):
        strict_mode = np.geterr().copy()
        for exceptional_a, exceptional_b in (
            (np.zeros((5, 6)), np.ones((5, 6))),
            (np.zeros((5, 6)), np.zeros((5, 6))),
            (np.ones((5, 6)), np.full((5, 6), np.nan)),
            (np.ones((5, 6)), np.full((5, 6), np.inf)),
            (np.full((5, 6), np.finfo(np.float64).max), np.full((5, 6), np.finfo(np.float64).max)),
            (np.full((5, 6), np.finfo(np.float64).smallest_subnormal), np.zeros((5, 6))),
        ):
            with pytest.raises(GuardFailure, match="floating-point"):
                artifact.run(exceptional_a, exceptional_b)
            assert np.geterr() == strict_mode
    assert np.geterr() == mode

    # glibc/x86 fenv constants: exercise a warmed worker pool after the caller
    # changes rounding, and check the native ABI preserves preexisting flags.
    if platform.system() == "Linux" and platform.machine() == "x86_64":
        from scar.codegen.cpp import _descriptor
        fenv = ctypes.CDLL(None)
        fenv.fegetround.argtypes = []
        fenv.fegetround.restype = ctypes.c_int
        for function in (fenv.fesetround, fenv.fetestexcept, fenv.feclearexcept, fenv.feraiseexcept):
            function.argtypes = [ctypes.c_int]
            function.restype = ctypes.c_int
        all_flags, inexact, downward = 0x3D, 0x20, 0x400
        saved_rounding = fenv.fegetround()
        saved_flags = fenv.fetestexcept(all_flags)
        native_output = np.empty(expected.shape)
        native_inputs = (_Array * 2)(_descriptor(a), _descriptor(b))
        native_output_descriptor = _descriptor(native_output)
        zero = np.zeros((5, 6))
        invalid_inputs = (_Array * 2)(_descriptor(zero), _descriptor(zero))
        try:
            assert fenv.fesetround(downward) == 0
            rounded_expected = (-((a[1:-1, :-1] + b[1:-1, :-1]) * 0.25) - b[1:-1, :-1]) / a[1:-1, :-1]
            assert fenv.feclearexcept(all_flags) == 0
            assert fenv.feraiseexcept(inexact) == 0
            assert artifact._run(native_inputs, 2, ctypes.byref(native_output_descriptor)) == 0
            assert fenv.fegetround() == downward
            assert fenv.fetestexcept(all_flags) == inexact
            np.testing.assert_array_equal(native_output.view(np.uint64), rounded_expected.view(np.uint64))
            # An exceptional call restores the same caller context as success.
            assert fenv.feclearexcept(all_flags) == 0
            assert fenv.feraiseexcept(inexact) == 0
            assert artifact._run(invalid_inputs, 2, ctypes.byref(native_output_descriptor)) == 3
            assert fenv.fegetround() == downward
            assert fenv.fetestexcept(all_flags) == inexact
        finally:
            fenv.fesetround(saved_rounding)
            fenv.feclearexcept(all_flags)
            fenv.feraiseexcept(saved_flags)

    limited = build(replace(plan, cost={"memory_budget_bytes": 8}), tmp_path / "limited")
    with pytest.raises(GuardFailure, match="memory_budget"):
        limited.run(a, b)

    if platform.system() == "Linux":
        # These backend checks use a typed placement; target-graph provenance
        # is checked separately by the compiler's hardware admission boundary.
        original_affinity = os.sched_getaffinity(0)
        cpu_ids = tuple(sorted(original_affinity)[:cpu_threads])
        placement = CpuPlacement(str(tmp_path / "target.json"), "0" * 64,
                                 "test-cpu-executor", cpu_ids)
        bound = build(replace(plan, schema_version=2, resource_binding=placement), tmp_path / "bound")

        def thread_affinities():
            masks = {}
            for task in Path("/proc/self/task").iterdir():
                try:
                    masks[int(task.name)] = os.sched_getaffinity(int(task.name))
                except ProcessLookupError:
                    pass
            return masks

        def assert_affinities_restored(before):
            after = thread_affinities()
            assert all(after[tid] == mask for tid, mask in before.items() if tid in after)
            assert os.sched_getaffinity(0) == original_affinity

        masks = thread_affinities()
        np.testing.assert_array_equal(bound.run(a, b).view(np.uint64), expected.view(np.uint64))
        assert_affinities_restored(masks)
        with pytest.raises(GuardFailure, match="floating-point"):
            bound.run(np.zeros((5, 6)), np.ones((5, 6)))
        assert_affinities_restored(masks)
        assert bound.run(a[:0], b[:0]).shape == (0, 5)
        assert_affinities_restored(masks)
        policy = bound.report["resource_placement"]
        assert policy["cpu_affinity"] == "NATIVE_ENFORCED_PER_CALL"
        assert policy["cpu_ids"] == list(cpu_ids)
        assert policy["memory_policy"] == "UNBOUND" and not policy["numa_page_binding"]
        if len(original_affinity) > 1:
            narrowed = {next(cpu for cpu in original_affinity if cpu != cpu_ids[-1])}
            try:
                os.sched_setaffinity(0, narrowed)
                with pytest.raises(GuardFailure, match="CPU affinity"):
                    bound.run(a, b)
                assert os.sched_getaffinity(0) == narrowed
            finally:
                os.sched_setaffinity(0, original_affinity)
        with pytest.raises(ValueError, match="schema"):
            build(replace(plan, resource_binding=placement), tmp_path / "invalid-binding")
