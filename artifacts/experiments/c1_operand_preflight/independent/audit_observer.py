"""Public observation APIs can invoke already installed Python audit hooks."""
import json
from pathlib import Path
import sys

events = []
phase = "installation"
def audit(event, args):
    events.append({"phase": phase, "event": event})
sys.addaudithook(audit)

def function(value=None):
    return value

phase = "getframe"
frame = sys._getframe()
phase = "frame_code"
code = frame.f_code
phase = "function_code"
function_code = function.__code__
phase = "function_defaults"
defaults = function.__defaults__
phase = "function_kwdefaults"
kwdefaults = function.__kwdefaults__
phase = "function_closure"
closure = function.__closure__
phase = "function_globals"
globals_mapping = function.__globals__
phase = "function_builtins"
builtins_mapping = function.__builtins__
phase = "frame_locals"
locals_mapping = frame.f_locals
phase = "frame_globals"
frame_globals = frame.f_globals
phase = "done"
result = {"python": sys.version, "events": events[:],
          "inference": "A collector using these APIs cannot promise no additional user audit-hook calls when such hooks are installed."}
Path(__file__).with_name("audit_observer.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
