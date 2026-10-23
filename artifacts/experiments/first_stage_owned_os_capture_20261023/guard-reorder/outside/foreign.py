import sys


def noise(count):
    values=[]
    for value in range(count):values.append(value)
    return len(values)


def remove_hook():
    sys.setprofile(None)
