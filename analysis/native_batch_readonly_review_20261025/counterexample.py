"""One synthetic metadata check of identity-vs-unavailability ordering."""
from hashlib import sha256
import json
from pathlib import Path

from scar.trace.native_capture_batch import _unavailable_physical
from scar.ir.execution.native_port_protocol import replay_interfaces
from scar.trace.native_schema import PROVIDER_REVISION

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
wrong_span = 'scar-dispatch:wrong-nonce:7:1:span'
wrong_output = 'scar-dispatch:wrong-nonce:7:1:output'
source = {'provider_revision': PROVIDER_REVISION, 'pid': 7, 'nonce': 'correct-nonce',
    'first_sequence': 1, 'max_sequences': 1, 'nodes': [], 'physical': [],
    'dispatch': [
        {'index': 1, 'process_id': 7, 'sequence': 1, 'kind': 'DISPATCH_BEGIN',
         'operator': 'aten.empty.memory_format', 'marker': wrong_span, 'slot_gaps': []},
        {'index': 2, 'process_id': 7, 'sequence': 1, 'kind': 'DISPATCH_OUTPUT',
         'marker': wrong_output, 'slot_gaps': []},
        {'index': 3, 'process_id': 7, 'sequence': 1, 'kind': 'DISPATCH_END',
         'outcome': 'RETURNED', 'span_enter_returned': True, 'output_marker': wrong_output},
    ]}
unavailable = _unavailable_physical(source)
assert unavailable['reason'] == 'PHYSICAL_MARKER_UNAVAILABLE'
try:
    replay_interfaces(source)
except ValueError as error:
    assert 'normal dispatch group marker mismatch' in str(error)
    rejection = {'type': type(error).__name__, 'detail': str(error)}
else:
    raise AssertionError('synthetic wrong-nonce group did not reject')
files = ['scar/trace/native_capture_batch.py', 'scar/ir/execution/native_port_protocol.py']
summary = {'status': 'SYNTHETIC_ORDERING_COUNTEREXAMPLE_CONFIRMED',
    'source_sha256': {name: sha256((ROOT / name).read_bytes()).hexdigest() for name in files},
    'availability_precheck_result': unavailable, 'independent_identity_rejection': rejection,
    'batch_path': 'availability result is consumed before replay_interfaces; classification continues',
    'raw_capture_reads': 0, 'archive_chunk_reads': 0, 'full_batch_gate_executed': False,
    'target_executed': False, 'code_review_is_full_native_verified': False}
with (HERE / 'counterexample.json').open('x') as stream:
    json.dump(summary, stream, sort_keys=True, indent=2); stream.write('\n')
print(json.dumps(summary, sort_keys=True))
