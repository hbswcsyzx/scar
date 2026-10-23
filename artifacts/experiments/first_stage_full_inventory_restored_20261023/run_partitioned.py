"""Resume the original inventory queue using its checksum-bound body returns.

This is a materialized-result recovery experiment, not source re-lowering and
not a relaxed public validator. No failed request falls back to construction.
"""
from functools import wraps
import gzip
import ast
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import time

from scar import cli
from scar.analysis import program_lowering
from scar.analysis.inventory_partitions import (InventoryPartitions, MaterializedBodySource,
    checkpoint_reference, publish_partitioned_inventory)
from scar.analysis.structured_lowering import require_valid_structured_body
from scar.ir.program.codec import loads as load_graph
from scar.ir.program.frames import FrameModel
from scar.ir.program.functions import BodyEntryInterface, BodyLoweringProfile
from scar.ir.program.source import LoweringMetadata
from scar.ir.program.structured import StructuredBodyModel
from scar.ir.record_codec import decode, encode
from scar.ir.v2._validation import record_errors


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ORIGINAL = HERE.parent / 'first_stage_full_inventory_plain_20261023'
CHECKPOINTS = ORIGINAL / 'checkpoints'
OUTPUT = HERE / 'result'
EXPECTED_COUNT = 1627
started = time.perf_counter()
log = (HERE / 'progress.jsonl').open('x', buffering=1)
consumed = 0
graph_count = 0
published = False
exit_code = None
failure = None
producer_records = []
source_snapshots = {}
materialized_bodies = {}
original_checkpoint_references = {}
producer_document = None


class RecoveryIntegrityError(RuntimeError):
    """Escape the inventory's ordinary unsupported-source error recovery."""


def require(condition, message):
    if not condition:
        raise RecoveryIntegrityError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def write(stage, status, **fields):
    log.write(json.dumps({'stage': stage, 'status': status,
                          'elapsed_s': time.perf_counter() - started, **fields}) + '\n')


def hash_file(path):
    digest = sha256()
    count = 0
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
            count += len(chunk)
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': count}


def checked_checkpoint(row):
    path = CHECKPOINTS / row['file']
    require(path.parent == CHECKPOINTS and path.name == f"{row['sequence']:05d}.json.gz",
            'checkpoint filename is not its original numbered file')
    with gzip.open(path, 'rb') as stream:
        payload = stream.read(row['raw_bytes'] + 1)
    require(len(payload) == row['raw_bytes'] and sha256(payload).hexdigest() == row['raw_sha256'],
            'checkpoint raw SHA/size mismatch at ' + row['file'])
    document = json.loads(payload)
    require(set(document) == {'schema', 'schema_version', 'entry', 'source', 'profile',
        'max_operations', 'graph', 'metadata', 'interface', 'frame', 'structured',
        'operations_emitted', 'whole_program_established'}, 'checkpoint field mismatch')
    require(document['schema'] == 'scar.body-construction-checkpoint'
            and document['schema_version'] == 1
            and document['whole_program_established'] is False, 'checkpoint schema/authority mismatch')
    require((document['graph'] is not None) is row['recovered'], 'checkpoint graph/index mismatch')
    require(document['entry'] == row['entry'], 'checkpoint entry/index mismatch')
    return document


