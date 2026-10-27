"""Standalone CPython language probes; no SCAR imports, target code or graph tests."""
from __future__ import annotations

import ast
import asyncio
import hashlib
import inspect
import json
import platform
from pathlib import Path
import sys
import time
import warnings
from collections.abc import Sequence


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


def tree(error):
    if isinstance(error, BaseExceptionGroup):
        return {"type": type(error).__name__, "children": [tree(e) for e in error.exceptions]}
    return {"type": type(error).__name__}


@case
def truth_context():
    events = []

    class Flag:
        def __init__(self, name, truth):
            self.name, self.truth = name, truth

        def __bool__(self):
            events.append(self.name)
            return self.truth

    a, b = Flag("a", False), Flag("b", True)
    result = a and b
    value_events = events[:]
    assert result is a and value_events == ["a"]
    events.clear()
    if a and b:
        raise AssertionError("short circuit failed")
    direct_events = events[:]
    assert direct_events == ["a"]
    events.clear()
    result = a and b
    if result:
        raise AssertionError("unexpected truth")
    stored_events = events[:]
    assert stored_events == ["a", "a"]
    events.clear()
    chosen = "yes" if (b if a else b) else "no"
    assert chosen == "yes" and events == ["a", "b"]
    conditional_events = events[:]
    events.clear()
    nested_result = (a and b) and b
    assert nested_result is a and events == ["a"]
    nested_events = events[:]
    return {"value_context": value_events, "direct_truth": direct_events,
            "stored_then_truth": stored_events, "conditional_truth": conditional_events,
            "nested_short_circuit": nested_events}


@case
def comparison_chain():
    events = []

    class Result:
        def __bool__(self):
            events.append("truth")
            return False

    result = Result()

    class Operand:
        def __lt__(self, other):
            events.append("compare")
            return result

    def operand(name):
        events.append(name)
        return Operand()

    value = operand("left") < operand("middle") < operand("right")
    value_events = events[:]
    assert value is result and events == ["left", "middle", "compare", "truth"]
    events.clear()
    if operand("left") < operand("middle") < operand("right"):
        raise AssertionError("unexpected branch")
    assert events == value_events
    return {"false_result_is_comparison_object": True, "value": value_events, "truth": events}


@case
def comparison_dispatch_and_membership():
    events = []

    class Base:
        def __lt__(self, other):
            events.append("base-lt")
            return True

    class Sub(Base):
        def __gt__(self, other):
            events.append("sub-gt")
            return True

    assert Base() < Sub()
    assert events == ["sub-gt"]
    events.clear()

    class Item:
        def __init__(self, name):
            self.name = name

        def __eq__(self, other):
            events.append(self.name + "-eq-" + other.name)
            return True

    class Container:
        def __iter__(self):
            events.append("iter")
            return iter([Item("item")])

    assert Item("needle") in Container()
    assert events == ["iter", "item-eq-needle"]
    return {"rich_comparison_subtype_priority": ["sub-gt"], "membership_fallback": events}


@case
def loops_and_exhaustion():
    events = []

    class Iter:
        def __iter__(self):
            events.append("iter")
            return self

        def __next__(self):
            events.append("next")
            raise StopIteration

    x = "previous"
    for x in Iter():
        events.append("body")
    else:
        events.append("else")
    assert x == "previous" and events == ["iter", "next", "else"]
    try:
        for _ in [1]:
            raise StopIteration("body")
    except StopIteration:
        events.append("body-stop-propagates")
    for _ in [1]:
        for _ in []:
            pass
        else:
            events.append("inner-else")
            break
    else:
        raise AssertionError("outer else ran after break")
    return {"events": events, "zero_iteration_target": x}


@case
def comprehensions():
    events = []

    class Iterable:
        def __iter__(self):
            events.append("iter")
            return iter([1, 2])

    def mark(name, value):
        events.append(name)
        return value

    x = 99
    values = {mark("key" + str(x), x): mark("value" + str(x), x) for x in Iterable()
              if mark("filter" + str(x), True)}
    eager = events[:]
    assert x == 99 and values == {1: 1, 2: 2}
    assert eager == ["iter", "filter1", "key1", "value1", "filter2", "key2", "value2"]
    events.clear()
    gen = (mark("element", x) for x in Iterable() if mark("filter", True))
    creation = events[:]
    assert creation == ["iter"]
    assert next(gen) == 1
    resumed = events[:]
    gen.close()
    captured = None
    [(captured := x) for x in [3, 4]]
    assert captured == 4 and x == 99
    return {"dict_order": eager, "generator_creation": creation,
            "generator_first_resume": resumed, "outer_x": x, "walrus_outer": captured}


