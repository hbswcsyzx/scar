"""One multi-function declared pipeline, never a recovered runtime program.

All stages share one ProgramGraph and ExecutionModel. CPU/GPU placements are
declarations; payload values are not saved or used as identity proofs.
"""
from dataclasses import replace
from hashlib import sha256
import json

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.common import Unresolved
from scar.ir.execution.content import (
    ContentRead, DataIdentity, EndpointContent, HostConsumer, ObservationConsumer,
    ProtocolInterval, ProtocolSelector, ResourceConsumer, StorageContent,
    ValueDenotation, VersionRef, WholeWorkRead,
)
from scar.ir.execution.coordinates import AccessRef, OccurrencePhase, OccurrencePoint, UseRef
from scar.ir.execution.coverage import RegionRef
from scar.ir.execution.ids import (
    CallActivationID, ContentReadID, ContributionSupportID, DenotationID,
    EstablishedProductionID, EvidenceInventoryID, HandleBindingID,
    ObservationRequirementID, ObservationRootID, RealizationID, ResourceAccessID,
    ResourceBindingID, ResourceInstanceID, QueuePrefixID, QueueOrderProfileID,
    OutcomeProductionID, WorkOutcomeID, WorkQuiescenceID,
    WorkRetentionID, WorkTicketID, WriteAssociationID,
)
from scar.ir.execution.inventory import build_inventory
from scar.ir.execution.observations import (
    BoundEndpoint, ContractRef, ObservationRequirement, ObservationRoot, OutputValue,
    RequiredEndpoint, RequiredOutput,
)
from scar.ir.execution.production import (
    BytePrefixWrite, EvidenceInventoryBinding, HostWrite, InventorySourceRef,
    RawRecordRef, StateProduction, WorkWrite, OutcomeProduction, WriteAssociation,
)
from scar.ir.execution.resources import (
    EndedAt, ExplicitHandle, HandleBinding, ImplicitBinding, ImportedAt, InstanceTarget,
    ProcessRealm, ReleaseAuthority, RequirementBinding, ResourceAccessBinding,
    ResourceInstance, ResourceRealization, Sharing, UnresolvedHandle,
)
from scar.ir.execution.snapshot import external_artifact, snapshot_for
from scar.ir.execution.validity import (
    CompletedVisibility, ContributionSupport, EstablishedProduction, HostDomain,
    OrderedVisibility, QueueDomain, EndpointDomain,
)
from scar.ir.execution.order import QueueOrderProfile
from scar.ir.execution.work import (
    BorrowRelease, MaterializationRef, ResourceOutcome, WorkOutcomeKind,
    WorkQuiescence, WorkRetention, WorkSubmission, WithinOperation,
    QueuePrefix, QueueStart, Queued,
)
from scar.ir.program.cleanup import CleanupRouteSuccessor, CleanupRouteTerminator
from scar.ir.program.control import (
    ControlScope, ControlScopeKind, ExceptionPacketDefinition,
    PendingCompletionDefinition, ProtocolValueKind as P, ProtocolValueType,
)
from scar.ir.program.ids import (
    BlockID, ControlPortID, ControlScopeID, OperationID, RegionID,
    ResourceDefinitionID, ResourceRequirementID, UseID, ValueID,
)
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult,
    CompletionSignature, CompletionSuccessor, DataValue, ExitKind, ExitPort,
    Footprint, FootprintKind, LiteralOrigin, Operation, OperationResult,
    ProtocolValue, ReferenceValue, Region, StateAccess, StateVersionValue,
    Successor, Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.resources import (
    ExternalResource, ResourceDefinition, ResourceKind, ResourceRequirement,
    ResourceRole, ResourceUse,
)
from scar.ir.v2.common import Completeness
from scar.ir.v2.contracts import ContractDefinition, ContractFacet, FacetRequirement
from scar.ir.v2.ids import (
    ContractID, LogicalValueID, MaterializationID, ProvenanceID,
    StorageAllocationID, StorageRegionID, ValueSlotID, ValueVersionID,
)
from scar.ir.v2.semantic import SemanticGraph, ValueSlot
from scar.ir.v2.values import (
    LogicalValue, Materialization, ProvenanceRecord, ProvenanceRelation,
    StorageAllocation, StorageRegion, ValueGraph, ValueVersion,
)
from tests.fixtures.execution_call_graphs import _model
from tests.fixtures.program_cleanup_invoke_graphs import cleanup_invoke_graph
from tests.fixtures.program_control_graphs import _source


