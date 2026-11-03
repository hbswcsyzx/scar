"""Owned, append-only source sidecar transactions shared by formal stages."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from scar.analysis.source_materials import _remove_owned_previous, _stamps


class SourceStage:
    """Preserve old model contents while a stage writes its own per-unit shard.

    This owns publication only. Tokenization, parsing, budgets and stage
    admission remain in their respective producers; no later layer runs here.
    """

    def __init__(self, model, out, *, artifact, verify, consumes):
        from scar.analysis.static_program import _artifacts, read_static_program
        if artifact not in ('source_tokens', 'source_syntax', 'source_symbols', 'source_roles', 'source_contexts', 'source_declarations', 'source_bindings', 'compiler_topology') or type(verify) is not bool:
            raise ValueError('unsupported formal source sidecar transaction')
        self.root, self.out = Path(model).absolute(), Path(out).absolute()
        if (self.root.resolve() != self.root or self.out.resolve() != self.out
                or self.out.is_relative_to(self.root)
                or self.out.exists() and (not self.out.is_dir() or any(self.out.iterdir()))):
            raise ValueError('source stage requires a canonical model and fresh external report directory')
        self.artifact, self.verify = artifact, verify
        self.manifest = read_static_program(self.root, verify=False)
        self.original = (self.root / 'manifest.json').read_bytes()
        if json.loads(self.original) != self.manifest:
            raise ValueError('source model changed during initial read')
        self.prior = tuple(_artifacts(self.manifest))
        keys = [unit['key'] for unit in self.manifest['units']]
        if (any(type(key) is not str or re.fullmatch(r'[A-Za-z0-9_-]{1,128}', key) is None for key in keys)
                or len(set(keys)) != len(keys)):
            raise ValueError('source stage requires unique, safe source-unit path components')
        owned = {d['path'] for d in self.prior}
        for unit in self.manifest['units']:
            relative = self.relative(unit)
            if artifact not in unit['artifacts'] and (relative in owned or (self.root / relative).exists()):
                raise ValueError('new source sidecar collides with an existing artifact')
        self.consumed = (tuple(d for unit in self.manifest['units'] for name, d in unit['artifacts'].items()
            if name in consumes) if verify else self.prior)
        self.stamps = _stamps(self.root, self.consumed)
        self.staging = None
        self.published = self.original
        self.retained_previous = None

    def relative(self, unit):
        return 'units/' + unit['key'] + '/' + self.artifact + '.json.gz'

    def __enter__(self):
        if not self.verify:
            self.staging = Path(tempfile.mkdtemp(prefix='.' + self.artifact + '-', dir=self.root.parent))
            try:
                shutil.copytree(self.root, self.staging, dirs_exist_ok=True, copy_function=os.link)
            except BaseException:
                shutil.rmtree(self.staging, ignore_errors=True)
                self.staging = None
                raise
        return self

    def check_inputs(self):
        from scar.analysis.static_program import read_static_program
        read_static_program(self.root, verify=False)
        if ((self.root / 'manifest.json').read_bytes() != self.original
                or _stamps(self.root, self.consumed) != self.stamps):
            raise ValueError('source stage inputs changed during processing')

    def publish(self, rows, inventory):
        from scar.analysis.static_program import _artifacts, _json, read_static_program
        if self.verify or self.staging is None or len(rows) != len(self.manifest['units']):
            raise ValueError('source publication requires a full staged row set')
        original = json.loads(self.original)
        for old, unit, row in zip(original['units'], self.manifest['units'], rows):
            if row['unit'] != unit['key'] or unit['key'] != old['key']:
                raise ValueError('source stage unit order changed')
            descriptor = row['artifact']
            if descriptor['path'] != self.relative(unit):
                raise ValueError('source sidecar must stay at its owned unit path')
            unit['artifacts'][self.artifact] = descriptor
            restored = {**unit, 'artifacts': {k: d for k, d in unit['artifacts'].items() if k != self.artifact}}
            if self.artifact in old['artifacts']:
                restored['artifacts'][self.artifact] = old['artifacts'][self.artifact]
                if descriptor != old['artifacts'][self.artifact]:
                    raise ValueError('source stage cannot replace an existing sidecar')
            if _json(restored) != _json(old):
                raise ValueError('source stage changed a prior unit field')
        self.manifest[self.artifact] = inventory
        unique = {d['path']: d for d in _artifacts(self.manifest)}
        self.manifest['storage'] = {'files': len(unique), 'compressed_bytes': sum(d['bytes'] for d in unique.values())}
        restored = {**self.manifest, 'units': original['units']}
        for field in (self.artifact, 'storage'):
            if field in original:
                restored[field] = original[field]
            else:
                restored.pop(field, None)
        if _json(restored) != _json(original):
            raise ValueError('source stage changed a prior manifest field')
        (self.staging / 'manifest.json').unlink()
        self.published = _json(self.manifest)
        (self.staging / 'manifest.json').write_bytes(self.published)
        read_static_program(self.staging, verify=False)
        if _stamps(self.staging, self.prior) != self.stamps:
            raise ValueError('source staging altered an original artifact')
        self.check_inputs()
        previous = Path(tempfile.mkdtemp(prefix='.' + self.artifact + '-replacing-', dir=self.root.parent))
        previous.rmdir()
        self.root.rename(previous)
        try:
            self.staging.rename(self.root)
            self.staging = None
        except BaseException:
            previous.rename(self.root)
            raise
        self.retained_previous = _remove_owned_previous(previous, self.prior, self.stamps)

    def finish(self, report):
        from scar.analysis.static_program import _json, read_static_program
        read_static_program(self.root, verify=False)
        if ((self.root / 'manifest.json').read_bytes() != self.published
                or _stamps(self.root, self.consumed) != self.stamps):
            raise ValueError('source model changed before stage receipt publication')
        report.update(prior_manifest_sha256=sha256(self.original).hexdigest(),
            published_manifest_sha256=sha256(self.published).hexdigest(),
            source_scan_remaining=self.manifest.get('remaining'),
            source_scan_issues=self.manifest.get('source_issues'),
            manifest_unchanged=self.published == self.original,
            consumed_artifacts_unchanged=True, original_units_and_endpoints_unchanged=True)
        if self.retained_previous is not None:
            report['retained_previous_directory'] = self.retained_previous
        self.out.mkdir(parents=True, exist_ok=True)
        with (self.out / 'result.json').open('xb') as stream:
            stream.write(_json(report))
        return report

    def __exit__(self, *exception):
        if self.staging is not None:
            shutil.rmtree(self.staging, ignore_errors=True)


__all__ = ['SourceStage']
