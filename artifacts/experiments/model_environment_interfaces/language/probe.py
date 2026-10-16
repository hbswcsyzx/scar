"""Small stdlib-only function environment facts; no target program or external I/O."""
import hashlib
import json
from pathlib import Path
import sys
import weakref


def builtins_binding():
    old = {'sentinel': 1}
    namespace = {'__builtins__': old}
    exec('def read(): return sentinel', namespace)
    read = namespace['read']
    before = read()
    namespace['__builtins__'] = {'sentinel': 2}
    after_replace = read()
    old['sentinel'] = 3
    after_mutate = read()
    assert (before, after_replace, after_mutate) == (1, 1, 3)
    assert read.__builtins__ is old
    both = {'sentinel': 4}
    both['__builtins__'] = both
    exec('def read(): return sentinel', both)
    assert both['read'].__globals__ is both['read'].__builtins__
    return {'values': [before, after_replace, after_mutate],
            'saved_builtins_survives_global_rebinding': True,
            'globals_and_builtins_can_be_same_object': True}


def closure_cells():
    def factory():
        x = []
        def read(): return x
        def erase():
            nonlocal x
            del x
        return read, erase
    read, erase = factory()
    cell = read.__closure__[0]
    assert cell is erase.__closure__[0]
    assert read.__code__.co_freevars == ('x',)
    erase()
    try: cell.cell_contents
    except ValueError: empty = True
    else: empty = False
    try: read()
    except NameError: read_raises = True
    else: read_raises = False
    try: weakref.ref(cell)
    except TypeError: not_weakrefable = True
    else: not_weakrefable = False
    assert empty and read_raises and not_weakrefable
    return {'shared_cell': True, 'empty_cell_is_not_none': empty,
            'empty_read_raises_name_error': read_raises, 'cell_not_weakrefable': not_weakrefable}


def defaults_and_function_state():
    shared = []
    def f(x=shared, *, y=shared): return x, y
    code = f.__code__
    assert f.__defaults__[0] is f.__kwdefaults__['y']
    new = object()
    f.__defaults__ = (new,)
    assert f()[0] is new and f()[1] is shared and f.__code__ is code
    f.marker = shared
    assert f.__dict__['marker'] is shared
    def g(): return None
    assert g.__defaults__ is None and g.__kwdefaults__ is None
    return {'defaults_and_kwdefaults_contents_can_alias': True,
            'defaults_rebind_without_code_change': True,
            'function_object_carries_additional_attributes': True,
            'absent_defaults_are_actual_none': True}


if __name__ == '__main__':
    result = {'python': sys.version, 'command': ' '.join(sys.orig_argv),
              'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'scope': 'stdlib language observations, not SCAR graph validation',
              'results': {fn.__name__: fn() for fn in
                          (builtins_binding, closure_cells, defaults_and_function_state)}}
    print(json.dumps(result, indent=2, sort_keys=True))
