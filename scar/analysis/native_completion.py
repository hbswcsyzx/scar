"""Queries for a selected native invocation's canonical normal interface.

This view joins existing ProgramGraph and ExecutionModel occurrences.  It
creates no operation, value, denotation, evidence edge, storage region, or
content version.  A selected normal transfer and an output leaf in the
original native evidence establish the route represented by these records;
they do not prove a write, copy, device readiness, or storage stability.
"""
from __future__ import annotations

from dataclasses import dataclass

from scar.ir.execution.content import (
    NativeInputRef, NativeOutputRef, ObjectIdentity, ValueDenotation,
)
from scar.ir.execution.coordinates import (
    ControlTransfer, OperationOccurrence, OperationOccurrenceID, UseOccurrence,
    UseRef, ValueOccurrence,
)
from scar.ir.execution.ids import ValueOccurrenceID
from scar.ir.execution.model import (
    ExecutionModel, OccurrenceEvidenceBinding,
)
from scar.ir.execution.work import (
    ActualCompletionState, InvokeBoundaryStateEffect,
)
from scar.ir.program.ids import NativeBoundaryID
from scar.ir.program.model import (
    CompletionResult, ExitKind, ProgramGraph, StateVersionValue, TerminatorKind,
    UseRole,
)
from scar.ir.program.providers import ProviderFactReference
from scar.ir.execution.common import Unresolved


@dataclass(frozen=True, slots=True)
class NativeCompletionPort:
    """One original native port resolved to its canonical runtime occurrence."""

    reference: NativeInputRef | NativeOutputRef
    use: UseOccurrence
    value: ValueOccurrence | Unresolved
    denotation: ValueDenotation | None

    def __post_init__(self) -> None:
        if type(self.reference) not in (NativeInputRef, NativeOutputRef):
            raise TypeError("completion port must reuse a native input/output reference")
        if type(self.use) is not UseOccurrence:
            raise TypeError("completion port must reuse an original UseOccurrence")
        if type(self.value) not in (ValueOccurrence, Unresolved):
            raise TypeError("completion port value must be an original ValueOccurrence or Unresolved")
        if type(self.value) is ValueOccurrence and self.use.value != self.value.id:
            raise ValueError("completion port UseOccurrence and ValueOccurrence differ")
        if self.denotation is not None:
            if type(self.denotation) is not ValueDenotation:
                raise TypeError("completion port denotation must reuse ValueDenotation")
            if self.denotation.basis != self.reference:
                raise ValueError("completion port denotation has a different native basis")
            if type(self.value) is not ValueOccurrence or self.denotation.value != self.value.id:
                raise ValueError("completion port denotation differs from its resolved occurrence")


