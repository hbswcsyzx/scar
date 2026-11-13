"""Read local F4 declarations without running a namespace/target solver.

The catalog references existing fact, interface and template stores. It grants
no executed scope, dispatch, environment contents or compiled-context facts.
"""
from hashlib import sha256
import json
from pathlib import Path
from types import MappingProxyType

from scar.analysis.normal_facts import SourceFactStore
from scar.analysis.source_interface_store import SourceInterfaceStore


SCHEMA = 'scar.declared-source-catalog'
_ABSENT_CLAIMS = ('global_namespace_resolved', 'compiled_contexts_present',
    'runtime_dispatch_proven', 'effects_proven', 'target_executed', 'first_stage_complete')


def _stamp(path):
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _receipt(path):
    path = Path(path).absolute()
    if path.resolve() != path or path.is_symlink() or not path.is_file():
        raise ValueError('declared catalog needs canonical original files')
    before = _stamp(path)
    raw = path.read_bytes()
    if _stamp(path) != before:
        raise ValueError('declared catalog parent changed during read')
    return dict(path=str(path), bytes=len(raw), sha256=sha256(raw).hexdigest())


def _check(receipt):
    if _receipt(receipt['path']) != receipt:
        raise ValueError('declared catalog parent receipt differs')


class DeclaredSourceFacts:
    """Explicit original-only fact view; no synthetic exec/namespace store."""
    def __init__(self, base):
        if not isinstance(base, SourceFactStore):
            raise TypeError('declared source facts require the original typed store')
        self.base = base
        self.path, self.raw, self.report = base.path, base.raw, base.report
        self.rows = MappingProxyType(base.rows)
        self.model_units = MappingProxyType(base.model_units)
        self.sources = MappingProxyType(base.sources)
        self.source_units = MappingProxyType(base.source_units)
        self.offsets = MappingProxyType(base.offsets)
        self.size = base.size
        self.original_source_units = MappingProxyType({})
        self.supplemental_sources = ()
        self._source_parents = MappingProxyType({unit: base for unit in base.rows})
        self.importable_units = frozenset(base.rows)
        self.loaded = base.loaded
        self._reports, self._tables = {}, {}
        self._parents(base)
        self.validate_parents()

    def _remember(self, path, expected=None):
        receipt = _receipt(path)
        raw = Path(receipt['path']).read_bytes()
        if expected is not None and raw != expected:
            raise ValueError('declared source report differs from its original reader')
        self._reports[Path(receipt['path'])] = raw

    def _parents(self, store):
        self._remember(store.path/'result.json', store.raw)
        if store.parents:
            for parent in store.parents:
                self._parents(parent)
            return
        self._remember(store.model/'manifest.json')
        self._remember(store.templates/'result.json')
        if (sha256(self._reports[store.model/'manifest.json']).hexdigest()
                != store.report['model_manifest_sha256']
                or sha256(self._reports[store.templates/'result.json']).hexdigest()
                != store.report['source_result_sha256']):
            raise ValueError('declared source model/template parent differs')
        for row in store.rows.values():
            path = store.path/row['facts']
            if path.is_symlink() or path.resolve() != path or not path.is_relative_to(store.path):
                raise ValueError('declared fact table escapes its original store')
            stamp = _stamp(path)
            if stamp[2] != row['bytes']:
                raise ValueError('declared fact table size differs')
            self._tables[path] = stamp

    def validate_parents(self):
        for path, raw in self._reports.items():
            if path.read_bytes() != raw:
                raise ValueError('declared source report changed: '+str(path))
        for path, stamp in self._tables.items():
            if _stamp(path) != stamp:
                raise ValueError('declared source fact table changed: '+str(path))
        return len(self._reports)+len(self._tables)

    def source_parent_for(self, identity):
        if identity not in self.rows:
            raise KeyError(identity)
        return self.base

    def load(self, identity):
        self.validate_parents()
        value = self.base.load(identity)
        self.validate_parents()
        return value

    def document(self, identity):
        self.validate_parents()
        value = self.base.document(identity)
        self.validate_parents()
        return value

    def model_for(self, identity):
        return self.base.model_for(identity)

    def templates_for(self, identity):
        return self.base.templates_for(identity)

    def units_for_source(self, source):
        return tuple(self.source_units.get(str(Path(source).absolute()), ()))

    def locate(self, point):
        return self.base.locate(point)


