import json
import os
from pathlib import Path
import torch

x = torch.ones((), device='cpu')
for _ in range(256):
    x = x + 1
torch.cat([x.reshape(1), x.reshape(1)])
exception_type = None
try:
    torch.ops.aten.cat.default([], 0)
except ValueError as error:
    exception_type = type(error).__name__
assert exception_type == 'ValueError' and x.device.type == 'cpu'
Path(os.environ['SCAR_MEMBERSHIP_PROBE_RESULT']).write_text(json.dumps({
    'CPU': True, 'loop_iterations': 256, 'expected_exception_type': exception_type,
    'process_id': os.getpid(), 'target_exit_intended': 0}))
