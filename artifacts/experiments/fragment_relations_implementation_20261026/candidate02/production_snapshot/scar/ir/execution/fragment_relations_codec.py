"""Closed v1 transport for cross-fragment records; no semantic certification."""
from scar.ir.record_codec import encode, decode, loads as strict_loads
from .fragment_relations import RECORD_TYPES, canonical, need

SCHEMA = "scar.execution-fragment-relations"
VERSION = 1
_TYPES = {kind.__name__: kind for kind in RECORD_TYPES}


def to_dict(record):
    need(type(record) in RECORD_TYPES, "unsupported relation record")
    record.__post_init__()
    value = {"schema": SCHEMA, "schema_version": VERSION,
             "record_type": type(record).__name__, "record": encode(record)}
    if hasattr(record, "id"):
        value["relation_id"] = record.id
    return value


def from_dict(value):
    need(type(value) is dict, "transport object")
    need({"schema", "schema_version", "record_type", "record"} <= set(value), "missing transport fields")
    need(value["schema"] == SCHEMA and type(value["schema_version"]) is int
         and value["schema_version"] == VERSION, "unsupported relation schema/version")
    need(type(value.get("record_type")) is str and value["record_type"] in _TYPES, "unknown relation record type")
    kind = _TYPES[value["record_type"]]
    expected = {"schema", "schema_version", "record_type", "record"} | ({"relation_id"} if hasattr(kind, "id") else set())
    need(set(value) == expected, "transport fields")
    record = decode(kind, value["record"])
    need("relation_id" not in value or value["relation_id"] == record.id, "derived qualified relation identity differs")
    return record


def dumps(record):
    return canonical(to_dict(record)).decode()


def loads(payload):
    return from_dict(strict_loads(payload))
