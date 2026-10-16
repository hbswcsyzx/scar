"""C1 constructor contracts only; no CFG, activation or runtime cleanup proof."""
from dataclasses import FrozenInstanceError, fields, replace

import pytest

from scar.ir.program import cleanup
from scar.ir.program.cleanup import (
    CleanupEnter, CleanupInterface, CleanupReplace, CleanupResume,
    CleanupRouteSuccessor, CleanupRouteTerminator, HandledContextDomain,
    HandledContextRead,
)
from scar.ir.program.control import PendingPayload, PendingSuccessor
from scar.ir.program.frames import FrameRules
from scar.ir.program.ids import (
    BlockID, ControlPortID, ControlScopeID, LocationID, OperationID, RegionID,
    UseID, ValueID,
)
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.record_codec import decode, encode
from scar.ir.v2.common import ProofStatus


def interface():
    return CleanupInterface(ControlScopeID("finally"), ControlScopeID("protected"),
                            BlockID("finally.entry"), ValueID("saved.pending"))


def continuation():
    return ControlEdgeReference(OperationID("post-action.jump"), 0)


def resume():
    return CleanupResume(OperationID("resume"), interface().scope,
                         UseID("saved.pending.use"), UseID("saved.context.use"), continuation())


def replacement():
    return CleanupReplace(OperationID("replace"), interface().scope,
                          UseID("saved.pending.use"), UseID("new.pending.use"),
                          UseID("saved.context.use"), continuation())


def successor(port="return", block="next.cleanup"):
    return CleanupRouteSuccessor(ControlPortID(port), BlockID(block),
                                 (UseID("pending.use"), UseID("current.world.use")))


def route():
    return CleanupRouteTerminator(UseID("pending.use"), (successor(),))


def records():
    return (
        HandledContextDomain(RegionID("body"), LocationID("existing.world")),
        interface(),
        CleanupEnter(OperationID("enter"), interface().scope,
                     UseID("entry.pending.use"), ValueID("saved.context")),
        resume(), replacement(),
        HandledContextRead(OperationID("context.read"), ValueID("exception.reference")),
        successor(), route(),
    )


@pytest.mark.parametrize("item", records(), ids=lambda row: type(row).__name__)
def test_existing_record_codec_roundtrips_only_declared_fields(item):
    document = encode(item)
    assert decode(type(item), document) == item
    assert set(document) == {field.name for field in fields(item)}
    for invented in ("verified", "authorized", "cleanup_verified", "before", "after"):
        assert invented not in document
        with pytest.raises(ValueError, match="fields mismatch"):
            decode(type(item), {**document, invented: True})


def test_all_records_are_frozen_slotted_without_private_authority_switches():
    assert set(cleanup.__all__) == {type(item).__name__ for item in records()}
    for item in records():
        assert not hasattr(item, "__dict__")
        name = fields(item)[0].name
        with pytest.raises(FrozenInstanceError):
            setattr(item, name, getattr(item, name))
        with pytest.raises((AttributeError, TypeError)):
            setattr(item, "verified", True)


def test_ids_require_exact_namespaces_and_reject_subclasses_in_every_endpoint():
    # Exercise each actual ID field across all interfaces/actions; wire names
    # or an inherited identifier cannot silently become a canonical endpoint.
    for item in records():
        for field in fields(item):
            identity = getattr(item, field.name)
            if type(identity) not in (BlockID, ControlPortID, ControlScopeID, LocationID,
                                      OperationID, RegionID, UseID, ValueID):
                continue
            subclass = type("Derived" + type(identity).__name__, (type(identity),), {})
            wrong_namespace = ValueID("wrong") if type(identity) is not ValueID else UseID("wrong")
            for invalid in (wrong_namespace, identity.wire, subclass(identity.value), True, None):
                with pytest.raises(TypeError):
                    replace(item, **{field.name: invalid})


def test_context_domain_and_cleanup_interface_defer_existence_and_scope_checks():
    domain = HandledContextDomain(RegionID("not-looked-up"), LocationID("not-looked-up"))
    item = replace(interface(), protected=interface().scope)
    assert domain.location == LocationID("not-looked-up")
    assert item.scope == item.protected
    # These declarations are not valid whole-graph evidence. Sibling ownership,
    # entry signatures, state domains and nonreentry need the graph validator.
    assert not hasattr(domain, "state_version")
    assert not hasattr(item, "active_stack")


def test_interface_reuses_fixed_frame_rules_and_rechecks_nested_rule_tampering():
    item = interface()
    assert type(item.rules) is FrameRules
    assert item.rules.condition_status is ProofStatus.UNKNOWN
    altered = FrameRules()
    object.__setattr__(altered, "condition_status", ProofStatus.PROVEN)
    with pytest.raises(ValueError, match="must remain"):
        replace(item, rules=altered)
    subclass = type("DerivedFrameRules", (FrameRules,), {})
    for invalid in ({}, None, True, subclass()):
        with pytest.raises(TypeError):
            replace(item, rules=invalid)


