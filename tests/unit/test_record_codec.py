from dataclasses import dataclass
import math

import pytest

from scar.ir.record_codec import decode, encode, loads
from scar.ir.v2 import ObjectID, StorageAllocationID, ValueVersionID, LogicalValueID


@dataclass(frozen=True)
class Record:
    identity: ObjectID
    pair: tuple[int, str]
    values: tuple[float, ...]
    attributes: dict[str, bool]
    optional: int | None = None


def test_typed_record_roundtrip_preserves_tuple_map_and_ids():
    record = Record(ObjectID("one"), (3, "value"), (1.5, 3.0), {"enabled": True})
    assert decode(Record, encode(record)) == record
    version = ValueVersionID(LogicalValueID("logical"), 2)
    assert decode(ValueVersionID, encode(version)) == version


@pytest.mark.parametrize("field,value", [
    ("pair", [1]), ("pair", [True, "x"]), ("pair", [1, "x", "extra"]),
    ("identity", StorageAllocationID("one").as_dict()),
    ("attributes", {"enabled": 1}), ("optional", True), ("values", [math.nan]),
])
def test_record_codec_rejects_wrong_types_and_identity_namespaces(field, value):
    document = encode(Record(ObjectID("one"), (1, "x"), (), {}))
    document[field] = value
    with pytest.raises(ValueError):
        decode(Record, document)


def test_json_duplicate_nonfinite_and_unknown_fields_are_rejected():
    for payload in ('{"key":1,"key":2}', '{"value":NaN}', '{"value":Infinity}'):
        with pytest.raises(ValueError):
            loads(payload)
    with pytest.raises(ValueError):
        encode({1: "non-string key"})
    with pytest.raises(ValueError):
        decode(float, math.inf)
    with pytest.raises(ValueError):
        decode(Record, {**encode(Record(ObjectID("one"), (1, "x"), (), {})), "extra": True})