@dataclass(frozen=True, slots=True)
class NativeNormalCompletion:
    """An existing invoke, selected normal route, and native ports.

    ``normal_return`` means that the ExecutionModel contains the selected
    original NORMAL transfer and its corresponding normal return occurrence.
    ``normal_basis`` also requires an original ETO output-leaf denotation.  It
    is an observational route result, not proof of effects or readiness.
    """

    invocation: OperationOccurrence
    normal_transfer: ControlTransfer
    normal_return: OperationOccurrence
    boundary: NativeBoundaryID
    input_ports: tuple[NativeCompletionPort, ...]
    output_ports: tuple[NativeCompletionPort, ...]
    invocation_evidence: OccurrenceEvidenceBinding
    completion_evidence: OccurrenceEvidenceBinding
    state_input: UseOccurrence | None
    state_output: ValueOccurrence | None
    state_effect: InvokeBoundaryStateEffect | None
    state_interface_status: str
    normal_basis: str
    effects_complete: bool

    def __post_init__(self) -> None:
        if type(self.invocation) is not OperationOccurrence:
            raise TypeError("completion invocation must reuse an OperationOccurrence")
        if type(self.normal_transfer) is not ControlTransfer:
            raise TypeError("completion transfer must reuse a ControlTransfer")
        if type(self.normal_return) is not OperationOccurrence:
            raise TypeError("normal return must reuse an OperationOccurrence")
        if (self.normal_transfer.operation != self.invocation.id
                or self.normal_return.visit != self.normal_transfer.target):
            raise ValueError("normal transfer and return do not share the original invocation route")
        if type(self.boundary) is not NativeBoundaryID:
            raise TypeError("completion boundary must reuse a NativeBoundaryID")
        if (type(self.input_ports) is not tuple or type(self.output_ports) is not tuple
                or any(type(row) is not NativeCompletionPort
                       for row in self.input_ports + self.output_ports)):
            raise TypeError("completion ports must be tuples of NativeCompletionPort")
        if any(type(row.reference) is not NativeInputRef for row in self.input_ports):
            raise ValueError("input port collection contains a non-input native reference")
        if any(type(row.reference) is not NativeOutputRef for row in self.output_ports):
            raise ValueError("output port collection contains a non-output native reference")
        if type(self.invocation_evidence) is not OccurrenceEvidenceBinding or (
                self.invocation_evidence.operation != self.invocation.id):
            raise ValueError("invocation evidence must bind the original invocation")
        if type(self.completion_evidence) is not OccurrenceEvidenceBinding or (
                self.completion_evidence.operation != self.normal_return.id):
            raise ValueError("completion evidence must bind the original normal return")
        if self.state_input is not None and type(self.state_input) is not UseOccurrence:
            raise TypeError("state_input must be an original UseOccurrence or None")
        if self.state_output is not None and type(self.state_output) is not ValueOccurrence:
            raise TypeError("state_output must be an original ValueOccurrence or None")
        if self.state_effect is not None:
            if type(self.state_effect) is not InvokeBoundaryStateEffect:
                raise TypeError("state_effect must be the existing InvokeBoundaryStateEffect type")
            if (self.state_input is None or self.state_output is None
                    or self.state_effect.invocation != self.invocation.id
                    or self.state_effect.state_input != UseRef(self.invocation.id, self.state_input.use)
                    or type(self.state_effect.post) is not ActualCompletionState
                    or self.state_effect.post.formal != self.state_output.id):
                raise ValueError("state effect does not resolve through original state occurrences")
        if type(self.state_interface_status) is not str or not self.state_interface_status:
            raise ValueError("state interface status must be explicit text")
        if type(self.normal_basis) is not str or not self.normal_basis:
            raise ValueError("normal route basis must be explicit text")
        if type(self.effects_complete) is not bool:
            raise TypeError("effects_complete must preserve the original exact boolean")

    @property
    def same_object_reference_pairs(self) -> tuple[tuple[int, int], ...]:
        """Return (output position, input position) pairs sharing ObjectIdentity.

        These are original object-reference matches only.  They do not establish
        storage allocation/epoch, tensor contents, or alias/write behavior.
        """
        pairs = []
        for output in self.output_ports:
            if output.denotation is None or type(output.denotation.identity) is not ObjectIdentity:
                continue
            for input_port in self.input_ports:
                if (input_port.denotation is not None
                        and type(input_port.denotation.identity) is ObjectIdentity
                        and output.denotation.identity.object == input_port.denotation.identity.object):
                    pairs.append((output.reference.position, input_port.reference.position))
        return tuple(pairs)


def _one(rows, description):
    rows = tuple(rows)
    if len(rows) != 1:
        raise ValueError(f"{description} must resolve exactly once; found {len(rows)}")
    return rows[0]


def _all_by(rows, key):
    result = {}
    for row in rows:
        result.setdefault(key(row), []).append(row)
    return result


