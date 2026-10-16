"""Generated synchronous CFGs are checked against independent Python runs."""
from dataclasses import dataclass, field, replace

import pytest

from scar.analysis.program_lowering import lower_source
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.program.model import TerminatorKind
from scar.ir.program.structured import PythonProtocol, PythonProtocolKind
from scar.ir.program.validation import require_valid
from scar.ir.semantics_v2 import Opcode
from tests.fixtures.structured_program_oracle import freeze, run_core, run_python


@dataclass
class Case:
    args: tuple
    globals: dict = field(default_factory=dict)
    observe: object = lambda: None
    identities: tuple = ()
    sentinel: BaseException | None = None


def normalized(value, case):
    for item, name in case.identities:
        if value is item:
            return ('identity', name)
    if type(value) is tuple:
        return tuple(normalized(item, case) for item in value)
    return freeze(value)


def signature(outcome, case):
    if outcome.status == 'RETURN':
        payload = normalized(outcome.value, case)
    elif outcome.status == 'RAISE':
        payload = (type(outcome.exception).__module__, type(outcome.exception).__qualname__,
                   normalized(outcome.exception.args, case), outcome.exception is case.sentinel)
    else:
        payload = outcome.detail
    return outcome.status, payload, outcome.observation


def compare(tmp_path, source, factory, *, mutate=None):
    path = tmp_path / 'original.py'
    path.write_text(source)
    program = lower_source(path, 'f', profile=BodyLoweringProfile.STRUCTURED_BODY)
    assert program.graph is not None, program.metadata.gaps
    assert program.structured is not None
    require_valid(program.graph)
    python_case, core_case = factory(), factory()
    expected = run_python(source, python_case.args, globals=python_case.globals,
                          observe=python_case.observe, filename=str(path))
    executed = mutate(program) if mutate else program
    actual = run_core(executed, core_case.args, globals=core_case.globals, observe=core_case.observe)
    assert actual.status in {'RETURN', 'RAISE'}, actual
    assert signature(expected, python_case) == signature(actual, core_case)
    assert actual.post_world
    assert all(world.observation == actual.observation for world in actual.post_world)
    assert program.structured.frame_rules.effects.value == 'UNKNOWN'
    assert program.structured.frame_rules.release.value == 'NOT_GUARANTEED'
    return program, expected, actual


@pytest.mark.parametrize('value', [None, 7, 'literal'])
def test_echo_uses_graph_ports_and_preserves_actual_none_binding(tmp_path, value):
    compare(tmp_path, 'def f(x):\n    return x\n', lambda: Case((value,)))


def test_local_rebinding_and_alias_return_follow_binding_tokens(tmp_path):
    def factory():
        left, right = object(), object()
        return Case((left, right), identities=((left, 'left'), (right, 'right')))
    compare(tmp_path, 'def f(x, y):\n    alias = x\n    x = y\n    return alias\n', factory)


@pytest.mark.parametrize('flag', [False, True])
def test_if_chooses_actual_predecessor_not_union_of_static_origins(tmp_path, flag):
    def factory():
        left, right = object(), object()
        return Case((flag, left, right), identities=((left, 'left'), (right, 'right')))
    compare(tmp_path, ('def f(flag, left, right):\n'
                       '    if flag:\n        selected = left\n'
                       '    else:\n        selected = right\n    return selected\n'), factory)


def test_unbound_branch_does_not_fall_back_to_same_named_global(tmp_path):
    compare(tmp_path, 'def f(flag):\n    if flag:\n        local = None\n    return local\n',
            lambda: Case((False,), globals={'local':'global must not be read'}))


@pytest.mark.parametrize('count', [0, 1, 4])
def test_while_zero_and_multiple_visits_recheck_condition_and_keep_else_order(tmp_path, count):
    def factory():
        events, cursor = [], [0]
        def test():
            answer = cursor[0] < count
            events.append(('test', answer))
            cursor[0] += 1
            return answer
        def emit(value):
            events.append(('body', value))
            return value
        return Case((test, emit), observe=lambda: events)
    source = ('def f(test, emit):\n    i = 0\n    while test():\n'
              '        i = i + 1\n        emit(i)\n'
              '    else:\n        emit("else")\n    return i\n')
    _, expected, actual = compare(tmp_path, source, factory)
    assert expected.value == count
    assert len([event for event in actual.observation if event[0]=='test']) == count + 1
    assert actual.observation[-1] == ('body', 'else')


