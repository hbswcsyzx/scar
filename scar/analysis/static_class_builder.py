"""Construct a conditional CPython class builder and connect a shared suite.

No application import, metaclass, descriptor, decorator or suite is evaluated.
The implementation graph is an abstract, versioned protocol expansion of the
standard builder, not a claim that the caller selected it. Callback internals,
fine-grained effects and target/source identity remain explicit obligations.
"""
from __future__ import annotations

import hashlib
import json

from scar.ir.program.class_builder import (
    ClassBuilderCompletion, ClassBuilderExpansion, ClassBuilderInput,
    ClassBuilderProvider, ClassBuilderStage, ClassBuilderStageKind as K,
    ClassSuiteCompletion, ClassSuiteInput,
)
from scar.ir.program.class_entries import ClassSuiteOverlay, ClassSuiteMethodOverlay
from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, ExitKind, ExitPort, Operation, ProgramGraph, ReferenceValue,
    OperationResult, Region, Stability, StateAccess, StateLocation, StateVersionValue, Terminator,
    TerminatorKind, Use, UseRole, ValueKind, ValueType, value_type,
)
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_subjects import FrameKind, SourceCompilationFrameRoot
from scar.ir.program.validation import require_valid


IMPLEMENTATION = ProviderArtifact(
    "https://raw.githubusercontent.com/python/cpython/v3.14.7/Python/bltinmodule.c",
    "25234c39aafcd1da77b9cf94938d9e72ffcbee9e76aed34fa6b235cc8ffe970a",
    104011, "cpython.source-c/3.14.7")
RULE = "CPYTHON_BUILD_CLASS_3147_V1"
REF = ValueType(ValueKind.REFERENCE)


def _need(ok, detail):
    if not ok:
        raise ValueError("class builder connection: " + detail)


