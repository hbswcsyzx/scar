def identity(value):
    return value
def relay(value):
    return identity(value)
def raw_target(self, value=None):
    return self
def replacement(self, value=None):
    return value
class Holder:
    pass
Holder.method = raw_target
