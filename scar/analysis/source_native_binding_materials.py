"""Publish generated Python/native declarations independently of source solvers.

The existing isolated torchgen tool supplies declarations only. This catalog
does not establish a runtime export, a selected overload, native ports, effects
or resources, and never imports torch or executes an analyzed program.
"""
import argparse
from contextlib import contextmanager
import gzip
from hashlib import sha256
from importlib.abc import MetaPathFinder
from io import BytesIO
import json
from pathlib import Path
import sys
import time


_FORBIDDEN = frozenset(('torch', 'hydra', 'omegaconf', 'lewm'))
_SCHEMA = 'scar.source-native-binding-materials'
_STATUS = 'STATIC_GENERATED_BINDING_DECLARATIONS'
_FALSE_FLAGS = ('source_interfaces_connected', 'native_interfaces_connected', 'resources_connected',
    'runtime_binding_verified', 'target_executed', 'first_stage_complete', 'transformation_authorized')


class _NoTargets(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0].lower() in _FORBIDDEN:
            raise ImportError('target imports are forbidden in static binding materials: ' + fullname)


def _check_imports():
    if any(name.split('.')[0].lower() in _FORBIDDEN for name in sys.modules):
        raise RuntimeError('static binding materials process has imported a target library')


@contextmanager
def _target_guard():
    _check_imports(); finder = _NoTargets(); sys.meta_path.insert(0, finder)
    try:
        yield
        _check_imports()
    finally:
        sys.meta_path.remove(finder)


with _target_guard():
    from scar.analysis import python_bindings as producer, tensor_return_flow
    from scar.analysis.normal_output import write_table
    from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
    from scar.analysis.source_template_links import _json
    from scar.ir.program import python_bindings as B, source_productions as P
    from scar.ir.program.providers import ProviderArtifact
    from scar.ir.record_codec import _decode, _record_tags, decode, encode


def _pins():
    return {name: sha256(Path(path).read_bytes()).hexdigest() for name, path in (
        ('publisher', __file__), ('types', B.__file__), ('producer', producer.__file__),
        ('worker', Path(producer.__file__).with_name('_static_python_bindings_worker.py')),
        ('return_flow', tensor_return_flow.__file__))}


def _site(path):
    path = Path(path).absolute()
    if path.resolve() != path or not path.is_dir():
        raise ValueError('binding materials need an original canonical tool site directory')
    return path


def _inputs_unchanged(document, site):
    for receipt in (*document['tools'], *document['materials']):
        path = Path(receipt['path']); raw = path.read_bytes()
        if (not path.is_relative_to(site) or len(raw) != receipt['size_bytes']
                or sha256(raw).hexdigest() != receipt['sha256']):
            raise ValueError('static binding tool or source material changed during publication/readback')


def _definitions(document, artifact):
    symbols = {}
    for key, wrapper in document['wrappers'].items():
        if sha256(wrapper['text'].encode()).hexdigest() != wrapper['sha256']:
            raise ValueError('static binding wrapper text differs from its recorded digest')
        symbols[key] = producer._wrapper_symbol(wrapper['text'])
    conditions = (*document['open_conditions'], 'CURRENT_NAMESPACE_EXPORT_ADMISSION', 'NATIVE_OVERRIDE_PATH_NOT_SELECTED')
    for index, row in enumerate(document['bindings']):
        wrapper = document['wrappers'][row['wrapper_id']]
        yield producer._definition(row, index, artifact, document['source_revision'], conditions,
            wrapper['sha256'], symbols[row['wrapper_id']])


def _counts(document):
    return dict(definitions=len(document['bindings']), wrappers=len(document['wrappers']),
        exports=len({row['export_namespace']+'.'+row['export_name'] for row in document['bindings']}),
        families=len({row['group_id'] for row in document['bindings']}))


