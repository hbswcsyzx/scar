"""A real split general-await acquisition and first driver call.

The parent owns A and invokes a distinct helper.  Inside that helper, the
original lookup, zero-argument ``__await__`` call, candidate qualification,
N/R failure routes and returned iterator B are separate CFG operations.  The
following original NEXT call drives B.  These declarations remain conditional
on native applicability and do not prove runtime identity.
"""
from dataclasses import replace

from scar.ir.program.control import ControlScope, ControlScopeKind, ExceptionPacketDefinition
from scar.ir.program.drivers import CreationCapture, NormalResultPort, ResumableCreate
from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.ids import (
    BlockID, ControlScopeID, OperationID, ProtocolScopeID, RegionID, UseID, ValueID,
)
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, DataValue, ExitKind, ExitPort, InvokeLiteralResult,
    Operation, OperationResult, ProtocolValue, ReferenceValue, Region,
    StateVersionValue, Successor, Terminator, TerminatorKind, Use, UseRole,
    ValueKind, ValueType,
)
from scar.ir.program.protocol_await_records import (
    AwaitAcquisition, AwaitIteratorQualification, ExpandedAwaitCallee,
)
from scar.ir.program.protocol_connections import (
    ProtocolCallInputCase, ProtocolCallInputs, ProtocolOperationRef,
    ProtocolResultConsumers,
)
from scar.ir.program.protocols import (
    ContractResult, HostTerminal, OperationSiteSubject, OwnedUse, ProtocolCall,
    ProtocolCallRule, ProtocolClause, ProtocolOperation, ProtocolProfile,
    ProtocolScope, StaticGapReason, StaticProtocolGap,
)
from scar.ir.program.resumption import ResumableKind
from scar.ir.program.state_addresses import InvokeStateOperand
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_await_pipeline_graphs import await_self_pipeline_program
from tests.fixtures.program_control_graphs import _source
from tests.fixtures.program_driver_graphs import PACKET, REFERENCE, _use


def _formal(block: BlockID, index: int, owner: RegionID, kind: str, world):
    origin = BlockArgument(block, index)
    identity = ValueID(f"{block.value}.arg.{index}")
    if kind == "reference":
        return ReferenceValue(identity, owner, origin)
    if kind == "state":
        return StateVersionValue(identity, owner, origin, world)
    if kind == "packet":
        from scar.ir.program.control import ProtocolValueKind
        return ProtocolValue(identity, owner, origin, ProtocolValueKind.EXCEPTION_PACKET)
    if kind == "bool":
        return DataValue(identity, owner, origin, "builtins.bool")
    raise ValueError(kind)


def _use_named(name, value, *, role=UseRole.REFERENCE):
    return Use(UseID(name), value, role)


