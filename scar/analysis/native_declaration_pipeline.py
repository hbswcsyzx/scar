"""Orchestrate canonical native interfaces from every declared source shard.

This small root is navigation, not a graph authority. Original program,
execution and evidence IDs stay in the independently readable fragments.
No workload is imported or run, and no dispatch marker is required.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import time

from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import encode, loads


SCHEMA = 'scar.native-declaration-pipeline'


def _write(path, document, schema):
    raw = (json.dumps(document, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False) + '\n').encode()
    with path.open('xb') as stream:
        stream.write(raw)
    return ProviderArtifact(str(path), sha256(raw).hexdigest(), len(raw), schema)


def _read_manifest(artifact):
    if type(artifact) is not ProviderArtifact or artifact.schema != 'scar.native-declaration-shard':
        raise TypeError('native declaration producer must return its typed shard manifest')
    artifact.__post_init__()
    path = Path(artifact.uri)
    if (not path.is_absolute() or path.resolve() != path or path.is_symlink()
            or not path.is_file() or path.stat().st_size != artifact.size_bytes
            or artifact.size_bytes > 4_000_000):
        raise ValueError('native declaration shard manifest absent or too large')
    raw = path.read_bytes()
    if len(raw) != artifact.size_bytes or sha256(raw).hexdigest() != artifact.sha256:
        raise ValueError('native declaration shard manifest changed')
    doc = loads(raw.decode('utf-8'))
    if type(doc) is not dict or doc.get('schema') != artifact.schema:
        raise ValueError('native declaration manifest schema differs')
    return doc


def publish_native_declaration_pipeline(index: ProviderArtifact, bundle, coordinates: ProviderArtifact,
        out_dir, *, budget=None, shards=None, progress=None):
    """Default to all shards; an explicit subset never narrows the denominator.

    The session owns normal source validation and one shared schema catalog.
    This orchestrator checks returned manifest counts and publishes references;
    it does not duplicate all fragments or restore validation from a success bit.
    """
    from scar.analysis.native_declaration_interfaces import NativeDeclarationBudget, NativeDeclarationSession

    if budget is None:
        budget = NativeDeclarationBudget()
    if type(budget) is not NativeDeclarationBudget:
        raise TypeError('native declaration pipeline requires its typed budget')
    for artifact in (index, coordinates):
        if type(artifact) is not ProviderArtifact:
            raise TypeError('original index and coordinates receipts required')
        artifact.__post_init__()
    root = Path(out_dir).absolute()
    if root != root.resolve() or root.exists():
        raise ValueError('native declaration pipeline requires a fresh canonical output directory')
    if shards is not None and (type(shards) is not tuple or not shards
            or any(type(i) is not int or i < 0 for i in shards) or len(set(shards)) != len(shards)):
        raise ValueError('explicit shard selection must be a nonempty tuple of unique nonnegative integers')
    root.mkdir(parents=True)
    started = time.monotonic()
    manifest = {'schema': SCHEMA, 'schema_version': 1, 'index': encode(index),
        'coordinates': encode(coordinates), 'status': 'RUNNING', 'shards': [],
        'whole_model_established': False, 'transformation_authorized': False,
        'completion_selected_count': 0,
        'scope': 'canonical native interfaces only; not whole-program or content/ready proof'}
    totals = {key: 0 for key in ('processed_operation_rows', 'canonical_operation_occurrences',
        'canonical_input_ports', 'conditional_output_ports', 'completion_selected_count')}
    active = None
    try:
        with NativeDeclarationSession(index, bundle, coordinates, budget=budget) as session:
            manifest['bundle'] = encode(session.bundle)
            selected = tuple(range(len(session.index.shards))) if shards is None else tuple(sorted(shards))
            if any(i >= len(session.index.shards) for i in selected):
                raise ValueError('selected source shard is outside the original index')
            manifest.update(declared_operation_rows=session.index.operation_rows,
                declared_source_nodes=session.index.source_nodes,
                classification_counts=session.index.classification_counts,
                indexed_first_source_ordinal=session.index.first_source_ordinal,
                indexed_stop_source_ordinal=session.index.stop_source_ordinal,
                whole_source_range_indexed=(session.index.first_source_ordinal == 0
                    and session.index.stop_source_ordinal == session.index.source_nodes),
                declared_input_ports=session.index.input_ports,
                declared_output_ports=session.index.output_ports,
                declared_shards=len(session.index.shards), selected_shards=list(selected),
                selection='ALL_SOURCE_SHARDS' if shards is None else 'EXPLICIT_SOURCE_SHARDS',
                selected_operation_rows=sum(session.index.shards[i].operation_rows for i in selected))
            catalog = session.prepare_catalog(root / 'catalog', shard_indices=selected)
            manifest['catalog'] = encode(catalog)
            for number in selected:
                active = number
                if time.monotonic() - started > budget.max_seconds:
                    raise TimeoutError('native declaration pipeline wall budget exceeded')
                reference = session.publish_shard(number, root / 'shards' / f'{number:06d}')
                doc = _read_manifest(reference)
                expected = session.index.shards[number].operation_rows
                if any(type(doc.get(k)) is not int or doc[k] != expected for k in
                       ('declared_operation_rows', 'selected_operation_rows', 'processed_operation_rows')):
                    raise ValueError('canonical shard did not retain every original operation row')
                if doc.get('canonical_operation_occurrences') != expected:
                    raise ValueError('canonical shard lacks an occurrence for an original operation')
                for key in totals:
                    value = doc.get(key)
                    if type(value) is not int or value < 0:
                        raise ValueError('invalid native declaration shard count: ' + key)
                    totals[key] += value
                manifest['shards'].append({'source_shard': number, 'artifact': encode(reference)})
                if progress is not None:
                    progress({'source_shard': number, 'completed_shards': len(manifest['shards']),
                              'selected_shards': len(selected), **totals})
            if totals['processed_operation_rows'] != manifest['selected_operation_rows']:
                raise ValueError('canonical native operation totals differ from selected source rows')
            all_shards = len(selected) == len(session.index.shards)
            if all_shards and (totals['canonical_input_ports'] != session.index.input_ports
                    or totals['conditional_output_ports'] != session.index.output_ports):
                raise ValueError('canonical native ports differ from the original whole-index denominator')
            manifest.update(status='PUBLISHED', **totals,
                native_boundaries_complete_for_selection=True,
                all_source_shards_processed=all_shards)
            manifest['input_measurements'] = session.meter.finish()
    except BaseException as error:
        manifest.update(status='FAILED_PARTIAL_RETAINED', **totals,
            failed_source_shard=active, native_boundaries_complete_for_selection=False,
            all_source_shards_processed=False,
            failure={'type': type(error).__name__, 'detail': str(error)})
        raise
    finally:
        manifest['elapsed_seconds'] = time.monotonic() - started
        if 'declared_operation_rows' in manifest:
            manifest['unprocessed_operation_rows'] = (
                manifest['declared_operation_rows'] - totals['processed_operation_rows'])
        artifact = _write(root / 'manifest.json', manifest, SCHEMA)
    return artifact


def build_native_interfaces_cli(args):
    from scar.analysis.native_declaration_interfaces import NativeDeclarationBudget

    def artifact(path, digest, schema):
        path = Path(path).absolute()
        return ProviderArtifact(str(path), digest, path.stat().st_size, schema)

    options = {key: getattr(args, key) for key in NativeDeclarationBudget.__dataclass_fields__}
    receipt = publish_native_declaration_pipeline(
        artifact(args.ports_index, args.ports_sha256, 'scar.native-boxed-port-index'), args.bundle,
        artifact(args.coordinates, args.coordinates_sha256, 'scar.capture-coordinates'), args.out,
        budget=NativeDeclarationBudget(**options),
        shards=None if args.shard is None else tuple(args.shard),
        progress=lambda row: print(json.dumps({'schema': SCHEMA, 'progress': row}), flush=True))
    print(json.dumps({'manifest': encode(receipt), 'whole_model_established': False}), flush=True)
    return 0


def register_native_interface_commands(sub):
    from scar.analysis.native_declaration_interfaces import NativeDeclarationBudget

    parser = sub.add_parser('build-native-interfaces',
        help='build canonical input/output/state boundaries for every native source shard, without dispatch markers')
    for name in ('ports-index', 'ports-sha256', 'bundle', 'coordinates', 'coordinates-sha256', 'out'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--shard', type=int, action='append',
        help='explicit bounded source-shard subset; original whole-index denominator is retained')
    for key, field in NativeDeclarationBudget.__dataclass_fields__.items():
        parser.add_argument('--' + key.replace('_', '-'), type=int, default=field.default)
    parser.set_defaults(func=build_native_interfaces_cli)
