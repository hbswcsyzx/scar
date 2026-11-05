"""Append compiled-context facts without renumbering original source points.

This in-memory catalog has its own receipt schema. Variant template stores
are F4 compilation stores, not the original sealed source-template format;
their interface reader must be selected explicitly by the consumer.
"""
from bisect import bisect_right
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis.normal_facts import SourceFactStore
from scar.analysis.source_exec_query import ExecRootGraph
from scar.analysis.source_template_links import _json
from scar.ir.program import normal_links as F


def _stamp(path):
    stat = path.stat()
    return stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns


class ContextFactStore:
    def __init__(self, base: SourceFactStore, exec_graph: ExecRootGraph):
        if not isinstance(base,SourceFactStore) or not isinstance(exec_graph,ExecRootGraph):
            raise TypeError('original source facts and a verified exec root graph required')
        self.base,self.exec_graph = base,exec_graph
        exec_raw = (exec_graph.path/'result.json').read_bytes()
        if (json.loads(exec_raw) != exec_graph.report
                or exec_graph.report['source_facts_sha256'] != sha256(base.raw).hexdigest()
                or (base.path/'result.json').read_bytes() != base.raw):
            raise ValueError('context source catalog parent snapshots differ')
        f4_root,f4_report = exec_graph.parents['f4_graphs']
        f4_raw = (f4_root/'result.json').read_bytes()
        if (json.loads(f4_raw) != f4_report
                or sha256(f4_raw).hexdigest() != exec_graph.report['f4_graphs']['sha256']):
            raise ValueError('context source F4 parent differs')
        self.exec_sha256 = sha256(exec_raw).hexdigest()
        self._parent_snapshots = ((base.path/'result.json',base.raw),
            (exec_graph.path/'result.json',exec_raw),(f4_root/'result.json',f4_raw))
        self._variant_fact_stamps = {}

        self.rows = dict(base.rows)
        self.model_units = dict(base.model_units)
        self.offsets = dict(base.offsets)
        self.starts,self.identities = list(base.starts),list(base.identities)
        self.size = base.size
        self.loaded = dict(base.loaded)
        # Paths remain the source-only admission index. Compiled variants are
        # selected by exec edges, never by a filename/module import lookup.
        self.source_units,self.sources = base.source_units,base.sources
        self.importable_units = frozenset(base.rows)
        self.original_source_units = {}
        self.variant_template_stores = {}
        self.template_store_kinds = {}
        self.variant_fact_receipts = {}
        connections = {}
        for connection in exec_graph.connections():
            identity = connection.root.owner.unit
            if identity in base.rows:
                raise ValueError('compiled namespace collides with an original source unit')
            connections.setdefault(identity,[]).append(connection)

        for identity in sorted(connections):
            descriptor = f4_report['variants'][identity]
            source = descriptor['original_source_unit']
            if source not in base.rows:
                raise ValueError('compiled namespace has no original source parent')
            receipt = dict(descriptor['tables']['facts'])
            folder = f4_root/descriptor['path'];fact_path = folder/receipt['path']
            stamp = _stamp(fact_path)
            facts = exec_graph.root_facts(connections[identity][0])
            # root_facts uses the strict table reader for both stored and
            # decoded receipts. Seal that read before using lightweight guards.
            if _stamp(fact_path) != stamp:
                raise ValueError('compiled source fact table changed during its strict read')
            self._variant_fact_stamps[fact_path] = stamp
            if (type(facts) is not F.UnitFacts or facts.unit != identity
                    or any(c.root != facts.root_scope for c in connections[identity])):
                raise ValueError('compiled facts or exec roots belong to another namespace')
            self._validate_variant(facts)
            counts = {table.value:len(getattr(facts,table.value)) for table in F.FactTable}
            counts.update(ports=len(facts.ports),scope_groups=len(facts.scope_groups))
            if counts['ports'] != descriptor['ports']:
                raise ValueError('compiled source port denominator differs')
            row = dict(unit=identity,path=base.rows[source]['path'],module=facts.module,
                original_source_unit=source,facts=str(folder/receipt['path']),counts=counts,
                bytes=receipt['bytes'],sha256=receipt['sha256'],decoded_bytes=receipt['decoded_bytes'],
                decoded_sha256=receipt['decoded_sha256'],records=receipt['records'],
                facts_format='COMPILE_CONTEXT_F4_JSONL',
                operation_kinds=dict(Counter(op.action.value for op in facts.operations)),
                operator_selectors=dict(Counter(op.selector.value for op in facts.operations)))
            self.rows[identity] = row
            # Only the catalog key changes. F0/F2 artifacts and their receipts
            # still refer to the original source material, without rewriting.
            self.model_units[identity] = dict(base.model_units[source],key=identity,original_source_unit=source)
            self.original_source_units[identity] = source
            self.starts.append(self.size);self.identities.append(identity)
            self.offsets[identity] = self.size;self.size += counts['ports']
            self.loaded[identity] = facts
            self.variant_fact_receipts[identity] = dict(store=str(f4_root),unit_path=descriptor['path'],
                receipt=receipt)
            self.template_store_kinds[identity] = 'COMPILE_CONTEXT_F4_VARIANT'
            self.variant_template_stores[identity] = dict(path=str(f4_root),unit_path=descriptor['path'],
                schema=f4_report['schema'],schema_version=f4_report['schema_version'],
                sha256=sha256(f4_raw).hexdigest(),sealed_source_template_store=False)

        counts = Counter()
        for row in self.rows.values():
            counts.update(row['counts'])
        self.report = dict(schema='scar.context-source-facts',schema_version=1,
            status='SOURCE_AND_COMPILED_CONTEXT_FACT_CATALOG',
            base_source_facts=dict(path=str(base.path),sha256=sha256(base.raw).hexdigest(),
                schema=base.report['schema'],schema_version=base.report['schema_version']),
            exec_roots=dict(path=str(exec_graph.path),sha256=sha256(exec_raw).hexdigest()),
            f4_graphs=dict(exec_graph.report['f4_graphs']),variant_facts=self.variant_fact_receipts,
            original_source_units=self.original_source_units,template_stores=self.variant_template_stores,
            importable_units=sorted(self.importable_units),units=list(self.rows.values()),counts=dict(counts),
            selected_sources=len(self.rows),base_sources=len(base.rows),compiled_namespaces=len(connections),
            base_point_count=base.size,point_count=self.size,copied_fact_bytes=0,
            source_body_activated=False,target_executed=False,first_stage_complete=False,
            implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest())
        self.raw = _json(self.report)
        self.validate_parents()

    def validate_parents(self):
        """Recheck the reports and receipt-verified variant fact footprint."""
        for path,raw in self._parent_snapshots:
            if path.read_bytes() != raw:
                raise ValueError('context source parent report changed: '+str(path))
        for path,stamp in self._variant_fact_stamps.items():
            if _stamp(path) != stamp:
                raise ValueError('context source fact table changed: '+str(path))
        return len(self._parent_snapshots)+len(self._variant_fact_stamps)

    @staticmethod
    def _validate_variant(facts):
        size = len(facts.ports)
        if any(len(pair) != 2 or any(type(p) is not int or not 0 <= p < size for p in pair)
                for pair in facts.aliases):
            raise ValueError('compiled source alias lies outside its original ports')
        coverage = {table:bytearray(len(getattr(facts,table.value))) for table in F.FactTable}
        for group in facts.scope_groups:
            if group.owner.unit != facts.unit:
                raise ValueError('compiled source fact owner belongs to another namespace')
            for span in group.tables:
                covered = coverage[span.table]
                if not 0 <= span.start < span.stop <= len(covered):
                    raise ValueError('compiled source activation range differs')
                for index in range(span.start,span.stop):
                    if covered[index] and span.table is not F.FactTable.ALIASES:
                        raise ValueError('compiled non-transport fact has multiple owners')
                    covered[index] = 1
        if any(0 in rows for rows in coverage.values()):
            raise ValueError('compiled source facts lack original activation ownership')
        if facts.root_scope is None or facts.root_scope.owner.unit != facts.unit:
            raise ValueError('compiled source root is absent or unqualified')

    def load(self,identity):
        if identity not in self.rows:
            raise KeyError(identity)
        if identity not in self.loaded:
            self.loaded[identity] = self.base.load(identity)
        return self.loaded[identity]

    def locate(self,point):
        if type(point) is not int or not 0 <= point < self.size:
            raise ValueError('source point outside context catalog')
        if point < self.base.size:
            return self.base.locate(point)
        index = bisect_right(self.starts,point)-1
        return self.identities[index],point-self.starts[index]

    def model_for(self,identity):
        return self.base.model_for(self.original_source_units.get(identity,identity))

    def templates_for(self,identity):
        if identity in self.original_source_units:
            return Path(self.variant_template_stores[identity]['path'])
        return self.base.templates_for(identity)

    def units_for_source(self,source):
        return tuple(self.source_units.get(str(Path(source).absolute()),()))
