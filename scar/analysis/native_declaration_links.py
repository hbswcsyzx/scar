"""Connect existing native graph fragments to data and optional GPU resources.

Only qualified relations are written. The existing program, execution, metadata
and work fragments retain their identities; no workload or native graph is run
or rebuilt here.
"""
from __future__ import annotations

from collections import Counter
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import gzip
import json
import time

from scar.analysis.native_declaration_pipeline import _write
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import decode, encode, loads

SCHEMA = 'scar.native-declaration-links'


def _document(artifact, maximum=4_000_000):
    artifact.__post_init__()
    p = Path(artifact.uri)
    if (p != p.resolve() or p.is_symlink() or not p.is_file()
            or p.stat().st_size != artifact.size_bytes or artifact.size_bytes > maximum):
        raise ValueError('bounded canonical artifact required')
    raw = p.read_bytes()
    if len(raw) != artifact.size_bytes or sha256(raw).hexdigest() != artifact.sha256:
        raise ValueError('native link input artifact changed')
    doc = loads(raw.decode())
    if type(doc) is not dict or doc.get('schema') != artifact.schema:
        raise ValueError('native link input schema differs')
    return doc


def _relations(path, ports, connections, *, max_line_bytes=4_000_000):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw_hash, raw_bytes, records = sha256(), 0, 0
    with path.open('xb') as output:
        with gzip.GzipFile(fileobj=output, mode='wb', filename='', compresslevel=1, mtime=0) as packed:
            for family, rows in (('INPUT_METADATA', ports), ('RESOURCE_WORK', connections)):
                for record in rows:
                    raw = (json.dumps({'family': family, 'record': encode(record)},
                        sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
                    if len(raw) > max_line_bytes:
                        raise ValueError('native link row exceeds output record budget')
                    packed.write(raw); raw_hash.update(raw); raw_bytes += len(raw); records += 1
    digest = sha256()
    with path.open('rb') as source:
        while chunk := source.read(1_048_576):
            digest.update(chunk)
    return {'path': str(path), 'stored_bytes': path.stat().st_size, 'stored_sha256': digest.hexdigest(),
            'decoded_bytes': raw_bytes, 'decoded_sha256': raw_hash.hexdigest(), 'records': records}


def publish_native_declaration_links(pipeline: ProviderArtifact, navigation: ProviderArtifact,
        out_dir, *, resource_index=None, work_manifest=None, source_shards=None,
        max_input_bytes=32_000_000_000, max_output_bytes=1_000_000_000, max_seconds=2400,
        progress=None):
    from scar.analysis.native_declaration_interfaces import NativeDeclarationBudget, NativeDeclarationReadSession
    from scar.analysis.native_declaration_inputs import NativeDeclarationInputBudget, NativeDeclarationInputSession

    if any(type(n) is not int or n <= 0 for n in (max_input_bytes, max_output_bytes, max_seconds)):
        raise ValueError('positive native link budgets required')
    if (resource_index is None) != (work_manifest is None):
        raise ValueError('resource index and work manifest must be supplied together')
    if pipeline.schema != 'scar.native-declaration-pipeline':
        raise ValueError('published native declaration pipeline required')
    parent = _document(pipeline)
    if parent['status'] != 'PUBLISHED':
        raise ValueError('native declaration source pipeline is not closed')
    selected = parent['shards']
    if source_shards is not None:
        if (type(source_shards) is not tuple or not source_shards
                or any(type(n) is not int or n < 0 for n in source_shards)
                or len(set(source_shards)) != len(source_shards)):
            raise ValueError('source shard subset must contain unique original shard indices')
        selected = [r for r in selected if r['source_shard'] in source_shards]
        if {r['source_shard'] for r in selected} != set(source_shards):
            raise ValueError('source shard is absent from the original pipeline')
    root = Path(out_dir).absolute()
    if root != root.resolve() or root.exists():
        raise ValueError('fresh canonical native links output directory required')
    root.mkdir(parents=True)
    start = time.monotonic()
    result = {'schema': SCHEMA, 'schema_version': 1, 'status': 'RUNNING',
        'native_pipeline': encode(pipeline), 'metadata_navigation': encode(navigation),
        'declared_operation_rows': parent['declared_operation_rows'],
        'declared_input_ports': parent['declared_input_ports'], 'shards': [],
        'selected_source_shards': [r['source_shard'] for r in selected],
        'metadata_status_counts': {}, 'processed_operation_rows': 0, 'processed_input_ports': 0,
        'resource_connections': 0, 'resource_join_requested': resource_index is not None,
        'whole_model_established': False, 'transformation_authorized': False,
        'scope': 'exact native port/metadata/provider-work relations; no content equality or ready proof'}
    statuses, stored = Counter(), 0
    try:
        with ExitStack() as stack:
            inputs = stack.enter_context(NativeDeclarationInputSession(navigation,
                budget=NativeDeclarationInputBudget(max_seconds=max_seconds)))
            metadata_bytes = inputs.measurements['stored_bytes'] + inputs.measurements['decoded_bytes']
            if metadata_bytes >= max_input_bytes:
                raise ValueError('native links combined input budget exhausted by metadata')
            reader = stack.enter_context(NativeDeclarationReadSession(decode(ProviderArtifact, parent['catalog']),
                budget=NativeDeclarationBudget(max_input_bytes=max_input_bytes-metadata_bytes,
                    max_seconds=max_seconds)))
            resources = None
            if resource_index is not None:
                from scar.analysis.native_declaration_resources import NativeResourceBudget, NativeDeclarationResourceSession
                work = _document(work_manifest)
                coordinates = decode(ProviderArtifact, work['coordinates'])
                if not Path(coordinates.uri).is_absolute():
                    # A work factory can retain a memory: locator for the
                    # same coordinate bytes already published by this native
                    # pipeline. Reuse that exact receipt, never invent a file.
                    retained = decode(ProviderArtifact, parent['coordinates'])
                    if (retained.sha256, retained.size_bytes, retained.schema) != (
                            coordinates.sha256, coordinates.size_bytes, coordinates.schema):
                        raise ValueError('work memory coordinates have no identical retained pipeline artifact')
                    coordinates = retained
                resources = stack.enter_context(NativeDeclarationResourceSession(resource_index, work_manifest,
                    coordinates,
                    budget=NativeResourceBudget(max_input_bytes=max_input_bytes,
                        max_seconds=max_seconds, max_connections=100_000)))
                result['resource_index'], result['work_manifest'] = encode(resource_index), encode(work_manifest)
            for shard in selected:
                source = decode(ProviderArtifact, shard['artifact'])
                document = _document(source)
                if (document['catalog'] != parent['catalog'] or document['index'] != parent['index']
                        or document['source_shard_index'] != shard['source_shard']):
                    raise ValueError('native source shard belongs to another pipeline')
                for number, item in enumerate(document['fragments']):
                    if time.monotonic() - start > max_seconds:
                        raise TimeoutError('native links whole wall budget exceeded')
                    fragment = decode(ProviderArtifact, item)
                    view = reader.read_fragment(fragment)
                    ports = inputs.join_fragment(view)
                    work = None if resources is None else resources.query_view(view)
                    connections = () if work is None else work['connections']
                    source_bytes = reader.measurements['stored_bytes'] + reader.measurements['decoded_bytes']
                    resource_bytes = 0 if resources is None else resources.meter.stored + resources.meter.decoded
                    if source_bytes + metadata_bytes + resource_bytes > max_input_bytes:
                        raise ValueError('native links combined source input budget exceeded')
                    if len(ports) != sum(len(r.inputs) for r in view.occurrences):
                        raise ValueError('native input join omitted an original ordered input')
                    relative = Path('relations') / f'{shard["source_shard"]:06d}' / f'{number:06d}.jsonl.gz'
                    reference = _relations(root / relative, ports, connections)
                    stored += reference['stored_bytes']
                    if stored > max_output_bytes:
                        raise ValueError('native links stored output budget exceeded')
                    reference['path'] = str(relative)
                    reference.update(source_shard=shard['source_shard'], source_fragment=item,
                        native_operations=len(view.occurrences), input_ports=len(ports),
                        resource_connections=len(connections))
                    result['shards'].append(reference)
                    statuses.update(r.status for r in ports)
                    result['processed_operation_rows'] += len(view.occurrences)
                    result['processed_input_ports'] += len(ports)
                    result['resource_connections'] += len(connections)
                    result['metadata_status_counts'] = dict(statuses)
                    if progress is not None:
                        progress({k: result[k] for k in ('processed_operation_rows',
                            'processed_input_ports', 'resource_connections', 'metadata_status_counts')})
            if source_shards is None and (result['processed_operation_rows'] != parent['processed_operation_rows']
                    or result['processed_input_ports'] != parent['canonical_input_ports']):
                raise ValueError('native link publication lost source pipeline rows or input ports')
            result['input_measurements'] = dict(inputs.measurements)
            result['native_measurements'] = dict(reader.measurements)
            if resources is not None:
                result['resource_measurements'] = resources.meter.finish()
            result['status'] = 'PUBLISHED'
    except BaseException as error:
        result.update(status='FAILED_PARTIAL_RETAINED', failure={'type': type(error).__name__, 'detail': str(error)})
        raise
    finally:
        result.update(elapsed_seconds=time.monotonic()-start, stored_relation_bytes=stored,
            unprocessed_operation_rows=result['declared_operation_rows']-result['processed_operation_rows'])
        artifact = _write(root / 'manifest.json', result, SCHEMA)
    return artifact


def build_native_links_cli(args):
    def artifact(path, digest, schema):
        p = Path(path).absolute()
        return ProviderArtifact(str(p), digest, p.stat().st_size, schema)
    resource_args = (args.resource_index, args.resource_sha256, args.work_manifest, args.work_sha256)
    if any(resource_args) and not all(resource_args):
        raise ValueError('all resource index/work manifest arguments required together')
    ref = publish_native_declaration_links(
        artifact(args.pipeline, args.pipeline_sha256, 'scar.native-declaration-pipeline'),
        artifact(args.navigation, args.navigation_sha256, 'scar.native-input-port-navigation'), args.out,
        resource_index=None if not all(resource_args) else artifact(args.resource_index, args.resource_sha256,
            'scar.native-work-resource-locator-index'),
        work_manifest=None if not all(resource_args) else artifact(args.work_manifest, args.work_sha256,
            'scar.native-activity-work-report'),
        source_shards=None if args.source_shard is None else tuple(args.source_shard),
        max_input_bytes=args.max_input_bytes, max_output_bytes=args.max_output_bytes, max_seconds=args.max_seconds,
        progress=lambda record: print(json.dumps({'schema': SCHEMA, 'progress': record}), flush=True))
    print(json.dumps({'manifest': encode(ref), 'whole_model_established': False}), flush=True)
    return 0


def register_native_links_command(sub):
    parser = sub.add_parser('build-native-links',
        help='join every existing native fragment to input metadata and optional same-Run GPU resources')
    for name in ('pipeline', 'pipeline-sha256', 'navigation', 'navigation-sha256', 'out'):
        parser.add_argument('--' + name, required=True)
    for name in ('resource-index', 'resource-sha256', 'work-manifest', 'work-sha256'):
        parser.add_argument('--' + name)
    parser.add_argument('--source-shard', type=int, action='append', help='explicit bounded subset; whole denominator retained')
    parser.add_argument('--max-input-bytes', type=int, default=32_000_000_000)
    parser.add_argument('--max-output-bytes', type=int, default=1_000_000_000)
    parser.add_argument('--max-seconds', type=int, default=2400)
    parser.set_defaults(func=build_native_links_cli)
