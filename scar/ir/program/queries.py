"""Exact def/use queries; deliberately independent of optimization decisions."""
from dataclasses import dataclass
from enum import Enum

from .environments import EnvironmentInterface, EnvironmentMember, FunctionEntryLayout
from .functions import FormalPort
from .ids import (BlockID, BoundaryRelationID, ControlScopeID, EnvironmentInterfaceID,
                  NativeBoundaryID, OperationID, ProviderID, RegionID, UseID, ValueID)
from .model import (CompletionResult, CompletionSuccessor, DataValue, ExitKind, Operation, ProgramGraph, ReferenceValue,
                    StateAccess, StateVersionValue, Successor, TerminatorKind, Use)
from .control import ProtocolValueKind
from .control_validation import derive_pending_facts
from .model import ProtocolValue
from .providers import ProviderBinding, ProviderEnvelope, ProviderRegion
from .native import BoundaryRelation, EntryPortRef, ExitPortRef, NativeBoundary
from .native_validation import port_key, region_port_keys
from .cleanup_validation import CleanupRouteKind, CleanupRouteStep
from .resumption import ResumeInput, ResumeSlot, ResumeSlotKind, SuspendTerminator, saved_actual_use
from .resumption_flow import first_body_outcome_operations
from .drivers import BodyDrive, BodyDriveResult, DriverInterface, NormalResultPort
from .driver_flow import body_drive_target, body_outcome_uses
from .lifecycle import (
    BodyOutcomeCommit, CreatedCloseTest, DriverLifecycle, LifecyclePostBinding, NoBodyFinish,
    SessionUpdate, TerminalFrameRelease,
)
from .lifecycle_flow import TerminalPointFacts
from .session_flow import SessionPointFacts
from .protocols import NoEntryOutcome, ProtocolOperation
from .protocol_flow import ProtocolPort
from .structured import ControlEdgeReference
from .state_addresses import (
    ExistingAccess, InvokeStateOperand, ReferenceOwner, ResourceOwner,
    StateAddressSite, UnknownOwner, address_effect_uses,
)
from scar.ir.v2.common import ProofStatus


@dataclass(frozen=True, slots=True)
class UseSite:
    operation: OperationID
    use: Use


@dataclass(frozen=True, slots=True)
class ResumptionBinding:
    """A landing parameter's declared saved source or later ingress slot."""

    formal: ValueID
    saved: UseSite | None
    supplied: ResumeSlot | None


@dataclass(frozen=True, slots=True)
class SuspensionHandoff:
    exported: UseSite
    states: tuple[UseSite, ...]


@dataclass(frozen=True, slots=True)
class BodyOutcomeSite:
    """A source operation's exported outcome operands, without saved/private slots."""

    operation: OperationID
    kind: TerminatorKind
    values: tuple[UseSite, ...]


@dataclass(frozen=True, slots=True)
class DriverBinding:
    """An existing formal and its canonical source Use, without a new producer."""

    formal: ValueID
    actual: UseSite


@dataclass(frozen=True, slots=True)
class InstanceCaptureInput:
    """A declared instance-frame projection, without choosing a Create occurrence."""

    instance: UseSite
    formal: ValueID


@dataclass(frozen=True, slots=True)
class DriveInputBinding:
    """A body formal's canonical source or instance capture recipe."""

    formal: ValueID
    source: UseSite | InstanceCaptureInput


@dataclass(frozen=True, slots=True)
class PublicationAccess:
    """An original access, canonical before Use and actual write result (if any)."""

    access: StateAccess
    before: UseSite
    after: StateVersionValue | None


@dataclass(frozen=True, slots=True)
class BodyPublication:
    """Declared source/owner/state links; no runtime or lifecycle proof is granted."""

    commit: BodyOutcomeCommit
    drive: BodyDrive
    source: BodyOutcomeSite
    instance: UseSite
    accesses: tuple[PublicationAccess, ...]


@dataclass(frozen=True, slots=True)
class CreatedClosePredicate:
    """Original predicate inputs and its actual bool-conditioned branch edges."""

    test: CreatedCloseTest
    instance: UseSite
    scheduler_request: UseSite
    effective_request: UseSite
    session: UseSite | None
    result: DataValue
    branch: Operation
    condition: UseSite
    true_successor: Successor
    false_successor: Successor
    accesses: tuple[PublicationAccess, ...]


@dataclass(frozen=True, slots=True)
class NoBodyPublication:
    """An explicit true-path finish, without a body outcome or new producer."""

    finish: NoBodyFinish
    predicate: CreatedClosePredicate
    instance: UseSite
    accesses: tuple[PublicationAccess, ...]