@case
def asynchronous_iteration():
    events = []

    class AsyncIter:
        def __init__(self, label):
            self.label, self.count = label, 0

        def __aiter__(self):
            events.append(self.label + ".aiter")
            return self

        async def __anext__(self):
            self.count += 1
            events.append(self.label + ".anext" + str(self.count))
            if self.count > 1:
                raise StopAsyncIteration
            return 7

        async def aclose(self):
            events.append(self.label + ".aclose")

    class SynchronousStop(AsyncIter):
        def __anext__(self):
            events.append("sync-stop")
            raise StopAsyncIteration

    async def run():
        async for x in AsyncIter("complete"):
            events.append("body" + str(x))
        else:
            events.append("else")
        async for x in AsyncIter("break"):
            break
        async for x in SynchronousStop("sync"):
            raise AssertionError("not exhausted")
        else:
            events.append("sync-else")
        try:
            async for x in AsyncIter("body-error"):
                raise StopAsyncIteration
        except StopAsyncIteration:
            events.append("body-error-propagates")
        gen = (x async for x in AsyncIter("gen"))
        before = events[:]
        assert before[-1] == "gen.aiter"
        assert await anext(gen) == 7
        await gen.aclose()
        values = [x async for x in AsyncIter("list")]
        assert values == [7]
        return before

    creation = asyncio.run(run())
    assert not any(event.endswith(".aclose") for event in events)
    assert "sync-else" in events and "body-error-propagates" in events
    return {"events": events, "before_async_generator_resume": creation}


@case
def try_handler_context():
    events = []

    def bad_type():
        events.append("match-expression")
        raise LookupError("matching")

    try:
        try:
            raise ValueError("original")
        except bad_type():
            events.append("unreachable")
        except Exception:
            events.append("wrong-sibling")
        finally:
            events.append("finally")
    except LookupError as escaped:
        assert isinstance(escaped.__context__, ValueError)
        events.append("outside")
    error = "old"
    outer = ValueError("outer")
    try:
        raise outer
    except ValueError as error:
        assert sys.exception() is outer
        try:
            raise KeyError("inner")
        except KeyError:
            events.append("inner-handler")
        assert sys.exception() is outer
    try:
        error
    except UnboundLocalError:
        events.append("as-target-unbound")
    assert events == ["match-expression", "finally", "outside", "inner-handler", "as-target-unbound"]
    return {"events": events, "handler_context_restored": sys.exception() is None}


@case
def exception_groups():
    events = []
    original = ExceptionGroup("root", [ValueError("v"), TypeError("t"), OSError("o")])
    try:
        try:
            raise original
        except* ValueError as matched:
            events.append(["value", type(matched).__name__, len(matched.exceptions)])
            raise RuntimeError("new")
        except* TypeError:
            events.append(["type"])
    except BaseExceptionGroup as escaped:
        result = tree(escaped)
    assert [event[0] for event in events] == ["value", "type"]
    assert result == {"type": "ExceptionGroup", "children": [
        {"type": "RuntimeError"}, {"type": "ExceptionGroup", "children": [{"type": "OSError"}]}]}
    try:
        raise ValueError("single")
    except* ValueError as wrapped:
        wrapping = type(wrapped).__name__
    assert wrapping == "ExceptionGroup"
    try:
        try:
            raise ValueError("unmatched")
        except* TypeError:
            raise AssertionError("unexpected match")
    except ValueError:
        unmatched = "ValueError"
    suffix = []
    def remaining_type():
        suffix.append("type-evaluated")
        return TypeError
    try:
        raise ValueError("consumed")
    except* ValueError:
        pass
    except* remaining_type():
        raise AssertionError("unexpected suffix handler")
    return {"events": events, "merged": result, "single_exception_wrapper": wrapping,
            "unmatched_naked": unmatched, "type_evaluation_after_all_consumed": suffix}


