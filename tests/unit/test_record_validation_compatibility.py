"""Differential contract against the validator frozen at f21eb53.

The reference below is copied from ``git show
f21eb53:scar/ir/v2/_validation.py``; only helper names were changed. It does
not import the production validator's type plans or validation helpers.
"""
from dataclasses import dataclass, fields, is_dataclass
from functools import lru_cache
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

import pytest

from scar.ir.v2._validation import mapping_errors, record_errors


@lru_cache(maxsize=None)
def reference_hints(cls):
    return get_type_hints(cls)


def reference_record_errors(value, expected, path):
    if expected is Any:
        return []
    origin, args = get_origin(expected), get_args(expected)
    if origin in (Union, UnionType):
        if any(not reference_record_errors(value, choice, path) for choice in args):
            return []
        return [f"{path} has invalid type or value for {expected}"]
    if origin in (tuple, list, set, frozenset, dict):
        if not isinstance(value, origin):
            return [f"{path} must be {origin.__name__}"]
        errors = []
        if origin is dict:
            for key, item in value.items():
                errors.extend(reference_record_errors(key, args[0], f"{path}.key"))
                errors.extend(reference_record_errors(item, args[1], f"{path}[{key!s}]"))
        elif origin is tuple and not (len(args) == 2 and args[1] is Ellipsis):
            if len(value) != len(args):
                return [f"{path} must contain {len(args)} fields"]
            for index, (item, item_type) in enumerate(zip(value, args)):
                errors.extend(reference_record_errors(item, item_type, f"{path}[{index}]"))
        else:
            for index, item in enumerate(value):
                errors.extend(reference_record_errors(item, args[0], f"{path}[{index}]"))
        return errors
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
    hints = reference_hints(type(value))
    for item in fields(value):
        errors.extend(reference_record_errors(getattr(value, item.name), hints[item.name],
                                             f"{path}.{item.name}"))
    if not errors and hasattr(value, "__post_init__"):
        try:
            value.__post_init__()
        except (TypeError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
    return errors


def reference_mapping_errors(mapping, key_type, record_type, path, key_field="id"):
    errors = []
    for key, value in mapping.items():
        errors.extend(reference_record_errors(key, key_type, f"{path}.key"))
        errors.extend(reference_record_errors(value, record_type, f"{path}[{key!s}]"))
        if isinstance(value, record_type) and key != getattr(value, key_field):
            errors.append(f"{path}[{key!s}] key does not match record {key_field}")
    return errors


class IntegerSubclass(int):
    pass


class FloatSubclass(float):
    pass


class TextSubclass(str):
    pass


@dataclass
class Leaf:
    count: int


@dataclass
class ExtendedLeaf(Leaf):
    label: str


@dataclass
class TextRecord(str):
    count: int = 0


@dataclass
class Nested:
    children: list[Leaf]
    lookup: dict[str, tuple[int, str]]
    optional: Leaf | None


@dataclass
class RegistryRecord:
    id: str
    count: int


@pytest.mark.parametrize("value,expected,accepted", [
    (True, bool, True), (1, bool, False), (True, int, False), (False, float, False),
    (1, int, True), (1, float, True), (1.5, float, True), (1.0, int, False),
    (IntegerSubclass(1), int, False), (IntegerSubclass(1), float, False),
    (FloatSubclass(1), float, False), (TextSubclass("x"), str, True),
    (None, type(None), True), (None, str, False), (object(), Any, True),
    (Leaf(True), Any, True), (Leaf(True), object, False),
    (ExtendedLeaf(1, "ok"), Leaf, True), (ExtendedLeaf(1, 3), Leaf, False),
])
def test_primitives_and_runtime_subclass_records_match_baseline(value, expected, accepted):
    baseline = reference_record_errors(value, expected, "root")
    assert bool(baseline) is not accepted
    assert record_errors(value, expected, "root") == baseline


@pytest.mark.parametrize("value,expected", [
    ((1, "ok"), tuple[int, str]), ((True, 7), tuple[int, str]),
    ((1,), tuple[int, str]), ((), tuple[()]), ((1,), tuple[()]),
    ((1, True, "bad"), tuple[int, ...]), ([1, True], list[int]),
    ({True}, set[int]), (frozenset({False}), frozenset[int]),
    ({"x": [1, True], 3: ["bad"]}, dict[str, list[int]]),
    ([1], tuple[int, ...]), ((1,), list[int]), ({1}, frozenset[int]),
    (1, int | str), (True, int | str), (None, Union[Leaf, None]),
    (Leaf(True), Union[Leaf, None]), (ExtendedLeaf(2, 4), Leaf | str),
])
def test_containers_unions_and_error_order_match_baseline(value, expected):
    assert record_errors(value, expected, "payload") == reference_record_errors(value, expected, "payload")


def test_nested_error_paths_are_exact_and_all_invalid_children_are_reported():
    value = Nested([Leaf(True), Leaf("bad")], {"item": (False, 7)}, None)
    errors = record_errors(value, Nested, "model")
    assert errors == reference_record_errors(value, Nested, "model")
    assert errors == [
        "model.children[0].count must be int", "model.children[1].count must be int",
        "model.lookup[item][0] must be int", "model.lookup[item][1] must be str",
    ]


def test_str_subclass_dataclass_fields_are_not_skipped_by_scalar_fast_path():
    value = TextRecord("text")
    value.count = 1
    assert record_errors(value, str, "text") == []
    value.count = True
    assert record_errors(value, str, "text") == reference_record_errors(value, str, "text")
    assert record_errors(value, str, "text") == ["text.count must be int"]


def test_container_subclass_obeys_original_container_precedence():
    class RecordList(list):
        pass
    value = RecordList([1, True])
    assert record_errors(value, list[int], "items") == reference_record_errors(value, list[int], "items")
    assert record_errors(value, list[int], "items") == ["items[1] must be int"]


def test_in_place_record_and_container_changes_are_checked_on_every_call():
    value = Nested([Leaf(1)], {"item": (2, "ok")}, Leaf(3))
    assert record_errors(value, Nested, "root") == []
    value.children[0].count = True
    value.lookup["item"] = (False, 9)
    value.children.append(ExtendedLeaf(1, False))
    value.optional = "wrong"
    errors = record_errors(value, Nested, "root")
    assert errors == reference_record_errors(value, Nested, "root")
    assert len(errors) == 5
    value.children[:] = [Leaf(4)]
    value.lookup.clear()
    value.optional = None
    assert record_errors(value, Nested, "root") == []


EVENTS = []


@dataclass
class Checked:
    name: str
    failure: str = ""

    def __post_init__(self):
        EVENTS.append(self.name)
        if self.failure == "value":
            raise ValueError("invalid invariant")
        if self.failure == "type":
            raise TypeError("bad invariant type")
        if self.failure == "runtime":
            raise RuntimeError("unexpected checker failure")


@dataclass
class ParentChecked:
    children: tuple[Checked, ...]

    def __post_init__(self):
        EVENTS.append("parent")


def validation_trace(checker, value, expected):
    EVENTS.clear()
    errors = checker(value, expected, "root")
    return errors, list(EVENTS)


def test_post_init_runs_each_time_in_child_then_parent_order_even_for_shared_values():
    child = Checked("child")
    parent = ParentChecked((child, child))
    baseline = validation_trace(reference_record_errors, parent, ParentChecked)
    assert baseline == ([], ["child", "child", "parent"])
    assert validation_trace(record_errors, parent, ParentChecked) == baseline
    assert validation_trace(record_errors, parent, ParentChecked) == baseline
    child.failure = "value"
    baseline = validation_trace(reference_record_errors, parent, ParentChecked)
    assert baseline == (["root.children[0]: invalid invariant", "root.children[1]: invalid invariant"],
                        ["child", "child"])
    assert validation_trace(record_errors, parent, ParentChecked) == baseline
    assert validation_trace(record_errors, parent, ParentChecked) == baseline


@pytest.mark.parametrize("failure", ("value", "type"))
def test_union_rechecks_dataclass_in_alternative_and_preserves_side_effects(failure):
    value = Checked("leaf")
    value.failure = failure
    expected = Checked | object
    baseline = validation_trace(reference_record_errors, value, expected)
    assert baseline[1] == ["leaf", "leaf"]
    assert len(baseline[0]) == 1
    assert validation_trace(record_errors, value, expected) == baseline


def test_field_type_failure_prevents_post_init_and_any_bypasses_record_checks():
    value = Checked("leaf")
    value.name = 123
    baseline = validation_trace(reference_record_errors, value, Checked)
    assert baseline == (["root.name must be str"], [])
    assert validation_trace(record_errors, value, Checked) == baseline
    assert validation_trace(record_errors, value, Any) == ([], [])


def test_post_init_method_is_not_frozen_in_cached_type_plan(monkeypatch):
    value = Checked("leaf")
    assert record_errors(value, Checked, "root") == []

    def replacement(self):
        raise ValueError("replacement invariant")

    monkeypatch.setattr(Checked, "__post_init__", replacement)
    assert record_errors(value, Checked, "root") == reference_record_errors(value, Checked, "root")
    assert record_errors(value, Checked, "root") == ["root: replacement invariant"]


def test_unexpected_post_init_exception_propagates_like_baseline():
    value = Checked("leaf")
    value.failure = "runtime"
    for checker in (reference_record_errors, record_errors):
        with pytest.raises(RuntimeError, match="unexpected checker failure"):
            checker(value, Checked, "root")


def test_mapping_key_record_type_and_identity_paths_match_baseline_after_mutation():
    mapping = {"first": RegistryRecord("first", 1), "second": RegistryRecord("second", 2)}
    assert mapping_errors(mapping, str, RegistryRecord, "registry") == []
    mapping["first"].id = "other"
    mapping["second"].count = True
    mapping[3] = "not a record"
    errors = mapping_errors(mapping, str, RegistryRecord, "registry")
    assert errors == reference_mapping_errors(mapping, str, RegistryRecord, "registry")
    assert errors == [
        "registry[first] key does not match record id", "registry[second].count must be int",
        "registry.key must be str", "registry[3] must be RegistryRecord",
    ]
    assert mapping_errors({1: Leaf(1)}, int, Leaf, "counts", key_field="count") == []
    assert mapping_errors({2: Leaf(1)}, int, Leaf, "counts", key_field="count") == [
        "counts[2] key does not match record count"]
