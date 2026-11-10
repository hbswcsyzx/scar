"""Load original exec compiler profiles and replay only their retained text.

The original compile caller's dont_inherit and requested flags remain in the
request/context records. Replay explicitly supplies the recorded effective
flags with dont_inherit=True, as the original compiled-values producer does.
No runtime code flags are interpreted as compiler inputs. Exec alternatives
retain separate original facts even when their shared root code matches.
"""
from hashlib import sha256
from io import BytesIO, TextIOWrapper
import json
from pathlib import Path
import sys
from types import CodeType

from scar.analysis import source_compiled_values as compiled, source_execution, source_text_values
from scar.analysis import source_compilation_contexts, source_context_variants, source_f4_variants
from scar.analysis.call_compilation import supported_future_flag_mask
from scar.analysis.source_context_query import ContextTargetGraph
from scar.analysis.source_reference_slice import ReferenceSlicer
from scar.analysis.source_bytes import read_source_bytes
from scar.analysis.source_syntax import _digest
from scar.analysis.static_query import _Fragments
from scar.ir.program import source_compiled_values as C, source_execution as E, source_text as S
from scar.ir.program import source_context_variants as CV, source_compiled_code_profiles as R
from scar.ir.program.call_edges import CapturedCode, CodeCapture
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.program.source_fact_materials import FactMaterialRoute
from scar.ir.program.source_compiled_code_profiles import (
    CompiledCodeProfile, CompiledExecAlternative, CompiledRootCodeMatch)
from scar.ir.record_codec import decode
from scar.trace.code_snapshot import describe_code


