"""SourceProgram6 mapping-frame entry overlays over existing core identities.

A declaration survives an unsupported body without dangling core ports. Only
an actual returned graph may carry MappingFrameEntry and correspondence.
These records grant no import, namespace identity, runtime or effect proof.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from scar.ir.program.call_edges import CapturedCode, CodeSourceLink
from scar.ir.program.frames import FrameRules
from scar.ir.program.ids import BlockID, ControlScopeID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.inventory import SourceContextDigest
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source import SourceRole
from scar.ir.program.source_subjects import ModuleUnitSource, SourceCompilationCodeRef
from scar.ir.program.structured import PythonProtocolKind, LoopInterface
from scar.ir.program.source_language import CodeConstantSource
from scar.ir.record_codec import decode, encode
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import (OperationDefinitionID, StaticValueID, ValueSlotID,
    ControlFlowSuiteID, ControlFlowNodeID, InsertionPointID)


class ModuleEntryProfile(str, Enum):
    EXEC_MAPPING_314_V1 = "EXEC_MAPPING_314_V1"
    STATIC_EXEC_MAPPING_314_V1 = "STATIC_EXEC_MAPPING_314_V1"


class ModuleBodyStatus(str, Enum):
    UNSUPPORTED = "ENTRY_DECLARED_BODY_UNSUPPORTED"
    PARTIAL = "ENTRY_GRAPH_WITH_UNEXPANDED_BODY"


class ModuleProtocolKind(str, Enum):
    INVOKE_MODULE_BODY = "INVOKE_MODULE_BODY"
    UNEXPANDED_BODY = "UNEXPANDED_MODULE_BODY"


class RequiredModuleExpansion(str, Enum):
    REQUIRED = "REQUIRED"


def _need(condition, detail):
    if not condition:
        raise ValueError("module entry: " + detail)


ModuleSource = ModuleUnitSource | SourceReference


@dataclass(frozen=True, slots=True)
class ModuleCodeWitness:
    captured: CapturedCode
    source_link: CodeSourceLink
    manifest: ProviderArtifact
    module_artifact: ProviderArtifact
    module_key: str

    def __post_init__(self):
        _need(type(self.captured) is CapturedCode and type(self.source_link) is CodeSourceLink,
              "root witness requires exact existing code/source records")
        _need(type(self.manifest) is ProviderArtifact and type(self.module_artifact) is ProviderArtifact,
              "root witness requires exact original archive receipts")
        _need(type(self.module_key) is str and re.fullmatch(r"[0-9a-f]{64}", self.module_key) is not None,
              "root witness requires exact compiler module key")


@dataclass(frozen=True, slots=True)
class ModuleCatalogEntry:
    unit: ModuleUnitSource
    context: SourceContextDigest
    file_index: int

    def __post_init__(self):
        _need(type(self.unit) is ModuleUnitSource and type(self.context) is SourceContextDigest
              and self.context.namespace_root == self.unit.namespace_root,
              "module catalog must retain the original qualified source context")
        _need(type(self.file_index) is int and self.file_index >= 0, "invalid original file index")


@dataclass(frozen=True, slots=True)
class ModuleEntryDeclaration:
    unit: ModuleUnitSource
    witness: ModuleCodeWitness
    closure_names: tuple[str, ...] = ()
    profile: ModuleEntryProfile = ModuleEntryProfile.EXEC_MAPPING_314_V1

    def __post_init__(self):
        _need(type(self.unit) is ModuleUnitSource and type(self.witness) is ModuleCodeWitness,
              "declaration needs source unit and compiler-root witness")
        _need(self.profile is ModuleEntryProfile.EXEC_MAPPING_314_V1,
              "unsupported mapping frame entry capability")
        _need(type(self.closure_names) is tuple and not self.closure_names,
              "nonempty mapping-frame closure is not connected by this capability")


@dataclass(frozen=True, slots=True)
class StaticModuleEntryDeclaration:
    """A source-compiled exec root; no captured or loaded-module identity."""

    unit: ModuleUnitSource
    compilation: SourceCompilationCodeRef
    closure_names: tuple[str, ...] = ()
    profile: ModuleEntryProfile = ModuleEntryProfile.STATIC_EXEC_MAPPING_314_V1

    def __post_init__(self):
        _need(type(self.unit) is ModuleUnitSource and type(self.compilation) is SourceCompilationCodeRef,
              "static declaration needs its original source unit and compiler provenance")
        self.compilation.__post_init__()
        _need(self.compilation.source == self.unit and self.compilation.definition == self.unit.initializer
              and not self.compilation.code_path, "static declaration must bind the exact module compiler root")
        _need(self.profile is ModuleEntryProfile.STATIC_EXEC_MAPPING_314_V1
              and type(self.closure_names) is tuple and not self.closure_names,
              "unsupported static module entry profile or closure")


@dataclass(frozen=True, slots=True)
class MappingFrameEntry:
    unit: ModuleUnitSource
    region: RegionID
    locals_namespace: ValueID
    globals_namespace: ValueID
    builtins_namespace: ValueID
    closure_cells: tuple[ValueID, ...]
    world: ValueID

    def __post_init__(self):
        _need(type(self.unit) is ModuleUnitSource and type(self.region) is RegionID,
              "interface needs original unit and core Region")
        refs = (self.locals_namespace, self.globals_namespace, self.builtins_namespace)
        _need(all(type(value) is ValueID for value in refs) and type(self.world) is ValueID,
              "namespace/world ports must be existing core ValueIDs")
        _need(type(self.closure_cells) is tuple and not self.closure_cells,
              "nonempty mapping-frame closure is unsupported")
        _need(self.world not in refs, "world must be separate from Python reference ports")
        # Distinct ports do not assert distinct Python objects. Alias is UNKNOWN.


@dataclass(frozen=True, slots=True)
class ModuleFrontier:
    source: ModuleSource
    kind: str
    detail: str

    def __post_init__(self):
        _need(type(self.source) in (ModuleUnitSource, SourceReference), "frontier needs exact source origin")
        _need(type(self.kind) is str and bool(self.kind) and type(self.detail) is str and bool(self.detail.strip()),
              "frontier needs a concrete kind and detail")


@dataclass(frozen=True, slots=True)
class ModuleSourceCensus:
    source_atoms: int
    semantic_operations: int
    cfg_nodes: int
    cfg_edges: int

    def __post_init__(self):
        _need(all(type(value) is int and value >= 0 for value in (
            self.source_atoms, self.semantic_operations, self.cfg_nodes, self.cfg_edges)),
            "source census requires nonnegative exact counts")


@dataclass(frozen=True, slots=True)
class ModuleOperationSource:
    operation: OperationID
    source: ModuleSource
    role: SourceRole
    semantic_operation: OperationDefinitionID | None = None
    opcode: Opcode | None = None


@dataclass(frozen=True, slots=True)
class ModuleValueSource:
    value: ValueID
    source: ModuleSource
    role: SourceRole
    slot: ValueSlotID | None = None
    semantic_value: StaticValueID | None = None


@dataclass(frozen=True, slots=True)
class ModuleUseSource:
    operation: OperationID
    use: UseID
    source: ModuleSource
    role: str
    index: int
    semantic_value: StaticValueID | None = None

    def __post_init__(self):
        _need(type(self.role) is str and bool(self.role) and type(self.index) is int and self.index >= 0,
              "Use correspondence requires ordered original roles")


@dataclass(frozen=True, slots=True)
class ModuleProtocol:
    operation: OperationID
    kind: ModuleProtocolKind | PythonProtocolKind
    source: ModuleSource


@dataclass(frozen=True, slots=True)
class UnexpandedModuleBody:
    """A whole-source child interface, not an assertion its internals ran."""
    unit: ModuleUnitSource
    context: SourceContextDigest
    region: RegionID
    operation: OperationID
    required_expansion: RequiredModuleExpansion = RequiredModuleExpansion.REQUIRED

    def __post_init__(self):
        _need(type(self.unit) is ModuleUnitSource and type(self.context) is SourceContextDigest
              and self.context.namespace_root == self.unit.namespace_root,
              "unexpanded body must retain its exact original source context")
        _need(type(self.region) is RegionID and type(self.operation) is OperationID,
              "unexpanded body must reference the actual core child interface")
        _need(self.required_expansion is RequiredModuleExpansion.REQUIRED,
              "an opaque body never discharges required expansion")


@dataclass(frozen=True, slots=True)
class ModuleBodyOverlay:
    declaration: ModuleEntryDeclaration
    status: ModuleBodyStatus
    census: ModuleSourceCensus
    interface: MappingFrameEntry | None
    frontiers: tuple[ModuleFrontier, ...]
    operations_emitted: int = 0
    operation_links: tuple[ModuleOperationSource, ...] = ()
    value_links: tuple[ModuleValueSource, ...] = ()
    use_links: tuple[ModuleUseSource, ...] = ()
    protocols: tuple[ModuleProtocol, ...] = ()
    loops: tuple[LoopInterface, ...] = ()
    frame_rules: FrameRules = FrameRules()
    unexpanded_body: UnexpandedModuleBody | None = None

    def __post_init__(self):
        _need(type(self.declaration) is ModuleEntryDeclaration and type(self.census) is ModuleSourceCensus,
              "overlay requires declaration and original source census")
        _need(type(self.status) is ModuleBodyStatus and type(self.operations_emitted) is int
              and self.operations_emitted >= 0, "invalid body status/construction count")
        if self.status is ModuleBodyStatus.UNSUPPORTED:
            _need(self.interface is None and not any((self.operation_links, self.value_links, self.use_links,
                  self.protocols, self.loops, self.unexpanded_body)) and bool(self.frontiers),
                  "unsupported body retains only declaration/frontiers, no dangling core ports")
        else:
            _need(type(self.interface) is MappingFrameEntry, "lowered body requires a real core interface")
        _need((self.status is ModuleBodyStatus.PARTIAL) == (type(self.unexpanded_body) is UnexpandedModuleBody),
              "partial entry graph must retain exactly its typed unexpanded body")
        _need(type(self.frame_rules) is FrameRules, "mapping frame must retain existing conditional lifetime rules")
        self.frame_rules.__post_init__()


MODULE_RECORD_TAGS = {ModuleUnitSource: ("source_kind", "MODULE_UNIT"),
                      SourceReference: ("source_kind", "SOURCE_ATOM")}


def encode_module_overlay(value):
    return encode(value, record_tags=MODULE_RECORD_TAGS)


def decode_module_overlay(value):
    return decode(ModuleBodyOverlay, value, record_tags=MODULE_RECORD_TAGS)


class ModuleBodyExpansionProfile(str, Enum):
    IMPORT_PREFIX_314_V1 = "MODULE_IMPORT_PREFIX_314_V1"


class ModulePrefixProtocolKind(str, Enum):
    INVOKE_IMPORT_PREFIX = "INVOKE_IMPORT_PREFIX"
    IMPORT_NAME_314 = "IMPORT_NAME_314"
    STORE_NAME_314 = "STORE_NAME_314"
    INVOKE_REMAINING = "INVOKE_REMAINING_STATEMENTS"
    UNEXPANDED_SLICE = "UNEXPANDED_STATEMENT_SLICE"


@dataclass(frozen=True, slots=True)
class ModuleStatementSlice:
    """Ordered original module.body suffix plus its original CFG boundary."""
    unit: ModuleUnitSource
    context: SourceContextDigest
    statements: tuple[SourceReference, ...]
    suite: ControlFlowSuiteID
    before: InsertionPointID

    def __post_init__(self):
        _need(type(self.unit) is ModuleUnitSource and type(self.context) is SourceContextDigest
              and self.context.namespace_root == self.unit.namespace_root, "slice source context differs")
        _need(type(self.statements) is tuple and bool(self.statements)
              and all(type(ref) is SourceReference and ref.path == self.unit.snapshot.path
                      and ref.fingerprint == self.unit.snapshot.fingerprint for ref in self.statements)
              and len(set(self.statements)) == len(self.statements), "slice requires unique ordered original statements")
        _need(type(self.suite) is ControlFlowSuiteID and type(self.before) is InsertionPointID,
              "slice requires original source control suite and BEFORE insertion")


@dataclass(frozen=True, slots=True)
class UnexpandedModuleSlice:
    subject: ModuleStatementSlice
    region: RegionID
    operation: OperationID
    required_expansion: RequiredModuleExpansion = RequiredModuleExpansion.REQUIRED

    def __post_init__(self):
        _need(type(self.subject) is ModuleStatementSlice and type(self.region) is RegionID
              and type(self.operation) is OperationID, "residual requires its exact source subject and core endpoints")
        _need(self.required_expansion is RequiredModuleExpansion.REQUIRED,
              "residual body must retain required expansion")


@dataclass(frozen=True, slots=True)
class ModuleImportPrefix:
    source: SourceReference
    sg_definition: OperationDefinitionID
    cfg_node: ControlFlowNodeID
    region: RegionID
    import_operation: OperationID
    store_operation: OperationID
    import_code_offset: int
    store_code_offset: int

    def __post_init__(self):
        _need(type(self.source) is SourceReference and type(self.sg_definition) is OperationDefinitionID
              and type(self.cfg_node) is ControlFlowNodeID and type(self.region) is RegionID
              and type(self.import_operation) is OperationID and type(self.store_operation) is OperationID,
              "import prefix requires original source/SG/CFG and existing core endpoints")
        _need(type(self.import_code_offset) is int and self.import_code_offset >= 0
              and type(self.store_code_offset) is int and self.store_code_offset > self.import_code_offset,
              "prefix offsets require ordered locations in the same original root code")


@dataclass(frozen=True, slots=True)
class ModulePrefixProtocol:
    operation: OperationID
    kind: ModulePrefixProtocolKind | ModuleProtocolKind | PythonProtocolKind
    source: ModuleSource


@dataclass(frozen=True, slots=True)
class ModulePrefixOverlay:
    """SP7 indices over original facts/core, with no stored-content proof.

    IMPORT_NAME owns level/fromlist until its opcode completion; STORE_NAME
    consumes its stack input on both completions. Neither rule establishes
    physical reclamation. Namespace addresses describe protocol attempts only.
    """
    declaration: ModuleEntryDeclaration
    census: ModuleSourceCensus
    interface: MappingFrameEntry
    body_region: RegionID
    prefix: ModuleImportPrefix
    remaining: UnexpandedModuleSlice
    frontiers: tuple[ModuleFrontier, ...]
    operations_emitted: int
    operation_links: tuple[ModuleOperationSource, ...]
    value_links: tuple[ModuleValueSource, ...]
    use_links: tuple[ModuleUseSource, ...]
    protocols: tuple[ModulePrefixProtocol, ...]
    frame_rules: FrameRules = FrameRules()
    status: ModuleBodyStatus = ModuleBodyStatus.PARTIAL
    profile: ModuleBodyExpansionProfile = ModuleBodyExpansionProfile.IMPORT_PREFIX_314_V1

    def __post_init__(self):
        _need(type(self.declaration) is ModuleEntryDeclaration and type(self.census) is ModuleSourceCensus
              and type(self.interface) is MappingFrameEntry and type(self.body_region) is RegionID,
              "prefix overlay requires the unchanged mapping ABI and original source census")
        _need(type(self.prefix) is ModuleImportPrefix and type(self.remaining) is UnexpandedModuleSlice,
              "prefix overlay requires exact prefix and residual subjects")
        _need(self.profile is ModuleBodyExpansionProfile.IMPORT_PREFIX_314_V1
              and self.status is ModuleBodyStatus.PARTIAL, "prefix capability remains partial")
        _need(type(self.operations_emitted) is int and self.operations_emitted > 0
              and type(self.frame_rules) is FrameRules, "invalid prefix construction/frame contract")
        self.frame_rules.__post_init__()


def encode_module_prefix(value):
    return encode(value, record_tags=MODULE_RECORD_TAGS)


def decode_module_prefix(value):
    return decode(ModulePrefixOverlay, value, record_tags=MODULE_RECORD_TAGS)


class FrameBodyProfile(str, Enum):
    STRUCTURED_MAPPING_314_V1 = 'STRUCTURED_MAPPING_314_V1'
    STRUCTURED_MAPPING_PROPAGATION_314_V1 = 'STRUCTURED_MAPPING_PROPAGATION_314_V1'


class NamespacePolicy(str, Enum):
    MODULE_MAPPING_314_V1 = 'MODULE_MAPPING_314_V1'


class FrameCompletionProfile(str, Enum):
    RAW_EXCEPTION_REF_314_V1 = 'RAW_EXCEPTION_REF_314_V1'
    PROPAGATION_REF_PAIR_314_V1 = 'PROPAGATION_REF_PAIR_314_V1'


class StatementSequenceField(str, Enum):
    BODY = 'BODY'
    ORELSE = 'ORELSE'
    HANDLER_BODY = 'HANDLER_BODY'
    FINALBODY = 'FINALBODY'


class SourceControlBoundary(str, Enum):
    EXACT_OLD_ANCHOR = 'EXACT_OLD_ANCHOR'
    NO_EXACT_OLD_ANCHOR = 'NO_EXACT_OLD_ANCHOR'


class FrameBodyProtocolKind(str, Enum):
    LOAD_NAME_314 = 'LOAD_NAME_314'
    STORE_NAME_314 = 'STORE_NAME_314'
    IMPORT_NAME_314 = 'IMPORT_NAME_314'
    IMPORT_FROM_314 = 'IMPORT_FROM_314'
    INVOKE_REMAINING = 'INVOKE_REMAINING'
    UNEXPANDED_SLICE = 'UNEXPANDED_SLICE'
    DELETE_NAME_314 = 'DELETE_NAME_314'
    VALIDATE_EXCEPT_TYPE_314 = 'VALIDATE_EXCEPT_TYPE_314'
    MATCH_EXCEPTION_BORROWED_314 = 'MATCH_EXCEPTION_BORROWED_314'
    FRAME_EXIT_EXCEPTION_PACKET = 'FRAME_EXIT_EXCEPTION_PACKET'


class FrameBodyStatus(str, Enum):
    PARTIAL = 'SOURCE_PREFIX_WITH_REQUIRED_SLICE'
    TOPOLOGY_RECOVERED = 'SOURCE_TOPOLOGY_RECOVERED_WITH_OPEN'


@dataclass(frozen=True, slots=True)
class FrameStatementSlice:
    """Exact source collection; anchors never invent coverage for old CFG gaps."""
    unit: ModuleUnitSource
    context: SourceContextDigest
    owner: ModuleSource
    field: StatementSequenceField
    statements: tuple[SourceReference, ...]
    boundary: SourceControlBoundary
    suite: ControlFlowSuiteID | None = None
    before: InsertionPointID | None = None

    def __post_init__(self):
        _need(type(self.unit) is ModuleUnitSource and type(self.context) is SourceContextDigest
              and self.context.namespace_root == self.unit.namespace_root, 'frame slice requires exact unit/context')
        _need(type(self.owner) in (ModuleUnitSource, SourceReference)
              and type(self.field) is StatementSequenceField, 'frame slice requires a typed lexical sequence')
        _need(type(self.statements) is tuple and bool(self.statements)
              and all(type(ref) is SourceReference and ref.path == self.unit.snapshot.path
                  and ref.fingerprint == self.unit.snapshot.fingerprint for ref in self.statements)
              and len(set(self.statements)) == len(self.statements), 'frame slice needs distinct ordered original members')
        _need(type(self.boundary) is SourceControlBoundary, 'frame slice boundary needs a closed status')
        if self.boundary is SourceControlBoundary.EXACT_OLD_ANCHOR:
            _need(type(self.suite) is ControlFlowSuiteID and type(self.before) is InsertionPointID,
                  'exact old boundary requires its actual suite/insertion')
        else:
            _need(self.suite is None and self.before is None, 'missing old boundary cannot acquire invented anchors')


@dataclass(frozen=True, slots=True)
class FrameStatementExpansion:
    source: SourceReference
    region: RegionID
    entry: BlockID
    normal: BlockID | None
    operations: tuple[OperationID, ...]
    child_slices: tuple[FrameStatementSlice, ...] = ()


@dataclass(frozen=True, slots=True)
class UnexpandedFrameSlice:
    subject: FrameStatementSlice
    region: RegionID
    operation: OperationID
    required_expansion: RequiredModuleExpansion = RequiredModuleExpansion.REQUIRED

    def __post_init__(self):
        _need(type(self.subject) is FrameStatementSlice and type(self.region) is RegionID
              and type(self.operation) is OperationID, 'frame debt requires exact collection and core interface')
        _need(self.required_expansion is RequiredModuleExpansion.REQUIRED, 'unexpanded slice cannot discharge itself')


@dataclass(frozen=True, slots=True)
class FrameBodyProtocol:
    operation: OperationID
    kind: FrameBodyProtocolKind | PythonProtocolKind
    source: ModuleSource


@dataclass(frozen=True, slots=True)
class StructuredFrameBodyOverlay:
    """Source indices over core29's sole FrameRoot entry authority.

    B's raw exception-reference boundary is not C0's exception packet and
    supplies no traceback/pending/handled-context proof. Later capabilities
    may connect those existing core relations without another body wire.
    """
    declaration: ModuleEntryDeclaration | StaticModuleEntryDeclaration
    census: ModuleSourceCensus
    root_scope: ControlScopeID
    prefix: FrameStatementSlice | None
    expansions: tuple[FrameStatementExpansion, ...]
    remaining: UnexpandedFrameSlice | None
    frontiers: tuple[ModuleFrontier, ...]
    operations_emitted: int
    operation_links: tuple[ModuleOperationSource, ...]
    value_links: tuple[ModuleValueSource, ...]
    use_links: tuple[ModuleUseSource, ...]
    protocols: tuple[FrameBodyProtocol, ...]
    loops: tuple[LoopInterface, ...]
    constants: tuple[CodeConstantSource, ...]
    namespace_policy: NamespacePolicy = NamespacePolicy.MODULE_MAPPING_314_V1
    completion_profile: FrameCompletionProfile = FrameCompletionProfile.RAW_EXCEPTION_REF_314_V1
    profile: FrameBodyProfile = FrameBodyProfile.STRUCTURED_MAPPING_314_V1
    frame_rules: FrameRules = FrameRules()

    @property
    def status(self):
        return FrameBodyStatus.PARTIAL if self.remaining is not None else FrameBodyStatus.TOPOLOGY_RECOVERED

    def __post_init__(self):
        _need(type(self.declaration) in (ModuleEntryDeclaration, StaticModuleEntryDeclaration) and type(self.census) is ModuleSourceCensus
              and type(self.root_scope) is ControlScopeID, 'structured frame needs original source and its sole core root')
        _need((self.profile,self.completion_profile) in (
                  (FrameBodyProfile.STRUCTURED_MAPPING_314_V1,FrameCompletionProfile.RAW_EXCEPTION_REF_314_V1),
                  (FrameBodyProfile.STRUCTURED_MAPPING_PROPAGATION_314_V1,FrameCompletionProfile.PROPAGATION_REF_PAIR_314_V1))
              and self.namespace_policy is NamespacePolicy.MODULE_MAPPING_314_V1,
              'unsupported explicit structured mapping/completion profile')
        _need(type(self.operations_emitted) is int and self.operations_emitted > 0
              and (self.prefix is None or type(self.prefix) is FrameStatementSlice)
              and (self.remaining is None or type(self.remaining) is UnexpandedFrameSlice), 'invalid frame construction/partition')
        _need(type(self.frame_rules) is FrameRules, 'frame must preserve conditional lifetime contract')
        self.frame_rules.__post_init__()


def encode_frame_body(value):
    return encode(value, record_tags=MODULE_RECORD_TAGS)


def decode_frame_body(value):
    return decode(StructuredFrameBodyOverlay, value, record_tags=MODULE_RECORD_TAGS)
