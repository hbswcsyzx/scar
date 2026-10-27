"""Byte-only decoder/repr check, no runtime hook or target capture."""
import dis
import hashlib
import json
from pathlib import Path
import sys

from scar.trace.code_snapshot import call_instruction

HERE=Path(__file__).resolve().parent
repr_calls=0
class Constant:
    def __repr__(self):
        global repr_calls
        repr_calls+=1
        return 'repr-probe'

def sample():
    return callback('marker')

code=sample.__code__
instructions=list(dis.get_instructions(code))
call=next(i for i in instructions if i.opname=='CALL')
load=next(i for i in instructions if i.opname=='LOAD_CONST')
constants=list(code.co_consts);constants[load.arg]=Constant()
custom=code.replace(co_consts=tuple(constants))
next(i for i in dis.get_instructions(custom) if i.opname=='CALL')
assert repr_calls==1  # Demonstrate the old formatter's user-code callback.
old_repr_calls=repr_calls;repr_calls=0
try:
    call_instruction(custom,call.offset)
except ValueError:
    unsupported_constant_rejected=True
else:
    raise AssertionError('structural-key unsupported-constant guard changed')
assert repr_calls==0
unpacks=0;original_unpack=dis._unpack_opargs;original_instructions=dis.get_instructions
def unpack(raw):
    global unpacks
    unpacks+=1
    return original_unpack(raw)
def forbidden(*args,**kwargs):
    raise AssertionError('production decoder must not resolve argval/argrepr')
dis._unpack_opargs=unpack;dis.get_instructions=forbidden
try:
    for _ in range(8):assert call_instruction(code,call.offset)==(call.opname,call.arg)
finally:
    dis._unpack_opargs=original_unpack;dis.get_instructions=original_instructions
assert unpacks==1
units=dis._inline_cache_entries.get('CALL',0)
raw=bytes([dis.opmap['RESUME'],0,dis.opmap['EXTENDED_ARG'],1,dis.opmap['CALL'],1]
          +[0,0]*units+[dis.opmap['RETURN_VALUE'],0])
extended=code.replace(co_code=raw)
expected=next(i for i in dis.get_instructions(extended) if i.opname=='CALL')
assert call_instruction(extended,expected.offset)==(expected.opname,expected.arg)==('CALL',257)
assert call_instruction(extended,expected.offset+2) is None  # Inline CACHE is not a CALL.
source=Path(dis.__file__)
result=dict(status='BYTE_ONLY_CALL_DECODER_PASS',runtime=sys.version,
    dis_source=dict(uri=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest()),
    original_get_instructions_repr_calls=old_repr_calls,new_decoder_repr_calls=repr_calls,
    unsupported_constant_rejected=unsupported_constant_rejected,
    same_call_site_requests=8,byte_only_decoder_scans=unpacks,extended_call_arg=expected.arg,
    inline_cache_not_instruction=True,capture_started=False,target_executed=False)
with (HERE/'RESULT.json').open('x') as stream:json.dump(result,stream,indent=2)
print(json.dumps(result))
