"""Validation utilities for mutable IR records and directly decoded graphs.

Constructors are not the trust boundary: a graph may have been assembled by a
decoder or changed in place.  Graph validators therefore recheck both declared
field types and local record invariants before following any references.
"""
from __future__ import annotations

from collections import deque
from dataclasses import fields, is_dataclass
from functools import lru_cache
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from ..literals import PythonLiteral, _preflight_literal


@lru_cache(maxsize=None)
def _hints(cls: type) -> dict:
    return get_type_hints(cls)


_ANY_PLAN = 0
_UNION_PLAN = 1
_CONTAINER_PLAN = 2
_INT_PLAN = 3
_FLOAT_PLAN = 4
_INSTANCE_PLAN = 5


@lru_cache(maxsize=None)
def _cached_type_plan(expected: Any) -> tuple:
    """Cache type structure only; values and validation results stay uncached."""
    return _build_type_plan(expected)


def _type_plan(expected: Any) -> tuple:
    try:
        return _cached_type_plan(expected)
    except TypeError:
        # record_errors historically lets isinstance/get_origin diagnose an
        # unusual unhashable ``expected`` value. Keep that path uncached.
        try:
            hash(expected)
        except TypeError:
            return _build_type_plan(expected)
        raise


def _build_type_plan(expected: Any) -> tuple:
    if expected is Any:
        return (_ANY_PLAN,)
    origin, args = get_origin(expected), get_args(expected)
    if origin in (Union, UnionType):
        return (_UNION_PLAN, expected, tuple(_type_plan(choice) for choice in args))
    if origin in (tuple, list, set, frozenset, dict):
        return (_CONTAINER_PLAN, origin, args,
                tuple(_type_plan(argument) for argument in args))
    if expected is int:
        return (_INT_PLAN,)
    if expected is float:
        return (_FLOAT_PLAN,)
    return (_INSTANCE_PLAN, expected)


@lru_cache(maxsize=None)
def _dataclass_schema(cls: type) -> tuple[tuple[str, tuple], ...]:
    hints = _hints(cls)
    return tuple((item.name, _type_plan(hints[item.name])) for item in fields(cls))


def record_errors(value: Any, expected: Any, path: str) -> list[str]:
    """Check a typed record, including nested records and post-init invariants."""
    return _record_errors(value, _type_plan(expected), path)


def _record_errors(value: Any, plan: tuple, path: str) -> list[str]:
    kind = plan[0]
    if kind == _ANY_PLAN:
        return []
    if kind == _UNION_PLAN:
        if any(not _record_errors(value, choice, path) for choice in plan[2]):
            return []
        return [f"{path} has invalid type or value for {plan[1]}"]
    if kind == _CONTAINER_PLAN:
        origin, args, child_plans = plan[1:]
        if not isinstance(value, origin):
            return [f"{path} must be {origin.__name__}"]
        errors: list[str] = []
        if origin is dict:
            for key, item in value.items():
                errors.extend(_record_errors(key, child_plans[0], f"{path}.key"))
                errors.extend(_record_errors(item, child_plans[1], f"{path}[{key!s}]"))
        elif origin is tuple and not (len(args) == 2 and args[1] is Ellipsis):
            if len(value) != len(args):
                return [f"{path} must contain {len(args)} fields"]
            for index, (item, item_type) in enumerate(zip(value, args)):
                errors.extend(_record_errors(item, child_plans[index], f"{path}[{index}]"))
        else:
            for index, item in enumerate(value):
                errors.extend(_record_errors(item, child_plans[0], f"{path}[{index}]"))
        return errors
    # Python bool subclasses int, but a true/false value is never a count or ID.
    if kind == _INT_PLAN:
        expected = int
        good_type = type(value) is int
    elif kind == _FLOAT_PLAN:
        expected = float
        good_type = type(value) in (float, int)
    else:
        expected = plan[1]
        good_type = isinstance(value, expected)
    if not good_type:
        return [f"{path} must be {getattr(expected, '__name__', expected)}"]
    if expected is PythonLiteral:
        try:
            _preflight_literal(value)
        except (TypeError, ValueError) as exc:
            return [f"{path}: {exc}"]
        return []
    if not is_dataclass(value):
        return []
    errors = []
    if isinstance(value, type):
        # Preserve dataclasses.fields(value)'s behavior for a dataclass class
        # passed as a value (rather than an instance).
        hints = _hints(type(value))
        schema = tuple((item.name, _type_plan(hints[item.name])) for item in fields(value))
    else:
        schema = _dataclass_schema(type(value))
    for name, field_plan in schema:
        errors.extend(_record_errors(getattr(value, name), field_plan, f"{path}.{name}"))
    if not errors and hasattr(value, "__post_init__"):
        try:
            value.__post_init__()
        except (TypeError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
    return errors


def mapping_errors(mapping: dict, key_type: type, record_type: type,
                   path: str, key_field: str = "id") -> list[str]:
    """Validate registry entries and ensure keys match the record identity."""
    errors = []
    for key, value in mapping.items():
        errors.extend(record_errors(key, key_type, f"{path}.key"))
        errors.extend(record_errors(value, record_type, f"{path}[{key!s}]"))
        if isinstance(value, record_type) and key != getattr(value, key_field):
            errors.append(f"{path}[{key!s}] key does not match record {key_field}")
    return errors


def cycle_errors(arcs, label: str) -> list[str]:
    """Check a directed relation in O(V+E), without Python recursion depth limits."""
    outgoing: dict[Any, set] = {}
    indegrees: dict[Any, int] = {}
    for source, target in arcs:
        children = outgoing.setdefault(source, set())
        indegrees.setdefault(source, 0)
        indegrees.setdefault(target, 0)
        if target not in children:
            children.add(target)
            indegrees[target] += 1
    pending = deque(item for item, degree in indegrees.items() if degree == 0)
    visited = 0
    while pending:
        item = pending.popleft()
        visited += 1
        for child in outgoing.get(item, ()):
            indegrees[child] -= 1
            if indegrees[child] == 0:
                pending.append(child)
    if visited == len(indegrees):
        return []
    return [f"cyclic {label}"]
