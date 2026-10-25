"""SourceProgram6 mapping-frame entry overlays over existing core identities.

A declaration survives an unsupported body without dangling core ports. Only
an actual returned graph may carry MappingFrameEntry and correspondence.
These records grant no import, namespace identity, runtime or effect proof.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
import re

from scar.ir.program.call_edges import CapturedCode, CodeSourceLink
from scar.ir.program.frames import FrameRules
from scar.ir.program.ids import OperationID, RegionID, UseID, ValueID
from scar.ir.program.inventory import SourceContextDigest
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source import SourceRole
from scar.ir.program.structured import PythonProtocolKind, LoopInterface
from scar.ir.record_codec import decode, encode
from scar.ir.semantics_v2 import Opcode, SourceSnapshot
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID, StaticValueID, ValueSlotID


class ModuleEntryProfile(str, Enum):
    EXEC_MAPPING_314_V1 = "EXEC_MAPPING_314_V1"


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


@dataclass(frozen=True, slots=True)
class ModuleUnitSource:
    snapshot: SourceSnapshot
    namespace_root: str
    initializer: OperationDefinitionID

    def __post_init__(self):
        _need(type(self.snapshot) is SourceSnapshot and type(self.initializer) is OperationDefinitionID,
              "unit requires original snapshot and MODULE initializer")
        _need(type(self.namespace_root) is str and PurePosixPath(self.namespace_root).is_absolute()
              and PurePosixPath(self.snapshot.path).is_relative_to(PurePosixPath(self.namespace_root)),
              "unit must retain its absolute original source namespace")


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
