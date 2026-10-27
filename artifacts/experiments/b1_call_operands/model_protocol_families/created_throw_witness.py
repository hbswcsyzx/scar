"""Bounded CPython startup-throw observations; no SCAR, torch or external IO."""
import hashlib
import inspect
import json
from pathlib import Path
import sys


def make(family, log):
    def generator():
        try:
            log.append('body-enter')
            yield 'item'
        finally:
            log.append('body-finally')

    async def coroutine():
        try:
            log.append('body-enter')
            return 'done'
        finally:
            log.append('body-finally')

    async def async_generator():
        try:
            log.append('body-enter')
            yield 'item'
        finally:
            log.append('body-finally')

    return {'generator': generator, 'coroutine': coroutine,
            'async_generator': async_generator}[family]()


def observe(family, mode):
    body_log, normalization = [], []
    body = make(family, body_log)
    state = {'generator': inspect.getgeneratorstate,
             'coroutine': inspect.getcoroutinestate,
             'async_generator': inspect.getasyncgenstate}[family]

    class ConstructorFailure(Exception):
        def __init__(self):
            normalization.append('exception-constructor')
            raise RuntimeError('controlled constructor failure')

    argument = {'instance': ValueError('injected'), 'invalid': 42,
                'constructor_failure': ConstructorFailure,
                'stop_iteration': StopIteration('injected stop')}[mode]
    before = state(body)
    request_created_state = None
    caught = None
    cause = None
    try:
        if family == 'async_generator':
            request = body.athrow(argument)
            request_created_state = state(body)
            request.send(None)
        else:
            body.throw(argument)
    except BaseException as error:
        caught = type(error).__name__
        cause = None if error.__cause__ is None else type(error.__cause__).__name__
    after, observed_body_log = state(body), list(body_log)
    can_start_after_failure = None
    if after.endswith('_CREATED') and family == 'generator':
        can_start_after_failure = next(body)
    if family == 'async_generator':
        try:
            body.aclose().send(None)
        except StopIteration:
            pass
    else:
        body.close()
    return {'family': family, 'mode': mode, 'before': before,
            'request_created_state': request_created_state, 'after_throw': after,
            'error_type': caught, 'cause_type': cause,
            'body_log_at_throw': observed_body_log, 'normalization_log': normalization,
            'can_start_after_failure': can_start_after_failure,
            'cleanup_log': list(body_log), 'cleanup_state': state(body)}


def main():
    out = Path(__file__).with_suffix('.json')
    if out.exists():
        raise RuntimeError('Original observation may not be overwritten')
    cases = [observe(family, mode) for family, mode in (
        ('generator', 'instance'), ('generator', 'invalid'),
        ('generator', 'constructor_failure'), ('generator', 'stop_iteration'),
        ('coroutine', 'instance'), ('async_generator', 'instance'))]
    result = {'schema': 'scar.created-throw-language-witness',
        'python': sys.version, 'implementation': sys.implementation.name,
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope': 'Six controlled stdlib CPU observations; no SCAR, torch, pytest, target workload or compiler invocation.',
        'cases': cases, 'family_model_implemented': False,
        'source_runtime_correspondence_verified': False,
        'transformation_authorized': False}
    out.write_text(json.dumps(result, indent=2) + '\n')
    assert all(not case['body_log_at_throw'] for case in cases)
    assert all(cases[index]['after_throw'].endswith('_CREATED')
               and cases[index]['can_start_after_failure'] == 'item' for index in (1, 2))
    assert all(cases[index]['after_throw'].endswith('_CLOSED') for index in (0, 3, 4, 5))
    assert cases[2]['normalization_log'] == ['exception-constructor']
    assert cases[3]['error_type'] == 'RuntimeError' and cases[3]['cause_type'] == 'StopIteration'
    print(json.dumps({'observations': len(cases), 'bounded_assertions': 'PASS', 'report': str(out)}))


if __name__ == '__main__':
    main()
