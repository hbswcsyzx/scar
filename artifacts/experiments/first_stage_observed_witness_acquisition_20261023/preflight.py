"""Read checked worklist fields and public API signatures without compilation."""
from pathlib import Path
from hashlib import sha256
import gzip
import inspect
import json
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
STARTED = time.perf_counter()
from scar.analysis.compiler_witness_archives import (
    CompilerWitnessArchives, CompilerArchiveBudget, ObservedAcquisitionBudget,
    acquire_observed_witnesses, plan_observed_witness_acquisition,
)
from scar.analysis.code_witness import CodeWitnessBudget
from scar.analysis.program_composition import CompositionIndex

PLAN = HERE.parent / 'first_stage_source_frontend_automatic_20261023/plan'
def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()

def checked_plan():
    manifest = json.loads((PLAN / 'manifest.json').read_text())
    if manifest['schema'] != 'scar.source-frontend-worklist-partitions' or manifest['schema_version'] != 1:
        raise ValueError('unsupported original plan schema')
    tables, receipts = {}, []
    for name, declaration in manifest['tables'].items():
        if declaration['uri'] != name + '.json.gz' or declaration['external'] is not False:
            raise ValueError('plan table is not its exact local member')
        path = PLAN / declaration['uri']
        raw = path.read_bytes(); decoded = gzip.decompress(raw)
        if (sha256(raw).hexdigest(), len(raw), sha256(decoded).hexdigest(), len(decoded)) != (
                declaration['physical_sha256'], declaration['physical_bytes'],
                declaration['decoded_sha256'], declaration['decoded_bytes']):
            raise ValueError('plan compressed/decoded receipt differs')
        document = json.loads(decoded)
        if document['schema'] != 'scar.source-frontend-table' or document['schema_version'] != 1:
            raise ValueError('unsupported plan table schema')
        tables[name] = document['rows']
        receipts.append({'path': str(path), 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw),
                         'decoded_sha256': sha256(decoded).hexdigest(), 'decoded_bytes': len(decoded)})
    digest = sha256(canonical({'document': manifest['document'], **tables})).hexdigest()
    if digest != manifest['plan_sha256']:
        raise ValueError('original full worklist digest differs')
    return manifest, tables, receipts

if __name__ == '__main__':
    manifest, tables, receipts = checked_plan()
    selected = [row for row in tables['bodies']
                if row['metadata_status'] == 'CODE_WITNESS_MODULE_VARIANT_MISSING']
    module = ROOT / 'scar/analysis/compiler_witness_archives.py'
    if sha256(module.read_bytes()).hexdigest() != '8b7f9b3875098bd545775f9937d9a89c07ff4136fcdcbf6869fc228583f2c0a0':
        raise ValueError('approved new compiler acquisition module differs')
    report = {'schema': 'scar.observed-witness-acquisition-preflight', 'schema_version': 1,
        'imports_verified': True, 'compile_performed': False, 'source_graphs_read': False,
        'target_executed': False, 'source_prepared': False,
        'plan_full_digest_verified': True, 'plan_sha256': manifest['plan_sha256'], 'tables': receipts,
        'bodies': len(tables['bodies']), 'groups': len(tables['groups']),
        'calls': sum(row['current_calls'] for row in tables['groups']),
        'selected_bodies': len(selected), 'selected_files': len({row['file_index'] for row in selected}),
        'selected_calls': sum(row['current_calls'] for row in selected),
        'selection': 'metadata_status == CODE_WITNESS_MODULE_VARIANT_MISSING',
        'row_keys': list(selected[0]), 'group_keys': list(tables['groups'][0]),
        'definition_keys': list(selected[0]['definition']),
        'api': {function.__name__: str(inspect.signature(function)) for function in (
            CompilerWitnessArchives, CompilerArchiveBudget, ObservedAcquisitionBudget,
            acquire_observed_witnesses, plan_observed_witness_acquisition, CodeWitnessBudget, CompositionIndex)},
        'module': {'path': str(module), 'sha256': sha256(module.read_bytes()).hexdigest()},
        'elapsed_s': time.perf_counter() - STARTED}
    (HERE / 'preflight.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('bodies', 'groups', 'calls', 'selected_bodies',
                                                  'selected_files', 'selected_calls', 'elapsed_s')}))