class _Builder:
    def __init__(self, graph):
        self.graph = graph
        self.values = list(graph.values)
        self.operations = list(graph.operations)
        self.regions = list(graph.regions)
        self.scopes = list(graph.control_scopes)
        self.packets = list(graph.exception_packets)
        self.world = graph.locations[0].id
        self.ambient = graph.handled_context_domains[0].location

    def value(self, name, region, origin, kind):
        identity = ValueID(name)
        row = (ReferenceValue(identity, region, origin) if kind == 'ref' else
               StateVersionValue(identity, region, origin, kind) if kind in (self.world, self.ambient) else
               ProtocolValue(identity, region, origin, kind) if type(kind) is P else
               DataValue(identity, region, origin, kind))
        self.values.append(row)
        return identity

    def args(self, block, region, kinds):
        return tuple(self.value(block.value + f'.arg.{i}', region, BlockArgument(block, i), kind)
                     for i, kind in enumerate(kinds))

    def use(self, name, value):
        row = next(row for row in self.values if row.id == value)
        role = (UseRole.REFERENCE if type(row) is ReferenceValue else
                UseRole.STATE_CONTENT if type(row) is StateVersionValue else
                UseRole.PROTOCOL if type(row) is ProtocolValue else UseRole.DATA)
        return Use(UseID(name), value, role)

    def op(self, name, uses=(), results=(), **kwargs):
        behaviors = ((Behavior.CONTROL, Behavior.READ, Behavior.WRITE) if kwargs.get('accesses') else
                     (Behavior.CONTROL,))
        row = Operation(OperationID(name), name, behaviors,
                        tuple(uses), tuple(results), **kwargs)
        self.operations.append(row)
        return row

    def leaf(self, stage, failed):
        region, entry = RegionID('io.' + stage), BlockID('io.' + stage + '.entry')
        close = stage == 'close'
        args = self.args(entry, region, ('ref', self.world, self.ambient) if close else
                         ('ref', 'ref', self.world, self.ambient))
        payload, sink = (args[0], args[0]) if close else args[:2]
        world, ambient = args[-2:]
        names = {'load': ('read',), 'prepare': ('represent', 'materialize', 'wait'),
                 'run': ('submit', 'wait', 'consume'), 'save': ('serialize', 'write'),
                 'close': ('buffer_read', 'flush', 'close')}[stage]
        entry_ops, primitives, primitive_states = [], {}, {}
        serialized = None
        for name in names:
            op_id = OperationID(f'io.{stage}.{name}')
            source = self.use(op_id.value + '.source', serialized if name in ('write', 'flush') else payload)
            receiver = self.use(op_id.value + '.sink', sink)
            before = self.use(op_id.value + '.world', world)
            produces = name in ('read', 'represent', 'materialize', 'submit', 'consume', 'serialize', 'buffer_read')
            kind = 'builtins.bytes' if name in ('serialize', 'buffer_read') else 'ref'
            result = self.value(op_id.value + '.result', region, OperationResult(op_id, 0), kind) if produces else None
            after = self.value(op_id.value + '.after', region,
                               OperationResult(op_id, int(produces)), self.world)
            op = self.op(op_id.value, (source, receiver, before),
                (*((result,) if produces else ()), after),
                accesses=(StateAccess(self.world, before.id, AccessMode.READ_WRITE, after,
                                     Footprint(FootprintKind.WHOLE), reference=receiver.id),),
                effects_complete=False)
            primitives[name] = op.id
            entry_ops.append(op.id)
            world = after
            if name in ('serialize', 'buffer_read'):
                serialized = result
            elif result is not None:
                payload = result
            primitive_states[name] = (payload, world)
        condition = self.value(f'io.{stage}.failed', region, LiteralOrigin(failed), 'builtins.bool')
        test = self.use(f'io.{stage}.condition', condition)
        normal, failure = BlockID(f'io.{stage}.normal'), BlockID(f'io.{stage}.failure')
        normal_args = self.args(normal, region, (self.world, self.ambient) if close else ('ref', self.world, self.ambient))
        failure_args = self.args(failure, region, (self.world, self.ambient))
        # The host can fail immediately after enqueue. The successful route
        # alone executes wait/consume; this is not a missing-capture trick.
        if stage == 'run':
            incoming_payload, incoming_world = primitive_states['submit']
            normal_values = (incoming_payload, incoming_world, ambient)
            failure_values = (incoming_world, ambient)
        else:
            normal_values = (world, ambient) if close else (payload, world, ambient)
            failure_values = (world, ambient)
        normal_uses = tuple(self.use(f'io.{stage}.normal.{i}', value) for i, value in enumerate(normal_values))
        failure_uses = tuple(self.use(f'io.{stage}.failure.{i}', value) for i, value in enumerate(failure_values))
        branch = self.op(f'io.{stage}.branch', (test, *normal_uses, *failure_uses),
            terminator=Terminator(TerminatorKind.BRANCH, (
                Successor(normal, tuple(use.id for use in normal_uses)),
                Successor(failure, tuple(use.id for use in failure_uses))), condition=test.id))
        entry_ops.append(branch.id)
        normal_ops = []
        if stage == 'run':
            normal_ops = [primitives['wait'], primitives['consume']]
            entry_ops = [primitives['submit'], branch.id]
            replacements = {incoming_payload: normal_args[0], incoming_world: normal_args[1]}
            self.operations = [replace(op, uses=tuple(replace(use, value=replacements.get(use.value, use.value))
                for use in op.uses)) if op.id in normal_ops else op for op in self.operations]
            return_values = (payload, world, normal_args[2])
        else:
            return_values = normal_args
        returned = tuple(self.use(f'io.{stage}.return.{i}', value) for i, value in enumerate(return_values))
        done = self.op(f'io.{stage}.return', returned,
            terminator=Terminator(TerminatorKind.RETURN, exit='normal', values=tuple(use.id for use in returned)))
        error_id = OperationID(f'io.{stage}.error')
        error = self.value(error_id.value + '.exception', region, OperationResult(error_id, 0), 'ref')
        tb = self.value(error_id.value + '.traceback', region, OperationResult(error_id, 1), 'ref')
        error_op = self.op(error_id.value, results=(error, tb), effects_complete=False)
        packet_id = OperationID(f'io.{stage}.packet')
        packet = self.value(packet_id.value, region, OperationResult(packet_id, 0), P.EXCEPTION_PACKET)
        ex_use, tb_use = self.use(packet_id.value + '.exception', error), self.use(packet_id.value + '.tb', tb)
        pack = self.op(packet_id.value, (ex_use, tb_use), (packet,), effects_complete=True)
        self.packets.append(ExceptionPacketDefinition(packet, ex_use.id, tb_use.id))
        raised = tuple(self.use(f'io.{stage}.raise.{i}', value) for i, value in enumerate((packet, *failure_args)))
        throw = self.op(f'io.{stage}.raise', raised,
            terminator=Terminator(TerminatorKind.RAISE, exit='exception', values=tuple(use.id for use in raised)))
        normal_types = (() if close else (ValueType(ValueKind.REFERENCE),)) + (
            ValueType(ValueKind.STATE, location=self.world), ValueType(ValueKind.STATE, location=self.ambient))
        failure_types = (ProtocolValueType(P.EXCEPTION_PACKET), *normal_types[-2:])
        blocks = (Block(entry, args, tuple(entry_ops)), Block(normal, normal_args, (*normal_ops, done.id)),
                  Block(failure, failure_args, (error_op.id, pack.id, throw.id)))
        self.regions.append(Region(region, stage, entry, blocks,
            (ExitPort('normal', ExitKind.NORMAL, normal_types), ExitPort('exception', ExitKind.RAISE, failure_types)),
            parent=self.graph.root))
        self.scopes.append(ControlScope(ControlScopeID('io.' + stage), region, None,
            ControlScopeKind.FUNCTION, _source('io.' + stage), tuple(block.id for block in blocks)))
        return {'region': region, 'entry': entry, 'normal': normal, 'failure': failure,
                'path': ((entry, int(failed)), (failure if failed else normal, None)),
                'terminal': throw.id if failed else done.id, 'primitives': primitives,
                'payload': payload, 'serialized': serialized, 'normal_types': normal_types,
                'failure_types': failure_types}

    def workflow(self, stages):
        region, entry = RegionID('io.workflow'), BlockID('io.workflow.entry')
        args = self.args(entry, region, ('ref', 'ref', self.world, self.ambient))
        payload, sink, world, ambient = args
        blocks, calls, path, terminal = [], {}, [], None
        block, arguments = entry, args
        for stage in ('load', 'prepare', 'run', 'save'):
            callee = stages[stage]
            normal, failure = BlockID(f'io.workflow.after.{stage}'), BlockID(f'io.workflow.failed.{stage}')
            normal_args = self.args(normal, region, ('ref', self.world, self.ambient))
            failure_args = self.args(failure, region, (P.EXCEPTION_PACKET, self.world, self.ambient))
            uses = tuple(self.use(f'io.call.{stage}.{i}', value)
                         for i, value in enumerate((payload, sink, world, ambient)))
            call = self.op(f'io.call.{stage}', uses,
                completions=(CompletionSignature(ExitKind.NORMAL, callee['normal_types']),
                             CompletionSignature(ExitKind.RAISE, callee['failure_types'])),
                callee=callee['region'], invoke_arguments=tuple(use.id for use in uses),
                terminator=Terminator(TerminatorKind.INVOKE, (
                    CompletionSuccessor(ExitKind.NORMAL, normal, tuple(CompletionResult(i) for i in range(3))),
                    CompletionSuccessor(ExitKind.RAISE, failure, tuple(CompletionResult(i) for i in range(3))))))
            blocks.append(Block(block, arguments, (call.id,)))
            failed = callee['path'][0][1] == 1
            if terminal is None:
                path.append((block, int(failed)))
            raised = tuple(self.use(f'io.workflow.raise.{stage}.{i}', value) for i, value in enumerate(failure_args))
            throw = self.op(f'io.workflow.raise.{stage}', raised,
                terminator=Terminator(TerminatorKind.RAISE, exit='exception', values=tuple(use.id for use in raised)))
            blocks.append(Block(failure, failure_args, (throw.id,)))
            calls[stage] = call.id
            if failed and terminal is None:
                path.append((failure, None))
                terminal = throw.id
            block, arguments = normal, normal_args
            payload, world, ambient = normal_args
        returned = tuple(self.use(f'io.workflow.return.{i}', value) for i, value in enumerate(arguments))
        done = self.op('io.workflow.return', returned,
            terminator=Terminator(TerminatorKind.RETURN, exit='normal', values=tuple(use.id for use in returned)))
        blocks.append(Block(block, arguments, (done.id,)))
        if terminal is None:
            path.append((block, None))
            terminal = done.id
        self.regions.append(Region(region, 'load prepare run save', entry, tuple(blocks), (
            ExitPort('normal', ExitKind.NORMAL, stages['load']['normal_types']),
            ExitPort('exception', ExitKind.RAISE, stages['load']['failure_types'])), parent=self.graph.root))
        self.scopes.append(ControlScope(ControlScopeID('io.workflow'), region, None,
            ControlScopeKind.FUNCTION, _source('io.workflow'), tuple(block.id for block in blocks)))
        return {'region': region, 'entry': entry, 'path': tuple(path), 'calls': calls, 'terminal': terminal}