class _Builder:
    """Small provider producer; core def/use and CFG remain authoritative."""
    def __init__(self, base_count, keyword_names, freevars):
        signature = json.dumps([RULE, base_count, keyword_names, freevars], separators=(",", ":"))
        self.prefix = "build-class-" + hashlib.sha256(signature.encode()).hexdigest()[:24]
        self.serial = 0
        self.region = self.fresh(RegionID, "region")
        self.location = self.fresh(LocationID, "world")
        self.state_type = ValueType(ValueKind.STATE, location=self.location)
        self.blocks, self.arguments, self.block_ops = [], {}, {}
        self.operations, self.values, self.stages, self.cleanups = [], [], [], []
        self.entry = self.block((REF,) * (2 + base_count + len(keyword_names) + bool(keyword_names))
                                + (self.state_type,))
        args = self.arguments[self.entry]
        self.body_function, self.name = args[:2]
        self.bases = args[2:2 + base_count]
        self.keywords = args[2 + base_count:2 + base_count + len(keyword_names)]
        self.keyword_table = args[-2] if keyword_names else None
        self.world = args[-1]
        self.current, self.state = self.entry, self.world

    def fresh(self, kind, role):
        self.serial += 1
        return kind(self.prefix + ":" + role + ":" + str(self.serial))

    def block(self, types):
        block = self.fresh(BlockID, "block")
        self.blocks.append(block)
        result = []
        for index, typ in enumerate(types):
            identity = self.fresh(ValueID, "argument")
            origin = BlockArgument(block, index)
            value = (StateVersionValue(identity, self.region, origin, self.location)
                     if typ.kind is ValueKind.STATE else ReferenceValue(identity, self.region, origin))
            self.values.append(value)
            result.append(identity)
        self.arguments[block], self.block_ops[block] = tuple(result), []
        return block

    def uses(self, identity, refs, world):
        return tuple(Use(self.fresh(UseID, "use"), value,
                         UseRole.STATE_CONTENT if index == len(refs) else UseRole.REFERENCE)
                     for index, value in enumerate((*refs, world)))

    def emit(self, operation):
        self.operations.append(operation)
        self.block_ops[self.current].append(operation.id)

    def cleanup(self, kind, refs):
        # This abstract native cleanup preserves the pending completion and
        # can run destructors/unraisable hooks. It is not effect-free and is
        # not a sequence of fabricated application calls or FD operations.
        identity = self.fresh(OperationID, kind.value)
        uses = self.uses(identity, refs, self.state)
        after = self.fresh(ValueID, "cleanup-world")
        self.values.append(StateVersionValue(after, self.region, OperationResult(identity, 0), self.location))
        self.emit(Operation(identity, kind.value, (Behavior.READ, Behavior.WRITE, Behavior.MEMORY), uses,
            (after,), (StateAccess(self.location, uses[-1].id, AccessMode.READ_WRITE, after),),
            effects_complete=False))
        self.cleanups.append(identity)
        self.state = after

    def exit(self, kind, refs):
        identity = self.fresh(OperationID, "exit")
        uses = self.uses(identity, refs, self.state)
        self.emit(Operation(identity, "provider " + kind.value.lower() + " exit", (Behavior.CONTROL,), uses,
            effects_complete=True, terminator=Terminator(
                TerminatorKind.RETURN if kind is ExitKind.NORMAL else TerminatorKind.RAISE,
                exit="normal" if kind is ExitKind.NORMAL else "raise", values=tuple(u.id for u in uses))))

    def invoke(self, kind, refs, result_count, owned=()):
        identity = self.fresh(OperationID, kind.value)
        uses = self.uses(identity, refs, self.state)
        types = (REF,) * result_count + (self.state_type,)
        raised_types = (REF, REF, self.state_type)
        normal, raised = self.block(types), self.block(raised_types)
        signatures = (CompletionSignature(ExitKind.NORMAL, types), CompletionSignature(ExitKind.RAISE, raised_types))
        self.emit(Operation(identity, kind.value,
            (Behavior.CONTROL, Behavior.READ, Behavior.WRITE, Behavior.MEMORY), uses,
            effects_complete=False, terminator=Terminator(TerminatorKind.INVOKE,
                tuple(CompletionSuccessor(signature.kind, block,
                    tuple(CompletionResult(i) for i in range(len(signature.types))))
                    for signature, block in zip(signatures, (normal, raised)))),
            completions=signatures, invoke_arguments=tuple(u.id for u in uses)))
        normal_values, raised_values = self.arguments[normal], self.arguments[raised]
        self.stages.append(ClassBuilderStage(kind, identity, tuple(u.id for u in uses[:-1]), uses[-1].id,
            normal, normal_values[:-1], normal_values[-1], raised, *raised_values))
        self.current, self.state = raised, raised_values[-1]
        self.cleanup(K.RELEASE_RAISE, (*owned, *raised_values[:-1]))
        self.exit(ExitKind.RAISE, raised_values[:-1])
        self.current, self.state = normal, normal_values[-1]
        return normal_values[:-1]

    def run(self, keyword_names, freevars):
        func, name = self.body_function, self.name
        self.invoke(K.CHECK_INPUTS, (func, name), 0)
        (orig_bases,) = self.invoke(K.PACK_BASES, self.bases, 1)
        (bases,) = self.invoke(K.UPDATE_BASES, (orig_bases,), 1, (orig_bases,))
        table = (self.keyword_table,) if self.keyword_table is not None else ()
        meta, *keyword_refs = self.invoke(K.SELECT_METACLASS, (bases, *self.keywords, *table),
            1 + bool(self.keywords), (orig_bases, bases))
        # No keywords means a NULL C dictionary pointer, not a Python None
        # object. That case has no dictionary Value/Use at all. With keywords
        # this result is the real remaining dictionary (possibly empty).
        keywords = tuple(keyword_refs)
        namespace, = self.invoke(K.PREPARE_NAMESPACE, (meta, name, bases, *keywords), 1,
            (orig_bases, bases, meta, *keywords))
        self.invoke(K.CHECK_MAPPING, (namespace,), 0, (orig_bases, bases, meta, *keywords, namespace))
        # These are current native frame-field projections at suite entry,
        # after __mro_entries__/__prepare__ callbacks, not factory snapshots.
        code, globals_ref, builtins_ref, *closure = self.invoke(K.READ_FUNCTION_FRAME, (func,), 3 + len(freevars),
            (orig_bases, bases, meta, *keywords, namespace))
        cell, = self.invoke(K.EVAL_SUITE, (func, code, namespace, globals_ref, builtins_ref, *closure), 1,
            (orig_bases, bases, meta, *keywords, namespace))
        self.invoke(K.STORE_ORIGINAL_BASES, (namespace, orig_bases, bases), 0,
            (orig_bases, bases, meta, *keywords, namespace, cell))
        cls, = self.invoke(K.CALL_METACLASS, (meta, name, bases, namespace, *keywords), 1,
            (orig_bases, bases, meta, *keywords, namespace, cell))
        self.invoke(K.CHECK_CLASS_CELL, (cls, cell, name), 0,
            (orig_bases, bases, meta, *keywords, namespace, cell, cls))
        self.cleanup(K.RELEASE_NORMAL, (cell, namespace, meta, *keywords, orig_bases, bases))
        self.exit(ExitKind.NORMAL, (cls,))
        graph = ProgramGraph(self.region, (Region(self.region, "conditional CPython __build_class__", self.entry,
            tuple(Block(b, self.arguments[b], tuple(self.block_ops[b])) for b in self.blocks),
            (ExitPort("normal", ExitKind.NORMAL, (REF, self.state_type)),
             ExitPort("raise", ExitKind.RAISE, (REF, REF, self.state_type)))),),
            tuple(self.operations), tuple(self.values),
            (StateLocation(self.location, "coarse builder/callback/external world", stability=Stability.UNKNOWN),))
        require_valid(graph)
        return ClassBuilderProvider(IMPLEMENTATION, RULE, len(self.bases), keyword_names, freevars, graph,
            func, name, self.bases, self.keywords, self.keyword_table, self.world,
            tuple(self.stages), tuple(self.cleanups))