@pytest.mark.parametrize("make", [resume, replacement], ids=["resume", "replace"])
def test_exit_actions_keep_the_existing_edge_reference_and_recheck_its_fields(make):
    edge = continuation()
    item = replace(make(), continuation=edge)
    assert item.continuation is edge
    assert {field.name for field in fields(edge)} == {"operation", "successor_index"}
    # No parallel block/argument/state route is invented here.
    for invalid in (OperationID("jump"), (OperationID("jump"), 0), None):
        with pytest.raises(TypeError):
            replace(item, continuation=invalid)
    for field, value in (("operation", BlockID("jump")), ("successor_index", True),
                         ("successor_index", -1), ("successor_index", 0.0)):
        bad_edge = continuation()
        object.__setattr__(bad_edge, field, value)
        with pytest.raises((TypeError, ValueError)):
            replace(item, continuation=bad_edge)
    subclass = type("DerivedEdge", (ControlEdgeReference,), {})
    with pytest.raises(TypeError):
        replace(item, continuation=subclass(edge.operation, edge.successor_index))


def test_actions_name_saved_context_and_pending_uses_without_freezing_their_payloads():
    enter, resume_action, replace_action, read = records()[2:6]
    assert type(enter.saved_context) is ValueID
    assert type(resume_action.context) is UseID
    assert type(replace_action.saved_pending) is type(replace_action.replacement) is UseID
    assert type(read.exception_result) is ValueID
    for item in (enter, resume_action, replace_action, read):
        assert not hasattr(item, "exception") and not hasattr(item, "traceback")
        assert not hasattr(item, "world") and not hasattr(item, "payload")
    # A constructor cannot establish current-activation freshness or distinguish
    # protocol types of the actual values; those are graph obligations.
    item = replace(replace_action, replacement=replace_action.saved_pending)
    assert item.replacement == item.saved_pending


@pytest.mark.parametrize("arguments", [(), (UseID("pending"),),
                                        (UseID("state"), UseID("pending"), UseID("state"))])
def test_route_successor_preserves_order_without_inventing_owned_use_checks(arguments):
    assert replace(successor(), arguments=arguments).arguments == arguments


@pytest.mark.parametrize("invalid", [[], [UseID("pending")], (PendingPayload(),),
                                     (ValueID("pending"),), (True,), (None,)])
def test_route_arguments_are_exact_use_tuples_and_never_payload_projections(invalid):
    with pytest.raises(TypeError):
        replace(successor(), arguments=invalid)


def test_route_cases_are_nonempty_port_unique_but_can_share_the_next_block():
    left, right = successor("return", "shared"), successor("raise", "shared")
    item = replace(route(), successors=(left, right))
    assert item.successors[0].block == item.successors[1].block
    with pytest.raises(ValueError, match="nonempty"):
        replace(item, successors=())
    with pytest.raises(ValueError, match="ports must be distinct"):
        replace(item, successors=(left, replace(left, block=BlockID("other"))))


def test_route_rechecks_nested_successors_and_rejects_other_control_protocols():
    item = route()
    bad = successor()
    object.__setattr__(bad, "arguments", (PendingPayload(),))
    with pytest.raises(TypeError):
        replace(item, successors=(bad,))
    for invalid in ([successor()], (PendingSuccessor(
            ControlPortID("return"), BlockID("next"), (UseID("pending"),)),), (True,)):
        with pytest.raises(TypeError):
            replace(item, successors=invalid)
    subclass = type("DerivedSuccessor", (CleanupRouteSuccessor,), {})
    edge = successor()
    with pytest.raises(TypeError):
        replace(item, successors=(subclass(edge.port, edge.block, edge.arguments),))


def test_route_terminator_properties_do_not_become_wire_fields():
    from scar.ir.program.model import TerminatorKind

    item = route()
    assert item.kind is TerminatorKind.CLEANUP_ROUTE
    assert item.condition is item.exit is None
    assert item.values == ()
    assert set(encode(item)) == {"pending", "successors"}
    assert {field.name for field in fields(item)} == {"pending", "successors"}


def test_wire_decode_rejects_projection_wrong_id_namespace_and_boolean_edge_index():
    document = encode(route())
    document["successors"][0]["arguments"][0] = {}
    with pytest.raises((TypeError, ValueError)):
        decode(CleanupRouteTerminator, document)
    document = encode(route())
    document["pending"] = ValueID("pending").as_dict()
    with pytest.raises(ValueError, match="namespace"):
        decode(CleanupRouteTerminator, document)
    document = encode(resume())
    document["continuation"]["successor_index"] = False
    with pytest.raises(ValueError):
        decode(CleanupResume, document)