def _program(raised_stage, close_raises):
    graph = cleanup_invoke_graph()
    b = _Builder(graph)
    stages = {stage: b.leaf(stage, stage == raised_stage or stage == 'close' and close_raises)
              for stage in ('load', 'prepare', 'run', 'save', 'close')}
    workflow = b.workflow(stages)
    main = graph.regions[0]
    block = BlockID('io.main.invoke')
    args = b.args(block, main.id, ('ref', b.world, b.ambient))
    failure = BlockID('io.main.failed')
    failed_args = b.args(failure, main.id, (P.EXCEPTION_PACKET, b.world, b.ambient))
    sink = ValueID('shared.exception.input')
    uses = tuple(b.use(f'io.main.call.{i}', value) for i, value in enumerate((args[0], sink, *args[1:])))
    invoke = b.op('io.main.call', uses, callee=workflow['region'],
        invoke_arguments=tuple(use.id for use in uses),
        completions=(CompletionSignature(ExitKind.NORMAL, stages['load']['normal_types']),
                     CompletionSignature(ExitKind.RAISE, stages['load']['failure_types'])),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID('shared.make_return'), tuple(CompletionResult(i) for i in range(3))),
            CompletionSuccessor(ExitKind.RAISE, failure, tuple(CompletionResult(i) for i in range(3))))))
    pack_id = OperationID('io.main.pending.raise')
    packet = b.use('io.main.pending.packet', failed_args[0])
    pending = b.value('io.main.pending', main.id, OperationResult(pack_id, 0), P.PENDING_COMPLETION)
    pack = b.op(pack_id.value, (packet,), (pending,), effects_complete=True)
    selector = b.use('io.main.route.selector', pending)
    forwards = tuple(b.use(f'io.main.route.{i}', value) for i, value in enumerate((pending, *failed_args[1:])))
    route = b.op('io.main.route', (selector, *forwards), terminator=CleanupRouteTerminator(selector.id, (
        CleanupRouteSuccessor(ControlPortID('shared.port.raise'), BlockID('shared.cleanup'), tuple(use.id for use in forwards)),)))
    operations = []
    for op in b.operations:
        if op.id == OperationID('shared.branch'):
            first, *others = op.terminator.successors
            op = replace(op, terminator=replace(op.terminator, successors=(replace(first, block=block), *others)))
        elif op.id == OperationID('shared.cleanup.write'):
            handle = b.use('io.close.actual.handle', sink)
            op = replace(op, uses=(handle, *op.uses),
                         invoke_arguments=(handle.id, *op.invoke_arguments), callee=stages['close']['region'])
        operations.append(op)
    extra_blocks = (Block(block, args, (invoke.id,)), Block(failure, failed_args, (pack.id, route.id)))
    b.regions[0] = replace(main, label='pipeline.main', blocks=(*main.blocks, *extra_blocks))
    b.scopes = [replace(row, blocks=(*row.blocks, block, failure))
                if row.id == graph.cleanup_interfaces[0].protected else row for row in b.scopes]
    graph = replace(graph, regions=tuple(b.regions), operations=tuple(operations), values=tuple(b.values),
        control_scopes=tuple(b.scopes), exception_packets=tuple(b.packets),
        pending_completions=(*graph.pending_completions,
            PendingCompletionDefinition(pending, ControlPortID('shared.port.raise'), packet.id)))
    return graph, stages, workflow


