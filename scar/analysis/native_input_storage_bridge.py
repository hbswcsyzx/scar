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
from scar.analysis.native_port_geometry import (
    NativeTensorPortGeometry, connect_observed_input_region,
)
from scar.ir.execution.codec import loads as load_execution
from scar.ir.execution.content import NativeInputRef
from scar.ir.execution.coordinates import InitialEntry
from scar.ir.execution.ids import ValueOccurrenceID
from scar.ir.execution.resources import AllocationTarget
from scar.ir.program.codec import loads as load_program
from scar.ir.program.model import TerminatorKind
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.provenance import _WIDTHS
from scar.ir.record_codec import decode, encode
from scar.ir.v2.ids import StorageAllocationID, StorageRegionID
from scar.ir.v2.values import StorageAllocation, StorageRegion
from scar.ir.v2._validation import record_errors
from scar.trace.native_import import _canonical_hash
from scar.trace.native_input_index import (NAVIGATION_PROFILE, _query_regular_bytes,
                                          query_native_input_associations)
from scar.trace.native_tensor_inputs import _json as strict_json


_REGION_PROTOCOL = 'PINNED_TORCH_VALID_STRIDED_ALLOCATION_BOUNDS_V1'


def _unique_region(association, allocation):
    """A static implication over exact inputs; never an observed offset.

    A valid nonempty strided Tensor addresses elements inside its allocation.
    If its bounding span exhausts that allocation, no offset other than zero
    can satisfy the bound. Empty/partial/unsupported geometry stays explicit.
    """
    metadata = association['metadata']
    result = {'protocol': _REGION_PROTOCOL, 'status': 'OPEN', 'region': None,
        'offset_observed': False, 'observed_storage_offset': metadata['storage_offset'],
        'original_storage_offset_gap': metadata['storage_offset_gap'],
        'basis': 'static protocol implication over original input metadata and allocation; not a new runtime observation',
        'assumptions': ['valid Tensor at the original input observation',
            'nonempty strided element addressing stays within this exact allocation epoch'],
        'source': {'metadata': association['metadata_source'], 'epoch_birth': association['provider_epoch']['source']},
        'record_is_stored': False, 'content_or_readiness_established': False}
    dtype, shape, strides = metadata['dtype'], metadata['sizes'], metadata['strides']
    width = _WIDTHS.get(dtype.removeprefix('torch.')) if type(dtype) is str and dtype.startswith('torch.') else None
    if metadata['layout'] != 'torch.strided' or width is None:
        return dict(result, reason='STRIDED_DTYPE_WIDTH_UNRESOLVED')
    if (type(shape) is not list or type(strides) is not list or len(shape) != len(strides)
            or len(shape) > 64 or any(type(n) is not int or n < 0 or n.bit_length() > 63
                                    for n in shape + strides)):
        return dict(result, reason='GEOMETRY_OUTSIDE_NONNEGATIVE_INT64_PROTOCOL')
    if 0 in shape:
        return dict(result, reason='EMPTY_TENSOR_HAS_NO_UNIQUE_OFFSET')
    if type(allocation.nbytes) is not int or allocation.nbytes <= 0:
        return dict(result, reason='ALLOCATION_EXTENT_UNRESOLVED')
    span = width * (1 + sum((n - 1) * stride for n, stride in zip(shape, strides)))
    result['constraints'] = {'element_bytes': width, 'bounding_span_bytes': span,
        'allocation_extent_bytes': allocation.nbytes, 'offset_elements_minimum': 0,
        'offset_elements_maximum': (allocation.nbytes - span) // width,
        'storage_base_matches_allocation_base': metadata['storage_data_ptr'] == allocation.metadata['address']}
    _need(span <= allocation.nbytes, 'input geometry contradicts valid Tensor allocation bounds protocol')
    if span != allocation.nbytes:
        return dict(result, reason='BOUNDING_SPAN_DOES_NOT_EXHAUST_ALLOCATION')
    _need(result['constraints']['storage_base_matches_allocation_base'], 'derived region storage base differs')
    scope = {'execution': association['canonical_parent']['execution'],
        'native_input': association['native_input'], 'metadata': association['metadata_source'],
        'allocation': encode(allocation.id), 'protocol': _REGION_PROTOCOL}
    region = StorageRegion(StorageRegionID('native-input-derived-region:' + _canonical_hash(scope)),
        allocation.id, 0, tuple(shape), tuple(strides), dtype, allocation.device)
    _need(not record_errors(region, StorageRegion, 'derived input region'), 'invalid derived StorageRegion record')
    return dict(result, status='DERIVED_UNIQUE_OFFSET_UNDER_VALID_TENSOR_PROTOCOL',
        region=encode(region), reason='NONNEGATIVE_OFFSET_AND_SATURATED_BOUND_REQUIRE_ZERO',
        derived_region_records=1)


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


