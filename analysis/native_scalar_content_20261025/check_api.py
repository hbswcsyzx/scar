"""Small synthetic metadata/literal API checks; never open capture artifacts."""
from enum import IntEnum
import hashlib
import json
from pathlib import Path
import signal
import sys
import time

from scar.ir.literals import PythonLiteral
from scar.ir.record_codec import encode, decode
from scar.trace.native_scalar_content import decode_pinned_scalar, ScalarFrontier
from scar.trace.native_schema import PROVIDER_REVISION

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
started = time.monotonic()


def expired(signum, frame):
    raise TimeoutError('small scalar metadata/API check exceeded 60 seconds')


def call(tag, kind, value, real=None, revision=PROVIDER_REVISION):
    return decode_pinned_scalar(revision, tag, kind, value,
        formal_real_kind=kind if real is None else real)


class ExampleEnum(IntEnum):
    ONE = 1


class IntSubclass(int):
    pass


signal.signal(signal.SIGALRM, expired)
signal.setitimer(signal.ITIMER_REAL, 60)
observed = []
try:
    positives = [('none', 'None', 'NoneType', '<None>', None),
        ('optional-none', 'None', 'OptionalType', '<None>', None),
        ('bool', 'Bool', 'BoolType', False, False),
        ('int64-min', 'Int', 'IntType', -(2**63), -(2**63)),
        ('int64-max', 'Int', 'IntType', 2**63 - 1, 2**63 - 1),
        ('string-controls', 'String', 'StringType', 'a\x00\n\\"z', 'a\x00\n\\"z'),
        ('empty-string', 'String', 'StringType', '', '')]
    for label, tag, kind, payload, expected in positives:
        result = call(tag, kind, payload)
        assert result.frontier is None
        restored = decode(PythonLiteral, encode(result.literal))
        actual = restored.to_python()
        assert restored == result.literal and type(actual) is type(expected) and actual == expected
        observed.append({'case': label, 'literal': encode(result.literal), 'builtin_type': result.builtin_type})
    negatives = [
        ('bool-is-not-int', 'Int', 'IntType', True, None, ScalarFrontier.PAYLOAD_TYPE),
        ('int-is-not-bool', 'Bool', 'BoolType', 1, None, ScalarFrontier.PAYLOAD_TYPE),
        ('enum-payload', 'Int', 'IntType', ExampleEnum.ONE, None, ScalarFrontier.PAYLOAD_TYPE),
        ('subclass-payload', 'Int', 'IntType', IntSubclass(1), None, ScalarFrontier.PAYLOAD_TYPE),
        ('enum-erased-formal', 'Int', 'IntType', 6, 'ScalarTypeType', ScalarFrontier.NON_BUILTIN_FORMAL),
        ('symint-erased-formal', 'Int', 'IntType', 7, 'SymIntType', ScalarFrontier.SYMBOLIC),
        ('symbolic-tag', 'SymInt', 'IntType', '<SymInt>', None, ScalarFrontier.SYMBOLIC),
        ('int64-overflow', 'Int', 'IntType', 2**63, None, ScalarFrontier.INT64_RANGE),
        ('int64-underflow', 'Int', 'IntType', -(2**63)-1, None, ScalarFrontier.INT64_RANGE),
        ('number-string', 'Int', 'IntType', '17', None, ScalarFrontier.PAYLOAD_TYPE),
        ('none-json-null', 'None', 'NoneType', None, None, ScalarFrontier.NONE_SENTINEL),
        ('none-wrong-sentinel', 'None', 'NoneType', 'None', None, ScalarFrontier.NONE_SENTINEL),
        ('none-not-string', 'None', 'StringType', '<None>', None, ScalarFrontier.FORMAL_KIND),
        ('double-finite', 'Double', 'FloatType', 1.0, None, ScalarFrontier.DOUBLE_PRECISION),
        ('double-negative-zero', 'Double', 'FloatType', -0.0, None, ScalarFrontier.DOUBLE_PRECISION),
        ('double-nonfinite', 'Double', 'FloatType', float('inf'), None, ScalarFrontier.NONFINITE),
        ('double-nan', 'Double', 'FloatType', float('nan'), None, ScalarFrontier.NONFINITE),
        ('double-stringified', 'Double', 'FloatType', 'inf', None, ScalarFrontier.DOUBLE_STRINGIFIED),
        ('nonascii', 'String', 'StringType', 'é', None, ScalarFrontier.STRING_ENCODING),
        ('surrogate', 'String', 'StringType', '\ud800', None, ScalarFrontier.STRING_ENCODING),
        ('string-budget', 'String', 'StringType', 'x' * 1_048_577, None, ScalarFrontier.PAYLOAD_BUDGET),
        ('tensor', 'Tensor(float)', 'TensorType', [1, 2, 0, 1, 4, 'cpu'], None, ScalarFrontier.TENSOR_REFERENCE),
        ('empty-container', 'List[Int]', 'ListType', [], None, ScalarFrontier.CONTAINER),
        ('unknown-tag', 'Unknown', 'IntType', 1, None, ScalarFrontier.PROVIDER_TAG),
    ]
    for label, tag, kind, payload, real, expected in negatives:
        result = call(tag, kind, payload, real)
        assert result.frontier is expected and result.literal is None and result.builtin_type is None
        observed.append({'case': label, 'frontier': result.frontier.value})
    changed = call('Int', 'IntType', 3, revision='0' * 40)
    assert changed.frontier is ScalarFrontier.PROVIDER_REVISION
    observed.append({'case': 'provider-revision', 'frontier': changed.frontier.value})
    # The pinned parser is used only on one synthetic schema. No dispatch/raw
    # inputs or target modules are imported or executed by this check.
    import torch
    assert torch.version.git_version == PROVIDER_REVISION
    schema = torch._C.parse_schema('example::scalar(int value, bool flag, str name, ScalarType dtype, SymInt count, float scale, int? maybe=None) -> int')
    formals = [{'name': a.name, 'kind': a.type.kind(), 'type': str(a.type),
        'real_type': str(a.real_type), 'real_kind': a.real_type.kind()} for a in schema.arguments]
    dtype = next(row for row in formals if row['name'] == 'dtype')
    symbolic = next(row for row in formals if row['name'] == 'count')
    assert dtype['kind'] == 'IntType' and dtype['real_kind'] == 'ScalarTypeType'
    assert symbolic['kind'] == 'IntType' and symbolic['real_type'] == 'int' and symbolic['real_kind'] == 'SymIntType'
    paths = [ROOT / 'scar/trace/native_scalar_content.py', ROOT / 'docs/NATIVE_SCALAR_CONTENT_CONTRACT.md', Path(__file__).resolve()]
    summary = {'status': 'PASS_PURE_METADATA_API_CHECKS', 'cases': observed,
        'case_count': len(observed), 'synthetic_schema_formals': formals,
        'provider_revision': PROVIDER_REVISION,
        'sources': [{'path': str(p), 'bytes': p.stat().st_size,
            'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths],
        'elapsed_seconds': time.monotonic() - started, 'raw_capture_reads': 0,
        'target_executed': False, 'code_witness_compile_performed': False,
        'owned_native_scalar_resolver_executed': False, 'content_chain_closed': False,
        'graph_records_created': False, 'first_stage_complete': False}
    output_name = sys.argv[1] if len(sys.argv) == 2 else 'summary.json'
    if Path(output_name).name != output_name or not output_name.endswith('.json'):
        raise ValueError('check output must be a local JSON filename')
    with (HERE / output_name).open('x') as stream:
        json.dump(summary, stream, sort_keys=True, ensure_ascii=False, indent=2); stream.write('\n')
    print(json.dumps({'status': summary['status'], 'case_count': len(observed),
        'elapsed_seconds': summary['elapsed_seconds']}, sort_keys=True))
finally:
    signal.setitimer(signal.ITIMER_REAL, 0)
