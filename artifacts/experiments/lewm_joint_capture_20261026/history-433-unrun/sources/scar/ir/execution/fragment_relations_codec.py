"""Closed versioned transports; v1 remains the explicit default writer."""
from scar.ir.record_codec import encode, decode, loads as strict_loads
from .fragment_relations import RECORD_TYPES, RECORD_TYPES_V2, WorkRelations, canonical, need

SCHEMA = "scar.execution-fragment-relations"
VERSION = 1
_TYPES = {1: {kind.__name__: kind for kind in RECORD_TYPES},
          2: {kind.__name__: kind for kind in RECORD_TYPES_V2}}
_V1_WORK_FIELDS = {"projection", "hosts", "source_contexts", "static_bindings", "gaps"}


def to_dict(record, *, schema_version=VERSION):
    need(type(schema_version) is int and schema_version in _TYPES, "unsupported relation schema/version")
    need(type(record) in _TYPES[schema_version].values(), "unsupported relation record")
    record.__post_init__()
    encoded = encode(record)
    if schema_version == 1 and type(record) is WorkRelations:
        need(not record.enclosing_native, "v1 cannot encode enclosing-native relations")
        del encoded["enclosing_native"]
    value = {"schema": SCHEMA, "schema_version": schema_version,
             "record_type": type(record).__name__, "record": encoded}
    if hasattr(record, "id"):
        value["relation_id"] = record.id
    return value


def from_dict(value):
    need(type(value) is dict, "transport object")
    need({"schema", "schema_version", "record_type", "record"} <= set(value), "missing transport fields")
    need(value["schema"] == SCHEMA and type(value["schema_version"]) is int
         and value["schema_version"] in _TYPES, "unsupported relation schema/version")
    types = _TYPES[value["schema_version"]]
    need(type(value.get("record_type")) is str and value["record_type"] in types, "unknown relation record type")
    kind = types[value["record_type"]]
    expected = {"schema", "schema_version", "record_type", "record"} | ({"relation_id"} if hasattr(kind, "id") else set())
    need(set(value) == expected, "transport fields")
    encoded = value["record"]
    if value["schema_version"] == 1 and kind is WorkRelations:
        need(type(encoded) is dict and set(encoded) == _V1_WORK_FIELDS, "v1 work fields")
        encoded = {**encoded, "enclosing_native": []}
    record = decode(kind, encoded)
    need("relation_id" not in value or value["relation_id"] == record.id, "derived qualified relation identity differs")
    return record


def dumps(record, *, schema_version=VERSION):
    return canonical(to_dict(record, schema_version=schema_version)).decode()


def loads(payload):
    return from_dict(strict_loads(payload))
