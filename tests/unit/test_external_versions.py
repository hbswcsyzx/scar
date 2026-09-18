import numpy as np
import torch

from scar.ir import StorageVersionRegistry


def test_numpy_alias_can_explicitly_invalidate_shared_tensor_storage():
    array = np.zeros(4, dtype=np.float32)
    tensor = torch.from_numpy(array)
    registry = StorageVersionRegistry()
    before = registry.token(tensor)
    array[0] = 1.0
    registry.mark_external_write(array)
    after = registry.token(tensor)
    assert after != before

