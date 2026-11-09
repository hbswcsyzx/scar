"""One F4 material interface for ordinary and compile-context source graphs.

The format selects the reader, never a workload or callable name. Compiled
plans are read from their original receipt-bound tables, without recompiling
source, executing code, renumbering ports or expanding loop iterations.
"""
from collections import defaultdict
from hashlib import sha256
import json

from scar.analysis.source_context_query import ContextTargetGraph
from scar.analysis.source_world_material import WorldMaterial
from scar.analysis.source_relation_selection import select_relation_rows
from scar.analysis.source_consumer_parents import _stamp
from scar.analysis.source_productions import _digest, read_production_plan
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_template_links import SourceTemplateKey


class CompiledGraphMaterial(WorldMaterial):
    """Expose existing compile-context recipes through the source reader API."""

    def __init__(self, catalog, unit):
        self.catalog = catalog if isinstance(catalog, ContextTargetGraph) else ContextTargetGraph(catalog)
        self.fact_store = self.catalog.fact_store
        if unit not in self.fact_store.original_source_units:
            raise ValueError('compiled material requires an original compile-context source identity')
        self.unit = unit; self._parents = {}; self._tables = {}; self._plans = {}
        self._catalog_raw = self._remember(self.catalog.path/'result.json')
        if json.loads(self._catalog_raw) != self.catalog.report:
            raise ValueError('compiled material source catalog changed')
        self.exec_graph = self.fact_store.exec_graph
        self._remember(self.exec_graph.path/'result.json')
        self.root, report = self.exec_graph.parents['f4_graphs']
        raw = self._remember(self.root/'result.json')
        if json.loads(raw) != report:
            raise ValueError('compiled material F4 report changed')
        self.result_artifact = ProviderArtifact(str(self.root/'result.json'), sha256(raw).hexdigest(),
            len(raw), report['schema'])
        self.descriptor = report['variants'][unit]
        if self.descriptor['original_source_unit'] != self.fact_store.original_source_units[unit]:
            raise ValueError('compiled material original source identity differs')
        connection = next(c for c in self.exec_graph.connections() if c.root.owner.unit == unit)
        receipt = self.descriptor['tables']['templates']
        table = self.root/self.descriptor['path']/receipt['path']; before = _stamp(table)
        self.graph = self.exec_graph.expand_root(connection)
        if before != _stamp(table): raise ValueError('compiled template table changed while reading')
        self._tables[table] = before
        self.interfaces = dict(nodes={n.key: n for n in self.graph.templates},
            links={(link.caller, link.step): link for link in self.graph.links})
        self._children = defaultdict(list)
        for link in self.graph.links: self._children[link.caller].append(link.callee)
        self.validate_parents()

    def validate_parents(self):
        if any(_stamp(path) != stamp for path, stamp in self._tables.items()):
            raise ValueError('compiled source material table changed')
        return super().validate_parents()

    def plans(self, keys):
        keys = tuple(dict.fromkeys(keys))
        if any(type(key) is not SourceTemplateKey or key not in self.interfaces['nodes'] for key in keys):
            raise ValueError('compiled material template key is absent or foreign')
        self.validate_parents()
        domains = defaultdict(dict)
        for key in keys:
            if key not in self._plans:
                node = self.interfaces['nodes'][key]
                domains[node.origin.domain.value][key.occurrence, key.purpose.value] = key, node
        selected = {}
        for domain, wanted in domains.items():
            receipt = self.descriptor['tables'][domain]
            folder = self.root/self.descriptor['path']; table = folder/receipt['path']; before = _stamp(table)
            rows = select_relation_rows(folder, receipt,
                lambda wire: (wire['source'].get('occurrence'), wire['purpose']) in wanted)
            if before != _stamp(table): raise ValueError('compiled recipe table changed during reading')
            for ordinal, wire in rows:
                key, node = wanted[wire['source']['occurrence'], wire['purpose']]
                if ordinal+1 != node.origin.line or _digest(wire) != node.origin.plan_sha256:
                    raise ValueError('compiled recipe location or digest differs from its original template')
                plan = read_production_plan(wire)
                if (key in selected or plan.source.occurrence != key.occurrence or plan.purpose is not key.purpose
                        or plan.root != node.root or plan.input != self.graph.input or plan.profile != self.graph.profile):
                    raise ValueError('compiled recipe identity, input, profile or coverage differs')
                selected[key] = plan
            self._tables[table] = before
        if set(selected) != {key for key in keys if key not in self._plans}:
            raise ValueError('compiled recipe selection did not cover the requested templates')
        self.validate_parents(); self._plans.update(selected)
        return {key: self._plans[key] for key in keys}


def source_graph_material(catalog, unit):
    """Select by the source catalog's format; keep its original identities."""
    catalog = catalog if isinstance(catalog, ContextTargetGraph) else ContextTargetGraph(catalog)
    if unit in catalog.fact_store.original_source_units:
        return CompiledGraphMaterial(catalog, unit)
    return WorldMaterial(catalog, unit)
