"""Opt-in CPython 3.14 generator-expression creation and fixed-unpack drive.

The nested regions are canonical ProgramGraph regions.  Construction does not
call B. NEXT drives share B and its one suspension; effects/close stay open.
The policy deliberately excludes generator arguments with guarded duplicated
creation, filters, async generators and nested comprehension clauses.
"""
from __future__ import annotations

import ast
import dis
import hashlib
from dataclasses import replace
from pathlib import Path
from types import CodeType

from scar.analysis.environment_lowering import StructuredEnvironmentBuilder, captured_cell_slot, _PREFIX
from scar.analysis.program_lowering import _Unsupported, _key, _REF, _BOOL, _Cursor
from scar.analysis.source_heap_lowering import expression_for_heap_target, _source_definition, _hold
from scar.analysis.source_mapping_lowering import _transfer
from scar.ir.program.bindings import BindingState
from scar.ir.program.control import ProtocolValueKind as P, ProtocolValueType
from scar.ir.program.drivers import (
    BodyDrive, BodyDriveResult, BodyDriveSuccessor, BodyDriveTerminator, BodyResume,
    BodyResumeInput, BodyStart, BodyStateInput, CreationCapture, DriverInterface,
    DriverReceiverKind, DriverRule, DriverRuleProfile, FinalBodyGate,
    NormalResultPort, RawRequestDefinition, RawRequestKind, ResumableCreate,
)
from scar.ir.program.environments import EnvironmentInterface, EnvironmentMember, EnvironmentRole, FunctionEntryLayout
from scar.ir.program.functions import FormalPort
from scar.ir.program.ids import EnvironmentInterfaceID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.lifecycle import BodyOutcomeCommit, DriveOutcomeRef, DriverLifecycle
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, DataValue, ExitKind, ExitPort, Footprint, FootprintKind, LocalBindingValue, Operation,
    LiteralOrigin, OperationResult, ProtocolValue, ReferenceValue, Region, StateAccess,
    StateVersionValue, Successor, Terminator, TerminatorKind, Use, UseRole, value_type,
)
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.resumption import (
    FrameContextAttach, FrameContextDetach, FrameContextInitial, ResumableBody,
    ResumableKind, ResumeInput, ResumeSlot, ResumeSlotKind, ResumeSuccessor,
    SavedInput, SavedRole, SavedSlot, SuspendTerminator, SuspensionFlavor,
)
from scar.ir.program.source import GapKind, SourceRole
from scar.ir.program.source_language import CodeConstantSource
from scar.ir.program.structured import PythonProtocolKind as Kind
from scar.ir.v2.ids import ValueSlotID
from scar.ir.v2.semantic import OperationKind


VERSION = "PYTHON_GENEXPR_314_V1"
TABLES = ("environments", "function_entries", "resumable_bodies", "frame_context_initials",
          "frame_context_attaches", "frame_context_detaches", "resumable_creates",
          "raw_driver_requests", "driver_interfaces", "final_body_gates", "body_drives",
          "driver_lifecycles", "body_outcome_commits")


def driver_rule():
    # A reference to this declared construction policy, never runtime evidence.
    path = Path(__file__).resolve()
    raw = path.read_bytes()
    return DriverRule(DriverRuleProfile.PYTHON_RESUMPTION_V1,
        ProviderFactReference(ProviderArtifact("scar://source-language/" + VERSION + "/producer",
                              hashlib.sha256(raw).hexdigest(), len(raw), VERSION),
                              "NEXT-only source construction; runtime and CLOSE unproved"))


def compiler_entry_slot(definition, key, constant_index):
    """A compiler interface slot, not a fabricated SG lexical binding."""
    return ValueSlotID(_key("genexpr-compiler-entry", definition.wire, key, constant_index, 0))