@case
def finally_and_raise_order():
    events = []

    class E(Exception):
        def __init__(self):
            events.append("construct-exception")

    class C(Exception):
        def __init__(self):
            events.append("construct-cause")

    def mark(name, value):
        events.append(name)
        return value

    try:
        raise mark("exception-expression", E) from mark("cause-expression", C)
    except E as exc:
        assert isinstance(exc.__cause__, C) and exc.__suppress_context__
    order = events[:]
    assert order == ["exception-expression", "cause-expression", "construct-exception", "construct-cause"]
    ns = {}
    source = "def f(xs):\n for x in xs:\n  try: return x\n  finally: break\n else: return 'empty'\n return 'broke'\n"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        exec(compile(source, "finally-probe.py", "exec"), ns)
    assert ns["f"]([]) == "empty" and ns["f"]([object()]) == "broke"
    payload = []

    def keep_ref():
        try:
            return payload
        finally:
            payload.append("mutated")

    assert keep_ref() is payload and payload == ["mutated"]
    return {"raise_order": order, "finally_overrides_return": True,
            "warnings": [type(item.message).__name__ for item in caught], "payload": payload}


@case
def context_manager_protocol():
    events = []

    class Truth:
        def __bool__(self):
            events.append("exit-truth")
            return True

    class Special:
        def __init__(self, name):
            self.name = name

        def __get__(self, obj, owner):
            events.append("lookup-" + self.name)
            if self.name == "enter":
                def enter():
                    events.append("enter")
                    return (1,)
                return enter
            def exit_(typ, value, tb):
                events.append("exit-" + (typ.__name__ if typ else "None"))
                return Truth()
            return exit_

    class Manager:
        __enter__ = Special("enter")
        __exit__ = Special("exit")

    with Manager() as (a, b):
        events.append("unreachable")
    failed_assignment = events[:]
    assert failed_assignment[-2:] == ["exit-ValueError", "exit-truth"]
    events.clear()

    def returning():
        with Manager():
            return "payload"

    assert returning() == "payload"
    normal_return = events[:]
    assert normal_return[-1] == "exit-None" and "exit-truth" not in normal_return
    events.clear()

    class AsyncManager:
        async def __aenter__(self):
            events.append("aenter")
            return self

        async def __aexit__(self, typ, value, tb):
            events.append("aexit-" + typ.__name__)
            return Truth()

    async def run():
        async with AsyncManager():
            raise ValueError("body")
        events.append("after")

    asyncio.run(run())
    assert events == ["aenter", "aexit-ValueError", "exit-truth", "after"]
    return {"target_failure": failed_assignment, "normal_return": normal_return, "async": events}


@case
def generator_protocol():
    events = []

    def child(box):
        events.append("entered")
        try:
            received = yield box
            box.append(received)
            return box
        finally:
            events.append("cleanup")

    box = []
    g = child(box)
    assert events == []
    assert next(g) is box
    box.append("outside")
    try:
        g.send("sent")
    except StopIteration as done:
        assert done.value is box
    assert box == ["outside", "sent"] and events == ["entered", "cleanup"]
    events.clear()
    untouched = child([])
    untouched.close()
    assert events == []

    def close_return():
        try:
            yield 1
        except GeneratorExit:
            return 9

    closing = close_return()
    next(closing)
    returned = closing.close()
    assert returned == 9

    def bad_close():
        try:
            yield 1
        except GeneratorExit:
            yield 2

    suspended = bad_close()
    next(suspended)
    try:
        suspended.close()
    except RuntimeError:
        state_after_failed_close = inspect.getgeneratorstate(suspended)
    assert state_after_failed_close == "GEN_SUSPENDED"
    suspended.close()

    def illegal_stop():
        yield 1
        raise StopIteration("wrong")

    illegal = illegal_stop()
    next(illegal)
    try:
        next(illegal)
    except RuntimeError as error:
        assert isinstance(error.__cause__, StopIteration)
    return {"box_after_resume": box, "close_return": returned,
            "failed_close_state": state_after_failed_close, "escaping_stopiteration": "RuntimeError"}


@case
def async_generator_protocol():
    events = []
    async def gen():
        events.append("entered")
        try:
            sent = yield "first"
            yield sent
        finally:
            events.append("cleanup")

    async def run():
        g = gen()
        request = g.__anext__()
        assert events == []
        assert await request == "first"
        assert await g.asend("sent") == "sent"
        assert await g.aclose() is None
        try:
            await g.__anext__()
        except StopAsyncIteration:
            after_close = "StopAsyncIteration"
        try:
            value = await g.athrow(ValueError("closed"))
            throw_closed = ["returned", value]
        except BaseException as error:
            throw_closed = ["raised", type(error).__name__]
        untouched = gen()
        try:
            await untouched.asend(1)
        except TypeError:
            created_send = "TypeError"
        await untouched.aclose()
        return {"closed_next": after_close, "closed_athrow": throw_closed,
                "created_send_non_none": created_send}

    result = asyncio.run(run())
    assert events == ["entered", "cleanup"]
    return {"events": events, **result}


