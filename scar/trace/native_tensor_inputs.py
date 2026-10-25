"""Strict bounded retention reader, without ETO joins or qualification tokens."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
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


def read_native_tensor_inputs(path, *, expected_sha256, max_bytes=512000000, max_rows=1000000, on_row=None):
    """Fully verify retained bytes/structure, never recreate a live owner.

    on_row receives provisional observations. Only successful return confirms
    complete retention; even then no ETO-port/object/geometry/ready join is given.
    """
    _need(_integer(max_bytes, 1) and _integer(max_rows, 1) and (on_row is None or callable(on_row)), "invalid reader bounds")
    path = Path(path).absolute()
    _need(not path.is_symlink() and path.is_file() and path.stat().st_size <= 2000000, "invalid manifest path/bound")
    raw = path.read_bytes()
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
        _need(receipt['path'] == str(source) and not source.is_symlink() and source.is_file()
              and _integer(receipt['raw_bytes'], 1) and source.stat().st_size == receipt['raw_bytes'] <= 2000000, "metadata namespace/size differs")
        content = source.read_bytes()
        _need(sha256(content).hexdigest() == receipt['raw_sha256'], "metadata bytes changed")
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
        source = path.parent / chunk['path']
        _need(not source.is_symlink() and source.is_file() and source.stat().st_size == chunk['raw_bytes'], "chunk file/size differs")
        digest, size, count = sha256(), 0, 0
        with source.open('rb') as stream:
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
