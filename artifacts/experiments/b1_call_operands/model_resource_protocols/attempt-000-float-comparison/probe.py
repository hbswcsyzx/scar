"""Small CPU/stdlib witnesses; no target execution, GPU context, or tensor dump."""
from pathlib import Path
import hashlib
import json
import os
import sys
import tempfile

import numpy as np
import torch


def file_witnesses():
    with tempfile.TemporaryDirectory(prefix="scar-resource-probe-") as raw:
        root = Path(raw)
        path = root / "source"
        alias = root / "alias"
        path.write_bytes(b"abcd")
        os.link(path, alias)
        first = os.open(path, os.O_RDONLY)
        duplicate = os.dup(first)
        independent = os.open(alias, os.O_RDONLY)
        try:
            os.read(first, 1)
            duplicate_offset = os.lseek(duplicate, 0, os.SEEK_CUR)
            independent_offset = os.lseek(independent, 0, os.SEEK_CUR)
            file_identity_equal = os.fstat(first).st_ino == os.fstat(independent).st_ino
        finally:
            for descriptor in (first, duplicate, independent):
                os.close(descriptor)
        with path.open("wb") as target:
            try:
                target.write(1)
            except TypeError as error:
                write_error = type(error).__name__
        return {
            "hardlink_file_identity_equal": file_identity_equal,
            "dup_offset_after_first_read": duplicate_offset,
            "independent_open_offset": independent_offset,
            "bad_write_exception": write_error,
            "content_size_after_open_truncate_and_bad_write": path.stat().st_size,
        }


def tensor_witnesses():
    array = np.zeros(4, dtype=np.float32)
    tensor = torch.from_numpy(array)
    before_version = tensor._version
    array[3] = 7
    numpy_alias = {
        "torch_version_unchanged": tensor._version == before_version,
        "tensor_last_element_changed": tensor[3].item() == 7,
        "same_device_to_returns_same_object": tensor.to("cpu") is tensor,
        "same_device_forced_copy_is_distinct": tensor.to("cpu", copy=True) is not tensor,
    }
    trainable = torch.ones(1, requires_grad=True)
    with torch.no_grad():
        no_grad_output = trainable * 2
    normal_output = trainable * 2
    rng = torch.Generator(device="cpu").manual_seed(23)
    rng_before = hashlib.sha256(rng.get_state().numpy().tobytes()).hexdigest()
    torch.rand(1, generator=rng)
    rng_after = hashlib.sha256(rng.get_state().numpy().tobytes()).hexdigest()
    layer = torch.nn.Linear(2, 2)
    old_weight = layer.weight[0, 0].item()
    incoming_weight = torch.full_like(layer.weight, old_weight + 1)
    try:
        layer.load_state_dict({"weight": incoming_weight, "bias": torch.zeros(3)})
    except RuntimeError as error:
        load_error = type(error).__name__
    return {
        "numpy_alias": numpy_alias,
        "no_grad_output_requires_grad": no_grad_output.requires_grad,
        "normal_output_requires_grad": normal_output.requires_grad,
        "rng_state_hash_changed": rng_before != rng_after,
        "partial_load_exception": load_error,
        "weight_was_written_despite_load_exception": layer.weight[0, 0].item() == old_weight + 1,
    }


sources = [
    Path(torch.__file__).parent / "cuda/streams.py",
    Path(torch.__file__).parent / "_tensor_docs.py",
    Path(torch.__file__).parent / "nn/modules/module.py",
    Path(torch.__file__).parent / "autograd/grad_mode.py",
    Path(torch.__file__).parent / "serialization.py",
]
result = {
    "scope": "small_cpu_stdlib_witnesses_only_not_graph_or_gpu_acceptance",
    "python": sys.version,
    "torch": torch.__version__,
    "cuda_build": torch.version.cuda,
    "cuda_initialized_before": torch.cuda.is_initialized(),
    "files": file_witnesses(),
    "tensors": tensor_witnesses(),
    "cuda_initialized_after": torch.cuda.is_initialized(),
    "source_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
}
Path(__file__).with_name("probe.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
