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
