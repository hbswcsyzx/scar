attempts = 0
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
