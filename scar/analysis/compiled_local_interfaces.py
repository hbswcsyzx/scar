"""Project existing compiled-local F4 interfaces without replaying source rules.

Only iteration, deferred-body and mapping interfaces are projected. Their
witnesses retain the actual local material receipt and never invent a static
model manifest, runtime namespace or suspension/resume instance.
"""
import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis.observed_compiled_material import ObservedCompiledLocalMaterial
from scar.analysis.source_interface_build import _project
from scar.analysis.source_interface_store import SourceInterfaceStore, file_receipt, projection_pins
from scar.analysis.source_productions import _digest
from scar.analysis.source_reference_slice import source_port
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import normal_links as F, source_productions as P
from scar.ir.program.suspension_interfaces import WitnessSource
from scar.ir.record_codec import decode, encode


SCHEMA = 'scar.compiled-local-interfaces'
_FALSE = ('target_executed', 'source_rules_replayed', 'source_bodies_activated',
    'runtime_namespace_proven', 'resume_instances_proven', 'first_stage_complete')
_FAMILIES = ('iterations', 'bodies', 'mappings')


def _producer():
    return sha256(Path(__file__).read_bytes()).hexdigest()


def _counts(value):
    return dict(iterations=len(value.iterations), bodies=len(value.bodies), mappings=len(value.mappings),
        merges=sum(len(entry.merges) for entry in value.mappings),
        suspensions=sum(len(entry.site.suspensions) for entry in value.bodies))


def _selected_plans(material, unit):
    """Read all wire headers, decode only required or suspending sealed plans."""
    required = {source_port(unit, item.value).port.template for item in unit.iterations}
    required.update(f.template for f in unit.functions if f.environment.kind is not P.DeferredBodyKind.FUNCTION)
    required.update(source_port(unit, item.value).port.template for item in unit.containers
        if item.kind is F.ContainerKind.MAPPING)
    if not required:
        return {}, (), 0
    graph = material.graph
    origins = {(node.origin.domain.value, node.origin.line):node for node in graph.templates}
    discriminator, tag = P.PRODUCTION_RECORD_TAGS[P.SuspendExecution]
    plans = {}; seen = set(); inputs = []
    for domain in sorted({key[0] for key in origins}):
        descriptor = material.report['tables'][domain]
        records = material._document(descriptor)['records']
        inputs.append(file_receipt(material.path/descriptor['path']))
        for line, document in enumerate(records, 1):
            node = origins.get((domain, line))
            if node is None: continue
            seen.add((domain, line))
            if node.key not in required and not any(
                    step['instruction'].get(discriminator) == tag for step in document['steps']):
                continue
            if _digest(document) != node.origin.plan_sha256:
                raise ValueError('compiled interface selected another sealed plan')
            # F4 already admitted this plan. Match its original identity and
            # immutable proof instead of rebuilding the complete type catalog.
            plan = decode(P.SourceProductionPlan, document, record_tags=P.PRODUCTION_RECORD_TAGS)
            if (plan.source != P.ProductionOccurrence(node.key.occurrence) or plan.purpose is not node.key.purpose
                    or plan.root != node.root or plan.input != graph.input or plan.profile != graph.profile):
                raise ValueError('compiled interface plan identity/input/profile differs')
            plans[node.key] = plan
    if seen != set(origins) or not required <= plans.keys():
        raise ValueError('compiled interface selected template coverage differs')
    material.validate_parents()
    return plans, tuple(inputs), len(seen)


