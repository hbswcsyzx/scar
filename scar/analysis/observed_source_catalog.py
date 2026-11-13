"""Compose file declarations with code-equivalent retained compilation graphs.

The catalog routes immutable local shards. It does not create exec namespaces,
select original compiler options, or make generated code importable. Runtime
body evidence selects a bounded material footprint, not a dead-code proof.
"""
import argparse
from bisect import bisect_right
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import time
from types import CodeType, MappingProxyType

from scar.analysis.source_declared_catalog import DeclaredSourceCatalog, _receipt, _check, _stamp
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.analysis.observed_compiled_material import ObservedCompiledLocalMaterial, build_local_material
from scar.ir.program.source_interfaces import UnitSourceInterfaces
from scar.ir.record_codec import decode


SCHEMA = 'scar.observed-source-catalog'
_FALSE = ('original_compile_options_proven', 'execution_namespace_proven',
    'source_code_temporal_pairing_proven', 'target_executed', 'first_stage_complete')


class _Facts:
    def __init__(self, catalog, raw):
        self.catalog = catalog; original = catalog.base.fact_store
        self.path = catalog.path; self.raw = raw; self.report = json.loads(raw)
        self.base = original.base; self.supplemental_sources = original.supplemental_sources
        self.original_source_units = original.original_source_units
        self.importable_units = original.importable_units
        self.observed_compiled_units = frozenset(catalog.materials)
        self.rows = dict(original.rows); self.model_units = dict(original.model_units)
        self.offsets = dict(original.offsets); self.size = original.size
        self.sources = dict(original.sources); self.source_units = dict(original.source_units)
        self._source_parents = dict(original._source_parents); self.loaded = {}
        for identity, material in sorted(catalog.materials.items()):
            if identity in self.rows: raise ValueError('compiled namespace collides with file unit')
            facts = material.fact_store
            self.rows[identity] = dict(facts.row, facts=str(material.path/facts.row['facts']), module=None)
            self.model_units[identity] = facts.model_units[identity]
            self.offsets[identity] = self.size; self.size += facts.size
            self.sources.update(facts.sources); self.source_units.update(facts.source_units)
            self._source_parents[identity] = facts
        if self.report['units'] != self.rows:
            raise ValueError('composite fact directory differs from its primitive leaves')
        self._ordered = tuple(sorted(self.offsets, key=self.offsets.get))
        self._starts = tuple(self.offsets[u] for u in self._ordered)
        for name in ('rows', 'model_units', 'offsets', 'sources', 'source_units', '_source_parents'):
            setattr(self, name, MappingProxyType(getattr(self, name)))

    def validate_parents(self): return self.catalog.validate_materials()
    def _parent(self, identity):
        if identity in self.catalog.materials: return self.catalog.materials[identity].fact_store
        if identity not in self.rows: raise KeyError(identity)
        return self.catalog.base.fact_store
    def source_parent_for(self, identity): return self._parent(identity).source_parent_for(identity)
    def model_for(self, identity): return self._parent(identity).model_for(identity)
    def templates_for(self, identity): return self._parent(identity).templates_for(identity)
    def load(self, identity):
        if identity not in self.loaded: self.loaded[identity] = self._parent(identity).load(identity)
        return self.loaded[identity]
    def document(self, identity): return self._parent(identity).document(identity)
    def units_for_source(self, source): return self.source_units.get(str(Path(source).absolute()), ())
    def locate(self, point):
        if type(point) is not int or not 0 <= point < self.size: raise ValueError('fact point outside catalog')
        unit = self._ordered[bisect_right(self._starts, point)-1]
        return unit, point-self.offsets[unit]


class _Interfaces:
    """Delegate actual summaries; an absent projection is never an empty one."""
    def __init__(self, catalog):
        self.catalog = catalog; self.base = catalog.base.interface_store
        self.stats = self.base.stats; self.loaded = {}
    def validate_parents(self): return self.catalog.validate_materials()
    def covers(self, unit):
        if unit.unit not in self.catalog.materials: return self.base.covers(unit)
        return 'interfaces' in self.catalog.materials[unit.unit].report['tables']
    def load(self, unit):
        if unit.unit not in self.catalog.materials: return self.base.load(unit)
        material = self.catalog.materials[unit.unit]
        if not self.covers(unit): raise ValueError('retained compiled auxiliary interfaces not yet projected')
        if unit.unit not in self.loaded:
            self.loaded[unit.unit] = decode(UnitSourceInterfaces,
                material._document(material.report['tables']['interfaces']))
        return self.loaded[unit.unit]
    def iteration(self, unit, item):
        if unit.unit in self.catalog.materials: raise ValueError('compiled iteration summary not projected')
        return self.base.iteration(unit, item)
    def body(self, unit, item):
        if unit.unit in self.catalog.materials: raise ValueError('compiled suspension summary not projected')
        return self.base.body(unit, item)
    def mapping(self, unit, template):
        if unit.unit in self.catalog.materials: raise ValueError('compiled mapping summary not projected')
        return self.base.mapping(unit, template)