def verify_producer():
    original_base = (ORIGINAL / 'base.git.txt').read_text().strip()
    # The original uncommitted patch only touched an experiment audit script.
    # Reject any hidden original production-code delta before using Git blobs.
    original_patch = (ORIGINAL / 'implementation.patch').read_text()
    require('diff --git a/scar/' not in original_patch,
            'original production code had uncommitted changes; reconstruction required')
    paths = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', original_base, '--',
        'scar/analysis', 'scar/ir', 'scar/trace/files.py', 'scar/cli.py'], cwd=ROOT, text=True).splitlines()
    # All source-analysis and IR modules are fixed to the original producer.
    # Capture/import adapters are not invoked by this source-only recovery.
    for name in paths:
        if not name.endswith('.py'):
            continue
        original_bytes = subprocess.check_output(['git', 'show', f'{original_base}:{name}'], cwd=ROOT)
        actual_bytes = (ROOT / name).read_bytes()
        old_hash, current_hash = sha256(original_bytes).hexdigest(), sha256(actual_bytes).hexdigest()
        if name not in {'scar/analysis/dispatch_sources.py', 'scar/cli.py'}:
            require(old_hash == current_hash, 'source producer changed: ' + name)
        elif name == 'scar/cli.py':
            # Appended public commands changed this module, while the invoked
            # inventory implementation, limits and writer must remain exact.
            required_functions = {'_inventory_program', '_inventory_limits', '_runtime_inventory_budget',
                '_context_inventory_budget', '_inventory_analysis_measurements', '_call_budget', '_write_call_document'}
            def functions(payload):
                return {node.name: ast.dump(node, include_attributes=False)
                    for node in ast.parse(payload).body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in required_functions}
            old_functions, current_functions = functions(original_bytes), functions(actual_bytes)
            require(set(old_functions) == required_functions and old_functions == current_functions,
                    'participating original CLI function changed')
        producer_records.append({'path': name, 'original_commit': original_base,
            'original_sha256': old_hash, 'current_sha256': current_hash, 'equal': old_hash == current_hash,
            'excluded_changed_module': name == 'scar/analysis/dispatch_sources.py',
            'participating_cli_functions_verified': name == 'scar/cli.py'})
    return original_base


def verify_argv():
    expected = ['inventory-program', '/home/zyf/AAA/le-wm/run_inference.py',
        '--project-root', '/home/zyf/AAA/le-wm', '--body-profile', 'environment',
        '--calls', 'artifacts/experiments/first_stage_lewm_dispatch_20261023/trace',
        '--out', str(OUTPUT.relative_to(ROOT)), '--max-files', '256',
        '--max-lowered-bodies', '4096', '--max-operations', '100000',
        '--max-call-trace-bytes', '256000000', '--max-call-trace-lines', '300000',
        '--max-call-trace-events', '250000', '--max-call-references', '2000000',
        '--max-call-report-bytes', '256000000']
    require(sys.argv[1:] == expected, 'recovery CLI differs from approved original arguments')
    require(not OUTPUT.exists(), 'refusing to overwrite a recovered inventory')


original_lower = program_lowering.PreparedSource.lower


