"""Reuse ancestors already certified by a complete world-flow read.

Every original report link and table receipt is checked. This does not waive
the initial strict read, re-sign an ancestor, or grant new admission authority.
"""
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis.source_world_flow import read_world_flow
from scar.analysis.source_symbol_variants import _table
from scar.ir.program import declared_contexts as D, declared_state_connections as J
from scar.ir.program import source_reference_slices as F, source_state_projections as S, source_productions as P
from scar.ir.record_codec import decode


def _stamp(path):
    row = path.stat()
    return row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns


class CertifiedWorldParents:
    def __init__(self, world):
        self.world = Path(world).absolute()
        self.world_report, self.flows = read_world_flow(self.world)
        self._reports = {}; self._tables = {}
        self._remember(self.world, self.world_report)
        self.join_root, self.join_report = self._report(self.world_report['join'], self.world_report['parent'])
        jr = self.join_report
        self.context_root, self.context_report = self._report(jr['contexts'], jr['parents']['contexts'])
        self.boundary_root, self.boundary_report = self._report(jr['boundaries'], jr['parents']['boundaries'])
        self.field_root, self.field_report = self._report(self.context_report['parent'], self.context_report['parent_ref'])
        self.joins = self._rows(self.join_root, jr['tables']['connections'], J.DeclaredStateConnection)
        self.bindings = self._rows(self.boundary_root, self.boundary_report['bindings'], S.SourceStateProjection)
        self.graph = D.DeclaredContextGraph(**{name: self._rows(self.context_root,
            self.context_report['tables'][name], cls) for name, cls in (
                ('contexts', D.DeclaredContext), ('entries', D.DeclaredContextEntry),
                ('edges', D.DeclaredContextEdge), ('frontiers', D.ContextFrontier))})
        self.queries = tuple(self._rows(self.field_root/shard['folder'], shard['table'], F.FieldInterfaceQuery)[0]
            for shard in self.field_report['shards'])
        self.validate()

    def _remember(self, root, report):
        path = Path(root)/'result.json'; raw = path.read_bytes()
        if json.loads(raw) != report: raise ValueError('certified world parent changed after its strict read')
        self._reports[path] = raw

    def _report(self, root, reference):
        root = Path(root).absolute(); path = root/'result.json'; raw = path.read_bytes()
        if (str(path) != reference['uri'] or len(raw) != reference['size_bytes']
                or sha256(raw).hexdigest() != reference['sha256']):
            raise ValueError('certified world ancestor report receipt differs')
        report = json.loads(raw); self._reports[path] = raw
        return root, report

    def _rows(self, root, receipt, cls):
        root = Path(root); path = root/receipt['path']; before = _stamp(path)
        rows = tuple(decode(cls, w, record_tags=P.PRODUCTION_RECORD_TAGS) for w in _table(root, receipt))
        if _stamp(path) != before: raise ValueError('certified world table changed during read')
        self._tables[path] = before
        return rows

    def validate(self):
        for path, raw in self._reports.items():
            if path.read_bytes() != raw: raise ValueError('certified world ancestor report changed')
        for path, stamp in self._tables.items():
            if _stamp(path) != stamp: raise ValueError('certified world ancestor table changed')
        return len(self._reports)+len(self._tables)
