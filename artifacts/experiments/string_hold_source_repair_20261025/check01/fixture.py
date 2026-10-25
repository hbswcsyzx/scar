def construct(key, value, callee):
    return f"prefix{key} middle{callee(value)}suffix"
