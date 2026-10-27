"""Stdlib archive receipts and qualified original-reference extraction only."""
import gzip
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXPERIMENTS = HERE.parent


def read_program(path):
    raw = path.read_bytes()
    decoded = gzip.decompress(raw)
    return json.loads(decoded), {'uri': str(path), 'physical_sha256': sha256(raw).hexdigest(),
        'physical_bytes': len(raw), 'decoded_sha256': sha256(decoded).hexdigest(), 'decoded_bytes': len(decoded),
        'representation': 'scar.source-program/5'}


references = []
programs = [EXPERIMENTS / 'first_stage_source_language_bodies_20261023/result/body-11.source-program5.json.gz',
            HERE / 'result/body-26.source-program5.json.gz']
for path in programs:
    doc, artifact = read_program(path)
    graph = doc['graph']
    namespace = {'artifact': {'uri': artifact['uri'], 'decoded_sha256': artifact['decoded_sha256']},
        'representation': 'scar.program-graph/' + str(graph['schema_version']), 'record_pointer': '#/graph',
        'body': {'definition': doc['interface']['definition'], 'entry': doc['metadata']['entry'],
                 'source': doc['structured']['source']}}
    operations = {row['id']['wire']: row for row in graph['operations']}
    source_links = {row['operation']['wire']: row for row in doc['metadata']['operation_links']}
    index_reads = []
    for row in graph['state_address_refinements']:
        key = row['site']['operation']['wire']
        if source_links[key]['opcode'] == 'index':
            operation = operations[key]
            index_reads.append({'operation': operation['id'], 'source': source_links[key],
                'uses': operation['uses'], 'invoke_arguments': operation['invoke_arguments'],
                'completions': operation['completions'], 'terminator': operation['terminator'],
                'partial_address': row, 'effects_complete': operation['effects_complete']})
    references.append({'artifact': artifact, 'namespace': namespace, 'root': graph['root'],
        'operation_count': len(operations), 'source': doc['metadata']['source'],
        'language_shapes': {key: doc['language'][key] for key in ('unpackings', 'slices', 'constants')},
        'index_reads': index_reads,
        'reference_scope': 'archived static SourceProgram5 graph; not inventory checkpoint/Run activation'})
(HERE / 'original-port-references.json').write_text(json.dumps({'scope': 'stdlib extraction, not public full-codec replay',
    'references': references, 'bare_local_ids_globally_merged': False,
    'runtime_code_instance_established': False, 'current_run_integrated': False}, indent=2) + '\n')

directories = ['first_stage_source_language_implementation_20261023',
    'first_stage_source_language_bodies_20261023',
    'first_stage_source_language_bodies_attempt02_20261023',
    'first_stage_source_language_bodies_attempt03_20261023']
rows = []
for name in directories:
    for path in sorted((EXPERIMENTS / name).rglob('*')):
        if path.is_file() and path != HERE / 'artifact-receipts.json':
            raw = path.read_bytes()
            rows.append({'path': str(path.relative_to(ROOT)), 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)})
(HERE / 'artifact-receipts.json').write_text(json.dumps({'scope': 'stored-byte SHA/size receipts only',
    'artifacts': rows, 'artifact_count': len(rows), 'total_bytes': sum(row['bytes'] for row in rows)}, indent=2) + '\n')
print(json.dumps({'artifacts': len(rows), 'bytes': sum(row['bytes'] for row in rows),
    'graph_reference_count': len(references), 'index_read_records': sum(len(row['index_reads']) for row in references)}))
