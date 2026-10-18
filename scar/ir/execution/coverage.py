"""Budgeted byte coverage of declarations in exact, caller-supplied ValueGraphs.

This module compares storage selectors, not values, production, lifetimes or
readiness. No URI is opened. A COVERED result cannot authorize transformation.
``None`` intervals mean unexpanded/unknown; ``()`` is the known empty byte set.

The shared geometry budget charges visited references, dimension/word checks,
enumerated points, and interval sorting/merging/comparison. Strict input-shape
checks and external snapshot validation/canonical hashing are separate costs.
Every distinct artifact is verified once per call; mutable graphs are never
trusted through a persistent cache. Unvisited offers are not catalog-verified.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import sys

from scar.ir.program.providers import ProviderArtifact
from scar.ir.provenance import _byte_bounds, _byte_intervals, _width
from scar.ir.v2.ids import StorageRegionID
from scar.ir.v2.values import ValueGraph
from .resources import _exact, _id, _index, _record
from .snapshot import ExternalSnapshots, SnapshotError


@dataclass(frozen=True, slots=True)
class RegionRef:
    artifact: ProviderArtifact
    region: StorageRegionID

    def __post_init__(self):
        _record(self.artifact, ProviderArtifact, "region artifact")
        _id(self.region, StorageRegionID, "storage region ID")


class CoverageStatus(str, Enum):
    COVERED = "COVERED"
    INCOMPLETE = "INCOMPLETE"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class CoverageGap:
    code: str
    region: RegionRef | None
    reason: str

    def __post_init__(self):
        for name in ("code", "reason"):
            _exact(getattr(self, name), str, "coverage gap " + name)
            if not getattr(self, name):
                raise ValueError("coverage gap " + name + " must be nonempty")
        if self.region is not None:
            _record(self.region, RegionRef, "coverage gap region")


def _refs(value, name):
    _exact(value, tuple, name)
    for ref in value:
        _record(ref, RegionRef, name + " item")


def _intervals(value, name):
    if value is None:
        return
    _exact(value, tuple, name)
    previous = None
    for interval in value:
        _exact(interval, tuple, name + " interval")
        if len(interval) != 2:
            raise ValueError(name + " intervals must have two endpoints")
        start, stop = interval
        _index(start, name + " start")
        _index(stop, name + " stop")
        if stop <= start or (previous is not None and start <= previous):
            raise ValueError(name + " must contain sorted, disjoint, merged nonempty intervals")
        previous = stop


@dataclass(frozen=True, slots=True)
class StorageCoverageResult:
    status: CoverageStatus
    required: RegionRef
    offered: tuple[RegionRef, ...]
    used: tuple[RegionRef, ...]
    covered_intervals: tuple[tuple[int, int], ...] | None
    missing_intervals: tuple[tuple[int, int], ...] | None
    budget_used: int
    gaps: tuple[CoverageGap, ...]

    def __post_init__(self):
        _exact(self.status, CoverageStatus, "coverage status")
        _record(self.required, RegionRef, "required region")
        _refs(self.offered, "offered regions")
        _refs(self.used, "used regions")
        _intervals(self.covered_intervals, "covered intervals")
        _intervals(self.missing_intervals, "missing intervals")
        _index(self.budget_used, "geometry budget used")
        _exact(self.gaps, tuple, "coverage gaps")
        for gap in self.gaps:
            _record(gap, CoverageGap, "coverage gap")

    @property
    def source_runtime_verified(self):
        return False

    @property
    def transformation_authorized(self):
        return False


def _artifact_key(artifact):
    return artifact.sha256, artifact.schema, artifact.size_bytes


def _region_key(ref):
    return _artifact_key(ref.artifact), ref.region


class _ValueCatalog:
    """Per-query exact snapshot resolver shared by MatRef and region queries."""

    def __init__(self, value_graphs):
        # Retain the existing public geometry input-type contract while the
        # shared resolver exposes coded SnapshotError to graph validation.
        _exact(value_graphs, dict, "ValueGraph catalog")
        try:
            self._snapshots = ExternalSnapshots(value_graphs=value_graphs)
        except SnapshotError as error:
            if error.code == "catalog_type":
                raise TypeError(str(error)) from error
            raise

    def graph(self, artifact):
        return self._snapshots.graph(artifact, ValueGraph)

    @classmethod
    def from_snapshots(cls, snapshots):
        """Reuse one content-query resolver without opening a second catalog."""
        _exact(snapshots, ExternalSnapshots, "external snapshot resolver")
        result = cls.__new__(cls)
        result._snapshots = snapshots
        return result


class _Budget:
    def __init__(self, limit):
        self.limit, self.used = limit, 0

    def take(self, amount=1):
        if amount > self.limit - self.used:
            return False
        self.used += amount
        return True

    @property
    def remaining(self):
        return self.limit - self.used


class _Coverage:
    def __init__(self, required, offered, catalog, budget):
        self.required, self.offered, self.catalog = required, offered, catalog
        self.budget = _Budget(budget)
        self.descriptions, self.gaps = {}, []

    def gap(self, code, ref, reason):
        self.gaps.append(CoverageGap(code, ref, reason))

    def take(self, amount, ref):
        if self.budget.take(amount):
            return True
        self.gap("geometry_budget_exhausted", ref,
                 "shared geometry budget cannot complete this comparison")
        return False

    def result(self, status, *, used=(), covered=None, missing=None):
        return StorageCoverageResult(status, self.required, self.offered, used,
                                     covered, missing, self.budget.used, tuple(self.gaps))

    def resolve(self, ref):
        graph = self.catalog.graph(ref.artifact)
        if graph is None:
            self.gap("external_graph_unavailable", ref,
                     "exact ValueGraph was not supplied; no URI is opened")
            return None
        row = graph.regions.get(ref.region)
        if row is None:
            raise ValueError("storage region is absent from the exact external ValueGraph")
        allocation = graph.allocations.get(row.allocation)
        if allocation is None:
            raise ValueError("storage region allocation is absent from the exact external ValueGraph")
        return row, allocation

    def describe(self, ref, resolved):
        """Return (row, dense interval or None); no strided-point enumeration."""
        key = _region_key(ref)
        if key in self.descriptions:
            return self.descriptions[key]
        row, allocation = resolved
        # Bit-width charging precedes address multiplication and sorting. Graph
        # validation is a separate input/snapshot cost, not a geometry shortcut.
        numbers = (row.offset, *row.shape, *row.strides)
        cost = 1 + 2 * len(row.shape)
        for number in numbers:
            cost += max(1, (abs(number).bit_length() + 63) // 64)
        if allocation.nbytes is not None:
            cost += max(1, allocation.nbytes.bit_length() // 64 + 1)
        if not self.take(cost, ref):
            return None
        if row.layout != "strided":
            self.gap("layout_unresolved", ref, "only declared strided byte geometry is supported")
            return None
        # An empty strided selector addresses no bytes, even with zero strides;
        # never pass it to helpers that replace zero-stride dimensions by one.
        if 0 in row.shape:
            result = row, ()
            self.descriptions[key] = result
            return result
        if _width(row) is None:
            self.gap("dtype_width_unresolved", ref, "dtype has no known element byte width")
            return None
        # A dense address set can overlap itself. Start with one element; each
        # dimension extends a continuous span iff its absolute stride <= span.
        rank = len(row.shape)
        if not self.take(rank * max(1, rank.bit_length()) + rank + 1, ref):
            return None
        dimensions = sorted((abs(stride), size) for size, stride in zip(row.shape, row.strides)
                            if size > 1 and stride != 0)
        span, dense = 1, True
        for stride, size in dimensions:
            if stride > span:
                dense = False
                break
            span += (size - 1) * stride
        bounds = _byte_bounds(row) if dense else None
        result = row, (bounds,) if bounds is not None else None
        self.descriptions[key] = result
        return result

    def expand(self, ref, description):
        row, dense = description
        if dense is not None:
            if not self.take(len(dense), ref):
                return None
            return dense
        # Cap cardinality *before* len(range(size)) inside the legacy helper.
        # Both multiplication and range length must stay below the shared budget.
        points = 1
        for size, stride in zip(row.shape, row.strides):
            effective = size if stride else 1
            if (effective > sys.maxsize or effective > self.budget.remaining
                    or points > self.budget.remaining // effective):
                self.gap("geometry_budget_exhausted", ref,
                         "strided point cardinality exceeds the shared geometry budget")
                return None
            points *= effective
        cost = points * (2 + len(row.shape) + points.bit_length())
        if not self.take(cost, ref):
            return None
        # Guards above establish nonempty strided layout, known width and a
        # bounded, platform-representable range length. Reuse its exact union.
        return tuple(_byte_intervals(row, budget=points))

    def run(self):
        if not self.take(1, self.required):
            return self.result(CoverageStatus.UNRESOLVED)
        resolved = self.resolve(self.required)
        if resolved is None:
            return self.result(CoverageStatus.UNRESOLVED)
        required_description = self.describe(self.required, resolved)
        if required_description is None:
            return self.result(CoverageStatus.UNRESOLVED)
        if required_description[1] == ():
            return self.result(CoverageStatus.COVERED, covered=(), missing=())

        coordinate = _artifact_key(self.required.artifact), resolved[0].allocation
        providers, seen, unresolved = [], set(), False
        # Describe before point enumeration so an identical large strided
        # selector can prove reflexive inclusion without expanding its holes.
        for ref in self.offered:
            if not self.take(1, ref):
                unresolved = True
                break
            offered = self.resolve(ref)
            if offered is None:
                unresolved = True
                continue
            if (_artifact_key(ref.artifact), offered[0].allocation) != coordinate:
                self.gap("allocation_correspondence_unresolved", ref,
                         "different scoped allocation coordinates have no declared byte mapping")
                unresolved = True
                continue
            if _region_key(ref) == _region_key(self.required):
                dense = required_description[1]
                return self.result(CoverageStatus.COVERED, used=(ref,), covered=dense, missing=())
            key = _region_key(ref)
            if key in seen:
                continue
            seen.add(key)
            description = self.describe(ref, offered)
            if description is None:
                unresolved = True
                continue
            providers.append((ref, description))

        required = self.expand(self.required, required_description)
        if required is None:
            return self.result(CoverageStatus.UNRESOLVED)
        intervals, used = [], []
        for ref, description in providers:
            expanded = self.expand(ref, description)
            if expanded is None:
                unresolved = True
                continue
            if expanded:
                intervals.extend(expanded)
                used.append(ref)
        count = len(intervals)
        if not self.take(count * (1 + count.bit_length()), None):
            return self.result(CoverageStatus.UNRESOLVED, used=tuple(used))
        merged = []
        for start, stop in sorted(intervals):
            if merged and start <= merged[-1][1]:
                merged[-1] = merged[-1][0], max(merged[-1][1], stop)
            else:
                merged.append((start, stop))
        # One monotone walk partitions only *requested* intervals. Bboxes never
        # add bytes to a strided selector or fill gaps in offered coverage.
        if not self.take(2 * (len(required) + len(merged)) + 1, None):
            return self.result(CoverageStatus.UNRESOLVED, used=tuple(used))
        covered, missing, cursor = [], [], 0
        for start, stop in required:
            position = start
            while cursor < len(merged) and merged[cursor][1] <= position:
                cursor += 1
            scan = cursor
            while scan < len(merged) and merged[scan][0] < stop:
                left, right = merged[scan]
                if left > position:
                    missing.append((position, min(left, stop)))
                if min(right, stop) > max(position, left):
                    covered.append((max(position, left), min(right, stop)))
                position = max(position, min(right, stop))
                if position == stop:
                    break
                scan += 1
            if position < stop:
                missing.append((position, stop))
            cursor = scan
        if not missing:
            return self.result(CoverageStatus.COVERED, used=tuple(used),
                               covered=tuple(covered), missing=())
        return self.result(CoverageStatus.UNRESOLVED if unresolved else CoverageStatus.INCOMPLETE,
                           used=tuple(used), covered=tuple(covered),
                           missing=None if unresolved else tuple(missing))


def _storage_coverage(required, offered, *, catalog, budget=4096):
    _record(required, RegionRef, "required region")
    _refs(offered, "offered regions")
    _exact(catalog, _ValueCatalog, "per-query ValueGraph resolver")
    _exact(budget, int, "geometry budget")
    if budget <= 0:
        raise ValueError("geometry budget must be positive")
    return _Coverage(required, offered, catalog, budget).run()


def storage_coverage(required, offered, *, value_graphs, budget=4096):
    """Compare a required byte selector with the union of offered selectors.

    Only caller-supplied snapshots are inspected. ``used`` lists the original
    nonempty offers included in the computed union, or the identity witness;
    it is a support set, not a claim of minimality or actual produced content.
    Unsupported/missing offers prevent INCOMPLETE, but do not invalidate a
    sufficient exact subset. Unsupported required geometry stays UNRESOLVED.
    Allocation identity includes artifact hash/schema/size; URI is not identity.
    """
    return _storage_coverage(required, offered, catalog=_ValueCatalog(value_graphs), budget=budget)


def _labeled_storage_coverage(required, offered, *, catalog, budget):
    """Preserve each offer's label while reusing the exact existing geometry.

    This is a derived view, not a new selector or content proof. Labels name
    caller-resolved fragments; the validity layer checks their version/domain.
    All repeated geometry and the label sweep consume one shared query budget.
    """
    from .validity_budget import ValidityBudget

    _record(required, RegionRef, "required region")
    _exact(offered, tuple, "labeled offers")
    _exact(catalog, _ValueCatalog, "per-query ValueGraph resolver")
    _exact(budget, ValidityBudget, "shared validity budget")
    seen = set()
    for offer in offered:
        _exact(offer, tuple, "labeled offer")
        if len(offer) != 2:
            raise ValueError("labeled offer must contain a label and region")
        label, ref = offer
        _exact(label, str, "coverage label")
        if not label or label in seen:
            raise ValueError("coverage labels must be nonempty and unique")
        seen.add(label)
        _record(ref, RegionRef, "labeled region")

    started, intersections, gaps = budget.used, [], []

    def geometry(refs):
        if budget.truncated or budget.remaining == 0:
            budget.mark_truncated('coverage.labels', 'no remaining shared budget for labeled geometry')
            return None
        result = _storage_coverage(required, refs, catalog=catalog, budget=budget.remaining)
        budget.spend('geometry', result.budget_used, path='coverage.labels')
        gaps.extend(result.gaps)
        if any(gap.code == 'geometry_budget_exhausted' for gap in result.gaps):
            budget.mark_truncated('coverage.labels', 'exact selector geometry exceeded the shared budget')
        return result

    union = geometry(tuple(ref for _, ref in offered))
    symbolic, events = [], []
    for label, ref in offered:
        if not budget.spend('coverage_labels', path='coverage.labels.offer'):
            break
        single = geometry((ref,))
        if single is None:
            break
        intersections.append({'label': label, 'region': ref, 'geometry': single})
        if single.status is CoverageStatus.COVERED and single.covered_intervals is None:
            symbolic.append(label)
        for left, right in single.covered_intervals or ():
            if not budget.spend('coverage_label_events', 2, path='coverage.labels.intersections'):
                break
            events.extend(((left, 1, label), (right, -1, label)))
        if budget.truncated:
            break

    portions = []
    if symbolic:
        # A huge exact strided selector can be covered without enumerating
        # holes. None here means the original symbolic selector, not zero bytes.
        portions.append({'selector': required, 'interval': None,
                         'labels': tuple(symbolic), 'symbolic': True})
    elif union is not None and union.covered_intervals is not None:
        # Mask the sweep by requested bytes. No bounding box fills their holes.
        required_intervals = (*union.covered_intervals, *(union.missing_intervals or ()))
        for left, right in required_intervals:
            if not budget.spend('coverage_label_events', 2, path='coverage.labels.demand'):
                break
            events.extend(((left, 1, None), (right, -1, None)))
        count = len(events)
        if not budget.truncated and budget.spend('coverage_label_sort', count * (1 + count.bit_length()),
                                                path='coverage.labels.sort'):
            events.sort(key=lambda event: event[0])
            active, requested, cursor = {}, 0, 0
            while cursor < count:
                position = events[cursor][0]
                while cursor < count and events[cursor][0] == position:
                    if not budget.spend('coverage_label_sweep', path='coverage.labels.sweep'):
                        break
                    _, delta, label = events[cursor]
                    if label is None:
                        requested += delta
                    else:
                        active[label] = active.get(label, 0) + delta
                        if not active[label]:
                            del active[label]
                    cursor += 1
                if budget.truncated or cursor == count:
                    break
                stop = events[cursor][0]
                if requested and position < stop:
                    cost = len(active) * (1 + len(active).bit_length()) + 1
                    if not budget.spend('coverage_label_sweep', cost, path='coverage.labels.portion'):
                        break
                    labels = tuple(sorted(active))
                    if portions and portions[-1]['labels'] == labels and portions[-1]['interval'][1] == position:
                        portions[-1]['interval'] = (portions[-1]['interval'][0], stop)
                    else:
                        portions.append({'selector': required, 'interval': (position, stop),
                                         'labels': labels, 'symbolic': False})

    status = CoverageStatus.UNRESOLVED
    if symbolic:
        status = CoverageStatus.COVERED
    elif union is not None and not budget.truncated:
        if union.status is CoverageStatus.COVERED and all(item['labels'] for item in portions):
            status = CoverageStatus.COVERED
        elif union.status is CoverageStatus.INCOMPLETE:
            status = CoverageStatus.INCOMPLETE
    return {'status': status.value, 'required': required, 'offered': offered, 'geometry': union,
            'intersections': tuple(intersections), 'portions': tuple(portions),
            'symbolic_whole': tuple(symbolic), 'budget_used': budget.used - started,
            'gaps': tuple(gaps), 'truncated': budget.truncated,
            'source_runtime_verified': False, 'transformation_authorized': False}


def labeled_storage_coverage(required, offered, *, value_graphs, budget=4096):
    """Return labeled byte coverage, without granting content/visibility proof."""
    from .validity_budget import ValidityBudget
    return _labeled_storage_coverage(required, offered, catalog=_ValueCatalog(value_graphs),
                                     budget=ValidityBudget(budget))


__all__ = ["RegionRef", "CoverageStatus", "CoverageGap", "StorageCoverageResult", "storage_coverage",
           "labeled_storage_coverage"]