class ObservedSourceCatalog(DeclaredSourceCatalog):
    def __init__(self, path):
        self.path = Path(path).absolute(); self._root_receipt = _receipt(self.path/'result.json')
        self.report = r = json.loads((self.path/'result.json').read_bytes())
        if ((r['schema'], r['schema_version']) != (SCHEMA, 1)
                or r['implementation_sha256'] != sha256(Path(__file__).read_bytes()).hexdigest()
                or any(r[name] is not False for name in _FALSE)):
            raise ValueError('observed source catalog contract or producer differs')
        for receipt in (r['base'], r['matches'], r['facts']): _check(receipt)
        from scar.analysis.compilation_audit import CompilationAuditInputs
        matched = json.loads(Path(r['matches']['path']).read_bytes())
        self.audit = CompilationAuditInputs(matched['trace'])
        if self.audit.receipts != matched['capture_inputs']:
            raise ValueError('observed source catalog audit parents differ from compilation matches')
        self.base = DeclaredSourceCatalog(Path(r['base']['path']).parent)
        self.materials = {}; self.replay_profiles = {}; self._receipts = [r['matches'], r['facts']]
        for entry in r['compiled']:
            _check(entry['material']); self._receipts.append(entry['material'])
            material = ObservedCompiledLocalMaterial(Path(entry['material']['path']).parent)
            unit = material.unit
            if unit in self.materials or unit != entry['unit'] or material.report['recipe'] != entry['recipe']:
                raise ValueError('observed compiled material identity or replay differs')
            if material.report['replayed_root_code'] != entry['root_code']:
                raise ValueError('observed compiled root differs from the matched execution code')
            if not any(all(recipe[k] == entry['recipe'][k] for k in entry['recipe'])
                    for recipe in entry['compatible_recipes']):
                raise ValueError('analysis replay is not one of the retained compatible alternatives')
            self.materials[unit] = material
            self.replay_profiles[unit] = dict(recipe=entry['recipe'], root_code=entry['root_code'])
        self.fact_store = _Facts(self, Path(r['facts']['path']).read_bytes())
        self.interface_store = _Interfaces(self)
        self.units, self.sources = self.fact_store.rows, self.fact_store.sources
        self.inputs, self.templates = self.base.inputs, self.base.templates
        self.validate_parents()

    def validate_materials(self):
        self.base.validate_parents()
        for material in self.materials.values(): material.validate_parents()
        self.audit.check()
        return len(self.materials)

    def evidence_stamps(self):
        self.validate_parents()
        return {**self.audit.guard_stamps(), **{Path(r['path']):_stamp(Path(r['path']))
            for r in (*self._receipts, self._root_receipt)}}

    def validate_parents(self):
        _check(self._root_receipt)
        if json.loads((self.path/'result.json').read_bytes()) != self.report:
            raise ValueError('observed source catalog changed in memory')
        for receipt in self._receipts: _check(receipt)
        self.validate_materials()

    def local_material(self, unit):
        material = self.materials[unit]
        # Keep the leaf's actual primitive facts; the facade needs only these
        # catalog routing fields, not a fictitious exec graph or template store.
        from copy import copy
        result = copy(material)
        result.catalog = self; result.fact_store = self.fact_store
        result._catalog_raw = (self.path/'result.json').read_bytes()
        result._parents = dict(material._parents)
        result._parents[self.path/'result.json'] = result._catalog_raw
        return result