def io_pipeline_execution(*, raised_stage=None, written=8, pending=False, close_raises=False,
                          include_call_links=True, include_endpoint_read=True,
                          include_flush_production=True, early_observation=False):
    """Return (program, model, catalogs, details), all from one canonical graph.

    Source/endpoint overlays are added below; all values are metadata only.
    ``pending`` is missing native work completion, never a missing host return.
    """
    if raised_stage not in (None, 'load', 'prepare', 'run', 'save'):
        raise ValueError('unknown pipeline stage')
    if type(written) is not int or not 0 <= written <= 8:
        raise ValueError('written must be an exact prefix length in [0,8]')
    program, stages, workflow = _program(raised_stage, close_raises)
    failed = raised_stage is not None
    raise_final = failed or close_raises
    main_path = [(BlockID('shared.entry'), 0), (BlockID('io.main.invoke'), int(failed)),
                 (BlockID('io.main.failed') if failed else BlockID('shared.make_return'), 0),
                 (BlockID('shared.cleanup'), int(close_raises))]
    if close_raises:
        main_path += [(BlockID('invoke.cleanup.failed'), 0), (BlockID('invoke.cleanup.replace'), 0)]
    else:
        main_path += [(BlockID('invoke.cleanup.normal'), 0)]
    main_path += [(BlockID('shared.cleanup.post-pop-route'), int(raise_final)),
                  (BlockID('shared.dispatch.block'), int(raise_final)),
                  (BlockID('shared.raise_exit' if raise_final else 'shared.return_exit'), None)]
    paths = [(program.root, tuple(main_path), 'io.main'),
             (workflow['region'], workflow['path'], 'io.workflow')]
    called_stages = []
    for stage in ('load', 'prepare', 'run', 'save'):
        called_stages.append(stage)
        paths.append((stages[stage]['region'], stages[stage]['path'], 'io.' + stage))
        if stage == raised_stage:
            break
    paths.append((stages['close']['region'], stages['close']['path'], 'io.close'))
    model, scopes, source = _model(program, paths)
    by_region = {region: (activation, visits, operations) for (region, _, _), (activation, visits, operations)
                 in zip(paths, scopes, strict=True)}
    links = []
    main_ops = by_region[program.root][2]
    pairs = [(main_ops[invoke], workflow['region'], workflow['terminal'])
             for invoke in (OperationID('io.main.call'),)]
    workflow_ops = by_region[workflow['region']][2]
    pairs += [(workflow_ops[workflow['calls'][stage]], stages[stage]['region'], stages[stage]['terminal'])
              for stage in called_stages]
    pairs.append((main_ops[OperationID('shared.cleanup.write')], stages['close']['region'], stages['close']['terminal']))
    for number, (caller, region, terminal) in enumerate(pairs):
        activation, visits, operations = by_region[region]
        links.append(CallActivation(CallActivationID(f'io.link.{number}'), caller, activation,
                                    visits[0], operations[terminal], source))
    model = replace(model, call_activations=tuple(links) if include_call_links else ())
    details = {'stages': stages, 'workflow': workflow, 'by_region': by_region,
               'called_stages': tuple(called_stages), 'raise_final': raise_final,
               'main_return': main_ops.get(OperationID('shared.return.exit.op')),
               'main_raise': main_ops.get(OperationID('shared.raise.exit.op')),
               'source': source, 'pending': pending or raised_stage == 'run', 'written': written,
               'include_endpoint_read': include_endpoint_read,
               'include_flush_production': include_flush_production, 'early_observation': early_observation}
    return _overlay(program, model, details)


