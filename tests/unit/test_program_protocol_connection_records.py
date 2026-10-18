"""P4.2 exact records; links are declarations over the original program ports."""
from dataclasses import FrozenInstanceError
from pathlib import Path
import os
import subprocess
import sys
import textwrap

import pytest

from scar.ir.program.ids import BlockID, OperationID, ProtocolScopeID, RegionID, UseID
from scar.ir.program.lifecycle import DriveOutcomeRef
from scar.ir.program.model import (
    BlockArgument, CompletionResult, InvokeLiteralResult, OperationResult, ProgramGraph,
)
from scar.ir.program.protocol_connections import (
    AsyncSessionOutcome, CancelDelivery, CancelDeliveryRef, CancelHandling,
    PROTOCOL_BINDING_TYPES,
    ProtocolCallInputCase, ProtocolCallInputs, ProtocolOperationRef,
    ProtocolResultConsumers, RawOperandSource, RawRequestTrigger,
    RequestAssociation, RequestStateCondition, RequestStateRule,
    ResumeSourceBinding, TaskCreatedTarget, TaskStatusRead, TaskStatusRule,
    TaskTargetRead, TaskTargetRole,
)
from scar.ir.program.protocols import (
    AdmissionPredicate, HostTerminal, OperationSiteSubject, OwnedUse, ProtocolClause, ProtocolOperation,
    ProtocolProfile, ProtocolScope, StaticGapReason, StaticProtocolGap,
)
from scar.ir.program.state_addresses import ExistingAccess, InvokeStateOperand
from scar.ir.program.structured import ControlEdgeReference


SCOPE = ProtocolScopeID("p4.scope")
OP = OperationID("p4.operation")
SOURCE = OperationID("p4.source")
USE = UseID("p4.use")
OWNED = OwnedUse(OP, USE)
GAP = StaticProtocolGap(StaticGapReason.PORT_UNCAPTURED)
RESULT = OperationResult(OP, 0)
EDGE_RESULT = InvokeLiteralResult(ControlEdgeReference(OP, 0), CompletionResult(0))


def test_exact_record_variants_keep_canonical_port_roles():
    formal = BlockArgument(BlockID("p4.block"), 2)
    site = ProtocolOperationRef(SCOPE, ProtocolClause.AWAIT_LOOKUP, OP, 0)
    raw_operand = RawOperandSource(OWNED, 0)
    inputs = ProtocolCallInputs(site, (
        ProtocolCallInputCase(None, formal, (raw_operand,), RawRequestTrigger(OWNED)),
    ))
    consumers = ProtocolResultConsumers(site, (OWNED, HostTerminal(SOURCE)))
    association = RequestAssociation(USE, EDGE_RESULT, OWNED,
                                     (InvokeStateOperand(OP, USE),))
    condition = RequestStateCondition(USE, (ExistingAccess(OP, 1),),
                                      RequestStateRule.IS_INITIAL_STEP)
    outcome = AsyncSessionOutcome(SCOPE, OP, DriveOutcomeRef(OP, SOURCE))
    created = TaskCreatedTarget(RESULT, OWNED, GAP)
    read = TaskTargetRead(OWNED, EDGE_RESULT, (InvokeStateOperand(OP, USE),),
                          TaskTargetRole.CURRENT_AWAITED, GAP)
    delivery = CancelDelivery(SCOPE, created, formal, OWNED)
    delivery_ref = CancelDeliveryRef.from_delivery(delivery)
    handling = CancelHandling(delivery_ref, OWNED, (ExistingAccess(OP, 1),), GAP)
    status = TaskStatusRead(SCOPE, OWNED, EDGE_RESULT,
                            (InvokeStateOperand(OP, USE),), TaskStatusRule.IS_DONE, GAP)

    assert type(inputs.cases[0].arguments[0]) is RawOperandSource
    assert inputs.cases[0].receiver is formal
    assert consumers.targets == (OWNED, HostTerminal(SOURCE))
    assert association.body is EDGE_RESULT and association.latent is OWNED
    assert condition.state_sites == (ExistingAccess(OP, 1),)
    assert type(outcome.source) is DriveOutcomeRef
    assert created.task_result is RESULT and read.target is EDGE_RESULT
    assert delivery_ref == CancelDeliveryRef(SCOPE, created, formal, OWNED)
    assert handling.delivery == delivery_ref
    assert status.state_sites == (InvokeStateOperand(OP, USE),)
    assert set(PROTOCOL_BINDING_TYPES) == {AsyncSessionOutcome, CancelDelivery,
                                           CancelHandling, TaskStatusRead}
    with pytest.raises(FrozenInstanceError):
        inputs.site = site
    with pytest.raises((AttributeError, TypeError)):
        inputs.extra = True


def test_single_guarded_call_input_case_can_represent_a_partial_declaration():
    """A lone guarded case is allowed; the graph ledger finds omitted edges."""
    site = ProtocolOperationRef(SCOPE, ProtocolClause.AWAIT_LOOKUP, OP, 0)
    edge = ControlEdgeReference(OP, 1)
    case = ProtocolCallInputCase(edge, BlockArgument(BlockID("p4.merge"), 0), (), None)
    inputs = ProtocolCallInputs(site, (case,))

    assert inputs.cases == (case,)
    assert inputs.cases[0].guard == edge


