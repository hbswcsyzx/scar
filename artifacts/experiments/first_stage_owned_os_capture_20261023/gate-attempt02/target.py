"""Owned CPU-only fixture; no application/workload-specific modeling rules."""
import ctypes
import platform
import time
import torch


torch.set_num_threads(1)
def exercise(x):
    return (x @ x).sum()

x=torch.arange(4,dtype=torch.float32).reshape(2,2)
y=exercise(x)
assert y.shape==torch.Size([])
# Real safe identity-control invocations which the old class filter omitted.
if platform.machine()=='x86_64':
    libc=ctypes.CDLL(None,use_errno=True)
    libc.syscall.restype=ctypes.c_long
    assert libc.syscall(272,0)==0
    assert libc.syscall(436,ctypes.c_uint(0xffffffff),ctypes.c_uint(0xffffffff),0)==0
time.sleep(0.02)
print('owned CPU target completed')
