"""Independent CPython witnesses; no SCAR import, GPU, or workload execution."""
import hashlib
import json
from pathlib import Path
import sys

out = {"python": sys.version, "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
for expression in ["not (a and b)", "not (a or b)"]:
    events = []
    class Signal:
        def __init__(self, name, answer):
            self.name, self.answer = name, answer
        def __bool__(self):
            events.append(self.name)
            return self.answer
    a, b = Signal("a", False), Signal("b", True)
    value = eval(expression)
    out[expression] = {"events": list(events), "value": value}
    events.clear()
    exec("if " + expression + ":\n result=1\nelse:\n result=2")
    out["if " + expression] = {"events": list(events), "result": result}

events = []
class Target:
    def __getattr__(self, name):
        events.append("getattr")
        return 0
    def __getitem__(self, key):
        events.append("getitem")
        return 0
def owner():
    events.append("owner")
    return Target()
def index():
    events.append("index")
    return 0
exec("owner().field: int\nowner()[index()]: int")
out["annassign_no_rhs"] = {"events": list(events)}

class Value:
    def __repr__(self):
        events.append("repr")
        return "v"
def value():
    events.append("value")
    return Value()
def width():
    events.append("width")
    return 2
events.clear()
f"{value()!r:{width()}}"
out["formatted_order"] = {"events": list(events)}
events.clear()
def base_pack():
    events.append("base_pack")
    return ()
def meta():
    events.append("metaclass_expression")
    return type
exec("class Header(metaclass=meta(), *base_pack()):\n pass")
out["class_header_star_after_keyword"] = {"events": list(events)}
Path(__file__).with_name("probe.json").write_text(json.dumps(out, indent=2) + "\n")
print(json.dumps(out, indent=2))
