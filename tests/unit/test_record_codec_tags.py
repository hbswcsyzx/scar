"""Optional discriminator rules distinguish records without altering old wire."""
from dataclasses import dataclass
import json

import pytest

from scar.ir.record_codec import decode, encode, loads
from scar.ir.v2.ids import ObjectID, ValueVersionID


@dataclass(frozen=True, slots=True)
class Left:
    value: int


@dataclass(frozen=True, slots=True)
class Right:
    value: int


@dataclass(frozen=True, slots=True)
class Nested:
    sequence: tuple[Left | Right, ...]
    groups: dict[str, list[Right | Left]]
    pair: tuple[Left | Right, Right | None]


TAGS = {Left: ("kind", "left"), Right: ("kind", "right")}


def test_same_shape_union_uses_explicit_tags_in_either_union_order():
    for item in (Left(3), Right(3)):
        document = encode(item, record_tags=TAGS)
        assert document == {"value": 3, "kind": type(item).__name__.lower()}
        for expected in (Left | Right, Right | Left):
            result = decode(expected, document, record_tags=TAGS)
            assert type(result) is type(item) and result == item


def test_nested_union_tuple_list_dict_and_optional_share_the_local_tag_rules():
    item = Nested((Left(1), Right(2)), {"nodes": [Right(3), Left(4)]}, (Right(5), None))
    document = encode(item, record_tags=TAGS)
    assert document["groups"]["nodes"][0]["kind"] == "right"
    assert decode(Nested, document, record_tags=TAGS) == item
    # Decoding reconstructs the actual variants rather than the first union arm.
    assert type(decode(Nested, document, record_tags=TAGS).pair[0]) is Right


def test_default_encoding_and_untagged_legacy_variant_remain_unchanged():
    assert json.dumps(encode(Left(7)), separators=(",", ":")) == '{"value":7}'
    assert encode(Left(7), record_tags={}) == encode(Left(7)) == encode(Right(7))
    assert decode(Left, {"value": 7}) == Left(7)
    # A new tagged variant can coexist with the unchanged old wire in one union.
    tags = {Right: ("kind", "new")}
    assert decode(Left | Right, encode(Left(7), record_tags=tags), record_tags=tags) == Left(7)
    assert type(decode(Left | Right, encode(Right(7), record_tags=tags), record_tags=tags)) is Right
    with pytest.raises(ValueError):
        decode(Right, {"value": 7}, record_tags=tags)
    with pytest.raises(ValueError):
        decode(Left | Right, {"value": 7, "kind": "new"})


@pytest.mark.parametrize("document", [
    {"value": 1}, {"value": 1, "kind": "unknown"}, {"value": 1, "kind": True},
    {"value": 1, "kind": None}, {"value": 1, "kind": "left", "verified": True},
])
def test_missing_wrong_or_extra_tag_fields_cannot_select_a_variant(document):
    with pytest.raises(ValueError):
        decode(Left | Right, document, record_tags=TAGS)


def test_tag_selection_happens_before_any_variant_constructor():
    called = []

    @dataclass(frozen=True)
    class First:
        value: int

        def __post_init__(self):
            called.append("first")

    @dataclass(frozen=True)
    class Second:
        value: int

        def __post_init__(self):
            called.append("second")

    tags = {First: ("kind", "first"), Second: ("kind", "second")}
    result = decode(First | Second, {"value": 1, "kind": "second"}, record_tags=tags)
    # Existing record_errors rechecks post-init invariants after construction;
    # none of those checks may instantiate or recheck the wrong union variant.
    assert type(result) is Second and called and set(called) == {"second"}
    called.clear()
    with pytest.raises(ValueError):
        decode(First | Second, {"value": 1, "kind": "unknown"}, record_tags=tags)
    assert called == []


@pytest.mark.parametrize("tags", [
    {Left: ["kind", "left"]}, {Left: ("kind",)}, {Left: ("", "left")},
    {Left: ("kind", "")}, {Left: ("kind", True)}, {Left: (False, "left")},
    {Left: ("value", "left")},
    {Left: ("kind", "same"), Right: ("kind", "same")},
])
def test_invalid_configuration_and_duplicate_discriminators_are_rejected(tags):
    for operation in (lambda: encode(Left(1), record_tags=tags),
                      lambda: decode(Left, {"value": 1}, record_tags=tags)):
        with pytest.raises(ValueError):
            operation()


@pytest.mark.parametrize("tags", [[(Left, ("kind", "left"))],
                                  {int: ("kind", "int")},
                                  {ObjectID: ("kind", "object")},
                                  {ValueVersionID: ("kind", "version")}])
def test_tags_only_apply_to_ordinary_dataclass_records_not_special_wire_types(tags):
    with pytest.raises(TypeError):
        encode(Left(1), record_tags=tags)


def test_duplicate_json_tag_and_malformed_nested_payload_still_fail_strictly():
    with pytest.raises(ValueError, match="duplicate JSON field"):
        loads('{"value":1,"kind":"left","kind":"right"}')
    with pytest.raises(ValueError):
        decode(Left | Right, {"value": True, "kind": "left"}, record_tags=TAGS)
    item = Nested((Left(1),), {}, (Right(2), None))
    document = encode(item, record_tags=TAGS)
    del document["sequence"][0]["kind"]
    with pytest.raises(ValueError):
        decode(Nested, document, record_tags=TAGS)
