"""Receipt-bound source templates for local world-dependency queries.

Only existing noncompiled source materials are supported here. Template
dependencies retain shared regions, branches and loop backedges; reading a
recipe does not enter a scope or execute the target program.
"""
from collections import defaultdict, deque
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis.source_declared_catalog import read_source_catalog
from scar.analysis.source_template_batch import read_template_bodies
from scar.analysis.source_template_links import read_template_graph
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_template_links import SourceTemplateKey


class WorldMaterial:
    """Read a source unit's sealed F4 plans without constructing a solver."""

    def __init__(self, catalog, unit):
        self.catalog = read_source_catalog(catalog)
        self.fact_store = self.catalog.fact_store
        if type(unit) is not str or unit not in self.fact_store.rows:
            raise ValueError('world material needs an original catalog source unit')
        if (unit in self.fact_store.original_source_units
                or self.fact_store.rows[unit].get('facts_format') == 'COMPILE_CONTEXT_F4_JSONL'):
            raise ValueError('compiled-context world material is unsupported by this source-only reader')
        self.unit = unit
        self._parents = {}
        self._catalog_raw = self._remember(self.catalog.path/'result.json')
        if json.loads(self._catalog_raw) != self.catalog.report:
            raise ValueError('world material catalog report changed during its strict read')

        def source_parents(store):
            self._remember(store.path/'result.json', store.raw)
            for parent in store.parents:
                source_parents(parent)

        source_parents(self.fact_store.base)
        for store in self.fact_store.supplemental_sources:
            source_parents(store)
        self.source_store = self.fact_store.source_parent_for(unit)
        while self.source_store.parents:
            self.source_store = self.source_store.parents[self.source_store.unit_parent[unit]]
        self.root = Path(self.source_store.templates).absolute()
        self._template_raw = self._remember(self.root/'result.json')
        self.result_artifact = ProviderArtifact(str(self.root/'result.json'),
            sha256(self._template_raw).hexdigest(), len(self._template_raw), 'scar.source-template-link-store')
        self.graph = read_template_graph(self.root, unit)
        self.interfaces = dict(nodes={node.key: node for node in self.graph.templates},
            links={(link.caller, link.step): link for link in self.graph.links})
        self._children = defaultdict(list)
        for link in self.graph.links:
            self._children[link.caller].append(link.callee)
        self._plans = {}
        self.validate_parents()

    def _remember(self, path, expected=None):
        path = Path(path).absolute(); raw = path.read_bytes()
        if ((expected is not None and raw != expected)
                or (path in self._parents and self._parents[path] != raw)):
            raise ValueError('world material source parent byte receipt differs: ' + str(path))
        self._parents[path] = raw
        return raw

    def validate_parents(self):
        """Recheck original catalog, template and source-fact parent bytes."""
        for path, raw in self._parents.items():
            if path.read_bytes() != raw:
                raise ValueError('world material parent changed: ' + str(path))
        if json.loads(self._catalog_raw) != self.catalog.report:
            raise ValueError('world material catalog report changed in memory')
        self.fact_store.validate_parents()
        self.catalog.interface_store.validate_parents()
        return len(self._parents)

    def plans(self, keys):
        """Batch-read missing original plans; cache only strictly verified plans."""
        keys = tuple(keys)
        if any(type(key) is not SourceTemplateKey or key not in self.interfaces['nodes'] for key in keys):
            raise ValueError('world material template key is absent or foreign')
        keys = tuple(dict.fromkeys(keys))
        self.validate_parents()
        wanted = tuple(key for key in keys if key not in self._plans)
        if wanted:
            selected = read_template_bodies(self.root, self.unit, wanted)
            self.validate_parents()
            self._plans.update(selected)
        self.validate_parents()
        return {key: self._plans[key] for key in keys}

    def closure(self, start_key, max_templates=4000):
        """Read a finite template dependency closure once, without loop unrolling."""
        if type(start_key) is not SourceTemplateKey or start_key not in self.interfaces['nodes']:
            raise ValueError('world material root template is absent or foreign')
        if type(max_templates) is not int or max_templates < 1:
            raise ValueError('world material template budget must be a positive integer')
        pending = deque((start_key,)); found = {start_key}; keys = []
        while pending:
            key = pending.popleft(); keys.append(key)
            for child in self._children.get(key, ()):
                if child in found:
                    continue
                if len(found) >= max_templates:
                    raise ValueError('world material template closure exceeds its declared budget')
                found.add(child); pending.append(child)
        return self.plans(keys)
