class Scale:
    def apply(self, x):
        return x * 2

def add(x):
    return x + 1

def run(n):
    obj = Scale()
    total = 0
    for i in range(n):
        total += add(obj.apply(i))
    return total
