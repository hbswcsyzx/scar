"""Finite Python language evidence, independent of SCAR's model implementation.

Run only by root in conda lewm. No GPU, tracing backend, external workload,
native extension, install, source modification or arbitrary task scheduler.
"""
import hashlib
import inspect
import json
from pathlib import Path
import sys
import types


class YieldOnce:
    def __init__(self, marker):
        self.marker = marker

    def __await__(self):
        return (yield self.marker)


async def native_zero():
    return 23


async def native_two():
    first = await YieldOnce('first')
    second = await YieldOnce('second')
    return first, second


def generator_zero():
    if False:
        yield
    return 23


def generator_two():
    first = yield 'first'
    second = yield 'second'
    return first, second


async def outer(value):
    return await value


class ProtocolAwaitable:
    def __init__(self, iterator):
        self.iterator = iterator
        self.calls = 0

    def __await__(self):
        self.calls += 1
        return self.iterator


class CallFailure:
    def __init__(self):
        self.calls = 0

    def __await__(self):
        self.calls += 1
        raise RuntimeError('declared await method failure')


def close(value):
    method = getattr(value, 'close', None)
    if method is not None:
        method()


def immediate(name, value, expected, *, inner=None):
    frame = outer(value)
    try:
        try:
            yielded = frame.send(None)
        except StopIteration as error:
            result = {'kind': 'RETURN', 'value': error.value}
        except Exception as error:
            result = {'kind': 'RAISE', 'exception': type(error).__name__, 'message': str(error)}
        else:
            result = {'kind': 'SUSPEND', 'value': yielded}
        assert result['kind'] == expected[0], (name, result)
        assert result.get('exception', result.get('value')) == expected[1], (name, result)
        if hasattr(value, 'calls'):
            result['await_method_calls'] = value.calls
            assert value.calls == 1
        return {'case': name, **result}
    finally:
        close(frame)
        close(value)
        close(inner)


def two_cuts(name, value, expected_iterator):
    frame = outer(value)
    try:
        yielded = [frame.send(None)]
        owners = [frame.cr_await is expected_iterator]
        yielded.append(frame.send(17))
        owners.append(frame.cr_await is expected_iterator)
        try:
            frame.send(29)
        except StopIteration as error:
            result = error.value
        else:
            raise AssertionError('third send must complete this finite example')
        assert yielded == ['first', 'second'] and owners == [True, True]
        assert result == (17, 29)
        return {'case': name, 'yielded': yielded, 'cr_await_is_expected_iterator': owners,
                'return': result, 'await_method_calls': getattr(value, 'calls', None)}
    finally:
        close(frame)
        close(value)
        close(expected_iterator)


def main():
    original_code = generator_zero.__code__
    decorated_zero = types.coroutine(generator_zero)
    decorated_two = types.coroutine(generator_two)
    flag_change = {'same_function_object': decorated_zero is generator_zero,
        'code_object_replaced': original_code is not decorated_zero.__code__,
        'bytecode_equal': original_code.co_code == decorated_zero.__code__.co_code,
        'flags_before': original_code.co_flags, 'flags_after': decorated_zero.__code__.co_flags}
    assert flag_change['same_function_object'] and flag_change['code_object_replaced']
    assert flag_change['bytecode_equal']
    assert flag_change['flags_after'] == flag_change['flags_before'] | inspect.CO_ITERABLE_COROUTINE

    # Keep an ordinary, unflagged generator factory after decoration above.
    def ordinary():
        if False:
            yield
        return 23

    cases = [immediate('native-self-zero', native_zero(), ('RETURN', 23)),
             immediate('iterable-generator-self-zero', decorated_zero(), ('RETURN', 23)),
             immediate('ordinary-generator-direct-rejected', ordinary(), ('RAISE', 'TypeError'))]
    iterator = ordinary()
    cases.append(immediate('general-return-ordinary-generator', ProtocolAwaitable(iterator),
                           ('RETURN', 23), inner=iterator))
    for name, returned in (('native-coroutine', native_zero()),
                           ('iterable-generator-coroutine', decorated_zero()),
                           ('non-iterator', 7)):
        cases.append(immediate('general-return-' + name + '-rejected',
            ProtocolAwaitable(returned), ('RAISE', 'TypeError'), inner=returned))
    cases.append(immediate('await-method-own-failure', CallFailure(), ('RAISE', 'RuntimeError')))
    native, generated = native_two(), decorated_two()
    cases.append(two_cuts('native-self-two-cuts', native, native))
    cases.append(two_cuts('iterable-generator-self-two-cuts', generated, generated))
    ordinary_two_code = types.CodeType.replace(generator_two.__code__,
        co_flags=generator_two.__code__.co_flags & ~inspect.CO_ITERABLE_COROUTINE)
    ordinary_two = types.FunctionType(ordinary_two_code, globals())()
    cases.append(two_cuts('general-protocol-two-cuts', ProtocolAwaitable(ordinary_two), ordinary_two))

    body = native_two()
    wrapper = body.__await__()
    try:
        distinct, iterator_self = wrapper is not body, iter(wrapper) is wrapper
        assert distinct and iterator_self
        yielded = [next(wrapper), wrapper.send(17)]
        try:
            wrapper.send(29)
        except StopIteration as error:
            result = error.value
        else:
            raise AssertionError('explicit wrapper must complete')
        assert yielded == ['first', 'second'] and result == (17, 29)
        cases.append({'case': 'explicit-coroutine-await-wrapper', 'wrapper_is_not_body': distinct,
            'iter_wrapper_is_wrapper': iterator_self, 'yielded': yielded, 'return': result,
            'native_held_body_identity_observed': False})
    finally:
        close(wrapper)
        close(body)

    generator = decorated_zero()
    try:
        assert not hasattr(generator, '__await__')
        flagged_has_await = hasattr(generator, '__await__')
    finally:
        close(generator)
    here = Path(__file__).resolve().parent
    result = {'scope': 'finite native language evidence; no SCAR correctness/performance claim',
        'python': sys.version, 'executable': sys.executable,
        'base_revision': '0bbc6235992e89e2a5735287e94622cfe0755cf8',
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'plan_sha256': hashlib.sha256(Path('docs/M1_AWAIT_ACQUISITION_PLAN.md').read_bytes()).hexdigest(),
        'decorator_code_transition': flag_change, 'flagged_generator_has_await': flagged_has_await,
        'cases': cases, 'case_count': len(cases), 'gpu_used': False,
        'scar_ir_verified': False, 'transformation_authorized': False}
    output = here / 'native-evidence.json'
    with output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
