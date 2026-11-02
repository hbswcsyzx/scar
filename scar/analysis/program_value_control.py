"""Typed control witnesses consumed by the existing value worklist.

These records reference the shared graph's original endpoints and edges.
They are not another graph or a control solver. A required selection means
an entry path passed that edge, possibly in an earlier loop iteration.
"""
from __future__ import annotations

from dataclasses import dataclass

from scar.ir.program.dependencies import (DependencyCondition as Condition,
    DependencyEdge,DependencyEvidence as Evidence,DependencyFrontier as Frontier,
    DependencyKind as K,DependencyPoint as Point,DependencyStrength as Strength)
from scar.ir.program.ids import BlockID,OperationID,RegionID


@dataclass(frozen=True,slots=True)
class ControlEntryScope:
    region: Point
    entry: Point
    evidence: Evidence

    def __post_init__(self):
        if (type(self.region)is not Point or type(self.region.node)is not RegionID
                or type(self.entry)is not Point or type(self.entry.node)is not BlockID
                or self.region.namespace!=self.entry.namespace or self.region.context!=self.entry.context
                or self.region.context is None or type(self.evidence)is not Evidence):
            raise TypeError('entry scope requires original same-context region/entry and evidence')


@dataclass(frozen=True,slots=True)
class ControlNecessity:
    choice: Condition
    scope: ControlEntryScope
    chain: tuple[DependencyEdge,...]
    evidence: Evidence

    def __post_init__(self):
        if (type(self.choice)is not Condition or self.choice.domain!='canonical'
                or self.choice.name!='SUCCESSOR_SELECTED' or self.choice.subject is None
                or self.choice.operands!=()or type(self.choice.subject.node)is not OperationID or self.choice.index is None
                or type(self.scope)is not ControlEntryScope or type(self.chain)is not tuple or not self.chain
                or any(type(e)is not DependencyEdge or e.strength is not Strength.EXACT for e in self.chain)
                or self.chain[0].source!=self.choice.subject or type(self.evidence)is not Evidence):
            raise TypeError('control necessity needs an original exact entry-control/ownership chain')
        for edge in self.chain:
            if (edge.kind not in(K.CONTROL,K.CONTAINS,K.RESULT,K.STATE_OUTPUT)
                    or any(p.namespace!=self.scope.region.namespace or p.context!=self.scope.region.context
                        for p in(edge.source,edge.target))):
                raise ValueError('control chain changed its original scope or relation kind')
            if any(c.operands!=()and(c.domain,c.name)in{
                    ('canonical','SUCCESSOR_SELECTED'),('canonical','COMPLETION_SLOT'),
                    ('canonical.binding','READ_NORMAL_REQUIRES_BOUND'),
                    ('control.analysis','ORIGINAL_EDGE_REQUIRED_FOR_ENTRY_REACHABILITY')}
                    for c in edge.conditions):
                raise ValueError('a known unary control prerequisite cannot accept additional operands')
        if any(a.target!=b.source for a,b in zip(self.chain,self.chain[1:])):
            raise ValueError('control necessity chain is disconnected')


@dataclass(frozen=True,slots=True)
class OccurrenceField:
    requirements: tuple[ControlNecessity,...] = ()
    unknown_paths: tuple[Frontier,...] = ()
    applicable: bool = False

    def __post_init__(self):
        if (type(self.requirements)is not tuple or any(type(r)is not ControlNecessity for r in self.requirements)
                or type(self.unknown_paths)is not tuple or any(type(f)is not Frontier for f in self.unknown_paths)
                or type(self.applicable)is not bool):
            raise TypeError('occurrence facts need typed necessary paths and explicit open scopes')


@dataclass(frozen=True,slots=True)
class TypedRouteRefutation:
    route: DependencyEdge
    source_evidence: tuple[Evidence,...]
    evidence: Evidence

    def __post_init__(self):
        if (type(self.route)is not DependencyEdge or self.route.strength is not Strength.EXACT
                or type(self.source_evidence)is not tuple or not self.source_evidence
                or any(type(e)is not Evidence for e in self.source_evidence)
                or type(self.evidence)is not Evidence):
            raise TypeError('route refutation requires an exact original edge and source infeasibility evidence')