def child_code(code, node):
    span = node.lineno, node.end_lineno, node.col_offset, node.end_col_offset
    rows = tuple(dis.get_instructions(code))
    matched = [row for row in rows if row.opname == "LOAD_CONST" and tuple(row.positions) == span
               and type(row.argval) is CodeType and row.argval.co_name == "<genexpr>"]
    if len(matched) != 1:
        raise _Unsupported(GapKind.CODE_VERSION, node, "GENEXPR_CREATION_OCCURRENCE_NOT_UNIQUE")
    row, = matched
    child = row.argval
    same = [item.opname for item in rows if tuple(item.positions) == span]
    calls = [item for item in rows if tuple(item.positions) == span and item.opname == "CALL"]
    makes = [item for item in rows if tuple(item.positions) == span and item.opname == "MAKE_FUNCTION"]
    outer = node.generators[0].iter
    outer_span = outer.lineno, outer.end_lineno, outer.col_offset, outer.end_col_offset
    gets = [item for item in rows if item.opname == "GET_ITER" and tuple(item.positions) == outer_span]
    if (child.co_argcount != 1 or child.co_varnames[:1] != (".0",)
            or child.co_flags & 0x20 == 0 or child.co_cellvars
            or same.count("MAKE_FUNCTION") != 1 or same.count("CALL") != 1
            or calls[0].arg != 0 or len(gets) != 1
            or not row.offset < makes[0].offset < gets[0].offset < calls[0].offset
            or child.co_varnames[1:2] != (node.generators[0].target.id,)):
        raise _Unsupported(GapKind.CODE_VERSION, node, "GENEXPR_COMPILER_CREATION_INTERFACE_UNRECOVERED")
    return row.arg, child


