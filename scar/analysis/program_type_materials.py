"""Export/recheck the shared source and target signature grammars only."""
import argparse
from hashlib import sha256
import math
from pathlib import Path
import time

from scar.analysis.program_types import program_type_catalog, read_program_type_catalog
from scar.analysis.source_type_catalog import source_type_catalog, read_source_type_catalog
from scar.analysis.static_program import _json, _write
from scar.analysis.static_query import _Fragments
from scar.ir.record_codec import loads


def _summary(source, target, artifacts):
    return dict(schema='scar.program-type-materials', schema_version=1, stage='F4-A', complete=True,
        artifacts=artifacts, source_constructors=len(source['constructors']), source_slots=len(source['slots']),
        source_catalog_sha256=source['content_sha256'], target_catalog_sha256=target['content_sha256'],
        target_counts=target['counts'], input_unchanged=None, input_materials=None, input_summary_sha256=None,
        graph_realized=False, operation_semantics_closed=False, target_executed=False,
        canonical_model_published=False, whole_program_complete=False)


def program_types(out, *, materials=None):
    started = time.monotonic()
    out = Path(out).resolve()
    source, target = source_type_catalog(), program_type_catalog()
    saved = root = raw = pins = None
    if materials is not None:
        root = Path(materials).resolve()
        if root == out or root in out.parents or out in root.parents:
            raise ValueError('type grammar input/output directories overlap')
        raw = (root / 'result.json').read_bytes()
        saved = loads(raw)
        if (saved.get('schema') != 'scar.program-type-materials' or type(saved.get('schema_version')) is not int
                or saved.get('schema_version') != 1
                or set(saved.get('artifacts', {})) != {'source', 'target'}):
            raise ValueError('invalid type grammar material envelope')
        for key, name, reader in (('source', 'source_types.json.gz', read_source_type_catalog),
                ('target', 'program_types.json.gz', read_program_type_catalog)):
            descriptor = saved['artifacts'][key]
            if descriptor.get('path') != name:
                raise ValueError('type grammar descriptor does not use its owned original path')
            reader(_Fragments(root).read(descriptor))
        expected_members = {'result.json', 'source_types.json.gz', 'program_types.json.gz'}
        if {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()} != expected_members:
            raise ValueError('type grammar store contains unowned or missing files')
        pins = {name: sha256((root / name).read_bytes()).hexdigest() for name in expected_members}
        seconds = saved.get('seconds')
        if (type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0
                or _json({k: v for k, v in saved.items() if k != 'seconds'})
                    != _json(_summary(source, target, saved['artifacts']))):
            raise ValueError('type grammar material summary differs from its original declarations')
    out.mkdir(parents=True, exist_ok=False)
    if saved is None:
        descriptors = {'source': _write(out, 'source_types.json.gz', source),
            'target': _write(out, 'program_types.json.gz', target)}
    else:
        descriptors = saved['artifacts']
    if root is not None:
        if (root / 'result.json').read_bytes() != raw or any(
                sha256((root / name).read_bytes()).hexdigest() != digest for name, digest in pins.items()):
            raise ValueError('type grammar input changed during verification')
        if {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()} != set(pins):
            raise ValueError('type grammar input membership changed during verification')
    report = dict(_summary(source, target, descriptors),
        schema='scar.program-type-verification' if saved else 'scar.program-type-materials',
        input_unchanged=True if saved else None,
        input_materials=None if root is None else str(root),
        input_summary_sha256=None if raw is None else sha256(raw).hexdigest(),
        seconds=time.monotonic() - started)
    (out / 'result.json').write_bytes(_json(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description='F4-A source/target structural signature grammars; no graph lowering')
    parser.add_argument('--out', required=True)
    parser.add_argument('--materials', help='fresh-check an existing shared type grammar store')
    args = parser.parse_args(argv)
    report = program_types(args.out, materials=args.materials)
    print(_json(report).decode('ascii'))
    return 0


__all__ = ['program_types', 'main']
