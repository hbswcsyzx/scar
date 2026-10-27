"""A small original CUDA/autograd program; no Tensor values are serialized."""
import json
from pathlib import Path
import sys
import time

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent / "project"))
from entry import run


def main():
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this experiment")
    torch.cuda.init()
    torch.cuda.reset_peak_memory_stats()
    cases = []
    for mode in ("distinct", "shared"):
        left = torch.ones((2, 2), device="cuda", requires_grad=True)
        right = left if mode == "shared" else torch.ones((2, 2), device="cuda", requires_grad=True)
        torch.cuda.synchronize()
        started = time.perf_counter()
        returned = run(left, right)
        assert returned is left
        assert returned.requires_grad and returned.is_leaf and returned.grad_fn is None
        assert returned.grad is None and right.grad is None
        loss = returned.sum()
        assert loss.requires_grad and loss.grad_fn is not None
        loss.backward()
        torch.cuda.synchronize()
        assert left.grad is not None and left.grad.device.type == "cuda"
        assert tuple(left.grad.shape) == tuple(left.shape)
        assert not left.grad.requires_grad
        if mode == "distinct":
            assert right is not left and right.grad is None
        else:
            assert right is left and right.grad is left.grad
        cases.append({
            "mode": mode, "returned_is_left": returned is left,
            "inputs_share_object": left is right,
            "left_requires_grad": left.requires_grad,
            "right_requires_grad": right.requires_grad,
            "returned_is_leaf": returned.is_leaf,
            "returned_grad_fn_absent": returned.grad_fn is None,
            "loss_has_grad_fn": loss.grad_fn is not None,
            "backward_completed": True,
            "left_grad_present": left.grad is not None,
            "right_grad_present": right.grad is not None,
            "left_grad_on_cuda": left.grad.device.type == "cuda",
            "left_grad_requires_grad": left.grad.requires_grad,
            "elapsed_seconds": time.perf_counter() - started,
        })
    print(json.dumps({
        "status": "CUDA_AUTOGRAD_COMPLETED",
        "torch_version": torch.__version__, "torch_cuda_version": torch.version.cuda,
        "python_version": sys.version, "cuda_device_name": torch.cuda.get_device_name(0),
        "cuda_device_index": torch.cuda.current_device(),
        "cuda_peak_memory_allocated_bytes": torch.cuda.max_memory_allocated(),
        "cuda_peak_memory_reserved_bytes": torch.cuda.max_memory_reserved(),
        "tensor_values_saved": False, "cases": cases,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
