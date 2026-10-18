"""Whole-interval scans over genuine canonical operations and source inventory."""
from dataclasses import replace

import pytest

from scar.ir.execution.production_query import production
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.execution.validity_stability import production_interval, stability
from tests.fixtures.execution_lifetime_graphs import host_lifetime_execution


def _context(fixture=None):
    program, model, values, evidence, payloads, details = fixture or host_lifetime_execution()
    index = ExecutionIndex(model, program, value_graphs=values, evidence_graphs=evidence, artifact_bytes=payloads)
    ctx = index._ctx
    write = model.writes[0]
    universe = production(ctx, details['read'])
    begin, end = production_interval(ctx, write)
    fragment = {'write': write, 'resolved_write': ctx.resolved_writes[write.id],
        'production': ctx.resolved_establishments[details['established']],
        'actual': model.established_productions[0].actual, 'requested': write.placement.selector,
        'placement': write.placement, 'source_candidates': tuple(row['id'] for row in universe['candidates']
            if row['source'] == write.stage), 'source_universe': universe,
        'production_start': begin, 'production_end': end}
    return ctx, details, fragment


def test_exact_establishing_effect_excluded_without_erasing_source_universe():
    ctx, details, fragment = _context()
    view = stability(ctx, ctx.resolved_content_reads[details['read']], fragment, budget=ValidityBudget(4000))
    assert any(item['reason'] == 'exact-establishing-effect-only' for item in view['exclusions'])
    assert view['production_start'] != view['production_end']
    assert any('native' in condition for condition in view['conditions'])


def test_shared_budget_exhaustion_preserves_unvisited_threats():
    ctx, details, fragment = _context()
    budget = ValidityBudget(1)
    view = stability(ctx, ctx.resolved_content_reads[details['read']], fragment, budget=budget)
    assert budget.truncated and view['truncated']
    assert view['status'] != 'MATCHED'
    assert any('unvisited' in condition for condition in view['conditions'])


def test_two_intervening_write_restore_stages_do_not_disappear_at_equal_version_endpoints():
    from tests.fixtures.execution_lifetime_graphs import intervening_host_execution
    ctx, details, fragment = _context(intervening_host_execution())
    view = stability(ctx, ctx.resolved_content_reads[details['read']], fragment, budget=ValidityBudget(10000))
    conflicts = {item['id'] for item in view['invalidators']}
    assert {('effect', effect) for effect in details['middle_effects']} <= conflicts
    assert view['status'] == 'CONTRADICTED'


def test_write_inside_conservative_production_extent_is_potential_not_definite_repaired_content():
    from tests.fixtures.execution_lifetime_graphs import intervening_host_execution
    from scar.ir.execution.coordinates import OccurrencePhase, OccurrencePoint
    ctx, details, fragment = _context(intervening_host_execution())
    # Widen an upper bound; this does not move the canonical writer or claim
    # its last native write happened at the upper-bound observation.
    fragment['production_end'] = OccurrencePoint(details['middle_effects'][-1].operation, OccurrencePhase.AFTER)
    view = stability(ctx, ctx.resolved_content_reads[details['read']], fragment, budget=ValidityBudget(10000))
    target = ('effect', details['middle_effects'][0])
    assert target not in {item['id'] for item in view['invalidators']}
    assert target in {item['id'] for item in view['potential_invalidators']}


def test_retirement_is_separate_from_borrow_and_invalidates_exact_incarnation():
    from scar.ir.execution.coordinates import OccurrencePhase, OccurrencePoint
    from scar.ir.execution.ids import TargetLifetimeEventID
    from scar.ir.execution.validity import LifetimeEventKind
    fixture = list(host_lifetime_execution())
    model = fixture[1]
    retired = replace(model.target_lifetime_events[0], id=TargetLifetimeEventID('retired'),
                      kind=LifetimeEventKind.RETIRED,
                      at=OccurrencePoint(fixture[-1]['operation'], OccurrencePhase.BEFORE))
    fixture[1] = replace(model, target_lifetime_events=(*model.target_lifetime_events, retired))
    ctx, details, fragment = _context(fixture)
    view = stability(ctx, ctx.resolved_content_reads[details['read']], fragment, budget=ValidityBudget(5000))
    assert any(item['reason'] == 'declared-target-retirement' for item in view['invalidators'])
    assert view['status'] == 'CONTRADICTED'
    assert any(item['conditions'] for item in view['lifetime'])


