"""Reference a retained target inventory from symbolic program resources.

This adapter reads existing typed hardware tables. It neither probes hardware
nor runs the target, and every attachment is a capability candidate rather
than a placement, allocation or transfer observation.
"""
from hashlib import sha256
from pathlib import Path

from scar.ir.program import target_hardware as H
from scar.ir.program.dependencies import DependencyPoint as Point
from scar.ir.program.ids import ResourceDefinitionID
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.resources import (
    ExternalResource, ResourceDefinition, ResourceKind, ResourceRole)
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.record_codec import encode


SCHEMA = 'scar.build-target-resources.v1'


def _stamp(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


class RetainedBuildTarget:
    """Project original hardware IDs into demanded program namespaces once."""
    def __init__(self, provider, path):
        from scar.analysis.source_resource_graph import _target
        self.provider = provider
        self.graph, self.resources = _target(Path(path).resolve())
        self.connections = self.graph.connections()
        self.paths = self.graph.paths()
        path = self.graph.path / 'result.json'
        raw = path.read_bytes()
        self.snapshot = ProviderArtifact(str(path), sha256(raw).hexdigest(), len(raw),
            self.graph.report['schema'])
        self.locator = SourceArtifactLocator(self.snapshot, self.snapshot.sha256,
            self.snapshot.size_bytes, 'canonical-json')
        report = self.graph.report
        files = (path, Path(report['inventory']['uri']),
            *(self.graph.path / r['path'] for r in report['nodes'].values()),
            self.graph.path / report['connections']['path'],
            self.graph.path / report['paths']['path'])
        self._stamps = {p: _stamp(p) for p in files}
        self.points = {}
        self.bindings = set()

    def check(self):
        if any(_stamp(path) != stamp for path, stamp in self._stamps.items()):
            raise ValueError('retained build target changed during the query session')

    def _point(self, namespace, record):
        identity = ResourceDefinitionID(sha256((SCHEMA + ':' + self.snapshot.sha256
            + ':' + self.snapshot.uri + ':' + str(record.id)).encode()).hexdigest())
        return Point(namespace, identity, None)

    def restore(self):
        """Reuse published namespace/pool projections without adding edges."""
        for namespace in {ns for ns, _ in self.provider.pools}:
            points = {r.id: self._point(namespace, r) for r in self.resources}
            if any(p not in self.provider.records for p in points.values()):
                raise ValueError('resource payload lost its target namespace projection')
            self.points[namespace] = points
        self.bindings.update(self.provider.pools)

    def add_namespace(self, namespace):
        if namespace in self.points:
            return self.points[namespace]
        root = Point(namespace, namespace.root, None)
        points = {}
        for record in self.resources:
            if type(record) is H.CpuExecutor:
                kind, role = ResourceKind.CPU, ResourceRole.EXECUTOR
            elif type(record) is H.Accelerator:
                kind, role = ResourceKind.GPU, ResourceRole.EXECUTOR
            elif type(record) is H.MemoryDomain:
                kind, role = ResourceKind.MEMORY, ResourceRole.MEMORY_POOL
            else:
                kind, role = ResourceKind.STORAGE, ResourceRole.STORAGE_ENDPOINT
            point = self._point(namespace, record)
            definition = ResourceDefinition(point.node, kind, role,
                ExternalResource(namespace.root, 'target-snapshot:' + str(record.id)))
            self.provider._record(point, definition, root)
            points[record.id] = point
        self.points[namespace] = points
        for connection in self.connections:
            pairs = ((connection.source, connection.target),)
            if connection.bidirectional:
                pairs += ((connection.target, connection.source),)
            for source, target in pairs:
                self.provider._edge(points[source], points[target],
                    'scar.build.retained-hardware-topology.v1', may=True,
                    guards=(*connection.conditions, 'RETAINED_TOPOLOGY_' + connection.kind.value,
                        'HARDWARE_SNAPSHOT_LINK_NOT_OBSERVED_TRANSFER'), evidence=(self.locator,))
        return points

    @staticmethod
    def _pool_names(record):
        if type(record) is H.CpuExecutor:
            return ('cpu',)
        if type(record) is H.Accelerator:
            return ('gpu',)
        if type(record) is H.MemoryDomain:
            return ('dram',) if record.kind is H.MemoryKind.HOST else ('device-memory',)
        if type(record) is H.StorageDevice:
            return (('ssd',) if record.media_kind == 'non_rotating' else ()) + (
                ('nvme',) if record.transport == 'nvme' else ())
        return ()

    def bind_pool(self, point, name):
        if (point.namespace, name) in self.bindings:
            return
        points = self.add_namespace(point.namespace)
        for record in self.resources:
            if name in self._pool_names(record):
                self.provider._edge(points[record.id], point,
                    'scar.build.retained-target-pool-candidate.v1', may=True,
                    guards=('SCOPE_EXECUTION_AND_RESOURCE_POLICY_SELECT_RECORDED_TARGET',
                        'INVENTORY_CAPACITY_NOT_AVAILABLE_ALLOCATION_BUDGET',
                        'RESOURCE_TYPE_COMPATIBILITY_NOT_PLACEMENT_OR_TRANSFER_PROOF'),
                    evidence=(self.locator,))
        self.bindings.add((point.namespace, name))

    def payload(self):
        self.check()
        return dict(schema=SCHEMA, snapshot=encode(self.snapshot),
            resources=encode(self.resources, record_tags=H.TARGET_RECORD_TAGS),
            connections=encode(self.connections), paths=encode(self.paths),
            physical_use_established=False, allocation_budgets_established=False,
            transfers_observed=False)
