"""Conditional entry-time namespace projections over original program ports.

The records do not add nodes, CALLs, worlds, imports or runtime identities.
Namespace-reference provenance and namespace contents at function entry are
different relations.  An initializer snapshot is only a possible entry source
under the explicit temporal, owner and intervening-effect predicates below.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .dependencies import (DependencyCondition, DependencyEdge, DependencyEvidence,
    DependencyKind, DependencyMeaning, DependencyPoint, DependencyStrength,
    GraphNamespace)
from .ids import OperationID, UseID, ValueID
from .static_calls import (NamespacePathStart, StaticNamespacePathSegment,
    StaticQualifiedNamespaceRead, StaticQualifiedNamespaceWrite)
from .structured import ControlEdgeReference


class EntryNamespaceOwnerMode(str, Enum):
    GLOBALS_ONLY = "GLOBALS_ONLY"
    CONDITIONAL_L_G_ALIAS = "CONDITIONAL_L_G_ALIAS"


@dataclass(frozen=True, slots=True)
class EntryNamespaceProjection:
    owner_path: tuple[DependencyEdge, ...]
    read: StaticQualifiedNamespaceRead
    read_slot: int
    entry_world: DependencyPoint
    entry_path: StaticNamespacePathSegment
    module_locals: DependencyPoint
    snapshot_write: StaticQualifiedNamespaceWrite
    snapshot_operation: DependencyPoint
    snapshot_world: DependencyPoint
    snapshot_path: tuple[ControlEdgeReference, ...]
    snapshot_operations: tuple[OperationID, ...]
    snapshot_equivalent_owners: tuple[ValueID, ...]
    key: str
    owner_mode: EntryNamespaceOwnerMode
    conditions: tuple[DependencyCondition, ...]
    evidence: tuple[DependencyEvidence, ...]
    initialization_contract: bool = False

    def __post_init__(self):
        if (type(self.owner_path) is not tuple or not self.owner_path
                or any(type(edge) is not DependencyEdge for edge in self.owner_path)):
            raise TypeError("entry projection needs an original nonempty reference path")
        for edge in self.owner_path:
            edge.__post_init__()
            if edge.kind is DependencyKind.VALUE_USE and edge.meaning is DependencyMeaning.VALUE:
                if (type(edge.source.node) is not ValueID or type(edge.target.node) is not UseID
                        or edge.source.namespace != edge.target.namespace
                        or edge.source.context != edge.target.context):
                    raise ValueError("owner VALUE_USE must retain the same original reference namespace/context")
            elif (edge.kind not in (DependencyKind.ENVIRONMENT, DependencyKind.ARGUMENT)
                    or edge.meaning is not DependencyMeaning.REFERENCE):
                raise ValueError("an arbitrary operand or state transfer cannot establish a namespace owner")
        if any(left.target != right.source for left, right in zip(self.owner_path, self.owner_path[1:])):
            raise ValueError("entry namespace reference path must join exact original points/contexts")
        points = (self.owner_path[0].source, *(edge.target for edge in self.owner_path))
        if len(set(points)) != len(points):
            raise ValueError("a cyclic owner path cannot establish its own module source")
        for value, kind in ((self.read, StaticQualifiedNamespaceRead),
                (self.entry_path, StaticNamespacePathSegment),
                (self.snapshot_write, StaticQualifiedNamespaceWrite)):
            if type(value) is not kind:
                raise TypeError("entry namespace projection needs " + kind.__name__)
            value.__post_init__()
        for point in (self.entry_world, self.module_locals, self.snapshot_operation, self.snapshot_world):
            if type(point) is not DependencyPoint:
                raise TypeError("entry projection fields must reference original qualified points")
            point.__post_init__()
        if (type(self.read_slot) is not int or self.read_slot < 0
                or self.read_slot != len(self.read.prior_lookup_owners)):
            raise ValueError("entry projection must preserve its original lookup-owner slot")
        entry, module = self.owner_path[-1].target, self.owner_path[0].source
        read_namespace = GraphNamespace.from_source(self.read.body)
        module_namespace = GraphNamespace.from_source(self.snapshot_write.body)
        if (entry.namespace != read_namespace or type(entry.node) is not ValueID
                or module.namespace != module_namespace or type(module.node) is not ValueID
                or self.entry_world.namespace != read_namespace
                or self.entry_world.context != entry.context or type(self.entry_world.node) is not ValueID
                or self.entry_path.body != self.read.body
                or self.entry_path.start_kind is not NamespacePathStart.ENTRY
                or self.entry_path.start_operation is not None
                or self.entry_path.start_owner != entry.node
                or self.entry_path.query_owner != entry.node
                or self.entry_path.query_operation != self.read.operation
                or self.entry_path.query_world != self.read.world):
            raise ValueError("entry projection changed original entry/read/owner endpoints")
        if (self.module_locals.namespace != module_namespace
                or self.module_locals.context != module.context or type(self.module_locals.node) is not ValueID
                or self.snapshot_operation.namespace != module_namespace
                or self.snapshot_world.namespace != module_namespace
                or self.snapshot_operation.context != module.context
                or self.snapshot_world.context != module.context
                or type(self.snapshot_operation.node) is not OperationID
                or type(self.snapshot_world.node) is not UseID):
            raise ValueError("initializer snapshot must retain its own original module points/context")
        for rows, kind in ((self.snapshot_path, ControlEdgeReference),
                (self.snapshot_operations, OperationID), (self.snapshot_equivalent_owners, ValueID),
                (self.conditions, DependencyCondition), (self.evidence, DependencyEvidence)):
            if type(rows) is not tuple or any(type(item) is not kind for item in rows):
                raise TypeError("entry projection requires immutable typed witnesses")
        if (not self.evidence or type(self.key) is not str or self.entry_path.key != self.key
                or type(self.owner_mode) is not EntryNamespaceOwnerMode
                or type(self.initialization_contract) is not bool):
            raise ValueError("entry namespace snapshot needs key, owner interpretation and evidence")
        if (not self.snapshot_equivalent_owners
                or len(set(self.snapshot_equivalent_owners)) != len(self.snapshot_equivalent_owners)
                or module.node not in self.snapshot_equivalent_owners):
            raise ValueError("initializer writer selection must retain its exact conditional owner domain")
        expected = ((module.node,) if self.owner_mode is EntryNamespaceOwnerMode.GLOBALS_ONLY
                    else tuple(dict.fromkeys((self.module_locals.node, module.node))))
        if self.snapshot_equivalent_owners != expected:
            raise ValueError("initializer alias interpretation changed its exact L/G owner domain")
        required = {"SOURCE_INITIALIZER_COMPLETES_NORMALLY", "SOURCE_SNAPSHOT_PRECEDES_FUNCTION_ENTRY",
                    "MODULE_BINDING_PRESERVED_UNTIL_FUNCTION_ENTRY", "ENTRY_NAMESPACE_OWNER_PATH_SELECTED"}
        if self.owner_mode is EntryNamespaceOwnerMode.CONDITIONAL_L_G_ALIAS:
            required.add("MODULE_INITIALIZER_LOCALS_ALIASES_GLOBALS")
        if self.initialization_contract:
            required.add("SOURCE_IMPORT_INITIALIZER_USES_MODULE_DICT")
        supplied = {condition.name for condition in self.conditions
                    if condition.domain == "scar.entry-namespace" and condition.operands}
        if not required <= supplied:
            raise ValueError("entry projection cannot omit its temporal, owner or effect predicates")
        inherited = {condition for edge in self.owner_path for condition in edge.conditions}
        if not inherited <= set(self.conditions):
            raise ValueError("entry projection cannot drop the original reference-path conditions")

    @property
    def source(self):
        return DependencyPoint(self.snapshot_operation.namespace,
            self.snapshot_write.assigned_reference, self.snapshot_operation.context)

    @property
    def target(self):
        return DependencyPoint(self.entry_world.namespace, self.read.result, self.entry_world.context)

    @property
    def strength(self):
        return DependencyStrength.MAY

    def dependency_edge(self):
        return DependencyEdge(self.source, self.target, DependencyKind.STATE_VALUE,
            DependencyMeaning.REFERENCE, self.evidence, self.conditions, DependencyStrength.MAY)


__all__ = ["EntryNamespaceOwnerMode", "EntryNamespaceProjection"]
