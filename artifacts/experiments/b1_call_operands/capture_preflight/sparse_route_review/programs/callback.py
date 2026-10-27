def choose(left, right):
    return left
def callback(value):
    return 0
def subject(fn, left, right, values):
    ordered = sorted(values, key=callback)
    return fn(left, right)
