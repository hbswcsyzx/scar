"""Exact def/use queries; deliberately independent of optimization decisions."""
from dataclasses import dataclass
from enum import Enum

from .environments import EnvironmentInterface, EnvironmentMember, FunctionEntryLayout
from .functions import FormalPort
from .ids import (BoundaryRelationID, EnvironmentInterfaceID, NativeBoundaryID,
                  OperationID, ProviderID, RegionID, UseID, ValueID)
from .model import ProgramGraph, StateVersionValue, TerminatorKind, Use
from .validation import require_valid
from .control import ProtocolValueKind
from .control_validation import derive_pending_facts
from .model import ProtocolValue
from .providers import ProviderBinding, ProviderEnvelope, ProviderRegion
from .native import BoundaryRelation, EntryPortRef, ExitPortRef, NativeBoundary
from .native_validation import port_key, region_port_keys


@dataclass(frozen=True, slots=True)
class UseSite:
    operation: OperationID
    use: Use


@dataclass(frozen=True, slots=True)
class ProviderRegionSource:
    """A declaration and its envelope, not equivalence or occurrence proof."""

    association: ProviderRegion
    envelope: ProviderEnvelope


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
        self._pending_facts = derive_pending_facts(graph) if graph.control_scopes else {}
        self._control_ports = {port.id: port for port in graph.control_ports}
        self._control_scope = {block: scope for scope in graph.control_scopes for block in scope.blocks}
        self._consumers = {value.id: [] for value in graph.values}
        self._uses = {}
        for operation in graph.operations:
            for use in operation.uses:
                site = UseSite(operation.id, use)
                self._consumers[use.value].append(site)
                self._uses[use.id] = site
        self._providers = {row.id: row for row in graph.provider_envelopes}
        self._provider_regions = {region.id: [] for region in graph.regions}
        for association in graph.provider_regions:
            self._provider_regions[association.region].append(ProviderRegionSource(
                association, self._providers[association.provider]))
        self._provider_sources = {}
        for binding in graph.provider_bindings:
            self._provider_sources.setdefault(binding.target, []).append(binding)
        self._native_boundaries = {row.id: row for row in graph.native_boundaries}
        self._native_regions = {row.region: row for row in graph.native_boundaries}
        self._boundary_relations = {row.id: row for row in graph.boundary_relations}
        self._boundary_incidence = {row.id: [] for row in graph.native_boundaries}
        for row in graph.boundary_relations:
            self._boundary_incidence[row.left].append(row)
            self._boundary_incidence[row.right].append(row)
        self._boundary_ports = {
            row.id: {port_key(item.port): item.port for item in
                     (*row.inputs, *row.core_inputs, *row.outputs, *row.core_outputs)}
            for row in graph.native_boundaries}
        self._region_ports = {row.id: region_port_keys(row) for row in graph.regions}
        self._entry_ports = {port: self.values[port[1]]
                             for entry, _ in self._region_ports.values() for port in entry}
        self._exit_ports = {port: [] for _, exits in self._region_ports.values() for port in exits}
        for region in graph.regions:
            for block in region.blocks:
                for identity in block.operations:
                    operation = self.operations[identity]
                    term = operation.terminator
                    if term is not None and term.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
                        for index, actual in enumerate(term.values):
                            self._exit_ports[(region.id, term.exit, index)].append(self._uses[actual])

    def producer(self, value_id: ValueID):
        return self.values[value_id].origin

    def consumers(self, value_id: ValueID) -> tuple[UseSite, ...]:
        return tuple(self._consumers[value_id])

    def use_site(self, use_id: UseID) -> UseSite:
        if type(use_id) is not UseID:
            raise TypeError("use_site requires canonical UseID")
        return self._uses[use_id]

    def provider_envelope(self, provider_id: ProviderID) -> ProviderEnvelope:
        if type(provider_id) is not ProviderID:
            raise TypeError("provider_envelope requires ProviderID")
        return self._providers[provider_id]

    def provider_region_sources(self, region_id: RegionID) -> tuple[ProviderRegionSource, ...]:
        """Return explicit representation owners and observation scopes separately.

        No declaration is inherited into child regions; no association denotes
        an actual runtime invocation or equivalence between representations.
        """
        if type(region_id) is not RegionID:
            raise TypeError("provider_region_sources requires RegionID")
        return tuple(self._provider_regions[region_id])

    def provider_sources(self, target: OperationID | ValueID | UseID) -> tuple[ProviderBinding, ...]:
        """Return exact declarations; an empty tuple is not proof of no sources."""
        registries = {OperationID: self.operations, ValueID: self.values, UseID: self._uses}
        registry = registries.get(type(target))
        if registry is None:
            raise TypeError("provider_sources needs OperationID, ValueID or UseID")
        if target not in registry:
            raise KeyError(target)
        return tuple(self._provider_sources.get(target, ()))

    def entry_arguments(self, region_id: RegionID):
        region = self.regions[region_id]
        block = next(block for block in region.blocks if block.id == region.entry)
        return tuple(self.values[value_id] for value_id in block.arguments)

    def native_boundary(self, boundary_id: NativeBoundaryID) -> NativeBoundary:
        if type(boundary_id) is not NativeBoundaryID:
            raise TypeError("native_boundary requires NativeBoundaryID")
        return self._native_boundaries[boundary_id]

    def native_boundary_for_region(self, region_id: RegionID) -> NativeBoundary | None:
        """Absence is a declaration gap, never proof of no native boundary."""
        if type(region_id) is not RegionID:
            raise TypeError("native_boundary_for_region requires RegionID")
        if region_id not in self.regions:
            raise KeyError(region_id)
        return self._native_regions.get(region_id)

    def entry_port(self, port: EntryPortRef):
        """Resolve the existing formal; no actual binding or tree is invented."""
        if type(port) is not EntryPortRef:
            raise TypeError("entry_port requires EntryPortRef")
        port.__post_init__()
        return self._entry_ports[port_key(port)]

    def exit_port_uses(self, port: ExitPortRef) -> tuple[UseSite, ...]:
        """All canonical Return/Raise occurrences at a logical exit position.

        Stable ordering is for presentation only, not execution order. Existing
        core validation requires every declared exit to have a control site;
        this index never creates a terminal or a producer to fill a missing one.
        """
        if type(port) is not ExitPortRef:
            raise TypeError("exit_port_uses requires ExitPortRef")
        port.__post_init__()
        return tuple(sorted(self._exit_ports[port_key(port)], key=lambda site: str(site.operation)))

    def native_input_values(self, boundary_id: NativeBoundaryID):
        return tuple(self.entry_port(slot.port) for slot in self.native_boundary(boundary_id).inputs)

    def native_output_uses(self, boundary_id: NativeBoundaryID) -> tuple[tuple[UseSite, ...], ...]:
        return tuple(self.exit_port_uses(slot.port) for slot in self.native_boundary(boundary_id).outputs)

    def boundary_relation(self, relation_id: BoundaryRelationID) -> BoundaryRelation:
        if type(relation_id) is not BoundaryRelationID:
            raise TypeError("boundary_relation requires BoundaryRelationID")
        return self._boundary_relations[relation_id]

    def boundary_relations(self, boundary_id: NativeBoundaryID) -> tuple[BoundaryRelation, ...]:
        self.native_boundary(boundary_id)
        return tuple(sorted(self._boundary_incidence[boundary_id], key=lambda row: str(row.id)))

    def boundary_unpaired_ports(self, relation_id: BoundaryRelationID):
        """Unpaired canonical ports, not evidence of absent data dependencies."""
        relation = self.boundary_relation(relation_id)
        result = []
        for side in ("left", "right"):
            boundary = self.native_boundary(getattr(relation, side))
            entry, exits = self._region_ports[boundary.region]
            paired = {port_key(getattr(pair, side)) for pair in relation.ports}
            refs = self._boundary_ports[boundary.id]
            result.append(tuple(refs[port] for port in (*entry, *exits) if port not in paired))
        return tuple(result)


    def environment_interface(self, region_id: RegionID) -> EnvironmentInterface | None:
        """Return a declaration; absence does not establish an empty environment."""
        if region_id not in self.regions:
            raise KeyError(region_id)
        return self._environments.get(region_id)

    def control_scope(self, block_id):
        """Declared lexical owner, never source correspondence/unwind proof."""
        if block_id not in {block.id for region in self.graph.regions for block in region.blocks}:
            raise KeyError(block_id)
        return self._control_scope.get(block_id)

    def pending_facts(self, value_id: ValueID):
        """Finite canonical CFG port facts; not dynamic dispatch or cleanup proof."""
        value = self.values[value_id]
        if not isinstance(value, ProtocolValue) or value.protocol is not ProtocolValueKind.PENDING_COMPLETION:
            raise TypeError("pending_facts needs a pending-completion protocol value")
        return self._pending_facts[value_id]

    def pending_ports(self, value_id: ValueID):
        return tuple(self._control_ports[identity] for identity in self.pending_facts(value_id).ports)

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
