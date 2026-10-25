"""Bounded pure syntax/decoder API check; no target, capture or Torch import."""
import ast
from hashlib import sha256
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[3]
SOURCES = ('scar/trace/native_scalar_content.py', 'scar/ir/execution/native_port_protocol.py',
           'scar/trace/native_protocol.py', 'scar/trace/native_capture_batch.py')
receipts = []
for name in SOURCES:
    raw = (BASE / name).read_bytes()
    ast.parse(raw, filename=name)
    receipts.append({'path': name, 'bytes': len(raw), 'sha256': sha256(raw).hexdigest()})

from scar.trace.native_scalar_content import (decode_pinned_scalar, ScalarFrontier,
    PINNED_SCALAR_PROVIDER_REVISION as REV, SCALAR_CONTENT_PROFILE_V1, SCALAR_CONTENT_PROFILE_V2)
from scar.ir.execution.native_port_protocol import (SCALAR_INPUT_CAPABILITY, SCALAR_INPUT_CAPABILITY_V2,
    _scalar_input, NativePortEvidence)
from scar.trace.native_capture_batch import bind_native_capture_model_batches

assert SCALAR_INPUT_CAPABILITY == SCALAR_CONTENT_PROFILE_V1
assert SCALAR_INPUT_CAPABILITY_V2 == SCALAR_CONTENT_PROFILE_V2
assert callable(NativePortEvidence.scalar_values)
count = 0

def decode(tag, value, kind='NumberType', real='NumberType', profile=SCALAR_INPUT_CAPABILITY_V2):
    global count
    count += 1
    return decode_pinned_scalar(REV, tag, kind, value, formal_real_kind=real, profile=profile)

integer = decode('Int', 1)
boolean = decode('Bool', False)
assert integer.literal.kind.value == 'int' and integer.literal.payload == '1'
assert boolean.literal.kind.value == 'bool' and boolean.literal.payload is False
assert integer.builtin_type == 'builtins.int' and boolean.builtin_type == 'builtins.bool'
assert decode('Int', 1, profile=SCALAR_INPUT_CAPABILITY).frontier is ScalarFrontier.NON_BUILTIN_FORMAL
assert decode_pinned_scalar(REV, 'Int', 'NumberType', 1,
    formal_real_kind='NumberType').frontier is ScalarFrontier.NON_BUILTIN_FORMAL
assert decode('Int', True).frontier is ScalarFrontier.PAYLOAD_TYPE
assert decode('Int', 1, 'IntType', 'ScalarTypeType').frontier is ScalarFrontier.NON_BUILTIN_FORMAL
assert decode('Int', 1, 'IntType', 'SymIntType').frontier is ScalarFrontier.SYMBOLIC
for tag, value in (('Device', 'cpu'), ('Enum', '<Enum>'), ('None', '<None>'),
                   ('String', '1'), ('Double', 1.0)):
    assert decode(tag, value).frontier is ScalarFrontier.NUMBER_TAG
assert decode('GenericList[]', []).frontier is ScalarFrontier.CONTAINER
assert decode('Int', 0, 'IntType', 'IntType').literal.payload == '0'
assert decode('None', '<None>', 'OptionalType', 'OptionalType').literal.kind.value == 'none'

# Exercise the schema-leaf handoff without importing/executing Torch. The
# actual pinned parser and live owned source are independently checked by gate.
class Kind:
    def kind(self): return 'NumberType'
class Formal:
    type = Kind()
    real_type = Kind()
selected = _scalar_input({'path': [0], 'type': 'Int', 'value': 1}, Formal(), REV,
                         profile=SCALAR_INPUT_CAPABILITY_V2)
assert selected['formal_kind'] == selected['formal_real_kind'] == 'NumberType'
assert selected['literal']['payload'] == '1' and selected['frontier'] is None
assert 'torch' not in sys.modules
result = {'status': 'PASS_PURE_SYNTAX_API', 'sources': receipts, 'decoder_calls': count + 2,
          'original_formal_preserved': True, 'V1_default_still_strict': True,
          'builtin_type_is_literal_representation_only': True,
          'primary_contract_receipt': 'analysis/native_scalar_union_plan_20261025/receipt.json',
          'runtime_kind_distribution': 'NOT_MEASURED', 'capture_reads': 0, 'target_runs': 0,
          'owned_native_producer_runs': 0, 'torch_imports': 0}
print(json.dumps(result, sort_keys=True, indent=2))
