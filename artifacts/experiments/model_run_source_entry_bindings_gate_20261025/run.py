"""One public source-entry-bindings CLI gate; --prepare opens headers only."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def sha(path):
    value, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        while block := stream.read(1_048_576):
            value.update(block); size += len(block)
    return {'uri': str(path), 'sha256': value.hexdigest(), 'size_bytes': size}


def small(path):
    assert path.is_file() and not path.is_symlink() and path.stat().st_size <= 2_000_000
    return json.loads(path.read_bytes())


def put(path, document):
    with path.open('x') as stream:
        json.dump(document, stream, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def prepare(source, label):
    from scar.analysis.model_run import _PinnedModelInputs
    from scar.analysis.source_entry_run import SourceEntryBindingBudget, _binding_inputs
    assert not (HERE / 'freeze.json').exists()
    reader = _PinnedModelInputs(2_000_000)
    inputs = _binding_inputs(source, reader, SourceEntryBindingBudget())
    assert not inputs['blockers'], inputs['blockers']
    refs = {row['uri']: {key: row[key] for key in ('uri', 'sha256', 'size_bytes')} for row in reader.receipts}
    dependency = small(Path(inputs['dependency_terminal']['uri']))
    bootstrap = small(Path(inputs['bootstrap_terminal']['uri']))
    saved = {row['uri']: row for terminal in (dependency, bootstrap) for stage in terminal['stages']
             for row in stage.get('post_stage', {}).get('stage_outputs', [])}
    admissions = small(Path(inputs['admissions']['uri']))
    declarations = []
    for file in admissions['source_files']:
        declarations.extend((file['snapshot_artifact'], file['source_graph_artifact']))
        for provider in file['providers']:
            declarations.extend(provider[key] for key in ('metadata_artifact', 'record_artifact') if key in provider)
    for declaration in declarations:
        if declaration is not None:
            path = Path(inputs['admissions']['uri']).parent / declaration['path']
            old = saved[str(path)]
            assert path.stat().st_size == old['size_bytes']
            refs[str(path)] = {key: old[key] for key in ('uri', 'sha256', 'size_bytes')}
    for name in ('archive', 'project_archive'):
        manifest = small(Path(inputs[name]['uri']))
        for kind in ('sources', 'modules'):
            for row in manifest[kind].values():
                artifact = row['artifact']
                path = Path(inputs[name]['uri']).parent / artifact['path']
                assert path.stat().st_size == artifact['bytes']
                refs[str(path)] = {'uri': str(path), 'sha256': artifact['sha256'], 'size_bytes': artifact['bytes']}
    for request in inputs['requests']:
        old = request['source_program']
        refs[old['uri']] = {'uri': old['uri'], 'sha256': old['physical_sha256'], 'size_bytes': old['physical_bytes']}
    coordinate = small(Path(inputs['coordinate_profile']['uri']))
    root = Path(inputs['capture'])
    controls = [root / 'archive-index.json', root / 'trace/run.json']
    native = [row for row in coordinate['membership'] if row['artifact']['schema'] == 'scar.execution-evidence-collection']
    assert len(native) == 1
    controls.append(Path(native[0]['local_path']))
    native_meta = small(controls[-1])
    provider = coordinate.get('os_capture_provider')
    if provider is not None:
        controls.extend(Path(row['uri']) for row in (provider['launch'], provider['profile'],
            native_meta['configuration']['os_capture_intent']['intent']))
    for path in controls:
        refs[str(path)] = sha(path)
    put(HERE / 'freeze.json', {'schema': 'scar.model-run-source-entry-binding-cli-freeze/1', 'head_label': label,
        'entry': sha(Path(__file__).resolve()), 'sources': [sha(path) for path in sorted((ROOT / 'scar').rglob('*.py'))],
        'inputs': list(refs.values()), 'source_entry_terminal': inputs['source_entry_terminal'],
        'original_denominators': inputs['original_denominators'], 'successful_programs': len(inputs['requests']),
        'budget': 'independent SourceEntryBindingBudget defaults; all effective values/provenance saved by CLI',
        'metadata_preparation_io': {'stored': reader.stored_bytes, 'decoded': reader.decoded_bytes},
        'raw_graph_decode_lower_compile_target_during_prepare': False, 'runtime_binary_freeze': 'OPEN'})
    print(json.dumps({'status': 'PREPARED_NOT_RUN', 'freeze': sha(HERE / 'freeze.json'),
                      'sources': len(list((ROOT / 'scar').rglob('*.py'))), 'inputs': len(refs)}), flush=True)


def verify(freeze):
    assert sorted(str(path) for path in (ROOT / 'scar').rglob('*.py')) == sorted(row['uri'] for row in freeze['sources'])
    amount = 0
    for expected in (freeze['entry'], *freeze['sources'], *freeze['inputs']):
        actual = sha(Path(expected['uri']))
        assert actual == {key: expected[key] for key in actual}, 'frozen bytes changed: ' + expected['uri']
        amount += actual['size_bytes']
    return amount


def run():
    freeze = small(HERE / 'freeze.json')
    assert not (HERE / 'model').exists()
    result = {'schema': 'scar.model-run-source-entry-binding-cli-gate/1', 'status': 'RUNNING', 'whole_model': 'OPEN'}
    started = time.monotonic()
    try:
        result['precheck_stored_bytes_read'] = verify(freeze)
        from scar.cli import main
        result['cli_exit'] = main(['model-run', '--from-model-run', freeze['source_entry_terminal']['uri'],
                                  '--stage', 'source-entry-bindings', '--out', str(HERE / 'model')])
        model = small(HERE / 'model/model-run.json')
        result.update(model_root=sha(HERE / 'model/model-run.json'), workflow_status=model['status'],
            workflow_attempt=model['attempt'], workflow_terminal=model['terminal'],
            original_denominators=model.get('original_denominators'), source_binding_summary=model.get('source_binding_summary'),
            actual_call_scan=model.get('actual_call_scan'), readonly_activity=model.get('readonly_activity'),
            workflow_failure=model.get('failure'), body_linked_calls=model.get('body_linked_calls'))
        result['postcheck_stored_bytes_read'] = verify(freeze)
        result['status'] = 'ACTUAL_CLI_BODY_ASSOCIATIONS_WITH_OPEN' if result['cli_exit'] == 0 and model['status'] == 'SOURCE_ENTRY_BINDINGS_WITH_OPEN' else 'FAILED'
    except BaseException as error:
        result.update(status='FAILED', failure={'type': type(error).__name__, 'detail': str(error), 'traceback': traceback.format_exc()})
        try:
            result['post_failure_source_input_check_bytes'] = verify(freeze)
        except BaseException as check_error:
            result['post_failure_source_input_check_error'] = str(check_error)
    result['wall_seconds'] = time.monotonic() - started
    put(HERE / 'result.json', result)
    print(json.dumps({'status': result['status'], 'wall_seconds': result['wall_seconds'], 'failure': result.get('workflow_failure', result.get('failure'))}), flush=True)
    return int(result['status'] == 'FAILED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--input', help='immutable SOURCE_ENTRIES terminal/navigation, used only for preparation')
    parser.add_argument('--head-label', default='root supplied; actual source hashes independently pinned')
    args = parser.parse_args()
    if args.prepare:
        if not args.input:
            parser.error('--prepare requires --input')
        prepare(Path(args.input).absolute(), args.head_label)
    else:
        raise SystemExit(run())
