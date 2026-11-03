"""Finite conditional CPython 3.14.7 construction protocol, without execution.

The native contract is type_call in CPython v3.14.7 Objects/typeobject.c.
This producer does not select a metaclass, resolve source callbacks, assert
allocation freshness, or expand the physical vectorcall/tp_call adapters.
The implementation receipt binds this producer's own source, not a running
interpreter or an observed native function pointer.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, DataValue, ExitKind, ExitPort, Operation, OperationResult,
    ProgramGraph, ReferenceValue, Region, Stability, StateAccess, StateLocation,
    StateVersionValue, Successor, Terminator, TerminatorKind, Use, UseRole,
    ValueKind, ValueType,
)
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.type_calls import (
    RULE, TypeCallCompletion, TypeCallOperand, TypeCallProvider, TypeCallStage,
    TypeCallStageKind as K, validate_type_call_layout,
)
from scar.ir.program.validation import require_valid


REF = ValueType(ValueKind.REFERENCE)
BOOL = ValueType(ValueKind.DATA, data_type="builtins.bool")
ARGUMENT_VIEW = ValueType(ValueKind.DATA, data_type="scar.logical-call-arguments")
NEW_SLOT = ValueType(ValueKind.DATA, data_type="cpython.optional-newfunc")
INIT_SLOT = ValueType(ValueKind.DATA, data_type="cpython.optional-initproc")


def _implementation():
    path = Path(__file__).resolve()
    raw = path.read_bytes()
    return ProviderArtifact(str(path), sha256(raw).hexdigest(), len(raw),
                            "scar.static-type-call-producer/1")


class _Builder:
    def __init__(self, input_types, layout, exception_arity, implementation):
        signature = [RULE, implementation.sha256,
            [(item.kind.value, item.data_type) for item in input_types],
            [(item.role, item.index, item.keyword) for item in layout], exception_arity]
        self.prefix = "type-call-" + sha256(json.dumps(signature, separators=(",", ":"),
                                                        ensure_ascii=False).encode()).hexdigest()[:24]
        self.input_types, self.layout = input_types, layout
        self.exception_arity, self.implementation = exception_arity, implementation
        self.serial = 0
        self.region = self.fresh(RegionID, "region")
        self.location = self.fresh(LocationID, "world")
        self.state_type = ValueType(ValueKind.STATE, location=self.location)
        self.blocks, self.arguments, self.block_ops = [], {}, {}
        self.operations, self.values, self.by_value = [], [], {}
        self.stages, self.cleanups = [], []
        self.entry = self.block((*input_types, self.state_type))
        self.inputs, self.world = self.arguments[self.entry][:-1], self.arguments[self.entry][-1]
        self.current, self.state = self.entry, self.world

    def fresh(self, kind, role):
        self.serial += 1
        return kind(self.prefix + ":" + role + ":" + str(self.serial))

    def value(self, identity, origin, typ):
        if typ.kind is ValueKind.REFERENCE:
            result = ReferenceValue(identity, self.region, origin)
        elif typ.kind is ValueKind.DATA:
            result = DataValue(identity, self.region, origin, typ.data_type)
        else:
            result = StateVersionValue(identity, self.region, origin, typ.location)
        self.values.append(result)
        self.by_value[identity] = result
        return identity

    def block(self, types):
        identity = self.fresh(BlockID, "block")
        self.blocks.append(identity)
        self.arguments[identity] = tuple(self.value(self.fresh(ValueID, "argument"),
            BlockArgument(identity, index), typ) for index, typ in enumerate(types))
        self.block_ops[identity] = []
        return identity

    def uses(self, values):
        return tuple(Use(self.fresh(UseID, "use"), identity,
            UseRole.REFERENCE if type(self.by_value[identity]) is ReferenceValue else
            UseRole.STATE_CONTENT if type(self.by_value[identity]) is StateVersionValue else UseRole.DATA)
            for identity in values)

    def emit(self, operation):
        self.operations.append(operation)
        self.block_ops[self.current].append(operation.id)

    def regular(self, kind, values, typ, *, read_world=False):
        identity = self.fresh(OperationID, kind.value)
        uses = self.uses((*values, self.state) if read_world else values)
        result = self.value(self.fresh(ValueID, "result"), OperationResult(identity, 0), typ)
        accesses = (StateAccess(self.location, uses[-1].id, AccessMode.READ),) if read_world else ()
        self.emit(Operation(identity, kind.value,
            (Behavior.READ,) if read_world else (Behavior.REPRESENT,) if kind is K.ARGUMENT_VIEW
            else (Behavior.COMPUTE,), uses, (result,), accesses, effects_complete=True))
        self.stages.append(TypeCallStage(kind, identity,
            tuple(use.id for use in (uses[:-1] if read_world else uses)), (result,),
            uses[-1].id if read_world else None))
        return result

    def branch(self, kind, condition):
        identity = self.fresh(OperationID, kind.value)
        uses = self.uses((condition, self.state, self.state))
        yes, no = self.block((self.state_type,)), self.block((self.state_type,))
        self.emit(Operation(identity, kind.value, (Behavior.CONTROL,), uses, effects_complete=True,
            terminator=Terminator(TerminatorKind.BRANCH,
                (Successor(yes, (uses[1].id,)), Successor(no, (uses[2].id,))),
                condition=uses[0].id)))
        self.stages.append(TypeCallStage(kind, identity, (uses[0].id,), (), uses[1].id))
        return yes, no

    def enter(self, block):
        self.current, self.state = block, self.arguments[block][-1]

    def exit(self, kind, values):
        stage_kind = K.RETURN_OBJECT if kind is ExitKind.NORMAL else K.PROPAGATE_RAISE
        identity = self.fresh(OperationID, stage_kind.value)
        uses = self.uses((*values, self.state))
        self.emit(Operation(identity, stage_kind.value, (Behavior.CONTROL,), uses,
            effects_complete=True, terminator=Terminator(
                TerminatorKind.RETURN if kind is ExitKind.NORMAL else TerminatorKind.RAISE,
                exit="normal" if kind is ExitKind.NORMAL else "raise", values=tuple(use.id for use in uses))))
        self.stages.append(TypeCallStage(stage_kind, identity, tuple(use.id for use in uses[:-1]),
                                         (), uses[-1].id))

    def release_failed_init(self, obj, pending):
        # Only this provider's owned new-result reference is released. The
        # pending payloads are retained, not decref'd as if they were that owner.
        # Native destruction can run Python finalizers/unraisable hooks. Its
        # postworld is open, while the same pending propagation is restored.
        kind = K.RELEASE_FAILED_INIT
        identity = self.fresh(OperationID, kind.value)
        uses = self.uses((obj, *pending, self.state))
        after = self.value(self.fresh(ValueID, "cleanup-world"), OperationResult(identity, 0), self.state_type)
        self.emit(Operation(identity, kind.value, (Behavior.READ, Behavior.WRITE, Behavior.MEMORY),
            uses, (after,), (StateAccess(self.location, uses[-1].id, AccessMode.READ_WRITE, after),),
            effects_complete=False))
        self.stages.append(TypeCallStage(kind, identity, tuple(use.id for use in uses[:-1]),
                                         (after,), uses[-1].id))
        self.cleanups.append(identity)
        self.state = after

    def invoke(self, kind, values, result_types, *, failed_owner=None):
        identity = self.fresh(OperationID, kind.value)
        uses = self.uses((*values, self.state))
        normal_types = None if result_types is None else (*result_types, self.state_type)
        raised_types = (REF,) * self.exception_arity + (self.state_type,)
        normal = self.block(normal_types) if normal_types is not None else None
        raised = self.block(raised_types)
        signatures, successors = [], []
        completions = {}
        for exit_kind, block, types in ((ExitKind.NORMAL, normal, normal_types),
                                        (ExitKind.RAISE, raised, raised_types)):
            if block is None:
                continue
            position = len(successors)
            signatures.append(CompletionSignature(exit_kind, types))
            successors.append(CompletionSuccessor(exit_kind, block,
                tuple(CompletionResult(index) for index in range(len(types)))))
            arguments = self.arguments[block]
            completions[exit_kind] = TypeCallCompletion(ControlEdgeReference(identity, position),
                                                       arguments[:-1], arguments[-1])
        self.emit(Operation(identity, kind.value,
            (Behavior.CONTROL, Behavior.READ, Behavior.WRITE, Behavior.MEMORY), uses,
            effects_complete=False, terminator=Terminator(TerminatorKind.INVOKE, tuple(successors)),
            completions=tuple(signatures), invoke_arguments=tuple(use.id for use in uses)))
        normal_completion = completions.get(ExitKind.NORMAL)
        self.stages.append(TypeCallStage(kind, identity, tuple(use.id for use in uses[:-1]),
            normal_completion.payloads if normal_completion is not None else (), uses[-1].id,
            normal_completion, completions[ExitKind.RAISE]))
        self.enter(raised)
        pending = self.arguments[raised][:-1]
        if failed_owner is not None:
            self.release_failed_init(failed_owner, pending)
        self.exit(ExitKind.RAISE, pending)
        if normal is not None:
            self.enter(normal)
            return self.arguments[normal][:-1]
        return ()

    def run(self):
        cls = self.inputs[0]
        view = self.regular(K.ARGUMENT_VIEW, self.inputs[1:], ARGUMENT_VIEW)
        new_slot = self.regular(K.READ_TP_NEW, (cls,), NEW_SLOT, read_world=True)
        new_present = self.regular(K.NEW_PRESENT, (new_slot,), BOOL)
        has_new, missing_new = self.branch(K.BRANCH_NEW, new_present)
        self.enter(missing_new)
        self.invoke(K.RAISE_MISSING_NEW, (cls,), None)
        self.enter(has_new)
        obj, = self.invoke(K.INVOKE_TP_NEW, (cls, new_slot, view), (REF,))
        is_instance = self.regular(K.IS_REQUESTED_INSTANCE, (obj, cls), BOOL, read_world=True)
        initialize, unrelated = self.branch(K.BRANCH_INSTANCE, is_instance)
        self.enter(unrelated)
        self.exit(ExitKind.NORMAL, (obj,))
        self.enter(initialize)
        # Read from Py_TYPE(obj) at this point, not cls and not a factory-time
        # class snapshot. tp_new may return a strict subclass or mutate state.
        init_slot = self.regular(K.READ_TP_INIT, (obj,), INIT_SLOT, read_world=True)
        init_present = self.regular(K.INIT_PRESENT, (init_slot,), BOOL)
        has_init, no_init = self.branch(K.BRANCH_INIT, init_present)
        self.enter(no_init)
        self.exit(ExitKind.NORMAL, (obj,))
        self.enter(has_init)
        # C initproc returns a status integer, not a Python object. This stage
        # includes the native status/error check, hence NORMAL has no payload.
        self.invoke(K.INVOKE_TP_INIT, (obj, init_slot, view), (), failed_owner=obj)
        self.exit(ExitKind.NORMAL, (obj,))
        graph = ProgramGraph(self.region, (Region(self.region,
            "conditional CPython standard non-builtin class construction", self.entry,
            tuple(Block(block, self.arguments[block], tuple(self.block_ops[block])) for block in self.blocks),
            (ExitPort("normal", ExitKind.NORMAL, (REF, self.state_type)),
             ExitPort("raise", ExitKind.RAISE, (REF,) * self.exception_arity + (self.state_type,)))),),
            tuple(self.operations), tuple(self.values),
            (StateLocation(self.location, "coarse class-slot/callback/cleanup/external world",
                           stability=Stability.UNKNOWN),))
        require_valid(graph)
        return TypeCallProvider(self.implementation, RULE, self.input_types, self.layout,
            self.exception_arity, graph, self.inputs, self.world, view, obj,
            tuple(self.stages), tuple(self.cleanups))


def build_type_call_provider(input_types: tuple[ValueType, ...], layout: tuple[TypeCallOperand, ...],
                             exception_arity: int = 1) -> TypeCallProvider:
    """Build a content-shared conditional protocol for this exact operand ABI.

    The first non-world operand is the original callee. All other non-world
    operands, including normalized method flags or keyword-name carriers, must
    be retained with their original types and roles. Matching those occurrences
    to this logical view remains a guard on the separate caller relation.
    """
    validate_type_call_layout(input_types, layout, exception_arity)
    return _Builder(input_types, layout, exception_arity, _implementation()).run()


def validate_type_call_provider(provider: TypeCallProvider) -> TypeCallProvider:
    """Freshly replay producer, typed layout, graph, ports, stages and guards."""
    if type(provider) is not TypeCallProvider:
        raise TypeError("expected a typed conditional standard constructor provider")
    provider.__post_init__()
    require_valid(provider.graph)
    expected = build_type_call_provider(provider.input_types, provider.layout, provider.exception_arity)
    if provider != expected:
        raise ValueError("type call provider differs from its current producer or exact typed protocol")
    return provider


__all__ = ["build_type_call_provider", "validate_type_call_provider"]
