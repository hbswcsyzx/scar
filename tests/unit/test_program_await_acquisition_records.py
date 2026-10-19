"""Exact Program23 declarations retain ports without claiming native identity."""
from dataclasses import FrozenInstanceError, fields, replace
from typing import Any, get_args, get_type_hints

import pytest

from scar.ir.program import codec
from scar.ir.program.ids import BlockID, OperationID, ProtocolScopeID, UseID
from scar.ir.program.model import (
    BlockArgument, CompletionResult, InvokeLiteralResult, OperationResult, ProgramGraph,
)
from scar.ir.program.protocol_await_records import (
    AWAIT_ACQUISITION_RECORD_TAGS, AwaitAcquisition, AwaitBodyLink,
    AwaitIteratorQualification, CoroutineAwaitWrapper, ExpandedAwaitCallee,
    WrapperHeldBody, has_await_acquisition_capability,
)
from scar.ir.program.protocol_connections import (
    PROTOCOL_CONNECTION_RECORD_TAGS, ProtocolOperationRef,
    has_protocol_connection_capability,
)
from scar.ir.program.protocol_rules import contract_allowed, required_clauses
from scar.ir.program.protocols import (
    OwnedUse, ProtocolClause as C, ProtocolOperation, ProtocolProfile as F,
    PROTOCOL_RECORD_TAGS, StaticGapReason, StaticProtocolGap,
)
from scar.ir.program.state_addresses import (
    STATE_ADDRESS_RECORD_TAGS, ExistingAccess, InvokeStateOperand,
)
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.record_codec import decode, encode


def _port(name="acquire", edge=1, slot=2):
    return InvokeLiteralResult(ControlEdgeReference(OperationID(name), edge),
                               CompletionResult(slot))


def _ref(name="acquire", clause=C.AWAIT_ACQUISITION):
    return ProtocolOperationRef(ProtocolScopeID(name + ".scope"), clause,
                                OperationID(name), 1)


def _records():
    source = BlockArgument(BlockID("entry"), 0)
    sites = (InvokeStateOperand(OperationID("acquire"), UseID("world")),)
    gap = StaticProtocolGap(StaticGapReason.PORT_UNCAPTURED)
    expanded = ExpandedAwaitCallee(_ref("lookup", C.AWAIT_LOOKUP),
        _ref("call", C.AWAIT_CALL), _ref("check", C.AWAIT_ITERATOR_QUALIFICATION))
    acquire = AwaitAcquisition(UseID("operand"), source, _port(), sites, expanded)
    qualify = AwaitIteratorQualification(UseID("candidate"), source, _port("check"),
                                         (), None, None)
    wrapper = CoroutineAwaitWrapper(UseID("body"), source, _port("constructor"), ())
    held = WrapperHeldBody(_ref("constructor", C.WRAPPER_CONSTRUCTION), source,
        OwnedUse(OperationID("constructor"), UseID("body")),
        OwnedUse(OperationID("getter"), UseID("wrapper")),
        OperationResult(OperationID("getter"), 0),
        (ExistingAccess(OperationID("getter"), 0),))
    link = AwaitBodyLink(_ref(), _ref("advance", C.DELEGATE_ADVANCE),
                         OperationID("drive"), held, ControlEdgeReference(OperationID("branch"), 1))
    return acquire, expanded, qualify, wrapper, held, link, gap


TAGS = {**PROTOCOL_RECORD_TAGS, **PROTOCOL_CONNECTION_RECORD_TAGS,
        **STATE_ADDRESS_RECORD_TAGS, **AWAIT_ACQUISITION_RECORD_TAGS,
        InvokeLiteralResult: ("kind", "INVOKE_LITERAL_RESULT")}


def test_new_records_roundtrip_the_original_namespaces_and_closed_late_bound_unions():
    for row in _records()[:-1]:
        wire = encode(row, record_tags=TAGS)
        assert decode(type(row), wire, record_tags=TAGS) == row
        assert not hasattr(row, "__dict__")
        assert get_type_hints(type(row))
        assert Any not in get_type_hints(type(row)).values()
    acquire, _, _, _, _, link, _ = _records()
    assert link.scope == link.source.scope
    assert "scope" not in {member.name for member in fields(link)}
    assert acquire.result.edge.successor_index == 1
    assert acquire.result.result.index == 2
    union = get_type_hints(ProtocolOperation)["contract"]
    assert AwaitAcquisition in get_args(union)
    bindings = get_args(get_type_hints(ProgramGraph)["protocol_bindings"])[0]
    assert AwaitBodyLink in get_args(bindings)
    with pytest.raises(FrozenInstanceError):
        link.drive = OperationID("replacement")
    with pytest.raises(TypeError):
        AWAIT_ACQUISITION_RECORD_TAGS[AwaitBodyLink] = ("kind", "OTHER")


@pytest.mark.parametrize("accepts_true", (True, False))
def test_boolean_qualification_keeps_polarity_and_original_input_not_an_iterator_result(accepts_true):
    source = BlockArgument(BlockID("entry"), 0)
    row = AwaitIteratorQualification(UseID("input"), source,
        OperationResult(OperationID("check"), 0), (), OperationID("branch"), accepts_true)
    assert row.accepts_true is accepts_true and row.input_use == UseID("input")
    assert decode(type(row), encode(row, record_tags=TAGS), record_tags=TAGS) == row