@dataclass(frozen=True, slots=True)
class LifecycleScope:
    """Original explicit declarations; their runtime applicability stays unknown."""

    declaration: DriverLifecycle
    interface: DriverInterface

    @property
    def applicability(self) -> ProofStatus:
        return ProofStatus.UNKNOWN

    @property
    def rule(self):
        return self.interface.rule


class LifecyclePosition(str, Enum):
    BEFORE = "BEFORE"
    AFTER = "AFTER"
    EDGE = "EDGE"


@dataclass(frozen=True, slots=True)
class LifecyclePoint:
    """Positioned conditional facts, not native/runtime or free/ready proof."""

    terminal: TerminalPointFacts
    session: SessionPointFacts
    scope: LifecycleScope
    operation: Operation
    position: LifecyclePosition
    successor_index: int | None

    def __post_init__(self):
        if type(self.scope) is not LifecycleScope:
            raise TypeError("lifecycle point needs its declared LifecycleScope")
        if not isinstance(self.operation, Operation):
            raise TypeError("lifecycle point needs its original Operation")
        if type(self.position) is not LifecyclePosition:
            raise TypeError("lifecycle position must be LifecyclePosition")
        if self.position is LifecyclePosition.EDGE:
            if (type(self.successor_index) is not int or self.successor_index < 0
                    or self.operation.terminator is None
                    or self.successor_index >= len(self.operation.terminator.successors)):
                raise ValueError("lifecycle edge index must identify a real successor")
        elif self.successor_index is not None:
            raise ValueError("before/after lifecycle points cannot have an edge index")

    @property
    def successor(self):
        return (self.operation.terminator.successors[self.successor_index]
                if self.position is LifecyclePosition.EDGE else None)


@dataclass(frozen=True, slots=True)
class SessionPublication:
    update: SessionUpdate
    request: UseSite
    body: UseSite
    state_inputs: tuple[UseSite, ...]
    accesses: tuple[PublicationAccess, ...]
    support: tuple[StateVersionValue, ...]
    normal_successor: CompletionSuccessor | None
    point: LifecyclePoint


@dataclass(frozen=True, slots=True)
class NoEntryPublication:
    """A conditional exact-edge source; not an observed body entry or permit."""

    declaration: ProtocolOperation
    instance: UseSite
    selected_edge: ControlEdgeReference | None
    terminal: ProtocolPort
    source: ProtocolPort
    state_sites: tuple[StateAddressSite, ...]