def build_binding_materials(site, out, catalog=None):
    """Collect declarations or validate a retained raw catalog; run no solver."""
    with _target_guard():
        started = time.monotonic(); pins = _pins(); site = _site(site); out = Path(out).absolute()
        if out.exists():
            raise ValueError('fresh source binding materials output required')
        catalog_started = time.monotonic()
        document = producer._catalog(site, catalog)
        catalog_seconds = time.monotonic()-catalog_started
        raw = _json(document)
        _durable_mkdir(out); path = out/'materials.json'; _durable_bytes(path, raw, replace=False)
        artifact = ProviderArtifact(str(path), sha256(raw).hexdigest(), len(raw), 'scar.generated-python-bindings')
        table = write_table(out/'definitions.jsonl.gz', _definitions(document, artifact))
        counts = _counts(document)
        if table['records'] != counts['definitions']:
            raise ValueError('static binding definition denominator differs')
        _inputs_unchanged(document, site)
        if pins != _pins() or path.read_bytes() != raw:
            raise ValueError('static binding producer or catalog changed during publication')
        report = dict(schema=_SCHEMA, schema_version=1, status=_STATUS, site=str(site), pins=pins,
            package_version=document['package_version'], source_revision=document['source_revision'],
            materials=encode(artifact), definitions=table, counts=counts,
            catalog_reused=catalog is not None, catalog_seconds=catalog_seconds,
            manual_bindings_included=document['manual_bindings_included'],
            python_reexports_resolved=document['python_reexports_resolved'],
            seconds=time.monotonic()-started, **{name: False for name in _FALSE_FLAGS})
        _durable_bytes(out/'result.json', _json(report), replace=False)
        return report


def read_binding_materials(path):
    """Strictly recheck stored declarations and installed tools; spawn no worker."""
    with _target_guard():
        path = Path(path).absolute(); raw = (path/'result.json').read_bytes(); report = json.loads(raw)
        if ((report['schema'], report['schema_version'], report['status']) != (_SCHEMA, 1, _STATUS)
                or type(report['schema_version']) is not int or report['pins'] != _pins()):
            raise ValueError('static source binding materials producer differs')
        site = _site(report['site']); artifact = decode(ProviderArtifact, report['materials'])
        material_path = path/'materials.json'; material_raw = material_path.read_bytes()
        if (artifact.uri != str(material_path) or artifact.schema != 'scar.generated-python-bindings'
                or artifact.size_bytes != len(material_raw) or artifact.sha256 != sha256(material_raw).hexdigest()):
            raise ValueError('static source binding material artifact receipt differs')
        # A path is always supplied: this invokes receipt validation, never the
        # isolated generator, and does not depend on an old source-target graph.
        document = producer._catalog(site, material_path)
        if json.loads(material_raw) != document:
            raise ValueError('static binding catalog changed during its strict read')
        expected = iter(_definitions(document, artifact)); receipt = report['definitions']
        relative = Path(receipt['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('static binding definition table leaves its publication directory')
        payload = (path/relative).read_bytes()
        if len(payload) != receipt['bytes'] or sha256(payload).hexdigest() != receipt['sha256']:
            raise ValueError('stored static binding definition table receipt differs')
        digest = sha256(); size = 0; rows = []; tags = _record_tags(P.PRODUCTION_RECORD_TAGS)
        with gzip.GzipFile(fileobj=BytesIO(payload), mode='rb') as stream:
            for line in stream:
                digest.update(line); size += len(line)
                if not line.endswith(b'\n') or size > receipt['decoded_bytes']:
                    raise ValueError('static binding definition table framing or decoded budget differs')
                record = _decode(B.PythonBinding, json.loads(line), tags)
                original = next(expected, None)
                if (record != original or record.native is not None or record.native_status != 'DECLARATION_ONLY'):
                    raise ValueError('static binding definition differs from its original generated declaration')
                rows.append(record)
        if (next(expected, None) is not None or len(rows) != receipt['records']
                or size != receipt['decoded_bytes'] or digest.hexdigest() != receipt['decoded_sha256']):
            raise ValueError('decoded static binding definition receipt or denominator differs')
        if (report['counts'] != _counts(document) or len(rows) != report['counts']['definitions']
                or report['package_version'] != document['package_version']
                or report['source_revision'] != document['source_revision']
                or report['manual_bindings_included'] != document['manual_bindings_included']
                or report['python_reexports_resolved'] != document['python_reexports_resolved']):
            raise ValueError('static binding source metadata or counts differ')
        if any(report[name] is not False for name in _FALSE_FLAGS):
            raise ValueError('binding declarations cannot grant source, native, resource or runtime authority')
        _inputs_unchanged(document, site)
        if ((path/'result.json').read_bytes() != raw or material_path.read_bytes() != material_raw
                or report['pins'] != _pins()):
            raise ValueError('static binding report, material or producer changed during verification')
        return report, tuple(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site'); parser.add_argument('--out'); parser.add_argument('--catalog'); parser.add_argument('--read')
    args = parser.parse_args()
    if args.read:
        report, _ = read_binding_materials(args.read)
    else:
        if not args.site or not args.out:
            parser.error('--site and --out required')
        report = build_binding_materials(args.site, args.out, args.catalog)
    print(json.dumps(dict(status=report['status'], counts=report['counts'], seconds=report['seconds'])), flush=True)


if __name__ == '__main__':
    main()