def test_while_break_continue_skip_only_their_own_control_paths(tmp_path):
    def factory():
        events, cursor = [], [0]
        def test():
            cursor[0] += 1
            events.append(('test', cursor[0]))
            return cursor[0] < 6
        def skip(value):
            events.append(('skip', value)); return value == 2
        def stop(value):
            events.append(('stop', value)); return value == 3
        def emit(value):
            events.append(('emit', value))
        return Case((test, skip, stop, emit), observe=lambda:events)
    source = ('def f(test, skip, stop, emit):\n    i = 0\n    while test():\n'
              '        i = i + 1\n        if skip(i):\n            continue\n'
              '        if stop(i):\n            break\n        emit(i)\n'
              '    else:\n        emit("else")\n    emit("after")\n    return i\n')
    _, expected, actual = compare(tmp_path, source, factory)
    assert expected.value == 3
    assert ('stop',2) not in actual.observation
    assert ('emit','else') not in actual.observation
    assert actual.observation[-1] == ('emit','after')


class OriginalError(Exception):
    pass


def test_truth_side_effect_then_raise_preserves_exception_and_its_poststate(tmp_path):
    def factory():
        events, count = [], [0]
        error = OriginalError('truth failed')
        class Truth:
            def __bool__(self):
                count[0] += 1
                events.append(('truth',count[0]))
                if count[0] == 2:
                    raise error
                return True
        def test():
            events.append(('test',)); return Truth()
        def body():
            events.append(('body',))
        return Case((test,body), observe=lambda:events, sentinel=error)
    source = ('def f(test, body):\n    while test():\n        body()\n'
              '    else:\n        body()\n    return None\n')
    _, expected, _ = compare(tmp_path,source,factory)
    assert expected.status == 'RAISE'
    assert expected.observation == (('test',),('truth',1),('body',),('test',),('truth',2))


@pytest.mark.parametrize('items', [[], [None], [1], [1,2,3]])
def test_for_target_zero_trip_unbound_and_actual_none_item_are_distinct(tmp_path,items):
    compare(tmp_path,'def f(xs):\n    for item in xs:\n        pass\n    return item\n',
            lambda:Case((list(items),)))


def test_for_zero_trip_preserves_existing_binding(tmp_path):
    compare(tmp_path,'def f(xs, initial):\n    item = initial\n    for item in xs:\n        pass\n    return item\n',
            lambda:Case(([], 'initial')))


@pytest.mark.parametrize('stop_at', [None, 2])
def test_for_continue_break_and_else_preserve_actual_iteration_order(tmp_path, stop_at):
    def factory():
        events = []
        def skip(item):
            events.append(('skip', item)); return item == 1
        def stop(item):
            events.append(('stop', item)); return item == stop_at
        def emit(item):
            events.append(('emit', item))
        return Case(([1, 2, 3], skip, stop, emit), observe=lambda: events)
    source = ('def f(xs, skip, stop, emit):\n    item = None\n    for item in xs:\n'
              '        if skip(item):\n            continue\n'
              '        if stop(item):\n            break\n        emit(item)\n'
              '    else:\n        emit("else")\n    emit("after")\n    return item\n')
    _, expected, _ = compare(tmp_path, source, factory)
    assert ('stop', 1) not in expected.observation
    assert (('emit', 'else') in expected.observation) is (stop_at is None)
    assert expected.observation[-1] == ('emit', 'after')


def test_nested_loop_break_does_not_terminate_outer_loop_or_run_inner_else(tmp_path):
    def factory():
        events = []
        def stop(item):
            events.append(('stop', item)); return item == 2
        def emit(outer, inner):
            events.append(('emit', outer, inner))
        return Case(([10, 20], [1, 2, 3], stop, emit), observe=lambda: events)
    source = ('def f(outer_items, inner_items, stop, emit):\n'
              '    for outer in outer_items:\n        for inner in inner_items:\n'
              '            if stop(inner):\n                break\n'
              '            emit(outer, inner)\n        else:\n            emit(outer, "inner-else")\n'
              '        emit(outer, "after-inner")\n    else:\n        emit("outer", "else")\n'
              '    return outer\n')
    _, expected, _ = compare(tmp_path, source, factory)
    assert expected.value == 20
    assert expected.observation == (('stop', 1), ('emit', 10, 1), ('stop', 2),
                                    ('emit', 10, 'after-inner'), ('stop', 1),
                                    ('emit', 20, 1), ('stop', 2),
                                    ('emit', 20, 'after-inner'), ('emit', 'outer', 'else'))


