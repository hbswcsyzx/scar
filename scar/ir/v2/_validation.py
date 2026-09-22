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


@lru_cache(maxsize=None)
def _hints(cls: type) -> dict:
    return get_type_hints(cls)


def record_errors(value: Any, expected: Any, path: str) -> list[str]:
    """Check a typed record, including nested records and post-init invariants."""
    if expected is Any:
        return []
    origin, args = get_origin(expected), get_args(expected)
    if origin in (Union, UnionType):
        if any(not record_errors(value, choice, path) for choice in args):
            return []
        return [f"{path} has invalid type or value for {expected}"]
    if origin in (tuple, list, set, frozenset, dict):
        if not isinstance(value, origin):
            return [f"{path} must be {origin.__name__}"]
        errors: list[str] = []
        if origin is dict:
            for key, item in value.items():
                errors.extend(record_errors(key, args[0], f"{path}.key"))
                errors.extend(record_errors(item, args[1], f"{path}[{key!s}]"))
        elif origin is tuple and not (len(args) == 2 and args[1] is Ellipsis):
            if len(value) != len(args):
                return [f"{path} must contain {len(args)} fields"]
            for index, (item, item_type) in enumerate(zip(value, args)):
                errors.extend(record_errors(item, item_type, f"{path}[{index}]"))
        else:
            for index, item in enumerate(value):
                errors.extend(record_errors(item, args[0], f"{path}[{index}]"))
        return errors
    # Python bool subclasses int, but a true/false value is never a count or ID.
    if expected is int:
        good_type = type(value) is int
    elif expected is float:
        good_type = type(value) in (float, int)
    else:
        good_type = isinstance(value, expected)
    if not good_type:
        return [f"{path} must be {getattr(expected, '__name__', expected)}"]
    if not is_dataclass(value):
        return []
    errors = []
    hints = _hints(type(value))
    for item in fields(value):
        errors.extend(record_errors(getattr(value, item.name), hints[item.name],
                                    f"{path}.{item.name}"))
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
