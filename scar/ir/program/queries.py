"""Exact def/use queries; deliberately independent of optimization decisions."""
from dataclasses import dataclass
from enum import Enum

from .environments import EnvironmentInterface, EnvironmentMember, FunctionEntryLayout
from .functions import FormalPort
from .ids import EnvironmentInterfaceID, OperationID, RegionID, ValueID
from .model import ProgramGraph, StateVersionValue, TerminatorKind, Use
from .validation import require_valid


@dataclass(frozen=True, slots=True)
class UseSite:
    operation: OperationID
    use: Use


class EnvironmentBindingStatus(str, Enum):
    DECLARED = "DECLARED"
    NO_DECLARED_CALLEE = "NO_DECLARED_CALLEE"
    NO_DECLARED_ENVIRONMENT = "NO_DECLARED_ENVIRONMENT"


@dataclass(frozen=True, slots=True)
class EnvironmentArgument:
    """Derived existing call Uses, not a second canonical binding store."""

    member: EnvironmentMember
    actual: UseSite
    state_arguments: tuple[UseSite, ...]


@dataclass(frozen=True, slots=True)
class FunctionArgument:
    parameter: FormalPort
    actual: UseSite


@dataclass(frozen=True, slots=True)
class EnvironmentCall:
    operation: OperationID
    callee: RegionID | None
    interface: EnvironmentInterfaceID | None
    status: EnvironmentBindingStatus
    arguments: tuple[EnvironmentArgument, ...]
    parameters: tuple[FunctionArgument, ...] = ()


class ProgramIndex:
    def __init__(self, graph: ProgramGraph):
        require_valid(graph)
        self.graph = graph
        self.values = {value.id: value for value in graph.values}
        self.regions = {region.id: region for region in graph.regions}
        self.operations = {operation.id: operation for operation in graph.operations}
        self._environments = {interface.region: interface for interface in graph.environments}
        self._function_entries = {layout.environment: layout for layout in graph.function_entries}
        self._consumers = {value.id: [] for value in graph.values}
        for operation in graph.operations:
            for use in operation.uses:
                self._consumers[use.value].append(UseSite(operation.id, use))

    def producer(self, value_id: ValueID):
        return self.values[value_id].origin

    def consumers(self, value_id: ValueID) -> tuple[UseSite, ...]:
        return tuple(self._consumers[value_id])

    def entry_arguments(self, region_id: RegionID):
        region = self.regions[region_id]
        block = next(block for block in region.blocks if block.id == region.entry)
        return tuple(self.values[value_id] for value_id in block.arguments)


    def environment_interface(self, region_id: RegionID) -> EnvironmentInterface | None:
        """Return a declaration; absence does not establish an empty environment."""
        if region_id not in self.regions:
            raise KeyError(region_id)
        return self._environments.get(region_id)

    def function_entry_layout(self, region_id: RegionID) -> FunctionEntryLayout | None:
        interface = self.environment_interface(region_id)
        return self._function_entries[interface.id] if interface is not None else None

    def environment_call(self, operation_id: OperationID) -> EnvironmentCall:
        """Follow canonical IR actuals, including implicit reference/state ports.

        IR call arguments are not the Python signature's explicit actuals.
        A declared binding does not prove runtime target/code, environment
        extraction, alias realization or a particular activation's denotation.
        """
        operation = self.operations[operation_id]
        if operation.callee is None:
            return EnvironmentCall(operation.id, None, None,
                                   EnvironmentBindingStatus.NO_DECLARED_CALLEE, ())
        interface = self._environments.get(operation.callee)
        if interface is None:
            return EnvironmentCall(operation.id, operation.callee, None,
                                   EnvironmentBindingStatus.NO_DECLARED_ENVIRONMENT, ())
        arguments = (operation.invoke_arguments
                     if operation.terminator is not None
                     and operation.terminator.kind is TerminatorKind.INVOKE
                     else operation.call_arguments)
        formals = self.entry_arguments(operation.callee)
        own_uses = {use.id: UseSite(operation.id, use) for use in operation.uses}
        bindings = {formal.id: own_uses[actual]
                    for formal, actual in zip(formals, arguments)}
        state_bindings = {formal.location: bindings[formal.id]
                          for formal in formals if isinstance(formal, StateVersionValue)}
        return EnvironmentCall(operation.id, operation.callee, interface.id,
                               EnvironmentBindingStatus.DECLARED, tuple(
            EnvironmentArgument(member, bindings[member.reference],
                                tuple(state_bindings[location] for location in member.locations))
            for member in interface.members), tuple(
            FunctionArgument(parameter, bindings[parameter.value])
            for parameter in self._function_entries[interface.id].parameters))


__all__ = ["ProgramIndex", "UseSite", "EnvironmentArgument", "EnvironmentCall",
           "EnvironmentBindingStatus", "FunctionArgument"]
