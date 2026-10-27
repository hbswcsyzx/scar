"""Canonical D reads plus strictly replayed P inventory; no capture authority."""
from dataclasses import replace
import json

from scar.ir.execution.common import MissingEvidence, Unresolved
from scar.ir.execution.content import ContentRead, HostConsumer, ProtocolInterval
from scar.ir.execution.coordinates import OccurrencePhase, OccurrencePoint
from scar.ir.execution.ids import ContentReadID, EvidenceInventoryID, WriteAssociationID
from scar.ir.execution.inventory import InventoryResolver, build_inventory
from scar.ir.execution.production import (
    EvidenceInventoryBinding, HostWrite, InventorySourceRef, SourceEdgeRef,
    ValueProduction, WriteAssociation,
)
from scar.ir.execution.snapshot import ExternalSnapshots
from scar.ir.program.providers import ProviderFactReference
from scar.ir.v2.evidence import EvidenceRelation
from tests.fixtures.execution_content_graphs import content_connection_fixture
from tests.fixtures.execution_produced_graphs import byte_prefix_execution


def production_query_fixture(*, write=True, native=False, outputs=1, observed_write=False,
                             raw_kind='torch_dispatch', observation=False):
    """Return program/model/catalogs/payloads/details with a real replayed bundle."""
    program, model, values, evidence, details = content_connection_fixture(observation=observation)
    descriptor = {'type': 'buffer', 'shape': [4], 'strides': [1], 'offset': 0,
                  'dtype': 'uint8', 'device': 'cpu', 'storage_id': 'hint',
                  'logical_version': 'hint-v0'}
    row = {'kind': raw_kind, 'invocation_id': 1, 'code_id': 'declared-op',
           'ts_ns': 10, 'duration_ns': 1, 'inputs': [],
           'outputs': [dict(descriptor) for _ in range(outputs)],
           'metadata': {'process_id': 10, 'thread_id': 11}}
    if observed_write:
        row['effect'] = {'writes': ['hint-v0']}
    if native:
        row['metadata']['scar_native_result'] = {'opaque': 'kept raw; not the byte-prefix schema'}
    raw = (json.dumps(row, sort_keys=True) + '\n').encode()
    manifest, index, payloads = build_inventory({'query': raw})
    source, = InventoryResolver(ExternalSnapshots(artifact_bytes=payloads)).resolve(manifest, index).sources
    binding = EvidenceInventoryBinding(EvidenceInventoryID('query.inventory'), model.runs[0].id,
        manifest, index, MissingEvidence('fixture, not native evidence'))
    reference = InventorySourceRef(binding.id, source.key)
    edges = tuple(edge for edge in source.bundle.evidence.edges.values()
                  if edge.relation is EvidenceRelation.PRODUCES)
    writes = ()
    if write and edges:
        association = WriteAssociation(WriteAssociationID('query.write'),
            SourceEdgeRef(reference, edges[0].edge_id), HostWrite(details['producer']),
            ValueProduction(details['data_value']), model.content_reads[0].placement, (), binding.source)
        writes = (association,)
    model = replace(model, source_inventories=(binding,), writes=writes)
    details = {**details, 'source': source, 'inventory': binding, 'source_ref': reference,
               'produce_edges': edges}
    return program, model, values, evidence, payloads, details


def native_production_query_fixture(**options):
    """A real canonical StateAccess read plus a parsed partial write Outcome."""
    program, model, values, payloads = byte_prefix_execution(**options)
    effect = model.writes[0].production.effect
    before = next(row.value for row in model.uses
                  if row.operation == effect.operation
                  and row.use == next(op for op in program.operations
                      if op.id == next(row.operation for row in model.operations
                          if row.id == effect.operation)).accesses[effect.index].before)
    anchor = OccurrencePoint(effect.operation, OccurrencePhase.BEFORE)
    missing = Unresolved('no native read-port proof', model.activations[0].entry)
    interval = ProtocolInterval(anchor, replace(anchor, phase=OccurrencePhase.AFTER),
        ProviderFactReference(model.snapshot.artifact, 'declared-host-read'), model.runs[0].source)
    read = ContentRead(ContentReadID('native.query.read'), HostConsumer(effect, interval),
        model.writes[0].placement, effect, anchor, (before,), missing, model.runs[0].source)
    return program, replace(model, content_reads=(read,)), values, {}, payloads, {'read': read.id}


__all__ = ['production_query_fixture', 'native_production_query_fixture']
