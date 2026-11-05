"""Read compact local interfaces without recovering complete F4 plans."""
from hashlib import sha256
from functools import lru_cache
import gzip
import json
from pathlib import Path
import sys

from scar.ir.program import source_interfaces as L, source_productions as P, normal_links as F
from scar.ir.record_codec import decode


@lru_cache(maxsize=1)
def _declaration_files():
    from scar.analysis.source_productions import production_type_catalog
    return tuple(Path(sys.modules[name].__file__).resolve() for name in production_type_catalog()['modules'])


def projection_pins():
    from scar.analysis.source_expression_materials import _implementation
    from scar.analysis.source_template_links import _compiler_profile
    package = Path(__file__).resolve().parents[1]
    names = ('analysis/source_interface_store.py', 'analysis/source_interface_build.py',
             'analysis/source_suspension_interfaces.py', 'ir/program/source_interfaces.py',
             'ir/program/suspension_interfaces.py', 'ir/program/normal_targets.py')
    paths = {str(package/name) for name in (*names,*_implementation())}
    paths.update(str(path) for path in _declaration_files())
    paths.add(_compiler_profile()['header'])
    return {path:sha256(Path(path).read_bytes()).hexdigest() for path in sorted(paths)}


def file_receipt(path):
    path = Path(path).absolute()
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=sha256(raw).hexdigest())


def _stamp(path):
    value = Path(path).stat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


class SourceInterfaceStore:
    def __init__(self, path, facts):
        self.path = Path(path).absolute()
        self.raw = (self.path/'result.json').read_bytes()
        self.report = json.loads(self.raw)
        r = self.report
        if (r['schema'],r['schema_version'],r['status']) != ('scar.local-source-interfaces',1,'LOCAL_INTERFACES_PROJECTED'):
            raise ValueError('expected completed local source interfaces')
        if r['projection_pins'] != projection_pins():
            raise ValueError('local interface projection implementation differs')
        if r['source_facts_sha256'] != sha256(facts.raw).hexdigest() or Path(r['source_facts']) != facts.path:
            raise ValueError('local interfaces belong to another source fact catalog')
        self.facts = facts
        self.rows = {row['unit']:row for row in r['units']}
        if len(self.rows)!=r['selected_sources'] or not self.rows.keys()<=facts.rows.keys():
            raise ValueError('local interface unit directory differs')
        self.loaded = {};self.iterations = {};self.bodies = {};self.mappings = {};self.pins = {}
        self.stats = dict(unit_reads=0,iteration_reads=0,body_reads=0,mapping_reads=0)
        self._admit(dict(path=str(self.path/'result.json'),bytes=len(self.raw),sha256=sha256(self.raw).hexdigest()))
        for receipt in r['parents']:self._admit(receipt)

    def _admit(self, receipt):
        path = Path(receipt['path']);before = _stamp(path)
        if path in self.pins:
            if self.pins[path]!=before:raise ValueError('local interface input changed')
            return
        raw = path.read_bytes()
        if len(raw)!=receipt['bytes'] or sha256(raw).hexdigest()!=receipt['sha256'] or _stamp(path)!=before:
            raise ValueError('local interface byte receipt differs')
        self.pins[path] = before

    def validate_parents(self):
        for path,stamp in self.pins.items():
            if _stamp(path)!=stamp:raise ValueError('local interface snapshot changed during query')

    def covers(self, unit):
        return unit.unit in self.rows

    @property
    def receipt(self):
        return dict(path=str(self.path),sha256=sha256(self.raw).hexdigest(),
                    selected_sources=len(self.rows),catalog_complete=len(self.rows)==len(self.facts.rows))

    def load(self, unit):
        if unit.unit in self.loaded:return self.loaded[unit.unit]
        row = self.rows[unit.unit]
        if row['facts_sha256']!=self.facts.rows[unit.unit]['sha256']:
            raise ValueError('local interface source unit differs')
        for receipt in row['inputs']:self._admit(receipt)
        path = self.path/row['interfaces']
        self._admit(dict(path=str(path),bytes=row['bytes'],sha256=row['sha256']))
        raw = gzip.decompress(path.read_bytes())
        if len(raw)!=row['decoded_bytes'] or sha256(raw).hexdigest()!=row['decoded_sha256']:
            raise ValueError('decoded local interface receipt differs')
        value = decode(L.UnitSourceInterfaces,json.loads(raw),record_tags=P.PRODUCTION_RECORD_TAGS)
        if value.unit!=unit.unit:raise ValueError('local interface unit identity differs')
        expected = {i for i,f in enumerate(unit.functions) if f.environment.kind is not P.DeferredBodyKind.FUNCTION}
        if ({x.fact for x in value.iterations}!=set(range(len(unit.iterations)))
                or len(value.iterations)!=len(unit.iterations)
                or {x.fact for x in value.bodies}!=expected or len(value.bodies)!=len(expected)):
            raise ValueError('local interface family coverage differs')
        for entry in value.iterations:
            self.iterations[unit.unit,unit.iterations[entry.fact]] = entry.site
        for entry in value.bodies:
            self.bodies[unit.unit,unit.functions[entry.fact].value] = entry.site
        for entry in value.mappings:self.mappings[unit.unit,entry.template] = entry
        if len({x.template for x in value.mappings})!=len(value.mappings):
            raise ValueError('duplicate mapping interface template')
        expected_mapping = set()
        for item in unit.containers:
            if item.kind is not F.ContainerKind.MAPPING:continue
            raw = unit.ports[item.value]
            expected_mapping.add((raw['template']['occurrence'],raw['template']['purpose']) if type(raw) is dict
                                 else (raw.template.occurrence,raw.template.purpose.value))
        if {(x.template.occurrence,x.template.purpose.value) for x in value.mappings}!=expected_mapping:
            raise ValueError('mapping interface coverage differs')
        self.loaded[unit.unit]=value;self.stats['unit_reads']+=1
        return value

    def iteration(self, unit, item):
        self.load(unit);self.stats['iteration_reads']+=1
        return self.iterations[unit.unit,item]

    def body(self, unit, function):
        self.load(unit);self.stats['body_reads']+=1
        site = self.bodies[unit.unit,function.value]
        if site.body_scope!=function.body_scope or site.kind is not function.environment.kind:
            raise ValueError('local body interface selects another original function')
        return site

    def mapping(self, unit, template):
        self.load(unit);self.stats['mapping_reads']+=1
        # Missing is a projection/coverage error, never a proven empty effect.
        return self.mappings[unit.unit,template]
