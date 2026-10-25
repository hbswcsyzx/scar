"""Freeze exact input/producer bytes; never import SCAR or use Git.

Input hashing reads physical artifacts, including raw files, without interpreting
raw observations. This command does not run the current source/dispatch/SBA gate.
"""
from __future__ import annotations
import argparse
import ast
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys

from config import (HERE, ROOT, OLD, BASELINE, REVISION, ANCESTOR, PUBLISHED,
    COMPOSITION, CAPTURE, ATTACHMENT, BRIDGE, PROFILE, CACHE, STALE_SOURCE,
    EXPECTED_RUN, EXPECTED_PUBLISHED_SHA256, EXPECTED_ANCESTOR_PRODUCERS, BUDGETS,
    FRAME_BUDGET, OPERAND_BUDGET, ROUTE_BUDGET)
from report_archive import receipt, write_json


def ordinary(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve(strict=True) != path or path.is_symlink() or not path.is_file():
        raise ValueError('not an exact ordinary canonical file: ' + str(path))
    return path


def load(path, *, limit=BUDGETS['metadata_decoded_bytes']):
    path = ordinary(Path(path))
    if path.stat().st_size > limit:
        raise ValueError('metadata stored byte ceiling exceeded: ' + str(path))
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('metadata decoded byte ceiling exceeded: ' + str(path))
    return json.loads(raw)


def check(row):
    path = ordinary(Path(row['path']))
    if path.stat().st_size > BUDGETS['input_file_bytes'] or receipt(path) != row:
        raise ValueError('fixed input differs or exceeds byte ceiling: ' + str(path))


def tree(directory):
    if directory.is_symlink() or directory.resolve(strict=True) != directory:
        raise ValueError('input directory is not canonical: ' + str(directory))
    paths = list(directory.rglob('*'))
    if any(path.is_symlink() for path in paths):
        raise ValueError('symlink in input tree: ' + str(directory))
    return sorted(str(path) for path in paths if path.is_file())


def inputs():
    paths = set()
    # Preserve the complete established raw/source/artifact denominator. The
    # attempt04 list is only immutable input evidence, never a resume source.
    for parent in (OLD, BASELINE):
        document = load(parent / 'inputs.json')
        paths.add(str(parent / 'inputs.json'))
        for row in document['inputs']:
            check(row); paths.add(row['path'])
    for parent in (REVISION, ANCESTOR):
        ledger = load(parent / 'artifact-receipts.json')
        paths.add(str(parent / 'artifact-receipts.json'))
        for row in ledger['artifacts']:
            path = Path(row['path'])
            path = path if path.is_absolute() else parent / path
            expected = {**row, 'path': str(path)}
            check(expected); paths.add(str(path))
    # Namespaces in the revision summary include both replacements and retained
    # historical expectations. Freeze their original artifacts without loading
    # the bad historical graph through a typed language/lifetime validator.
    def artifacts(value):
        if type(value) is dict:
            if type(value.get('uri')) is str:
                path = Path(value['uri'])
                if path.is_absolute() and path.is_file():
                    ordinary(path); paths.add(str(path))
            for item in value.values(): artifacts(item)
        elif type(value) is list:
            for item in value: artifacts(item)
    artifacts(load(REVISION / 'summary.json'))
    for path in tree(PUBLISHED): paths.add(path)
    for name in ('report.json', 'bindings.json'):
        paths.add(str(OLD / 'result/source' / name))
        paths.add(str(STALE_SOURCE / name))
    paths.update(str(OLD / name) for name in ('frozen/producer.json',
        'participating-producer.json', 'summary.json'))
    for row in load(OLD / 'participating-producer.json')['checked']:
        path = OLD / 'participating-source-evidence' / (row['sha256'] + '.py-source')
        actual = receipt(ordinary(path))
        if (actual['sha256'], actual['bytes']) != (row['sha256'], row['bytes']):
            raise ValueError('original participating archive changed')
        paths.add(str(path))
    paths.update(map(str, (COMPOSITION, ATTACHMENT, BRIDGE, PROFILE,
        BASELINE / 'dynamic-audit.json', BASELINE / 'summary.json')))
    for directory in (CAPTURE / 'trace', CACHE): paths.update(tree(directory))
    if len(paths) > BUDGETS['input_files']:
        raise ValueError('input file denominator exceeds independent ceiling')
    rows, total = [], 0
    for name in sorted(paths):
        path = ordinary(Path(name))
        if not path.is_relative_to(ROOT / 'artifacts'):
            raise ValueError('only original artifact inputs are allowed: ' + name)
        if path.stat().st_size > BUDGETS['input_file_bytes']:
            raise ValueError('input physical byte ceiling exceeded')
        row = receipt(path); rows.append(row); total += row['bytes']
        if total > BUDGETS['input_total_bytes']:
            raise ValueError('total fixed-input byte ceiling exceeded')
    for path, sha in EXPECTED_PUBLISHED_SHA256.items():
        if receipt(path)['sha256'] != sha:
            raise ValueError('official published snapshot differs: ' + path)
    write_json(HERE / 'inputs.json', {
        'schema': 'scar.source-revision-current-inputs', 'schema_version': 1,
        'run': EXPECTED_RUN, 'inputs': rows, 'physical_input_bytes': total,
        'directories': {str(p): tree(p) for p in (CAPTURE / 'trace', CACHE, PUBLISHED)},
        'previous_source_directory': str(OLD / 'result/source'),
        'coordinate_profile_uri': str(PROFILE), 'dispatch_bridge_uri': str(BRIDGE),
        'published_composition_uri': str(COMPOSITION), 'readonly_code_witness_uri': str(CACHE),
        'resume_source_directory': None, 'budgets': BUDGETS,
        'frame_budget': FRAME_BUDGET, 'operand_budget': OPERAND_BUDGET, 'route_budget': ROUTE_BUDGET,
        'physical_raw_artifact_hashing_performed': True, 'raw_observation_scan_performed': False,
        'source_prepared': False, 'source_lowered': False, 'code_compiled': False,
        'target_executed': False, 'first_stage_complete': False,
    })
    print(json.dumps({'stage': 'INPUTS_FIXED', 'files': len(rows),
        'physical_bytes': total, 'receipt': receipt(HERE / 'inputs.json')}, sort_keys=True))


def frozen():
    fixed = load(HERE / 'inputs.json')
    for row in fixed['inputs']: check(row)
    for name, sha in EXPECTED_ANCESTOR_PRODUCERS.items():
        if receipt(ROOT / name)['sha256'] != sha:
            raise ValueError('reviewed ancestor producer changed: ' + name)
    for directory, names in fixed['directories'].items():
        if tree(Path(directory)) != names: raise ValueError('fixed input tree changed')
    paths = sorted(set((ROOT / 'scar').rglob('*.py')) | set(HERE.glob('*.py'))
        | {ROOT / 'sitecustomize.py', HERE / 'prepare.sh', HERE / 'run.sh'})
    rows, total = [], 0
    for path in paths:
        ordinary(path)
        if path.suffix == '.py': ast.parse(path.read_bytes(), filename=str(path))
        row = receipt(path); rows.append(row); total += row['bytes']
    if total > BUDGETS['producer_source_bytes']:
        raise ValueError('producer source byte ceiling exceeded')
    directory = HERE / 'frozen'; directory.mkdir(exist_ok=False)
    archive = directory / 'candidate-source-evidence'; archive.mkdir()
    for row in rows:
        target = archive / (row['sha256'] + '.py-source')
        if not target.exists(): shutil.copyfile(row['path'], target)
    write_json(directory / 'producer.json', {
        'schema': 'scar.source-revision-current-producer', 'schema_version': 1,
        'modules': rows, 'fixed_inputs': receipt(HERE / 'inputs.json'),
        'python': sys.version, 'python_executable': sys.executable,
        'ancestor_frozen_source_sha256': EXPECTED_ANCESTOR_PRODUCERS,
        'reported_root_commits_for_navigation_only': ['366dd09c', '1e262f80'],
        'producer_identity_is_exact_bytes_not_head': True,
        'all_scar_candidates_frozen': True, 'unused_candidates_not_authority': True,
        'raw_observation_scan_performed': False, 'target_executed': False,
        'source_prepared': False, 'source_lowered': False, 'code_compiled': False,
    })
    print(json.dumps({'stage': 'FROZEN', 'receipt': receipt(directory / 'producer.json')}, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=('inputs', 'frozen'), required=True)
    args = parser.parse_args()
    inputs() if args.phase == 'inputs' else frozen()
