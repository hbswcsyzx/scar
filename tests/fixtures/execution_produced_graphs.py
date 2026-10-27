"""Original canonical work/host effects with conditional production declarations."""
from dataclasses import replace
from hashlib import sha256
import json

from scar.ir.execution.common import Unresolved
from scar.ir.execution.content import StorageContent
from scar.ir.execution.coverage import RegionRef
from scar.ir.execution.ids import EvidenceInventoryID, OutcomeProductionID, WriteAssociationID
from scar.ir.execution.coordinates import ValueOccurrence
from scar.ir.execution.ids import ValueOccurrenceID
from scar.ir.execution.production import (
    BytePrefixWrite, EvidenceInventoryBinding, ExternalEstablishment, HostWrite,
    InventorySourceRef, OutcomeProduction, RawRecordRef, SourceEdgeRef, StateProduction,
    ValueProduction, WorkWrite, WriteAssociation,
)
from scar.ir.execution.snapshot import external_artifact, snapshot_for
from scar.ir.execution.work import MaterializationRef, WorkOutcomeKind
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.ids import ValueID
from scar.ir.program.model import DataValue, OperationResult
from scar.ir.v2.ids import (
    LogicalValueID, MaterializationID, StorageAllocationID, StorageRegionID, ValueVersionID,
)
from scar.ir.v2.values import (
    LogicalValue, Materialization, StorageAllocation, StorageRegion, ValueGraph, ValueVersion,
)
from tests.fixtures.execution_work_graphs import invoke_work_execution, ordinary_work_execution


def produced_execution(*, host=False, external=False, invoke=False, raised=False, value=False,
                       requested=8, actual=4, work_value=False):
    """Return (program, model, value_graphs), retaining exact original effects.

    Unavailable raw/native result evidence stays unresolved. The graph contains
    no fake ticket for host/external writers and no source/runtime proof.
    """
    program, model, _ = invoke_work_execution(raised=raised) if invoke else ordinary_work_execution()
    original_work = model.submissions[0]
    effect = original_work.effects[0]
    operation = original_work.origin.operation
    work_output = None
    if work_value:
        occurrence = next(row for row in model.operations if row.id == operation)
        original = next(row for row in program.operations if row.id == occurrence.operation)
        output = DataValue(ValueID('produced.result'), program.root,
                           OperationResult(original.id, len(original.results)), 'builtins.bytes')
        program = replace(program, operations=tuple(replace(row, results=(*row.results, output.id))
            if row.id == original.id else row for row in program.operations), values=(*program.values, output))
        work_output = ValueOccurrence(ValueOccurrenceID('produced.result'), output.id, operation)
        model = replace(model, snapshot=snapshot_for(program), values=(*model.values, work_output))
    graph = ValueGraph()
    logical, allocation = LogicalValueID('produced.bytes'), StorageAllocationID('produced.bytes')
    version, mat = ValueVersionID(logical, 1), MaterializationID('produced.bytes')
    graph.add_logical_value(LogicalValue(logical, 'bytes'))
    graph.add_version(ValueVersion(version))
    graph.add_allocation(StorageAllocation(allocation, 'cpu', 32))
    actual_count = actual
    request, actual = StorageRegionID('produced.request'), StorageRegionID('produced.actual')
    graph.add_region(StorageRegion(request, allocation, 0, (requested,), (1,), 'uint8', 'cpu'))
    graph.add_region(StorageRegion(actual, allocation, 0, (actual_count,), (1,), 'uint8', 'cpu'))
    graph.add_materialization(Materialization(mat, version, 'bytes', 'cpu', request))
    artifact = external_artifact(graph)
    unknown = Unresolved('no raw/native result evidence supplied', model.activations[0].entry)
    production = StateProduction(effect)
    writer = WorkWrite(original_work.id)
    if host:
        writer = HostWrite(operation)
    if value:
        actual_value = next(row for row in model.values if row.origin == model.operations[0].id
                            and row.value.value == 'resource.fd')
        production = ValueProduction(actual_value.id)
        writer = HostWrite(actual_value.origin)
    if work_value:
        production = ValueProduction(work_output.id)
    if external:
        writer, production = ExternalEstablishment(model.activations[0].entry), unknown
    write = WriteAssociation(WriteAssociationID('write'), unknown, writer, production,
        StorageContent(MaterializationRef(artifact, mat), RegionRef(artifact, request)), (), model.runs[0].source)
    if host or external or value:
        model = replace(model, submissions=(), outcomes=(), quiescences=(), retentions=(), queue_prefixes=())
        produced = ()
    else:
        produced = (OutcomeProduction(OutcomeProductionID('produced'), write.id, model.outcomes[0].id,
            None if work_value else 0, RegionRef(artifact, actual), unknown, model.runs[0].source),)
    model = replace(model, writes=(write,), produced=produced)
    return program, model, {artifact.sha256: graph}