class _Nested(StructuredEnvironmentBuilder):
    """Use the original builder's buffers/budget, with a different Region owner."""

    def __init__(self, owner, node, region, definition):
        self.__dict__.update(owner.__dict__)
        self.owner, self.node = owner, node
        self.function_context, self.function_definition = region, definition
        self.function_blocks = []
        self.active_temporaries = []
        self.reference_candidates = {}
        self.environment_references, self.cell_references = {}, {}
        self.free_cells = frozenset()
        self.local_cells = frozenset()
        self.locals, self.global_names = set(), set()
        self.callers = {}
        self.lazy = False

    def fresh(self, cls, tag):
        return self.owner.fresh(cls, "genexpr-" + tag)

    def emit(self, cursor, operation, node, role, old=None):
        self.owner.emit(cursor, operation, node, role, old=old)

    def use(self, operation, value, node, role, index, *, semantic_value=None):
        if type(self.values_by_id[value]) is ProtocolValue:
            from scar.ir.program.source import UseSource
            use = Use(self.fresh(UseID, "protocol-use"), value, UseRole.PROTOCOL)
            self.use_links.append(UseSource(operation, use.id, self.source(node), role, index, semantic_value))
            return use
        return super().use(operation, value, node, role, index, semantic_value=semantic_value)

    def _addresses(self, operation_id, effects):
        from scar.ir.program.state_addresses import StateAddressRefinement, InvokeStateOperand, AddressCoverage
        operation = self.operation_records[operation_id]
        self.address_refinements.append(StateAddressRefinement(
            InvokeStateOperand(operation_id, operation.invoke_arguments[-1]), tuple(effects), AddressCoverage.PARTIAL))

    def ports(self, types, *, detached=False):
        cursor = super().new_block(self.node, extra_types=())
        state = self.pop_value()
        args = []
        for kind in types:
            origin = BlockArgument(cursor.block, len(args))
            identity = self.fresh(ValueID, "entry")
            if kind == _REF:
                value = ReferenceValue(identity, self.function_context, origin)
            elif kind == _BOOL:
                value = DataValue(identity, self.function_context, origin, "builtins.bool")
            elif type(kind) is ValueSlotID:
                value = LocalBindingValue(identity, self.function_context, origin, kind)
            else:
                value = ProtocolValue(identity, self.function_context, origin, kind.protocol)
            self.add_value(value); self.link_value(value, self.node, SourceRole.PARAMETER)
            args.append(value.id)
        if self.lazy and not detached:
            value = ProtocolValue(self.fresh(ValueID, "caller-port"), self.function_context,
                BlockArgument(cursor.block, len(args)), P.DRIVE_CALLER_CONTEXT)
            self.add_value(value); self.link_value(value, self.node, SourceRole.CONTROL)
            args.append(value.id); self.callers[cursor.block] = value.id
        state = replace(state, origin=BlockArgument(cursor.block, len(args)))
        self.add_value(state); self.link_value(state, self.node, SourceRole.STATE)
        self.block_arguments[cursor.block] = (*args, state.id)
        cursor.state = state.id
        return cursor, tuple(args[:len(types)])

    def raw_value(self, operation, index, kind, node=None):
        value = ProtocolValue(self.fresh(ValueID, "private-result"), self.function_context,
                              OperationResult(operation, index), kind)
        self.add_value(value); self.link_value(value, node or self.node, SourceRole.CONTROL)
        return value.id

    def boolean(self, value):
        result = DataValue(self.fresh(ValueID, "outcome-tag"), self.function_context,
                           LiteralOrigin(value), "builtins.bool")
        self.add_value(result); self.link_value(result, self.node, SourceRole.CONTROL)
        return result.id

    def integer(self, value):
        result = DataValue(self.fresh(ValueID, "arity"), self.function_context,
                           LiteralOrigin(value), "builtins.int")
        self.add_value(result); self.link_value(result, self.node, SourceRole.CONTROL)
        return result.id

    def switch(self, cursor, value, *, attach):
        operation = self.fresh(OperationID, "attach" if attach else "detach")
        operand = self.use(operation, value, self.node, "frame-fragment", 0)
        before = self.use(operation, cursor.state, self.node, "context-world", 0)
        result = self.raw_value(operation, 0, P.DRIVE_CALLER_CONTEXT if attach else P.FRAME_CONTEXT)
        state = StateVersionValue(self.fresh(ValueID, "context-state"), self.function_context,
                                  OperationResult(operation, 1), self.world)
        self.add_value(state); self.link_value(state, self.node, SourceRole.STATE)
        self.emit(cursor, Operation(operation, "attach" if attach else "detach",
            (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), (operand, before), (result, state.id),
            (StateAccess(self.world, before.id, AccessMode.READ_WRITE, state.id, Footprint(FootprintKind.WHOLE)),), effects_complete=True),
            self.node, SourceRole.CONTROL)
        table = "frame_context_attaches" if attach else "frame_context_detaches"
        record = FrameContextAttach(operation, operand.id, result) if attach else FrameContextDetach(operation, operand.id, result)
        self.owner.generator_records[table].append(record)
        cursor.state = state.id
        if attach:
            self.callers[cursor.block] = result
        return result

    def invoke_results(self, cursor, node, inputs, *, role=SourceRole.EXPRESSION, old=None,
                       result_types=(), failure_handler=None, callee=None):
        operation_id = self.fresh(OperationID, "invoke")
        uses = [self.use(operation_id, value, child, name, index, semantic_value=static)
                for value, child, name, index, static in inputs]
        uses.append(self.use(operation_id, cursor.state, node, "state", 0))
        arguments = tuple(use.id for use in uses)
        normal, results = self.ports(result_types)
        failure, failed_results = self.ports((_REF,))
        normal.env, failure.env = dict(cursor.env), dict(cursor.env)
        signatures = (CompletionSignature(ExitKind.NORMAL, (*result_types, self.state_type)),
                      CompletionSignature(ExitKind.RAISE, (_REF, self.state_type)))
        edges = []
        for signature, target in zip(signatures, (normal, failure)):
            actual = tuple(CompletionResult(i) for i in range(len(signature.types) - 1))
            if self.lazy:
                forward = self.use(operation_id, self.callers[cursor.block], node, "caller-edge", len(edges))
                uses.append(forward); actual += (forward.id,)
            actual += (CompletionResult(len(signature.types) - 1),)
            edges.append(CompletionSuccessor(signature.kind, target.block, actual))
        self.emit(cursor, Operation(operation_id, role.value, (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
            tuple(uses), effects_complete=False, callee=callee,
            terminator=Terminator(TerminatorKind.INVOKE, tuple(edges)), completions=signatures,
            invoke_arguments=arguments), node, role, old=old)
        if failure_handler is None:
            self.finish_exit(failure, node, failed_results[0], ExitKind.RAISE)
        else:
            failure_handler(failure, failed_results[0])
        return normal, results, operation_id

    def finish_exit(self, cursor, node, value, kind, *, binding=None):
        if self.lazy and kind is ExitKind.RAISE:
            # This is the existing generator escape-adapter rule over the
            # source profile's coarse exception-reference ABI. A StopIteration
            # from the elt is never the iterator's normal exhaustion branch.
            def adapter_failed(failure, exception):
                self._finish_terminal(failure, node, exception, ExitKind.RAISE)
            cursor, results, operation = self.invoke_results(cursor, node,
                ((value, node, "escaping-exception", 0, None),), result_types=(_REF,),
                failure_handler=adapter_failed)
            self.protocol(operation, Kind.GENERATOR_ESCAPE_STOPITER_TO_RUNTIME_ERROR, node)
            value, = results
        return self._finish_terminal(cursor, node, value, kind)

    def _finish_terminal(self, cursor, node, value, kind):
        refs = [(value, node, "held-payload")]
        refs.extend((token, node, "held-local") for token in cursor.env.values())
        refs.extend((value, node, "held-temporary") for value in self.active_temporaries)
        self.frame_transition(cursor, node, refs, Kind.FRAME_EXIT)
        if self.lazy:
            self.switch(cursor, self.callers[cursor.block], attach=False)
        return self.terminal(cursor, (value,), kind)

    def terminal(self, cursor, results, kind=ExitKind.NORMAL):
        identity = self.fresh(OperationID, "terminal")
        uses = tuple(self.use(identity, value, self.node, "result", index)
                     for index, value in enumerate((*results, cursor.state)))
        self.emit(cursor, Operation(identity, kind.value, (Behavior.CONTROL,), uses,
            terminator=Terminator(TerminatorKind.RETURN if kind is ExitKind.NORMAL else TerminatorKind.RAISE,
                exit=kind.value.lower(), values=tuple(use.id for use in uses))), self.node, SourceRole.RETURN)
        return identity

    def jump_ports(self, cursor, target, actual):
        identity = self.fresh(OperationID, "jump")
        if self.lazy:
            actual = (*actual, self.callers[cursor.block])
        uses = tuple(self.use(identity, value, self.node, "edge", index)
                     for index, value in enumerate((*actual, cursor.state)))
        self.emit(cursor, Operation(identity, "jump", (Behavior.CONTROL,), uses,
            terminator=Terminator(TerminatorKind.JUMP,
                (Successor(target.block, tuple(use.id for use in uses)),))), self.node, SourceRole.CONTROL)

    def branch_to(self, cursor, boolean, yes, no):
        identity = self.fresh(OperationID, "branch")
        test = self.use(identity, boolean, self.node, "predicate", 0)
        edges, uses = [], [test]
        for target in (yes, no):
            forwarded = []
            if self.lazy:
                forwarded.append(self.use(identity, self.callers[cursor.block], self.node, "caller-edge", len(edges)))
            forwarded.append(self.use(identity, cursor.state, self.node, "state-edge", len(edges)))
            uses.extend(forwarded)
            edges.append(Successor(target.block, tuple(use.id for use in forwarded)))
            target.env = dict(cursor.env)
        self.emit(cursor, Operation(identity, "branch", (Behavior.CONTROL,), tuple(uses),
            terminator=Terminator(TerminatorKind.BRANCH, tuple(edges), condition=test.id)), self.node, SourceRole.CONTROL)

    def close_region(self, entry, normal_types, *, parent):
        blocks = tuple(Block(block, self.block_arguments[block], tuple(self.block_operations[block]))
                       for block in self.function_blocks)
        region = Region(self.function_context, "generator source interface", entry.block, blocks,
            (ExitPort("normal", ExitKind.NORMAL, (*normal_types, self.state_type)),
             ExitPort("raise", ExitKind.RAISE, (_REF, self.state_type))), parent=parent)
        self.regions.append(region)
        return region


def _body(owner, node, definition, code, index):
    region_id = RegionID(_key("genexpr-lazy-body", definition.id.wire,
                             owner.language_options.code_evidence.captured.key, index, VERSION))
    b = _Nested(owner, node, region_id, definition)
    b.lazy = True
    b.locals = {node.generators[0].target.id}
    b.free_cells = frozenset(code.co_freevars)
    b.global_names = set(code.co_names)
    refs_count = len(_PREFIX) + len(code.co_freevars) + 1
    entry, refs = b.ports((_REF,) * refs_count, detached=True)
    environment_refs, iterator = refs[:-1], refs[-1]
    members = [EnvironmentMember(role, value, (b.world,)) for role, value in zip(_PREFIX, environment_refs)]
    for position, name in enumerate(code.co_freevars):
        members.append(EnvironmentMember(EnvironmentRole.CAPTURED_CELL,
            environment_refs[len(_PREFIX) + position], (b.world,), captured_cell_slot(definition.id, name), position))
    environment = EnvironmentInterface(EnvironmentInterfaceID(_key("genexpr-environment", region_id.wire)),
                                       region_id, definition.id, tuple(members))
    port = FormalPort(compiler_entry_slot(definition.id, owner.language_options.code_evidence.captured.key, index), iterator)
    owner.generator_records["environments"].append(environment)
    owner.generator_records["function_entries"].append(FunctionEntryLayout(environment.id, (port,)))
    owner.generator_records["resumable_bodies"].append(ResumableBody(region_id, ResumableKind.GENERATOR, b.world))
    operation = b.fresh(OperationID, "initial")
    frame = b.raw_value(operation, 0, P.FRAME_CONTEXT)
    b.emit(entry, Operation(operation, "initial", (Behavior.CONTROL,), results=(frame,), effects_complete=True), node, SourceRole.CONTROL)
    owner.generator_records["frame_context_initials"].append(FrameContextInitial(operation, frame))
    b.switch(entry, frame, attach=True)
    b.frame_transition(entry, node, tuple((value, node, "environment-reference") for value in refs), Kind.FRAME_ENTER)
    target = node.generators[0].target
    b.define_binding(target.id, entry, target)
    slot = b.slots.get((definition.id, target.id))
    if slot is None:
        raise _Unsupported(GapKind.SOURCE_MAPPING, target, "GENEXPR_TARGET_HAS_NO_ORIGINAL_SCOPE_SLOT")
    header, carried = b.ports((slot, *(_REF for _ in refs)))
    header.env[target.id] = carried[0]
    b.jump_ports(entry, header, (entry.env[target.id], *refs))
    h_env, h_iterator = carried[1:-1], carried[-1]
    b.environment_references = dict(zip(_PREFIX, h_env))
    b.cell_references = dict(zip(code.co_freevars, h_env[len(_PREFIX):]))
    natural, _ = b.ports(())
    def exhausted(failure, exception):
        identity = b.fresh(OperationID, "match-stop")
        exc = b.use(identity, exception, node, "exception", 0)
        state = b.use(identity, failure.state, node, "exception-type-state", 0)
        boolean = DataValue(b.fresh(ValueID, "stop-bool"), region_id, OperationResult(identity, 0), "builtins.bool")
        b.add_value(boolean); b.link_value(boolean, node, SourceRole.TRUTH)
        b.emit(failure, Operation(identity, "match-stop-iteration", (Behavior.COMPUTE, Behavior.READ),
            (exc, state), (boolean.id,), (StateAccess(b.world, state.id, AccessMode.READ),), effects_complete=True),
            node, SourceRole.TRUTH)
        b.protocol(identity, Kind.MATCH_STOP_ITERATION, node)
        raised, _ = b.ports(())
        b.branch_to(failure, boolean.id, natural, raised)
        b.finish_exit(raised, node, exception, ExitKind.RAISE)
        b.frame_transition(natural, node, ((exception, node, "consumed-exhaustion"),), Kind.FRAME_DISCARD)
        b.finish_exit(natural, node, b.literal(node, None), ExitKind.NORMAL)
    body, item, _ = b.invoke_protocol(header, node, (h_iterator,), Kind.ADVANCE_ITERATOR, failure_handler=exhausted)
    body = b.store(target, item, body)
    body, yielded = expression_for_heap_target(b, node.elt, body)
    if body is None:
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, "GENEXPR_ELT_HAS_NO_NORMAL_YIELD")
    frame = b.switch(body, b.callers[body.block], attach=False)
    suspend_id = b.fresh(OperationID, "yield")
    export = b.use(suspend_id, yielded, node.elt, "yield", 0)
    saved_values = (frame, body.env[target.id], *h_env, h_iterator)
    saved_uses = tuple(b.use(suspend_id, value, node, "saved", n) for n, value in enumerate(saved_values))
    handoff = b.use(suspend_id, body.state, node, "handoff", 0)
    landing, restored = b.ports((ProtocolValueType(P.FRAME_CONTEXT), slot,
        *(_REF for _ in refs), _REF), detached=True)
    successor = ResumeSuccessor((ResumeSlot(ResumeSlotKind.SENT_VALUE), ResumeSlot(ResumeSlotKind.STATE, b.world)),
        landing.block, (*(SavedInput(i) for i in range(len(saved_values))), ResumeInput(0), ResumeInput(1)))
    term = SuspendTerminator(SuspensionFlavor.YIELD, export.id,
        tuple(SavedSlot(SavedRole.FRAME_CONTEXT if n == 0 else SavedRole.LOCAL_BINDING if n == 1 else SavedRole.VALUE, use.id)
              for n, use in enumerate(saved_uses)), (handoff.id,), (successor,))
    b.emit(body, Operation(suspend_id, "yield", (Behavior.CONTROL,), (export, *saved_uses, handoff),
                          terminator=term, effects_complete=False), node, SourceRole.CONTROL)
    b.switch(landing, restored[0], attach=True)
    landing.env[target.id] = restored[1]
    b.frame_transition(landing, node, ((restored[-1], node, "discarded-send-value"),), Kind.FRAME_DISCARD)
    b.jump_ports(landing, header, restored[1:-1])
    region = b.close_region(entry, (_REF,), parent=owner.function_context)
    return region, environment, port, suspend_id