class StopSubclass(StopIteration):
    pass


class SpoofedStop(Exception):
    @property
    def __class__(self):
        return StopIteration


@pytest.mark.parametrize('finish', ['exhausted','subclass','error','spoofed'])
def test_iterator_protocol_uses_real_exception_type_and_preserves_failed_next_state(tmp_path,finish):
    def factory():
        events = []
        error = {'exhausted':StopIteration('not an item'), 'subclass':StopSubclass('not an item'),
                 'error':OriginalError('next failed'), 'spoofed':SpoofedStop('not exhausted')}[finish]
        class Iterator:
            cursor = 0
            def __iter__(self):
                events.append(('iter',)); return self
            def __next__(self):
                self.cursor += 1
                events.append(('next',self.cursor))
                if self.cursor == 3:
                    raise error
                return self.cursor
        def emit(value):
            events.append(('emit',value))
        return Case((Iterator(),emit),observe=lambda:events,sentinel=error)
    source = ('def f(xs, emit):\n    for item in xs:\n        emit(item)\n'
              '    else:\n        emit("else")\n    return item\n')
    _, expected, _ = compare(tmp_path,source,factory)
    assert len([event for event in expected.observation if event[0]=='iter']) == 1
    assert len([event for event in expected.observation if event[0]=='next']) == 3
    assert expected.status == ('RETURN' if finish in ('exhausted','subclass') else 'RAISE')


def test_get_iterator_stopiteration_is_not_normal_exhaustion(tmp_path):
    def factory():
        events, error = [], StopIteration('iter creation failed')
        class Iterable:
            def __iter__(self):
                events.append('iter-mutated'); raise error
        return Case((Iterable(),),observe=lambda:events,sentinel=error)
    _, expected, _ = compare(tmp_path,'def f(xs):\n    for item in xs:\n        pass\n    else:\n        return "else"\n',factory)
    assert expected.status == 'RAISE'


def test_body_stopiteration_is_not_consumed_as_next_exhaustion(tmp_path):
    def factory():
        events, error = [], StopIteration('body failed')
        def body(item):
            events.append(item); raise error
        return Case(([1,2],body),observe=lambda:events,sentinel=error)
    _, expected, _ = compare(tmp_path,('def f(xs, body):\n    for item in xs:\n        body(item)\n'
                                      '    else:\n        return "else"\n    return "after"\n'),factory)
    assert expected.status == 'RAISE' and expected.observation == (1,)


def test_sequence_iteration_fallback_preserves_getitem_order_and_indexerror_exhaustion(tmp_path):
    def factory():
        events = []
        class Sequence:
            def __getitem__(self, index):
                events.append(index)
                if index == 2:
                    raise IndexError('sequence ended')
                return index + 5
        return Case((Sequence(),), observe=lambda: events)
    _, expected, _ = compare(tmp_path, 'def f(xs):\n    for item in xs:\n        pass\n    return item\n', factory)
    assert expected.value == 6 and expected.observation == (0, 1, 2)


@pytest.mark.parametrize('fail_at', [None,2])
def test_heap_mutation_alias_and_exception_poststate_are_visible(tmp_path,fail_at):
    def factory():
        box, events = [], []
        error = OriginalError('mutated before failure')
        def change(target,item):
            target.append(item); events.append(('change',item))
            if fail_at is not None and len(target) == fail_at:
                raise error
        return Case(([1,2,3],change,box,box),observe=lambda:{'box':box,'events':events},
                    identities=((box,'shared-box'),),sentinel=error)
    source = ('def f(xs, change, left, right):\n    for item in xs:\n        change(left, item)\n'
              '    else:\n        change(left, "else")\n    return right\n')
    _, expected, _ = compare(tmp_path,source,factory)
    observed = dict(expected.observation)
    assert observed['box'] == ((1,2) if fail_at else (1,2,3,'else'))


