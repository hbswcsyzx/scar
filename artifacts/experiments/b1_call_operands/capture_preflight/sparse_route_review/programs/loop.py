def choose(left, right):
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