def build_observed_catalog(base, trace, matches, out, *, project_root, material_roots=()):
    from scar.analysis.compilation_audit import CompilationAuditInputs, SCHEMA as MATCH_SCHEMA
    from scar.analysis.call_operand_reader import read_call_operands
    from scar.analysis.source_symbol_variants import SymbolVariantWorker
    from scar.trace.code_snapshot import describe_code
    started = time.monotonic(); base = DeclaredSourceCatalog(base)
    trace = Path(trace).absolute(); matches = Path(matches).absolute(); out = Path(out).absolute()
    if out.resolve() != out or out.exists(): raise ValueError('fresh canonical observed source catalog required')
    if matches.is_dir(): matches /= 'result.json'
    match_receipt = _receipt(matches); report = json.loads(matches.read_bytes())
    audit = CompilationAuditInputs(trace)
    if ((report['schema'], report['schema_version']) != (MATCH_SCHEMA, 1)
            or report['trace'] != str(trace) or report['capture_inputs'] != audit.receipts
            or any(report[k] is not False for k in _FALSE)):
        raise ValueError('compilation matches differ from the actual audit material')
    frames = read_call_operands(trace, project_root)
    captured = {(c.process_id, c.code.key) for c in frames.frame_scan.captures}
    _durable_mkdir(out); _durable_mkdir(out/'compiled')
    entries = []; unselected = []; seen = set(); cache_hits = 0
    material_roots = tuple(Path(p).resolve() for p in material_roots)
    def child_keys(code):
        yield describe_code(code)['key']
        for child in code.co_consts:
            if type(child) is CodeType: yield from child_keys(child)
    with SymbolVariantWorker() as worker:
        for matched in report['matches']:
            groups = defaultdict(list)
            for recipe in matched['recipes']:
                groups[recipe['source_kind'], recipe['source_sha256']].append(recipe)
            for (kind, digest), alternatives in sorted(groups.items()):
                selected = alternatives[0]
                recipe = {k:selected[k] for k in ('filename', 'mode', 'flags', 'dont_inherit', 'optimize')}
                source = audit.sources[matched['process_id'], kind, digest]
                payload = source.raw if kind == 'BYTES' else source.text()
                root = compile(
                    payload, recipe['filename'], recipe['mode'], flags=recipe['flags'],
                    dont_inherit=True, optimize=recipe['optimize'])
                if describe_code(root) != matched['code']:
                    raise ValueError('selected replay no longer matches the complete observed root')
                actual = sorted(k for k in child_keys(root) if (matched['process_id'], k) in captured)
                if not actual:
                    unselected.append(dict(root_code=matched['code'], process_id=matched['process_id'],
                        reason='NO_ROOT_OR_NESTED_BODY_CODE_IN_RETAINED_FRAME_CAPTURE'))
                    continue
                key = sha256(_json((recipe, kind, digest))).hexdigest()
                if key in seen: continue
                seen.add(key)
                folder = next((p/key for p in material_roots if (p/key/'result.json').is_file()), None)
                if folder is None:
                    folder = out/'compiled'/key
                    local = build_local_material(payload, recipe, folder, worker=worker)
                else:
                    local = ObservedCompiledLocalMaterial(folder).report
                    expected_raw = payload if type(payload) is bytes else payload.encode('utf-8')
                    if (local['recipe'] != recipe
                            or local['snapshot']['sha256'] != sha256(expected_raw).hexdigest()):
                        raise ValueError('cached local material has another retained payload or replay')
                    cache_hits += 1
                if local['replayed_root_code'] != matched['code']: raise ValueError('local F4 replay root differs')
                entries.append(dict(unit=local['unit'], material=_receipt(folder/'result.json'),
                    recipe=recipe, root_code=matched['code'], compatible_recipes=alternatives,
                    observed_child_codes=actual, process_id=matched['process_id']))
    rows = dict(base.fact_store.rows)
    for entry in entries:
        material = ObservedCompiledLocalMaterial(Path(entry['material']['path']).parent)
        if material.unit in rows: raise ValueError('local compiled unit collision')
        rows[material.unit] = dict(material.fact_store.row,
            facts=str(material.path/material.fact_store.row['facts']), module=None)
    facts = dict(schema='scar.observed-source-facts', schema_version=1, units=rows)
    _durable_bytes(out/'facts.json', _json(facts), replace=False)
    audit.check(); base.validate_parents(); _check(match_receipt)
    result = dict(schema=SCHEMA, schema_version=1, base=_receipt(base.path/'result.json'),
        facts=_receipt(out/'facts.json'), matches=match_receipt, compiled=entries,
        unselected_roots=unselected, selection='ROOT_OR_NESTED_FULL_CODE_ID_IN_FRAME_CAPTURE',
        imports='ORIGINAL_FILE_UNITS_ONLY', source_units=list(rows),
        material_cache_hits=cache_hits,
        auxiliary_interfaces='ORIGINAL_SUMMARIES_OR_ACTUAL_EMPTY_COMPILED_LEAVES_ONLY',
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        **{name:False for name in _FALSE}, seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json', _json(result), replace=False)
    ObservedSourceCatalog(out)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base', 'trace', 'matches', 'project-root', 'out'): parser.add_argument('--'+name, required=True)
    parser.add_argument('--material-root', action='append', default=[], help='reuse verified immutable local F4 leaves under this directory')
    args = parser.parse_args()
    report = build_observed_catalog(args.base, args.trace, args.matches, args.out,
        project_root=args.project_root, material_roots=args.material_root)
    print(json.dumps(dict(compiled_units=len(report['compiled']), source_units=len(report['source_units']),
        seconds=report['seconds'], first_stage_complete=False)), flush=True)


if __name__ == '__main__': main()
