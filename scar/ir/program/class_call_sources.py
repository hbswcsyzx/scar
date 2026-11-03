"""Original class-statement products reaching a source CALL's callable Use.

The final decorator result is a source occurrence, not proof of a runtime
class, metaclass, selected call implementation or instance allocation.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from scar.ir.program.class_construction import ClassConstruction
from scar.ir.program.dependencies import (
    DependencyCondition as Condition, DependencyEdge as Edge,
    DependencyEvidence as Evidence, DependencyKind as K, DependencyMeaning as M,
    DependencyPoint as Point,
)
from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.source_references import SourceArtifactLocator


@dataclass(frozen=True, slots=True)
class ContextualClassStatementSource:
    call: Point
    callable: Point
    source: Point
    construction: ClassConstruction
    locator: SourceArtifactLocator
    path: tuple[Edge, ...]
    evidence: tuple[Evidence, ...]
    conditions: tuple[Condition, ...]
    runtime_class_verified: bool = False

    def __post_init__(self):
        for value, kind in ((self.call, Point), (self.callable, Point),
                (self.source, Point), (self.construction, ClassConstruction),
                (self.locator, SourceArtifactLocator)):
            if type(value) is not kind:
                raise TypeError('class statement source requires original ' + kind.__name__)
            value.__post_init__()
        if (type(self.call.node) is not OperationID or type(self.callable.node) is not UseID
                or type(self.source.node) is not ValueID
                or self.call.namespace != self.callable.namespace
                or self.call.context != self.callable.context
                or self.source.node != self.construction.result):
            raise ValueError('class source must retain the actual CALL, callable Use and final construction result')
        pointer = self.locator.pointer.rsplit('/', 1)
        if (len(pointer) != 2 or pointer[0] not in
                ('#/module/class_constructions', '#/language/class_constructions')
                or not pointer[1].isdigit()
                or replace(self.locator, pointer='#/graph') != self.source.namespace.graph):
            raise ValueError('class source locator must select its original construction table')
        for rows, kind in ((self.path, Edge), (self.evidence, Evidence), (self.conditions, Condition)):
            if type(rows) is not tuple or any(type(row) is not kind for row in rows):
                raise TypeError('class source evidence and paths must be immutable typed records')
        if (not self.path or not self.evidence or self.path[0].source != self.source
                or self.path[-1].target != self.callable):
            raise ValueError('class source needs a continuous final-result to callable path')
        visited = {self.source}
        cursor = self.source
        for edge in self.path:
            if (edge.source != cursor or edge.target in visited
                    or any(type(point.node) not in (UseID, ValueID)
                           for point in (edge.source, edge.target))):
                raise ValueError('class source path is disconnected, cyclic or not a reference-port path')
            if edge.kind is K.VALUE_USE:
                valid = (edge.meaning is M.VALUE and type(edge.source.node) is ValueID
                    and type(edge.target.node) is UseID
                    and edge.source.namespace == edge.target.namespace
                    and edge.source.context == edge.target.context)
            elif edge.kind in (K.BINDING_PAYLOAD, K.BINDING_READ):
                valid = edge.meaning is M.BINDING
            elif edge.kind is K.BLOCK_ARGUMENT:
                valid = edge.meaning in (M.VALUE, M.REFERENCE)
            else:
                valid = (edge.kind in (K.ARGUMENT, K.COMPLETION, K.ENVIRONMENT, K.STATE_VALUE)
                    and edge.meaning is M.REFERENCE)
            if not valid:
                raise ValueError('class source cannot treat computation dependence as callable identity')
            if any(condition not in self.conditions for condition in edge.conditions):
                raise ValueError('class source dropped an original path condition')
            if any(item not in self.evidence for item in edge.evidence):
                raise ValueError('class source dropped original reference-path evidence')
            cursor = edge.target
            visited.add(cursor)
        for ports in (self.construction.builder_call,
                *(row.call for row in self.construction.decorators)):
            subject = Point(self.source.namespace, ports.operation, self.source.context)
            if not any(condition.domain == 'canonical' and condition.name == 'SUCCESSOR_SELECTED'
                    and condition.subject == subject and condition.index is not None
                    and not condition.operands for condition in self.conditions):
                raise ValueError('class source dropped an original builder/decorator NORMAL selection')
        if type(self.runtime_class_verified) is not bool or self.runtime_class_verified:
            raise ValueError('a class statement source cannot assert a runtime class')


__all__ = ['ContextualClassStatementSource']
