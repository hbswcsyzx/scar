"""Independent stdlib audit of actual capture identities and retained records."""
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
RESULT = HERE / 'result'


def read(path):
    with (gzip.open(path, 'rt') if path.suffix == '.gz' else path.open()) as stream:
        return json.load(stream)


def digest(path):
    result = sha256()
    with path.open('rb') as stream:
        while block := stream.read(1048576):
            result.update(block)
    return result.hexdigest()


def require(value, message):
    if not value:
        raise AssertionError(message)


model = read(RESULT / 'capture-model.json')
capture = Path(model['capture'])
archive_path = capture / 'archive-index.json'
archive = {row['logical_path']: row for row in read(archive_path)['files']} if archive_path.exists() else {}


def verify_raw(artifact):
    logical = Path(artifact['uri'])
    require(logical.resolve().is_relative_to(capture.resolve()), 'raw source escapes capture')
    if logical.exists():
        require(digest(logical) == artifact['sha256'] and logical.stat().st_size == artifact['size_bytes'], 'raw OS artifact')
        return
    row = archive[str(logical)]
    actual = Path(row['actual_path'])
    require(actual.resolve().is_relative_to(capture.resolve()), 'retained source escapes capture')
    require(digest(actual) == row['gzip_sha256'] and actual.stat().st_size == row['compressed_bytes'], 'retention hash/size')
    result, size = sha256(), 0
    with gzip.open(actual, 'rb') as stream:
        while block := stream.read(1048576):
            result.update(block)
            size += len(block)
    require(result.hexdigest() == artifact['sha256'] == row['raw_sha256']
            and size == artifact['size_bytes'] == row['raw_bytes'], 'retained raw OS artifact')
coords_path = RESULT / 'capture-coordinates.json'
coords = read(coords_path)
require(digest(coords_path) == model['coordinate_binding']['sha256'], 'coordinate hash')
require(coords_path.stat().st_size == model['coordinate_binding']['size_bytes'], 'coordinate size')
require(model['run'] == coords['run'], 'run declaration')
require(model['processes'] == coords['processes'], 'process declarations')
require(model['threads'] == coords['threads'], 'thread declarations')
run = coords['run']['id']
processes = {item['id']['wire']: item for item in coords['processes']}
threads = {item['id']['wire']: item for item in coords['threads']}
members = {row['artifact']['sha256']: row['artifact'] for row in coords['membership']}

for artifact in model['outputs']:
    path = RESULT / Path(artifact['path']).relative_to(RESULT)
    require(digest(path) == artifact['stored_sha256'], 'stored output hash')
    require(path.stat().st_size == artifact['stored_bytes'], 'stored output size')


def points(value):
    if type(value) is dict:
        if set(value) == {'run', 'process', 'source'}:
            yield value
        else:
            for child in value.values():
                yield from points(child)
    elif type(value) is list:
        for child in value:
            yield from points(child)


point_counts = {}
for name in ['native/native-memory-lifetimes.json.gz', 'os/os-resources.json.gz']:
    document = read(RESULT / name)
    declared_runs = document.get('runs', [document.get('run')])
    require(declared_runs == [coords['run']], 'fragment changed run')
    for process in document['processes']:
        require(processes.get(process['id']['wire']) == process, 'fragment changed process')
    for thread in document.get('threads', []):
        require(threads.get(thread['id']['wire']) == thread, 'fragment changed thread')
    raw_artifacts = dict(members)
    # The enclosing tracer process is retained as an OS source but is not a
    # proved descendant of the target. Raw provenance is distinct from actor
    # membership: verify those bytes independently, never infer its process.
    for artifact in document.get('artifacts', []):
        verify_raw(artifact)
        raw_artifacts[artifact['sha256']] = artifact
    counts = Counter()
    for point in points(document):
        require(point['run'] == run, 'foreign evidence run')
        actor = point['process']
        require(actor is None or actor['wire'] in processes, 'foreign evidence process')
        artifact = point['source']['artifact']
        require(raw_artifacts.get(artifact['sha256']) == artifact, 'evidence point lacks verified raw artifact')
        counts['checked'] += 1
        counts['unresolved_actor'] += actor is None
        counts['outside_proved_actor_artifacts'] += artifact['sha256'] not in members
    point_counts[name] = dict(counts)
    if name.startswith('native/'):
        require(len(document['target_lifetime_events']) == model['native']['shared_lifetime_points_checked'], 'memory record count')
        require(all(row['at']['process'] == coords['target_process']
                    for row in document['target_lifetime_events']), 'native target actor')
    else:
        require(document['summary'] == read(RESULT / 'os/summary.json'), 'OS summary')
        require(len(document['line_classifications']) == model['os']['physical_lines'], 'OS line conservation')
    del document

run_document = read(capture / 'trace/run.json')
require(run_document['returncode'] == 0, 'target failed')
manifest = read(next((capture / 'trace').glob('execution-evidence.*.json')))
require(manifest['status'] == 'CLOSED' and manifest['failures'] == [], 'native collector failed')
require(manifest['configuration']['experimental_config']['adjust_timestamps'] is False, 'ordering config')
kineto_path = capture / 'trace' / Path(manifest['artifacts']['kineto']['path']).name
if not kineto_path.exists():
    kineto_path = kineto_path.with_suffix(kineto_path.suffix + '.gz')
kineto = read(kineto_path)
categories = Counter(row.get('cat', '') for row in kineto['traceEvents'])
require(dict(categories) == model['native']['category_counts'], 'raw provider categories')
receipts = [row for row in kineto['traceEvents'] if row.get('cat') == 'cpu_instant_event'
            and row.get('name') == '[memory]']
memory_counts = model['native']['memory']['counts']
require(len(receipts) == memory_counts['memory_records'], 'raw memory receipt conservation')
require(sum(row['args']['Bytes'] > 0 for row in receipts) == memory_counts['positive_receipts'], 'raw births')
require(sum(row['args']['Bytes'] < 0 for row in receipts) == memory_counts['negative_receipts'], 'raw frees')
require(model['coordinate_identity_consistent'] is True, 'identity report')
require(model['whole_model_established'] is False, 'false completeness')
require(model['transformation_authorized'] is False, 'false transformation authority')
require(all(row['status'] == 'OPEN' for row in model['coverage_obligations']), 'hidden obligations')
report = {'status': 'PASS', 'scope': 'shared coordinates and record conservation only',
          'stored_outputs_verified': len(model['outputs']), 'point_counts': point_counts,
          'processes': len(processes), 'threads': len(threads),
          'memory_receipts': len(receipts), 'provider_categories': dict(categories),
          'whole_program_verified': False, 'source_data_state_ready_verified': False}
(HERE / 'audit.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
