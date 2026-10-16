"""Protocol SSA values retain precise types and canonical origins."""
from dataclasses import replace

import pytest

from scar.ir.program import (
    BlockArgument, BlockID, LiteralOrigin, OperationID, OperationResult,
    ProtocolValue, ProtocolValueKind, ProtocolValueType, RegionID, ValueID, value_type,
)
from scar.ir.record_codec import decode, encode


@pytest.mark.parametrize("kind", tuple(ProtocolValueKind))
@pytest.mark.parametrize("origin", [BlockArgument(BlockID("entry"), 0),
                                    OperationResult(OperationID("pack"), 0)])
def test_protocol_values_roundtrip_as_a_distinct_typed_value(kind, origin):
    value = ProtocolValue(ValueID("value"), RegionID("region"), origin, kind)
    assert value_type(value) == ProtocolValueType(kind)
    assert decode(ProtocolValue, encode(value)) == value


@pytest.mark.parametrize("field,value", [
    ("id", OperationID("value")), ("id", "program_value:value"), ("id", False),
    ("region", BlockID("region")), ("region", True),
    ("origin", LiteralOrigin(None)), ("origin", {}),
    ("protocol", "PENDING_COMPLETION"), ("protocol", None), ("protocol", True),
])
def test_protocol_constructor_rejects_plain_values_wrong_ids_and_literals(field, value):
    record = ProtocolValue(ValueID("value"), RegionID("region"),
                           OperationResult(OperationID("pack"), 0),
                           ProtocolValueKind.PENDING_COMPLETION)
    with pytest.raises((TypeError, ValueError)):
        replace(record, **{field: value})
