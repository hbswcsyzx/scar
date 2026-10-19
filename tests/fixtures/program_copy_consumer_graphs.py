"""Original copy-consumer graphs assembled from canonical Program ports.

These fixtures declare static CALL/INVOKE paths only. They do not assert
runtime execution, source applicability, or object identity.
"""
from dataclasses import replace

from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, DataValue, ExitKind, ExitPort,
    Operation, OperationResult, ProgramGraph, ReferenceValue, Region,
    StateLocation, StateVersionValue, Terminator, TerminatorKind, Use,
    UseRole, ValueKind, ValueType,
)
from scar.ir.program.protocols import OwnedUse
from tests.fixtures.program_await_outcome_graphs import await_outcome_program
from tests.fixtures.program_call_composition_graphs import (
    call_composition_program, duplicate_argument_composition_program,
    distinct_call_composition_program, loop_call_composition_program,
)
from tests.fixtures.program_call_return_graphs import (
    call_return_program, multi_return_program, recursive_return_program,
)
from tests.fixtures.program_call_return_state_graphs import call_return_state_program


REFERENCE = ValueType(ValueKind.REFERENCE)
WORLD = LocationID("copy-consumer.world")
STATE = ValueType(ValueKind.STATE, location=WORLD)


def _use(name, value):
    return Use(UseID(name), value.id,
               UseRole.STATE_CONTENT if isinstance(value, StateVersionValue)
               else UseRole.REFERENCE)


def _reference(name, region, block, index):
    return ReferenceValue(ValueID(name), region, BlockArgument(block, index))


def _state(name, region, block, index):
    return StateVersionValue(ValueID(name), region, BlockArgument(block, index), WORLD)


def _multi_argument_program(*, calls=2, duplicate_actuals=False, duplicate_return=False,
                            opaque_consumer=False):
    """A shared two-payload helper with distinct original input and return Uses.

    With two calls the second caller swaps the payload ordinals. Both calls use
    the same static helper and the helper's same two internal consumer Uses.
    """
    root, helper = RegionID("copy-consumer.root"), RegionID("copy-consumer.helper")
    root_entry = BlockID("copy-consumer.root.entry")
    helper_entry = BlockID("copy-consumer.helper.entry")

    x = _reference("copy-consumer.root.x", root, root_entry, 0)
    y = _reference("copy-consumer.root.y", root, root_entry, 1)
    root_state = _state("copy-consumer.root.state", root, root_entry, 2)
    left = _reference("copy-consumer.helper.left", helper, helper_entry, 0)
    right = _reference("copy-consumer.helper.right", helper, helper_entry, 1)
    helper_state = _state("copy-consumer.helper.state", helper, helper_entry, 2)

    inspect_id = OperationID("copy-consumer.helper.inspect")
    left_use = _use("copy-consumer.helper.inspect.left", left)
    right_use = _use("copy-consumer.helper.inspect.right", right)
    inspected = DataValue(ValueID("copy-consumer.helper.inspected"), helper,
                          OperationResult(inspect_id, 0), "builtins.int")
    inspect = Operation(inspect_id, "original two-input consumer", (Behavior.COMPUTE,),
        (left_use, right_use), (inspected.id,), effects_complete=not opaque_consumer)

    terminal_id = OperationID("copy-consumer.helper.return")
    returned_values = (left, left if duplicate_return else right, helper_state)
    terminal_uses = tuple(_use(f"copy-consumer.helper.return.{index}", value)
                          for index, value in enumerate(returned_values))
    terminal = Operation(terminal_id, "original multi-slot helper return", (Behavior.CONTROL,),
        terminal_uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                              values=tuple(item.id for item in terminal_uses)))

    result_ids = []
    result_values = []
    call_ops = []
    call_actuals = {}
    current_state = root_state
    for number in range(calls):
        identity = OperationID(f"copy-consumer.root.call.{number}")
        if duplicate_actuals:
            payloads = (x, x)
        elif number == 1:
            payloads = (y, x)
        else:
            payloads = (x, y)
        actual_values = (*payloads, current_state)
        actual_uses = tuple(_use(f"{identity.value}.actual.{index}", value)
                            for index, value in enumerate(actual_values))
        outputs = (
            ReferenceValue(ValueID(f"{identity.value}.result.0"), root,
                           OperationResult(identity, 0)),
            ReferenceValue(ValueID(f"{identity.value}.result.1"), root,
                           OperationResult(identity, 1)),
            StateVersionValue(ValueID(f"{identity.value}.state"), root,
                              OperationResult(identity, 2), WORLD),
        )
        operation = Operation(identity, "original shared-helper CALL", (Behavior.CONTROL,),
            actual_uses, tuple(value.id for value in outputs), callee=helper,
            call_arguments=tuple(item.id for item in actual_uses), effects_complete=True)
        call_ops.append(operation)
        call_actuals[identity] = tuple(OwnedUse(identity, item.id) for item in actual_uses)
        result_ids.append(tuple(value.id for value in outputs))
        result_values.extend(outputs)
        current_state = outputs[2]

    root_terminal_id = OperationID("copy-consumer.root.return")
    final_values = (*tuple(next(value for value in result_values if value.id == identity)
                           for identity in result_ids[-1][:2]), current_state)
    root_terminal_uses = tuple(_use(f"copy-consumer.root.return.{index}", value)
                               for index, value in enumerate(final_values))
    root_terminal = Operation(root_terminal_id, "original caller return", (Behavior.CONTROL,),
        root_terminal_uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                              values=tuple(item.id for item in root_terminal_uses)))

    root_exits = (ExitPort("normal", ExitKind.NORMAL, (REFERENCE, REFERENCE, STATE)),)
    helper_exits = (ExitPort("normal", ExitKind.NORMAL, (REFERENCE, REFERENCE, STATE)),)
    root_operations = tuple(item.id for item in (*call_ops, root_terminal))
    root_region = Region(root, "shared helper callers", root_entry,
        (Block(root_entry, (x.id, y.id, root_state.id), root_operations),), root_exits)
    helper_region = Region(helper, "two-input shared helper", helper_entry,
        (Block(helper_entry, (left.id, right.id, helper_state.id),
               (inspect.id, terminal.id)),), helper_exits, parent=root)
    graph = ProgramGraph(root, (root_region, helper_region),
        (*call_ops, inspect, terminal, root_terminal),
        (x, y, root_state, left, right, helper_state, inspected, *result_values),
        locations=(StateLocation(WORLD, "original state port"),))
    return graph, {
        "source": BlockArgument(root_entry, 0),
        "other_source": BlockArgument(root_entry, 1),
        "root": root,
        "helper": helper,
        "calls": tuple(item.id for item in call_ops),
        "call_actuals": call_actuals,
        "formal_values": (left.id, right.id, helper_state.id),
        "inspect": inspect.id,
        "inspect_uses": (OwnedUse(inspect.id, left_use.id), OwnedUse(inspect.id, right_use.id)),
        "helper_return": terminal.id,
        "helper_return_uses": tuple(OwnedUse(terminal.id, item.id) for item in terminal_uses),
        "helper_return_values": tuple(item.value for item in terminal_uses),
        "root_terminal": root_terminal.id,
        "root_terminal_uses": tuple(OwnedUse(root_terminal.id, item.id)
                                    for item in root_terminal_uses),
        "call_result_ids": tuple(result_ids),
        "duplicate_actuals": duplicate_actuals,
        "duplicate_return": duplicate_return,
        "opaque_consumer": opaque_consumer,
    }


