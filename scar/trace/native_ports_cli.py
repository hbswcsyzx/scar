"""Public producers/queries for the existing native operation port fragments."""
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.ir.record_codec import decode, encode
from scar.ir.v2.evidence import OperationInstance
from scar.store.bundle_partitions import BundlePartitions
from scar.trace.native_port_sidecar import (
    build_native_port_publication, query_native_ports, query_native_port_edges, read_native_port_index,
)


def _summary(index):
    return {'source_nodes': index.source_nodes, 'operation_rows': index.operation_rows,
            'input_ports': index.input_ports, 'output_ports': index.output_ports,
            'classification_counts': index.classification_counts, 'shards': len(index.shards),
            'stored_shard_bytes': sum(ref.stored_bytes for ref in index.shards),
            'decoded_shard_bytes': sum(ref.decoded_bytes for ref in index.shards)}


def build_native_ports_cli(args):
    started = time.monotonic()
    index = build_native_port_publication(args.eto, args.archive_index, args.archive_sha256,
        args.bundle, args.out, shard_size=args.shard_size)
    manifest = Path(args.out).absolute() / 'index.json'
    print(json.dumps({'status': 'OBSERVED_PORTS_PUBLISHED', 'index': str(manifest),
                      'sha256': sha256(manifest.read_bytes()).hexdigest(),
                      'elapsed_s': time.monotonic() - started, **_summary(index),
                      'logical_content_or_ready_proved': False, 'whole_model_established': False}))
    return 0


def query_native_ports_cli(args):
    started = time.monotonic()
    path = Path(args.index).absolute()
    index = read_native_port_index(path, expected_sha256=args.sha256)
    result = {'schema': 'scar.native-boxed-port-query', 'schema_version': 1,
              'index': {'uri': str(path), 'sha256': args.sha256}, 'summary': _summary(index),
              'qualification': 'ORIGINAL_NATIVE_INSTANCE_AND_ORDERED_OBSERVED_PORTS',
              'logical_content_or_ready_proved': False, 'whole_model_established': False,
              'transformation_authorized': False}
    if args.descriptor_id is not None and args.provider_reference is None:
        raise ValueError('--descriptor-id requires --provider-reference')
    if args.provider_reference is not None:
        if args.descriptor_id is None or args.bundle is None:
            raise ValueError('provider occurrence query needs --descriptor-id and --bundle')
        matches = query_native_port_edges(args.provider_reference, args.descriptor_id,
            path.parent, args.bundle, expected_index_sha256=args.sha256)
        result['qualification'] = 'OBSERVED_PORT_OCCURRENCES_AND_ORIGINAL_EVIDENCE_EDGES'
        result['provider_reference'] = args.provider_reference
        result['descriptor_id'] = args.descriptor_id
        result['occurrences'] = [{'instance': row.instance.wire, 'definition': row.definition.wire,
                                  'source_ordinal': row.source_ordinal, 'port': encode(port),
                                  'edge': edge.as_dict()} for row, port, edge in matches]
        result['matched_occurrences'] = len(matches)
    if args.ordinal is not None:
        if not 0 <= args.ordinal < index.source_nodes:
            raise ValueError('ordinal must identify an original ETO node')
        if args.bundle is None:
            raise ValueError('--bundle is required to resolve the original instance')
        bundle = BundlePartitions(args.bundle)
        record = bundle.selected_records('evidence', 'instances', (args.ordinal,))[0]['record']
        instance = decode(OperationInstance, record)
        row = query_native_ports(instance, path.parent, args.bundle, expected_index_sha256=args.sha256)
        result['row'] = encode(row)
    result['elapsed_s'] = time.monotonic() - started
    payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if args.out:
        with Path(args.out).open('x', encoding='utf-8') as stream:
            stream.write(payload)
    else:
        print(payload, end='')
    return 0


def _flow_summary(index):
    return {name: getattr(index, name) for name in (
        'source_nodes', 'operation_rows', 'native_ports', 'reference_ports',
        'input_reference_ports', 'output_reference_ports', 'ports_with_one_original_edge',
        'ports_without_one_original_edge', 'groups_with_input_and_output')}


def build_native_reference_flow_cli(args):
    from scar.trace.native_reference_flow import build_native_reference_flow_publication
    started = time.monotonic()
    ports = Path(args.ports_index).absolute()
    if ports.name != 'index.json':
        raise ValueError('--ports-index must select the original index.json')
    index = build_native_reference_flow_publication(ports.parent, args.bundle, args.out,
        expected_native_port_index_sha256=args.ports_sha256)
    path = Path(args.out).absolute() / 'index.json'
    print(json.dumps({'status': 'REFERENCE_GROUP_INDEX_PUBLISHED', 'index': str(path),
        'sha256': sha256(path.read_bytes()).hexdigest(), 'summary': _flow_summary(index),
        'elapsed_s': time.monotonic() - started, 'whole_model_established': False,
        'content_versions_or_causal_def_use_proved': False}))
    return 0


def query_native_reference_flow_cli(args):
    import re
    from scar.trace.native_reference_flow import read_native_reference_flow_index, query_native_reference_flow_upstream
    started = time.monotonic()
    path, ports = Path(args.index).absolute(), Path(args.ports_index).absolute()
    if path.name != 'index.json' or ports.name != 'index.json':
        raise ValueError('flow and port indexes must select their original index.json')
    if re.fullmatch(r'(?:0|[1-9][0-9]*)(?:/(?:0|[1-9][0-9]*))*', args.input_path) is None:
        raise ValueError('--input-path needs canonical ordered indices, for example 0 or 0/1')
    index, _ = read_native_reference_flow_index(path.parent, expected_sha256=args.sha256)
    if not 0 <= args.ordinal < index.source_nodes:
        raise ValueError('--ordinal must select an original source node')
    bundle = BundlePartitions(args.bundle)
    record = bundle.selected_records('evidence', 'instances', (args.ordinal,))[0]['record']
    instance = decode(OperationInstance, record)
    flows = query_native_reference_flow_upstream(path.parent, ports.parent, args.bundle, instance,
        tuple(int(part) for part in args.input_path.split('/')), expected_flow_index_sha256=args.sha256,
        expected_native_port_index_sha256=args.ports_sha256, max_candidates=args.max_candidates)
    result = {'schema': 'scar.native-reference-flow-query', 'schema_version': 1,
        'index': {'uri': str(path), 'sha256': args.sha256}, 'summary': _flow_summary(index),
        'consumer': instance.id.wire, 'input_path': args.input_path, 'flows': encode(flows),
        'matched_candidates': len(flows), 'ordering_basis': 'ETO_SOURCE_ORDINAL_ONLY',
        'qualification': 'SAME_PROVIDER_REFERENCE_AND_DESCRIPTOR_CANDIDATES',
        'content_versions_or_causal_def_use_proved': False, 'whole_model_established': False,
        'transformation_authorized': False, 'elapsed_s': time.monotonic() - started}
    payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if args.out:
        with Path(args.out).open('x', encoding='utf-8') as stream:
            stream.write(payload)
    else:
        print(payload, end='')
    return 0