def _helper_region(parent: RegionID, state_locations, body, environment,
                   entry_layout, create_rule):
    """Build the actual lookup → call → qualification callee of GET_AWAITABLE."""
    from scar.ir.program.control import ProtocolValueKind

    owner = RegionID("await.general.helper")
    entry = BlockID("await.general.helper.entry")
    lookup_n = BlockID("await.general.helper.lookup.normal")
    lookup_r = BlockID("await.general.helper.lookup.raise")
    call_n = BlockID("await.general.helper.call.normal")
    call_r = BlockID("await.general.helper.call.raise")
    accepted = BlockID("await.general.helper.accepted")
    rejected = BlockID("await.general.helper.rejected")

    state_types = tuple(ValueType(ValueKind.STATE, location=location)
                        for location in state_locations)
    entry_references = (
        _formal(entry, 0, owner, "reference", None),
        *(_formal(entry, index + 1, owner, "reference", None)
          for index, _member in enumerate(environment.members)),
    )
    entry_states = tuple(_formal(entry, len(entry_references) + index, owner,
                                 "state", location)
                         for index, location in enumerate(state_locations))
    entry_values = (*entry_references, *entry_states)

    def completion_values(block, kind):
        return (_formal(block, 0, owner, kind, None), *(
            _formal(block, index + 1, owner, "state", location)
            for index, location in enumerate(state_locations)))

    lookup_n_values = completion_values(lookup_n, "reference")
    lookup_r_values = completion_values(lookup_r, "packet")
    call_n_values = completion_values(call_n, "reference")
    call_r_values = completion_values(call_r, "packet")
    accepted_values = completion_values(accepted, "reference")
    rejected_values = completion_values(rejected, "reference")
    method = lookup_n_values[0]
    checked = DataValue(ValueID("await.general.helper.is_iterator"), owner,
                        OperationResult(OperationID("await.general.helper.qualify"), 0),
                        "builtins.bool")
    error_ref = ReferenceValue(ValueID("await.general.helper.type_error"), owner,
                               OperationResult(OperationID("await.general.helper.make_type_error"), 0))
    traceback = ReferenceValue(ValueID("await.general.helper.type_error.traceback"), owner,
                               OperationResult(OperationID("await.general.helper.make_type_error"), 1))
    packet = ProtocolValue(ValueID("await.general.helper.type_error.packet"), owner,
                           OperationResult(OperationID("await.general.helper.type_error.packet"), 0),
                           ProtocolValueKind.EXCEPTION_PACKET)

    lookup_id = OperationID("await.general.helper.lookup")
    lookup_operand = _use_named("await.general.helper.lookup.A", entry_values[0].id)
    lookup_state = tuple(_use_named(f"await.general.helper.lookup.state.{index}", value.id,
                                    role=UseRole.STATE_CONTENT)
                         for index, value in enumerate(entry_states))
    lookup = Operation(lookup_id, "lookup __await__ on the original A", (Behavior.CONTROL,),
        (lookup_operand, *lookup_state), effects_complete=False,
        invoke_arguments=tuple(use.id for use in (lookup_operand, *lookup_state)),
        completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, *state_types)),
                     CompletionSignature(ExitKind.RAISE, (PACKET, *state_types))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, lookup_n,
                                tuple(CompletionResult(index)
                                      for index in range(len(state_types) + 1))),
            CompletionSuccessor(ExitKind.RAISE, lookup_r,
                                tuple(CompletionResult(index)
                                      for index in range(len(state_types) + 1))),)))

    call_id = OperationID("await.general.helper.call")
    function_member = next(member for member in environment.members
                           if member.role is EnvironmentRole.FUNCTION_OBJECT)
    parameter_formals = tuple(parameter.value for parameter in entry_layout.parameters)
    if len(parameter_formals) != 1:
        raise ValueError("the __await__ body must have exactly its original self formal")
    function_formals = {member.reference for member in environment.members}
    if parameter_formals[0] in function_formals:
        raise ValueError("the __await__ self formal must remain separate from environment ports")
    capture_values = {parameter_formals[0]: entry_references[0]}
    capture_values[function_member.reference] = method
    capture_values.update({member.reference: entry_references[index + 1]
                           for index, member in enumerate(environment.members)
                           if member.reference != function_member.reference})
    # Derive the creation sources from the exact body formal partition.
    # The input capture uses are private environment operands of this
    # invocation, not user arguments to the bound __await__ method.
    call_capture_uses = tuple(_use_named(
        f"await.general.helper.call.capture.{index}", capture_values[formal].id)
        for index, formal in enumerate((*parameter_formals,
            *(member.reference for member in environment.members))))
    call_uses = (_use_named("await.general.helper.call.bound_method", method.id),
        *call_capture_uses,
        *(_use_named(f"await.general.helper.call.state.{index}", value.id,
                     role=UseRole.STATE_CONTENT)
          for index, value in enumerate(lookup_n_values[1:])))
    call = Operation(call_id, "invoke __await__ with no user arguments", (Behavior.CONTROL,),
        call_uses, effects_complete=False, invoke_arguments=tuple(use.id for use in call_uses),
        completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, *state_types)),
                     CompletionSignature(ExitKind.RAISE, (PACKET, *state_types))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, call_n,
                                tuple(CompletionResult(index)
                                      for index in range(len(state_types) + 1))),
            CompletionSuccessor(ExitKind.RAISE, call_r,
                                tuple(CompletionResult(index)
                                      for index in range(len(state_types) + 1))),)))

    qualify_use = _use_named("await.general.helper.qualify.input", call_n_values[0].id)
    qualify = Operation(OperationID("await.general.helper.qualify"),
        "check that the exact __await__ result is an iterator", (Behavior.COMPUTE,),
        (qualify_use,), (checked.id,), effects_complete=True)
    branch_condition = _use_named("await.general.helper.qualify.condition", checked.id,
                                  role=UseRole.DATA)
    accepted_candidate = _use_named(
        "await.general.helper.qualify.accepted_candidate", call_n_values[0].id)
    accepted_states = tuple(_use_named(
        f"await.general.helper.qualify.accepted_state.{index}", value.id,
        role=UseRole.STATE_CONTENT) for index, value in enumerate(call_n_values[1:]))
    rejected_candidate = _use_named(
        "await.general.helper.qualify.rejected_candidate", call_n_values[0].id)
    rejected_states = tuple(_use_named(
        f"await.general.helper.qualify.rejected_state.{index}", value.id,
        role=UseRole.STATE_CONTENT) for index, value in enumerate(call_n_values[1:]))
    branch = Operation(OperationID("await.general.helper.qualify.branch"),
        "take the original iterator qualification result", (Behavior.CONTROL,),
        (branch_condition, accepted_candidate, *accepted_states,
         rejected_candidate, *rejected_states), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH, (
            Successor(accepted, tuple(use.id for use in (accepted_candidate, *accepted_states))),
            Successor(rejected, tuple(use.id for use in (rejected_candidate, *rejected_states)))),
            condition=branch_condition.id))

    def terminal(name, values, *, raised):
        packet_or_value, *states = values
        uses = (_use_named(name + ".value", packet_or_value.id,
                    role=UseRole.PROTOCOL if raised else UseRole.REFERENCE),
                *(_use_named(name + f".state.{index}", state.id,
                    role=UseRole.STATE_CONTENT) for index, state in enumerate(states)))
        return Operation(OperationID(name), "exact helper completion", (Behavior.CONTROL,), uses,
            effects_complete=True,
            terminator=Terminator(TerminatorKind.RAISE if raised else TerminatorKind.RETURN,
                exit="failure" if raised else "normal", values=tuple(use.id for use in uses)))

    lookup_raise = terminal("await.general.helper.lookup.raise.exit", lookup_r_values, raised=True)
    call_raise = terminal("await.general.helper.call.raise.exit", call_r_values, raised=True)
    normal_exit = terminal("await.general.helper.return", accepted_values, raised=False)

    # The rejected qualification arm creates an explicit packet and returns it
    # through the helper's RAISE port. Its label describes the declared route;
    # it does not prove native TypeError construction.
    make_error = Operation(OperationID("await.general.helper.make_type_error"),
        "declare the TypeError object and traceback for rejected AWAIT result",
        (Behavior.COMPUTE,),
        (_use_named("await.general.helper.type_error.input", rejected_values[0].id),),
        (error_ref.id, traceback.id),
        effects_complete=True)
    packet_error = Operation(OperationID("await.general.helper.type_error.packet"),
        "construct the rejected-await exception packet", (Behavior.CONTROL,),
        (_use_named("await.general.helper.packet.exception", error_ref.id),
         _use_named("await.general.helper.packet.traceback", traceback.id)),
        (packet.id,), effects_complete=True)
    error_packet_use = _use_named("await.general.helper.rejected.packet", packet.id,
                                  role=UseRole.PROTOCOL)
    error_state_uses = tuple(_use_named(f"await.general.helper.rejected.state.{index}", value.id,
                                role=UseRole.STATE_CONTENT)
                             for index, value in enumerate(rejected_values[1:]))
    error_exit = Operation(OperationID("await.general.helper.type_error.raise"),
        "propagate the qualification failure packet", (Behavior.CONTROL,),
        (error_packet_use, *error_state_uses), effects_complete=True,
        terminator=Terminator(TerminatorKind.RAISE, exit="failure",
                              values=tuple(use.id for use in (error_packet_use, *error_state_uses))))

    blocks = (
        Block(entry, tuple(value.id for value in entry_values), (lookup.id,)),
        Block(lookup_n, tuple(value.id for value in lookup_n_values), (call.id,)),
        Block(lookup_r, tuple(value.id for value in lookup_r_values), (lookup_raise.id,)),
        Block(call_n, tuple(value.id for value in call_n_values), (qualify.id, branch.id)),
        Block(call_r, tuple(value.id for value in call_r_values), (call_raise.id,)),
        Block(accepted, tuple(value.id for value in accepted_values), (normal_exit.id,)),
        Block(rejected, tuple(value.id for value in rejected_values),
              (make_error.id, packet_error.id, error_exit.id)),
    )
    region = Region(owner, "general await acquisition helper", entry, blocks,
        (ExitPort("normal", ExitKind.NORMAL, (REFERENCE, *state_types)),
         ExitPort("failure", ExitKind.RAISE, (PACKET, *state_types))),
        parent=parent)
    operations = (lookup, call, qualify, branch, lookup_raise, call_raise, normal_exit,
                  make_error, packet_error, error_exit)
    values = (*entry_values, *lookup_n_values, *lookup_r_values, *call_n_values,
              *call_r_values, *accepted_values, *rejected_values, checked,
              error_ref, traceback, packet)
    entry_scope = ControlScope(ControlScopeID("await.general.helper.function"), owner,
        None, ControlScopeKind.FUNCTION,
        _source("await.general.helper.function"), tuple(block.id for block in blocks))
    # Each created body receives its exact function environment captures from
    # this __await__ invocation. These remain environment Uses, not protocol
    # user arguments.
    capture_by_formal = {
        formal: use for formal, use in zip(
            (*parameter_formals, *(member.reference for member in environment.members)),
            call_capture_uses, strict=True)
    }
    function_capture_use = capture_by_formal[function_member.reference]
    if function_capture_use.value != method.id:
        raise ValueError("the function-object capture must use the exact bound __await__ method")
    create = ResumableCreate(call.id, body.region, function_capture_use.id,
        tuple(CreationCapture(formal, capture_by_formal[formal].id)
              for formal in (*parameter_formals, *(member.reference for member in environment.members))),
        NormalResultPort(0), create_rule)
    return {
        "region": region, "scope": entry_scope, "operations": operations,
        "values": values, "lookup": lookup, "lookup_normal": lookup_n,
        "lookup_failure": lookup_r, "lookup_row_normal": lookup_n_values[0],
        "lookup_row_failure": lookup_r_values[0], "call": call,
        "call_normal": call_n, "call_failure": call_r, "candidate": call_n_values[0],
        "qualify": qualify, "branch": branch, "accepted": accepted,
        "rejected": rejected, "return": normal_exit, "lookup_raise": lookup_raise,
        "call_raise": call_raise, "type_error": error_exit,
        "packet_error": packet_error, "packet": packet,
        "error_ref": error_ref, "traceback": traceback, "create": create,
        "function_capture_use": function_capture_use, "bound_method_value": method.id,
        "entry": entry, "entry_values": entry_values,
        "entry_references": entry_references, "entry_states": entry_states,
        "call_normal": call_n,
    }