def _normal_state_interface(program: ProgramGraph, execution: ExecutionModel,
                            invocation: OperationOccurrence, invoke_op,
                            return_op, normal_return: OperationOccurrence,
                            normal_visit, successor,
                            successor_index: int):
    """Resolve the zero-or-one canonical STATE_CONTENT continuation."""
    values_by_id = {item.id: item for item in program.values}
    input_state_uses = []
    static_uses = {item.id: item for item in invoke_op.uses}
    for use_id in invoke_op.invoke_arguments:
        static_use = static_uses[use_id]
        if (static_use.role is UseRole.STATE_CONTENT
                and type(values_by_id.get(static_use.value)) is StateVersionValue):
            input_state_uses.append(static_use)

    block_by_id = {block.id: block for region in program.regions for block in region.blocks}
    target_block = block_by_id[normal_visit.block]
    runtime_uses = _all_by(execution.uses, lambda row: (row.operation, row.use))
    runtime_values = _all_by(execution.values, lambda row: row.id)
    output_state_values = []
    for formal_index, formal_id in enumerate(target_block.arguments):
        if type(values_by_id.get(formal_id)) is not StateVersionValue:
            continue
        if formal_index >= len(successor.arguments):
            continue
        argument = successor.arguments[formal_index]
        # The invoke result index, rather than visit/ordinal order, identifies
        # which boundary state is forwarded to this original completion formal.
        if type(argument) is not CompletionResult:
            continue
        occurrence = _one(
            (row for row in execution.values
             if row.origin == normal_visit.id and row.value == formal_id),
            "normal world-state completion ValueOccurrence",
        )
        output_state_values.append((values_by_id[formal_id].location,
                                    formal_id, argument.index, occurrence))

    input_state_runtime = []
    for static_use in input_state_uses:
        runtime = _one(runtime_uses.get((invocation.id, static_use.id), ()),
                       "invoke world-state UseOccurrence")
        input_state_runtime.append((values_by_id[static_use.value].location, runtime))

    if not input_state_runtime and not output_state_values:
        return None, None, None, "NO_CANONICAL_STATE_INTERFACE"
    if len(input_state_runtime) != 1 or len(output_state_values) != 1:
        return (input_state_runtime[0][1] if len(input_state_runtime) == 1 else None,
                output_state_values[0][3] if len(output_state_values) == 1 else None,
                None, "MULTIPLE_OR_UNMATCHED_STATE_INTERFACE")
    input_location, state_input = input_state_runtime[0]
    output_location, output_formal, result_index, state_output = output_state_values[0]
    if input_location != output_location:
        return state_input, state_output, None, "STATE_LOCATION_MISMATCH"
    if type(state_input.value) is not ValueOccurrenceID:
        return state_input, state_output, None, "STATE_INPUT_VALUE_UNRESOLVED"
    return_state_use = _one((row for row in return_op.uses
                             if row.value == output_formal
                             and row.role is UseRole.STATE_CONTENT),
                            "normal-return world-state Use")
    return_state_actual = _one(runtime_uses.get((normal_return.id, return_state_use.id), ()),
                               "normal-return world-state UseOccurrence")
    if return_state_actual.value != state_output.id:
        return state_input, state_output, None, "STATE_RETURN_USE_MISMATCH"
    effect = InvokeBoundaryStateEffect(
        invocation.id,
        UseRef(invocation.id, state_input.use),
        ActualCompletionState(successor_index, result_index, state_output.id),
    )
    return state_input, state_output, effect, "ONE_SELECTED_NORMAL_STATE_CONTINUATION"


