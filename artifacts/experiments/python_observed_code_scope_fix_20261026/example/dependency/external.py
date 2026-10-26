def selected(value):
    return leaf(value)

def leaf(value):
    return value

def opaque_wrapper(callback, value):
    return callback(value)
