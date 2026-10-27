"""Resolve an original canonical native input to an existing allocation epoch.

Logical contents, write versions and materialization are deliberately distinct.
No graph, value ID, handle lifetime or logical version is created by this view.
"""
from __future__ import annotations

from pathlib import Path
import re
import gzip
from hashlib import sha256
from io import BytesIO

from scar.analysis.tensor_storage_index import TensorStorageReferenceIndex, _scope
from scar.analysis.tensor_storage_query import _Meter, _json, _need, _stamp
from scar.ir.execution.codec import loads as load_execution
from scar.ir.execution.content import NativeInputRef
from scar.ir.execution.coordinates import InitialEntry
from scar.ir.execution.ids import ValueOccurrenceID
from scar.ir.execution.resources import AllocationTarget
from scar.ir.program.codec import loads as load_program
from scar.ir.program.model import TerminatorKind
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import decode, encode
from scar.ir.v2.ids import StorageAllocationID
from scar.ir.v2.values import StorageAllocation
from scar.trace.native_import import _canonical_hash
from scar.trace.native_input_index import (NAVIGATION_PROFILE, _query_regular_bytes,
                                          query_native_input_associations)
from scar.trace.native_tensor_inputs import _json as strict_json


def _association(artifact, meter, row, path, native_input=None, execution=None):
    doc = _json(artifact, meter)
    _need(doc.get('schema') == 'scar.native-input-port-navigation',
          'canonical parent navigation required, not an unqualified association dump')
    chunks = [c for c in doc['tables']['associations']['chunks']
              if row is None or c['first_row'] <= row <= c['last_row']]
    if native_input is not None:
        _need(type(doc.get('schema_version')) is int and doc['schema_version'] == 1
              and doc['profile'] == NAVIGATION_PROFILE and doc['status'] == 'PUBLISHED_WITH_OPEN',
              'unsupported canonical input navigation')
        # This is bounded reference selection, not restored producer ownership.
        # The selected endpoint is checked against ordinary IR below. A row
        # hint restricts chunks; otherwise stop at the first exact scoped hit.
        for chunk in chunks:
            _need(type(chunk['raw_bytes']) is int and 0 <= chunk['raw_bytes'] <= 8_000_000,
                  'navigation chunk decoded ceiling differs')
            relative = Path(chunk['path'])
            root = Path(artifact.uri).parent
            _need(not relative.is_absolute() and '..' not in relative.parts, 'navigation chunk escapes root')
            p = root / relative
            _need(p.resolve().is_relative_to(root), 'navigation chunk escapes original namespace')
            meter.charge(stored=chunk['size_bytes'], decoded=chunk['raw_bytes'])
            stored = _query_regular_bytes(p, 8_100_000)
            _need(len(stored) == chunk['size_bytes'] and sha256(stored).hexdigest() == chunk['sha256'],
                  'original navigation chunk stored receipt differs')
            with gzip.GzipFile(fileobj=BytesIO(stored)) as stream:
                raw = stream.read(chunk['raw_bytes'] + 1)
            _need(len(raw) == chunk['raw_bytes'] and sha256(raw).hexdigest() == chunk['raw_sha256'],
                  'original navigation chunk decoded receipt differs')
            meter.inputs.append((p, _stamp(p)))
            matches = [value for value in map(strict_json, raw.splitlines())
                       if value['native_input'] == encode(native_input)
                       and value['canonical_parent']['execution'] == encode(execution)
                       and (row is None or value['row'] == row)
                       and (path is None or value['path'] == list(path))]
            _need(len(matches) <= 1, 'ambiguous qualified native input in navigation chunk')
            if matches:
                return doc, matches[0]
        raise LookupError('qualified native input is absent from the bounded navigation')
    if row is None:
        chunks = chunks[:1]
    # Charge the ordinary reader's repeated metadata and full selected chunks
    # before calling it. No raw trace or private locator database is opened.
    meter.charge(stored=artifact.size_bytes + sum(c['size_bytes'] for c in chunks),
                 decoded=artifact.size_bytes + sum(c['raw_bytes'] for c in chunks))
    result = query_native_input_associations(artifact.uri, expected_sha256=artifact.sha256,
        row=row, associations=True, limit=1 if row is None else 1000)
    matches = result['matches']
    if path is not None:
        matches = [r for r in matches if r['path'] == list(path)]
    _need(len(matches) == 1, 'native input selector is absent or ambiguous; specify row and original path')
    for c in chunks:
        p = Path(artifact.uri).parent / c['path']
        meter.inputs.append((p, _stamp(p)))
    return doc, matches[0]