def build_material_interfaces(material_path, out):
    """Publish all three interface families from one actual immutable F4 leaf."""
    started = time.monotonic()
    material = (material_path if isinstance(material_path, ObservedCompiledLocalMaterial)
        else ObservedCompiledLocalMaterial(material_path))
    out = Path(out).absolute()
    if out.resolve() != out or out.exists():
        raise ValueError('fresh canonical compiled interface output required')
    pins, producer = projection_pins(), _producer()
    unit = material.fact_store.load(material.unit)
    plans, selected_inputs, scanned = _selected_plans(material, unit)
    parent = file_receipt(material.path/'result.json')
    facts = file_receipt(material.path/material.report['tables']['facts']['path'])
    graph = file_receipt(material.path/material.report['tables']['graph']['path'])
    value = _project(unit, material.graph, plans, parent['sha256'], None,
        fact_store=material.fact_store, witness_source=WitnessSource.SEALED_COMPILED_LOCAL_MATERIAL)
    material.validate_parents()
    if pins != projection_pins() or producer != _producer():
        raise ValueError('compiled interface projector changed during projection')
    raw = _json(encode(value, record_tags=P.PRODUCTION_RECORD_TAGS))
    payload = gzip.compress(raw, compresslevel=3, mtime=0)
    _durable_mkdir(out); _durable_bytes(out/'interfaces.json.gz', payload, replace=False)
    inputs = tuple(dict((entry['path'], entry) for entry in (parent, facts, graph, *selected_inputs)).values())
    row = dict(unit=unit.unit, interfaces='interfaces.json.gz', bytes=len(payload),
        sha256=sha256(payload).hexdigest(), decoded_bytes=len(raw), decoded_sha256=sha256(raw).hexdigest(),
        facts_sha256=facts['sha256'], inputs=inputs, counts=_counts(value))
    report = dict(schema=SCHEMA, schema_version=1, status='COMPILED_LOCAL_INTERFACES_PROJECTED',
        unit=unit.unit, material=parent, facts=facts, row=row, parents=inputs,
        projection_pins=pins, implementation_sha256=producer,
        families_complete={name:True for name in _FAMILIES}, counts=_counts(value),
        scanned_templates=scanned, selected_plans=len(plans), catalog_templates=len(material.graph.templates),
        witness_source=WitnessSource.SEALED_COMPILED_LOCAL_MATERIAL.value,
        **{name:False for name in _FALSE}, seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json', _json(report), replace=False)
    CompiledLocalInterfaces(out, material)
    return report


class CompiledLocalInterfaces(SourceInterfaceStore):
    """Reuse the standard family coverage/port reader for a compiled F4 leaf."""
    def __init__(self, path, material):
        self.material = (material if isinstance(material, ObservedCompiledLocalMaterial)
            else ObservedCompiledLocalMaterial(material))
        self.path = Path(path).absolute()
        if self.path.resolve() != self.path:
            raise ValueError('canonical compiled interface directory required')
        self.raw = (self.path/'result.json').read_bytes()
        self.report = report = json.loads(self.raw)
        if ((report['schema'], report['schema_version'], report['status'])
                != (SCHEMA, 1, 'COMPILED_LOCAL_INTERFACES_PROJECTED')
                or report['implementation_sha256'] != _producer()
                or report['projection_pins'] != projection_pins()
                or report['unit'] != self.material.unit
                or report['witness_source'] != WitnessSource.SEALED_COMPILED_LOCAL_MATERIAL.value
                or report['families_complete'] != {name:True for name in _FAMILIES}
                or any(report[name] is not False for name in _FALSE)):
            raise ValueError('compiled interface producer/material/coverage contract differs')
        if (report['material'] != file_receipt(self.material.path/'result.json')
                or report['facts'] != file_receipt(self.material.path/self.material.report['tables']['facts']['path'])
                or report['row']['unit'] != self.material.unit):
            raise ValueError('compiled interface original result/fact parent differs')
        self.facts = self.material.fact_store
        self.rows = {self.material.unit:report['row']}
        self.loaded = {}; self.iterations = {}; self.bodies = {}; self.mappings = {}; self.pins = {}
        self.stats = dict(unit_reads=0, iteration_reads=0, body_reads=0, mapping_reads=0)
        self._admit(file_receipt(self.path/'result.json'))
        for parent in report['parents']: self._admit(parent)
        self.load(self.facts.load(self.material.unit))
        self.validate_parents()

    def validate_parents(self):
        self.material.validate_parents()
        super().validate_parents()
        if json.loads(self.raw) != self.report:
            raise ValueError('compiled interface in-memory report changed')
        return len(self.pins)

    def load(self, unit):
        self.validate_parents()
        value = super().load(unit)
        if _counts(value) != self.report['counts'] or self.rows[unit.unit]['counts'] != self.report['counts']:
            raise ValueError('compiled interface count denominator differs')
        witnesses = [entry.site.witness for entry in value.iterations]
        witnesses.extend(site.witness for entry in value.bodies for site in entry.site.suspensions)
        witnesses.extend(merge.witness for entry in value.mappings for merge in entry.merges)
        for witness in witnesses:
            if (witness.unit != self.material.unit
                    or witness.source is not WitnessSource.SEALED_COMPILED_LOCAL_MATERIAL
                    or witness.template_result_sha256 != self.report['material']['sha256']
                    or witness.model_manifest_sha256 is not None):
                raise ValueError('compiled interface witness selects another material kind or parent')
        self.validate_parents()
        return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--material', required=True); parser.add_argument('--out', required=True)
    args = parser.parse_args()
    result = build_material_interfaces(args.material, args.out)
    print(json.dumps({name:result[name] for name in ('status', 'counts', 'selected_plans', 'seconds')}), flush=True)


if __name__ == '__main__': main()