class CompiledCodeProfiles:
    """One compiled F4 unit's shared code and all original exec alternatives.

    ``code`` is a static replay product. ``match_capture`` returns conditional
    template correspondences; it deliberately does not select ``branches``.
    """
    def __init__(self, catalog, unit):
        self.catalog = catalog if isinstance(catalog, ContextTargetGraph) else ContextTargetGraph(catalog)
        store = self.catalog.fact_store
        if unit not in store.original_source_units:
            raise ValueError('compiled profile requires an original compile-context unit')
        self.unit = unit
        self.original_source_unit = store.original_source_units[unit]
        self._guard = {}; self._material_routes = {}
        self._remember(self.catalog.path/'result.json')
        graph = store.exec_graph
        self._remember(graph.path/'result.json')
        connections = tuple((i, c) for i, c in enumerate(graph.connections()) if c.root.owner.unit == unit)
        if not connections:
            raise ValueError('compiled unit has no original exec connection')
        self._remember_table(graph.path, graph.report['tables']['connections'])
        facts = store.load(unit)
        self.root_scope = facts.root_scope
        if self.root_scope is None or any(c.root != self.root_scope for _, c in connections):
            raise ValueError('exec alternatives disagree with the original compiled root')
        row = store.rows[unit]
        fact_raw = self._remember(Path(row['facts']))
        if len(fact_raw) != row['bytes'] or sha256(fact_raw).hexdigest() != row['sha256']:
            raise ValueError('compiled root facts receipt differs')
        root_fact = ProviderFactReference(ProviderArtifact(row['facts'], row['sha256'], row['bytes'],
            'scar.source-facts-unit'), '#/records/0/root_scope')

        cp, cr = graph.parents['compiled_sources']
        eroot, er = graph.parents['source_execution']
        cr2, crows, cref = compiled._overlay(cp, 'scar.source-compiled-values', compiled, C,
            {'candidates': C.CompiledSourceCandidate})
        er2, erows, eref = compiled._overlay(eroot, 'scar.source-builtin-execution', source_execution, E,
            {'boundaries': E.SourceBuiltinInvocation, 'compilation-contexts': E.SourceCompilationRequest,
             'compiled-code-uses': E.CompiledCodeUse})
        if (cr2 != cr or er2 != er or cr['source_execution'] != eref
                or cref != graph.report['compiled_sources'] or eref != graph.report['source_execution']):
            raise ValueError('compiler profile parent chain differs from the exec graph')
        if cr['compiler_digest_sha256'] != sha256(Path(source_compilation_contexts.__file__).read_bytes()).hexdigest():
            raise ValueError('original code digest implementation differs')
        self._remember(cp/'result.json'); self._remember(eroot/'result.json')
        for name in ('candidates',): self._remember_table(cp, cr['tables'][name])
        for name in erows: self._remember_table(eroot, er['tables'][name])
        troot = Path(cr['source_text']['path'])
        tr, trows, tref = compiled._overlay(troot, 'scar.source-text-candidates', source_text_values, S,
            {'candidates': S.SourceTextCandidate})
        if tref != cr['source_text'] or any(r['source_facts_sha256'] != graph.report['source_facts_sha256']
                for r in (cr, er, tr)):
            raise ValueError('source text/compiler/execution facts belong to different parents')
        self._remember(troot/'result.json'); self._remember_table(troot, tr['tables']['candidates'])

        # Follow the original F4 -> compiler-symbol -> C1 variant receipts.
        froot, fr = graph.parents['f4_graphs']
        self._remember(froot/'result.json')
        sp, sraw, sr, sref = source_f4_variants.S._report(fr['compiler_symbols']['path'],
            'scar.source-compiler-symbol-variants', source_f4_variants.S)
        vp, vraw, vr, vref = source_f4_variants.S._report(sr['context_variants']['path'],
            'scar.source-context-variants', source_context_variants)
        if sref != fr['compiler_symbols'] or vref != sr['context_variants']:
            raise ValueError('compiled context receipt chain differs')
        self._remember(sp/'result.json'); self._remember(vp/'result.json')
        vd = vr['variants'][unit]
        vdoc = source_f4_variants.S._variant(vp, vd)
        self._remember(vp/vd['path'])
        variant = decode(CV.SourceContextVariant, vdoc)
        if variant.namespace != unit or variant.source_unit != self.original_source_unit:
            raise ValueError('compiled context and original source unit differ')
        context_fact = ProviderFactReference(self._artifact(vp/vd['path'], vr['schema']), '#/context')
        self.context_variant = variant

        model = store.model_units[self.original_source_unit]
        self.syntax_root = Path(store.model_for(self.original_source_unit))
        manifest_path = self.syntax_root/'manifest.json'
        manifest_raw = self._remember(manifest_path)
        manifest = json.loads(manifest_raw)
        ordinals = [i for i, u in enumerate(manifest['units']) if u['key'] == self.original_source_unit]
        if len(ordinals) != 1:
            raise ValueError('original source has no unique manifest declaration')
        self.source_syntax_descriptor = model['artifacts']['source_syntax']
        fragments = _Fragments(self.syntax_root)
        f0d = model['artifacts']['source_bytes']
        f0 = fragments.read(f0d)
        f2 = fragments.read(self.source_syntax_descriptor)
        for descriptor in (f0d, self.source_syntax_descriptor):
            self._remember_table(self.syntax_root, descriptor)
        self.raw_source = read_source_bytes(f0)
        self.source_path = f0['path']
        self.syntax = decode(SourceSyntaxMaterial, f2)
        self.syntax_locator = self._source_locator(self.source_syntax_descriptor, manifest_path,
            ordinals[0], 'source_syntax', 'scar.source-syntax')
        source_locator = self._source_locator(f0d, manifest_path, ordinals[0],
            'source_bytes', 'scar.source-bytes+gzip-json')

        profiles = []
        ids = {c.compiled_candidate for _, c in connections}
        slicer = ReferenceSlicer(type('SourceFacts', (), {'fact_store': store})())
        for i, candidate in enumerate(crows['candidates']):
            if candidate.id not in ids: continue
            if (candidate.source_unit != self.original_source_unit or candidate.context != variant.context
                    or candidate.code_digest != variant.code_digest
                    or candidate.text_utf8_sha256 != variant.text_utf8_sha256):
                raise ValueError('exec compiler candidate differs from the sealed F4 context')
            context = candidate.context
            if context.runtime.implementation != sys.implementation.name or context.runtime.version != tuple(sys.version_info):
                raise ValueError('compiler replay runtime differs')
            requests = [(n, r) for n, r in enumerate(erows['compilation-contexts'])
                        if r.invocation_result == candidate.compile_result]
            if len(requests) != 1: raise ValueError('compiler candidate lacks one original request')
            ri, request = requests[0]
            inherited = 0 if request.dont_inherit else request.inherited_future_flags
            if (request.requested_flags != context.requested_flags or request.dont_inherit != context.caller_dont_inherit
                    or inherited != context.inherited_future_flags or request.effective_optimize != context.optimize
                    or context.compiler_input_flags != request.requested_flags | inherited):
                raise ValueError('original compile request and effective context disagree')
            bi = candidate.builtin_boundary_ordinal
            boundary = erows['boundaries'][bi]
            if (boundary.builtin is not E.SourceBuiltin.COMPILE or boundary.site.result != candidate.compile_result
                    or request.caller != boundary.owner):
                raise ValueError('compiler candidate does not name its original compile boundary')
            caller = store.load(boundary.owner.unit)
            refs = compiled._References(caller)
            calls = [(n, c) for n, c in enumerate(caller.calls) if refs.site(c) == boundary.site]
            if len(calls) != 1: raise ValueError('compile boundary lacks one exact original call ABI')
            compile_call = slicer.fact(caller, 'calls', calls[0][0])
            self._caller_material(caller.unit, compile_call)
            ti = candidate.text_candidate_ordinal
            text = trows['candidates'][ti]
            if (text.source != source_locator or candidate.source != source_locator
                    or text.source_unit != candidate.source_unit or text.read_result != candidate.read_result
                    or text.text_utf8_sha256 != candidate.text_utf8_sha256 or text.source_path != f0['path']
                    or text.raw_bytes != len(self.raw_source) or text.raw_sha256 != sha256(self.raw_source).hexdigest()
                    or _digest(f0) != text.f0_document_sha256):
                raise ValueError('original text and captured raw source receipts differ')
            interpretation = text.interpretation
            if not interpretation.newline_resolved or interpretation.encoding is None or interpretation.errors is None:
                raise ValueError('recorded compiler text interpretation is unresolved')
            with TextIOWrapper(BytesIO(self.raw_source), encoding=interpretation.encoding,
                    errors=interpretation.errors, newline=interpretation.newline) as stream:
                payload = stream.read()
            if sha256(payload.encode('utf-8')).hexdigest() != candidate.text_utf8_sha256:
                raise ValueError('recorded compiler payload hash differs')
            code = compile(payload, context.filename, context.mode,
                flags=context.compiler_input_flags, dont_inherit=True, optimize=context.optimize)
            if (type(code) is not CodeType or source_compilation_contexts.code_digest(code) != candidate.code_digest
                    or code.co_flags != context.compiled_code_flags
                    or code.co_flags & supported_future_flag_mask() != context.compiled_future_flags):
                raise ValueError('replayed original compiler result differs')
            branches = tuple(CompiledExecAlternative(self._table_fact(graph.path, graph.report,
                'connections', n), c) for n, c in connections if c.compiled_candidate == candidate.id)
            if any(c.connection.code_use not in erows['compiled-code-uses']
                   or c.connection.code_use.producer != candidate.compile_result for c in branches):
                raise ValueError('exec alternatives lost their original code-use witness')
            compiled_root = decode(CapturedCode, describe_code(code))
            profiles.append(CompiledCodeProfile(unit, self.original_source_unit, self.root_scope, root_fact,
                self._table_fact(cp, cr, 'candidates', i), candidate,
                self._table_fact(eroot, er, 'compilation-contexts', ri), request,
                self._table_fact(eroot, er, 'boundaries', bi), boundary,
                compile_call, self._table_fact(troot, tr, 'candidates', ti),
                text, context_fact, self.syntax_locator, compiled_root, branches))
            if hasattr(self, 'code') and describe_code(self.code) != describe_code(code):
                raise ValueError('one compiled unit has conflicting shared root code')
            self.code, self.payload, self.context = code, payload, context
        if {p.candidate.id for p in profiles} != ids:
            raise ValueError('exec candidate coverage is incomplete')
        self.profiles = tuple(profiles)
        self.fact_material_routes = tuple(self._material_routes.values())
        self.compiled_root = self.profiles[0].compiled_root
        for module in (compiled, source_execution, source_text_values, source_compilation_contexts,
                       source_context_variants, source_f4_variants):
            self._remember(Path(module.__file__))
        self._remember(Path(__file__))
        self._remember(Path(R.__file__))
        self.check()

    def _remember(self, path):
        path = Path(path).absolute(); raw = path.read_bytes()
        if path in self._guard and self._guard[path] != raw:
            raise ValueError('compiler profile material changed during read')
        self._guard[path] = raw
        return raw

    def _artifact(self, path, schema):
        raw = self._remember(path)
        return ProviderArtifact(str(Path(path).absolute()), sha256(raw).hexdigest(), len(raw), schema)

    def _remember_table(self, root, receipt):
        raw = self._remember(Path(root)/receipt['path'])
        if len(raw) != receipt['bytes'] or sha256(raw).hexdigest() != receipt['sha256']:
            raise ValueError('original compiler material stored receipt differs')

    def _table_fact(self, root, report, name, ordinal):
        return ProviderFactReference(self._artifact(Path(root)/report['tables'][name]['path'],
            report['schema']+'-record'), '#/records/'+str(ordinal))

    def _source_locator(self, descriptor, manifest, ordinal, name, schema):
        return SourceArtifactLocator(self._artifact(self.syntax_root/descriptor['path'], schema),
            descriptor['decoded_sha256'], descriptor['decoded_bytes'], 'gzip-canonical-json',
            declaration=ProviderFactReference(self._artifact(manifest, 'scar.static-program'),
                '#/units/'+str(ordinal)+'/artifacts/'+name))

    def _caller_material(self, unit, reference):
        """Preserve collection evidence and guard its fixed primitive leaf.

        This follows the same unit_parent route as FactMaterialResolver, for
        this original compiler caller only; it does not enumerate unit facts.
        """
        if reference.artifact in self._material_routes: return
        store = self.catalog.fact_store; row = store.rows[unit]
        parent = store._source_parents[unit]
        catalogs = [self._artifact(self.catalog.path/'result.json', self.catalog.report['schema'])]
        receipt = self.catalog.report['context_facts']
        self._remember_table(self.catalog.path, receipt)
        catalogs.append(self._artifact(self.catalog.path/receipt['path'], store.report['schema']))
        while True:
            catalogs.append(self._artifact(parent.path/'result.json', parent.report['schema']))
            if not parent.parents: break
            parent = parent.parents[parent.unit_parent[unit]]
        if parent.rows[unit] != row:
            raise ValueError('compiler caller fact route selects a different original row')
        physical = self._artifact(parent.path/row['facts'], reference.artifact.schema)
        if (physical.sha256, physical.size_bytes) != (reference.artifact.sha256, reference.artifact.size_bytes):
            raise ValueError('compiler caller primitive leaf receipt differs')
        self._material_routes[reference.artifact] = FactMaterialRoute(unit, reference.artifact,
            physical, tuple(catalogs), row.get('facts_format', 'SOURCE_FACT_JSON'))

    def resolve_fact(self, reference):
        """Resolve an original compile-call fact without changing its locator."""
        if type(reference) is not ProviderFactReference:
            raise TypeError('expected an original compiler call fact')
        self.check()
        route = self._material_routes[reference.artifact]
        return ProviderFactReference(route.physical, reference.locator)

    def check(self):
        self.catalog.fact_store.validate_parents()
        if any(path.read_bytes() != raw for path, raw in self._guard.items()):
            raise ValueError('original compiler profile materials changed')

    def match_capture(self, capture):
        if type(capture) is not CodeCapture:
            raise TypeError('compiled root matching requires an original typed CodeCapture')
        self.check()
        return tuple(CompiledRootCodeMatch(i, capture) for i, profile in enumerate(self.profiles)
                     if capture.code == profile.compiled_root)