def _canonical_input(association, meter, owned_execution=None):
    parent = association['canonical_parent']
    execution_artifact = decode(ProviderArtifact, parent['execution'])
    program_artifact = decode(ProviderArtifact, parent['program_snapshot']['artifact'])
    execution_raw = (meter.artifact(execution_artifact, 32_000_000)
                     if owned_execution is None else b'')
    program_raw = meter.artifact(program_artifact, 32_000_000)
    meter.charge(decoded=len(execution_raw) + len(program_raw))
    execution = (load_execution(execution_raw.decode('utf8'))
                 if owned_execution is None else owned_execution)
    program = load_program(program_raw.decode('utf8'))
    _need(encode(execution.snapshot) == parent['program_snapshot'], 'original ProgramSnapshot differs')
    denotations = [r for r in execution.denotations if encode(r.id) == parent['denotation']]
    _need(len(denotations) == 1, 'original input has no unique denotation')
    denotation = denotations[0]
    _need(type(denotation.basis) is NativeInputRef
          and encode(denotation.basis) == association['native_input']
          and encode(denotation.value) == association['value_occurrence']
          and encode(denotation.source) == association['original_input'],
          'original native input/denotation/source differs')
    bindings = [r for r in execution.evidence_bindings
                if encode(r.legacy) == association['native_producer']['instance']
                and encode(r.source) == association['native_producer']['source']]
    _need(len(bindings) == 1, 'native input original producer binding differs')
    occurrences = [r for r in execution.operations if r.id == bindings[0].operation
                   and r.visit == denotation.basis.entry]
    _need(len(occurrences) == 1, 'native input actual invoke occurrence differs')
    operations = [r for r in program.operations if r.id == occurrences[0].operation]
    _need(len(operations) == 1 and operations[0].terminator is not None
          and operations[0].terminator.kind is TerminatorKind.INVOKE, 'native input is not an actual invoke port')
    operation = operations[0]
    boundaries = [b for b in program.native_boundaries if b.id == denotation.basis.boundary]
    _need(len(boundaries) == 1 and denotation.basis.position < len(boundaries[0].inputs),
          'native input signature slot is absent from the original boundary')
    boundary = boundaries[0]
    port = boundary.inputs[denotation.basis.position].port
    regions = [r for r in program.regions if r.id == port.region]
    visits = [v for v in execution.visits if v.id == denotation.basis.entry]
    _need(len(regions) == len(visits) == 1 and visits[0].block == regions[0].entry
          and any(operation.id in b.operations for b in regions[0].blocks),
          'native input visit/invoke is outside its exact entry region')
    segments = [s for s in execution.segments if s.id == visits[0].segment]
    _need(len(segments) == 1 and type(segments[0].ingress) is InitialEntry,
          'native input is not an original initial entry')
    _need(sum(a.id == segments[0].activation and a.region == port.region
              for a in execution.activations) == 1,
          'native input activation and original boundary region differ')
    # Native signature order need not be physical core Use order.
    arguments = [u for u in operation.uses if u.id in operation.invoke_arguments
                 and u.value == port.value]
    _need(len(arguments) == 1, 'native input has no unique original invoke argument')
    actual_use = arguments[0]
    uses = [r for r in execution.uses if r.operation == occurrences[0].id
            and r.use == actual_use.id and r.value == denotation.value]
    values = [r for r in execution.values if r.id == denotation.value and r.origin == denotation.basis.entry]
    _need(len(uses) == len(values) == 1 and values[0].value == actual_use.value,
          'native input actual ValueOccurrence/Use/value origin differs')
    return execution, operation, occurrences[0], denotation, uses[0], boundary


