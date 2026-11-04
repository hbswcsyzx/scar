"""Register accepted frontend bytes without rerunning their semantic stages.

The caller pins a historical acceptance report. Its exact material receipts,
source basis and implementation scope stay authoritative; transportation does
not turn that evidence into a new parser/compiler replay.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import time

from scar.analysis.source_stage import SourceStage, _durable_bytes, _durable_mkdir
from scar.analysis.source_store import source_input_basis
from scar.analysis.static_program import _json, read_static_program


_EVIDENCE = 'HISTORICAL_FRESH_ACCEPTANCE_REUSE'


def _check_output(root, out):
    if (root.resolve() != root or out.resolve() != out or out.is_relative_to(root)
            or out.exists() and (not out.is_dir() or any(out.iterdir()))):
        raise ValueError('registration requires a canonical model and fresh independent report directory')


def _artifact_path(root, descriptor):
    relative = descriptor['path']
    if (type(relative) is not str or not relative or PurePosixPath(relative).is_absolute()
            or '..' in PurePosixPath(relative).parts or str(PurePosixPath(relative)) != relative
            or type(descriptor['bytes']) is not int or descriptor['bytes'] < 0
            or type(descriptor['sha256']) is not str
            or re.fullmatch(r'[0-9a-f]{64}', descriptor['sha256']) is None):
        raise ValueError('registration requires a canonical artifact path and exact byte receipt')
    path = root / relative
    if path.resolve() != path or path.is_symlink():
        raise ValueError('registration artifact cannot traverse a symlink')
    return path


def _transfer_bytes(source, descriptor, destination=None):
    """Bound the read to the pinned size; optionally copy into a fresh inode."""
    remaining, digest = descriptor['bytes'], sha256()
    with source.open('rb') as original:
        while True:
            chunk = original.read(min(1024 * 1024, remaining + 1))
            if not chunk:
                break
            remaining -= len(chunk)
            if remaining < 0:
                raise ValueError('registration artifact exceeds its accepted byte receipt')
            digest.update(chunk)
            if destination is not None:
                destination.write(chunk)
    if remaining or digest.hexdigest() != descriptor['sha256']:
        raise ValueError('registration artifact differs from its accepted byte receipt')


def _copy_artifact(source_root, destination_root, descriptor):
    """Copy gzip bytes verbatim; external material stores never share inodes."""
    source = _artifact_path(source_root, descriptor)
    target = _artifact_path(destination_root, descriptor)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as copied:
        _transfer_bytes(source, descriptor, copied)
        copied.flush()
        os.fsync(copied.fileno())


def _canonical_basis(manifest, stored):
    """Project precisely the prerequisites selected by the accepted store."""
    basis = source_input_basis(manifest['units'])
    expected = stored['basis']
    if len(basis) != len(expected):
        raise ValueError('registration source-unit denominator changed')
    for unit, projected, wanted in zip(manifest['units'], basis, expected):
        if unit['key'] != wanted['key']:
            raise ValueError('registration source-unit order changed')
        for parent in wanted['artifacts']:
            if parent not in projected['artifacts']:
                try:
                    projected['artifacts'][parent] = unit['artifacts'][parent]
                except KeyError as error:
                    raise ValueError('registration requires the original canonical parent ' + parent) from error
    if _json(basis) != _json(expected):
        raise ValueError('canonical source/parent receipts differ from accepted frontend inputs')


def _already_registered(manifest, item):
    present = [item.artifact in unit['artifacts'] for unit in manifest['units']]
    if item.artifact not in manifest and not any(present):
        return False
    if (not all(present) or _json(manifest.get(item.artifact)) != _json(item.inventory)
            or len(item.descriptors) != len(manifest['units'])
            or any(_json(unit['artifacts'][item.artifact]) != _json(descriptor)
                for unit, descriptor in zip(manifest['units'], item.descriptors))):
        raise ValueError('registration conflicts with an existing canonical frontend stage')
    return True


def _files(item):
    return [*([item.catalog] if item.catalog is not None else []), *item.descriptors]


def _report_receipt(root, path):
    payload = path.read_bytes()
    return {'path': path.relative_to(root).as_posix(), 'format': 'json',
        'bytes': len(payload), 'sha256': sha256(payload).hexdigest()}


def _check_destinations(root, manifest, stages):
    """Reject all known target conflicts before publishing the first stage."""
    for item in stages:
        existing = _already_registered(manifest, item)
        for descriptor in _files(item):
            path = _artifact_path(root, descriptor)
            parent = path.parent
            while parent != root:
                if parent.exists() and not parent.is_dir():
                    raise ValueError('registration artifact parent conflicts with an existing file')
                parent = parent.parent
            if existing:
                _transfer_bytes(path, descriptor)
            elif path.exists():
                raise ValueError('new registration artifact conflicts with an existing canonical file')


def register_frontend(model, out, *, acceptance, acceptance_sha256, verifications, jobs=4):
    """Admit all seven accepted stages, preserving every existing graph record.

    Preflight covers the complete chain once. Each transport has its own
    durable SourceStage publication; interruption can leave an already
    registered prefix, which a subsequent identical registration may reuse.
    No detector, parser, symbol collector or recursive semantic reader runs.
    """
    from scar.analysis.frontend_registration_inputs import prepare_registration, finish_check
    if type(jobs) is not int or not 1 <= jobs <= 32 or type(verifications) is not dict:
        raise ValueError('registration needs bounded copy jobs and an explicit verification map')
    started = time.monotonic()
    root, out = Path(model).absolute(), Path(out).absolute()
    _check_output(root, out)
    manifest = read_static_program(root, verify=False)
    original = (root / 'manifest.json').read_bytes()
    if json.loads(original) != manifest:
        raise ValueError('canonical model changed during registration admission')
    plan = prepare_registration(root, manifest, acceptance=Path(acceptance).absolute(),
        acceptance_sha256=acceptance_sha256,
        verifications={key: Path(path).absolute() for key, path in verifications.items()}, out=out)
    finish_check(plan)
    _check_destinations(root, manifest, plan.stages)
    finish_check(plan)
    _check_output(root, out)
    _durable_mkdir(out)
    reports = []
    for item in plan.stages:
        finish_check(plan)
        current = read_static_program(root, verify=False)
        _canonical_basis(current, item.stored)
        existing = _already_registered(current, item)
        receipt_dir = out / 'stages' / item.artifact
        consumes = tuple(item.stored['basis'][0]['artifacts']) + (item.artifact,) if item.stored['basis'] else (item.artifact,)
        with SourceStage(root, receipt_dir, artifact=item.artifact, verify=existing, consumes=consumes) as stage:
            _canonical_basis(stage.manifest, item.stored)
            registered = _already_registered(stage.manifest, item)
            if registered != existing:
                raise ValueError('canonical frontend registration changed during stage admission')
            files = _files(item)
            if registered:
                for descriptor in files:
                    _transfer_bytes(_artifact_path(stage.root, descriptor), descriptor)
            elif jobs == 1:
                for descriptor in files:
                    _copy_artifact(item.root, stage.staging, descriptor)
            else:
                with ThreadPoolExecutor(max_workers=jobs) as pool:
                    list(pool.map(lambda descriptor: _copy_artifact(item.root, stage.staging, descriptor), files))
            # A source change during copying must abort before model rename.
            finish_check(plan)
            if not registered:
                rows = [{'unit': unit['key'], 'artifact': descriptor}
                    for unit, descriptor in zip(stage.manifest['units'], item.descriptors)]
                stage.publish(rows, item.inventory)
            finish_check(plan)
            report = {'schema': 'scar.frontend-registration-stage', 'schema_version': 1,
                'stage': item.stored['stage'], 'artifact': item.artifact,
                'transport': 'ALREADY_REGISTERED' if registered else 'COPIED_AND_REGISTERED',
                'units': len(item.descriptors), 'files': files,
                'source_materials': str(item.root), 'verification': str(item.verification_path),
                'material_result_sha256': sha256(item.raw).hexdigest(),
                'verification_sha256': sha256(item.verification_raw).hexdigest(),
                'acceptance_sha256': plan.receipt_sha, 'evidence_policy': _EVIDENCE,
                'semantic_replay_executed': False, 'target_executed': False,
                'proof_scope_expanded': False}
            stage.finish(report)
        finish_check(plan)
        reports.append({**report, 'transport_receipt': _report_receipt(out, receipt_dir / 'result.json')})
    finish_check(plan)
    final = (root / 'manifest.json').read_bytes()
    report = {'schema': 'scar.frontend-registration', 'schema_version': 1,
        'input_scope': 'EXACT_ACCEPTED_MATERIAL_SOURCE_UNITS',
        'units': len(plan.model_basis), 'registered_stages': len(reports), 'stages': reports,
        'all_seven_registered': len(reports) == 7,
        'complete_for_declared_units': len(reports) == 7,
        'files': sum(len(row['files']) for row in reports),
        'compressed_bytes': sum(descriptor['bytes'] for row in reports for descriptor in row['files']),
        'prior_manifest_sha256': sha256(original).hexdigest(),
        'published_manifest_sha256': sha256(final).hexdigest(),
        'manifest_unchanged': final == original, 'source_input_basis_unchanged': True,
        'source_input_basis_sha256': sha256(_json(plan.model_basis)).hexdigest(),
        'acceptance': str(plan.acceptance_path), 'acceptance_sha256': plan.receipt_sha,
        'evidence_policy': _EVIDENCE, 'semantic_replay_executed': False,
        'parser_executed': False, 'symtable_executed': False, 'target_executed': False,
        'proof_scope_expanded': False, 'whole_program_complete': False,
        'jobs': jobs, 'seconds': time.monotonic() - started}
    _durable_bytes(out / 'result.json', _json(report), replace=False)
    return report


def main(argv=None):
    from scar.ir.record_codec import loads
    parser = argparse.ArgumentParser(prog='scar frontend-register')
    parser.add_argument('--model', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--acceptance', required=True)
    parser.add_argument('--acceptance-sha256', required=True)
    parser.add_argument('--verifications', required=True, help='JSON map, or JSON file, of artifact to verification report')
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args(argv)
    value = args.verifications
    mapping = loads(value if value.lstrip().startswith('{') else Path(value).read_bytes())
    report = register_frontend(args.model, args.out, acceptance=args.acceptance,
        acceptance_sha256=args.acceptance_sha256, verifications=mapping, jobs=args.jobs)
    print(_json({key: report[key] for key in ('registered_stages', 'units', 'files',
        'all_seven_registered', 'semantic_replay_executed', 'seconds')}).decode().strip())
    return 0 if report['all_seven_registered'] else 1


__all__ = ['register_frontend', 'main']
