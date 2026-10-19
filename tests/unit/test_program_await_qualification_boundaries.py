"""An unrelated native predicate cannot qualify another helper's bad return."""
from dataclasses import replace

from scar.ir.program.control import ControlScope, ControlScopeKind
from scar.ir.program.ids import (
    BlockID, ControlScopeID, OperationID, ProtocolScopeID, RegionID, UseID, ValueID,
)
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, DataValue, ExitKind, ExitPort, Operation,
    OperationResult, ProgramGraph, ReferenceValue, Region, Successor,
    Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.protocol_await_records import AwaitIteratorQualification
from scar.ir.program.protocol_connections import ProtocolOperationRef, ProtocolResultConsumers
from scar.ir.program.protocols import (
    OperationSiteSubject, OwnedUse, ProtocolClause, ProtocolOperation,
    ProtocolProfile, ProtocolScope, StaticGapReason, StaticProtocolGap,
)
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_await_qualification_graphs import unqualified_general_program
from tests.fixtures.program_control_graphs import _source


def _core_valid(graph):
    require_valid(replace(graph, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=()))


def _unrelated_qualification_program():
    """A standalone, uncalled region checks its own external reference.

    Missing method lookup/call declarations remain scope gaps. The existing
    native-predicate contract supplies no producer or caller for those stages.
    """
    owner = RegionID("await.boundary.side")
    entry, accepted, rejected = (BlockID("await.boundary.side." + name)
                                 for name in ("entry", "accepted", "rejected"))
    qid = OperationID("await.boundary.side.qualify")
    bid = OperationID("await.boundary.side.branch")
    refs = tuple(ReferenceValue(ValueID("await.boundary.side." + name), owner,
                               BlockArgument(block, 0))
                 for name, block in (("input", entry), ("accepted.value", accepted),
                                     ("rejected.value", rejected)))
    boolean = DataValue(ValueID("await.boundary.side.bool"), owner,
                        OperationResult(qid, 0), "builtins.bool")
    checked = Use(UseID("await.boundary.side.input"), refs[0].id, UseRole.REFERENCE)
    qualification = Operation(qid, "check this region's own external candidate",
        (Behavior.COMPUTE,), (checked,), (boolean.id,), effects_complete=True)
    condition = Use(UseID("await.boundary.side.condition"), boolean.id, UseRole.DATA)
    copies = tuple(Use(UseID(f"await.boundary.side.edge.{index}"), refs[0].id,
                       UseRole.REFERENCE) for index in range(2))
    branch = Operation(bid, "branch on this exact predicate", (Behavior.CONTROL,),
        (condition, *copies), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH, (
            Successor(accepted, (copies[0].id,)),
            Successor(rejected, (copies[1].id,))), condition=condition.id))
    returns = []
    for number, ref in enumerate(refs[1:]):
        actual = Use(UseID(f"await.boundary.side.return.{number}.value"),
                     ref.id, UseRole.REFERENCE)
        returns.append(Operation(OperationID(f"await.boundary.side.return.{number}"),
            "return this arm's original value", (Behavior.CONTROL,), (actual,),
            effects_complete=True, terminator=Terminator(TerminatorKind.RETURN,
                exit="normal", values=(actual.id,))))
    blocks = (
        Block(entry, (refs[0].id,), (qualification.id, branch.id)),
        Block(accepted, (refs[1].id,), (returns[0].id,)),
        Block(rejected, (refs[2].id,), (returns[1].id,)),
    )
    region = Region(owner, "independent predicate with no caller", entry, blocks,
                    (ExitPort("normal", ExitKind.NORMAL,
                              (ValueType(ValueKind.REFERENCE),)),))
    missing = StaticProtocolGap(StaticGapReason.NATIVE_APPLICABILITY_UNPROVEN)
    scope = ProtocolScope(ProtocolScopeID("await.boundary.side.scope"),
        ProtocolProfile.AWAIT_METHOD_IMPLEMENTATION_V1,
        OperationSiteSubject(owner, qualification.id), missing)
    row = ProtocolOperation(scope.id, ProtocolClause.AWAIT_ITERATOR_QUALIFICATION,
        qualification.id, 0, AwaitIteratorQualification(checked.id,
            BlockArgument(entry, 0), OperationResult(qid, 0), (), branch.id, True), missing)
    site = ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)
    return ProgramGraph(owner, (region,), (qualification, branch, *returns), (*refs, boolean),
        control_scopes=(ControlScope(ControlScopeID("await.boundary.side.function"),
            owner, None, ControlScopeKind.FUNCTION, _source("await.boundary.side"),
            tuple(block.id for block in blocks)),),
        protocol_scopes=(scope,), protocol_operations=(row,),
        protocol_result_consumers=(ProtocolResultConsumers(site,
            (OwnedUse(branch.id, condition.id),)),))


def test_uncalled_side_qualification_cannot_hide_a_known_unqualified_bad_continue():
    graph, _ = unqualified_general_program()
    _core_valid(graph)
    assert "protocol_await_return_qualification" in {issue.code for issue in validate(graph)}
    side = _unrelated_qualification_program()
    require_valid(side)
    assert all(operation.callee != side.root for operation in graph.operations)
    combined = replace(graph,
        regions=(*graph.regions, replace(side.regions[0], parent=graph.root)),
        operations=(*graph.operations, *side.operations), values=(*graph.values, *side.values),
        control_scopes=(*graph.control_scopes, *side.control_scopes),
        protocol_scopes=(*graph.protocol_scopes, *side.protocol_scopes),
        protocol_operations=(*graph.protocol_operations, *side.protocol_operations),
        protocol_result_consumers=(*graph.protocol_result_consumers,
                                   *side.protocol_result_consumers))
    _core_valid(combined)
    assert all(operation.callee != side.root for operation in combined.operations)
    assert "protocol_await_return_qualification" in {
        issue.code for issue in validate(combined)
    }