@dataclass(frozen=True, slots=True)
class TerminalReleasePublication:
    """Current must-fact with possible static source explanations.

    Multiple declarations on one source operation can describe different edges;
    their presence here does not mean they all occurred on the current path.
    """
    release: TerminalFrameRelease
    owner: UseSite
    accesses: tuple[PublicationAccess, ...]
    sources: tuple[BodyPublication | NoBodyPublication | NoEntryPublication, ...]
    point: LifecyclePoint


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
        # Reuse the validator's canonical CFG/dominators and derived cleanup
        # result rather than running a second dataflow algorithm for queries.
        from .validation import validate
        cleanup, resumption, lifecycle, prepared = [], [], [], []
        issues = validate(graph, _cleanup_facts=cleanup, _resumption_facts=resumption,
                          _lifecycle_facts=lifecycle, _prepared_index=prepared)
        if issues:
            raise ValueError("; ".join(f"{i.code} at {i.path}: {i.message}" for i in issues))
        if prepared:
            self.__dict__.update(prepared[0].__dict__)
            return
        self._prepare(graph, cleanup[0], resumption[0], lifecycle[0])

    @classmethod
    def _from_validated_core(cls, graph, cleanup, resumption, lifecycle):
        """Private validation-stage index over an already checked core.

        Only validation calls this, after canonical CFG/SSA, resumptions,
        lifecycles and provider/native checks. It avoids calling validation
        recursively when a connection obligation needs original call routes.
        This is preparation, not an alternative public graph validator.
        """
        index = cls.__new__(cls)
        index._prepare(graph, cleanup, resumption, lifecycle)
        return index

    def _prepare(self, graph, cleanup, resumption, lifecycle):
        self._cleanup_facts = cleanup
        self._resumption_facts = resumption
        self._lifecycle_facts = lifecycle
        self._bodies = {row.region: row for row in graph.resumable_bodies}
        self._frame_context_actions = {row.operation: row for rows in (
            graph.frame_context_initials, graph.frame_context_attaches,
            graph.frame_context_detaches) for row in rows}
        self._raw_driver_requests = {row.value: row for row in graph.raw_driver_requests}
        self._resumable_creates = {row.operation: row for row in graph.resumable_creates}
        self._async_request_creates = {row.operation: row for row in graph.async_request_creates}
        self._association_reads = {row.operation: row for row in graph.request_association_reads}
        self._driver_interfaces = {row.region: row for row in graph.driver_interfaces}
        self._final_body_gates = {row.operation: row for row in graph.final_body_gates}
        self._body_drives = {row.operation: row for row in graph.body_drives}
        self._driver_lifecycles = {row.region: row for row in graph.driver_lifecycles}
        self._lifecycle_scopes = {
            row.region: LifecycleScope(row, self._driver_interfaces[row.region])
            for row in graph.driver_lifecycles}
        self._body_outcome_commits = {row.operation: row for row in graph.body_outcome_commits}
        self._created_close_tests = {row.operation: row for row in graph.created_close_tests}
        self._no_body_finishes = {row.operation: row for row in graph.no_body_finishes}
        self._session_updates = {row.operation: row for row in graph.session_updates}
        self._terminal_frame_releases = {row.operation: row for row in graph.terminal_frame_releases}
        self._state_addresses = {row.site: row for row in graph.state_address_refinements}
        self._state_resource_uses = {(row.operation, row.requirement): row
                                     for row in graph.resource_uses}
        self.graph = graph
        self.values = {value.id: value for value in graph.values}
        self.locations = {location.id: location for location in graph.locations}
        self.regions = {region.id: region for region in graph.regions}
        self.operations = {operation.id: operation for operation in graph.operations}
        self._environments = {interface.region: interface for interface in graph.environments}
        self._function_entries = {layout.environment: layout for layout in graph.function_entries}
        self._pending_facts = derive_pending_facts(graph) if graph.control_scopes else {}
        self._control_ports = {port.id: port for port in graph.control_ports}
        self._control_scope = {block: scope for scope in graph.control_scopes for block in scope.blocks}
        self._scopes = {scope.id: scope for scope in graph.control_scopes}
        self._blocks = {b.id: r.id for r in graph.regions for b in r.blocks}
        self._block_records = {b.id: b for r in graph.regions for b in r.blocks}
        self._operation_blocks = {operation: block.id for region in graph.regions
                                  for block in region.blocks for operation in block.operations}
        self._context_domains = {row.region: row for row in graph.handled_context_domains}
        self._cleanups = {row.scope: row for row in graph.cleanup_interfaces}
        self._cleanup_actions = {row.operation: row for rows in (
            graph.cleanup_enters, graph.cleanup_resumes, graph.cleanup_replacements,
            graph.handled_context_reads) for row in rows}
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

    def literal_evaluation(self, site) -> dict:
        """Original production and optional content declaration, never identity proof."""
        from .literal_validation import literal_site
        from .literal_sources import CodeConstant, SourceExpression, UninterpretedConstant, UnlocatedLiteral
        resolved = literal_site(self.graph, site)
        row = next((row for row in self.graph.literal_evaluations if row.site == site), None)
        operation = resolved["operation"]
        conditions = []
        if row is None:
            conditions.append("content declaration is absent")
        else:
            if type(row.literal) is UninterpretedConstant:
                conditions.append("content and its type mapping are uninterpreted: " + row.literal.reason)
            else:
                conditions.append("exact payload representation is checked; runtime content applicability is unverified")
            if type(row.definition) is UnlocatedLiteral:
                conditions.append("definition source is unlocated: " + row.definition.reason)
            elif type(row.definition) is CodeConstant:
                conditions.append("code-record context and co_consts slot have not been replayed or verified")
            elif type(row.definition) is SourceExpression:
                conditions.append("source expression span is declared, not an AST classification or replay")
        conditions.extend((
            "equal content establishes neither object identity nor future immutability",
            "original effects, state, exceptions and producer remain unchanged",
        ))
        return {
            "site": site, "row": row, **resolved,
            "uses": tuple(self._uses[use.id] for use in operation.uses),
            "literal": None if row is None else row.literal,
            "definition": None if row is None else row.definition,
            "conditions": tuple(conditions),
            "source_runtime_verified": False, "value_identity_verified": False,
            "transformation_authorized": False,
        }

    def state_address(self, site: StateAddressSite) -> dict:
        """Project original state ports and optional address declarations.

        ``refinement=None`` explicitly means unknown address precision. Its
        empty effect tuple is not an empty-effect proof: the coarse state
        dependency and original operation remain present. INVOKE completion
        ports are returned separately without manufacturing an ``after``.

        ``operands`` retains unknown-owner inputs first, then selector inputs
        in path order, including repetitions. A reference owner is separately
        available as its original ``owner_use``.
        """
        if type(site) not in (ExistingAccess, InvokeStateOperand):
            raise TypeError("state_address requires an exact state address site")
        site.__post_init__()
        operation = self.operations[site.operation]
        completions = ()
        if type(site) is ExistingAccess:
            if (operation.terminator is not None
                    and operation.terminator.kind is TerminatorKind.INVOKE):
                raise ValueError("INVOKE state addresses require InvokeStateOperand")
            if site.index >= len(operation.accesses):
                raise KeyError(site)
            access = operation.accesses[site.index]
            before = self._uses[access.before]
            carrier = self.locations[access.location]
            after = None if access.after is None else self.values[access.after]
        else:
            if (operation.terminator is None
                    or operation.terminator.kind is not TerminatorKind.INVOKE
                    or site.state_use not in operation.invoke_arguments):
                raise ValueError("state address site must select an actual INVOKE state operand")
            before = self._uses[site.state_use]
            value = self.values[before.use.value]
            if before.operation != operation.id or not isinstance(value, StateVersionValue):
                raise ValueError("state address INVOKE operand must be an owned state Use")
            access, after = None, None
            carrier = self.locations[value.location]
            completions = tuple(
                {"successor_index": number, "successor": successor,
                 "formal": self.values[formal], "argument": actual}
                for number, successor in enumerate(operation.terminator.successors)
                for actual, formal in zip(successor.arguments,
                                          self._block_records[successor.block].arguments)
                if isinstance(self.values[formal], StateVersionValue)
                and self.values[formal].location == carrier.id)

        refinement = self._state_addresses.get(site)
        effects = []
        if refinement is not None:
            for number, effect in enumerate(refinement.effects):
                owner = effect.owner
                unknown_inputs = owner.operands if type(owner) is UnknownOwner else ()
                operands = (*unknown_inputs, *address_effect_uses(effect))
                effects.append({
                    "index": number, "effect": effect,
                    "owner_use": self._uses[owner.use] if type(owner) is ReferenceOwner else None,
                    "resource_use": self._state_resource_uses[(operation.id, owner.requirement)]
                        if type(owner) is ResourceOwner else None,
                    "operands": tuple(self._uses[use] for use in operands),
                })
        conditions = (
            "typed address paths do not interpret legacy Footprint coordinate units or establish geometric coverage",
            "DECLARED_COMPLETE describes declared addresses and modes, not native effects or source/runtime applicability",
        )
        if refinement is None:
            conditions += (
                "address precision is unknown without a refinement; the empty address tuple is not an empty-effect proof",
            )
        return {
            "site": refinement.site if refinement is not None else site,
            "refinement": refinement, "operation": operation, "carrier": carrier,
            "access": access, "before": before, "after": after,
            "completions": completions, "effects": tuple(effects),
            "coarse_dependencies_retained": True,
            "address_interpretation_verified": False, "conditions": conditions,
            "source_runtime_verified": False, "transformation_authorized": False,
        }

    def _driver_operation(self, operation_id, rows):
        if type(operation_id) is not OperationID:
            raise TypeError("driver operation query requires OperationID")
        if operation_id not in self.operations:
            raise KeyError(operation_id)
        return rows.get(operation_id)

    def raw_driver_request(self, value_id: ValueID):
        """Return a pack declaration; raw entry ports need not have one."""
        if type(value_id) is not ValueID:
            raise TypeError("raw_driver_request requires ValueID")
        if value_id not in self.values:
            raise KeyError(value_id)
        return self._raw_driver_requests.get(value_id)

    def raw_driver_operands(self, value_id: ValueID):
        """Original ordered reference Uses; None differs from a known zero arity."""
        row = self.raw_driver_request(value_id)
        return None if row is None else tuple(self._uses[use] for use in row.operands)

    def resumable_create(self, operation_id: OperationID):
        return self._driver_operation(operation_id, self._resumable_creates)

    def async_request_create(self, operation_id: OperationID):
        return self._driver_operation(operation_id, self._async_request_creates)

    def request_association_read(self, operation_id: OperationID):
        return self._driver_operation(operation_id, self._association_reads)

    def driver_interface(self, region_id: RegionID):
        """Static driver roles, without source or runtime authorization."""
        if type(region_id) is not RegionID:
            raise TypeError("driver_interface requires RegionID")
        if region_id not in self.regions:
            raise KeyError(region_id)
        return self._driver_interfaces.get(region_id)

    def final_body_gate(self, operation_id: OperationID):
        return self._driver_operation(operation_id, self._final_body_gates)

    def body_drive(self, operation_id: OperationID):
        return self._driver_operation(operation_id, self._body_drives)

    def driver_lifecycle(self, region_id: RegionID):
        """An explicit D2.1 publication scope, not completed lifecycle analysis."""
        if type(region_id) is not RegionID:
            raise TypeError("driver_lifecycle requires RegionID")
        if region_id not in self.regions:
            raise KeyError(region_id)
        return self._driver_lifecycles.get(region_id)

    def lifecycle_scope(self, region_id: RegionID):
        """An explicit conditional scope, never inferred from a D1 interface."""
        self.driver_lifecycle(region_id)
        return self._lifecycle_scopes.get(region_id)

    def body_outcome_commit(self, operation_id: OperationID):
        return self._driver_operation(operation_id, self._body_outcome_commits)

    def _state_access_views(self, operation_id):
        return tuple(PublicationAccess(
            access, self._uses[access.before],
            None if access.after is None else self.values[access.after])
            for access in self.operations[operation_id].accesses)

    def body_publication(self, operation_id: OperationID):
        """Resolve publication against original Uses/accesses and source-derived output.

        READ has no fabricated after-state; every write result retains its
        canonical producer. Source kind comes from the actual body outcome,
        without inferring native state, session completion or reference release.
        """
        commit = self.body_outcome_commit(operation_id)
        if commit is None:
            return None
        source = next(site for site in self.drive_outcomes(commit.outcome.drive)
                      if site.operation == commit.outcome.source)
        return BodyPublication(
            commit, self._body_drives[commit.outcome.drive], source,
            self._uses[commit.instance], self._state_access_views(commit.operation))

    def created_close_test(self, operation_id: OperationID):
        return self._driver_operation(operation_id, self._created_close_tests)

    def no_body_finish(self, operation_id: OperationID):
        return self._driver_operation(operation_id, self._no_body_finishes)

    def created_close_predicate(self, operation_id: OperationID):
        """Resolve real branch order, without evaluating the predicate or its guard."""
        test = self.created_close_test(operation_id)
        if test is None:
            return None
        block = self._block_records[self._operation_blocks[operation_id]]
        branch = self.operations[block.operations[-1]]
        return CreatedClosePredicate(
            test, self._uses[test.instance], self._uses[test.scheduler_request],
            self._uses[test.effective_request],
            None if test.session is None else self._uses[test.session],
            self.values[test.result], branch, self._uses[branch.terminator.condition],
            branch.terminator.successors[0], branch.terminator.successors[1],
            self._state_access_views(operation_id))

    def no_body_publication(self, operation_id: OperationID):
        """Resolve only a declared finish; predicate-only graphs have no such result."""
        finish = self.no_body_finish(operation_id)
        if finish is None:
            return None
        block = self._block_records[self._operation_blocks[finish.precondition.operation]]
        predicate = self.created_close_predicate(block.operations[-2])
        return NoBodyPublication(finish, predicate, self._uses[finish.instance],
                                 self._state_access_views(operation_id))

    def session_update(self, operation_id: OperationID):
        return self._driver_operation(operation_id, self._session_updates)

    def terminal_frame_release(self, operation_id: OperationID):
        return self._driver_operation(operation_id, self._terminal_frame_releases)

    def _lifecycle_point(self, operation_id, position):
        self._driver_operation(operation_id, {})
        region = self._blocks[self._operation_blocks[operation_id]]
        facts = self._lifecycle_facts.get(region)
        if facts is None:
            return None
        field = position.value.lower()
        return LifecyclePoint(getattr(facts.terminal, field)[operation_id],
                              getattr(facts.session, field)[operation_id],
                              self._lifecycle_scopes[region], self.operations[operation_id],
                              position, None)

    def lifecycle_before(self, operation_id: OperationID):
        return self._lifecycle_point(operation_id, LifecyclePosition.BEFORE)

    def lifecycle_after(self, operation_id: OperationID):
        return self._lifecycle_point(operation_id, LifecyclePosition.AFTER)

    def lifecycle_edge(self, operation_id: OperationID, successor_index: int):
        self._driver_operation(operation_id, {})
        if type(successor_index) is not int or successor_index < 0:
            raise ValueError("successor index must be an exact nonnegative integer")
        op = self.operations[operation_id]
        if op.terminator is None or successor_index >= len(op.terminator.successors):
            raise ValueError("successor index exceeds the real operation signature")
        region = self._blocks[self._operation_blocks[operation_id]]
        facts = self._lifecycle_facts.get(region)
        if facts is None:
            return None
        key = (operation_id, successor_index)
        return LifecyclePoint(facts.terminal.edges[key], facts.session.edges[key],
                              self._lifecycle_scopes[region], op,
                              LifecyclePosition.EDGE, successor_index)

    def session_publication(self, operation_id: OperationID):
        row = self.session_update(operation_id)
        if row is None:
            return None
        operation = self.operations[operation_id]
        normal = None
        if row.binding is LifecyclePostBinding.AFTER_OPERATION:
            point = self.lifecycle_after(operation_id)
            states = tuple(self._uses[access.before] for access in operation.accesses)
        else:
            number, normal = next((number, edge) for number, edge in enumerate(operation.terminator.successors)
                                  if edge.kind is ExitKind.NORMAL)
            point = self.lifecycle_edge(operation_id, number)
            states = tuple(self._uses[identity] for identity in operation.invoke_arguments
                           if isinstance(self.values[self._uses[identity].use.value], StateVersionValue))
        request, body = self._uses[row.request], self._uses[row.body]
        post = next(fact for fact in point.session.for_pair(request.use.value, body.use.value) if fact.post is row.post)
        return SessionPublication(row, request, body, states, self._state_access_views(operation_id),
                                  post.support, normal, point)

    def terminal_release_publication(self, operation_id: OperationID):
        row = self.terminal_frame_release(operation_id)
        if row is None:
            return None
        owner = self._uses[row.owner]
        point = self.lifecycle_before(operation_id)
        sources = []
        for identity in sorted(point.terminal.source_operations(owner.use.value), key=lambda item: item.wire):
            previous = self.body_publication(identity) or self.no_body_publication(identity)
            if previous is not None:
                sources.append(previous)
            else:
                sources.extend(self.no_entry_publications(identity))
        return TerminalReleasePublication(row, owner, self._state_access_views(operation_id), tuple(sources), point)

    def no_entry_publications(self, operation_id: OperationID):
        self._driver_operation(operation_id, {})
        from .protocol_flow import ProtocolFlow
        from .protocol_validation import no_entry_route
        from .protocols import ProtocolClause
        ctx = ProtocolFlow(self.graph)
        result = []
        for row in self.graph.protocol_operations:
            if (row.operation != operation_id or type(row.contract) is not NoEntryOutcome
                    or row.clause not in (ProtocolClause.INITIAL_THROW_DELIVERED,
                                          ProtocolClause.INITIAL_THROW_CONSTRUCTOR_FAILURE)):
                continue
            route = no_entry_route(ctx, row)
            if route['complete']:
                result.append(NoEntryPublication(row, self._uses[row.contract.instance_use],
                    row.contract.selected_edge, route['terminal'], route['source'], row.contract.state_sites))
        return tuple(result)

    def normal_result(self, operation_id: OperationID, port: NormalResultPort):
        """The original NORMAL landing value at an exact produced result slot."""
        self._driver_operation(operation_id, {})
        if type(port) is not NormalResultPort:
            raise TypeError("normal_result requires NormalResultPort")
        port.__post_init__()
        operation = self.operations[operation_id]
        if operation.terminator is None or operation.terminator.kind is not TerminatorKind.INVOKE:
            raise ValueError("normal_result requires INVOKE")
        edge = next((edge for edge in operation.terminator.successors if edge.kind is ExitKind.NORMAL), None)
        if edge is None:
            raise ValueError("normal_result requires an actual NORMAL completion")
        signature = next(signature for signature in operation.completions
                         if signature.kind is ExitKind.NORMAL)
        if port.index >= len(signature.types):
            raise IndexError(port.index)
        block = self._block_records[edge.block]
        position = next((index for index, actual in enumerate(edge.arguments)
                         if type(actual) is CompletionResult and actual.index == port.index), None)
        if position is None:
            raise ValueError("normal_result slot has no produced landing value")
        return self.values[block.arguments[position]]

    def protocol_obligations(self, scope=None, *, budget=4096):
        """Fixed supplied-model obligations; missing joins never remove clauses."""
        from .protocol_query import protocol_obligations
        return protocol_obligations(self.graph, scope, budget=budget, _index=self)

    def input_origins(self, operation_id, use_id, *, budget=4096):
        """Static original input routes, reusing this validated model index."""
        from scar.ir.execution.validity_budget import ValidityBudget
        from .input_origins import _input_origins
        return _input_origins(self, operation_id, use_id, accounting=ValidityBudget(budget))

    def paired_input_origins(self, raw, pack_operand, *, budget=4096):
        """Exact raw-pack operand routes; not a predicate-input binding."""
        from .input_origins import paired_input_origins
        return paired_input_origins(self, raw, pack_operand, budget=budget)

    def request_input_binding(self, raw, input, ordinal=0, *, budget=4096):
        """Joint original raw/operand/input routes under one static call context."""
        from .request_inputs import request_input_binding
        return request_input_binding(self, raw, input, ordinal, budget=budget)

    def creation_bindings(self, operation_id: OperationID):
        """Bound references from Create Uses; no dynamic instance is inferred."""
        row = self.resumable_create(operation_id)
        return None if row is None else tuple(
            DriverBinding(capture.formal, self._uses[capture.source]) for capture in row.captures)

    def drive_input_bindings(self, operation_id: OperationID):
        """Derive Start captures or Resume saved/current inputs, without copying actuals.

        A Start reference describes a projection of this Drive's actual
        instance frame. It does not select any static Create or runtime object.
        Resume saved sources remain the original Suspend Uses; only dynamic
        payload/state inputs are supplied by the Drive's canonical operands.
        """
        drive = self.body_drive(operation_id)
        if drive is None:
            return None
        region, start, edge = body_drive_target(self.graph, drive)
        states = {item.location: self._uses[item.source] for item in drive.state_inputs}
        if edge is None:
            bindings = []
            for formal in self._block_records[start].arguments:
                value = self.values[formal]
                if isinstance(value, StateVersionValue):
                    source = states[value.location]
                elif isinstance(value, ReferenceValue):
                    source = InstanceCaptureInput(self._uses[drive.instance], formal)
                else:
                    raise ValueError("Start input must be a state or captured reference")
                bindings.append(DriveInputBinding(formal, source))
            return tuple(bindings)
        dynamic = {item.slot: self._uses[item.source] for item in drive.resume_inputs}
        bindings = self.resumption_bindings(drive.target.suspend, drive.target.successor)
        result = []
        for binding, actual in zip(bindings, edge.arguments):
            if binding.saved is not None:
                source = binding.saved
            else:
                slot = edge.inputs[actual.resume_slot]
                source = (states[slot.location] if slot.kind is ResumeSlotKind.STATE
                          else dynamic[actual.resume_slot])
            result.append(DriveInputBinding(binding.formal, source))
        return tuple(result)

    def drive_outcomes(self, operation_id: OperationID):
        """Actual source-relative declarations in this drive's edge order.

        Values are the body's original public handoff/terminal Uses, never its
        private saved slots or invented driver-side producers. No occurrence,
        state postcondition, lifecycle commit or runtime choice is established.
        """
        if self.body_drive(operation_id) is None:
            return None
        term = self.operations[operation_id].terminator
        return tuple(BodyOutcomeSite(
            edge.source, self.operations[edge.source].terminator.kind,
            tuple(self._uses[use] for use in body_outcome_uses(self.operations[edge.source])))
            for edge in term.successors)

    def drive_bindings(self, operation_id: OperationID, source: OperationID):
        """Resolve landing formals to body result Uses or driver forwarding Uses."""
        drive = self.body_drive(operation_id)
        if type(source) is not OperationID:
            raise TypeError("drive_bindings source requires OperationID")
        if drive is None:
            return None
        if source not in self.operations:
            raise KeyError(source)
        term = self.operations[operation_id].terminator
        edge = next((edge for edge in term.successors if edge.source == source), None)
        if edge is None:
            raise ValueError("source is not an outcome of this BodyDrive")
        block = self._block_records[edge.block]
        uses = body_outcome_uses(self.operations[source])
        return tuple(DriverBinding(formal, self._uses[
            uses[actual.index] if type(actual) is BodyDriveResult else actual])
            for actual, formal in zip(edge.arguments, block.arguments))

    def resumable_body(self, region_id: RegionID):
        """A static body declaration, without runtime or driver evidence."""
        if type(region_id) is not RegionID:
            raise TypeError("resumable_body requires RegionID")
        if region_id not in self.regions:
            raise KeyError(region_id)
        return self._bodies.get(region_id)

    def frame_context_action(self, operation_id: OperationID):
        if type(operation_id) is not OperationID:
            raise TypeError("frame_context_action requires OperationID")
        if operation_id not in self.operations:
            raise KeyError(operation_id)
        return self._frame_context_actions.get(operation_id)

    def drive_context(self, block_id: BlockID):
        """Derived context at block entry, not an observed drive identity."""
        if type(block_id) is not BlockID:
            raise TypeError("drive_context requires BlockID")
        if block_id not in self._blocks:
            raise KeyError(block_id)
        return self._resumption_facts.contexts.get(block_id)

    def availability_roots(self, region_id: RegionID):
        if self.resumable_body(region_id) is None:
            return None
        return self._resumption_facts.roots[region_id]

    def resumption_bindings(self, operation_id: OperationID, case: int):
        """Project a case from canonical saved Uses and its input signature."""
        self.frame_context_action(operation_id)  # Exact identity/existence check.
        op = self.operations[operation_id]
        if not isinstance(op.terminator, SuspendTerminator):
            raise ValueError("resumption_bindings requires SUSPEND")
        if type(case) is not int:
            raise TypeError("case requires int")
        if case < 0 or case >= len(op.terminator.successors):
            raise IndexError(case)
        edge = op.terminator.successors[case]
        block = next(b for r in self.graph.regions for b in r.blocks if b.id == edge.block)
        return tuple(ResumptionBinding(formal, None, edge.inputs[actual.resume_slot])
                     if isinstance(actual, ResumeInput) else
                     ResumptionBinding(formal, self._uses[saved_actual_use(op, actual)], None)
                     for actual, formal in zip(edge.arguments, block.arguments))

    def suspension_handoff(self, operation_id: OperationID):
        self.frame_context_action(operation_id)
        term = self.operations[operation_id].terminator
        if not isinstance(term, SuspendTerminator):
            return None
        return SuspensionHandoff(self._uses[term.exported],
                                 tuple(self._uses[use] for use in term.handoff))

    def body_outcomes(self, region_id: RegionID, start: BlockID | None = None):
        """Derive first outcomes from a body entry or exact resume landing.

        This is a structural query over ordinary CFG successors. A SUSPEND is
        returned as the current drive's outcome; its temporal successors are
        considered only by a later query rooted at that landing. The result
        does not assert that any outcome executes at runtime.
        """
        if type(region_id) is not RegionID:
            raise TypeError("body_outcomes requires RegionID")
        region = self.regions.get(region_id)
        if region is None:
            raise KeyError(region_id)

        if start is not None:
            if type(start) is not BlockID:
                raise TypeError("body_outcomes start requires BlockID")
            owner = self._blocks.get(start)
            if owner is None:
                raise KeyError(start)
            if owner != region_id:
                raise ValueError("body_outcomes start belongs to another region")

        if region_id not in self._bodies:
            return None

        if start is None:
            start = region.entry
        roots = self._resumption_facts.roots[region_id]
        if start not in roots:
            raise ValueError("body_outcomes start must be the entry or a temporal landing")

        outcome_operations = first_body_outcome_operations(region, self.operations, start)
        sites = []
        for operation_id in outcome_operations:
            operation = self.operations[operation_id]
            terminator = operation.terminator
            values = body_outcome_uses(operation)
            sites.append(BodyOutcomeSite(
                operation_id, terminator.kind,
                tuple(self._uses[use_id] for use_id in values),
            ))
        return tuple(sites)

    def handled_context_domain(self, region_id: RegionID):
        """Return a declaration, not current runtime exception evidence."""
        if type(region_id) is not RegionID:
            raise TypeError("handled_context_domain requires RegionID")
        if region_id not in self.regions:
            raise KeyError(region_id)
        return self._context_domains.get(region_id)

    def cleanup_interface(self, scope_id: ControlScopeID):
        if type(scope_id) is not ControlScopeID:
            raise TypeError("cleanup_interface requires ControlScopeID")
        if scope_id not in self._scopes:
            raise KeyError(scope_id)
        return self._cleanups.get(scope_id)

    def cleanup_action(self, operation_id: OperationID):
        if type(operation_id) is not OperationID:
            raise TypeError("cleanup_action requires OperationID")
        if operation_id not in self.operations:
            raise KeyError(operation_id)
        return self._cleanup_actions.get(operation_id)

    def cleanup_stack(self, block_id: BlockID):
        """Derived block-entry stack; None means this protocol is undeclared."""
        if type(block_id) is not BlockID:
            raise TypeError("cleanup_stack requires BlockID")
        if block_id not in self._blocks:
            raise KeyError(block_id)
        return self._cleanup_facts.stacks.get(block_id)

    def cleanup_pending_copies(self, scope_id: ControlScopeID):
        if self.cleanup_interface(scope_id) is None:
            return None
        return tuple(sorted(self._cleanup_facts.forward[scope_id].pending, key=lambda v: v.wire))

    def cleanup_context_copies(self, scope_id: ControlScopeID):
        if self.cleanup_interface(scope_id) is None:
            return None
        return tuple(sorted(self._cleanup_facts.forward[scope_id].context, key=lambda v: v.wire))

    def cleanup_route_steps(self, operation_id: OperationID) -> tuple[CleanupRouteStep, ...]:
        self.cleanup_action(operation_id)  # Check canonical identity/existence.
        return self._cleanup_facts.routes.get(operation_id, ())

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
        core validation requires control sites for old graphs. A C1 cleanup can
        intercept a declared target forever or replace it; no site then returns
        an empty tuple, without inventing a terminal or producer.
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


__all__ = ["ProgramIndex", "UseSite", "BodyOutcomeSite", "DriverBinding", "DriveInputBinding",
           "InstanceCaptureInput", "PublicationAccess", "BodyPublication",
           "CreatedClosePredicate", "NoBodyPublication",
           "LifecycleScope", "LifecyclePosition", "LifecyclePoint", "SessionPublication", "TerminalReleasePublication",
           "EnvironmentArgument", "EnvironmentCall",
           "EnvironmentBindingStatus", "FunctionArgument", "CleanupRouteKind", "CleanupRouteStep",
           "ResumptionBinding", "SuspensionHandoff"]
