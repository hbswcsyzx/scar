"""Strict versioned data-only codec for non-execution scope ledger records."""
from __future__ import annotations

import json
from scar.ir import modeling_scope as m
from scar.ir.record_codec import encode, decode, loads as strict_loads
from scar.ir.v2._validation import record_errors

SCHEMA = "scar.modeling-scope-record"
SCHEMA_VERSION = 1
_TYPES = {cls.__name__: cls for cls in (m.AnalysisScope, m.LedgerEntry, m.DenominatorInventory)}
_TAGS = {cls: ("$ledger_record", name) for name, cls in _TYPES.items()}


def to_dict(record):
    cls = type(record)
    if cls not in _TAGS:
        raise ValueError("unsupported scope record type/refinement")
    errors = record_errors(record, cls, "record")
    if errors:
        raise ValueError("; ".join(errors))
    return {"schema": SCHEMA, "schema_version": SCHEMA_VERSION,
            "record": encode(record, record_tags=_TAGS)}


def from_dict(document):
    if type(document) is not dict or set(document) != {"schema", "schema_version", "record"}:
        raise ValueError("incorrect scope record envelope")
    if (document["schema"] != SCHEMA or type(document["schema_version"]) is not int
            or document["schema_version"] != SCHEMA_VERSION):
        raise ValueError("unsupported scope record schema/version")
    row = document["record"]
    if type(row) is not dict or type(row.get("$ledger_record")) is not str or row["$ledger_record"] not in _TYPES:
        raise ValueError("unsupported scope record discriminator/refinement")
    return decode(_TYPES[row["$ledger_record"]], row, record_tags=_TAGS)


def dumps(record):
    return json.dumps(to_dict(record), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def loads(payload):
    if type(payload) is not str:
        raise ValueError("scope record text must be exact str")
    try:
        return from_dict(strict_loads(payload))
    except (TypeError, RecursionError, KeyError) as error:
        raise ValueError("invalid scope record: " + str(error)) from error


__all__ = ["SCHEMA", "SCHEMA_VERSION", "to_dict", "from_dict", "dumps", "loads"]
