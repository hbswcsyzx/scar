"""Three bounded stdlib counterexamples, without importing SCAR or Torch."""
import json
from pathlib import Path
import sys
import weakref


def callback_changes_post():
    events = []

    class Request:
        phase = "ACTIVE"

    class OldReference:
        def __init__(self, request):
            self.request = weakref.ref(request)

        def __del__(self):
            request = self.request()
            events.append("callback.enter")
            request.phase = "HOLD"
            events.append("callback.reassociate.HOLD")

    request = Request()
    request.payload = OldReference(request)

    def update():
        request.phase = "COMPLETE"
        events.append("metadata.COMPLETE")
        request.payload = None
        events.append("helper.NORMAL")

    result = update()
    assert result is None
    assert request.phase == "HOLD"
    assert events == ["metadata.COMPLETE", "callback.enter",
                      "callback.reassociate.HOLD", "helper.NORMAL"]
    return {"events": events, "normal_returned": 1, "final_phase": request.phase}


def raise_after_partial_write():
    events = []
    state = {"phase": "ACTIVE", "world": 0}

    class HelperFailure(Exception):
        pass

    def update():
        state["phase"] = "COMPLETE"
        state["world"] += 1
        events.append("write.COMPLETE")
        raise HelperFailure("after the write")

    try:
        update()
    except HelperFailure:
        events.append("helper.RAISE")
    else:
        raise AssertionError("helper did not raise")
    assert state == {"phase": "COMPLETE", "world": 1}
    assert events == ["write.COMPLETE", "helper.RAISE"]
    return {"events": events, "final_phase": state["phase"], "world": state["world"]}


def unraisable_keeps_completion_and_effects():
    events = []
    state = {"world": 0}

    class FinalizerFailure(Exception):
        pass

    class Victim:
        def __del__(self):
            state["world"] += 1
            events.append("finalizer.write")
            raise FinalizerFailure("ordinary finalizer error")

    def hook(args):
        events.append("unraisable." + type(args.exc_value).__name__)

    def drop():
        local = Victim()
        del local
        events.append("helper.NORMAL")
        return "KEPT"

    previous = sys.unraisablehook
    try:
        sys.unraisablehook = hook
        result = drop()
    finally:
        sys.unraisablehook = previous
    assert result == "KEPT"
    assert state["world"] == 1
    assert events == ["finalizer.write", "unraisable.FinalizerFailure", "helper.NORMAL"]
    return {"events": events, "result": result, "world": state["world"]}


cases = []
for function in (callback_changes_post, raise_after_partial_write,
                 unraisable_keeps_completion_and_effects):
    try:
        detail = function()
    except BaseException as exc:
        cases.append({"case": function.__name__, "status": "FAIL",
                      "error": type(exc).__name__ + ": " + str(exc)})
    else:
        cases.append({"case": function.__name__, "status": "PASS", **detail})
failed = sum(case["status"] == "FAIL" for case in cases)
result = {"python": sys.version, "command": [sys.executable, str(Path(__file__).resolve())],
          "attempt": 1, "cases": cases, "passed": len(cases) - failed,
          "failed": failed, "exit_code": int(bool(failed)),
          "torch_imported": int("torch" in sys.modules),
          "scar_imported": int("scar" in sys.modules)}
Path(__file__).with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
sys.exit(result["exit_code"])