def await_general_program(*, result_kind=ResumableKind.GENERATOR, attach_link=True):
    """Build A→parent GET/callee helper→qualified B→original NEXT/body graph."""
    if type(result_kind) is not ResumableKind or result_kind not in (
            ResumableKind.GENERATOR, ResumableKind.GENERATOR_COROUTINE):
        raise ValueError("result_kind must be GENERATOR or GENERATOR_COROUTINE")
    from scar.ir.program.protocol_await_records import AwaitBodyLink

    graph, details = await_self_pipeline_program()
    factory = next(region for region in graph.regions if region.id == graph.root)
    values = {value.id: value for value in graph.values}
    body = replace(graph.resumable_bodies[0], kind=result_kind)
    environment = graph.environments[0]
    get = details["get"]
    base_create = graph.resumable_creates[0]
    base_create_operation = next(operation for operation in graph.operations
                                 if operation.id == base_create.operation)
    base_create_uses = {use.id: use for use in base_create_operation.uses}
    captured_values = {
        capture.formal: base_create_uses[capture.source].value
        for capture in base_create.captures
    }
    environment_values = tuple(captured_values[member.reference]
                               for member in environment.members)
    entry_layout = next(layout for layout in graph.function_entries
                        if layout.environment == environment.id)
    state_uses = tuple(get.uses[1:])
    state_locations = tuple(values[use.value].location for use in state_uses
                            if isinstance(values.get(use.value), StateVersionValue))
    if len(state_locations) != len(state_uses):
        raise ValueError("GET_AWAITABLE must preserve each original state operand")
    helper = _helper_region(factory.id, state_locations, body, environment,
                            entry_layout, base_create.rule)

    capture_uses = tuple(_use(f"factory.get_awaitable.capture.{index}", value)
                         for index, value in enumerate(environment_values))
    get_uses = (get.uses[0], *capture_uses, *state_uses)
    get = replace(get, callee=helper["region"].id, uses=get_uses,
                  invoke_arguments=tuple(use.id for use in get_uses))

    method_scope_id = ProtocolScopeID("await.general.method")
    method_gap = StaticProtocolGap(StaticGapReason.NATIVE_APPLICABILITY_UNPROVEN)
    lookup, call, qualify, branch = (helper[key] for key in ("lookup", "call", "qualify", "branch"))
    lookup_state = tuple(InvokeStateOperand(lookup.id, use.id) for use in lookup.uses
                         if isinstance(next(value for value in helper["values"]
                             if value.id == use.value), StateVersionValue))
    call_state = tuple(InvokeStateOperand(call.id, use.id) for use in call.uses
                       if isinstance(next(value for value in helper["values"]
                           if value.id == use.value), StateVersionValue))
    lookup_ports = tuple(InvokeLiteralResult(ControlEdgeReference(lookup.id, slot), CompletionResult(0))
                         for slot in range(2))
    call_ports = tuple(InvokeLiteralResult(ControlEdgeReference(call.id, slot), CompletionResult(0))
                       for slot in range(2))
    lookup_rows = tuple(ProtocolOperation(method_scope_id, ProtocolClause.AWAIT_LOOKUP,
        lookup.id, slot, ProtocolCall(lookup.uses[0].id, (), lookup_ports[slot], lookup_state,
        ProtocolCallRule.AWAIT_LOOKUP), method_gap) for slot in range(2))
    call_rows = tuple(ProtocolOperation(method_scope_id, ProtocolClause.AWAIT_CALL,
        call.id, slot, ProtocolCall(call.uses[0].id, (), call_ports[slot], call_state,
        ProtocolCallRule.AWAIT_CALL), method_gap) for slot in range(2))
    qualification_row = ProtocolOperation(method_scope_id,
        ProtocolClause.AWAIT_ITERATOR_QUALIFICATION, qualify.id, 0,
        AwaitIteratorQualification(qualify.uses[0].id,
            BlockArgument(helper["call_normal"], 0), OperationResult(qualify.id, 0),
            (), branch.id, True), method_gap)

    acquisition_scope = details["acquisition_scope"]
    references = ExpandedAwaitCallee(
        ProtocolOperationRef(method_scope_id, ProtocolClause.AWAIT_LOOKUP, lookup.id, 0),
        ProtocolOperationRef(method_scope_id, ProtocolClause.AWAIT_CALL, call.id, 0),
        ProtocolOperationRef(method_scope_id, ProtocolClause.AWAIT_ITERATOR_QUALIFICATION,
                             qualify.id, 0))
    get_rows = tuple(replace(row, contract=AwaitAcquisition(
        get.uses[0].id, BlockArgument(BlockID("factory.created"), 0),
        InvokeLiteralResult(ControlEdgeReference(get.id, row.slot), CompletionResult(0)),
        tuple(InvokeStateOperand(get.id, use.id) for use in get.uses
              if isinstance(values.get(use.value), StateVersionValue)), references))
        for row in details["get_rows"])

    def result_ref(row):
        return ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)

    lookup_success = ContractResult(method_scope_id, ProtocolClause.AWAIT_LOOKUP,
                                    lookup.id, 0, lookup_rows[0].contract.result)
    call_success = ContractResult(method_scope_id, ProtocolClause.AWAIT_CALL,
                                  call.id, 0, call_rows[0].contract.result)
    # The qualification candidate is the independent __await__ NORMAL port;
    # the actual drive later in the caller is not used to select it.
    qualification_expected = BlockArgument(helper["call_normal"], 0)
    method_inputs = tuple(ProtocolCallInputs(result_ref(row), (
        ProtocolCallInputCase(None,
            BlockArgument(helper["region"].entry, 0) if row.operation == lookup.id
            else lookup_success, (), None),)) for row in (*lookup_rows, *call_rows))
    method_consumers = (
        ProtocolResultConsumers(result_ref(lookup_rows[0]),
            (OwnedUse(call.id, call.uses[0].id),)),
        ProtocolResultConsumers(result_ref(lookup_rows[1]),
            (HostTerminal(helper["lookup_raise"].id),)),
        ProtocolResultConsumers(result_ref(call_rows[0]),
            (OwnedUse(qualify.id, qualify.uses[0].id),)),
        ProtocolResultConsumers(result_ref(call_rows[1]),
            (HostTerminal(helper["call_raise"].id),)),
        ProtocolResultConsumers(result_ref(qualification_row),
            (OwnedUse(branch.id, branch.uses[0].id),)),
    )
    method_scope = ProtocolScope(method_scope_id, ProtocolProfile.AWAIT_METHOD_IMPLEMENTATION_V1,
        OperationSiteSubject(helper["region"].id, lookup.id), method_gap)

    helper_create = helper["create"]
    result_operations = tuple(get if operation.id == get.id else operation
                               for operation in graph.operations)
    factory_blocks = tuple(replace(block, operations=(get.id,))
        if block.id == BlockID("factory.created") else block for block in factory.blocks)
    factory = replace(factory, blocks=factory_blocks)
    control_scopes = tuple(replace(scope, blocks=tuple(block.id for block in factory.blocks))
        if scope.region == factory.id else scope for scope in graph.control_scopes)
    helper_failure_host = details["get_failure"]
    base_consumers = tuple(graph.protocol_result_consumers)
    links = tuple(AwaitBodyLink(
        ProtocolOperationRef(acquisition_scope, ProtocolClause.AWAIT_ACQUISITION,
                             get.id, 0),
        result_ref(row), OperationID("driver.drive"), None, None)
        for row in details["call_rows"])
    result = replace(graph,
        regions=tuple(factory if region.id == factory.id else region for region in graph.regions)
               + (helper["region"],),
        operations=(*result_operations, *helper["operations"]),
        values=(*graph.values, *helper["values"]),
        resumable_bodies=(body,),
        resumable_creates=(helper_create,),
        protocol_scopes=(*graph.protocol_scopes, method_scope),
        protocol_operations=tuple(row for row in graph.protocol_operations
            if row.operation != details["get"].id) + (*get_rows, *lookup_rows, *call_rows,
                qualification_row),
        protocol_call_inputs=(*graph.protocol_call_inputs, *method_inputs),
        protocol_result_consumers=(*base_consumers, *method_consumers),
        exception_packets=(*graph.exception_packets,
            ExceptionPacketDefinition(helper["packet"].id,
                helper["packet_error"].uses[0].id,
                helper["packet_error"].uses[1].id)),
        protocol_bindings=tuple(row for row in graph.protocol_bindings
            if not isinstance(row, AwaitBodyLink)) + (links if attach_link else ()),
        control_scopes=(*control_scopes, helper["scope"]))
    return result, {
        **details, "get": get, "get_rows": get_rows, "helper": helper["region"],
        "helper_lookup": lookup, "helper_call": call, "qualification": qualify,
        "qualification_branch": branch, "method_scope": method_scope_id,
        "method_lookup_rows": lookup_rows, "method_call_rows": call_rows,
        "qualification_row": qualification_row, "helper_create": helper_create,
        "helper_create_operation": call, "helper_lookup_raise": helper["lookup_raise"],
        "helper_call_raise": helper["call_raise"],
        "helper_type_error": helper["type_error"], "helper_entry": helper["entry"],
        "helper_return": helper["return"],
        "helper_entry_values": helper["entry_values"],
        "helper_call_normal": helper["call_normal"],
        "function_capture_use": helper["function_capture_use"],
        "bound_method_value": helper["bound_method_value"],
        "links": links,
        "A": BlockArgument(BlockID("factory.created"), 0),
        "B": qualification_expected, "lookup_success": lookup_success,
        "call_success": call_success,
        "get_failure": helper_failure_host,
        "accepted_edge": ControlEdgeReference(branch.id, 0),
        "rejected_edge": ControlEdgeReference(branch.id, 1),
    }


__all__ = ["await_general_program"]
