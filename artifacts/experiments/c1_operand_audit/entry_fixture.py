from c1_helper_fixture import relay
def name_call(fn, value):
    return fn(value)
def attr_call(receiver, value):
    return receiver.method(value)
def run(left, right):
    first = relay(left)
    second = relay(right)
    return first
selected = replacement = None
def mutate_selected(value):
    global selected
    selected = replacement
    return value
def global_rebind(value):
    return selected(mutate_selected(value))
def local_rebind(fn, other, value):
    return fn((fn := other), value)