@pytest.mark.parametrize("change", (
    "invoke_with_polarity", "ordinary_without_branch", "branch_with_invoke",
    "boolean_branch", "integer_polarity", "missing_polarity",
))
def test_qualification_modes_cannot_be_forged_by_union_or_bool_coercion(change):
    row = _records()[2]
    kwargs = {
        "invoke_with_polarity": {"accepts_true": False},
        "ordinary_without_branch": {"result": OperationResult(OperationID("check"), 0)},
        "branch_with_invoke": {"branch": OperationID("branch"), "accepts_true": True},
        "boolean_branch": {"branch": True, "accepts_true": True},
        "integer_polarity": {"result": OperationResult(OperationID("check"), 0),
                             "branch": OperationID("branch"), "accepts_true": 1},
        "missing_polarity": {"result": OperationResult(OperationID("check"), 0),
                             "branch": OperationID("branch")},
    }[change]
    with pytest.raises((TypeError, ValueError)):
        replace(row, **kwargs)


@pytest.mark.parametrize("row_index,field,bad", (
    (0, "operand_use", OperationID("wrong-namespace")),
    (0, "expected", _ref()),
    (0, "state_sites", []),
    (0, "expansion", None),
    (0, "result", OperationResult(OperationID("acquire"), 0)),
    (1, "lookup", StaticProtocolGap(StaticGapReason.PORT_UNCAPTURED)),
    (1, "call", {}),
    (3, "result", OperationResult(OperationID("constructor"), 0)),
    (4, "body", UseID("bare-use")),
    (4, "body_result", StaticProtocolGap(StaticGapReason.PORT_UNCAPTURED)),
    (5, "drive", UseID("wrong-namespace")),
    (5, "projection", {}),
    (5, "guard", False),
))
def test_new_records_reject_wrong_port_families_and_structural_variants(row_index, field, bad):
    with pytest.raises((TypeError, ValueError)):
        replace(_records()[row_index], **{field: bad})


@pytest.mark.parametrize("mutation", ("id_class", "id_text", "slot", "state_index"))
def test_parent_construction_rechecks_mutated_frozen_nested_records(mutation):
    acquire, expanded, _, _, held, _, _ = _records()
    if mutation == "id_class":
        class DerivedUse(UseID):
            pass
        value = OwnedUse(OperationID("constructor"), UseID("body"))
        object.__setattr__(value, "use", DerivedUse("body"))
        build = lambda: replace(held, body=value)
    elif mutation == "id_text":
        class DerivedText(str):
            pass
        identity = OperationID("lookup")
        object.__setattr__(identity, "value", DerivedText("lookup"))
        value = replace(expanded.lookup, operation=OperationID("lookup"))
        object.__setattr__(value, "operation", identity)
        build = lambda: replace(expanded, lookup=value)
    elif mutation == "slot":
        value = _port()
        object.__setattr__(value.result, "index", True)
        build = lambda: replace(acquire, result=value)
    else:
        value = ExistingAccess(OperationID("getter"), 0)
        object.__setattr__(value, "index", True)
        build = lambda: replace(held, state_sites=(value,))
    with pytest.raises((TypeError, ValueError)):
        build()


def test_duplicate_state_refs_and_duplicate_body_link_natural_keys_are_rejected():
    acquire, _, _, _, _, link, _ = _records()
    with pytest.raises(ValueError):
        replace(acquire, state_sites=acquire.state_sites * 2)
    from tests.fixtures.program_continuation_graphs import continuation_site_program
    graph, _ = continuation_site_program(kind="await")
    # Natural-key uniqueness is a record invariant, independent of unresolved FKs.
    with pytest.raises(ValueError, match="binding keys"):
        replace(graph, protocol_bindings=(link, replace(link, projection=None)))


@pytest.mark.parametrize("index,profile,clause", (
    (0, F.AWAIT_ACQUISITION_V1, C.AWAIT_ACQUISITION),
    (2, F.AWAIT_METHOD_IMPLEMENTATION_V1, C.AWAIT_ITERATOR_QUALIFICATION),
    (3, F.COROUTINE_WRAPPER_CONSTRUCTION_V1, C.WRAPPER_CONSTRUCTION),
))
def test_each_new_local_contract_has_one_closed_profile_clause(index, profile, clause):
    row = _records()[index]
    for candidate_profile in F:
        for candidate_clause in C:
            assert contract_allowed(candidate_profile, candidate_clause, row) is (
                candidate_profile is profile and candidate_clause is clause)
    assert clause in required_clauses(profile)


def test_capability_detects_new_enums_inside_old_refs_without_string_false_positives():
    from tests.fixtures.program_continuation_graphs import continuation_site_program
    graph, _ = continuation_site_program(kind="await")
    harmless = replace(graph, operations=tuple(
        replace(op, label="AWAIT_ACQUISITION_V1 WRAPPER_HELD_BODY") for op in graph.operations))
    assert not has_await_acquisition_capability(harmless)
    row = graph.protocol_operations[0]
    changed = replace(graph, protocol_operations=(replace(row, clause=C.AWAIT_ACQUISITION),))
    assert has_await_acquisition_capability(changed)
    assert has_protocol_connection_capability(changed)
    assert codec.SCHEMA_VERSION == 23