def build_class_provider(*, base_count, keyword_names=(), freevars=()):
    """Build the same finite shared provider graph for a given ABI signature."""
    _need(type(base_count) is int and base_count >= 0, "base count must be a nonnegative integer")
    _need(type(keyword_names) is tuple and all(type(n) is str and n for n in keyword_names)
          and len(set(keyword_names)) == len(keyword_names), "keyword names must be unique ordered strings")
    _need(type(freevars) is tuple and all(type(n) is str and n for n in freevars)
          and len(set(freevars)) == len(freevars), "freevars must retain the exact ordered layout")
    return _Builder(base_count, keyword_names, freevars).run(keyword_names, freevars)


def _original_ports(parent, construction, suite, overlay):
    """Resolve original boundaries; no protocol outputs are minted here."""
    require_valid(parent)
    require_valid(suite)
    _need(type(overlay) in (ClassSuiteOverlay, ClassSuiteMethodOverlay), "shared body needs a class suite overlay")
    _need(construction.suite == overlay.compilation and construction.definition == overlay.definition
          and construction.source == overlay.source, "parent and suite compiler/source identity differ")
    _need(construction.suite.compiler_implementation == "cpython"
          and construction.suite.compiler_version == (3, 14, 7), "suite requires the declared CPython 3.14.7 ABI")
    _need(len(suite.frame_roots) == 1 and type(suite.frame_roots[0]) is SourceCompilationFrameRoot
          and suite.frame_roots[0].kind is FrameKind.CLASS
          and suite.frame_roots[0].code == overlay.compilation and suite.frame_roots[0].entry == overlay.interface,
          "suite original frame root differs from class ABI")
    parent_operations = {op.id: op for op in parent.operations}
    parent_blocks = {b.id: b for r in parent.regions for b in r.blocks}
    call = construction.builder_call
    operation = parent_operations.get(call.operation)
    _need(operation is not None and operation.terminator is not None
          and operation.terminator.kind is TerminatorKind.INVOKE and operation.callee is None
          and not operation.effects_complete, "original unknown builder INVOKE must remain intact")
    uses = {u.id: u for u in operation.uses}
    _need(tuple(uses) == (call.callee, *(a.use for a in call.arguments),
          *((call.keyword_names,) if call.keyword_names is not None else ()), call.world),
          "parent selected callee/actual/world occurrences differ")
    normal, raised = operation.terminator.successors
    _need(normal.kind is ExitKind.NORMAL and raised.kind is ExitKind.RAISE
          and normal.block == call.normal and raised.block == call.raised
          and parent_blocks[normal.block].arguments == (call.result, call.normal_world)
          and parent_blocks[raised.block].arguments == (call.exception, call.traceback, call.raised_world),
          "parent completion endpoints differ")
    _need(len(call.arguments) >= 2 and uses[call.arguments[0].use].value == construction.body_function,
          "builder body operand is not the original factory result")
    factory = parent_operations.get(construction.factory)
    _need(factory is not None and factory.terminator is not None
        and factory.terminator.kind is TerminatorKind.INVOKE
        and tuple(u.id for u in factory.uses[:-1]) == (
        construction.factory_code, construction.factory_globals, *construction.factory_closure),
        "body factory code/globals/closure occurrences differ")
    factory_normal = next(e for e in factory.terminator.successors if e.kind is ExitKind.NORMAL)
    _need(parent_blocks[factory_normal.block].arguments[0] == construction.body_function,
          "body function is not the factory normal result")
    entry = next(r for r in suite.regions if r.id == suite.root).entry
    block = next(b for r in suite.regions for b in r.blocks if b.id == entry)
    mapping = overlay.interface.mapping
    formals = (mapping.locals_namespace, mapping.globals_namespace, mapping.builtins_namespace,
               *mapping.closure_cells, mapping.world)
    _need(block.arguments == formals, "suite ABI is not its original ordered entry interface")
    return operation, uses, mapping