@case
def delegation_and_await():
    events = []

    def sub():
        try:
            sent = yield "first"
            events.append(["sent", sent])
            try:
                yield "second"
            except ValueError:
                events.append("caught-throw")
                return "delegated-result"
        finally:
            events.append("sub-cleanup")

    def parent():
        result = yield from sub()
        events.append(["parent-result", result])
        return result

    g = parent()
    assert next(g) == "first" and g.send(4) == "second"
    try:
        g.throw(ValueError("injected"))
    except StopIteration as done:
        assert done.value == "delegated-result"
    delegation = events[:]
    events.clear()

    class Awaitable:
        def __await__(self):
            events.append("await-enter")
            value = yield "scheduler-request"
            events.append(["await-resume", value])
            return value

    async def outer():
        return await Awaitable()

    coro = outer()
    assert events == [] and coro.send(None) == "scheduler-request"
    try:
        coro.send(12)
    except StopIteration as done:
        assert done.value == 12
    return {"delegation": delegation, "await": events}


@case
def match_capture_and_protocols():
    events = []
    subject = [1, 2]
    captured = "before"
    match subject:
        case [captured, _] if False:
            events.append("wrong")
        case _:
            events.append("next-case")
    assert captured == 1

    class Mapping(dict):
        def get(self, key, default=None):
            events.append(["get", key])
            return super().get(key, default)

        def __missing__(self, key):
            events.append("missing")
            return 4

    match Mapping(a=1, b=2):
        case {"a": value, **rest}:
            assert value == 1 and rest == {"b": 2}
        case _:
            raise AssertionError("mapping did not match")
    assert "missing" not in events

    class Obj:
        __match_args__ = ("x", "y")

        @property
        def x(self):
            events.append("get-x")
            return 1

        @property
        def y(self):
            events.append("get-y")
            return 2

    match Obj():
        case Obj(1, second):
            assert second == 2
    assert events[-2:] == ["get-x", "get-y"]
    match "ab":
        case [a, b]:
            raise AssertionError("str matched sequence pattern")
        case _:
            events.append("str-not-sequence")
    match 7:
        case int(value):
            assert value == 7
    return {"events": events, "binding_after_false_guard": captured, "int_self_pattern": value}


@case
def pattern_fetch_before_subpattern():
    events = []

    class Obj:
        __match_args__ = ("x", "y")

        @property
        def x(self):
            events.append("class-x")
            return 0

        @property
        def y(self):
            events.append("class-y")
            return 2

    match Obj():
        case Obj(1, _):
            raise AssertionError("unexpected class match")
    class_events = events[:]
    assert class_events == ["class-x", "class-y"]
    events.clear()

    class Seq(Sequence):
        def __len__(self):
            events.append("length")
            return 2

        def __getitem__(self, index):
            events.append(["item", index])
            return [0, 2][index]

    match Seq():
        case [1, _]:
            raise AssertionError("unexpected sequence match")
    sequence_events = events[:]
    assert sequence_events == ["length", ["item", 0], ["item", 1], ["item", 2]]
    events.clear()

    class Mapping(dict):
        def get(self, key, default=None):
            events.append(["get", key])
            return super().get(key, default)

    match Mapping(a=0, b=2):
        case {"a": 1, "b": _}:
            raise AssertionError("unexpected mapping match")
    mapping_events = events[:]
    assert mapping_events == [["get", "a"], ["get", "b"]]
    return {"class": class_events, "sequence": sequence_events, "mapping": mapping_events}


