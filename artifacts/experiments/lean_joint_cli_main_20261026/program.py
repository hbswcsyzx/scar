import torch
import sample
host = torch.ones(2)
value = host.to("cuda")
result = sample.run(sample.Box(), value, (value,))
assert result.shape == value.shape
print("JOINT_GPU_TARGET_RETURNED")