def connect_class_suite(*, parent_namespace, parent_graph, construction,
                        suite_namespace, suite_graph, suite_overlay):
    """Produce qualified parent -> provider -> shared suite port relations.

    The owning reader must verify namespaces and their artifact receipts from
    original source/body inputs before calling this constructor. This routine
    checks actual core endpoints and compiler provenance; it is not an artifact
    loader and does not convert its still-present guards into proven facts.
    """
    _, uses, mapping = _original_ports(parent_graph, construction, suite_graph, suite_overlay)
    _need(parent_namespace.region == parent_graph.root and suite_namespace.region == suite_graph.root
          and suite_namespace.definition == suite_overlay.definition and suite_namespace.source == suite_overlay.source,
          "qualified namespaces differ from supplied original graphs")
    actuals = construction.builder_call.arguments
    positional = tuple(a for a in actuals if a.keyword is None)
    keyword_actuals = tuple(a for a in actuals if a.keyword is not None)
    _need(tuple(actuals) == (*positional, *keyword_actuals), "builder inputs must retain positional then keyword order")
    _need(bool(keyword_actuals) == (construction.builder_call.keyword_names is not None),
          "builder keyword table differs from original named actuals")
    provider = build_class_provider(base_count=len(positional) - 2,
        keyword_names=tuple(a.keyword for a in keyword_actuals), freevars=suite_overlay.interface.co_freevars)
    formals = (provider.body_function, provider.name, *provider.bases, *provider.keywords)
    inputs = tuple(ClassBuilderInput(a.use, uses[a.use].value, formal) for a, formal in zip(actuals, formals))
    call = construction.builder_call
    if call.keyword_names is not None:
        inputs += (ClassBuilderInput(call.keyword_names, uses[call.keyword_names].value, provider.keyword_table),)
    inputs += (ClassBuilderInput(call.world, uses[call.world].value, provider.world),)
    stage = next(s for s in provider.stages if s.kind is K.EVAL_SUITE)
    provider_ops = {op.id: op for op in provider.graph.operations}
    eval_uses = {u.id: u for u in provider_ops[stage.operation].uses}
    # First eval operands are body function and current code. Namespace/frame
    # roles begin after them; saved B is a function-field result, never parent B.
    role_names = ("locals", "globals", "builtins", *("closure" for _ in mapping.closure_cells), "world")
    targets = (mapping.locals_namespace, mapping.globals_namespace, mapping.builtins_namespace,
               *mapping.closure_cells, mapping.world)
    source_uses = (*stage.inputs[2:], stage.world)
    suite_inputs = tuple(ClassSuiteInput(role, use, eval_uses[use].value, formal)
        for role, use, formal in zip(role_names, source_uses, targets))
    root = next(r for r in suite_graph.regions if r.id == suite_graph.root)
    normal = next(e for e in root.exits if e.kind is ExitKind.NORMAL)
    raised = next(e for e in root.exits if e.kind is ExitKind.RAISE)
    suite_completions = (
        ClassSuiteCompletion(ExitKind.NORMAL, normal.name, stage.normal, (*stage.results, stage.normal_world)),
        ClassSuiteCompletion(ExitKind.RAISE, raised.name, stage.raised,
            (stage.exception, stage.traceback, stage.raised_world)))
    completions = (
        ClassBuilderCompletion(ExitKind.NORMAL, "normal", call.normal, (call.result, call.normal_world)),
        ClassBuilderCompletion(ExitKind.RAISE, "raise", call.raised,
            (call.exception, call.traceback, call.raised_world)))
    return ClassBuilderExpansion(parent_namespace, construction, suite_namespace, provider,
        inputs, suite_inputs, suite_completions, completions)


def validate_class_builder_expansion(expansion, *, parent_graph, suite_graph, suite_overlay):
    """Re-derive all mappings and provider CFG from the original core inputs."""
    expansion.__post_init__()
    expected = connect_class_suite(parent_namespace=expansion.parent, parent_graph=parent_graph,
        construction=expansion.construction, suite_namespace=expansion.suite,
        suite_graph=suite_graph, suite_overlay=suite_overlay)
    _need(expansion == expected, "stored provider graph, guards or original port mappings differ")
    return expansion
