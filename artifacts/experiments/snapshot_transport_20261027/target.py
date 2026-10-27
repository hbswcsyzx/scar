import json
import threading

class Adder:
    def __init__(self, offset):
        self.offset = offset
    def apply(self, value):
        return self.offset + value

def with_default(value, offset=1):
    return value + offset

def run(count):
    first, second = Adder(3), Adder(7)
    total = 0
    for step in range(count):
        with_default.__defaults__ = (step % 5,)
        receiver = first if step % 2 else second
        total += receiver.apply(with_default(step))
    return total

result = [run(300)]
thread = threading.Thread(target=lambda: result.append(run(30)))
thread.start()
thread.join()
print(json.dumps({'result': result}, sort_keys=True))