def _qualified_eto_input_geometry(association, denotation, allocation_query, meter):
    """Read only the exact qualification row already referenced by navigation."""
    parent = association.get('canonical_parent', {})
    qualification = parent.get('qualification_row') if type(parent) is dict else None
    if type(qualification) is not dict:
        return None, None, 'NAVIGATION_HAS_NO_QUALIFICATION_ROW_REFERENCE'
    _need(qualification.get('representation') ==
          'derived port-qualification JSONL transport; not original ETO coordinate',
          'unsupported original qualification-row representation')
    artifact = decode(ProviderArtifact, qualification['artifact'])
    _need(artifact.schema == 'scar.native-capture-row-chunk'
          and type(qualification.get('line_1_based')) is int
          and qualification['line_1_based'] > 0,
          'navigation qualification-row receipt/coordinate differs')
    raw = meter.artifact(artifact, 8_100_000)
    meter.charge(decoded=len(raw))
    lines = raw.splitlines()
    line_no = qualification['line_1_based']
    _need(line_no <= len(lines), 'qualified input row is outside the original retained chunk')
    row = strict_json(lines[line_no - 1])
    required = {'A', 'B', 'C', 'D', 'denotation', 'direction', 'native_path', 'native_shape',
                'native_strides', 'native_tensor_tuple', 'native_type', 'position', 'sequence', 'source'}
    _need(type(row) is dict and set(row) == required and row['A'] == 'QUALIFIED_NATIVE_PORT'
          and row['direction'] == 'inputs' and row['B'] == 'QUALIFIED_HELD_OBJECT',
          'original input qualification row is not a qualified held native port')
    _need(type(denotation.basis) is NativeInputRef
          and row['denotation'] == encode(denotation)
          and row['source'] == encode(denotation.source)
          and row['native_path'] == association['path']
          and row['position'] == denotation.basis.position,
          'qualification row differs from original NativeInputRef/denotation/path')
    tensor = row['native_tensor_tuple']
    _need(type(tensor) is list and len(tensor) == 6,
          'qualified ETO Tensor tuple does not have six fields')
    qualification_source = ProviderFactReference(artifact, '#/lines/' + str(line_no))
    geometry = NativeTensorPortGeometry(
        denotation.basis, denotation.source, qualification_source, 'inputs',
        tuple(row['native_path']), row['native_type'], tensor[0], tensor[1], tensor[2],
        tensor[3], tensor[4], tensor[5], tuple(row['native_shape']), tuple(row['native_strides']))
    if not geometry.has_storage:
        return geometry, None, 'ETO_INPUT_HAS_NO_STORAGE_GEOMETRY'
    execution_artifact = decode(ProviderArtifact, parent['execution'])
    connection = connect_observed_input_region(geometry, allocation_query, execution_artifact)
    return geometry, connection, None


def query_native_input_allocation(navigation: ProviderArtifact, storage_index: ProviderArtifact, *,
        native_input: NativeInputRef | None = None, value_occurrence: ValueOccurrenceID | None = None,
        execution: ProviderArtifact | None = None, row: int | None = None,
        path: tuple[int, ...] | None = None, derive_region: bool = False,
        max_input_bytes=256_000_000, max_seconds=60):
    """Same-profiler input metadata -> original scoped allocation, not contents.

    Without a selector, use the first ordinary canonical navigation record.
    A path selector requires its original row; no file/function-name rules or
    nearest-time/bare-pointer matching is used. An unavailable epoch remains a
    hard explicit boundary rather than a fabricated allocation or version.
    derive_region opts into the versioned valid-Tensor-bounds static protocol;
    it does not turn the provider's unobserved offset into observed metadata.
    When the selected navigation row carries its original qualification-row
    receipt, this same query also returns the exact ETO input geometry and a
    StorageRegion joined to the same native input and provider allocation.
    """
    _need(type(navigation) is type(storage_index) is ProviderArtifact, 'typed original artifact receipts required')
    navigation.__post_init__(); storage_index.__post_init__()
    _need(navigation.schema == 'scar.native-input-port-navigation'
          and storage_index.schema == 'scar.tensor-storage-locator-index', 'original artifact schemas differ')
    _need(type(derive_region) is bool, 'derive_region must be an explicit boolean option')
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
    result = {'schema': 'scar.native-input-allocation-query', 'schema_version': 1,
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
        'new_graph_nodes': 0, 'producer_inputs_replayed': False, 'whole_program_complete': False}
    if derive_region:
        result['geometry'] = _unique_region(association, allocation)
        result['scope'] = ('exact observed input allocation plus explicitly conditional static geometry; '
            'no observed offset, lifetime extent, contents/version, actual state-write or readiness upgrade')
    geometry, region_connection, geometry_gap = _qualified_eto_input_geometry(
        association, denotation, result, meter)
    if geometry is None:
        result['observed_eto_geometry'] = {
            'status': 'OPEN', 'reason': geometry_gap,
            'source': association['original_input'],
        }
    else:
        result['observed_eto_geometry'] = {
            'status': 'OBSERVED_EXACT_NATIVE_INPUT_PORT_GEOMETRY',
            'source': encode(geometry.source),
            'qualification_source': encode(geometry.qualification_source),
            'direction': geometry.direction,
            'native_path': list(geometry.native_path),
            'native_type': geometry.native_type,
            'native_tensor_tuple': [geometry.tensor_id, geometry.storage_id,
                                    geometry.storage_offset, geometry.numel,
                                    geometry.itemsize, geometry.device],
            'shape': list(geometry.shape), 'strides': list(geometry.strides),
            'eto_storage_id_is_provider_epoch': False,
        }
    if region_connection is None:
        result['observed_storage_region'] = {
            'status': 'OPEN', 'reason': geometry_gap or 'STORAGE_REGION_CONNECTION_UNAVAILABLE',
            'region': None, 'contents_or_readiness_established': False,
        }
    else:
        result['observed_storage_region'] = {
            'status': 'DERIVED_FROM_EXACT_ETO_INPUT_GEOMETRY_AND_OBSERVED_PROVIDER_EPOCH',
            'region': encode(region_connection.region),
            'allocation_source': encode(region_connection.allocation_source),
            'provider_epoch_source': encode(region_connection.provider_epoch_source),
            'geometry_source': encode(region_connection.geometry.source),
            'qualification_source': encode(region_connection.geometry.qualification_source),
            'stored_as_new_ir_record': False,
            'contents_or_readiness_established': False,
        }
        result['scope'] = ('exact observed input allocation plus same-port ETO geometry-derived StorageRegion; '
            'no content/version, actual state-write or readiness claim')
    result['measurements'] = meter.finish()
    return result
