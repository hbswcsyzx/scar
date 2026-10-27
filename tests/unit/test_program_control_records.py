"""Constructor-only contracts; no cleanup, graph validity or source proof."""
from dataclasses import FrozenInstanceError, fields, replace

import pytest

from scar.ir.program import control
from scar.ir.program.control import (
    ControlPort, ControlScope, ControlScopeKind, ExceptionPacketDefinition,
    LanguageCompletionKind, PendingCompletionDefinition, PendingDispatchTerminator,
    PendingPayload, PendingSuccessor, ProtocolValueKind, ProtocolValueType,
)
from scar.ir.program.ids import (
    BlockID, ControlPortID, ControlScopeID, RegionID, UseID, ValueID,
)
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import SourceAtomID


def source():
    # No canonical hash/source truth is invented by this interface declaration.
    return SourceReference(SourceAtomID("source.atom"), "declared.py",
                           "unverified-declared-version", 1, 3, 0, 12)


def scope():
    return ControlScope(ControlScopeID("function"), RegionID("body"), None,
                        ControlScopeKind.FUNCTION, source(), (BlockID("entry"),))


def port():
    return ControlPort(ControlPortID("return"), scope().id, LanguageCompletionKind.RETURN,
                       exit="normal")


def successor(name="return", block="dispatch.return"):
    return PendingSuccessor(ControlPortID(name), BlockID(block),
                            (PendingPayload(), UseID("poststate")))


def dispatch():
    return PendingDispatchTerminator(UseID("pending"), (successor(),))


@pytest.mark.parametrize("kind", tuple(ProtocolValueKind))
def test_protocol_type_kind_is_its_own_enum_not_an_ordinary_value_kind(kind):
    record = ProtocolValueType(kind)
    assert record.kind is kind
    assert type(record.kind) is ProtocolValueKind
    assert [field.name for field in fields(record)] == ["protocol"]


@pytest.mark.parametrize("wrong", ["PENDING_COMPLETION", True, False, 1, None,
                                  LanguageCompletionKind.RETURN])
def test_protocol_type_requires_exact_protocol_enum(wrong):
    with pytest.raises(TypeError):
        ProtocolValueType(wrong)


@pytest.mark.parametrize("kind", tuple(ControlScopeKind))
def test_scope_records_parent_and_direct_blocks_without_runtime_authority(kind):
    item = replace(scope(), kind=kind,
                   parent=None if kind is ControlScopeKind.FUNCTION else ControlScopeID("parent"))
    assert item.blocks == (BlockID("entry"),)
    assert item.source.fingerprint == "unverified-declared-version"
    assert not hasattr(item, "cleanup_verified")
    assert not hasattr(item, "runtime_verified")


@pytest.mark.parametrize("field,value", [
    ("id", RegionID("function")), ("id", "program_control_scope:function"),
    ("region", BlockID("body")), ("region", True),
    ("parent", RegionID("parent")), ("parent", False),
    ("kind", "FUNCTION"), ("kind", LanguageCompletionKind.RETURN),
    ("source", {}), ("source", None),
    ("blocks", [BlockID("entry")]), ("blocks", (RegionID("entry"),)),
    ("blocks", ("entry",)), ("blocks", (True,)),
])
def test_scope_rejects_untyped_fields(field, value):
    with pytest.raises(TypeError):
        replace(scope(), **{field: value})


@pytest.mark.parametrize("blocks", [(), (BlockID("entry"), BlockID("entry"))])
def test_scope_direct_blocks_are_nonempty_and_unique(blocks):
    with pytest.raises(ValueError, match="nonempty distinct"):
        replace(scope(), blocks=blocks)


def test_function_scope_forbids_parent_and_nonfunction_scope_requires_one():
    with pytest.raises(ValueError, match="must not have a parent"):
        replace(scope(), parent=ControlScopeID("parent"))
    for kind in tuple(ControlScopeKind)[1:]:
        with pytest.raises(ValueError, match="needs a parent"):
            replace(scope(), kind=kind)


@pytest.mark.parametrize("field,value", [
    ("atom_id", RegionID("source.atom")),
    ("path", True), ("fingerprint", True),
    ("start_line", True), ("end_line", True),
    ("start_column", False), ("end_column", True),
    ("start_line", 1.0), ("end_line", 3.0),
    ("start_column", 0.0), ("end_column", "12"),
])
def test_scope_rechecks_source_types_and_rejects_boolean_positions(field, value):
    reference = source()
    # Isolate this constructor's guarantee from weaker historic SourceReference
    # validation; no mutation is used by any production record implementation.
    object.__setattr__(reference, field, value)
    with pytest.raises(TypeError):
        replace(scope(), source=reference)


@pytest.mark.parametrize("field,value", [
    ("path", ""), ("fingerprint", ""), ("start_line", 0), ("end_line", 0),
    ("start_column", -1), ("end_column", -1),
])
def test_scope_rechecks_existing_source_ranges_without_inventing_a_new_hash_rule(field, value):
    reference = source()
    object.__setattr__(reference, field, value)
    with pytest.raises(ValueError):
        replace(scope(), source=reference)
    assert replace(scope(), source=replace(source(), end_column=None)).source.end_column is None


