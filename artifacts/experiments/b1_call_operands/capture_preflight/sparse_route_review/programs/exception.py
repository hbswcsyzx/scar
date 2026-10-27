def choose(left, right):
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