def _driver(owner, node, definition, body, suspend, *, resume):
    region_id = RegionID(_key("genexpr-next-driver", body.id.wire, int(resume), VERSION))
    b = _Nested(owner, node, region_id, definition)
    raw_type = ProtocolValueType(P.RAW_DRIVER_REQUEST)
    entry, (instance, scheduler, sent) = b.ports((_REF, raw_type, _REF))
    ingress, (own_instance, own_scheduler, own_sent) = b.ports((_REF, raw_type, _REF))
    reject, (exception,) = b.ports((_REF,))
    gate_id = b.fresh(OperationID, "final-gate")
    gate_inputs = tuple(b.use(gate_id, value, node, "gate-input", n) for n, value in enumerate((instance, scheduler, sent, entry.state)))
    forwards = tuple(b.use(gate_id, value, node, "gate-forward", n) for n, value in enumerate((instance, scheduler, sent)))
    gate = Operation(gate_id, "NEXT admission/lifecycle boundary", (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
        (*gate_inputs, *forwards), effects_complete=False, invoke_arguments=tuple(use.id for use in gate_inputs),
        completions=(CompletionSignature(ExitKind.NORMAL, (b.state_type,)), CompletionSignature(ExitKind.RAISE, (_REF, b.state_type))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, ingress.block, (*(use.id for use in forwards), CompletionResult(0))),
            CompletionSuccessor(ExitKind.RAISE, reject.block, (CompletionResult(0), CompletionResult(1))))))
    b.emit(entry, gate, node, SourceRole.CONTROL)
    b.finish_exit(reject, node, exception, ExitKind.RAISE)
    drive_id = b.fresh(OperationID, "drive")
    uses = [b.use(drive_id, value, node, "drive-input", n) for n, value in enumerate(
        (own_instance, own_scheduler, *((own_sent,) if resume else ()), ingress.state))]
    drive = BodyDrive(drive_id, uses[0].id, uses[1].id, None,
        BodyResume(suspend, 0) if resume else BodyStart(body.id),
        (BodyStateInput(b.world, uses[-1].id),), (BodyResumeInput(0, uses[2].id),) if resume else ())
    from scar.ir.program.resumption_flow import first_body_outcome_operations
    start = next(op for op in owner.operations if op.id == suspend).terminator.successors[0].block if resume else body.entry
    operations = {op.id: op for op in owner.operations}
    sources = first_body_outcome_operations(body, operations, start)
    edges = []
    for source in sources:
        outcome, (payload,) = b.ports((_REF,))
        edges.append(BodyDriveSuccessor(source, outcome.block, (BodyDriveResult(0), BodyDriveResult(1))))
        commit = b.fresh(OperationID, "outcome-commit")
        own = b.use(commit, own_instance, node, "instance", 0)
        before = b.use(commit, outcome.state, node, "lifecycle-before", 0)
        after = StateVersionValue(b.fresh(ValueID, "committed-world"), region_id, OperationResult(commit, 0), b.world)
        b.add_value(after); b.link_value(after, node, SourceRole.STATE)
        b.emit(outcome, Operation(commit, "declared body outcome publication", (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
            (own, before), (after.id,), (StateAccess(b.world, before.id, AccessMode.READ_WRITE, after.id, Footprint(FootprintKind.WHOLE)),), effects_complete=True),
            node, SourceRole.CONTROL)
        owner.generator_records["body_outcome_commits"].append(BodyOutcomeCommit(commit, DriveOutcomeRef(drive_id, source), own.id))
        outcome.state = after.id
        source_kind = operations[source].terminator.kind
        if source_kind is TerminatorKind.RAISE:
            b.finish_exit(outcome, node, payload, ExitKind.RAISE)
        else:
            flag = b.boolean(source_kind is TerminatorKind.SUSPEND)
            b.terminal(outcome, (payload, flag))
    b.emit(ingress, Operation(drive_id, "drive same lazy body", (Behavior.CONTROL,), tuple(uses),
        terminator=BodyDriveTerminator(tuple(edges)), effects_complete=False), node, SourceRole.CONTROL)
    owner.generator_records["body_drives"].append(drive)
    owner.generator_records["final_body_gates"].append(FinalBodyGate(gate_id, drive_id, 0, 1, None,
        delivery_arguments=(2,) if resume else ()))
    owner.generator_records["driver_interfaces"].append(DriverInterface(region_id, body.id, DriverReceiverKind.BODY,
        instance, scheduler, (b.world,), driver_rule()))
    owner.generator_records["driver_lifecycles"].append(DriverLifecycle(region_id))
    return b.close_region(entry, (_REF, _BOOL), parent=owner.function_context)


def lower_generator(builder, node, cursor):
    if not builder.has_language("FIXED_UNPACK") or not builder.has_language("LEXICAL_LOCALS"):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, "GENEXPR_REQUIRES_FIXED_UNPACK_AND_LEXICAL_LOCALS")
    evidence = builder.language_options.code_evidence
    if evidence is None:
        raise _Unsupported(GapKind.CODE_VERSION, node, "GENEXPR_READONLY_CHILD_CODE_WITNESS_REQUIRED")
    parents = [parent for parent in ast.walk(builder.tree) if node in tuple(ast.iter_child_nodes(parent))]
    if (len(parents) != 1 or not isinstance(parents[0], ast.Assign) or parents[0].value is not node
            or len(parents[0].targets) != 1 or not isinstance(parents[0].targets[0], (ast.Tuple, ast.List))):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, "GENEXPR_CONSUMER_GUARD_OR_DRIVE_INTERFACE_UNRECOVERED")
    if (len(node.generators) != 1 or node.generators[0].is_async or node.generators[0].ifs
            or not isinstance(node.generators[0].target, ast.Name)):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, node, "GENEXPR_CLAUSE_INTERFACE_UNIMPLEMENTED")
    definition = _source_definition(builder, node)
    if definition.kind is not OperationKind.OPAQUE or definition.metadata.get("ast_type") != "GeneratorExp":
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, "GENEXPR_ORIGINAL_SG_SCOPE_REQUIRED")
    index, code = child_code(evidence.code, node)
    if any(name not in builder.cell_references for name in code.co_freevars):
        raise _Unsupported(GapKind.SOURCE_MAPPING, node, "GENEXPR_CAPTURE_REQUIRES_ACTUAL_PARENT_CELL")
    if not hasattr(builder, "generator_records"):
        builder.generator_records = {name: [] for name in TABLES}
        builder.generator_handles = {}
    body, environment, port, suspend = _body(builder, node, definition, code, index)
    start = _driver(builder, node, definition, body, suspend, resume=False)
    resume = _driver(builder, node, definition, body, suspend, resume=True)
    operation = builder.fresh(OperationID, "genexpr-code")
    before = builder.use(operation, cursor.state, node, "code-constant-world", 0)
    value = ReferenceValue(builder.fresh(ValueID, "genexpr-code"), builder.function_context, OperationResult(operation, 0))
    builder.add_value(value); builder.link_value(value, node, SourceRole.EXPRESSION)
    builder.emit(cursor, Operation(operation, "child code reference", (Behavior.READ,), (before,), (value.id,),
        (StateAccess(builder.world, before.id, AccessMode.READ),), effects_complete=False), node, SourceRole.EXPRESSION)
    builder.protocol(operation, Kind.READ_CODE_CONSTANT, node)
    builder.language_constants.append(CodeConstantSource(operation, builder.source(node), evidence.captured.key, (index,)))
    captures = tuple(builder.cell_references[name] for name in code.co_freevars)
    inputs = (value.id, builder.environment_references[_PREFIX[1]], *captures)
    cursor, function_env, make = builder.invoke_results(cursor, node,
        tuple((value, node, "function-input", n, None) for n, value in enumerate(inputs)), result_types=(_REF,) * 5)
    builder.protocol(make, Kind.MAKE_GENEXPR_FUNCTION, node)
    function, globals_ref, builtins_ref, defaults_ref, kwdefaults_ref = function_env
    baseline = len(builder.active_temporaries)
    _hold(builder, cursor, node, function)
    try:
        outer = node.generators[0].iter
        cursor, iterable = expression_for_heap_target(builder, outer, cursor)
        if cursor is None:
            return None, None
        _hold(builder, cursor, outer, iterable)
        def get_failed(failure, exception):
            pending = tuple(builder.active_temporaries)
            try:
                _transfer(builder, ((outer, iterable),), outer)
                builder.finish_exit(failure, outer, exception, ExitKind.RAISE)
            finally:
                builder.active_temporaries[:] = pending
        cursor, iterator, _ = builder.invoke_protocol(cursor, outer, (iterable,), Kind.GET_ITERATOR,
                                                     failure_handler=get_failed)
        # CPython 3.14.7 GET_ITER closes its input before either completion.
        _transfer(builder, ((outer, iterable),), outer)
        _hold(builder, cursor, outer, iterator)
        actual = (function, globals_ref, builtins_ref, defaults_ref, kwdefaults_ref, *captures, iterator)
        consumed = ((node, function), (outer, iterator))
        def failed(failure, exception):
            pending = tuple(builder.active_temporaries)
            try:
                _transfer(builder, consumed, node)
                builder.finish_exit(failure, node, exception, ExitKind.RAISE)
            finally:
                builder.active_temporaries[:] = pending
        cursor, results, create = builder.invoke_results(cursor, node,
            tuple((value, node, "creation-capture", n, None) for n, value in enumerate(actual)),
            result_types=(_REF,), failure_handler=failed)
        builder.protocol(create, Kind.CREATE_GENEXPR, node)
        _transfer(builder, consumed, node)
        operation = builder.operation_records[create]
        captures_rows = tuple(CreationCapture(formal, use.id) for formal, use in
                             zip((*[member.reference for member in environment.members], port.value), operation.uses))
        builder.generator_records["resumable_creates"].append(ResumableCreate(create, body.id, captures_rows[0].source,
            captures_rows, NormalResultPort(0), driver_rule()))
        handle, = results
        builder.generator_handles[handle] = (node, definition, body, start, resume)
        builder.gap(GapKind.EFFECT_SUMMARY, node,
            "creation/lazy body/NEXT fixed-unpack are declared; callee effects, runtime/RNG, CLOSE/THROW, "
            "intermediate primitive ownership and outer finalizer/noncompletion effects remain unproved")
        return cursor, handle
    finally:
        del builder.active_temporaries[baseline:]


