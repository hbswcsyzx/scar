"""Original readonly predicate/bool/branch ports, not a native phase capture."""
from dataclasses import replace

from scar.ir.program.ids import BlockID, OperationID, ProtocolScopeID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, DataValue, ExitKind, ExitPort,
    Operation, OperationResult, ReferenceValue, StateAccess, StateVersionValue,
    Successor, Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.protocols import (
    AdmissionPredicate, BodyStateCondition, BodyStatePredicateRule, DriverSubject,
    ProtocolClause, ProtocolOperation, ProtocolProfile, ProtocolScope,
    ReferenceIsNoneCondition,
)
from scar.ir.program.state_addresses import ExistingAccess
from tests.fixtures.program_protocol_graphs import no_entry_throw_program


def admission_program(*, subject="body", rule=BodyStatePredicateRule.IS_RUNNING):
    """One true helper path and false return; raw/source applicability stays open.

    The phase predicate consumes only its body and one actual coarse READ.
    The None predicate consumes only a separate original Reference input.
    Neither primitive consumes the scheduler raw. Existing helper NORMAL/RAISE
    state and payload routes remain real; this fixture declares no F transition.
    """
    if subject not in ("body", "none"):
        raise ValueError("subject must be body or none")
    graph, prior = no_entry_throw_program(reject=True)
    interface, = graph.driver_interfaces
    region = next(row for row in graph.regions if row.id == interface.region)
    entry = next(block for block in region.blocks if block.id == region.entry)
    values = {value.id: value for value in graph.values}
    originals = tuple(values[identity] for identity in entry.arguments)
    states = tuple(value for value in originals if type(value) is StateVersionValue)
    predicate_id, branch_id = OperationID("admission.read"), OperationID("admission.branch")
    helper_block, false_block = BlockID("admission.helper"), BlockID("admission.false")
    bool_value = DataValue(ValueID("admission.bool"), region.id,
                           OperationResult(predicate_id, 0), "builtins.bool")
    added = [bool_value]
    if subject == "body":
        instance = Use(UseID("admission.instance"), interface.receiver, UseRole.REFERENCE)
        before = Use(UseID("admission.before"), states[0].id, UseRole.STATE_CONTENT)
        predicate = Operation(predicate_id, "read body state", (Behavior.CONTROL, Behavior.READ),
            (instance, before), (bool_value.id,),
            # A coarse domain read does not claim a precise physical alias
            # for this reference whose targets are still unknown.
            accesses=(StateAccess(states[0].location, before.id, AccessMode.READ),),
            effects_complete=True)
        condition = BodyStateCondition(instance.id, (ExistingAccess(predicate.id, 0),), rule)
        entry_arguments = entry.arguments
        input_id = instance.value
    else:
        input_value = ReferenceValue(ValueID("admission.input"), region.id,
                                     BlockArgument(entry.id, len(entry.arguments)))
        added.append(input_value)
        input_use = Use(UseID("admission.input.use"), input_value.id, UseRole.REFERENCE)
        predicate = Operation(predicate_id, "reference is None", (Behavior.COMPUTE,),
                              (input_use,), (bool_value.id,), effects_complete=True)
        condition = ReferenceIsNoneCondition(input_use.id)
        entry_arguments = (*entry.arguments, input_value.id)
        input_id = input_value.id
    bool_use = Use(UseID("admission.condition"), bool_value.id, UseRole.DATA)
    forwards, successors, landings = [], [], []
    for number, destination in enumerate((helper_block, false_block)):
        formals, actuals = [], []
        for position, original in enumerate(originals):
            formal = replace(original, id=ValueID(f"admission.edge.{number}.{position}"),
                             origin=BlockArgument(destination, position))
            added.append(formal)
            formals.append(formal.id)
            role = (UseRole.STATE_CONTENT if type(original) is StateVersionValue else
                    UseRole.REFERENCE if type(original) is ReferenceValue else UseRole.PROTOCOL)
            actual = Use(UseID(f"admission.forward.{number}.{position}"), original.id, role)
            forwards.append(actual)
            actuals.append(actual.id)
        successors.append(Successor(destination, tuple(actuals)))
        landings.append(tuple(formals))
    branch = Operation(branch_id, "branch on original predicate", (Behavior.CONTROL,),
                       (bool_use, *forwards), effects_complete=True,
                       terminator=Terminator(TerminatorKind.BRANCH, tuple(successors),
                                             condition=bool_use.id))
    replacement = dict(zip(entry.arguments, landings[0]))
    helper = next(operation for operation in graph.operations if operation.id == prior["processing"])
    helper = replace(helper, uses=tuple(replace(use, value=replacement.get(use.value, use.value))
                                       for use in helper.uses))
    false_state_ids = tuple(identity for identity, original in zip(landings[1], originals)
                            if type(original) is StateVersionValue)
    false_owner = landings[1][entry.arguments.index(interface.receiver)]
    result_uses = (Use(UseID("admission.false.result"), false_owner, UseRole.REFERENCE),
        *(Use(UseID(f"admission.false.state.{number}"), identity, UseRole.STATE_CONTENT)
          for number, identity in enumerate(false_state_ids)))
    terminal = Operation(OperationID("admission.false.return"), "unselected ordinary result",
        (Behavior.CONTROL,), result_uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.RETURN, exit="admission.normal",
                              values=tuple(use.id for use in result_uses)))
    blocks = tuple(replace(block, arguments=entry_arguments, operations=(predicate.id, branch.id))
                   if block.id == entry.id else block for block in region.blocks)
    blocks += (Block(helper_block, landings[0], (helper.id,)),
               Block(false_block, landings[1], (terminal.id,)))
    normal_types = (ValueType(ValueKind.REFERENCE),
                    *(ValueType(ValueKind.STATE, location=state.location) for state in states))
    region = replace(region, blocks=blocks,
                     exits=(*region.exits, ExitPort("admission.normal", ExitKind.NORMAL, normal_types)))
    scope = ProtocolScope(ProtocolScopeID("admission.scope"), ProtocolProfile.GENERATOR_BODY_V1,
                          DriverSubject(region.id), graph.protocol_scopes[0].source)
    contract = AdmissionPredicate(condition, OperationResult(predicate.id, 0), branch.id)
    row = ProtocolOperation(scope.id, ProtocolClause.RAW_ADMISSION, predicate.id, 0,
                            contract, scope.source)
    graph = replace(graph,
        regions=tuple(region if item.id == region.id else item for item in graph.regions),
        operations=tuple(helper if op.id == helper.id else op for op in graph.operations)
                   + (predicate, branch, terminal), values=(*graph.values, *added),
        protocol_scopes=(scope,), protocol_operations=(row,),
        control_scopes=tuple(replace(item, blocks=tuple(block.id for block in blocks))
                             if item.region == region.id else item for item in graph.control_scopes))
    return graph, {"scope": scope.id, "predicate": predicate.id, "branch": branch.id,
                   "condition_use": bool_use.id, "input": input_id,
                   "row": row, "state_sites": contract.state_sites}


__all__ = ["admission_program"]
