import gc
import json
import weakref

def factory(initial):
    value = initial
    def read():
        return value
    def write(new):
        nonlocal value
        value = new
    return read, write

def entry(default=7):
    return default

def drive():
    left, write = factory(3)
    right, _ = factory(5)
    assert left() == 3
    write(4)
    assert left() == 4
    assert right() == 5
    entry()
    entry.__defaults__ = (9,)
    assert entry() == 9
    handle = weakref.ref(left)
    del left
    gc.collect()
    assert handle() is None, 'observer retained the function'
    print(json.dumps({'probe': 'closure identity and nonretention', 'valid': True}))

drive()