@pytest.mark.parametrize("kind,destination", [
    (LanguageCompletionKind.FALLTHROUGH, "block"),
    (LanguageCompletionKind.RETURN, "exit"),
    (LanguageCompletionKind.RAISE, "block"),
    (LanguageCompletionKind.RAISE, "exit"),
    (LanguageCompletionKind.BREAK, "block"),
    (LanguageCompletionKind.CONTINUE, "block"),
])
def test_port_all_supported_destination_shapes_are_representable(kind, destination):
    item = ControlPort(ControlPortID(kind.value), ControlScopeID("declared.owner"), kind,
                       **{destination: BlockID("target") if destination == "block" else "done"})
    assert item.kind is kind
    assert (item.block is None) != (item.exit is None)


@pytest.mark.parametrize("kind", tuple(LanguageCompletionKind))
@pytest.mark.parametrize("destinations", [{}, {"block": BlockID("target"), "exit": "done"}])
def test_port_needs_exactly_one_destination(kind, destinations):
    with pytest.raises(ValueError, match="exactly one"):
        ControlPort(ControlPortID("port"), ControlScopeID("owner"), kind, **destinations)


@pytest.mark.parametrize("kind,destination", [
    (LanguageCompletionKind.RETURN, {"block": BlockID("target")}),
    (LanguageCompletionKind.FALLTHROUGH, {"exit": "done"}),
    (LanguageCompletionKind.BREAK, {"exit": "done"}),
    (LanguageCompletionKind.CONTINUE, {"exit": "done"}),
])
def test_port_destination_shape_respects_completion_kind(kind, destination):
    with pytest.raises(ValueError):
        ControlPort(ControlPortID("port"), ControlScopeID("owner"), kind, **destination)


@pytest.mark.parametrize("field,value", [
    ("id", ControlScopeID("return")), ("scope", ControlPortID("owner")),
    ("kind", "RETURN"), ("kind", ControlScopeKind.FUNCTION),
    ("block", RegionID("target")), ("block", True),
    ("exit", True), ("exit", 0),
])
def test_port_rejects_untyped_fields(field, value):
    with pytest.raises(TypeError):
        replace(port(), **{field: value})


def test_port_exit_is_nonempty_and_scope_target_graph_checks_are_deferred():
    with pytest.raises(ValueError, match="nonempty"):
        replace(port(), exit="")
    # Ownership, actual scope kind and existence of this destination need a
    # graph. A typed declaration by itself proves none of those relationships.
    item = ControlPort(ControlPortID("break"), ControlScopeID("not.looked.up"),
                       LanguageCompletionKind.BREAK, block=BlockID("not.looked.up"))
    assert item.scope == ControlScopeID("not.looked.up")


@pytest.mark.parametrize("field,value", [
    ("value", UseID("packet")), ("value", "packet"),
    ("exception", ValueID("exception")), ("exception", True),
    ("traceback", ValueID("traceback")), ("traceback", None),
])
def test_exception_packet_requires_value_and_two_typed_operand_uses(field, value):
    item = ExceptionPacketDefinition(ValueID("packet"), UseID("exception"), UseID("traceback"))
    with pytest.raises(TypeError):
        replace(item, **{field: value})


def test_exception_packet_has_distinct_uses_without_demanding_distinct_actual_objects():
    item = ExceptionPacketDefinition(ValueID("packet"), UseID("exception"), UseID("traceback"))
    with pytest.raises(ValueError, match="distinct"):
        replace(item, traceback=item.exception)
    assert {field.name for field in fields(item)} == {"value", "exception", "traceback"}
    # Uses identify two operands; actual values, including legitimate None for
    # traceback, and state/context interpretation are not present in this record.
    assert not hasattr(item, "state") and not hasattr(item, "handler_context")


@pytest.mark.parametrize("payload", [None, UseID("evaluated.payload")])
def test_pending_completion_declares_payload_but_defers_port_kind_legality(payload):
    item = PendingCompletionDefinition(ValueID("pending"), ControlPortID("declared.port"), payload)
    assert item.payload == payload
    assert {field.name for field in fields(item)} == {"value", "port", "payload"}


@pytest.mark.parametrize("field,value", [
    ("value", UseID("pending")), ("port", ControlScopeID("port")),
    ("payload", ValueID("payload")), ("payload", True), ("payload", 0),
])
def test_pending_completion_rejects_untyped_fields(field, value):
    item = PendingCompletionDefinition(ValueID("pending"), ControlPortID("port"))
    with pytest.raises(TypeError):
        replace(item, **{field: value})


def test_pending_payload_is_only_a_zero_field_projection_marker():
    assert fields(PendingPayload) == ()
    assert PendingPayload() == PendingPayload()
    with pytest.raises(TypeError):
        PendingPayload(UseID("invented.actual"))
    with pytest.raises(TypeError):
        PendingPayload(value=ValueID("invented.actual"))


