"""Freeze the next retained-capture gate without executing target/compiler/SCAR.

Input selection is an experiment configuration; production publisher discovers
the input programs' identities and current bindings mechanically.
"""
from __future__ import annotations

import argparse
import ast
import gzip
import json
from pathlib import Path
import shutil
import subprocess

from report_archive import receipt, write_json


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXPS = HERE.parent
OLD = EXPS / 'first_stage_current_source_gate_20261023'
CAPTURE = EXPS / 'first_stage_lewm_physical_20261023'
COMPOSITION = EXPS / 'first_stage_partitioned_composition_bindings_20261023/composition/index.json.gz'
ATTACHMENT = EXPS / 'first_stage_dependency_continuation_20261023/result/continuation.json'
BRIDGE = EXPS / 'first_stage_joined_physical_20261023/result/native/dispatch-bridge.json.gz'
COORDINATES = EXPS / 'first_stage_joined_physical_20261023/result/capture-coordinates.json'
CACHE = EXPS / 'first_stage_partitioned_operand_routes_20261023/result/code-witnesses'
PROGRAMS = (
    EXPS / 'first_stage_source_language_bodies_20261023/result/body-11.source-program5.json.gz',
    EXPS / 'first_stage_source_language_bodies_attempt03_20261023/result/body-26.source-program5.json.gz',
)
EXPECTED_RUN = 'capture:1ddea1de4990462b59cf5dd24beb3f120156eb47bca68cfb3f1a63f9f73f2cf0'


def load(path):
    raw = Path(path).read_bytes()
    if str(path).endswith('.gz'):
        raw = gzip.decompress(raw)
    return json.loads(raw)


def inputs():
    previous = load(OLD / 'inputs.json')
    paths = {Path(row['path']) for row in previous['inputs']}
    for row in previous['inputs']:
        if receipt(Path(row['path'])) != row:
            raise ValueError('parent retained input changed: ' + row['path'])
    paths.update(PROGRAMS)
    publication_parent = EXPS / 'first_stage_source_publication_current_20261023'
    paths.update(path for path in (publication_parent / 'result').rglob('*') if path.is_file())
    paths.update(publication_parent / name for name in ('failure.json', 'run.time.txt', 'frozen/producer.json'))
    paths.update(OLD / name for name in (
        'summary.json', 'source-audit.json', 'frozen/producer.json',
        'participating-producer.json', 'artifact-receipts.json',
        'result/source/report.json', 'result/source/bindings.json',
        'inputs.json',
    ))
    for row in load(OLD / 'participating-producer.json')['checked']:
        # The previous producer is retained source evidence, not current code.
        archived = OLD / 'participating-source-evidence' / (row['sha256'] + '.py-source')
        actual = receipt(archived)
        if (actual['sha256'], actual['bytes']) != (row['sha256'], row['bytes']):
            raise ValueError('parent participating producer archive changed')
        paths.add(archived)
    write_json(HERE / 'inputs.json', {
        'schema': 'scar.source-publication-current-gate-inputs', 'schema_version': 1,
        'run': EXPECTED_RUN, 'parent_inputs': receipt(OLD / 'inputs.json'),
        'inputs': [receipt(path) for path in sorted(paths)],
        'source_programs': [receipt(path) for path in PROGRAMS],
        'target_executed': False, 'source_prepared': False, 'code_compiled': False,
        'first_stage_complete': False,
    })
    print(json.dumps({'stage': 'INPUTS_FIXED', 'files': len(paths),
                      'receipt': receipt(HERE / 'inputs.json')}, sort_keys=True))


def freeze():
    directory = HERE / 'frozen'
    directory.mkdir(exist_ok=False)
    for row in load(HERE / 'inputs.json')['inputs']:
        if receipt(Path(row['path'])) != row:
            raise ValueError('fixed gate input changed: ' + row['path'])
    names = subprocess.check_output(['rg', '--files', 'scar'], cwd=ROOT, text=True).splitlines()
    paths = [ROOT / name for name in names if name.endswith('.py')]
    paths += sorted(HERE.glob('*.py')) + [HERE / 'run.sh']
    for path in paths:
        if path.suffix == '.py':
            ast.parse(path.read_bytes(), filename=str(path))
    (directory / 'implementation.patch').write_bytes(subprocess.check_output(
        ['git', 'diff', '--binary', '--', 'scar'], cwd=ROOT))
    # Also retain untracked implementation bytes before execution, so an early
    # failed gate stays reproducible after a later fix. A diff alone omits them.
    archived = directory / 'candidate-source-evidence'
    archived.mkdir()
    module_receipts = [receipt(path) for path in sorted(set(paths))]
    for row in module_receipts:
        target = archived / (row['sha256'] + '.py-source')
        if not target.exists():
            shutil.copyfile(row['path'], target)
    write_json(directory / 'producer.json', {
        'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'modules': module_receipts,
        'fixed_inputs': receipt(HERE / 'inputs.json'),
        'additional_inputs': [receipt(OLD / 'result/capture-coordinates.json')],
        'candidate_unused_modules_not_authority': True,
        'target_executed': False, 'source_prepared': False, 'code_compiled': False,
    })
    print(json.dumps({'stage': 'FROZEN', 'receipt': receipt(directory / 'producer.json')}, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=('inputs', 'frozen'), required=True)
    args = parser.parse_args()
    inputs() if args.phase == 'inputs' else freeze()