@wraps(original_lower)
def restore_body(self, entry, *, source=None, max_operations=10000,
                 expand_candidates=True, profile=BodyLoweringProfile.LEGACY):
    global consumed, graph_count
    try:
        require(consumed < len(rows), 'current queue asks for an additional, uncheckpointed body')
        row = rows[consumed]
        document = checked_checkpoint(row)
        write('body_restore', 'BEGIN', sequence=row['sequence'], path=str(self.path), entry=entry)
        require(row['sequence'] == consumed + 1 and str(self.path) == row['path'],
                'current queue path/order differs from checkpoint')
        require(entry == document['entry'] and encode(source) == document['source'],
                'current queue entry/exact source differs from checkpoint')
        require(encode(profile) == document['profile']
                and max_operations == document['max_operations']
                and expand_candidates is False, 'current body construction request differs from checkpoint')
        metadata = decode(LoweringMetadata, document['metadata'])
        require(not record_errors(metadata, LoweringMetadata, 'metadata'), 'invalid metadata record')
        snapshot = self.semantics.sources[str(self.path)]
        fingerprint = 'sha256:' + sha256(self.text.encode()).hexdigest()
        require(metadata.source == snapshot and snapshot.fingerprint == fingerprint
                and source is not None and source.fingerprint == fingerprint,
                'current prepared source snapshot differs from original checkpoint')
        require(metadata.entry == entry, 'body metadata entry mismatch')
        prior = source_snapshots.setdefault(str(self.path), encode(snapshot))
        require(prior == encode(snapshot), 'source changed within recovered queue')
        graph = load_graph(canonical(document['graph'])) if document['graph'] is not None else None
        interface = decode(BodyEntryInterface, document['interface']) if document['interface'] is not None else None
        frame = FrameModel.from_dict(document['frame']) if document['frame'] is not None else None
        structured = decode(StructuredBodyModel, document['structured']) if document['structured'] is not None else None
        require(type(document['operations_emitted']) is int
                and 0 <= document['operations_emitted'] <= max_operations,
                'checkpoint construction operation charge mismatch')
        if graph is None:
            require(interface is None and frame is None and structured is None,
                    'unsupported original body must not acquire an interface/overlay')
        else:
            require(profile is BodyLoweringProfile.STRUCTURED_ENV and frame is None
                    and interface is not None and structured is not None,
                    'materialized body profile/interface mismatch')
            # Ordinary public validation, including independent source-control
            # validation; no sealed-session or graph-validation fast path.
            require_valid_structured_body(structured, graph, interface, metadata,
                                          semantic=self.semantic, control=self.control)
            operations = {operation.id: operation for operation in graph.operations}
            require({link.operation for link in metadata.operation_links} == set(operations),
                    'restored operation correspondence incomplete')
            require({link.value for link in metadata.value_links} == {value.id for value in graph.values},
                    'restored value correspondence incomplete')
            require({(link.operation, link.use) for link in metadata.use_links}
                    == {(operation.id, use.id) for operation in graph.operations for use in operation.uses},
                    'restored ordered-use correspondence incomplete')
            for link in (*metadata.operation_links, *metadata.value_links, *metadata.use_links):
                atom = self.semantic.source_atoms.get(link.source.atom_id)
                require(atom is not None and atom.reference == link.source,
                        'restored correspondence is not in the current prepared source')
            graph_count += 1
        result = program_lowering.LoweredSourceBody(graph, metadata, document['operations_emitted'],
                                                   interface, frame, structured)
        materialized_bodies[id(metadata)] = MaterializedBodySource(result,
            original_checkpoint_references[row['sequence']], row['sequence'])
        # The unchanged inventory subsequently calls its full signature/formal
        # validator and records the original interface in the original builder.
        consumed += 1
        write('body_restore', 'END', sequence=row['sequence'], path=str(self.path), entry=entry,
              raw_sha256=row['raw_sha256'], raw_bytes=row['raw_bytes'], recovered=graph is not None,
              operations=result.operations_emitted, original_materialized_return=True,
              fresh_lower_performed=False)
        return result
    except RecoveryIntegrityError:
        raise
    except Exception as error:
        raise RecoveryIntegrityError(f'recovery validation failed at request {consumed + 1}: {error}') from error


def inventory_partitioned(args):
    global published
    from scar.analysis.program_inventory import inventory_program
    # Same public arguments, source preparation, queue and aggregate budgets.
    # Only serialization is replaced before result.to_dict can duplicate graphs.
    result = inventory_program(args.source, project_root=args.project_root,
        source_roots=args.source_root, **cli._inventory_limits(args),
        runtime_trace=args.trace, runtime_budget=cli._runtime_inventory_budget(args),
        max_compile_attempts=args.max_compile_attempts,
        context_budget=cli._context_inventory_budget(args),
        calls_trace=args.calls, call_budget=cli._call_budget(args),
        body_profile=BodyLoweringProfile.STRUCTURED_ENV)
    require(consumed == EXPECTED_COUNT, 'queue did not consume all original body returns')
    require(hash_file(index_path) == original_index_receipt, 'original checkpoint index changed')
    summary = result.summary()
    require(summary['body_statuses'].get('LOWERED_WITH_GAPS', 0) == graph_count,
            'unchanged inventory rejected a restored body interface')
    require(Path(args.out).resolve() == OUTPUT and not OUTPUT.exists(), 'partition output mismatch')
    # Keep the original source/raw protection even though output is a directory.
    protected = [Path(file.snapshot.path).resolve() for file in result.discovery.files]
    if result.call_sources is not None:
        protected.extend(Path(path).resolve() for path in cli._call_source_inputs(result.call_sources.model))
    require(not any(path == OUTPUT or path.is_relative_to(OUTPUT) for path in protected),
            'partition output would overlap source/raw evidence')
    manifest = publish_partitioned_inventory(result, OUTPUT,
        materialized_bodies=materialized_bodies, producer=producer_document,
        inputs={'original_checkpoint_index': original_index_receipt,
            'original_failed_run': str(ORIGINAL),
            'original_output_error': 'call report exceeds independent write byte ceiling: 256000000',
            'body_validation': 'ordinary public graph codec and complete structured/source overlay',
            'body_construction': 'materialized original return reuse; no fresh lower',
            'inventory_signature_validation': 'unchanged FunctionInterfaceBuilder.record_body',
            'actual_source_preparation': 'fresh source/call seed/discovery/context preparation',
            'raw_calls': encode(result.call_sources.model.files) if result.call_sources else None})
    # This lightweight reader checks every new source/component shard receipt.
    # It never assembles a monolithic ProgramInventory JSON representation.
    archive = InventoryPartitions(OUTPUT)
    for unused in archive.iter_files():
        pass
    for name in manifest['components']:
        archive.component(name)
    published = True
    write('partition_publish', 'END', counts=manifest['counts'], summary=summary,
          max_component_bytes=max(ref['decoded_bytes'] for ref in manifest['components'].values()),
          max_source_bytes=max(ref['decoded_bytes'] for ref in manifest['files']))
    print(json.dumps({'status': 'PARTITIONED_INVENTORY_RESTORED',
        'out': str(OUTPUT / 'manifest.json'), 'counts': manifest['counts'], 'summary': summary,
        'fresh_body_lowering_performed': False, 'whole_program_established': False}))
    return 0


