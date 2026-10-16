class Holder:
    def method(self, value):
        return value
def subject(box, value):
    direct = box.method(value)
    bound = box.method
    alias = bound(value)
    return alias