def byte_prefix_execution(*, profile=None, requested=8, written=4, kind=WorkOutcomeKind.COMPLETED,
                          invoke=False, raised=False):
    """Return (program, model, value_graphs, artifact_bytes) from real raw bytes.

    The source payload is a declaration; it does not authenticate a native write.
    Requested and actual selectors are original ValueGraph regions.
    """
    from scar.ir.execution.inventory import build_inventory

    program, model, values = produced_execution(invoke=invoke, raised=raised, requested=requested, actual=written)
    if profile is None:
        profile = {'schema': 'scar.native.byte-prefix-write', 'schema_version': 1,
                   'stage': 'native-prefix-stage', 'requested_bytes': requested, 'written_bytes': written}
    event = {'kind': 'python_c_call', 'invocation_id': 1, 'code_id': 'declared-native-write',
             'ts_ns': 10, 'duration_ns': 1, 'inputs': [], 'outputs': [],
             'metadata': {'process_id': 10, 'thread_id': 11, 'scar_native_result': profile}}
    raw = (json.dumps(event, separators=(',', ':'), sort_keys=True) + '\n').encode('utf-8')
    manifest, index, payloads = build_inventory({'native': raw})
    inventory = EvidenceInventoryBinding(EvidenceInventoryID('native'), model.runs[0].id,
                                         manifest, index, model.runs[0].source)
    stage = RawRecordRef(InventorySourceRef(inventory.id, 'native'), 1, sha256(raw).hexdigest())
    raw_artifact = ProviderArtifact('inventory:native:raw', sha256(raw).hexdigest(), len(raw), 'scar.trace.raw-jsonl')
    result = ProviderFactReference(raw_artifact, '#L1/metadata/scar_native_result')
    model = replace(model, source_inventories=(inventory,),
        writes=(replace(model.writes[0], stage=stage),),
        outcomes=(replace(model.outcomes[0], protocol_result=result, kind=kind),),
        produced=(replace(model.produced[0], rule=BytePrefixWrite()),))
    return program, model, values, payloads


def source_write_execution(*, wrong_target=False):
    """Use a replayed source bundle's original mat/version, not bare ID joins."""
    from scar.ir.execution.inventory import build_inventory, InventoryResolver
    from scar.ir.execution.snapshot import ExternalSnapshots
    from scar.ir.v2.evidence import EvidenceRelation

    program, model, _ = produced_execution()
    output = {'type': 'buffer', 'shape': [8], 'strides': [1], 'offset': 0,
              'device': 'cpu', 'dtype': 'uint8', 'storage_id': 'captured-storage-hint'}
    event = {'kind': 'torch_dispatch', 'invocation_id': 1, 'code_id': 'declared-two-output',
             'ts_ns': 10, 'duration_ns': 1, 'inputs': [], 'outputs': [output, output],
             'metadata': {'process_id': 10, 'thread_id': 11}}
    raw = (json.dumps(event) + '\n').encode('utf-8')
    manifest, index, payloads = build_inventory({'source': raw})
    resolved = InventoryResolver(ExternalSnapshots(artifact_bytes=payloads)).resolve(manifest, index).sources[0]
    edge = next(row for row in resolved.bundle.evidence.edges.values() if row.relation is EvidenceRelation.PRODUCES)
    observation = resolved.bundle.evidence.observations[edge.target.reference]
    materialization = observation.materialization
    if wrong_target:
        materialization = next(identity for identity in resolved.bundle.values.materializations if identity != materialization)
    original = resolved.bundle.values.materializations[materialization]
    inventory = EvidenceInventoryBinding(EvidenceInventoryID('source'), model.runs[0].id,
                                         manifest, index, model.runs[0].source)
    stage = SourceEdgeRef(InventorySourceRef(inventory.id, 'source'), edge.edge_id)
    placement = StorageContent(MaterializationRef(resolved.values_artifact, materialization),
                               RegionRef(resolved.values_artifact, original.region))
    model = replace(model, source_inventories=(inventory,),
                    writes=(replace(model.writes[0], stage=stage, placement=placement),), produced=())
    return program, model, {resolved.values_artifact.sha256: resolved.bundle.values}, payloads


__all__ = ['produced_execution', 'byte_prefix_execution', 'source_write_execution']
