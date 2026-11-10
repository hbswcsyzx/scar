"""A sealed set of disjoint function-interface leaves, without copied rows.

Each unit keeps its original reader, row facts and provenance. A collection
joins material availability; it does not admit an execution or select a call.
"""
import argparse
import json
from pathlib import Path

from scar.analysis.source_call_view import open_function_interfaces, function_interface_fact
from scar.analysis.source_value_flow import _artifact
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.record_codec import encode


SCHEMA = 'scar.source-function-interface-collection'


def _layout(stores):
    catalog = stores[0].catalog
    shards = {}
    for i, store in enumerate(stores):
        if (store.catalog.path, store.catalog.report) != (catalog.path, catalog.report):
            raise ValueError('interface leaves need the exact same source catalog')
        for unit, shard in store.report['shards'].items():
            if unit in shards:
                raise ValueError('overlapping interface leaves require an explicit selected overlay')
            shards[unit] = dict(reader=i, path=str(store.path / shard['path']),
                tables=shard['tables'], counts=shard['counts'])
    return dict(sorted(shards.items()))


def _report(stores):
    shards = _layout(stores)
    return dict(schema=SCHEMA, schema_version=1, catalog=str(stores[0].catalog.path),
        catalog_parent=encode(_artifact(stores[0].catalog.path/'result.json', stores[0].catalog.report['schema'])),
        readers=[dict(path=str(s.path), parent=encode(_artifact(s.path/'result.json', s.report['schema']))) for s in stores],
        shards=shards, counts=dict(units=len(shards),
            calls=sum(s['counts']['calls'] for s in shards.values()),
            interfaces=sum(s['counts']['interfaces'] for s in shards.values())),
        source_bodies_copied=False, interface_rows_copied=False,
        runtime_dispatch_proven=False, target_executed=False, first_stage_complete=False)


def publish_function_collection(paths, out):
    stores = tuple(open_function_interfaces(p) for p in paths)
    if not stores:
        raise ValueError('at least one sealed function-interface reader required')
    report = _report(stores)
    out = Path(out).absolute()
    if out.exists():
        raise ValueError('fresh collection output required')
    for store in stores: store.validate()
    _durable_mkdir(out)
    _durable_bytes(out/'result.json', _json(report), replace=False)
    return report


class FunctionInterfaceCollection:
    def __init__(self, path):
        self.path = Path(path).absolute()
        self.raw = (self.path/'result.json').read_bytes()
        self.report = report = json.loads(self.raw)
        if (report['schema'], report['schema_version']) != (SCHEMA, 1) or not report['readers']:
            raise ValueError('function collection schema or leaves differ')
        self.stores = tuple(open_function_interfaces(s['path']) for s in report['readers'])
        self.catalog = self.stores[0].catalog
        self.validate()

    def validate(self):
        if self.raw != (self.path/'result.json').read_bytes() or self.report != _report(self.stores):
            raise ValueError('function collection or original leaf receipts changed')
        for store in self.stores: store.validate()

    def _reader(self, unit):
        self.validate()
        return self.stores[self.report['shards'][unit]['reader']]

    def load_unit(self, unit): return self._reader(unit).load_unit(unit)
    def read_unit(self, unit): return self._reader(unit).read_unit(unit)

    def load_declarations(self, unit):
        store = self._reader(unit)
        method = getattr(store, 'load_declarations', None)
        return method(unit) if callable(method) else store.parents.calls.load_unit(unit)

    def interface_fact(self, unit, i):
        return function_interface_fact(self._reader(unit), unit, i)

    def callable_provenance(self, unit, i):
        store = self._reader(unit)
        method = getattr(store, 'callable_provenance', None)
        return method(unit, i) if callable(method) else None

    def provenance_locator(self, unit, i):
        store = self._reader(unit)
        method = getattr(store, 'provenance_locator', None)
        return method(unit, i) if callable(method) else None


def main():
    from scar.analysis.source_declared_calls import _NoTargets, _check_targets
    import sys
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interfaces', action='append', default=[])
    parser.add_argument('--out'); parser.add_argument('--read')
    args = parser.parse_args(); sys.meta_path.insert(0, _NoTargets()); _check_targets()
    if args.read:
        store = FunctionInterfaceCollection(args.read)
        for unit in store.report['shards']: store.read_unit(unit)
        report = store.report
    else:
        if not args.interfaces or not args.out: parser.error('--interfaces and --out required')
        report = publish_function_collection(args.interfaces, args.out)
    _check_targets(); print(json.dumps(report['counts']), flush=True)


if __name__ == '__main__': main()
