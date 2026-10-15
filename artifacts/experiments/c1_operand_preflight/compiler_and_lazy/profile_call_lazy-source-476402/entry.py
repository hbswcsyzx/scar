from lazy_helper_476402 import identity
def caller(fn, value):
    return fn(value)
def run(value):
    return caller(identity, value)
result = run(object())
