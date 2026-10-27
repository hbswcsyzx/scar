def choose(left, right):
    return left
def subject(fn, left, right):
    yield fn(left, right)
    yield fn(right, left)
