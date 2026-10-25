"""Pure in-memory JSON token boundary checks; no original capture input."""
import io
import json
from scar.trace.native_capture_batch import _JSONStream


def complete(raw):
    parser = _JSONStream(io.BytesIO(raw), 4_000_000)
    result = parser.value()
    assert parser.peek() == '', 'trailing data'
    return result


checks = []
for spelling in ('-0.25', '1e-10', '-1.25E+12', '0.125e-7'):
    token = spelling.encode()
    for split in range(1, len(token)):
        raw = b' ' * (65_536 - split) + token
        assert complete(raw) == json.loads(token)
        checks.append({'kind': 'numeric_boundary', 'token': spelling, 'split': split})
for text in ('é', '中', '🙂', 'aé中🙂z'):
    token = json.dumps(text, ensure_ascii=False).encode()
    for split in range(1, len(token)):
        raw = b' ' * (65_536 - split) + token
        assert complete(raw) == text
        checks.append({'kind': 'utf8_boundary', 'text': text, 'split': split})
for raw in (b'1e', b'1.', b'-1e+', b'{"a":1}garbage', b'{"a":1,"a":2}',
            b'{"a":[1,2', b'"unfinished', b'\xc2\xa01', b'1\xc2\xa0'):
    try:
        complete(raw)
    except (ValueError, AssertionError, UnicodeDecodeError):
        pass
    else:
        raise AssertionError('malformed complete JSON accepted: ' + repr(raw))
    checks.append({'kind': 'rejection', 'raw_hex': raw.hex()})
print(json.dumps({'status': 'PURE_PARSER_CHECK_PASS', 'checks': checks,
                  'original_raw_reads': 0, 'archive_chunk_reads': 0, 'full_gate_run': False},
                 ensure_ascii=False, sort_keys=True, indent=2))
