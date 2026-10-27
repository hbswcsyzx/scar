"""Wire-only rich declarations, not a claimed valid physical execution."""
from dataclasses import replace
from pathlib import Path

from scar.ir.execution.codec import loads
from scar.ir.execution.common import Unresolved
from scar.ir.execution.coordinates import AccessRef, OccurrencePhase, OccurrencePoint, UseRef
from scar.ir.execution.ids import (
    ContributionSupportID, EstablishedProductionID, OrderAssociationID, TargetLifetimeEventID,
    QueuePrefixID, ResourceInstanceID,
)
from scar.ir.execution.order import EventSignal, PrefixEnd, WorkEnd, WorkStart
from scar.ir.execution.production import BytePrefixWrite, SourceEdgeRef
from scar.ir.execution.resources import AllocationTarget
from scar.ir.execution.validity import (
    CompletedVisibility, ContributionSupport, EndpointDomain, EstablishedProduction,
    HostDomain, LifetimeEventKind, OrderAssociation, OrderedVisibility, QueueDomain,
    TargetLifetimeEvent,
)


def validity_record_model():
    model = loads((Path(__file__).parent / 'execution_v5_frozen.json').read_text())
    fact = model.writes[0].source
    gap = Unresolved('wire fixture has no native correspondence', model.activations[0].entry)
    occurrence = model.operations[0].id
    before = OccurrencePoint(occurrence, OccurrencePhase.BEFORE)
    after = OccurrencePoint(occurrence, OccurrencePhase.AFTER)
    raw = model.writes[0].stage
    edge = SourceEdgeRef(raw.source, 'production.wire.source-edge')
    region = model.writes[0].placement.selector
    target = next(row.target for row in model.source_bridges if type(row.target) is AllocationTarget)
    established = EstablishedProduction(EstablishedProductionID('wire.established'), model.writes[1].id,
        after, region, model.values[0].id, BytePrefixWrite(), fact)
    unknown = EstablishedProduction(EstablishedProductionID('wire.established.unknown'), model.writes[2].id,
        model.activations[0].entry, gap, gap, gap, fact)
    retired = TargetLifetimeEvent(TargetLifetimeEventID('wire.retired'), target, LifetimeEventKind.RETIRED,
        WorkEnd(model.submissions[0].id), raw, AccessRef(occurrence, 0), fact, fact)
    live = TargetLifetimeEvent(TargetLifetimeEventID('wire.live'), target, LifetimeEventKind.LIVE,
        gap, edge, None, fact, fact)
    orders = (OrderAssociation(OrderAssociationID('wire.order'), before, after,
        UseRef(model.uses[0].operation, model.uses[0].use), fact, fact),
        OrderAssociation(OrderAssociationID('wire.order.unknown'),
            WorkStart(model.submissions[0].id), PrefixEnd(QueuePrefixID('wire.prefix')), gap, fact, fact))
    domains = (HostDomain(model.threads[0].id), QueueDomain(ResourceInstanceID('wire.queue')), EndpointDomain(target), gap)
    points = (after, WorkEnd(model.submissions[0].id), PrefixEnd(QueuePrefixID('wire.prefix')), gap.point)
    supports = tuple(ContributionSupport(ContributionSupportID(f'wire.support.{index}'),
        model.content_reads[0].id, model.writes[0].id, model.produced[0].id,
        CompletedVisibility(point, raw if index == 0 else edge, domain, fact), fact)
        for index, (point, domain) in enumerate(zip(points, domains)))
    supports += (ContributionSupport(ContributionSupportID('wire.support.ordered'),
        model.content_reads[0].id, model.writes[0].id, None, OrderedVisibility(fact), fact),
        ContributionSupport(ContributionSupportID('wire.support.unknown'),
            model.content_reads[0].id, model.writes[0].id, gap, gap, fact),
        ContributionSupport(ContributionSupportID('wire.support.host'),
            model.content_reads[0].id, model.writes[1].id, established.id,
            CompletedVisibility(after, AccessRef(occurrence, 0), domains[0], fact), fact))
    return replace(model, established_productions=(established, unknown),
        target_lifetime_events=(retired, live), order_associations=orders, contribution_supports=supports)