def query_native_input_allocation(navigation: ProviderArtifact, storage_index: ProviderArtifact, *,
        native_input: NativeInputRef | None = None, value_occurrence: ValueOccurrenceID | None = None,
        execution: ProviderArtifact | None = None, row: int | None = None,
        path: tuple[int, ...] | None = None, max_input_bytes=256_000_000, max_seconds=60):
    """Same-profiler input metadata -> original scoped allocation, not contents.

    Without a selector, use the first ordinary canonical navigation record.
    A path selector requires its original row; no file/function-name rules or
    nearest-time/bare-pointer matching is used. An unavailable epoch remains a
    hard explicit boundary rather than a fabricated allocation or version.
    """
    _need(type(navigation) is type(storage_index) is ProviderArtifact, 'typed original artifact receipts required')
    navigation.__post_init__(); storage_index.__post_init__()
    _need(navigation.schema == 'scar.native-input-port-navigation'
          and storage_index.schema == 'scar.tensor-storage-locator-index', 'original artifact schemas differ')
    _need(row is None or (type(row) is int and row >= 0), 'exact nonnegative native row required')
    _need(path is None or (row is not None and type(path) is tuple
          and all(type(i) is int and i >= 0 for i in path)), 'path requires a row and exact ordered integer tuple')
    meter = _Meter(max_input_bytes, max_seconds)
    _need(native_input is None or type(native_input) is NativeInputRef, 'typed original NativeInputRef required')
    _need(value_occurrence is None or type(value_occurrence) is ValueOccurrenceID,
          'typed original ValueOccurrenceID required')
    selected = native_input is not None or value_occurrence is not None
    _need((selected and type(execution) is ProviderArtifact) or (not selected and execution is None),
          'native input/value occurrence selectors require their exact execution artifact')
    owned = None
    if selected:
        execution.__post_init__()
        raw = meter.artifact(execution, 32_000_000); meter.charge(decoded=len(raw))
        owned = load_execution(raw.decode('utf8'))
        candidates = [d for d in owned.denotations if type(d.basis) is NativeInputRef
                      and (native_input is None or d.basis == native_input)
                      and (value_occurrence is None or d.value == value_occurrence)]
        _need(len(candidates) == 1, 'qualified input/occurrence has no unique actual native denotation')
        native_input = candidates[0].basis
    nav, association = _association(navigation, meter, row, path, native_input, execution)
    execution, operation, occurrence, denotation, use, boundary = _canonical_input(association, meter, owned)
    index = TensorStorageReferenceIndex(storage_index, meter)
    capture, coordinates, coordinate_artifact, process, pid = _scope(
        decode(ProviderArtifact, index.document['capture_model']), meter)
    _need(nav['run'] == capture['run']['id'] and nav['process'] == process == index.document['process']
          and index.document['run'] == capture['run']
          and encode(coordinate_artifact) == index.document['coordinates'], 'input and storage Run/process/coordinate scopes differ')
    _need(any(encode(r.id) == nav['run'] for r in execution.runs)
          and any(encode(r.id) == process and r.pid == pid for r in execution.processes),
          'canonical input execution is outside the original storage process')
    _need(association['native_producer']['source']['artifact'] == index.document['eto_source'],
          'native input and allocation source have different original ETO namespaces')
    bundle = decode(ProviderArtifact, index.document['bundle'])
    _need(any(r['path'] == bundle.uri and r['stored_sha256'] == bundle.sha256
              and r['stored_bytes'] == bundle.size_bytes for r in capture['outputs']),
          'allocation bundle is outside the exact capture model')
    metadata, epoch = association['metadata'], association['provider_epoch']
    _need(metadata['status'] == 'OBSERVED' and metadata['physical_epoch_reference_observed'] is True
          and not metadata['gaps'] and epoch['status'] == 'OBSERVED_PROVIDER_EPOCH_REFERENCE'
          and epoch['device'] == metadata['device']['text']
          and type(epoch['provider_allocation_id']) is int and epoch['provider_allocation_id'] > 0
          and epoch['provider_allocation_id'] == metadata['provider_allocation_id'],
          'actual native input has no exact observed provider allocation epoch')
    physical = capture['native']['tensor_physical']
    _need(epoch['source']['artifact'] == physical['artifacts']['observations'],
          'native input epoch birth is not this capture physical provider source')
    match = re.fullmatch(r'#/lines/([1-9][0-9]*)', epoch['source']['locator'])
    _need(match is not None, 'provider birth lacks its exact original line')
    # This is the existing importer's lookup recipe, not a minted record. The
    # original allocation must exist and independently satisfy every field.
    identity = StorageAllocationID(physical['scope'] + ':epoch:' +
        _canonical_hash((epoch['device'], epoch['provider_allocation_id'])))
    raw, source = index.record('values', 'allocations', identity.wire)
    allocation = decode(StorageAllocation, raw)
    expected_birth = 'sha256:' + epoch['source']['artifact']['sha256'] + '#line/' + match[1]
    _need(allocation.id == identity and allocation.device == epoch['device']
          and allocation.lifetime_scope == physical['scope']
          and allocation.metadata['provider_allocation_id'] == epoch['provider_allocation_id']
          and allocation.metadata['birth_reference'] == expected_birth
          and expected_birth in allocation.metadata['allocation_receipts']
          and allocation.metadata['address'] == metadata['storage_data_ptr'],
          'original allocation contradicts the actual native input epoch/birth/address')
    target = AllocationTarget(source.artifact, allocation.id)
    return {'schema': 'scar.native-input-allocation-query', 'schema_version': 1,
        'qualification': 'RETAINED_EXACT_NATIVE_INPUT_PROVIDER_EPOCH_ALLOCATION',
        'run': nav['run'], 'process': process, 'capture_model': index.document['capture_model'],
        'navigation': encode(navigation), 'storage_index': encode(storage_index),
        'selector': {'row': association['row'], 'path': association['path']},
        'canonical_parent': association['canonical_parent'], 'value_occurrence': association['value_occurrence'],
        'native_input': association['native_input'], 'operation_occurrence': encode(occurrence),
        'native_operation': {'label': operation.label, 'boundary': encode(boundary.id),
            'signature': encode(boundary.signature), 'producer': association['native_producer']},
        'actual_use_occurrence': encode(use), 'original_denotation': encode(denotation),
        'original_input': association['original_input'], 'metadata_source': association['metadata_source'],
        'observed_metadata': metadata, 'provider_epoch': epoch,
        'allocation_target': encode(target), 'allocation': raw, 'allocation_source': encode(source),
        'original_state_interface': {'operation': encode(operation.id), 'accesses': encode(operation.accesses),
            'completions': encode(operation.completions), 'effects_complete': operation.effects_complete},
        'scope': 'exact observed input allocation only; no lifetime extent, region/range, object/content/version or actual state-write upgrade',
        'python_identity_established': False, 'logical_version_established': False,
        'materialization': None, 'actual_state_write_established': False, 'resource_ready_established': False,
        'new_graph_nodes': 0, 'producer_inputs_replayed': False, 'whole_program_complete': False,
        'measurements': meter.finish()}
