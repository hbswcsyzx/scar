"""Read-only sparse-window architecture probe, not a production collector."""
from __future__ import annotations
import ast
from collections import Counter, defaultdict, deque
import dis
import inspect
import json
from pathlib import Path
import sys
import time
import types

from scar.trace.operand_bytecode import load_slots

BASE = Path(__file__).resolve().parent
CASES = {
'loop': '''def choose(left, right):
    return left
def subject(fn, left, right, flags):
    outputs = []
    for flag in flags:
        if flag:
            marker = 1
        else:
            marker = 2
        result = fn(left, right)
        outputs.append(result)
    return result
''',
'exception': '''def choose(left, right):
    return left
def subject(fn, left, right, flags):
    for flag in flags:
        try:
            if flag:
                del left
            result = fn(left, right)
        except UnboundLocalError:
            left = right
    return result
''',
'handler': '''attempts = 0
def choose(left, right):
    global attempts
    attempts += 1
    if attempts == 1:
        raise ValueError('first')
    return left
def subject(fn, left, right):
    try:
        return fn(left, right)
    except ValueError:
        return fn(right, left)
''',
'callback': '''def choose(left, right):
    return left
def callback(value):
    return 0
def subject(fn, left, right, values):
    ordered = sorted(values, key=callback)
    return fn(left, right)
''',
'generator': '''def choose(left, right):
    return left
def subject(fn, left, right):
    yield fn(left, right)
    yield fn(right, left)
''',
'method': '''class Holder:
    def method(self, value):
        return value
def subject(box, value):
    direct = box.method(value)
    bound = box.method
    alias = bound(value)
    return alias
''',
'perf': '''def choose(left, right):
    return left
def subject(fn, left, right, values):
    created = [value * value for value in values if value % 2]
    return fn(left, right)
''',
}


def codes(code):
    yield code
    for value in code.co_consts:
        if type(value) is types.CodeType:
            yield from codes(value)


def static_plans(code, text):
    instructions = tuple(dis.get_instructions(code))
    calls = [node for node in ast.walk(ast.parse(text)) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and not node.keywords
             and all(isinstance(arg, ast.Name) for arg in node.args)]
    jump_targets = {item.argval for item in instructions if item.opcode in dis.hasjump}
    handlers = {item.target for item in dis.Bytecode(code).exception_entries}
    plans, rejected = {}, []
    for index, call in enumerate(instructions):
        if call.opname != 'CALL':
            continue
        matching = [node for node in calls if (node.lineno, node.end_lineno, node.col_offset, node.end_col_offset)
                    == (call.positions.lineno, call.positions.end_lineno, call.positions.col_offset, call.positions.end_col_offset)]
        if len(matching) != 1:
            continue
        node, = matching
        if call.arg != len(node.args):
            continue
        backwards, count = [], 0
        for item in reversed(instructions[:index]):
            slots = load_slots(code, item)
            if slots is None or (not slots and item.opname not in ('PUSH_NULL', 'NOP')):
                break
            backwards.append(item)
            count += len(slots)
            if count >= len(node.args) + 1:
                break
        if count != len(node.args) + 1:
            continue
        window = tuple(reversed(backwards)) + (call,)
        loads = [slot for item in window[:-1] for slot in load_slots(code, item)]
        if [slot[2] for slot in loads] != [node.func.id, *(arg.id for arg in node.args)]:
            continue
        if any(slot[1] != 'FAST_LOCAL' for slot in loads[1:]):
            continue
        internal = {item.offset for item in window[1:]}
        problem = sorted(internal & (jump_targets | handlers))
        if problem:
            rejected.append({'call': call.offset, 'interior_targets': problem})
            continue
        plans[call.offset] = tuple(item.offset for item in window)
    return plans, {'qualname': code.co_qualname, 'flags': code.co_flags,
                   'suspended_code': bool(code.co_flags & (inspect.CO_GENERATOR | inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR)),
                   'windows': [{'call': offset, 'offsets': list(window)} for offset, window in plans.items()],
                   'jump_targets': sorted(jump_targets), 'handler_targets': sorted(handlers), 'rejected': rejected,
                   'instructions': [{'offset': item.offset, 'opname': item.opname, 'argval': repr(item.argval),
                                     'position': list(item.positions)} for item in instructions]}


