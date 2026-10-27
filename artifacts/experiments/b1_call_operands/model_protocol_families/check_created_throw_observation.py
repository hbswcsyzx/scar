"""Read saved observations only; do not execute the original witness or tests."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    script = HERE / 'created_throw_witness.py'
    raw = HERE / 'created_throw_witness.json'
    result = json.loads(raw.read_text())
    assert result['script_sha256'] == hashlib.sha256(script.read_bytes()).hexdigest()
    cases = result['cases']
    assert len(cases) == 6
    expected = [
        ('generator', 'instance', 'GEN_CLOSED', 'ValueError', None, [], None),
        ('generator', 'invalid', 'GEN_CREATED', 'TypeError', None, [], 'item'),
        ('generator', 'constructor_failure', 'GEN_CLOSED', 'RuntimeError', None,
         ['exception-constructor'], None),
        ('generator', 'stop_iteration', 'GEN_CLOSED', 'StopIteration', None, [], None),
        ('coroutine', 'instance', 'CORO_CLOSED', 'ValueError', None, [], None),
        ('async_generator', 'instance', 'AGEN_CLOSED', 'ValueError', None, [], None),
    ]
    for row, observation in zip(cases, expected):
        assert tuple(row[key] for key in ('family', 'mode', 'after_throw', 'error_type',
                      'cause_type', 'normalization_log', 'can_start_after_failure')) == observation
        assert row['body_log_at_throw'] == []
        assert row['cleanup_state'].endswith('_CLOSED')
    assert cases[5]['request_created_state'] == 'AGEN_CREATED'
    assert not any(result[key] for key in ('family_model_implemented',
        'source_runtime_correspondence_verified', 'transformation_authorized'))
    print(json.dumps({'status': 'SAVED_OBSERVATIONS_VERIFIED', 'observations': 6,
        'witness_executions_started': 0, 'tests_started': 0,
        'original_witness_exit_code': 1, 'original_assertion_rejected': True,
        'raw_sha256': hashlib.sha256(raw.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
