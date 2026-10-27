"""Authorized no-state diagnostic child; Linux amd64 only."""
import ctypes
import json
import platform

assert platform.machine()=='x86_64'
libc=ctypes.CDLL(None,use_errno=True)
libc.syscall.restype=ctypes.c_long
results=[]
for name,number,args in [('unshare',272,[ctypes.c_ulong(0)]),
                         ('close_range',436,[ctypes.c_uint(0xffffffff),ctypes.c_uint(0xffffffff),ctypes.c_uint(0)])]:
    ctypes.set_errno(0)
    result=libc.syscall(ctypes.c_long(number),*args)
    results.append({'syscall':name,'return':result,'errno':ctypes.get_errno(),
        'arguments':[0] if name=='unshare' else [0xffffffff,0xffffffff,0]})
print(json.dumps({'probe':'no-state-actual-syscalls','results':results},sort_keys=True))
