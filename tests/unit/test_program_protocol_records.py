from dataclasses import FrozenInstanceError
import subprocess
import sys
from typing import get_args, get_type_hints

import pytest

from scar.ir.program.drivers import DriverReceiverKind
from scar.ir.program.ids import (
    NativeBoundaryID, OperationID, ProtocolScopeID, RegionID, UseID, ValueID,
)
from scar.ir.program.lifecycle import DriveOutcomeRef
from scar.ir.program.model import (
    CompletionResult, InvokeLiteralResult, OperationResult,
)
from scar.ir.program.native import ExitPortRef
from scar.ir.program.protocol_rules import (
    ALLOWED_RULES, PROFILE_CLAUSES, PROFILE_FAMILY, contract_allowed,
    profile_subject, required_clauses,
)
from scar.ir.program.protocols import (
    ContractResult, DriveResult, DriverSubject, HostTerminal, NativeExit,
    NoEntryOutcome, OperationSiteSubject, OutcomeAdapter, OutcomeAdapterRule,
    PacketConstruction, PacketRule, PROTOCOL_RECORD_TAGS, ProtocolCall,
    ProtocolCallRule, ProtocolClause, ProtocolOperation, ProtocolProfile,
    ProtocolScope, RequestOperandBinding, RequestProcessing,
    RequestProcessingRule, StaticGapReason, StaticProtocolGap,
)
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.resumption import ResumableKind
from scar.ir.program.state_addresses import ExistingAccess, InvokeStateOperand
from scar.ir.program.structured import ControlEdgeReference


def _fact():
    return ProviderFactReference(
        ProviderArtifact("memory://protocol-test", "0" * 64, 0, "test"), "fixture")


def _gap(reason=StaticGapReason.NATIVE_APPLICABILITY_UNPROVEN):
    return StaticProtocolGap(reason)


def _scope(profile=ProtocolProfile.CREATED_THROW_V1):
    return ProtocolScope(
        ProtocolScopeID("scope"), profile,
        OperationSiteSubject(RegionID("region"), OperationID("site")), _fact())


def test_protocol_records_revalidate_exact_nested_ids_and_frozen_fields():
    scope = _scope()
    assert scope.subject.operation == OperationID("site")
    with pytest.raises(FrozenInstanceError):
        scope.id = ProtocolScopeID("changed")

    class StringChild(str):
        pass

    forged_region = RegionID("region")
    object.__setattr__(forged_region, "value", StringChild("region"))
    with pytest.raises(TypeError, match="exact str"):
        DriverSubject(forged_region)

    forged_id = ProtocolScopeID("nested")
    object.__setattr__(forged_id, "value", "")
    with pytest.raises(ValueError, match="nonempty"):
        ProtocolScope(forged_id, ProtocolProfile.CREATED_THROW_V1,
                      OperationSiteSubject(RegionID("r"), OperationID("o")), _fact())

    with pytest.raises(TypeError, match="exact int"):
        ProtocolOperation(ProtocolScopeID("s"), ProtocolClause.RAW_ADMISSION,
                          OperationID("o"), True,
                          RequestProcessing(UseID("raw"), (), OperationResult(OperationID("o"), 0), (),
                                            RequestProcessingRule.CHECK_THROW), _fact())


def test_protocol_result_and_state_ports_retain_their_original_classes():
    operation = OperationID("invoke")
    normal = OperationResult(OperationID("ordinary"), 0)
    invoke = InvokeLiteralResult(ControlEdgeReference(operation, 1), CompletionResult(0))
    normal_access = ExistingAccess(OperationID("ordinary"), 2)
    invoke_state = InvokeStateOperand(operation, UseID("state"))

    check = RequestProcessing(UseID("raw"), (RequestOperandBinding(0, UseID("arg")),),
                             normal, (normal_access, invoke_state),
                             RequestProcessingRule.CHECK_THROW)
    assert check.result is normal
    assert check.state_sites == (normal_access, invoke_state)
    assert get_args(get_type_hints(RequestProcessing)["result"]) == (
        OperationResult, InvokeLiteralResult, StaticProtocolGap)

    source = ContractResult(ProtocolScopeID("s"), ProtocolClause.THROW_NORMALIZATION,
                            OperationID("normalize"), 0, invoke)
    packet = PacketConstruction(ValueID("packet"), source,
                                OperationResult(OperationID("raw"), 2),
                                PacketRule.THROW_PACKET_FROM_NORMALIZED)
    assert packet.exception_source is source


def test_no_entry_contract_cannot_reference_a_body_drive_result():
    drive = DriveResult(DriveOutcomeRef(OperationID("drive"), OperationID("body.exit")), 0)
    with pytest.raises(TypeError, match="NoEntryInputPort|no-entry selected input"):
        NoEntryOutcome(UseID("instance"), UseID("request"), drive, (), None,
                       HostTerminal(OperationID("host.raise")))

    gap = _gap(StaticGapReason.PORT_UNCAPTURED)
    no_entry = NoEntryOutcome(UseID("instance"), UseID("request"), gap,
                              (InvokeStateOperand(OperationID("transition"), UseID("state")),),
                              ControlEdgeReference(OperationID("transition"), 1),
                              HostTerminal(OperationID("host.raise")))
    row = ProtocolOperation(ProtocolScopeID("created"),
        ProtocolClause.INITIAL_THROW_DELIVERED, OperationID("transition"), 1,
        no_entry, _fact())
    assert row.contract is no_entry
    assert row.contract.selected_edge.successor_index == row.slot