def test_another_allocation_lifetime_does_not_retire_this_materialization():
    from scar.ir.execution.coordinates import OccurrencePhase, OccurrencePoint
    from scar.ir.execution.ids import TargetLifetimeEventID
    from scar.ir.execution.resources import AllocationTarget
    from scar.ir.execution.validity import LifetimeEventKind
    fixture = list(host_lifetime_execution())
    model, details = fixture[1], fixture[-1]
    graph = fixture[2][details['target'].artifact.sha256]
    other = graph.regions[details['other_region']].allocation
    event = replace(model.target_lifetime_events[0], id=TargetLifetimeEventID('other-retired'),
        target=AllocationTarget(details['target'].artifact, other), kind=LifetimeEventKind.RETIRED,
        at=OccurrencePoint(details['operation'], OccurrencePhase.BEFORE))
    fixture[1] = replace(model, target_lifetime_events=(*model.target_lifetime_events, event))
    ctx, details, fragment = _context(fixture)
    view = stability(ctx, ctx.resolved_content_reads[details['read']], fragment, budget=ValidityBudget(5000))
    assert not any(item['id'] == ('lifetime', event.id) for item in view['invalidators'])


def test_geometry_budget_guard_cannot_turn_unknown_comparison_into_disjoint():
    from scar.ir.execution.coverage import RegionRef
    from scar.ir.execution.validity_stability import _spatial
    ctx, details, fragment = _context()
    other = RegionRef(fragment['actual'].artifact, details['other_region'])
    budget = ValidityBudget(1)
    assert _spatial(ctx, fragment['actual'], other, budget) == 'UNRESOLVED'
    assert budget.truncated


@pytest.mark.parametrize('written', [0, 4, 16])
def test_source_requested_overlap_only_conflicts_for_actual_produced_overlap(written):
    from copy import deepcopy
    from hashlib import sha256
    import json

    from scar.ir.execution.coverage import RegionRef
    from scar.ir.execution.ids import EvidenceInventoryID
    from scar.ir.execution.inventory import build_inventory
    from scar.ir.execution.production import EvidenceInventoryBinding, InventorySourceRef, RawRecordRef
    from scar.ir.execution.snapshot import external_artifact
    from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
    from scar.ir.v2.ids import StorageRegionID
    from scar.ir.v2.values import StorageRegion
    from tests.fixtures.execution_lifetime_graphs import intervening_host_execution

    fixture = list(intervening_host_execution())
    model, graphs = fixture[1], fixture[2]
    old_ref = model.writes[0].placement.materialization.artifact
    graph = deepcopy(graphs[old_ref.sha256])
    allocation = next(iter(graph.materializations.values())).region
    allocation = graph.regions[allocation].allocation
    tail, prefix = StorageRegionID('validity.tail'), StorageRegionID('validity.prefix')
    graph.add_region(StorageRegion(tail, allocation, 8, (8,), (1,), 'uint8', 'cpu'))
    graph.add_region(StorageRegion(prefix, allocation, 0, (written,), (1,), 'uint8', 'cpu'))
    artifact = external_artifact(graph)

    def placement(row):
        return replace(row, materialization=replace(row.materialization, artifact=artifact),
                       selector=RegionRef(artifact, row.selector.region))

    profile = {'schema': 'scar.native.byte-prefix-write', 'schema_version': 1,
               'stage': 'partial-intervening', 'requested_bytes': 16, 'written_bytes': written}
    raw = (json.dumps({'kind': 'python_c_call', 'invocation_id': 1, 'code_id': 'partial-intervening',
        'ts_ns': 20, 'duration_ns': 1, 'inputs': [], 'outputs': [],
        'metadata': {'process_id': 10, 'thread_id': 11, 'scar_native_result': profile}}) + '\n').encode()
    manifest, index, payloads = build_inventory({'partial': raw})
    inventory = EvidenceInventoryBinding(EvidenceInventoryID('partial'), model.runs[0].id,
                                         manifest, index, model.runs[0].source)
    stage = RawRecordRef(InventorySourceRef(inventory.id, 'partial'), 1, sha256(raw).hexdigest())
    raw_artifact = ProviderArtifact('inventory:partial:raw', sha256(raw).hexdigest(), len(raw), 'scar.trace.raw-jsonl')
    result = ProviderFactReference(raw_artifact, '#L1/metadata/scar_native_result')
    writes = tuple(replace(row, placement=placement(row.placement),
                           stage=row.stage if number == 0 else stage)
                   for number, row in enumerate(model.writes))
    established = tuple(replace(row,
        actual=RegionRef(artifact, row.actual.region if number == 0 else prefix),
        result=row.result if number == 0 else result)
        for number, row in enumerate(model.established_productions))
    fixture[1] = replace(model, writes=writes, established_productions=established,
        content_reads=(replace(model.content_reads[0], placement=placement(model.content_reads[0].placement)),),
        target_lifetime_events=tuple(replace(row, target=replace(row.target, artifact=artifact))
                                    for row in model.target_lifetime_events),
        source_inventories=(*model.source_inventories, inventory))
    fixture[2] = {**graphs, artifact.sha256: graph}
    fixture[4] = {**fixture[4], **payloads}
    ctx, details, fragment = _context(fixture)
    fragment['actual'] = RegionRef(artifact, tail)
    view = stability(ctx, ctx.resolved_content_reads[details['read']], fragment, budget=ValidityBudget(14000))
    source_conflicts = [item for item in view['invalidators']
                        if type(item.get('original')) is dict and 'source' in item['original']]
    assert bool(source_conflicts) is (written == 16)
