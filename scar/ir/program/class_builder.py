"""Conditional, qualified class-builder interfaces over ordinary core graphs.

These records do not replace a caller's selected builder or declare its
identity. Provider operations belong to a separate, versioned implementation
region; their normal results, not relationship records, produce namespace and
function-environment references. The shared class body is never cloned.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum

from scar.ir.program.class_construction import ClassConstruction
from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.model import ExitKind, ProgramGraph
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_call_bindings import SourceBodyNamespace
from scar.ir.program.source_references import SourceArtifactLocator


def _need(value, message):
    if not value:
        raise ValueError("class builder: " + message)


class ClassBuilderGuard(str, Enum):
    STANDARD_BUILDER_SELECTED = "SELECTED_CALLEE_IS_CPYTHON_3_14_7_BUILD_CLASS"
    PROFILE_MATCHES_TARGET = "TARGET_HAS_DECLARED_CPYTHON_BUILD_CLASS_IMPLEMENTATION"
    CURRENT_CODE_MATCHES_SUITE = "BODY_FUNCTION_CURRENT_CODE_MATCHES_SHARED_SUITE"
    CURRENT_CLOSURE_MATCHES_SUITE = "BODY_FUNCTION_CURRENT_CLOSURE_MATCHES_SUITE_LAYOUT"


class ClassBuilderStageKind(str, Enum):
    CHECK_INPUTS = "CHECK_FUNCTION_AND_NAME"
    PACK_BASES = "PACK_ORIGINAL_BASES"
    UPDATE_BASES = "UPDATE_MRO_ENTRIES"
    SELECT_METACLASS = "SELECT_METACLASS_AND_REMAINING_KEYWORDS"
    PREPARE_NAMESPACE = "PREPARE_NAMESPACE_OR_ALLOCATE_DICT"
    CHECK_MAPPING = "CHECK_PREPARED_MAPPING"
    READ_FUNCTION_FRAME = "READ_CURRENT_FUNCTION_CODE_GLOBALS_BUILTINS_CLOSURE"
    EVAL_SUITE = "EVALUATE_CLASS_BODY_WITH_MAPPING_LOCALS"
    STORE_ORIGINAL_BASES = "STORE_ORIGINAL_BASES_IF_REPLACED"
    CALL_METACLASS = "CALL_SELECTED_METACLASS"
    CHECK_CLASS_CELL = "CHECK_RETURNED_CLASS_CELL_IF_APPLICABLE"
    RELEASE_NORMAL = "RELEASE_BUILDER_OWNERS_NORMAL"
    RELEASE_RAISE = "RELEASE_BUILDER_OWNERS_RAISE"


@dataclass(frozen=True, slots=True)
class ClassBuilderStage:
    kind: ClassBuilderStageKind
    operation: OperationID
    inputs: tuple[UseID, ...]
    world: UseID
    normal: BlockID
    results: tuple[ValueID, ...]
    normal_world: ValueID
    raised: BlockID
    exception: ValueID
    traceback: ValueID
    raised_world: ValueID

    def __post_init__(self):
        _need(type(self.kind) is ClassBuilderStageKind and type(self.operation) is OperationID,
              "stage must name its original provider operation")
        _need(type(self.inputs) is tuple and all(type(u) is UseID for u in self.inputs)
              and type(self.world) is UseID and len(set((*self.inputs, self.world))) == len(self.inputs) + 1,
              "stage must retain ordered distinct operand occurrences")
        _need(type(self.normal) is BlockID and type(self.raised) is BlockID,
              "stage must retain both original completion blocks")
        _need(type(self.results) is tuple and all(type(v) is ValueID for v in self.results)
              and all(type(v) is ValueID for v in (self.normal_world, self.exception,
                  self.traceback, self.raised_world)), "stage results must be original Values")


@dataclass(frozen=True, slots=True)
class ClassBuilderProvider:
    implementation: ProviderArtifact
    rule: str
    base_count: int
    keyword_names: tuple[str, ...]
    freevars: tuple[str, ...]
    graph: ProgramGraph
    body_function: ValueID
    name: ValueID
    bases: tuple[ValueID, ...]
    keywords: tuple[ValueID, ...]
    keyword_table: ValueID | None
    world: ValueID
    stages: tuple[ClassBuilderStage, ...]
    cleanup_operations: tuple[OperationID, ...]
    effects_complete: bool = False

    def __post_init__(self):
        _need(type(self.implementation) is ProviderArtifact and type(self.graph) is ProgramGraph,
              "provider needs implementation provenance and a canonical graph")
        _need(self.rule == "CPYTHON_BUILD_CLASS_3147_V1" and self.effects_complete is False,
              "this provider does not close callback or cleanup effects")
        _need(type(self.base_count) is int and self.base_count >= 0
              and type(self.keyword_names) is tuple and len(set(self.keyword_names)) == len(self.keyword_names)
              and all(type(n) is str and bool(n) for n in self.keyword_names)
              and type(self.freevars) is tuple and len(set(self.freevars)) == len(self.freevars)
              and all(type(n) is str and bool(n) for n in self.freevars), "invalid provider input layout")
        _need(type(self.bases) is tuple and len(self.bases) == self.base_count
              and type(self.keywords) is tuple and len(self.keywords) == len(self.keyword_names)
              and all(type(v) is ValueID for v in (self.body_function, self.name,
                  *self.bases, *self.keywords, self.world)), "provider formals differ from input layout")
        _need((bool(self.keyword_names) and type(self.keyword_table) is ValueID)
              or (not self.keyword_names and self.keyword_table is None), "keyword table port differs from layout")
        _need(type(self.stages) is tuple and all(type(s) is ClassBuilderStage for s in self.stages),
              "provider stages must be typed original ports")
        _need(type(self.cleanup_operations) is tuple
              and all(type(o) is OperationID for o in self.cleanup_operations), "cleanup must name original operations")


def decode_class_builder_provider(record):
    """Strict provider read, admitting only the known pre-lookup graph layout.

    Embedded provider graphs have no core-version envelope. The sole legacy
    difference admitted here is the absent optional lookup evidence table;
    None preserves NOT_RECORDED, rather than certifying an empty new table.
    Original dictionaries and stored provider bytes are never changed.
    """
    from scar.ir.record_codec import decode
    provider_fields = {field.name for field in fields(ClassBuilderProvider)}
    if type(record) is not dict or set(record) != provider_fields:
        raise ValueError('class builder provider record fields mismatch')
    graph = record['graph']
    graph_fields = {field.name for field in fields(ProgramGraph)}
    if type(graph) is not dict:
        raise ValueError('class builder provider graph must be an exact record')
    if set(graph) == graph_fields - {'attribute_lookups'}:
        record = {**record, 'graph': {**graph, 'attribute_lookups': None}}
    elif set(graph) != graph_fields:
        raise ValueError('class builder provider graph fields mismatch')
    return decode(ClassBuilderProvider, record)


@dataclass(frozen=True, slots=True)
class ClassBuilderInput:
    """One original parent INVOKE operand to one provider entry parameter."""
    actual_use: UseID
    actual_value: ValueID
    formal: ValueID

    def __post_init__(self):
        _need(type(self.actual_use) is UseID and type(self.actual_value) is ValueID
              and type(self.formal) is ValueID, "provider input mapping needs original ports")


@dataclass(frozen=True, slots=True)
class ClassSuiteInput:
    """An eval operation Use to an existing shared suite frame parameter."""
    role: str
    actual_use: UseID
    actual_value: ValueID
    formal: ValueID

    def __post_init__(self):
        _need(self.role in ("locals", "globals", "builtins", "closure", "world")
              and type(self.actual_use) is UseID and type(self.actual_value) is ValueID
              and type(self.formal) is ValueID, "suite input mapping needs original frame ports")


@dataclass(frozen=True, slots=True)
class ClassSuiteCompletion:
    kind: ExitKind
    suite_exit: str
    provider_block: BlockID
    provider_values: tuple[ValueID, ...]

    def __post_init__(self):
        _need(type(self.kind) is ExitKind and type(self.suite_exit) is str and bool(self.suite_exit)
              and type(self.provider_block) is BlockID and type(self.provider_values) is tuple
              and all(type(v) is ValueID for v in self.provider_values), "suite completion mapping is invalid")


@dataclass(frozen=True, slots=True)
class ClassBuilderCompletion:
    kind: ExitKind
    provider_exit: str
    parent_block: BlockID
    parent_values: tuple[ValueID, ...]

    def __post_init__(self):
        _need(type(self.kind) is ExitKind and type(self.provider_exit) is str and bool(self.provider_exit)
              and type(self.parent_block) is BlockID and type(self.parent_values) is tuple
              and all(type(v) is ValueID for v in self.parent_values), "parent completion mapping is invalid")


@dataclass(frozen=True, slots=True)
class ClassBuilderExpansion:
    """A conditional implementation alternative, not replacement authority.

    Parent and suite are qualified original graph namespaces. Provider IDs are
    qualified by this record's own provider.graph. The unknown/custom-builder
    alternative remains the original parent INVOKE, unchanged.
    """
    parent: SourceBodyNamespace
    construction: ClassConstruction
    suite: SourceBodyNamespace
    provider: ClassBuilderProvider
    inputs: tuple[ClassBuilderInput, ...]
    suite_inputs: tuple[ClassSuiteInput, ...]
    suite_completions: tuple[ClassSuiteCompletion, ...]
    completions: tuple[ClassBuilderCompletion, ...]
    guards: tuple[ClassBuilderGuard, ...] = tuple(ClassBuilderGuard)
    original_builder_retained: bool = True
    status: str = "CONDITIONAL_CLASS_SUITE_PORTS_CONNECTED_EFFECTS_OPEN"

    def __post_init__(self):
        _need(type(self.parent) is type(self.suite) is SourceBodyNamespace
              and type(self.construction) is ClassConstruction and type(self.provider) is ClassBuilderProvider,
              "expansion needs original namespaces, construction and provider")
        for rows, kind in ((self.inputs, ClassBuilderInput), (self.suite_inputs, ClassSuiteInput),
                (self.suite_completions, ClassSuiteCompletion), (self.completions, ClassBuilderCompletion)):
            _need(type(rows) is tuple and all(type(x) is kind for x in rows), "invalid mapping table")
        _need(self.guards == tuple(ClassBuilderGuard) and self.original_builder_retained is True
              and self.status == "CONDITIONAL_CLASS_SUITE_PORTS_CONNECTED_EFFECTS_OPEN",
              "conditional expansion cannot erase unknown builder or claim closed effects")


@dataclass(frozen=True, slots=True)
class StaticClassBuilderBinding:
    """Stored relation; the provider implementation is shared by locator."""
    parent: SourceBodyNamespace
    construction: ClassConstruction
    suite: SourceBodyNamespace
    provider: SourceArtifactLocator
    inputs: tuple[ClassBuilderInput, ...]
    suite_inputs: tuple[ClassSuiteInput, ...]
    suite_completions: tuple[ClassSuiteCompletion, ...]
    completions: tuple[ClassBuilderCompletion, ...]
    guards: tuple[ClassBuilderGuard, ...] = tuple(ClassBuilderGuard)
    original_builder_retained: bool = True
    status: str = "CONDITIONAL_CLASS_SUITE_PORTS_CONNECTED_EFFECTS_OPEN"

    def __post_init__(self):
        _need(type(self.parent) is type(self.suite) is SourceBodyNamespace
              and type(self.construction) is ClassConstruction and type(self.provider) is SourceArtifactLocator,
              "stored binding needs qualified originals and a provider locator")
        for rows, kind in ((self.inputs, ClassBuilderInput), (self.suite_inputs, ClassSuiteInput),
                (self.suite_completions, ClassSuiteCompletion), (self.completions, ClassBuilderCompletion)):
            _need(type(rows) is tuple and all(type(x) is kind for x in rows), "invalid stored mapping table")
        _need(self.guards == tuple(ClassBuilderGuard) and self.original_builder_retained is True
              and self.status == "CONDITIONAL_CLASS_SUITE_PORTS_CONNECTED_EFFECTS_OPEN",
              "stored binding cannot erase unknown builder or close effects")