def _overlay(program, model, details):
    source, point = details['source'], model.activations[0].entry
    unknown = Unresolved('hand-authored pipeline; native/source applicability unverified', point)
    definitions = {row.id: row for row in program.values}
    operations = {row.id: row for row in program.operations}
    occurrences = {row.operation: row for row in model.operations
                   if row.operation.value.startswith('io.')}
    dynamic = {(row.operation, row.use): row for row in model.uses}

    def occurrence(stage, name):
        return occurrences[details['stages'][stage]['primitives'][name]]

    def support(row):
        return tuple(dynamic[row.id, use.id].value for use in operations[row.operation].uses
                     if type(definitions[use.value]) is StateVersionValue)

    def profile(operation, length):
        data = json.dumps({'schema': 'scar.endpoint-byte-profile', 'schema_version': 1,
            'profile': 'BYTE_PREFIX_READ_AFTER_COMPLETED_WRITE', 'operation': operation,
            'offset_bytes': 0, 'length_bytes': length}, sort_keys=True, separators=(',', ':')).encode()
        artifact = ProviderArtifact('memory:io-profile-' + operation, sha256(data).hexdigest(), len(data),
                                    'scar.endpoint-byte-profile')
        return ProviderFactReference(artifact, '#'), data

    read_profile, read_bytes = profile('READ', 8)
    write_profile, write_bytes = profile('WRITE_REQUEST', 8)
    flush_written = details['written'] if 'save' in details['called_stages'] else 0
    actual_profile, actual_bytes = profile('WRITE_ACTUAL', flush_written)
    profile_payloads = {ref.artifact.sha256: data for ref, data in (
        (read_profile, read_bytes), (write_profile, write_bytes), (actual_profile, actual_bytes))}

    graph = ValueGraph()
    versions, mats, regions = {}, {}, {}
    previous = None
    for label in ('file', 'raw', 'normalized', 'computed', 'serialized'):
        logical = LogicalValueID('io.' + label)
        version = ValueVersionID(logical, 0)
        provenance = ProvenanceID('io.' + label)
        parents = () if previous is None else (previous,)
        graph.add_logical_value(LogicalValue(logical, 'bytes'))
        graph.add_version(ValueVersion(version, provenance, parents))
        graph.add_provenance(ProvenanceRecord(provenance,
            ProvenanceRelation.ORIGIN if previous is None else ProvenanceRelation.TRANSFORM,
            parents, (version,), evidence='Declared; no automatic native provenance'))
        versions[label] = version
        previous = version
    empty = LogicalValueID('io.empty-buffer')
    versions['empty'] = ValueVersionID(empty, 0)
    graph.add_logical_value(LogicalValue(empty, 'bytes'))
    graph.add_version(ValueVersion(versions['empty']))
    for label, logical, device in (
        ('file', 'file', 'storage'), ('raw', 'raw', 'cpu'),
        ('normalized.cpu', 'normalized', 'cpu'), ('normalized.gpu', 'normalized', 'cuda:0'),
        ('computed.gpu', 'computed', 'cuda:0'), ('computed.cpu', 'computed', 'cpu'),
        ('serialized', 'serialized', 'cpu'), ('buffer', 'serialized', 'cpu'), ('buffer.empty', 'empty', 'cpu'),
        ('endpoint', 'serialized', 'storage')):
        mat = MaterializationID('io.' + label)
        region = None
        if device != 'storage':
            allocation = StorageAllocationID('io.' + label)
            region = StorageRegionID('io.' + label)
            graph.add_allocation(StorageAllocation(allocation, device, 8))
            graph.add_region(StorageRegion(region, allocation, 0, (0 if label == 'buffer.empty' else 8,), (1,), 'uint8', device))
            regions[label] = region
        graph.add_materialization(Materialization(mat, versions[logical], 'linear bytes', device, region,
            evidence='Declared; device placement is not an observed transfer'))
        mats[label] = mat
    artifact = external_artifact(graph, 'memory:io-values')
    mat = {name: MaterializationRef(artifact, identity) for name, identity in mats.items()}
    region = {name: RegionRef(artifact, identity) for name, identity in regions.items()}
    buffer_current = 'buffer' if 'save' in details['called_stages'] else 'buffer.empty'

    resource_specs = {
        'input': (ResourceKind.FILE, ResourceRole.FILE_ENTITY),
        'output': (ResourceKind.FILE, ResourceRole.FILE_ENTITY),
        'cpu': (ResourceKind.MEMORY, ResourceRole.MEMORY_POOL),
        'gpu': (ResourceKind.GPU, ResourceRole.EXECUTOR),
        'queue': (ResourceKind.STREAM, ResourceRole.QUEUE),
    }
    resources = []
    resource_definitions = {}
    instances = tuple(ResourceInstance(ResourceInstanceID('io.' + name), kind, role,
        ProcessRealm(model.processes[0].id), ImportedAt(point), source)
        for name, (kind, role) in resource_specs.items())
    target = {name: InstanceTarget(row.id) for name, row in zip(resource_specs, instances, strict=True)}
    requirements, uses, realizations, bindings, handles, accesses = [], [], [], [], [], []
    access_ids = {}
    selected = []
    for stage in details['called_stages']:
        names = details['stages'][stage]['primitives']
        selected.extend((occurrence(stage, name), 'input' if stage == 'load' else 'cpu', name == 'write')
                        for name in names if names[name] in occurrences)
    selected.extend((occurrence('close', name), 'cpu' if name == 'buffer_read' else 'output', name != 'buffer_read')
                    for name in ('buffer_read', 'flush', 'close'))
    for stage, name in (('prepare', 'materialize'), ('run', 'submit')):
        if stage in details['called_stages']:
            selected.extend(((occurrence(stage, name), 'gpu', False), (occurrence(stage, name), 'queue', False)))
    for number, (row, resource, receiver) in enumerate(selected):
        spec = resource_specs[resource]
        requirement = ResourceRequirement(ResourceRequirementID(f'io.use.{number}'), row.operation, *spec)
        original = operations[row.operation]
        operand = original.uses[1 if receiver else 0]
        implicit = resource in ('gpu', 'queue')
        requirements.append(requirement)
        activation = next(activation for owner, (activation, _, ops) in details['by_region'].items()
                          if row.operation in ops)
        owner = next(owner for owner, (activation_, _, ops) in details['by_region'].items()
                     if activation_ == activation)
        definition_key = owner, resource
        definition = resource_definitions.get(definition_key)
        if definition is None:
            definition = ResourceDefinitionID(f'io.{owner.value}.{resource}')
            resource_definitions[definition_key] = definition
            resources.append(ResourceDefinition(definition, *spec, ExternalResource(owner, resource)))
            realizations.append(ResourceRealization(RealizationID(f'io.realization.{number}'),
                definition, activation, target[resource], source))
        uses.append(ResourceUse(row.operation, requirement.id, definition,
                                None if implicit else operand.id))
        binding = ResourceBindingID(f'io.binding.{number}')
        bindings.append(RequirementBinding(binding, requirement.id, row.id, target[resource], source))
        if implicit:
            handle = ImplicitBinding(ProviderFactReference(model.snapshot.artifact, '#declared-' + resource), support(row))
        else:
            handle_id = HandleBindingID(f'io.handle.{number}')
            endpoint = UnresolvedHandle(dynamic[row.id, operand.id].value, unknown)
            end = EndedAt(OccurrencePoint(row.id, OccurrencePhase.AFTER), source) if row.operation == OperationID('io.close.close') else unknown
            handles.append(HandleBinding(handle_id, endpoint, target[resource],
                OccurrencePoint(row.id, OccurrencePhase.BEFORE), end, support(row), unknown, unknown, source))
            handle = ExplicitHandle(handle_id)
        identity = ResourceAccessID(f'io.access.{number}')
        accesses.append(ResourceAccessBinding(identity, row.id, binding, handle, support(row), (), source))
        access_ids[row.operation, resource] = identity
    # Static interfaces are not shrunk to the selected observed control path.
    for stage in ('load', 'prepare', 'run', 'save'):
        owner = details['stages'][stage]['region']
        for name, operation_id in details['stages'][stage]['primitives'].items():
            if operation_id in occurrences:
                continue
            selected_resources = ['input' if stage == 'load' else 'cpu']
            if (stage, name) in (('prepare', 'materialize'), ('run', 'submit')):
                selected_resources += ['gpu', 'queue']
            for resource in selected_resources:
                spec = resource_specs[resource]
                definition = resource_definitions.get((owner, resource))
                if definition is None:
                    definition = ResourceDefinitionID(f'io.{owner.value}.{resource}')
                    resource_definitions[owner, resource] = definition
                    resources.append(ResourceDefinition(definition, *spec, ExternalResource(owner, resource)))
                requirement = ResourceRequirement(ResourceRequirementID(f'io.unobserved.{stage}.{name}.{resource}'),
                                                  operation_id, *spec)
                requirements.append(requirement)
                original = operations[operation_id]
                operand = original.uses[1 if resource == 'output' or name == 'write' else 0]
                uses.append(ResourceUse(operation_id, requirement.id, definition,
                                        None if resource in ('gpu', 'queue') else operand.id))
    endpoint_requirement = ResourceRequirement(ResourceRequirementID('io.required.output'), program.root,
                                               ResourceKind.FILE, ResourceRole.FILE_ENTITY)
    requirements.append(endpoint_requirement)
    root_activation = details['by_region'][program.root][0]
    endpoint_binding = RequirementBinding(ResourceBindingID('io.required.output'), endpoint_requirement.id,
                                         root_activation, target['output'], source)
    bindings.append(endpoint_binding)
    program = replace(program, resources=tuple(resources), resource_requirements=tuple(requirements), resource_uses=tuple(uses))
    model = replace(model, snapshot=snapshot_for(program), resources=instances, realizations=tuple(realizations),
                    requirements=tuple(bindings), handles=tuple(handles), accesses=tuple(accesses))

    # Independent source rows remain even if downstream write/result links are removed.
    write_stages = [(stage, name, placement) for stage, name, placement in (
        ('load', 'read', 'raw'), ('prepare', 'represent', 'normalized.cpu'),
        ('prepare', 'materialize', 'normalized.gpu'), ('run', 'submit', 'computed.gpu'),
        ('run', 'consume', 'computed.cpu'), ('save', 'serialize', 'serialized'),
        ('save', 'write', 'buffer'), ('close', 'flush', 'endpoint'))
        if stage in (*details['called_stages'], 'close')
        and details['stages'][stage]['primitives'][name] in occurrences
        and not (stage == 'close' and buffer_current == 'buffer.empty')]
    raw_rows = []
    for number, (stage, name, placement) in enumerate(write_stages):
        metadata = {'process_id': 10, 'thread_id': 11}
        if details['pending'] and stage == 'run' and name == 'submit':
            metadata['enqueue'] = True
        else:
            metadata['scar_native_result'] = {'schema': 'scar.native.byte-prefix-write', 'schema_version': 1,
                'stage': f'{stage}.{name}', 'requested_bytes': 8,
                'written_bytes': flush_written if placement == 'endpoint' else 8}
        raw_rows.append({'kind': 'python_c_call', 'invocation_id': number + 1, 'code_id': f'pipeline.primitive.{number}',
            'ts_ns': number * 10, 'duration_ns': 1, 'inputs': [], 'outputs': [], 'metadata': metadata})
    lines = [(json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n').encode() for row in raw_rows]
    manifest, normal_index, payloads = build_inventory({'pipeline': b''.join(lines)})
    payloads.update(profile_payloads)
    inventory = EvidenceInventoryBinding(EvidenceInventoryID('io.source'), model.runs[0].id, manifest, normal_index, source)
    raw_artifact = ProviderArtifact('inventory:pipeline:raw', sha256(b''.join(lines)).hexdigest(),
                                    sum(map(len, lines)), 'scar.trace.raw-jsonl')
    stages = {pair[:2]: (RawRecordRef(InventorySourceRef(inventory.id, 'pipeline'), index + 1,
        sha256(lines[index]).hexdigest()), ProviderFactReference(raw_artifact,
        f'#L{index + 1}/metadata/scar_native_result')) for index, pair in enumerate(write_stages)}

    submissions, outcomes, quiescences, retentions, prefixes = [], [], [], [], []
    work_ids = {}
    previous = QueueStart(source)
    for stage, name, source_mat, destination_mat in (
        ('prepare', 'materialize', 'normalized.cpu', 'normalized.gpu'),
        ('run', 'submit', 'normalized.gpu', 'computed.gpu')):
        if stage not in details['called_stages']:
            continue
        row = occurrence(stage, name)
        wait = occurrences.get(details['stages'][stage]['primitives']['wait'])
        ticket = WorkTicketID('io.' + stage)
        work_ids[stage, name] = ticket
        prefix = QueuePrefixID('io.' + stage)
        origin = WithinOperation(row.id, source)
        rule = ProviderFactReference(model.snapshot.artifact, '#declared-queue-fifo')
        prefixes.append(QueuePrefix(prefix, ResourceInstanceID('io.queue'), previous, ticket,
                                    OccurrencePoint(row.id, OccurrencePhase.AFTER), rule, source))
        previous = prefix
        retention = WorkRetentionID('io.' + stage)
        quiet = WorkQuiescenceID('io.' + stage)
        pending = (details['pending'] and stage == 'run') or wait is None
        complete_at = None if wait is None else OccurrencePoint(wait.id, OccurrencePhase.AFTER)
        retentions.append(WorkRetention(retention, ticket, mat[source_mat], mat[source_mat], origin,
            support(row), ReleaseAuthority.BORROWED, Sharing.SHARED,
            unknown if pending else BorrowRelease(complete_at, quiet, source), source))
        effect = AccessRef(row.id, 0)
        submissions.append(WorkSubmission(ticket, origin, access_ids[row.operation, 'gpu'],
            Queued(access_ids[row.operation, 'queue'], prefix), (), Completeness.UNKNOWN,
            (effect,), Completeness.PARTIAL, (mat[source_mat], mat[destination_mat]), Completeness.COMPLETE,
            (retention,), rule, source))
        if not pending:
            quiescences.append(WorkQuiescence(quiet, ticket, complete_at, source))
            outcomes.append(ResourceOutcome(WorkOutcomeID('io.' + stage), ticket, WorkOutcomeKind.COMPLETED,
                complete_at, stages[stage, name][1], (effect,), Completeness.PARTIAL, quiet, source))
    profiles = (() if not prefixes else (QueueOrderProfile(QueueOrderProfileID('io.queue'),
        ResourceInstanceID('io.queue'), prefixes[-1].id,
        ProviderFactReference(model.snapshot.artifact, '#declared-queue-fifo'), source),))

    writes, produced, established = [], [], []
    for stage, name, placement in write_stages:
        row = occurrence(stage, name)
        ticket = work_ids.get((stage, name))
        selected = EndpointContent(mat[placement], target['output'], ProtocolSelector(write_profile)) if placement == 'endpoint' else StorageContent(mat[placement], region[placement])
        write = WriteAssociation(WriteAssociationID('io.' + stage + '.' + name), stages[stage, name][0],
            WorkWrite(ticket) if ticket is not None else HostWrite(row.id), StateProduction(AccessRef(row.id, 0)),
            selected, (), source)
        writes.append(write)
        actual = ProtocolSelector(actual_profile) if placement == 'endpoint' else region[placement]
        if ticket is None:
            established.append(EstablishedProduction(EstablishedProductionID(write.id.value), write.id,
                OccurrencePoint(row.id, OccurrencePhase.AFTER), actual, stages[stage, name][1], BytePrefixWrite(), source))
        elif not (details['pending'] and stage == 'run'):
            produced.append(OutcomeProduction(OutcomeProductionID(write.id.value), write.id,
                WorkOutcomeID('io.' + stage), 0, actual, BytePrefixWrite(), source))

    reads, denotations, supports = [], [], []
    read_specs = [('load', 'read', 'file'), ('prepare', 'represent', 'raw'),
        ('prepare', 'materialize', 'normalized.cpu'), ('run', 'submit', 'normalized.gpu'),
        ('run', 'consume', 'computed.gpu'), ('save', 'serialize', 'computed.cpu'),
        ('save', 'write', 'serialized'), ('close', 'buffer_read', 'buffer'),
        ('close', 'flush', 'buffer')]
    writer_by_placement = {placement: next(write for write in writes if write.id.value == f'io.{stage}.{name}')
                           for stage, name, placement in write_stages}
    for stage, name, placement in read_specs:
        if (stage not in (*details['called_stages'], 'close') or
                details['stages'][stage]['primitives'][name] not in occurrences):
            continue
        if stage == 'close' and placement == 'buffer':
            placement = buffer_current
        row = occurrence(stage, name)
        use = operations[row.operation].uses[0]
        subject = UseRef(row.id, use.id)
        anchor = OccurrencePoint(row.id, OccurrencePhase.BEFORE)
        interval = ProtocolInterval(anchor, replace(anchor, phase=OccurrencePhase.AFTER), read_profile, source)
        ticket = work_ids.get((stage, name))
        consumer = (ResourceConsumer(subject, WholeWorkRead(ticket), unknown) if ticket is not None
                    else HostConsumer(subject, interval))
        read = ContentRead(ContentReadID('io.' + stage + '.' + name),
            consumer, EndpointContent(mat['file'], target['input'], ProtocolSelector(read_profile))
            if placement == 'file' else StorageContent(mat[placement], region[placement]),
            unknown if type(definitions[use.value]) is ReferenceValue else None,
            anchor, support(row), unknown, source)
        reads.append(read)
        if (stage, name) in (('save', 'write'), ('close', 'flush')):
            denotations.append(ValueDenotation(DenotationID('io.' + stage + '.bytes'), dynamic[row.id, use.id].value,
                DataIdentity(VersionRef(artifact, graph.materializations[mats[placement]].value_version)), unknown, source))
        original_write = writer_by_placement.get(placement)
        if original_write is not None:
            production = next((item for item in (*established, *produced) if item.write == original_write.id), None)
            writer_row = occurrence(*next((stage_, name_) for stage_, name_, placed in write_stages if placed == placement))
            at = (OccurrencePoint(occurrence('run', 'wait').id, OccurrencePhase.AFTER)
                  if placement == 'computed.gpu' else
                  OccurrencePoint(occurrence('prepare', 'wait').id, OccurrencePhase.AFTER)
                  if placement == 'normalized.gpu' else OccurrencePoint(writer_row.id, OccurrencePhase.AFTER))
            visibility = (OrderedVisibility(read_profile) if production is None else
                CompletedVisibility(at, AccessRef(writer_row.id, 0),
                    QueueDomain(ResourceInstanceID('io.queue')) if ticket is not None else HostDomain(model.threads[0].id), read_profile))
            supports.append(ContributionSupport(ContributionSupportID(read.id.value), read.id, original_write.id,
                None if production is None else production.id, visibility, source))

    semantic = SemanticGraph()
    output, contract = ValueSlotID('io.result'), ContractID('io.required')
    semantic.add_slot(ValueSlot(output, 'result', 'output'))
    semantic.add_contract(ContractDefinition(contract, 'result and output bytes', (output,),
        (FacetRequirement(ContractFacet.EXTERNAL, True),)))
    semantic_artifact = external_artifact(semantic, 'memory:io-contract')
    contract_ref = ContractRef(semantic_artifact, contract)
    requirement = ObservationRequirement(ObservationRequirementID('io.bytes'), contract_ref,
        RequiredEndpoint(endpoint_requirement.id, ContractFacet.EXTERNAL), read_profile, source)
    result_requirement = ObservationRequirement(ObservationRequirementID('io.result'), contract_ref,
        RequiredOutput(output), read_profile, source)
    terminal = details['main_raise'] if details['raise_final'] else details['main_return']
    terminal_row = next(row for row in model.operations if row.id == terminal)
    terminal_op = next(row for row in program.operations if row.id == terminal_row.operation)
    observed_at = occurrence('close', 'flush') if details['early_observation'] else terminal_row
    anchor = OccurrencePoint(observed_at.id, OccurrencePhase.BEFORE)
    interval = ProtocolInterval(anchor, replace(anchor, phase=OccurrencePhase.AFTER), read_profile, source)
    endpoint_root = ObservationRoot(ObservationRootID('io.bytes'), requirement.id, BoundEndpoint(endpoint_binding.id),
        interval, anchor, support(observed_at), source)
    roots = [endpoint_root]
    if not details['raise_final']:
        payload = dynamic[terminal, terminal_op.terminator.values[0]].value
        roots.append(ObservationRoot(ObservationRootID('io.result'), result_requirement.id, OutputValue(payload),
            interval, anchor, support(observed_at), source))
    if details['include_endpoint_read']:
        read = ContentRead(ContentReadID('io.endpoint'), ObservationConsumer(endpoint_root.id),
            EndpointContent(mat['endpoint'], target['output'], ProtocolSelector(read_profile)), None,
            anchor, support(observed_at), unknown, source)
        reads.append(read)
        writer = next((row for row in writes if row.id.value == 'io.close.flush'), None)
        if writer is not None and not details['early_observation']:
            row = occurrence('close', 'flush')
            production = next(row for row in established if row.write == writer.id)
            supports.append(ContributionSupport(ContributionSupportID('io.endpoint'), read.id, writer.id, production.id,
                CompletedVisibility(OccurrencePoint(row.id, OccurrencePhase.AFTER), AccessRef(row.id, 0),
                    # Endpoint read/visibility protocol must agree exactly.
                    EndpointDomain(target['output']),
                    read_profile), source))
    if not details['include_flush_production']:
        missing = WriteAssociationID('io.close.flush')
        writes = [row for row in writes if row.id != missing]
        established = [row for row in established if row.write != missing]
        supports = [row for row in supports if row.write != missing]
    model = replace(model, submissions=tuple(submissions), outcomes=tuple(outcomes), quiescences=tuple(quiescences),
        retentions=tuple(retentions), queue_prefixes=tuple(prefixes), queue_order_profiles=profiles,
        source_inventories=(inventory,), writes=tuple(writes), produced=tuple(produced),
        established_productions=tuple(established), content_reads=tuple(reads), denotations=tuple(denotations),
        contribution_supports=tuple(supports), observation_requirements=(result_requirement, requirement),
        observation_roots=tuple(roots))
    catalogs = {'value_graphs': {artifact.sha256: graph}, 'semantic_graphs': {semantic_artifact.sha256: semantic},
                'artifact_bytes': payloads}
    details.update(contract=contract_ref, mats=mat, regions=region, versions=versions,
        endpoint_read=ContentReadID('io.endpoint'), source_read=ContentReadID('io.close.flush'),
        output_target=target['output'], read_profile=read_profile, work_ids=work_ids,
        buffer_current=mat[buffer_current])
    return program, model, catalogs, details
