"""Strict bounded retention reader, without ETO joins or qualification tokens."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import gzip
import json
from pathlib import Path
import re

from scar.trace.tensor_physical import NATIVE_INPUT_PROFILE, PROVIDER_REVISION


def _need(condition, message):
    if not condition:
        raise ValueError("native input retention: " + message)


def _pairs(items):
    result = {}
    for key, value in items:
        _need(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _json(raw):
    def invalid(_value):
        raise ValueError("native input retention: nonfinite JSON constant")
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=invalid)


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _keys(value, names):
    _need(type(value) is dict and set(value) == set(names.split()), "unexpected fields")


def _gaps(value):
    _need(type(value) is list and all(type(x) is str for x in value), "invalid gaps")


def _path(value, expected):
    return type(value) is list and all(type(x) is int for x in value) and value == expected


def _metadata(value):
    _keys(value, "status impl_ptr storage_data_ptr provider_tensor_id provider_allocation_id device dtype layout sizes strides storage_offset physical_epoch_reference_observed storage_offset_gap gaps")
    _need(value['status'] in ('OBSERVED', 'OPEN'), "invalid metadata status")
    for key, minimum in [('impl_ptr', 0), ('storage_data_ptr', 0), ('provider_tensor_id', 0), ('provider_allocation_id', 1)]:
        _need(value[key] is None or _integer(value[key], minimum), "invalid provider metadata integer")
    for key in ('dtype', 'layout'):
        _need(value[key] is None or type(value[key]) is str, "invalid metadata type text")
    device = value['device']
    if device is not None:
        _keys(device, 'type index text')
        _need(type(device['type']) is str and type(device['text']) is str
              and (device['index'] is None or _integer(device['index'])), "invalid device")
    for key in ('sizes', 'strides'):
        vector = value[key]
        _need(vector is None or (type(vector) is list and len(vector) <= 64
              and all(type(x) is int and (key != 'sizes' or x >= 0) for x in vector)), "invalid geometry")
    if value['sizes'] is not None and value['strides'] is not None:
        _need(len(value['sizes']) == len(value['strides'])
              or 'provider_geometry_rank_mismatch' in value['gaps'], "geometry rank lacks its frontier")
    _need(value['storage_offset'] is None
          and value['storage_offset_gap'] == 'not_exposed_by_installed_tensor_metadata_binding', "invented storage offset")
    epoch = value['provider_allocation_id'] is not None and device is not None and value['storage_data_ptr'] not in (None, 0)
    _need(type(value['physical_epoch_reference_observed']) is bool
          and value['physical_epoch_reference_observed'] == epoch, "epoch flag differs")
    _gaps(value['gaps'])
    _need((value['status'] == 'OPEN') == bool(value['gaps']), "metadata gap/status differs")


def _row(row, index, pid, nonce, previous, seen, counts):
    _keys(row, 'schema schema_version process_id nonce index kind event name overload_name scope inputs gaps')
    _need(row['schema'] == 'scar.native-tensor-input-observation' and type(row['schema_version']) is int
          and row['schema_version'] == 1 and row['index'] == index and type(row['index']) is int
          and row['process_id'] == pid and type(row['process_id']) is int and row['nonce'] == nonce
          and row['kind'] == 'TORCH_OP_INPUTS', "row namespace/index differs")
    _need(type(row['name']) is str and type(row['overload_name']) is str
          and (row['scope'] is None or type(row['scope']) is str), "invalid operator descriptor")
    header = row['event']
    _keys(header, 'traversal_ordinal result_id parent_result_id start_time_ns end_time_ns record_function_thread_token correlation_id')
    _need(_integer(header['traversal_ordinal'], 1) and header['traversal_ordinal'] > previous, "traversal ordinal not increasing")
    result = header['result_id']
    _need(_integer(result, 1) and result not in seen, "duplicate/invalid result ID")
    seen.add(result)
    for key in ('parent_result_id', 'record_function_thread_token'):
        _need(header[key] is None or _integer(header[key], 1), "invalid event reference")
    for key in ('start_time_ns', 'end_time_ns', 'correlation_id'):
        _need(header[key] is None or _integer(header[key]), "invalid event scalar")
    _gaps(row['gaps'])
    data = row['inputs']
    _keys(data, 'availability top_level_count slots')
    _need(data['availability'] in ('OBSERVED', 'UNAVAILABLE') and type(data['slots']) is list, "invalid input availability")
    if data['availability'] == 'UNAVAILABLE':
        _need(not data['slots'] and (data['top_level_count'] is None or _integer(data['top_level_count']))
              and bool(row['gaps']), "unavailable inputs lack a frontier")
        counts['unavailable_input_rows'] += 1
        return header['traversal_ordinal']
    _need(type(data['top_level_count']) is int and data['top_level_count'] == len(data['slots'])
          and len(data['slots']) <= 4096, "input slot count differs")
    tensor_count = 0
    for i, slot in enumerate(data['slots']):
        _need(type(slot) is dict and type(slot.get('ordinal')) is int and slot['ordinal'] == i, "slot order differs")
        kind = slot.get('kind')
        counts[kind if type(kind) is str else 'invalid'] += 1
        if kind == 'TENSOR':
            _keys(slot, 'ordinal kind path metadata')
            _need(_path(slot['path'], [i]), "Tensor path differs")
            _metadata(slot['metadata'])
            tensor_count += 1
        elif kind == 'TENSOR_LIST':
            _keys(slot, 'ordinal kind items')
            _need(type(slot['items']) is list and len(slot['items']) <= 4096, "invalid TensorList")
            for j, item in enumerate(slot['items']):
                _keys(item, 'ordinal path metadata')
                _need(type(item['ordinal']) is int and item['ordinal'] == j and _path(item['path'], [i, j]), "TensorList order/path differs")
                _metadata(item['metadata'])
            tensor_count += len(slot['items'])
            counts['empty_tensor_lists'] += not slot['items']
        elif kind == 'SCALAR_OPAQUE':
            _keys(slot, 'ordinal kind scalar_kind')
            _need(slot['scalar_kind'] in ('bool', 'int', 'float', 'complex'), "invalid opaque scalar type")
        elif kind == 'OPAQUE':
            _keys(slot, 'ordinal kind reason')
            _need(slot['reason'] in ('provider_none_or_unsupported_or_undefined', 'unsupported_provider_input',
                'unsupported_or_over_budget_tensor_list', 'native_input_tensor_metadata_budget'), "invalid opaque reason")
        else:
            raise ValueError('native input retention: unsupported slot kind')
    _need(tensor_count <= 4096, "Tensor metadata count exceeded")
    counts['tensor_metadata'] += tensor_count
    return header['traversal_ordinal']


def read_native_tensor_inputs(path, *, expected_sha256, max_bytes=512000000, max_rows=1000000, on_row=None,
                              _retained_files=None):
    """Fully verify retained bytes/structure, never recreate a live owner.

    on_row receives provisional observations. Only successful return confirms
    complete retention; even then no ETO-port/object/geometry/ready join is given.
    """
    _need(_integer(max_bytes, 1) and _integer(max_rows, 1) and (on_row is None or callable(on_row)), "invalid reader bounds")
    path = Path(path).absolute()
    if _retained_files is not None:
        from scar.trace.capture_coordinates import _Files
        _need(type(_retained_files) is _Files, "exact retained file resolver required")

    def locate(logical, schema):
        if _retained_files is None:
            _need(not logical.is_symlink() and logical.is_file(), "absent/symlinked source")
            return logical, None, None
        artifact = _retained_files.verify(str(logical), schema)
        local, entry = _retained_files.local(str(logical))
        return local, entry, artifact

    def document(logical, schema):
        local, entry, artifact = locate(logical, schema)
        _need((artifact.size_bytes if artifact is not None else local.stat().st_size) <= 2000000,
              "metadata bound exceeded")
        with (gzip.open if entry is not None else open)(local, 'rb') as source:
            content = source.read(2000001)
        _need(len(content) <= 2000000, "metadata read bound exceeded")
        if artifact is not None:
            _need(len(content) == artifact.size_bytes and sha256(content).hexdigest() == artifact.sha256,
                  "resolved metadata changed")
        return content

    raw = document(path, 'scar.native-tensor-input-trace')
    _need(sha256(raw).hexdigest() == expected_sha256, "manifest SHA differs")
    doc = _json(raw)
    _keys(doc, 'schema schema_version profile provider_revision process_id nonce status traversal_completed frontier transport_failure errors visited_torch_ops retained_rows omitted_visited_torch_ops raw_bytes chunks limits inputs legacy_physical_metadata capabilities assumptions membership')
    pid, nonce = doc['process_id'], doc['nonce']
    _need(doc['schema'] == 'scar.native-tensor-input-trace' and type(doc['schema_version']) is int
          and doc['schema_version'] == 1 and doc['profile'] == NATIVE_INPUT_PROFILE
          and doc['provider_revision'] == PROVIDER_REVISION and _integer(pid, 1)
          and type(nonce) is str and re.fullmatch('[0-9a-f]{32}', nonce), "manifest profile differs")
    _need(path.name == 'manifest.json' and path.parent.name == f'native-tensor-inputs.{pid}.{nonce}', "manifest namespace differs")
    _need(doc['status'] == 'COMPLETE_RETENTION' and doc['traversal_completed'] is True
          and doc['frontier'] is None and doc['transport_failure'] is None and doc['errors'] == []
          and type(doc['omitted_visited_torch_ops']) is int and doc['omitted_visited_torch_ops'] == 0, "retention is incomplete")
    _need(doc['capabilities'] == {'native_inputs': 'PROVIDER_METADATA_ONLY', 'native_outputs': 'UNAVAILABLE_IN_PINNED_API',
        'ETO_port_join_established': False, 'Python_identity_established': False,
        'logical_content_established': False, 'resource_ready_established': False}, "unsupported capability")
    _need(all(type(doc['capabilities'][key]) is bool for key in ('ETO_port_join_established',
        'Python_identity_established', 'logical_content_established', 'resource_ready_established')), "invalid capability type")
    _need(doc['assumptions'] == ['same caller-owned closed profiler result as the legacy physical exporter']
          and doc['membership'] == 'companion retention only; not an ordinary CaptureCoordinates member', "unsupported retention scope")
    limits = doc['limits']
    _keys(limits, 'chunk_rows chunk_bytes max_rows max_bytes line_bytes')
    _need(all(_integer(v, 1) for v in limits.values()) and limits['chunk_rows'] <= 1000
          and limits['chunk_bytes'] <= 8000000 and limits['line_bytes'] <= 2000000, "unsupported transport bounds")
    _need(_integer(doc['retained_rows']) and doc['retained_rows'] <= min(max_rows, limits['max_rows'])
          and type(doc['visited_torch_ops']) is int and doc['retained_rows'] == doc['visited_torch_ops']
          and _integer(doc['raw_bytes']) and doc['raw_bytes'] <= min(max_bytes, limits['max_bytes']), "manifest totals/bounds differ")
    _need(type(doc['chunks']) is list and len(doc['chunks']) <= 4096, "chunk manifest bound")
    _keys(doc['inputs'], 'native_manifest dispatch_metadata dispatch_observations')
    def metadata_receipt(receipt, filename):
        _keys(receipt, 'path raw_bytes raw_sha256')
        source = path.parent.parent / filename
        _need(receipt['path'] == str(source) and _integer(receipt['raw_bytes'], 1)
              and receipt['raw_bytes'] <= 2000000, "metadata namespace/size differs")
        content = document(source, 'application/json')
        _need(len(content) == receipt['raw_bytes'] and sha256(content).hexdigest() == receipt['raw_sha256'], "metadata bytes changed")
        return _json(content)
    native = metadata_receipt(doc['inputs']['native_manifest'], f'execution-evidence.{pid}.json')
    dispatch = metadata_receipt(doc['inputs']['dispatch_metadata'], f'dispatch-meta.{pid}.{nonce}.json')
    physical = metadata_receipt(doc['legacy_physical_metadata'], f'tensor-physical-meta.{pid}.{nonce}.json')
    request = native.get('configuration', {}).get('native_tensor_input_observations', {})
    _need(native.get('schema') == 'scar.execution-evidence-collection' and type(native.get('schema_version')) is int
          and native['schema_version'] == 1 and native.get('status') == 'CLOSED' and native.get('pid') == pid
          and native.get('provider', {}).get('torch_git_version') == PROVIDER_REVISION
          and request.get('profile') == NATIVE_INPUT_PROFILE and request.get('requested') is True
          and request.get('chunk_rows') == limits['chunk_rows']
          and request.get('manifest') == str(path), "native request/closure differs")
    _need(dispatch.get('schema') == 'scar.dispatch-observation-trace' and type(dispatch.get('schema_version')) is int
          and dispatch['schema_version'] == 1 and dispatch.get('profile') == 'scar.dispatch-marker-collector-v1'
          and dispatch.get('provider_revision') == PROVIDER_REVISION and dispatch.get('process_id') == pid
          and dispatch.get('nonce') == nonce and dispatch.get('mode_popped') is True
          and physical.get('schema') == 'scar.tensor-physical-trace' and type(physical.get('schema_version')) is int
          and physical['schema_version'] == 1 and physical.get('profile') == 'scar.tensor-physical-event-tree-v1'
          and physical.get('provider_revision') == PROVIDER_REVISION and physical.get('process_id') == pid
          and physical.get('nonce') == nonce and dispatch.get('native_manifest') == doc['inputs']['native_manifest']
          and dispatch.get('file') == doc['inputs']['dispatch_observations']
          and physical.get('inputs') == doc['inputs'], "closed input receipt chain differs")
    total = rows = previous = 0
    counts, seen = Counter(), set()
    for number, chunk in enumerate(doc['chunks']):
        _keys(chunk, 'path raw_bytes raw_sha256 rows first_index')
        _need(chunk['path'] == f'{number:06d}.jsonl' and type(chunk['first_index']) is int
              and chunk['first_index'] == rows + 1 and _integer(chunk['rows'], 1)
              and chunk['rows'] <= limits['chunk_rows'] and _integer(chunk['raw_bytes'], 1)
              and chunk['raw_bytes'] <= limits['chunk_bytes'], "chunk namespace/range differs")
        source, entry, artifact = locate(path.parent / chunk['path'], 'scar.native-tensor-input-observation.v1')
        _need((artifact.size_bytes if artifact is not None else source.stat().st_size) == chunk['raw_bytes'], "chunk file/size differs")
        if artifact is not None:
            _need(artifact.sha256 == chunk['raw_sha256'], "resolved chunk SHA differs")
        digest, size, count = sha256(), 0, 0
        with (gzip.open if entry is not None else open)(source, 'rb') as stream:
            while line := stream.readline(limits['line_bytes'] + 1):
                _need(len(line) <= limits['line_bytes'] and line.endswith(b'\n')
                      and total + len(line) <= max_bytes and rows < max_rows, "chunk line/reader budget")
                digest.update(line)
                size += len(line)
                total += len(line)
                rows += 1
                count += 1
                row = _json(line)
                previous = _row(row, rows, pid, nonce, previous, seen, counts)
                if on_row is not None:
                    on_row(row)
        _need(size == chunk['raw_bytes'] and count == chunk['rows'] and digest.hexdigest() == chunk['raw_sha256'], "chunk receipt differs")
    _need(total == doc['raw_bytes'] and rows == doc['retained_rows'], "final retention totals differ")
    return {'profile': NATIVE_INPUT_PROFILE, 'manifest_sha256': expected_sha256,
        'retained_rows': rows, 'raw_bytes': total, 'counts': dict(counts),
        'capabilities': doc['capabilities'], 'ordinary_capture_membership_established': False}


__all__ = ['read_native_tensor_inputs']


# This capability associates retained native input metadata with an already
# verified V2 occurrence. It grants no object, allocation, content or ready fact.
INPUT_ASSOCIATION_PROFILE = 'SCAR_NATIVE_INPUT_METADATA_ASSOCIATION_V1'
_INPUT_OWNER = object()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


class NativeInputPayloadBudget:
    """One bounded accounting ledger; complete legacy passes are explicit.

    The unchanged public coordinate binder reports verified complete artifacts.
    Its full-pass read multiplicities are charged separately and labeled derived;
    newly opened adapter streams count returned bytes directly. Reservations are
    charged before a phase, reconciled after success, and never reusable credit.
    """
    def __init__(self, maximum=68000000, control_maximum=1000000):
        _need(_integer(maximum, 1) and maximum <= 68000000
              and _integer(control_maximum, 1) and control_maximum <= 1000000, 'payload budget')
        self.maximum, self.control_maximum = maximum, control_maximum
        self.entries, self.total, self.control = [], 0, 0

    def charge(self, component, stored, decoded, *, basis='returned bytes', control=False):
        _need(_integer(stored) and _integer(decoded), 'invalid payload accounting')
        amount = stored + decoded
        _need(self.total + amount <= self.maximum, 'aggregate stored+decoded payload budget')
        _need(not control or self.control + amount <= self.control_maximum, 'control metadata budget')
        self.total += amount
        self.control += amount if control else 0
        self.entries.append({'component': component, 'stored_bytes': stored, 'decoded_bytes': decoded,
                             'basis': basis, 'control_metadata': control})

    def report(self):
        return {'limit': self.maximum, 'stored_plus_decoded_bytes': self.total,
                'control_metadata_limit': self.control_maximum, 'control_metadata_bytes': self.control,
                'entries': list(self.entries), 'kernel_IO_measurement': False}


def _association_members(coordinates):
    from scar.trace.capture_coordinates import CaptureCoordinates
    from scar.ir.record_codec import decode
    from scar.ir.program.providers import ProviderArtifact
    _need(type(coordinates) is CaptureCoordinates
          and sha256(coordinates.payload).hexdigest() == coordinates.artifact.sha256
          and _json(coordinates.payload) == coordinates.report, 'genuine ordinary coordinates required')
    result = {}
    for row in coordinates.report['membership']:
        artifact = decode(ProviderArtifact, row['artifact'])
        if row['process'] != coordinates.report['target_process']:
            continue
        _need(coordinates.process_for(artifact, coordinates.target_process.pid) == coordinates.target_process,
              'input member process differs')
        _need(artifact.uri not in result, 'duplicate exact member URI')
        result[artifact.uri] = (artifact, Path(row['local_path']))
    return result


def _read_input_member(members, logical, budget, label, archive):
    """Read exact declared local bytes once, then decode the same buffer."""
    from io import BytesIO
    artifact, path = members[str(logical)]
    _need(path.is_file() and not path.is_symlink(), 'absent/symlinked associated member')
    size = path.stat().st_size
    entry = archive.get(str(logical))
    _need(entry is None or (entry['raw_bytes'] == artifact.size_bytes
          and entry['raw_sha256'] == artifact.sha256 and size == entry['compressed_bytes']), 'associated archive declaration differs')
    # Reserve both planes before reading; a changed file cannot consume an
    # unbounded extra stream. SHA/EOF comparisons below reject any change.
    budget.charge(label, size, artifact.size_bytes, basis='bounded member returned bytes')
    with path.open('rb') as source:
        stored = source.read(size + 1)
    _need(len(stored) == size, 'associated stored source changed')
    if path.suffix == '.gz':
        _need(entry is not None and sha256(stored).hexdigest() == entry['gzip_sha256'], 'associated stored SHA differs')
        with gzip.GzipFile(fileobj=BytesIO(stored), mode='rb') as source:
            raw = source.read(artifact.size_bytes + 1)
    else:
        raw = stored
    _need(len(raw) == artifact.size_bytes and sha256(raw).hexdigest() == artifact.sha256,
          'associated raw source changed')
    return artifact, raw


class NativeInputMetadataSession:
    """Fresh immutable raw join preimages, never a canonical graph or old owner."""
    __slots__ = ('_wire', '_seen', '_canonical_nodes', '_associations')

    def __setattr__(self, name, value):
        if name == '_wire' and hasattr(self, '_wire'):
            raise AttributeError('native input preimages are immutable')
        object.__setattr__(self, name, value)

    def __init__(self, key, document):
        _need(key is _INPUT_OWNER, 'input association factory required')
        self._wire = _canonical(document)
        self._seen, self._canonical_nodes, self._associations = set(), set(), []

    def _expected(self, shard):
        from scar.ir.execution.content import NativeInputRef
        from scar.ir.program.model import TerminatorKind
        from scar.ir.record_codec import encode
        # Covers all identities, including all-Unknown and zero-Tensor calls.
        shard.native_port_evidence.require_scope(shard.execution, shard.program)
        source = _json(self._wire)
        _need(len(shard.execution.runs) == 1 and shard.execution.runs[0].id.value == source['run']
              and any(p.id.value == source['process'] for p in shard.execution.processes), 'association Run/process differs')
        model, program = shard.execution, shard.program
        raw_nodes = {r['node_id']: r for r in source['rows'] if r.get('node_id') is not None}
        by_visit, by_binding = {}, {}
        for occurrence in model.operations:
            by_visit.setdefault(occurrence.visit, []).append(occurrence)
        for binding in model.evidence_bindings:
            by_binding.setdefault(binding.operation, []).append(binding)
        static_ops = {o.id: o for o in program.operations}
        instances = shard.evidence.instances
        expected, canonical_nodes = [], set()
        for occurrence in model.operations:
            static = static_ops[occurrence.operation]
            if static.terminator is None or static.terminator.kind != TerminatorKind.INVOKE:
                continue
            bindings = by_binding.get(occurrence.id, ())
            _need(len(bindings) == 1, 'unique exact native invoke binding required')
            native = instances.get(bindings[0].legacy.instance)
            _need(native is not None and native.metadata.get('provider') == 'ETO', 'original ETO producer missing')
            canonical_nodes.add(native.metadata['node_id'])
        for denotation in model.denotations:
            basis = denotation.basis
            if type(basis) is not NativeInputRef:
                continue
            invokes = [o for o in by_visit.get(basis.entry, ()) if static_ops[o.operation].terminator is not None
                       and static_ops[o.operation].terminator.kind == TerminatorKind.INVOKE]
            _need(len(invokes) == 1, 'input has no unique actual invoke')
            binding = by_binding[invokes[0].id][0]
            instance = instances.get(binding.legacy.instance)
            _need(instance is not None, 'input original producer unavailable')
            row = raw_nodes.get(instance.metadata['node_id'])
            if row is None:
                continue
            producer = {'instance': encode(binding.legacy), 'source': encode(binding.source)}
            _need(producer['source'] == row['original_node'], 'input producer/ordinal differs from original raw join')
            _need(denotation.source.artifact == binding.source.artifact, 'input and producer artifact differ')
            prefix = row['original_node']['locator'] + '/inputs/values/'
            _need(denotation.source.locator.startswith(prefix), 'input lacks exact original native slot')
            tail = denotation.source.locator[len(prefix):]
            _need(tail and all(p.isdecimal() for p in tail.split('/')), 'invalid original input path')
            path = [int(p) for p in tail.split('/')]
            leaves = [p for p in row['metadata'] if p['path'] == path]
            _need(len(leaves) <= 1, 'ambiguous original input metadata path')
            if not leaves:
                continue
            leaf = leaves[0]
            expected.append({'native_input': encode(basis), 'value_occurrence': encode(denotation.value),
                'native_producer': producer, 'original_input': encode(denotation.source),
                'metadata_source': leaf['source'], 'CPU_bridge': row['CPU_bridge'],
                'metadata': leaf['metadata'], 'row': row['index'], 'path': path,
                'Python_identity_qualified': False, 'geometry_allocation_qualified': False,
                'logical_content_qualified': False, 'resource_ready_qualified': False})
        return expected, canonical_nodes

    def check(self, shard, associations):
        """Independent comparison to fresh raw preimages and real canonical ports."""
        expected, _ = self._expected(shard)
        _need(type(associations) is list and len(associations) == len(expected), 'input association inventory differs')
        for actual, original in zip(associations, expected, strict=True):
            _need(_canonical(actual) == _canonical(original), 'native input association producer/path/source mismatch')
        return True

    def bind_shard(self, shard):
        expected, nodes = self._expected(shard)
        self.check(shard, expected)
        for item in expected:
            key = (item['row'], tuple(item['path']))
            _need(key not in self._seen, 'input metadata associated twice across shards')
            self._seen.add(key)
        self._canonical_nodes.update(nodes)
        self._associations.extend(expected)
        return expected

    def report(self):
        source = _json(self._wire)
        rows, counts = [], Counter()
        for original in source['rows']:
            row = dict(original)
            if row.get('node_id') in self._canonical_nodes:
                row['canonical_status'] = 'CANONICAL_BOUNDARY_AVAILABLE'
            else:
                row['canonical_status'] = 'CANONICAL_NATIVE_BOUNDARY_UNAVAILABLE'
            for leaf in row['metadata']:
                associated = (row['index'], tuple(leaf['path'])) in self._seen
                _need(associated or row.get('node_id') not in self._canonical_nodes,
                      'canonical native input metadata path lacks its exact actual port')
                leaf['association'] = 'ASSOCIATED' if associated else row['canonical_status']
                counts[leaf['association']] += 1
            rows.append(row)
        return {'schema': 'scar.native-input-metadata-associations', 'schema_version': 1,
            'profile': INPUT_ASSOCIATION_PROFILE, 'run': source['run'], 'process': source['process'],
            'counts': {**source['counts'], 'associated_metadata_paths': len(self._seen),
                       'canonical_nodes': len(self._canonical_nodes), 'metadata_dispositions': dict(counts)},
            'rows': rows, 'associations': list(self._associations),
            'native_outputs': 'UNAVAILABLE_IN_PINNED_API', 'Python_identity_established': False,
            'geometry_allocation_established': False, 'logical_content_established': False,
            'state_effects_established': False, 'resource_ready_established': False,
            'whole_model_established': False, 'frontiers': source['frontiers']}


def prepare_native_input_metadata(coordinates, *, budget):
    """Verify all retained rows and raw bridge preimages under ordinary membership."""
    from collections import defaultdict
    from scar.ir.record_codec import encode
    from scar.ir.execution.native_port_protocol import attributes, flat_native
    from scar.trace.capture_coordinates import _Files
    _need(type(budget) is NativeInputPayloadBudget, 'exact shared payload budget required')
    members = _association_members(coordinates)
    root = Path(coordinates.report['local_root'])
    original_root = Path(coordinates.report['original_root'])
    archive_path = root / 'archive-index.json'
    archive_size = archive_path.stat().st_size
    budget.charge('adapter archive index', archive_size, archive_size, control=True)
    archive_raw = archive_path.read_bytes()
    _need(len(archive_raw) == archive_size, 'archive index size changed')
    archive = _json(archive_raw)
    _need(sha256(archive_raw).hexdigest() == coordinates.report['seed']['archive_sha256'], 'archive root changed')
    files = _Files(root, original_root, archive, budget.maximum)
    capability = coordinates.report['native_tensor_input_membership']
    _need(capability['capability'] == 'SCAR_NATIVE_TENSOR_INPUT_MEMBERSHIP_V1', 'ordinary input membership required')
    manifest = capability['manifest']
    archived = {r['logical_path']: r for r in archive['files']}
    manifest_path = members[manifest['uri']][1]
    budget.charge('adapter companion manifest reload', manifest['size_bytes'], manifest['size_bytes'], control=True)
    manifest_raw = manifest_path.read_bytes()
    _need(len(manifest_raw) == manifest['size_bytes'] and sha256(manifest_raw).hexdigest() == manifest['sha256'], 'input manifest changed')
    companion_doc = _json(manifest_raw)
    strict_names = [manifest['uri']] + [companion_doc['inputs'][k]['path'] for k in ('native_manifest', 'dispatch_metadata')]
    strict_names += [companion_doc['legacy_physical_metadata']['path']]
    for logical in strict_names:
        size = members[logical][0].size_bytes
        budget.charge('adapter strict metadata verify+parse', 2*size, 2*size, control=True)
    strict_raw = 0
    for artifact in capability['chunks']:
        entry = archived[artifact['uri']]
        _need(entry['raw_sha256'] == artifact['sha256'] and entry['raw_bytes'] == artifact['size_bytes'], 'input chunk membership differs')
        budget.charge('adapter strict chunk verify+parse', 3*entry['compressed_bytes'], 2*entry['raw_bytes'],
                      basis='reserved complete strict-reader passes; verified on return')
        strict_raw += entry['raw_bytes']
    raw_rows = []
    retention = read_native_tensor_inputs(manifest['uri'], expected_sha256=manifest['sha256'],
        max_bytes=max(1, strict_raw), on_row=raw_rows.append, _retained_files=files)
    _need(retention['raw_bytes'] == strict_raw, 'strict companion returned-byte accounting differs')
    def member(schema):
        matches = [x for x in members.values() if x[0].schema == schema]
        _need(len(matches) == 1, 'no unique associated member: ' + schema)
        return matches[0][0]
    ea, ka = member('pytorch.execution-trace.v1'), member('pytorch.kineto.chrome-trace.v1')
    _, eraw = _read_input_member(members, ea.uri, budget, 'adapter ETO', archived)
    _, kraw = _read_input_member(members, ka.uri, budget, 'adapter Kineto', archived)
    eto, kineto = _json(eraw), _json(kraw)
    pid = coordinates.target_process.pid
    _need(eto['pid'] == pid, 'input ETO process differs')
    cpu, rf, correlations = defaultdict(list), defaultdict(list), defaultdict(list)
    for ordinal, event in enumerate(kineto['traceEvents']):
        key = event.get('args', {}).get('External id')
        if event.get('ph') == 'X' and event.get('cat') in ('cpu_op', 'user_annotation') and event.get('pid') == pid and type(key) is int and key > 0:
            cpu[key].append((ordinal, event))
    for ordinal, node in enumerate(eto['nodes']):
        handle = attributes(node).get('rf_id')
        if type(handle) is int and handle > 0:
            rf[handle].append((ordinal, node))
    for row in raw_rows:
        correlations[row['event']['correlation_id']].append(row['index'])
    def fact(artifact, locator):
        return {'artifact': encode(artifact), 'locator': locator}
    chunk_for_row = {}
    for chunk, artifact in zip(companion_doc['chunks'], capability['chunks'], strict=True):
        for offset in range(chunk['rows']):
            chunk_for_row[chunk['first_index'] + offset] = (artifact, offset + 1)
    counts, frontiers, result, mapped = Counter(), Counter(), [], {}
    for row in raw_rows:
        index, event = row['index'], row['event']
        chunk, line = chunk_for_row[index]
        leaves = []
        for slot in row['inputs']['slots']:
            counts['slot_' + slot['kind']] += 1
            if slot['kind'] == 'TENSOR_LIST':
                counts['empty_tensor_lists'] += not slot['items']
            items = [(slot['path'], slot['metadata'], f"/inputs/slots/{slot['ordinal']}/metadata")] if slot['kind'] == 'TENSOR' else [
                (item['path'], item['metadata'], f"/inputs/slots/{slot['ordinal']}/items/{item['ordinal']}/metadata") for item in slot['items']] if slot['kind'] == 'TENSOR_LIST' else []
            for path, metadata, pointer in items:
                leaves.append({'path': path, 'metadata': metadata, 'source': {'artifact': chunk, 'locator': f'#/lines/{line}' + pointer}})
        retained_inputs = []
        for slot in row['inputs']['slots']:
            skeleton = {'ordinal': slot['ordinal'], 'kind': slot['kind']}
            if slot['kind'] == 'TENSOR':
                skeleton['tensor_paths'] = [slot['path']]
            elif slot['kind'] == 'TENSOR_LIST':
                skeleton['tensor_paths'] = [p['path'] for p in slot['items']]
            elif slot['kind'] == 'OPAQUE':
                skeleton['reason'] = slot['reason']
            elif slot['kind'] == 'SCALAR_OPAQUE':
                skeleton['scalar_kind'] = slot['scalar_kind']
            retained_inputs.append(skeleton)
        item = {'index': index, 'metadata': leaves, 'node_id': None, 'source': {'artifact': chunk, 'locator': f'#/lines/{line}'},
                'tree_parent': event['parent_result_id'], 'tree_result': event['result_id'],
                'input_availability': row['inputs']['availability'], 'retained_inputs': retained_inputs}
        counts['metadata_paths'] += len(leaves)
        correlation = event['correlation_id']
        if type(correlation) is int and correlation > 0:
            _need(len(correlations[correlation]) == 1, 'ambiguous tree correlation')
        candidates = cpu.get(correlation, ()) if type(correlation) is int and correlation > 0 else ()
        _need(len(candidates) <= 1, 'ambiguous CPU External id')
        if not candidates:
            item['frontier'] = 'CPU_EXTERNAL_UNAVAILABLE'
        else:
            ko, observed = candidates[0]
            handle = observed.get('args', {}).get('Record function id')
            matches = rf.get(handle, ()) if type(handle) is int and handle > 0 else ()
            _need(len(matches) <= 1, 'ambiguous ETO RecordFunction id')
            if not matches:
                item['frontier'] = 'ETO_RF_MISSING'
            else:
                ordinal, node = matches[0]
                attrs = attributes(node)
                _need(attrs.get('tid') == event['record_function_thread_token'], 'raw RF thread contradiction')
                name = row['name'] + ('.' + row['overload_name'] if row['overload_name'] else '')
                _need(node['name'] == row['name'] and observed['name'] == name, 'name contradiction after exact key join')
                if row['inputs']['availability'] == 'OBSERVED':
                    _need(len(row['inputs']['slots']) == len(node['inputs']['values']), 'native boxed input arity contradiction')
                item.update(node_id=node['id'], original_node=fact(ea, f'#/nodes/{ordinal}'),
                    CPU_bridge=fact(ka, f'#/traceEvents/{ko}'), ETO_parent=node['ctrl_deps'])
                mapped[event['result_id']] = node['id']
                counts['exact_raw_key_joins'] += 1
                item['schema_text_present'] = bool(attrs.get('op_schema'))
                if not item['schema_text_present']:
                    item['schema_frontier'] = 'REGISTERED_SCHEMA_TEXT_UNAVAILABLE'
                    frontiers['REGISTERED_SCHEMA_TEXT_UNAVAILABLE'] += 1
                try:
                    native_paths = {tuple(p['path']): p for p in flat_native(node['inputs']) if p['tensor']}
                except ValueError:
                    item['frontier'] = 'NATIVE_INPUT_STRUCTURE_UNSUPPORTED'
                    native_paths = None
                if native_paths is not None:
                    seen = set()
                    for leaf in leaves:
                        path = tuple(leaf['path'])
                        _need(path not in seen and path in native_paths, 'metadata original Tensor path contradiction')
                        seen.add(path)
                        original = native_paths[path]
                        metadata = leaf['metadata']
                        if metadata['sizes'] is not None and metadata['strides'] is not None and metadata['device'] is not None:
                            _need(metadata['sizes'] == original['shape'] and metadata['strides'] == original['strides']
                                  and metadata['device']['text'] == original['value'][5], 'metadata geometry contradiction after original path join')
                        counts['metadata_at_exact_native_path'] += 1
                    frontiers['NATIVE_TENSOR_WITHOUT_EXPOSED_METADATA'] += len(set(native_paths) - seen)
        if 'frontier' in item:
            frontiers[item['frontier']] += 1
        result.append(item)
    for row in result:
        if row.get('node_id') is not None:
            parent = row['tree_parent']
            if parent in mapped:
                _need(mapped[parent] == row['ETO_parent'], 'mapped original parent contradiction')
                counts['mapped_parent_checks'] += 1
            else:
                frontiers['PARENT_OUTSIDE_EXPORTED_TORCHOP_BOUNDARY'] += 1
    counts['rows'] = len(result)
    _need(counts['rows'] == retention['retained_rows'], 'full input row denominator differs')
    return NativeInputMetadataSession(_INPUT_OWNER, {'run': coordinates.run.id.value,
        'process': coordinates.target_process.id.value, 'rows': result, 'counts': dict(counts), 'frontiers': dict(frontiers)})


__all__ += ['INPUT_ASSOCIATION_PROFILE', 'NativeInputPayloadBudget', 'NativeInputMetadataSession', 'prepare_native_input_metadata']
