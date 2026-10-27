"""Typed identifiers for the canonical program graph.

Each identifier inherits the wire encoding and equality behavior of the shared
v2 :class:`Identifier`, while its distinct prefix prevents accidental joins to
legacy graph nodes.
"""
from scar.ir.v2.ids import Identifier


class ValueID(Identifier):
    prefix = "program_value"


class LocationID(Identifier):
    prefix = "program_location"


class OperationID(Identifier):
    prefix = "program_operation"


class RegionID(Identifier):
    prefix = "program_region"


class BlockID(Identifier):
    prefix = "program_block"


class UseID(Identifier):
    prefix = "program_use"


class ResourceDefinitionID(Identifier):
    prefix = "program_resource"


class ResourceRequirementID(Identifier):
    prefix = "program_resource_requirement"


class EnvironmentInterfaceID(Identifier):
    prefix = "program_environment"


class ControlScopeID(Identifier):
    prefix = "program_control_scope"


class ControlPortID(Identifier):
    prefix = "program_control_port"


class ProviderID(Identifier):
    prefix = "program_provider"


class NativeBoundaryID(Identifier):
    prefix = "program_native_boundary"


class BoundaryRelationID(Identifier):
    prefix = "program_boundary_relation"


class ProtocolScopeID(Identifier):
    prefix = "program_protocol_scope"


__all__ = [
    "BlockID", "LocationID", "OperationID", "RegionID", "UseID", "ValueID",
    "ResourceDefinitionID", "ResourceRequirementID",
    "EnvironmentInterfaceID",
    "ControlScopeID", "ControlPortID",
    "ProviderID",
    "NativeBoundaryID", "BoundaryRelationID", "ProtocolScopeID",
]
