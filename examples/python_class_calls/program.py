"""Small input for SCAR's source-only class-call model."""


def replace_class(cls):
    return lambda value: value


class Maker:
    def __init__(self, value, flag=False):
        self.value = value


def construct(cls, value):
    return cls(value)


Alias = Maker
first = Alias(3, flag=True)
second = Alias(4, flag=False)


@replace_class
class Wrapped:
    pass


other = Wrapped(9)
forwarded = construct(Maker, 7)
