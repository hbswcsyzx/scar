from helper import relay


def run(x, y):
    first = relay(x, y)
    second = relay(y, x)
    return first
