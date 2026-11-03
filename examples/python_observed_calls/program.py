"""Two actual class objects reach the same source CALL through a parameter."""


class Left:
    def __init__(self, value):
        self.value = value


class Right:
    def __init__(self, value):
        self.value = value


def build(cls):
    return cls(3)


first = build(Left)
second = build(Right)
assert first.value == second.value == 3

