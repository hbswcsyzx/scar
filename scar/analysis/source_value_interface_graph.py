"""Receipt-bound argument interfaces downstream of source value operations.

One parent certification is shared within a build/verification session. This
does not select dispatch, erase parent dependency conditions or enter bodies.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis import source_value_flow as values
from scar.analysis.source_consumer_parents import _stamp
from scar.analysis.source_relation_snapshot import RelationSnapshot, _local_path
from scar.analysis.source_value_interfaces import connect_value_interfaces
from scar.analysis.normal_output import write_table
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import source_value_interfaces as V, reference_consumers as R, source_productions as P
from scar.ir.record_codec import encode, decode


class ValueInterfaceParents:
    """Retain exactly one fully certified source value-flow parent in memory."""

    def __init__(self, path):
        started = time.monotonic(); self.root = Path(path).absolute()
        self.report, (self.bodies, self.reaches) = values.read_value_flow(self.root)
        self.raw = (self.root/'result.json').read_bytes()
        if json.loads(self.raw) != self.report:
            raise ValueError('value interface parent changed after its strict read')
        self.artifact = values._artifact(self.root/'result.json', self.report['schema'])
        self.tables = {}
        for receipt in self.report['tables'].values():
            table = _local_path(self.root, receipt['path']); before = _stamp(table); raw = table.read_bytes()
            if (sha256(raw).hexdigest() != receipt['sha256'] or len(raw) != receipt['bytes']
                    or before != _stamp(table)):
                raise ValueError('value interface parent table changed after certification')
            self.tables[table] = before
        consumer_root = Path(self.report['consumers'])
        consumer = json.loads((consumer_root/'result.json').read_bytes())
        if encode(values._artifact(consumer_root/'result.json', 'scar.reference-consumer-graph')) != self.report['parent']:
            raise ValueError('certified value-flow consumer report changed')
        self.catalog, self._validate_sources = values._source_catalog(consumer_root, consumer)
        # These exact report links were certified above. They locate the inert
        # historical relation snapshot, whose own receipts are checked below.
        returns = json.loads((Path(consumer['returns'])/'result.json').read_bytes())
        world = json.loads((Path(returns['world'])/'result.json').read_bytes())
        join = json.loads((Path(world['join'])/'result.json').read_bytes())
        declared = json.loads((Path(join['contexts'])/'result.json').read_bytes())
        fields = json.loads((Path(declared['parent'])/'result.json').read_bytes())
        self.snapshot = RelationSnapshot(fields['relations'], fields['catalog'])
        if (encode(self.snapshot.result_artifact) != fields['relation_parent']
                or encode(self.snapshot.catalog_artifact) != fields['catalog_parent']):
            raise ValueError('value interface relations differ from the certified field parent')
        self.validate()
        self.certification_seconds = time.monotonic()-started

    def validate(self):
        if self.raw != (self.root/'result.json').read_bytes() or self.report['pins'] != values._pins():
            raise ValueError('certified value-flow report or rules changed')
        if any(_stamp(path) != stamp for path, stamp in self.tables.items()):
            raise ValueError('certified value-flow tables changed')
        self._validate_sources(); self.snapshot.validate_parents()


def _pins():
    from scar.analysis import source_value_interfaces, source_reference_consumers
    return {name: sha256(Path(path).read_bytes()).hexdigest() for name, path in (
        ('producer', __file__), ('types', V.__file__), ('interfaces', source_value_interfaces.__file__),
        ('binder', source_reference_consumers.__file__), ('values', values.__file__))}


def _counts(graph):
    return dict(uses=len(graph.uses), bindings=len(graph.bindings),
        bound_uses=len({b.use for b in graph.bindings}),
        source_functions=len({b.source_callable for b in graph.bindings}),
        activations=dict(Counter(b.activation.value for b in graph.bindings)),
        frontiers=len(graph.frontiers), frontier_reasons=dict(Counter(f.reason for f in graph.frontiers)))


def _parents(path, parents):
    parent = parents if parents is not None else ValueInterfaceParents(path)
    if parent.root != Path(path).absolute(): raise ValueError('certified value parent path differs')
    parent.validate()
    return parent


def build_value_interface_graph(path, out, *, parents=None):
    started = time.monotonic(); pins = _pins(); out = Path(out).absolute()
    if out.exists(): raise ValueError('fresh value interfaces output required')
    parents = _parents(path, parents)
    graph = connect_value_interfaces(parents.snapshot, parents.bodies, parents.reaches)
    parents.validate()
    if _pins() != pins: raise ValueError('value interface producer changed')
    _durable_mkdir(out)
    tables = {name: write_table(out/(name+'.jsonl.gz'), getattr(graph, name))
        for name in ('uses', 'bindings', 'frontiers')}
    report = dict(schema='scar.source-value-interfaces', schema_version=1,
        status='CONDITIONAL_SOURCE_VALUE_CALL_INTERFACES', values=str(parents.root),
        parent=encode(parents.artifact), pins=pins, tables=tables, counts=_counts(graph),
        runtime_dispatch_proven=False, root_to_argument_identity_proven=False,
        target_executed=False, first_stage_complete=False, seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json', _json(report), replace=False)
    return report


def read_value_interface_graph(path, *, parents=None):
    path = Path(path).absolute(); raw = (path/'result.json').read_bytes(); report = json.loads(raw)
    if (report['schema'], report['schema_version']) != ('scar.source-value-interfaces', 1) or report['pins'] != _pins():
        raise ValueError('value interface producer differs')
    parents = _parents(report['values'], parents)
    if report['parent'] != encode(parents.artifact): raise ValueError('value interface parent differs')
    classes = dict(uses=V.SourceValueInterfaceUse, bindings=R.SourceConsumerBinding, frontiers=R.ConsumerFrontier)
    graph = V.SourceValueInterfaceGraph(**{name: tuple(decode(cls, row, record_tags=P.PRODUCTION_RECORD_TAGS)
        for row in _table(path, report['tables'][name])) for name, cls in classes.items()})
    if (graph != connect_value_interfaces(parents.snapshot, parents.bodies, parents.reaches)
            or _counts(graph) != report['counts']):
        raise ValueError('value interface bindings differ from original call inputs and source interfaces')
    if any(report[k] is not False for k in ('runtime_dispatch_proven', 'root_to_argument_identity_proven',
            'target_executed', 'first_stage_complete')):
        raise ValueError('value interface graph cannot prove runtime dispatch or root identity')
    parents.validate()
    if raw != (path/'result.json').read_bytes(): raise ValueError('value interface graph changed during verification')
    return report, graph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--values'); parser.add_argument('--out'); parser.add_argument('--read')
    args = parser.parse_args()
    if args.read: report, _ = read_value_interface_graph(args.read)
    else:
        if not args.values or not args.out: parser.error('--values and --out required')
        report = build_value_interface_graph(args.values, args.out)
    print(json.dumps(dict(status=report['status'], counts=report['counts'], seconds=report['seconds'])), flush=True)


if __name__ == '__main__': main()
