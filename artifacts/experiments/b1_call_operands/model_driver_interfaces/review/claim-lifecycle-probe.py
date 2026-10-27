"""Small stdlib observations for claim/session design; not a C2D validator."""
import json
import sys
import warnings


def exception_normalization_reentry():
    events = []

    def body():
        try:
            events.append("body:first")
            yield "first"
            events.append("body:nested-resume")
            yield "second"
        except ReentrantError:
            events.append("body:outer-throw-resume")
            yield "caught"

    class ReentrantError(Exception):
        def __init__(self):
            events.append("exception-constructor")
            events.append({"nested_next": next(instance)})
            super().__init__()

    instance = body()
    started = next(instance)
    events.clear()
    returned = instance.throw(ReentrantError)
    result = {"started": started, "outer_throw_returned": returned,
              "events_inside_outer_throw": list(events),
              "body_ingresses_inside_outer_host_call": sum(
                  isinstance(event, str) and event.startswith("body:") for event in events)}
    instance.close()
    return result


def async_request_across_inner_await():
    class Pause:
        def __await__(self):
            yield "scheduler-token"
            return "ready"

    async def body():
        value = await Pause()
        yield value

    instance = body()
    request = instance.asend(None)
    yielded = request.send(None)
    while_waiting = {"ag_running": instance.ag_running,
                     "frame_present": instance.ag_frame is not None}
    competitor = instance.asend(None)
    try:
        competitor.send(None)
    except BaseException as error:
        competitor_result = {"exception": type(error).__name__, "message": str(error)}
    else:
        competitor_result = {"exception": None}
    try:
        request.send(None)
    except StopIteration as completed:
        request_result = {"exception": "StopIteration", "value": completed.value}
    after_item = {"ag_running": instance.ag_running,
                  "frame_present": instance.ag_frame is not None}
    closing = instance.aclose()
    try:
        closing.send(None)
    except StopIteration:
        pass
    return {"first_drive_yielded": yielded, "while_inner_await": while_waiting,
            "other_request": competitor_result, "original_request_completion": request_result,
            "after_async_yield": after_item, "after_close_frame_present": instance.ag_frame is not None}


def raw_throw_to_delegate():
    events = []
    marker, invalid_traceback = object(), object()

    class Error(Exception):
        def __init__(self, *args):
            events.append("exception-normalized")
            super().__init__(*args)

    class Delegate:
        def __iter__(self):
            return self

        def __next__(self):
            return "delegate-start"

        def throw(self, *arguments):
            events.append({"arity": len(arguments), "raw_class": arguments[0] is Error,
                           "raw_value": arguments[1] is marker,
                           "raw_traceback": arguments[2] is invalid_traceback})
            return "delegate-item"

    def body():
        yield from Delegate()

    instance = body()
    next(instance)
    with warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter("always")
        result = instance.throw(Error, marker, invalid_traceback)
    instance.close()
    return {"returned": result, "events": events,
            "warnings": [type(item.message).__name__ for item in observed]}


if __name__ == "__main__":
    print(json.dumps({"python": sys.version, "implementation": sys.implementation.name,
                      "normalization_reentry": exception_normalization_reentry(),
                      "async_request_session": async_request_across_inner_await(),
                      "raw_throw_to_delegate": raw_throw_to_delegate()}, indent=2))