@pytest.mark.parametrize("arguments", [(), (UseID("state"),), (PendingPayload(),),
                                         (UseID("state"), PendingPayload(), UseID("other"))])
def test_successor_retains_order_of_projection_and_current_operand_uses(arguments):
    assert replace(successor(), arguments=arguments).arguments == arguments


@pytest.mark.parametrize("field,value", [
    ("port", ControlScopeID("port")), ("block", RegionID("block")),
    ("arguments", [UseID("state")]), ("arguments", (ValueID("payload"),)),
    ("arguments", (True,)), ("arguments", ({"pending_payload": True},)),
])
def test_successor_rejects_untyped_fields_and_payload_lookalikes(field, value):
    with pytest.raises(TypeError):
        replace(successor(), **{field: value})


def test_dispatch_allows_distinct_ports_sharing_one_target_without_local_use_deduplication():
    left = successor("left", "shared")
    right = successor("right", "shared")
    item = replace(dispatch(), successors=(left, right))
    assert item.successors[0].block == item.successors[1].block
    # Operand ownership and duplicate UseID handling remain core obligations.
    repeated = replace(left, arguments=(UseID("same"), UseID("same")))
    assert replace(item, successors=(repeated, right)).successors[0].arguments[0] == UseID("same")


@pytest.mark.parametrize("field,value", [
    ("pending", ValueID("pending")), ("pending", "pending"),
    ("successors", [successor()]), ("successors", (BlockID("target"),)),
    ("successors", ({"port": "return"},)),
])
def test_dispatch_rejects_untyped_operand_successors_and_containers(field, value):
    with pytest.raises(TypeError):
        replace(dispatch(), **{field: value})


def test_dispatch_needs_nonempty_unique_port_alternatives():
    with pytest.raises(ValueError, match="nonempty"):
        replace(dispatch(), successors=())
    with pytest.raises(ValueError, match="ports must be distinct"):
        replace(dispatch(), successors=(successor(), replace(successor(), block=BlockID("other"))))


def test_dispatch_compatibility_properties_are_derived_and_not_dataclass_fields():
    item = dispatch()
    assert item.kind.name == "PENDING_DISPATCH"
    assert item.condition is None and item.exit is None and item.values == ()
    assert {field.name for field in fields(item)} == {"pending", "successors"}
    assert not hasattr(item, "cleanup_verified")


@pytest.mark.parametrize("item", [
    ProtocolValueType(ProtocolValueKind.PENDING_COMPLETION), scope(), port(),
    ExceptionPacketDefinition(ValueID("packet"), UseID("exception"), UseID("traceback")),
    PendingCompletionDefinition(ValueID("pending"), ControlPortID("return")),
    PendingPayload(), successor(), dispatch(),
], ids=lambda item: type(item).__name__)
def test_all_records_are_frozen_and_slotted(item):
    assert not hasattr(item, "__dict__")
    record_fields = fields(item)
    if record_fields:
        field = record_fields[0]
        with pytest.raises(FrozenInstanceError):
            setattr(item, field.name, getattr(item, field.name))
    else:
        with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
            item.invented = True


def test_exact_types_reject_identifier_record_tuple_and_source_subclasses():
    class DerivedScopeID(ControlScopeID):
        pass

    class DerivedUseID(UseID):
        pass

    class DerivedTuple(tuple):
        pass

    class DerivedSuccessor(PendingSuccessor):
        pass

    class DerivedProjection(PendingPayload):
        pass

    class DerivedSource(SourceReference):
        pass

    with pytest.raises(TypeError):
        replace(scope(), id=DerivedScopeID("function"))
    with pytest.raises(TypeError):
        replace(scope(), blocks=DerivedTuple((BlockID("entry"),)))
    with pytest.raises(TypeError):
        replace(scope(), source=DerivedSource(SourceAtomID("atom"), "file.py", "version", 1, 1))
    with pytest.raises(TypeError):
        replace(dispatch(), pending=DerivedUseID("pending"))
    with pytest.raises(TypeError):
        replace(dispatch(), successors=DerivedTuple((successor(),)))
    with pytest.raises(TypeError):
        replace(dispatch(), successors=(DerivedSuccessor(ControlPortID("return"), BlockID("target"), ()),))
    with pytest.raises(TypeError):
        replace(successor(), arguments=DerivedTuple((UseID("state"),)))
    with pytest.raises(TypeError):
        replace(successor(), arguments=(DerivedProjection(),))


def test_public_exports_are_only_the_contract_records_and_enums():
    assert set(control.__all__) == {
        "ControlPort", "ControlScope", "ControlScopeKind", "ExceptionPacketDefinition",
        "LanguageCompletionKind", "PendingCompletionDefinition", "PendingDispatchTerminator",
        "PendingPayload", "PendingSuccessor", "ProtocolValueKind", "ProtocolValueType",
    }