def query_native_normal_completion(
    program: ProgramGraph,
    execution: ExecutionModel,
    invocation: OperationOccurrenceID,
) -> NativeNormalCompletion:
    """Resolve one existing native invoke through its selected normal return.

    This function is a typed in-memory join.  Callers must already have loaded
    and qualified the supplied models.  It checks that the invoke, selected
    edge, return, port denotations, and original evidence bindings all refer to
    one original native instance and ETO source.
    """
    if type(program) is not ProgramGraph or type(execution) is not ExecutionModel:
        raise TypeError("program and execution must be exact ProgramGraph and ExecutionModel records")
    if type(invocation) is not OperationOccurrenceID:
        raise TypeError("invocation must be an OperationOccurrenceID")

    runtime_invocation = _one((row for row in execution.operations if row.id == invocation),
                              "native invocation occurrence")
    static_operations = {row.id: row for row in program.operations}
    static_invoke = static_operations.get(runtime_invocation.operation)
    if (static_invoke is None or static_invoke.terminator is None
            or static_invoke.terminator.kind is not TerminatorKind.INVOKE):
        raise ValueError("selected occurrence is not an original typed INVOKE operation")

    visits = {row.id: row for row in execution.visits}
    invoke_visit = visits.get(runtime_invocation.visit)
    if invoke_visit is None:
        raise ValueError("native invocation's original BlockVisit is absent")
    block_rows = [(region, block) for region in program.regions for block in region.blocks]
    invoke_blocks = [(region, block) for region, block in block_rows
                     if block.id == invoke_visit.block and static_invoke.id in block.operations]
    region, _invoke_block = _one(invoke_blocks, "native invocation's containing region")
    boundary = _one((row for row in program.native_boundaries if row.region == region.id),
                    "native boundary for invocation region")

    transfers = tuple(row for row in execution.transfers if row.operation == invocation)
    if len(transfers) != 1:
        raise ValueError(f"native invocation must have one selected control transfer; found {len(transfers)}")
    transfer = transfers[0]
    if transfer.successor_index >= len(static_invoke.terminator.successors):
        raise ValueError("selected transfer is outside the original invoke signature")
    successor = static_invoke.terminator.successors[transfer.successor_index]
    if successor.kind is not ExitKind.NORMAL:
        raise ValueError("the original execution selected a non-normal invoke completion")
    normal_visit = visits.get(transfer.target)
    if normal_visit is None or normal_visit.block != successor.block:
        raise ValueError("selected normal transfer target differs from the original successor")
    block_by_id = {block.id: (parent, block) for parent, block in block_rows}
    normal_region, normal_block = block_by_id[normal_visit.block]
    if normal_region.id != boundary.region:
        raise ValueError("selected normal visit leaves the original native boundary region")

    normal_return_ops = [row for row in normal_block.operations
                         if (static_operations[row].terminator is not None
                             and static_operations[row].terminator.kind is TerminatorKind.RETURN
                             and static_operations[row].terminator.exit == "normal")]
    normal_return_op_id = _one(normal_return_ops, "normal return operation in selected completion block")
    normal_return = _one((row for row in execution.operations
                          if row.visit == normal_visit.id and row.operation == normal_return_op_id),
                         "normal return occurrence in selected completion visit")
    static_return = static_operations[normal_return_op_id]

    evidence_by_op = _all_by(execution.evidence_bindings, lambda row: row.operation)
    invocation_evidence = _one(evidence_by_op.get(invocation, ()),
                               "original invocation evidence binding")
    completion_evidence = _one(evidence_by_op.get(normal_return.id, ()),
                               "original normal-return evidence binding")
    if (invocation_evidence.legacy != completion_evidence.legacy
            or invocation_evidence.source.artifact != completion_evidence.source.artifact):
        raise ValueError("invoke and normal return evidence do not name the same original native instance")
    if type(invocation_evidence.source) is not ProviderFactReference or type(
            completion_evidence.source) is not ProviderFactReference:
        raise ValueError("native invocation/return lacks original ETO provider evidence")
    eto_artifact = invocation_evidence.source.artifact
    if not completion_evidence.source.locator.startswith(
            invocation_evidence.source.locator.rstrip("/") + "/outputs"):
        raise ValueError("normal-return evidence is not a subtree of the original ETO node")

    runtime_uses = _all_by(execution.uses, lambda row: (row.operation, row.use))
    runtime_values = _all_by(execution.values, lambda row: row.id)
    denotations = _all_by(execution.denotations, lambda row: row.value)
    inputs = []
    invoke_static_uses = {row.id: row for row in static_invoke.uses}
    for slot in boundary.inputs:
        if slot.port.region != boundary.region:
            raise ValueError("native input slot points outside its original boundary region")
        if slot.position >= len(static_invoke.invoke_arguments):
            raise ValueError("native input slot is outside original invoke argument list")
        static_use_id = static_invoke.invoke_arguments[slot.position]
        static_use = invoke_static_uses[static_use_id]
        if static_use.value != slot.port.value:
            raise ValueError("native input slot differs from its original invoke argument ValueID")
        use = _one(runtime_uses.get((invocation, static_use_id), ()),
                   "native input UseOccurrence")
        if type(use.value) is ValueOccurrenceID:
            value = _one((row for row in runtime_values.get(use.value, ())
                          if row.origin == invoke_visit.id and row.value == static_use.value),
                         "native input ValueOccurrence")
        elif type(use.value) is Unresolved:
            value = use.value
        else:
            raise TypeError("native input UseOccurrence has an unsupported value reference")
        reference = NativeInputRef(boundary.id, invoke_visit.id, slot.position)
        selected_denotations = tuple(row for row in execution.denotations
                                     if row.basis == reference)
        denotation = None
        if selected_denotations:
            denotation = _one(selected_denotations, "native input denotation")
            if denotation.value != use.value:
                raise ValueError("native input denotation differs from original UseOccurrence")
            if (type(denotation.source) is not ProviderFactReference
                    or denotation.source.artifact != eto_artifact
                    or not denotation.source.locator.startswith(
                        invocation_evidence.source.locator.rstrip("/") + "/inputs/")):
                raise ValueError("native input denotation differs from original ETO input subtree")
        inputs.append(NativeCompletionPort(reference, use, value, denotation))

    return_uses = {row.id: row for row in static_return.uses}
    output_runtime_uses = _all_by(execution.uses, lambda row: (row.operation, row.use))
    outputs = []
    for slot in boundary.outputs:
        if (slot.port.region != boundary.region or slot.port.exit_name != "normal"
                or slot.position != slot.port.index):
            raise ValueError("native output slot is not an ordered port on the normal exit")
        if slot.port.index >= len(static_return.terminator.values):
            raise ValueError("native output slot is outside original normal-return uses")
        static_use_id = static_return.terminator.values[slot.port.index]
        static_use = return_uses[static_use_id]
        if slot.port.index >= len(normal_block.arguments):
            raise ValueError("native output slot is outside the selected normal block formals")
        if static_use.value != normal_block.arguments[slot.port.index]:
            raise ValueError("native output slot does not resolve to its original normal formal")
        use = _one(output_runtime_uses.get((normal_return.id, static_use_id), ()),
                   "native output UseOccurrence")
        if type(use.value) is not ValueOccurrenceID:
            raise ValueError("selected normal return output has no resolved ValueOccurrence")
        value = _one((row for row in runtime_values.get(use.value, ())
                      if row.origin == normal_visit.id and row.value == static_use.value),
                     "native output ValueOccurrence")
        reference = NativeOutputRef(boundary.id, normal_return.id, slot.position)
        denotation = _one((row for row in denotations.get(value.id, ())
                           if row.basis == reference), "original native output denotation")
        if (type(denotation.source) is not ProviderFactReference
                or denotation.source.artifact != eto_artifact
                or not denotation.source.locator.startswith(
                    completion_evidence.source.locator.rstrip("/") + "/")):
            raise ValueError("native output denotation does not resolve to the original ETO output subtree")
        outputs.append(NativeCompletionPort(reference, use, value, denotation))
    if not outputs:
        raise ValueError("original native boundary declares no observed normal output ports")

    state_input, state_output, state_effect, state_status = _normal_state_interface(
        program, execution, runtime_invocation, static_invoke, static_return,
        normal_return,
        normal_visit, successor, transfer.successor_index)
    return NativeNormalCompletion(
        runtime_invocation, transfer, normal_return, boundary.id,
        tuple(inputs), tuple(outputs), invocation_evidence, completion_evidence,
        state_input, state_output, state_effect, state_status,
        "selected original NORMAL transfer plus original ETO output-leaf denotation",
        static_invoke.effects_complete,
    )


__all__ = ["NativeCompletionPort", "NativeNormalCompletion",
           "query_native_normal_completion"]
