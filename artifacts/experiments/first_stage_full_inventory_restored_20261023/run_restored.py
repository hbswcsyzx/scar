"""SUPERSEDED, NEVER EXECUTED: original proposed monolithic recovery route.

This is a materialized-result recovery experiment, not source re-lowering and
not a relaxed public validator. No failed request falls back to construction.
"""
from functools import wraps
import gzip
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import time

from scar import cli
from scar.analysis import program_lowering
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
OUTPUT = HERE / 'inventory.json.gz'
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
        require(old_hash == current_hash, 'source producer changed: ' + name)
        producer_records.append({'path': name, 'original_commit': original_base,
            'original_sha256': old_hash, 'current_sha256': current_hash, 'equal': True})
    return original_base


def verify_argv():
    expected = ['inventory-program', '/home/zyf/AAA/le-wm/run_inference.py',
        '--project-root', '/home/zyf/AAA/le-wm', '--body-profile', 'environment',
        '--calls', 'artifacts/experiments/first_stage_lewm_dispatch_20261023/trace',
        '--out', str(OUTPUT.relative_to(ROOT)), '--max-files', '256',
        '--max-lowered-bodies', '4096', '--max-operations', '100000',
        '--max-call-trace-bytes', '256000000', '--max-call-trace-lines', '300000',
        '--max-call-trace-events', '250000', '--max-call-references', '2000000',
        '--max-call-report-bytes', '1000000000']
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


original_write = cli._write_call_document


@wraps(original_write)
def write_inventory(output, document, max_bytes):
    global published
    require(Path(output).resolve() == OUTPUT, 'recovery writer received a different output')
    require(consumed == EXPECTED_COUNT, 'refusing publication before all original bodies are consumed')
    require(hash_file(index_path) == original_index_receipt, 'checkpoint index changed during recovery')
    require(max_bytes == 1000000000, 'independent output limit differs from approved 1GB')
    require(document['summary']['body_statuses'].get('LOWERED_WITH_GAPS', 0) == graph_count,
            'recovered graph was rejected by the unchanged inventory interface validator')
    original_write(output, document, max_bytes)
    published = True
    write('inventory_publish', 'END', restored_bodies=consumed, graph_bodies=graph_count,
          summary=document['summary'])


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
    write('checkpoint_preflight', 'END', count=len(rows),
          graph_returns=sum(row['recovered'] for row in rows),
          raw_bytes=sum(row['raw_bytes'] for row in rows), index=original_index_receipt)
    (HERE / 'producer.json').write_text(json.dumps({'original_base': original_base,
        'current_base': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'original_patch': hash_file(ORIGINAL / 'implementation.patch'),
        'original_wrapper': hash_file(ORIGINAL / 'run_progress.py'),
        'recovery_wrapper': hash_file(Path(__file__)), 'production_modules': producer_records,
        'original_checkpoints': original_index_receipt,
        'body_construction': 'REUSED_MATERIALIZED_ORIGINAL_RETURNS',
        'source_preparation': 'UNCHANGED_PUBLIC_PREPARE_AND_CALL_SEED_QUEUE',
        'public_graph_and_overlay_validation': 'FULL',
        'fresh_body_lowering_performed': False,
        'whole_program_established': False}, indent=2) + '\n')
    program_lowering.PreparedSource.lower = restore_body
    cli._write_call_document = write_inventory
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
        'output': hash_file(OUTPUT) if published else None,
        'source_snapshots': source_snapshots, 'whole_program_established': False}, indent=2) + '\n')
    log.close()
