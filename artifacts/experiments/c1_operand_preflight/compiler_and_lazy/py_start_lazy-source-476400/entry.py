from lazy_helper_476400 import identity
def caller(fn, value):
    return fn(value)
def run(value):
    return caller(identity, value)
result = run(object())