@case
def exception_group_custom_split_and_failure():
    events = []

    class Group(ExceptionGroup):
        def split(self, condition):
            events.append("split")
            return super().split(condition)

        def derive(self, exceptions):
            events.append(["derive", len(exceptions)])
            return Group(self.message, exceptions)

    try:
        try:
            raise Group("custom", [ValueError(), TypeError()])
        except* ValueError:
            events.append("handler")
    except BaseExceptionGroup:
        events.append("outer")
    custom = events[:]
    assert "split" in custom and "handler" in custom and "outer" in custom
    events.clear()

    def bad_matcher():
        events.append("bad-match")
        raise LookupError

    try:
        try:
            raise ExceptionGroup("group", [ValueError(), TypeError()])
        except* bad_matcher():
            events.append("wrong-first")
        except* TypeError:
            events.append("wrong-second")
    except LookupError:
        events.append("outer-match-error")
    assert events == ["bad-match", "outer-match-error"]
    return {"custom_hooks": custom, "matching_failure": events}


@case
def assertions_and_compiler_constraints():
    source = "def f():\n assert probe('test', False), probe('message', 'bad')\n return 'ok'\n"
    results = {}
    for optimize in (0, 1, 2):
        events = []
        def probe(name, value):
            events.append(name)
            return value
        ns = {"probe": probe, "AssertionError": RuntimeError}
        exec(compile(source, "assert-probe.py", "exec", optimize=optimize), ns)
        try:
            value = ns["f"]()
            outcome = ["returned", value]
        except BaseException as error:
            outcome = ["raised", type(error).__name__, list(error.args)]
        results[str(optimize)] = {"events": events, "outcome": outcome}
    assert results["0"] == {"events": ["test", "message"], "outcome": ["raised", "AssertionError", ["bad"]]}
    assert results["1"] == results["2"] == {"events": [], "outcome": ["returned", "ok"]}

    sources = {
        "return_outside": "return 1",
        "break_outside": "break",
        "continue_outside": "continue",
        "except_star_escape": "def f():\n try: pass\n except* Exception: return 1\n",
        "except_star_local_loop_break": "try: pass\nexcept* Exception:\n for x in [1]:\n  break\n",
        "yield_from_async": "async def f():\n yield from []\n",
        "async_generator_return_value": "async def f():\n yield 1\n return 2\n",
        "comprehension_iterable_walrus": "[x for x in (items := [])]",
        "or_pattern_different_bindings": "match x:\n case [a] | [b]: pass\n",
    }
    constraints = {}
    for name, text in sources.items():
        try:
            compile(text, name + ".py", "exec")
        except SyntaxError as error:
            constraints[name] = {"accepted": False, "message": error.msg}
        else:
            constraints[name] = {"accepted": True}
    assert constraints["except_star_local_loop_break"]["accepted"]
    assert all(not record["accepted"] for name, record in constraints.items()
               if name != "except_star_local_loop_break")
    return {"assert_modes": results, "compile_constraints": constraints}


NODES = (
    "If BoolOp IfExp Compare And Or Eq NotEq Lt LtE Gt GtE Is IsNot In NotIn "
    "For While AsyncFor ListComp SetComp DictComp GeneratorExp comprehension "
    "Try TryStar ExceptHandler Raise With AsyncWith withitem Yield YieldFrom Await "
    "Return Break Continue Match match_case MatchValue MatchSingleton MatchSequence "
    "MatchMapping MatchClass MatchStar MatchAs MatchOr Assert"
).split()


def main():
    started = time.perf_counter()
    results = []
    for fn in CASES:
        try:
            result = fn()
            results.append({"case": fn.__name__, "status": "PASS", "result": result})
        except BaseException as error:
            results.append({"case": fn.__name__, "status": "FAIL", "error": type(error).__name__,
                            "message": str(error)})
    report = {
        "kind": "standalone-language-probe-not-scar-validation",
        "python": sys.version, "executable": sys.executable, "implementation": platform.python_implementation(),
        "command": "PYTHONDONTWRITEBYTECODE=1 /home/zyf/miniconda3/envs/lewm/bin/python artifacts/experiments/model_control_protocols/probe.py",
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "ast_fields": {name: list(getattr(ast, name)._fields) for name in NODES},
        "results": results, "passed": sum(r["status"] == "PASS" for r in results),
        "failed": sum(r["status"] == "FAIL" for r in results), "wall_seconds": time.perf_counter() - started,
        "target_executed": False, "scar_graph_validated": False,
    }
    destination = Path(__file__).with_name("results.json")
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"report": str(destination), "passed": report["passed"],
                      "failed": report["failed"], "wall_seconds": report["wall_seconds"]}))
    for result in results:
        if result["status"] == "FAIL":
            print(json.dumps(result, ensure_ascii=False))
    return bool(report["failed"])


if __name__ == "__main__":
    raise SystemExit(main())