def swapped_shared_callee_program():
    return _multi_argument_program(calls=2)


def duplicate_actual_program():
    return _multi_argument_program(calls=1, duplicate_actuals=True)


def duplicate_return_program():
    return _multi_argument_program(calls=1, duplicate_actuals=True, duplicate_return=True)


def distinct_payload_return_program():
    return _multi_argument_program(calls=1)


def opaque_internal_consumer_program():
    return _multi_argument_program(calls=1, opaque_consumer=True)


def nested_copy_consumer_program():
    return call_composition_program(depth=2, calls="single")


def duplicate_formal_copy_consumer_program():
    return duplicate_argument_composition_program(duplicate=True)


def invoke_nr_copy_consumer_program(*, normal_write=False, two_callers=False):
    graph, details = call_return_state_program(normal_write=normal_write,
                                               two_callers=two_callers)
    details = {**details,
        "source": BlockArgument(BlockID("return-state.root.entry"), 0),
        "world_source": BlockArgument(BlockID("return-state.root.entry"), 5)}
    return graph, details


def conditional_return_copy_consumer_program():
    return multi_return_program(mixed=True)


def recursive_copy_consumer_program():
    return recursive_return_program()


def repeated_copy_consumer_program(*, stale=False):
    return loop_call_composition_program(stale=stale)


def opaque_call_copy_consumer_program():
    return distinct_call_composition_program(opaque=True)


def source_in_shared_callee_program():
    return call_return_program(calls="siblings", internal=True)


def await_result_copy_consumer_program(*, zero_cut=True):
    return await_outcome_program(zero_cut=zero_cut, final_adapters=True)


def with_incomplete_internal_consumer(graph, operation_id):
    """Mark one original known use-site effect inventory incomplete."""
    operations = tuple(replace(operation, effects_complete=False)
                       if operation.id == operation_id else operation
                       for operation in graph.operations)
    return replace(graph, operations=operations)


__all__ = [
    "conditional_return_copy_consumer_program", "distinct_payload_return_program",
    "duplicate_actual_program", "duplicate_formal_copy_consumer_program",
    "duplicate_return_program", "invoke_nr_copy_consumer_program",
    "nested_copy_consumer_program", "opaque_call_copy_consumer_program",
    "opaque_internal_consumer_program", "repeated_copy_consumer_program",
    "recursive_copy_consumer_program", "source_in_shared_callee_program",
    "swapped_shared_callee_program", "await_result_copy_consumer_program",
    "with_incomplete_internal_consumer",
]
