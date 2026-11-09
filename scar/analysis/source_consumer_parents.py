"""Reuse ancestors certified by one complete world-return graph read.

Receipt checks preserve that certification; they do not admit source scopes,
select current state versions, verify runtime dispatch or authorize execution
or transformation. Historical producer profiles remain inert evidence.
"""
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis.source_world_returns import read_world_returns
from scar.analysis.source_relation_snapshot import RelationSnapshot, _local_path
from scar.analysis.source_symbol_variants import _table
from scar.ir.program import declared_contexts as D, source_productions as P
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import decode, encode


def _stamp(path):
    row = path.stat()
    return row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns


class ConsumerParents:
    """Original world-return records and their already certified declarations."""

    def __init__(self, returns_path):
        self.returns_root = Path(returns_path).absolute()
        # The only complete ancestor derivation in this adapter. Later reads
        # retain exactly its original report links and table receipts.
        self.report, self.graph = read_world_returns(self.returns_root)
        self._reports = {}; self._tables = {}
        self._remember(self.returns_root, self.report)
        for receipt in self.report['tables'].values():
            self._guard_table(self.returns_root, receipt)
        self.world_root, self.world_report = self._report(
            self.report['world'], self.report['parent'], 'scar.source-world-flow')
        self._guard_table(self.world_root, self.world_report['table'])
        self.join_root, self.join_report = self._report(
            self.world_report['join'], self.world_report['parent'], 'scar.declared-state-connections')
        for receipt in self.join_report['tables'].values():
            self._guard_table(self.join_root, receipt)
        self.declared_root, self.declared_report = self._report(
            self.join_report['contexts'], self.join_report['parents']['contexts'], 'scar.declared-context-graph')
        self.field_root, self.field_report = self._report(
            self.declared_report['parent'], self.declared_report['parent_ref'], 'scar.source-field-interface-graph')
        self.declared_graph = D.DeclaredContextGraph(**{name: self._rows(self.declared_root,
            self.declared_report['tables'][name], cls) for name, cls in (
                ('contexts', D.DeclaredContext), ('entries', D.DeclaredContextEntry),
                ('edges', D.DeclaredContextEdge), ('frontiers', D.ContextFrontier))})
        for shard in self.field_report['shards']:
            self._guard_table(_local_path(self.field_root, shard['folder']), shard['table'])
        self.snapshot = RelationSnapshot(self.field_report['relations'], self.field_report['catalog'])
        if (encode(self.snapshot.result_artifact) != self.field_report['relation_parent']
                or encode(self.snapshot.catalog_artifact) != self.field_report['catalog_parent']):
            raise ValueError('consumer relation or catalog artifact differs from the certified field parent')
        self.validate()

    def _remember(self, root, report):
        path = Path(root)/'result.json'; raw = path.read_bytes()
        if json.loads(raw) != report:
            raise ValueError('consumer parent report changed after its complete strict read')
        if path in self._reports and self._reports[path][0] != raw:
            raise ValueError('consumer parent report has conflicting certified bytes')
        self._reports[path] = raw, report

    def _report(self, root, reference, schema):
        root = Path(root).absolute(); path = root/'result.json'
        original = decode(ProviderArtifact, reference)
        raw = path.read_bytes()
        if (original.uri != str(path) or original.schema != schema
                or original.size_bytes != len(raw) or original.sha256 != sha256(raw).hexdigest()):
            raise ValueError('consumer ancestor report URI or byte receipt differs')
        report = json.loads(raw)
        if report.get('schema') != schema:
            raise ValueError('consumer ancestor report schema differs')
        if path in self._reports and self._reports[path][0] != raw:
            raise ValueError('consumer ancestor report has conflicting original bytes')
        self._reports[path] = raw, report
        return root, report

    def _guard_table(self, root, receipt):
        path = _local_path(Path(root), receipt['path']); before = _stamp(path)
        payload = path.read_bytes()
        if (len(payload) != receipt['bytes'] or sha256(payload).hexdigest() != receipt['sha256']
                or _stamp(path) != before):
            raise ValueError('consumer ancestor table byte receipt changed')
        if path in self._tables and self._tables[path] != before:
            raise ValueError('consumer ancestor table changed between certified reads')
        self._tables[path] = before

    def _rows(self, root, receipt, cls):
        root = Path(root); path = _local_path(root, receipt['path']); before = _stamp(path)
        rows = tuple(decode(cls, wire, record_tags=P.PRODUCTION_RECORD_TAGS) for wire in _table(root, receipt))
        if _stamp(path) != before:
            raise ValueError('consumer declared table changed during strict typed reading')
        if path in self._tables and self._tables[path] != before:
            raise ValueError('consumer declared table changed between reads')
        self._tables[path] = before
        return rows

    def validate(self):
        """Recheck original report bytes, stable table guards and source parents."""
        for path, (raw, report) in self._reports.items():
            if path.read_bytes() != raw or json.loads(raw) != report:
                raise ValueError('consumer certified ancestor report changed')
        for path, stamp in self._tables.items():
            if _stamp(path) != stamp:
                raise ValueError('consumer certified ancestor table changed')
        return len(self._reports) + len(self._tables) + self.snapshot.validate_parents()
