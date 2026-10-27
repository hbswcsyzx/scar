import time
from scar.trace.deferred_jsonl import DeferredJsonl
original = DeferredJsonl.finalize
def delayed_conversion(self):
    time.sleep(2)
    return original(self)
DeferredJsonl.finalize = delayed_conversion
def call(value):
    return value
for i in range(5):
    call(i)
print('APPLICATION_BODY_RETURNING', flush=True)