def unpack_callee(builder, target, rhs):
    item = getattr(builder, "generator_handles", {}).get(rhs)
    if item is None:
        return None
    node, definition, body, start, resume = item
    if any(not isinstance(child, ast.Name) for child in target.elts):
        raise _Unsupported(GapKind.UNSUPPORTED_SYNTAX, target, "GENEXPR_NESTED_UNPACK_DRIVE_UNIMPLEMENTED")
    count = len(target.elts)
    region_id = RegionID(_key("genexpr-fixed-unpack", body.id.wire, builder.source(target).atom_id.wire, count, VERSION))
    b = _Nested(builder, node, region_id, definition)
    entry, (instance,) = b.ports((_REF,))
    current = entry
    operation = b.fresh(OperationID, "raw-next")
    raw = b.raw_value(operation, 0, P.RAW_DRIVER_REQUEST)
    b.emit(current, Operation(operation, "NEXT request pack", (Behavior.COMPUTE,), results=(raw,), effects_complete=True), node, SourceRole.CONTROL)
    builder.generator_records["raw_driver_requests"].append(RawRequestDefinition(raw, RawRequestKind.NEXT, ()))
    sent = b.literal(node, None)
    yielded = []
    for ordinal in range(count + 1):
        driver = start if ordinal == 0 else resume
        current, (payload, available), _ = b.invoke_results(current, node,
            ((instance, node, "generator-instance", 0, None), (raw, node, "scheduler", 1, None),
             (sent, node, "sent-value", 2, None)), result_types=(_REF, _BOOL), callee=driver.id)
        yes, _ = b.ports(())
        no, _ = b.ports(())
        b.branch_to(current, available, yes, no)
        error_cursor = no if ordinal < count else yes
        b.frame_transition(error_cursor, target, ((payload, target, "consumed-drive-payload"),), Kind.FRAME_DISCARD)
        # Explicit error primitive retains both allocation/error-world paths.
        expected, observed = b.integer(count), b.integer(ordinal + int(ordinal == count))
        error_cursor, error, error_op = b.invoke(error_cursor, target,
            ((expected, target, "expected-arity", 0, None),
             (observed, target, "observed-arity", 1, None)), role=SourceRole.EXCEPTION)
        b.protocol(error_op, Kind.MAKE_UNPACK_ARITY_ERROR, target)
        b.finish_exit(error_cursor, target, error, ExitKind.RAISE)
        if ordinal < count:
            yielded.append(payload)
            b.frame_transition(yes, target, ((payload, target, "unpack-held-result"),), Kind.FRAME_HOLD_TEMPORARY)
            b.active_temporaries.append(payload)
            current = yes
        else:
            b.frame_transition(no, target, ((payload, target, "consumed-exhaustion-payload"),), Kind.FRAME_DISCARD)
            b.terminal(no, tuple(yielded))
    b.gap(GapKind.FRAME_EFFECT, target,
        "N yields and one excess probe are connected; partial-result cleanup/finalizers and CLOSE are unproved")
    return b.close_region(entry, (_REF,) * count, parent=builder.function_context).id


def assemble_generators(builder, graph):
    return replace(graph, **{name: (*getattr(graph, name), *builder.generator_records[name]) for name in TABLES})


__all__ = ["lower_generator", "unpack_callee", "assemble_generators", "compiler_entry_slot", "child_code", "VERSION"]
