"""Read historical conditional relations against a current, strict catalog.

Historical producer hashes describe provenance only: their modules are neither
imported nor executed. Availability of a source template or a relation never
establishes scope admission, current contents, runtime dispatch or permission to
transform. The original report's status and event budget remain unchanged.
"""
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis.source_context_query import ContextTargetGraph
from scar.analysis.source_relation_selection import select_relation_rows
from scar.ir.program import source_productions as P
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import decode


_SCHEMA = 'scar.context-source-targets'
_COMPATIBILITY = (
    'source_facts_sha256', 'propagation_pins', 'content_key_semantics',
    'content_encoding', 'namespace_lookup_semantics', 'interface_summary',
    'source_only_publisher_sha256', 'types_sha256',
    'container_implementation_sha256', 'namespace_implementation_sha256',
    'namespace_types_sha256', 'descriptor_implementation_sha256',
    'invocation_implementation_sha256', 'construction_implementation_sha256',
    'generator_implementation_sha256', 'generator_types_sha256',
    'suspension_interface_implementation_sha256', 'suspension_interface_types_sha256',
    'source_reader_pins',
)


def _stamp(path):
    value = path.stat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _local_path(root, relative):
    if type(relative) is not str or not relative:
        raise ValueError('snapshot fragment needs its original relative path')
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('snapshot fragment is outside its original directory')
    return root / path