def test_protocol_call_and_adapter_reject_duplicate_role_use_ids():
    with pytest.raises(ValueError, match="independent"):
        ProtocolCall(UseID("receiver"), (UseID("receiver"),),
                     OperationResult(OperationID("call"), 0), (), ProtocolCallRule.AWAIT_CALL)

    with pytest.raises(ValueError, match="unique|independent"):
        RequestProcessing(UseID("raw"),
            (RequestOperandBinding(0, UseID("a")), RequestOperandBinding(0, UseID("b"))),
            OperationResult(OperationID("process"), 0), (), RequestProcessingRule.CHECK_SEND)

    adapter = OutcomeAdapter(
        ContractResult(ProtocolScopeID("s"), ProtocolClause.AWAIT_CALL,
                       OperationID("await"), 0, InvokeLiteralResult(
                           ControlEdgeReference(OperationID("await"), 0), CompletionResult(0))),
        UseID("input"), NativeExit(NativeBoundaryID("boundary"),
                                   ExitPortRef(RegionID("native"), "normal", 0)),
        OutcomeAdapterRule.AWAIT_STOPITER_TO_EXPRESSION)
    assert adapter.input_use == UseID("input")


def test_protocol_indexes_and_rule_profile_tables_are_closed_and_exact():
    with pytest.raises(ValueError, match="nonnegative"):
        DriveResult(DriveOutcomeRef(OperationID("d"), OperationID("s")), -1)
    with pytest.raises(TypeError, match="exact int"):
        DriveResult(DriveOutcomeRef(OperationID("d"), OperationID("s")), True)
    with pytest.raises(TypeError, match="tuple"):
        RequestProcessing(UseID("raw"), [RequestOperandBinding(0, UseID("arg"))],
                          OperationResult(OperationID("op"), 0), (),
                          RequestProcessingRule.CHECK_SEND)

    clauses = required_clauses(ProtocolProfile.GENERATOR_BODY_V1)
    assert ProtocolClause.BODY_INGRESS in clauses
    assert ProtocolClause.DIRECT_HOST_ADAPTER not in clauses
    assert PROFILE_FAMILY[ProtocolProfile.ASYNC_GENERATOR_BODY_V1] == (
        # These are the existing canonical enums; this table adds no receiver kind.
        ResumableKind.ASYNC_GENERATOR,
        DriverReceiverKind.ASYNC_REQUEST,
    )
    assert profile_subject(ProtocolProfile.AWAIT_SITE_V1) is OperationSiteSubject
    assert profile_subject(ProtocolProfile.GENERATOR_BODY_V1) is DriverSubject
    assert contract_allowed(
        ProtocolProfile.GENERATOR_BODY_V1, ProtocolClause.RAW_ADMISSION,
        RequestProcessing(UseID("raw"), (), OperationResult(OperationID("p"), 0), (),
                          RequestProcessingRule.CHECK_NEXT))
    assert not contract_allowed(
        ProtocolProfile.GENERATOR_BODY_V1, ProtocolClause.RAW_ADMISSION,
        RequestProcessing(UseID("raw"), (), OperationResult(OperationID("p"), 0), (),
                          RequestProcessingRule.NORMALIZE_ASYNC_THROW))
    with pytest.raises(TypeError):
        PROFILE_CLAUSES[ProtocolProfile.GENERATOR_BODY_V1] = ()
    with pytest.raises(TypeError):
        ALLOWED_RULES[(ProtocolProfile.GENERATOR_BODY_V1, ProtocolClause.RAW_ADMISSION,
                       RequestProcessing)] = frozenset()

    assert PROTOCOL_RECORD_TAGS[NoEntryOutcome] == ("kind", "PROTOCOL_NO_ENTRY_OUTCOME")
    assert all(type(key) is type for key in PROTOCOL_RECORD_TAGS)


@pytest.mark.parametrize("order", ["protocols-first", "model-first"])
def test_model_result_type_binding_is_canonical_and_import_order_safe(order):
    source = r'''
import importlib
order = __import__("sys").argv[1]
if order == "protocols-first":
    p = importlib.import_module("scar.ir.program.protocols")
    m = importlib.import_module("scar.ir.program.model")
else:
    m = importlib.import_module("scar.ir.program.model")
    p = importlib.import_module("scar.ir.program.protocols")
from typing import get_args, get_type_hints
assert get_args(get_type_hints(p.RequestProcessing)["result"]) == (
    m.OperationResult, m.InvokeLiteralResult, p.StaticProtocolGap)
assert get_args(p.ProtocolResultPort) == (
    m.OperationResult, m.InvokeLiteralResult, p.StaticProtocolGap)
'''
    result = subprocess.run([sys.executable, "-c", source, order], text=True,
                            capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
