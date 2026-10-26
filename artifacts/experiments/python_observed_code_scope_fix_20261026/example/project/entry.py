from external import selected
gateway = None

def sentinel(value):
    return value

def run(value):
    first = selected(value)
    second = gateway(first)
    return sentinel(second)
