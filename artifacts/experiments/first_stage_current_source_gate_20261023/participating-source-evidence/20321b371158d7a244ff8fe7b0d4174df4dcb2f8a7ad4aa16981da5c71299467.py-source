"""Fix retained input bytes / producer SHA without importing SCAR or target."""
import argparse
import ast
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT, EXPS = HERE.parents[2], HERE.parent
CAPTURE = EXPS / 'first_stage_lewm_physical_20261023'
OLD = EXPS / 'first_stage_partitioned_composition_bindings_20261023'
COMPOSITION = OLD / 'composition/index.json.gz'
LAYERS = EXPS / 'first_stage_source_context_20261022/result/source-layers'
INVENTORY = EXPS / 'first_stage_full_inventory_restored_20261023/result/manifest.json'
ATTACHMENT = EXPS / 'first_stage_dependency_continuation_20261023/result/continuation.json'
PARENT = EXPS / 'first_stage_dependency_sources_20261023/result/admissions.json'
BRIDGE = EXPS / 'first_stage_joined_physical_20261023/result/native/dispatch-bridge.json.gz'
COORDINATES = EXPS / 'first_stage_joined_physical_20261023/result/capture-coordinates.json'
CACHE = EXPS / 'first_stage_partitioned_operand_routes_20261023/result/code-witnesses'
SCOPE = EXPS / 'first_stage_current_source_scope_20261023/result.json'
EXPECTED_ATTACHMENT = 'c9ff2f87a0e90ee42297501d256d9d24aeeab60273c6172fe692c0323207173e'
EXPECTED_PARENT = 'fc97075aa66a92758938ad8416347d895e6b18ef0e454053fc7f9c1a7d2f0424'
EXPECTED_CACHE = '56355f7ef10d16d8ab4fb02a84988cf2f0070b75e4cd5fccbf1c86c1ea34170d'
EXPECTED_RUN = 'capture:1ddea1de4990462b59cf5dd24beb3f120156eb47bca68cfb3f1a63f9f73f2cf0'


def receipt(path):
    path = Path(path)
    assert path.is_file() and not path.is_symlink()
    before = path.stat()
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1_048_576), b''):
            digest.update(block); size += len(block)
    after = path.stat()
    assert (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)
    return {'path':str(path.resolve()),'sha256':digest.hexdigest(),'bytes':size}


def document(path,limit=16_000_000):
    assert path.stat().st_size<=limit
    raw=path.read_bytes()
    if path.suffix=='.gz':
        raw=gzip.decompress(raw)
    assert len(raw)<=limit
    return json.loads(raw)


def prepare_inputs():
    assert not (HERE/'inputs.json').exists()
    paths={COMPOSITION,INVENTORY,LAYERS/'index.json',ATTACHMENT,PARENT,BRIDGE,COORDINATES,
           CAPTURE/'archive-index.json',CAPTURE/'trace/execution-evidence.369749.json',CACHE/'manifest.json',SCOPE}
    coordinates=document(COORDINATES)
    assert coordinates['run']['id']['value']==EXPECTED_RUN
    archive=document(CAPTURE/'archive-index.json')
    assert archive['verified_roundtrip'] is True
    relocation={row['logical_path']:row for row in archive['files']}
    for row in coordinates['membership']:
        logical=row['artifact']['uri']
        if logical in relocation:
            path=Path(relocation[logical]['actual_path'])
        else:
            path=Path(row.get('local_path',logical))
        assert path.is_relative_to(CAPTURE)
        paths.add(path)
    attachment=document(ATTACHMENT)
    assert receipt(ATTACHMENT)['sha256']==EXPECTED_ATTACHMENT and receipt(PARENT)['sha256']==EXPECTED_PARENT
    assert Path(attachment['parent']['directory'])==PARENT.parent
    def original_artifacts(value):
        if type(value) is dict:
            if 'origin' in value and type(value.get('artifact')) is dict and 'path' in value['artifact']:
                if value['origin']=='PARENT':
                    assert value['parent_directory']==str(PARENT.parent)
                    assert value['parent_report_raw_sha256']==EXPECTED_PARENT
                    base=PARENT.parent
                else:
                    assert value['origin']=='CONTINUATION'
                    base=ATTACHMENT.parent
                path=base/value['artifact']['path']
                assert path.resolve().is_relative_to(base)
                paths.add(path)
            for child in value.values():original_artifacts(child)
        elif type(value) is list:
            for child in value:original_artifacts(child)
    original_artifacts(attachment)
    for row in document(LAYERS/'index.json')['files']:
        if row['status']=='STORED': paths.add(LAYERS/row['archive'])
    cache=document(CACHE/'manifest.json')
    assert receipt(CACHE/'manifest.json')['sha256']==EXPECTED_CACHE
    assert len(cache['modules'])==len(cache['sources'])==20
    for family in ('modules','sources'):
        for row in cache[family].values():
            path=CACHE/row['artifact']['path']
            actual=receipt(path)
            assert (actual['sha256'],actual['bytes'])==(row['artifact']['sha256'],row['artifact']['bytes'])
            paths.add(path)
    result={'schema':'scar.current-source-gate-fixed-inputs','schema_version':1,
        'run':EXPECTED_RUN,'process_id':369749,'inputs':[receipt(path) for path in sorted(paths)],
        'attachment_raw_sha256':EXPECTED_ATTACHMENT,'parent_raw_sha256':EXPECTED_PARENT,
        'code_witness_manifest_sha256':EXPECTED_CACHE,'source_graphs_prepared':False,
        'scar_imported':False,'target_executed':False,'code_compiled':False,
        'source_versions_refreshed':False,'whole_model_established':False}
    (HERE/'inputs.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print(json.dumps({'phase':'inputs','files':len(paths),'stored_bytes':sum(row['bytes'] for row in result['inputs']),
        'receipt':receipt(HERE/'inputs.json')},sort_keys=True))


def freeze():
    destination=HERE/'frozen';destination.mkdir(exist_ok=False)
    fixed=document(HERE/'inputs.json')
    for original in fixed['inputs']:
        assert receipt(Path(original['path']))==original
    names=subprocess.check_output(['rg','--files','scar'],cwd=ROOT,text=True).splitlines()
    paths=[ROOT/name for name in names if name.endswith('.py')]
    paths += [HERE/name for name in ('prepare.py','run.py','run.sh')]
    modules=[receipt(path) for path in sorted(paths)]
    for name in ('prepare.py','run.py'):
        ast.parse((HERE/name).read_bytes(),filename=name)
    patch=subprocess.check_output(['git','diff','--binary','--','scar'],cwd=ROOT)
    (destination/'implementation.patch').write_bytes(patch)
    result={'revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'modules':modules,'fixed_inputs':receipt(HERE/'inputs.json'),'input_count':len(fixed['inputs']),
        'candidate_unused_modules_not_authority':True,'runtime_imports_not_performed':True}
    (destination/'producer.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print(json.dumps({'phase':'frozen','modules':len(modules),'receipt':receipt(destination/'producer.json')},sort_keys=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=('inputs','frozen'),required=True)
    mode=parser.parse_args().phase
    prepare_inputs() if mode=='inputs' else freeze()