try:
    verify_argv()
    original_base = verify_producer()
    index_path = CHECKPOINTS / 'index.jsonl'
    original_index_receipt = hash_file(index_path)
    payload = index_path.read_bytes()
    require(payload.endswith(b'\n'), 'original checkpoint index is incomplete')
    rows = [json.loads(line) for line in payload.splitlines()]
    require(len(rows) == EXPECTED_COUNT, 'original checkpoint count differs from approved 1627')
    for index, row in enumerate(rows, 1):
        require(row['sequence'] == index, 'original checkpoint sequence is discontinuous')
        checked_checkpoint(row)
        original_checkpoint_references[index] = checkpoint_reference(CHECKPOINTS / row['file'],
            decoded_sha256=row['raw_sha256'], decoded_bytes=row['raw_bytes'])
    write('checkpoint_preflight', 'END', count=len(rows),
          graph_returns=sum(row['recovered'] for row in rows),
          raw_bytes=sum(row['raw_bytes'] for row in rows), index=original_index_receipt)
    producer_document = {'original_base': original_base,
        'current_base': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'original_patch': hash_file(ORIGINAL / 'implementation.patch'),
        'original_wrapper': hash_file(ORIGINAL / 'run_progress.py'),
        'recovery_wrapper': hash_file(Path(__file__)), 'production_modules': producer_records,
        'original_checkpoints': original_index_receipt,
        'body_construction': 'REUSED_MATERIALIZED_ORIGINAL_RETURNS',
        'source_preparation': 'UNCHANGED_PUBLIC_PREPARE_AND_CALL_SEED_QUEUE',
        'public_graph_and_overlay_validation': 'FULL',
        'fresh_body_lowering_performed': False,
        'whole_program_established': False}
    (HERE / 'producer.json').write_text(json.dumps(producer_document, indent=2) + '\n')
    program_lowering.PreparedSource.lower = restore_body
    cli._inventory_program = inventory_partitioned
    exit_code = cli.main()
    require(exit_code == 0 and published and consumed == EXPECTED_COUNT,
            f'public inventory failed or did not publish (exit={exit_code}, consumed={consumed})')
except BaseException as error:
    failure = f'{type(error).__name__}: {error}'
    write('recovery', 'FAILED', detail=failure, consumed=consumed)
    raise
finally:
    (HERE / 'recovery.json').write_text(json.dumps({'status': 'RESTORED' if published and failure is None else 'FAILED',
        'elapsed_s': time.perf_counter() - started, 'cli_exit_code': exit_code,
        'consumed_original_returns': consumed, 'graph_bodies': graph_count,
        'fresh_body_lowering_performed': False, 'failure': failure,
        'output': hash_file(OUTPUT / 'manifest.json') if published else None,
        'source_snapshots': source_snapshots, 'whole_program_established': False}, indent=2) + '\n')
    log.close()
