from helper import external
class Operator:
    def operation(receiver, value):
        return value + 1

def ordinary(value):
    return value * 2

def ordinary_default(value, optional=11):
    return value + optional

def run():
    object_value = Operator()
    retained_method = object_value.operation
    first = retained_method(3)
    second = object_value.operation(4)
    third = ordinary(5)
    fourth = external(6)
    fifth = len((1, 2))
    ordinary_default(2)
    return first + second + third + fourth + fifth
