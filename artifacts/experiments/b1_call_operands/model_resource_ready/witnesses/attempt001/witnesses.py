#!/usr/bin/env python3
"""Small asserted CPU/OS counterexamples for resource-ready contracts.

These are hand-written semantic witnesses, not SCAR recovery or tracing tests.
They intentionally retain only a few scalar observations in the result.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import torch


def witness_shared_tensor_buffer() -> dict[str, object]:
    buffer = np.array([11, 22, 33], dtype=np.int64)
    tensor = torch.from_numpy(buffer)
    tensor_identity = id(tensor)
    data_pointer = tensor.data_ptr()
    version_before = tensor._version
    assert tensor.device.type == "cpu"

    consumer_started = threading.Event()
    release_consumer = threading.Event()

    def delayed_consumer() -> int:
        consumer_started.set()
        if not release_consumer.wait(timeout=8):
            raise TimeoutError("consumer was not released")
        return int(tensor[0].item())

    executor = ThreadPoolExecutor(max_workers=1)
    future = None
    try:
        future = executor.submit(delayed_consumer)
        assert consumer_started.wait(timeout=8), "worker did not start"
        assert not future.done(), "consumer unexpectedly completed before release"

        buffer[0] = 73
        version_after_numpy_write = tensor._version
        assert version_after_numpy_write == version_before, (
            "NumPy mutation unexpectedly changed the PyTorch version counter"
        )
        assert tensor.data_ptr() == data_pointer
        assert id(tensor) == tensor_identity

        release_consumer.set()
        observed = future.result(timeout=8)
        assert observed == 73, f"consumer saw stale content: {observed}"
        return {
            "status": "PASS",
            "device": tensor.device.type,
            "same_tensor_object": True,
            "same_data_pointer": True,
            "version_before": version_before,
            "version_after_numpy_write": version_after_numpy_write,
            "consumer_observed_after_release": observed,
            "assertion": "retained tensor and unchanged version did not imply stable contents",
        }
    finally:
        release_consumer.set()
        if future is not None:
            try:
                future.result(timeout=8)
            except Exception:
                pass
        executor.shutdown(wait=True, cancel_futures=True)


class ControlledWriteFailure(RuntimeError):
    pass


def witness_partial_file_write() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="scar-partial-write-") as temp_dir:
        path = Path(temp_dir) / "payload.bin"
        fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_RDWR, 0o600)
        try:
            os.ftruncate(fd, 8)
            try:
                written = os.pwrite(fd, b"ABCD", 0)
                assert written == 4, f"short pwrite: {written} bytes"
                raise ControlledWriteFailure("injected after first four bytes")
            except ControlledWriteFailure:
                injected_failure_observed = True
        finally:
            os.close(fd)

        visible = path.read_bytes()
        assert injected_failure_observed
        assert len(visible) == 8
        assert visible[:4] == b"ABCD"
        assert visible[4:] == b"\x00" * 4
        return {
            "status": "PASS",
            "requested_length": 8,
            "written_before_controlled_failure": 4,
            "partial_bytes_visible": True,
            "remaining_zero_filled_bytes": 4,
            "durability_or_fsync_tested": False,
            "assertion": "an error after a partial write did not roll back the file",
        }


def witness_strided_geometry() -> dict[str, object]:
    base = np.arange(8, dtype=np.uint8)
    dense = base[1:4]
    stride_two = base[1:4:2]

    def element_offsets(view: np.ndarray) -> tuple[int, ...]:
        base_address = int(base.ctypes.data)
        itemsize = int(view.dtype.itemsize)
        first = int(view.ctypes.data)
        if view.size == 0:
            return ()
        return tuple(
            (first + index * int(view.strides[0]) - base_address) // itemsize
            for index in range(view.shape[0])
        )

    def bounding_interval(offsets: tuple[int, ...]) -> tuple[int, int] | None:
        if not offsets:
            return None
        return min(offsets), max(offsets) + 1

    dense_offsets = element_offsets(dense)
    stride_offsets = element_offsets(stride_two)
    dense_interval = bounding_interval(dense_offsets)
    stride_interval = bounding_interval(stride_offsets)
    holes = tuple(sorted(set(dense_offsets) - set(stride_offsets)))
    assert dense_interval == stride_interval == (1, 4)
    assert dense_offsets == (1, 2, 3)
    assert stride_offsets == (1, 3)
    assert holes == (2,)

    empty_zero_stride = np.lib.stride_tricks.as_strided(
        base[:1], shape=(0, 3), strides=(0, 0), writeable=False
    )
    assert empty_zero_stride.size == 0
    assert empty_zero_stride.strides == (0, 0)
    assert tuple(np.ndindex(empty_zero_stride.shape)) == ()

    return {
        "status": "PASS",
        "dense": {
            "shape": dense.shape,
            "strides": dense.strides,
            "addressed_offsets": dense_offsets,
            "bounding_interval": dense_interval,
        },
        "stride_two": {
            "shape": stride_two.shape,
            "strides": stride_two.strides,
            "addressed_offsets": stride_offsets,
            "bounding_interval": stride_interval,
        },
        "unaddressed_holes_inside_same_interval": holes,
        "empty_zero_stride": {
            "shape": empty_zero_stride.shape,
            "strides": empty_zero_stride.strides,
            "element_count": int(empty_zero_stride.size),
            "addressed_elements": 0,
        },
        "assertion": "equal bounding intervals did not imply equal addressed elements",
    }


def run_one(name: str, function) -> dict[str, object]:
    try:
        result = function()
        return {"name": name, **result}
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        return {
            "name": name,
            "status": "FAIL",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def main() -> int:
    witnesses = [
        run_one("shared_tensor_buffer_with_delayed_thread_consumer", witness_shared_tensor_buffer),
        run_one("partial_os_file_write", witness_partial_file_write),
        run_one("strided_numpy_geometry", witness_strided_geometry),
    ]
    passed = sum(row["status"] == "PASS" for row in witnesses)
    result = {
        "schema": "scar.resource-ready-cpu-os-witnesses",
        "schema_version": 1,
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "torch": torch.__version__,
        "numpy": np.__version__,
        "scope": "three hand-written bounded witnesses; no SCAR recovery, GPU, or durability claim",
        "passed": passed,
        "total": len(witnesses),
        "status": "PASS" if passed == len(witnesses) else "FAIL",
        "witnesses": witnesses,
    }
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if passed == len(witnesses) else 1


if __name__ == "__main__":
    raise SystemExit(main())
