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


__all__ = [
    "BlockID", "LocationID", "OperationID", "RegionID", "UseID", "ValueID",
    "ResourceDefinitionID", "ResourceRequirementID",
    "EnvironmentInterfaceID",
    "ControlScopeID", "ControlPortID",
]