@pytest.mark.parametrize('items', [[1,2,3],[1,1,1]])
def test_repeated_call_uses_and_dynamic_visits_are_not_memoized_by_static_value(tmp_path,items):
    def factory():
        events = []
        def choose(left,right):
            events.append((left,right)); return left
        return Case((list(items),choose),observe=lambda:events)
    source = ('def f(xs, choose):\n    selected = None\n    for item in xs:\n'
              '        selected = choose(item, item)\n    return selected\n')
    program, expected, actual = compare(tmp_path,source,factory)
    assert expected.value == items[-1] and len(expected.observation) == len(items)
    call_operations = {link.operation for link in program.metadata.operation_links
                       if link.semantic_operation is not None and
                       program.semantics.operations[link.semantic_operation].opcode is Opcode.CALL}
    calls = [visit for visit in actual.visits if visit.operation in call_operations]
    assert len(calls) == len(items) and len({visit.operation for visit in calls}) == 1
    assert len({visit.index for visit in calls}) == len(items)
    operation, = [operation for operation in program.graph.operations if operation.id in call_operations]
    assert operation.invoke_arguments[1] != operation.invoke_arguments[2]


def test_evaluator_ignores_display_labels_and_uses_typed_records(tmp_path):
    def relabel(program):
        return replace(program, graph=replace(program.graph,operations=tuple(
            replace(operation,label='misleading opaque ADD branch label') for operation in program.graph.operations)))
    compare(tmp_path,'def f(x, y):\n    local = x\n    local = y\n    return local\n',
            lambda:Case((1,2)),mutate=relabel)


def test_opaque_protocol_never_falls_back_to_executing_known_source_opcode(tmp_path):
    path = tmp_path / 'original.py'
    path.write_text('def f(x, y):\n    return x + y\n')
    program = lower_source(path, 'f', profile=BodyLoweringProfile.STRUCTURED_BODY)
    assert program.graph is not None
    source, = [link for link in program.metadata.operation_links
               if link.semantic_operation is not None and
               program.semantics.operations[link.semantic_operation].opcode is Opcode.ADD]
    protocol = PythonProtocol(source.operation, PythonProtocolKind.OPAQUE_EXPRESSION, source.source)
    opaque = replace(program, structured=replace(program.structured,
                     protocols=program.structured.protocols + (protocol,)))
    events = []
    class Number:
        def __add__(self, other):
            events.append('must not be called')
            return other
    actual = run_core(opaque, (Number(), object()), observe=lambda: events)
    assert actual.status == 'UNSUPPORTED' and 'OPAQUE_EXPRESSION' in actual.detail
    assert actual.exception is None and not events


def test_type_valid_wrong_branch_is_caught_by_execution_not_self_replay(tmp_path):
    source = 'def f(flag):\n    if flag:\n        return 1\n    else:\n        return 2\n'
    path=tmp_path/'original.py';path.write_text(source)
    program=lower_source(path,'f',profile=BodyLoweringProfile.STRUCTURED_BODY)
    assert program.graph is not None
    graph=replace(program.graph,operations=tuple(
        replace(operation,terminator=replace(operation.terminator,successors=tuple(reversed(operation.terminator.successors))))
        if operation.terminator and operation.terminator.kind is TerminatorKind.BRANCH else operation
        for operation in program.graph.operations))
    require_valid(graph)
    actual=run_core(replace(program,graph=graph),(True,))
    assert actual.status=='RETURN' and actual.value==2
    expected=run_python(source,(True,))
    assert expected.status=='RETURN' and expected.value==1


def test_dynamic_step_budget_is_not_a_python_exception_or_partial_success(tmp_path):
    source='def f(xs):\n    for item in xs:\n        pass\n    return None\n'
    path=tmp_path/'original.py';path.write_text(source)
    program=lower_source(path,'f',profile=BodyLoweringProfile.STRUCTURED_BODY)
    assert program.graph is not None
    actual=run_core(program,(list(range(20)),),max_steps=3)
    assert actual.status=='BUDGET_EXHAUSTED' and actual.exception is None
    assert len(actual.visits)==3