def test_new_contract_and_admission_subjects_are_exact_closed_unions():
    scope = ProtocolScope(SCOPE, ProtocolProfile.AWAIT_SITE_V1,
                          OperationSiteSubject(RegionID("p4.region"), OP), GAP)
    association = RequestAssociation(USE, RESULT, EDGE_RESULT, ())
    row = ProtocolOperation(SCOPE, ProtocolClause.ASYNC_REQUEST_ASSOCIATE,
                            OP, 0, association, GAP)
    assert type(row.contract) is RequestAssociation
    predicate = AdmissionPredicate(
        RequestStateCondition(USE, (ExistingAccess(OP, 0),), RequestStateRule.IS_COMPLETE),
        RESULT, OP)
    assert type(predicate.subject) is RequestStateCondition
    ProtocolOperation(SCOPE, ProtocolClause.RAW_ADMISSION, OP, 0, predicate, GAP)
    with pytest.raises(TypeError):
        RequestAssociation(USE, object(), EDGE_RESULT, ())
    with pytest.raises(TypeError):
        RequestStateCondition(USE, (InvokeStateOperand(OP, USE),),
                              RequestStateRule.IS_COMPLETE)
    assert scope.source is GAP


def test_constructors_revalidate_exact_nested_values_and_indices():
    with pytest.raises(TypeError):
        ProtocolOperationRef(SCOPE, ProtocolClause.AWAIT_LOOKUP, OP, True)
    with pytest.raises(TypeError):
        ProtocolCallInputCase(None, RESULT, [], None)
    with pytest.raises(ValueError):
        ProtocolCallInputs(ProtocolOperationRef(SCOPE, ProtocolClause.AWAIT_LOOKUP, OP, 0), ())
    edge = ControlEdgeReference(OP, 0)
    object.__setattr__(edge, "successor_index", True)
    with pytest.raises((TypeError, ValueError)):
        ProtocolCallInputCase(edge, RESULT, (), None)

    # frozen objects can still arrive from unsafe decoders or object.__setattr__;
    # the owner graph must rerun nested exact checks instead of trusting them.
    site = ProtocolOperationRef(SCOPE, ProtocolClause.AWAIT_LOOKUP, OP, 0)
    malformed = ProtocolCallInputs(site, (ProtocolCallInputCase(None, RESULT, (), None),))
    object.__setattr__(site, "slot", True)
    with pytest.raises(TypeError):
        ProgramGraph(RegionID("p4.root"), (), (), (), protocol_call_inputs=(malformed,))


def test_program_graph_uses_unique_natural_keys_and_exact_tuples():
    site = ProtocolOperationRef(SCOPE, ProtocolClause.AWAIT_LOOKUP, OP, 0)
    call = ProtocolCallInputs(site, (ProtocolCallInputCase(None, RESULT, (), None),))
    consumers = ProtocolResultConsumers(site, (OWNED,))
    row = AsyncSessionOutcome(SCOPE, OP, DriveOutcomeRef(OP, SOURCE))
    graph = ProgramGraph(RegionID("p4.root"), (), (), (),
                         protocol_call_inputs=(call,),
                         protocol_result_consumers=(consumers,),
                         protocol_bindings=(row,))
    assert graph.protocol_call_inputs == (call,)
    with pytest.raises(ValueError, match="sites"):
        ProgramGraph(RegionID("p4.root"), (), (), (), protocol_call_inputs=(call, call))
    with pytest.raises(ValueError, match="sites"):
        ProgramGraph(RegionID("p4.root"), (), (), (),
                     protocol_result_consumers=(consumers, consumers))
    with pytest.raises(ValueError, match="keys"):
        ProgramGraph(RegionID("p4.root"), (), (), (), protocol_bindings=(row, row))
    with pytest.raises(TypeError):
        ProgramGraph(RegionID("p4.root"), (), (), (), protocol_bindings=(object(),))
    with pytest.raises(TypeError):
        ProgramGraph(RegionID("p4.root"), (), (), (), protocol_call_inputs=[call])


def test_package_port_aliases_match_closed_model_unions_in_fresh_process():
    script = textwrap.dedent("""
        from typing import Any, get_args
        import scar.ir.program as program
        from scar.ir.program import protocol_connections as connections
        from scar.ir.program.model import BlockArgument, InvokeLiteralResult, OperationResult
        from scar.ir.program.protocols import ProtocolSourcePort

        assert program.AssociationPort is connections.AssociationPort
        assert program.ExactResultPort is connections.ExactResultPort
        assert program.ExpectedSourcePort is connections.ExpectedSourcePort
        assert Any not in get_args(program.ExpectedSourcePort)
        assert set(get_args(program.ExpectedSourcePort)) == set(get_args(ProtocolSourcePort)) | {BlockArgument}
        assert get_args(program.AssociationPort) == (
            OperationResult, InvokeLiteralResult,
            connections.OwnedUse, connections.StaticProtocolGap,
        )
        assert get_args(program.ExactResultPort) == (OperationResult, InvokeLiteralResult)
    """)
    root = Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(root)
    result = subprocess.run([sys.executable, "-c", script], cwd=root,
                            env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