class RelationSnapshot:
    """Receipt-bound rows, without granting a historical solver new authority."""
    semantics = 'HISTORICAL_CONDITIONAL_RELATIONS_NOT_CURRENT_STATE_OR_ADMISSION'

    def __init__(self, path, catalog):
        self.path = Path(path).absolute()
        self.raw = (self.path / 'result.json').read_bytes()
        self.report = report = json.loads(self.raw)
        if ((report.get('schema'), report.get('schema_version'), report.get('profile'))
                != (_SCHEMA, 1, 'NORMAL_SUCCESS')
                or type(report.get('schema_version')) is not int
                or report.get('target_executed') is not False):
            raise ValueError('historical normal source-context snapshot required')
        if report.get('status') not in ('CONTEXT_TARGET_BUDGET_FRONTIER', 'CONTEXT_TARGET_FIXED_POINT'):
            raise ValueError('historical context snapshot status differs')
        for name in ('first_stage_complete', 'transformation_authorized',
                     'runtime_dispatch_verified', 'effects_proven'):
            if report.get(name) is not False:
                raise ValueError('relation snapshot has no execution or transformation authority')

        self.catalog = catalog if isinstance(catalog, ContextTargetGraph) else ContextTargetGraph(catalog)
        self.canonical_catalog = self.catalog
        self.fact_store = self.catalog.fact_store
        self._parents = {}
        self._table_stamps = {}
        self._catalog_raw = (self.catalog.path / 'result.json').read_bytes()
        if json.loads(self._catalog_raw) != self.catalog.report:
            raise ValueError('canonical context report changed during its strict read')
        current = self.catalog.report
        for name in _COMPATIBILITY:
            if name not in report or name not in current or report[name] != current[name]:
                raise ValueError('historical relation ABI or semantics differ: ' + name)
        old_pins, live_pins = report.get('extension_pins'), current.get('extension_pins')
        if (type(old_pins) is not dict or type(live_pins) is not dict
                or any(old_pins.get(key) != value for key, value in live_pins.items())):
            raise ValueError('historical source-context rule pins differ')
        # Additional historical scheduling-profile code remains inert evidence.
        self.historical_producer_sha256 = report['implementation_sha256']
        self.historical_profile_pins = {key: value for key, value in old_pins.items() if key not in live_pins}
        self.result_artifact = ProviderArtifact(str(self.path / 'result.json'),
            sha256(self.raw).hexdigest(), len(self.raw), _SCHEMA)
        self.catalog_artifact = ProviderArtifact(str(self.catalog.path / 'result.json'),
            sha256(self._catalog_raw).hexdigest(), len(self._catalog_raw), _SCHEMA)
        self._remember(self.path / 'result.json', self.raw)
        self._remember(self.catalog.path / 'result.json', self._catalog_raw)

        source_raw = self._remember(Path(report['source_facts']) / 'result.json',
                                    expected_sha=report['source_facts_sha256'])
        if source_raw != self.fact_store.base.raw:
            raise ValueError('historical base fact catalog differs from the canonical bytes')
        for name in ('namespace_graph', 'script_entry'):
            if report.get(name) != current.get(name):
                raise ValueError('historical context parent differs: ' + name)
            self._reference(report[name])
        if report.get('supplemental_sources', []) != current.get('supplemental_sources', []):
            raise ValueError('historical supplemental source/interface parents differ')
        for pair in report.get('supplemental_sources', []):
            for reference in pair.values():
                self._reference(reference)

        for folder, document in ((self.path, report), (self.catalog.path, current)):
            receipt = document['context_facts']
            raw = self._remember(_local_path(folder, receipt['path']),
                expected_sha=receipt['sha256'], expected_size=receipt['bytes'])
            if raw != self.fact_store.raw:
                raise ValueError('historical context fact catalog differs from the canonical bytes')

        self._source_parents(self.fact_store.base)
        for parent in self.fact_store.supplemental_sources:
            self._source_parents(parent)
        namespace = self.catalog.namespace_graph
        self._reference(namespace.report['binding_variants'])
        self._reference(namespace.report['exec_roots'])
        for name in ('source_execution', 'compiled_sources', 'f4_graphs'):
            self._reference(namespace.exec_graph.report[name])
        self.validate_parents()

    def _remember(self, path, expected=None, *, expected_sha=None, expected_size=None):
        path = Path(path).absolute()
        raw = path.read_bytes()
        if ((expected is not None and raw != expected)
                or (expected_sha is not None and sha256(raw).hexdigest() != expected_sha)
                or (expected_size is not None and len(raw) != expected_size)
                or (path in self._parents and self._parents[path] != raw)):
            raise ValueError('relation snapshot parent byte receipt differs: ' + str(path))
        self._parents[path] = raw
        return raw

    def _reference(self, reference):
        return self._remember(Path(reference['path']) / 'result.json',
                              expected_sha=reference['sha256'])

    def _source_parents(self, store):
        self._remember(store.path / 'result.json', store.raw)
        if store.parents:
            for parent in store.parents:
                self._source_parents(parent)
        else:
            self._remember(store.templates / 'result.json', expected_sha=store.report['source_result_sha256'])
            self._remember(store.model / 'manifest.json', expected_sha=store.report['model_manifest_sha256'])

    def rows(self, name, predicate, record_type):
        """Validate the entire table, then decode only predicate-selected rows.

        ``predicate`` receives original wire records. Returned ordinals and fact
        references stay scoped to this historical artifact, not the live graph.
        """
        self.validate_parents()
        receipt = self.report.get(name)
        required = ('path', 'bytes', 'sha256', 'decoded_bytes', 'decoded_sha256', 'records')
        if type(receipt) is not dict or any(key not in receipt for key in required):
            raise ValueError('historical relation table is absent: ' + str(name))
        path = _local_path(self.path, receipt['path'])
        before = _stamp(path)
        selected = select_relation_rows(self.path, receipt, predicate)
        if _stamp(path) != before:
            raise ValueError('historical relation table changed during selection')
        self._table_stamps[path] = before
        artifact = ProviderArtifact(str(path), receipt['sha256'], receipt['bytes'], 'scar.context.' + name)
        rows = tuple((ordinal, decode(record_type, wire, record_tags=P.PRODUCTION_RECORD_TAGS),
                      ProviderFactReference(artifact, '#/records/' + str(ordinal)))
                     for ordinal, wire in selected)
        self.validate_parents()
        return rows

    def validate_parents(self):
        """Recheck original report bytes and all already verified parent guards."""
        for path, raw in self._parents.items():
            if path.read_bytes() != raw:
                raise ValueError('relation snapshot parent changed: ' + str(path))
        if self.report != json.loads(self.raw) or self.catalog.report != json.loads(self._catalog_raw):
            raise ValueError('relation snapshot report was modified in memory')
        self.fact_store.validate_parents()
        self.catalog.interface_store.validate_parents()
        for path, stamp in self._table_stamps.items():
            if _stamp(path) != stamp:
                raise ValueError('verified historical relation table changed: ' + str(path))
        return len(self._parents) + len(self._table_stamps)