def main():
    case, mode, masks = sys.argv[1:]
    source = CASES[case]
    path = BASE / 'programs' / (case + '.py')
    path.parent.mkdir(exist_ok=True)
    path.write_text(source)
    top = compile(source, str(path), 'exec', dont_inherit=True)
    namespace = {}
    exec(top, namespace)
    all_codes = tuple(codes(top))
    target_codes = {code for code in all_codes if code.co_name != '<module>'}
    plans, descriptions = {}, []
    for code in target_codes:
        plan, description = static_plans(code, source)
        plans[code] = plan
        descriptions.append(description)
    selected = {code: {offset for window in plan.values() for offset in window} for code, plan in plans.items()}
    oracle_enabled = case != 'perf'
    tool, oracle_tool = 3, 4
    monitor = sys.monitoring
    active, next_owner = {}, 0
    sparse_tail, oracle_tail = defaultdict(lambda: deque(maxlen=64)), defaultdict(lambda: deque(maxlen=64))
    callbacks, disabled = Counter(), Counter()
    entries, observed_calls, matched, loaded_shapes = [], [], [], []
    resumed = Counter()
    missing_owner = 0

    def owner(frame):
        return active.get(id(frame))

    def instruction(code, offset):
        nonlocal missing_owner
        frame = sys._getframe(1)
        key = owner(frame)
        if key is None:
            missing_owner += 1
            return
        callbacks[code.co_qualname, offset] += 1
        if mode == 'sparse' and offset not in selected[code]:
            disabled[code.co_qualname, offset] += 1
            return monitor.DISABLE
        sparse_tail[key].append(offset)
        if offset in selected[code]:
            item = next(item for item in dis.get_instructions(code) if item.offset == offset)
            slots = load_slots(code, item)
            for suboperand, kind, name, index in slots or ():
                mapping = frame.f_locals if kind == 'FAST_LOCAL' else frame.f_globals
                value = mapping.get(name)
                shape = 'EXACT_METHOD' if type(value) is types.MethodType else 'EXACT_FUNCTION' if type(value) is types.FunctionType else type(value).__name__
                loaded_shapes.append({'owner': key, 'offset': offset, 'suboperand': suboperand, 'name': name, 'kind': shape})

    def oracle(code, offset):
        frame = sys._getframe(1)
        key = owner(frame)
        if key is not None:
            oracle_tail[key].append(offset)

    def call(code, offset, callable_object, arg0):
        frame = sys._getframe(1)
        key = owner(frame)
        if key is None:
            return
        shape = 'EXACT_METHOD' if type(callable_object) is types.MethodType else 'EXACT_FUNCTION' if type(callable_object) is types.FunctionType else type(callable_object).__name__
        observed_calls.append({'owner': key, 'qualname': code.co_qualname, 'offset': offset, 'kind': shape,
                               'arg0_missing': arg0 is monitor.MISSING})
        plan = plans[code].get(offset)
        if plan is not None:
            dynamic = list(sparse_tail[key])[-len(plan):]
            full = list(oracle_tail[key])[-len(plan):] if oracle_enabled else None
            matched.append({'owner': key, 'qualname': code.co_qualname, 'call': offset, 'window': list(plan),
                            'sparse_tail': dynamic, 'sparse_match': dynamic == list(plan),
                            'oracle_tail': full, 'oracle_match': full == list(plan) if oracle_enabled else None})

    def profile(frame, event, arg):
        nonlocal next_owner
        if frame.f_code not in target_codes:
            return
        if event == 'call':
            next_owner += 1
            active[id(frame)] = next_owner
            resumed[frame.f_code.co_qualname] += 1
            entries.append({'owner': next_owner, 'qualname': frame.f_code.co_qualname, 'offset': frame.f_lasti})
            if masks == 'toggle' or monitor.get_local_events(tool, frame.f_code) == 0:
                monitor.set_local_events(tool, frame.f_code, monitor.events.INSTRUCTION | monitor.events.CALL)
                if oracle_enabled:
                    monitor.set_local_events(oracle_tool, frame.f_code, monitor.events.INSTRUCTION)
        elif event == 'return':
            active.pop(id(frame), None)
            if masks == 'toggle':
                monitor.set_local_events(tool, frame.f_code, 0)
                if oracle_enabled:
                    monitor.set_local_events(oracle_tool, frame.f_code, 0)

    old_profile = sys.getprofile()
    sys.setprofile(profile)
    monitor.use_tool_id(tool, 'scar-sparse-review')
    monitor.register_callback(tool, monitor.events.INSTRUCTION, instruction)
    monitor.register_callback(tool, monitor.events.CALL, call)
    if oracle_enabled:
        monitor.use_tool_id(oracle_tool, 'scar-sparse-review-oracle')
        monitor.register_callback(oracle_tool, monitor.events.INSTRUCTION, oracle)
    started = time.perf_counter()
    try:
        left, right = object(), object()
        if case == 'loop':
            namespace['subject'](namespace['choose'], left, right, [False, True] * 3)
        elif case == 'exception':
            namespace['subject'](namespace['choose'], left, right, [True, False, True, False])
        elif case == 'handler':
            namespace['subject'](namespace['choose'], left, right)
        elif case == 'callback':
            namespace['subject'](namespace['choose'], left, right, [3, 1, 2])
        elif case == 'generator':
            list(namespace['subject'](namespace['choose'], left, right))
        elif case == 'method':
            namespace['subject'](namespace['Holder'](), left)
        elif case == 'perf':
            values = list(range(5000))
            for _ in range(3):
                namespace['subject'](namespace['choose'], left, right, values)
    finally:
        elapsed = time.perf_counter() - started
        sys.setprofile(old_profile)
        monitor.free_tool_id(tool)
        if oracle_enabled:
            monitor.free_tool_id(oracle_tool)
    result = {'case': case, 'mode': mode, 'mask_lifecycle': masks, 'python': sys.version,
              'oracle_enabled': oracle_enabled, 'elapsed_seconds': elapsed,
              'instruction_callback_count': sum(callbacks.values()), 'disable_returns': sum(disabled.values()),
              'disabled_offsets': [{'qualname': k[0], 'offset': k[1], 'count': v} for k, v in sorted(disabled.items())],
              'selected_instruction_callback_count': sum(v for (name, offset), v in callbacks.items()
                                                          if any(code.co_qualname == name and offset in selected[code] for code in target_codes)),
              'missing_owner': missing_owner, 'entries': entries, 'calls': observed_calls,
              'windows': matched, 'load_shapes': loaded_shapes, 'code_plans': descriptions,
              'spliced_accepted_windows': [item for item in matched if item['sparse_match'] and item['oracle_match'] is False]}
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
