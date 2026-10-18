"""Canonical immutable program-graph record types.

Graph-wide validation and queries are available from ``program.validation``
and ``program.queries``. Typed records remain independently importable.
"""
from scar.ir.program.ids import (
    BlockID, EnvironmentInterfaceID, LocationID, OperationID, RegionID, ResourceDefinitionID,
    ResourceRequirementID, UseID, ValueID, ControlScopeID, ControlPortID,
    ProviderID,
    NativeBoundaryID, BoundaryRelationID,
)
from scar.ir.program.native import (
    BoundaryDomain, BoundaryObligation, BoundaryPortPair, BoundaryRelation,
    CoreInputPort, CoreOutputPort, EntryPortRef, ExitPortRef, NativeBoundary,
    NativeInputSlot, NativeOutputSlot,
)
from scar.ir.program.providers import (
    ProviderArtifact, ProviderArtifactKind, ProviderBinding, ProviderCaptureMode,
    ProviderCollectionDomain, ProviderCollectionObservation, ProviderCondition,
    ProviderConditionDomain, ProviderCoverage, ProviderCoverageDomain,
    ProviderElement, ProviderElementKind, ProviderEnvelope, ProviderFactReference,
    ProviderPathIndex, ProviderPathKey, ProviderRegion, ProviderRegionRelation,
    ProviderRunScope, ProviderStage,
)
from scar.ir.program.resources import (
    CapacityConstraint, CreatedResource, ExternalResource, RequirementRelation,
    ResourceDefinition, ResourceKind, ResourceLocation, ResourceRelationConstraint,
    ResourceRequirement, ResourceRole, ResourceUse,
)
from scar.ir.program.drivers import (
    AsyncRequestCreate, BodyDrive, BodyDriveResult, BodyDriveSuccessor,
    BodyDriveTerminator, BodyResume, BodyResumeInput, BodyStart, BodyStateInput,
    CreationCapture, DriverInterface, DriverReceiverKind, DriverRule,
    DriverRuleProfile, FinalBodyGate, NormalResultPort, RawRequestDefinition,
    RawRequestKind, RequestAssociationRead, ResumableCreate,
)
from scar.ir.program.bindings import BindingDefinition, BindingRead, BindingState
from scar.ir.program.environments import (
    EnvironmentInterface, EnvironmentMember, EnvironmentRole, FunctionEntryLayout,
)
from scar.ir.program.control import (
    ControlPort, ControlScope, ControlScopeKind, ExceptionPacketDefinition,
    LanguageCompletionKind, PendingCompletionDefinition, PendingDispatchTerminator,
    PendingPayload, PendingSuccessor, ProtocolValueKind, ProtocolValueType,
)
from scar.ir.program.cleanup import (
    CleanupEnter, CleanupInterface, CleanupReplace, CleanupResume,
    CleanupRouteSuccessor, CleanupRouteTerminator, HandledContextDomain, HandledContextRead,
)
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult,
    CompletionSignature, CompletionSuccessor, DataValue, ExitKind, ExitPort,
    Footprint, FootprintKind, LiteralOrigin, Operation, OperationResult, OrderEdge,
    LocalBindingType, LocalBindingValue, ProgramValueType, ProtocolValue,
    ProgramGraph, ReferenceValue, Region, Stability, StateAccess, StateLocation,
    StateVersionValue, Successor, Terminator, TerminatorKind, Use, UseRole,
    Value, ValueKind, ValueType, value_type,
)
from scar.ir.program.codec import SCHEMA, SCHEMA_VERSION, dumps, loads
from scar.ir.program.binding_validation import derive_binding_facts


from .resumption import (
    FrameContextAttach, FrameContextDetach, FrameContextInitial, ResumableBody,
    ResumableKind, ResumeInput, ResumeSlot, ResumeSlotKind, ResumeSuccessor,
    SavedInput, SavedRole, SavedSlot, SuspendTerminator, SuspensionFlavor,
)

__all__ = [
    "FrameContextAttach", "FrameContextDetach", "FrameContextInitial", "ResumableBody",
    "ResumableKind", "ResumeInput", "ResumeSlot", "ResumeSlotKind", "ResumeSuccessor",
    "SavedInput", "SavedRole", "SavedSlot", "SuspendTerminator", "SuspensionFlavor",
    "AccessMode", "Behavior", "BindingDefinition", "BindingRead", "BindingState",
    "Block", "BlockArgument", "BlockID",
    "CompletionResult", "CompletionSignature", "CompletionSuccessor", "DataValue",
    "ExitKind", "ExitPort", "Footprint", "FootprintKind", "LiteralOrigin",
    "LocalBindingType", "LocalBindingValue", "LocationID", "Operation", "OperationID", "OperationResult", "OrderEdge",
    "ProgramGraph", "ProgramValueType", "ReferenceValue", "Region", "RegionID", "SCHEMA",
    "SCHEMA_VERSION", "Stability", "StateAccess", "StateLocation",
    "StateVersionValue", "Successor", "Terminator", "TerminatorKind", "Use",
    "UseID", "UseRole", "Value", "ValueID", "ValueKind", "ValueType",
    "derive_binding_facts", "dumps", "loads", "value_type",
    "CapacityConstraint", "CreatedResource", "ExternalResource", "RequirementRelation",
    "ResourceDefinition", "ResourceDefinitionID", "ResourceKind", "ResourceLocation",
    "ResourceRelationConstraint", "ResourceRequirement", "ResourceRequirementID",
    "ResourceRole", "ResourceUse",
    "EnvironmentInterface", "EnvironmentInterfaceID", "EnvironmentMember", "EnvironmentRole",
    "FunctionEntryLayout",
    "ControlPort", "ControlPortID", "ControlScope", "ControlScopeID", "ControlScopeKind",
    "ExceptionPacketDefinition", "LanguageCompletionKind", "PendingCompletionDefinition",
    "PendingDispatchTerminator", "PendingPayload", "PendingSuccessor", "ProtocolValue",
    "ProtocolValueKind", "ProtocolValueType",
    "CleanupEnter", "CleanupInterface", "CleanupReplace", "CleanupResume",
    "CleanupRouteSuccessor", "CleanupRouteTerminator", "HandledContextDomain", "HandledContextRead",
    "ProviderID", "ProviderArtifact", "ProviderArtifactKind", "ProviderBinding",
    "ProviderCaptureMode", "ProviderCollectionDomain", "ProviderCollectionObservation",
    "ProviderCondition", "ProviderConditionDomain", "ProviderCoverage", "ProviderCoverageDomain",
    "ProviderElement", "ProviderElementKind", "ProviderEnvelope", "ProviderFactReference",
    "ProviderPathIndex", "ProviderPathKey", "ProviderRegion", "ProviderRegionRelation",
    "ProviderRunScope", "ProviderStage",
    "NativeBoundaryID", "BoundaryRelationID", "BoundaryDomain", "BoundaryObligation",
    "BoundaryPortPair", "BoundaryRelation", "CoreInputPort", "CoreOutputPort",
    "EntryPortRef", "ExitPortRef", "NativeBoundary", "NativeInputSlot", "NativeOutputSlot",
    "AsyncRequestCreate", "BodyDrive", "BodyDriveResult", "BodyDriveSuccessor",
    "BodyDriveTerminator", "BodyResume", "BodyResumeInput", "BodyStart", "BodyStateInput",
    "CreationCapture", "DriverInterface", "DriverReceiverKind", "DriverRule",
    "DriverRuleProfile", "FinalBodyGate", "NormalResultPort", "RawRequestDefinition",
    "RawRequestKind", "RequestAssociationRead", "ResumableCreate",
]
