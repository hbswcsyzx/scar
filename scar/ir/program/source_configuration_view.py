"""Declared input algebra; distinct from runtime Python configuration objects."""
from dataclasses import dataclass

from .ids import OperationID,RegionID,ValueID
from .providers import ProviderArtifact,ProviderFactReference
from .configuration_values import ConfigurationExpression,ConfigurationProjection,ConfigurationReadDemand,ConfigurationRoot,ConfigurationInterpolation


@dataclass(frozen=True,slots=True)
class ConfigurationRegion:
    id: RegionID
    values: ProviderArtifact
    boundary: ProviderFactReference
    layer: str = 'DECLARED_INPUT_ALGEBRA_NOT_RUNTIME_OPERATIONS'


@dataclass(frozen=True,slots=True)
class ConfigurationExpressionOperation:
    id: OperationID
    expression: ConfigurationExpression


@dataclass(frozen=True,slots=True)
class ConfigurationExpressionValue:
    id: ValueID
    expression: int


@dataclass(frozen=True,slots=True)
class ConfigurationProjectionValue:
    id: ValueID
    projection: ConfigurationProjection


@dataclass(frozen=True,slots=True)
class ConfigurationReadOperation:
    id: OperationID
    demand: ConfigurationReadDemand


@dataclass(frozen=True,slots=True)
class ConfigurationInterpolationOperation:
    id: OperationID
    interpolation: ConfigurationInterpolation


@dataclass(frozen=True,slots=True)
class ConfigurationDeclaredVersion:
    id: ValueID
    root: ConfigurationRoot