class DeclaredSourceCatalog:
    """A receipt-bound directory of local declarations, independent of solve."""
    def __init__(self, path):
        self.path = Path(path).absolute()
        if self.path.resolve() != self.path:
            raise ValueError('declared catalog must be canonical')
        root = self.path/'result.json'
        self._root_receipt = _receipt(root)
        self.report = report = json.loads(root.read_bytes())
        fields = {'schema', 'schema_version', 'profile', 'facts', 'interfaces',
            'source_units', 'implementation_sha256', *_ABSENT_CLAIMS}
        if (set(report) != fields or (report['schema'], report['schema_version'], report['profile'])
                != (SCHEMA, 1, 'NORMAL_SUCCESS')
                or type(report['schema_version']) is not int
                or report['implementation_sha256'] != sha256(Path(__file__).read_bytes()).hexdigest()
                or any(report[name] is not False for name in _ABSENT_CLAIMS)):
            raise ValueError('unsupported declared catalog contract or producer')
        _check(report['facts']); _check(report['interfaces'])
        base = SourceFactStore(Path(report['facts']['path']).parent)
        if (base.path/'result.json').read_bytes() != base.raw:
            raise ValueError('declared fact catalog changed during admission')
        self.fact_store = DeclaredSourceFacts(base)
        self.interface_store = SourceInterfaceStore(Path(report['interfaces']['path']).parent, base)
        if (set(report['source_units']) != set(self.fact_store.rows)
                or len(report['source_units']) != len(self.fact_store.rows)
                or not self.interface_store.receipt['catalog_complete']):
            raise ValueError('declared catalog local source/interface coverage differs')
        self.units, self.sources = self.fact_store.rows, self.fact_store.sources
        self.inputs, self.templates = base.report, base.templates
        self.validate_parents()

    def validate_parents(self):
        _check(self._root_receipt)
        if json.loads((self.path/'result.json').read_bytes()) != self.report:
            raise ValueError('declared catalog in-memory report changed')
        self.fact_store.validate_parents()
        self.interface_store.validate_parents()

    def units_for_source(self, source=None):
        return None if source is None else frozenset(self.fact_store.units_for_source(source))


def publish_declared_catalog(facts, interfaces, out):
    """Reference existing complete local stores; do not build or solve bodies."""
    from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
    from scar.analysis.source_template_links import _json
    out = Path(out).absolute()
    if out.resolve() != out or out.exists():
        raise ValueError('declared catalog requires fresh canonical output')
    base = SourceFactStore(Path(facts).absolute())
    local = SourceInterfaceStore(Path(interfaces).absolute(), base)
    if not local.receipt['catalog_complete']:
        raise ValueError('declared catalog requires all declared local interfaces')
    report = dict(schema=SCHEMA, schema_version=1, profile='NORMAL_SUCCESS',
        facts=_receipt(base.path/'result.json'), interfaces=_receipt(local.path/'result.json'),
        source_units=list(base.rows), implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        **{name: False for name in _ABSENT_CLAIMS})
    _durable_mkdir(out)
    _durable_bytes(out/'result.json', _json(report), replace=False)
    DeclaredSourceCatalog(out)
    return report


def read_source_catalog(value):
    """Select one concrete catalog reader by its original schema."""
    if isinstance(value, DeclaredSourceCatalog):
        return value
    if isinstance(value, (str, Path)):
        path = Path(value).absolute()
        report = json.loads((path/'result.json').read_bytes())
        if report.get('schema') == SCHEMA:
            return DeclaredSourceCatalog(path)
    from scar.analysis.source_context_query import ContextTargetGraph
    return value if isinstance(value, ContextTargetGraph) else ContextTargetGraph(value)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--facts', required=True)
    parser.add_argument('--interfaces', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    report = publish_declared_catalog(args.facts, args.interfaces, args.out)
    print(json.dumps(dict(schema=report['schema'], source_units=len(report['source_units']),
        global_namespace_resolved=False, target_executed=False, first_stage_complete=False)))


if __name__ == '__main__':
    main()
