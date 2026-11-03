"""One static-only check of lookup ports; the application is never executed."""
from dataclasses import replace

import pytest

from scar.analysis.program_lowering import prepare_source_text
from scar.analysis.source_language import SourceLanguageOptions
from scar.analysis.source_attribute_lookup import validate_source_attribute_lookups
from scar.analysis.source_class_body_lowering import lower_class_suite
from scar.analysis.static_compilation import compile_source_unit
from scar.analysis.static_lexical import inspect_lexical
from scar.analysis.static_rules import plan_static_entry
from scar.ir.program.attribute_lookups import AttributeLookupForm, SelectorResolution
from scar.ir.program.codec import dumps, loads
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.source_language import SourceLanguageCapability
from scar.ir.record_codec import decode
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID


def test_attribute_requests_keep_original_ports_without_resolving_dispatch(tmp_path):
    text = '''__scar_application_must_never_execute__()
def read(obj):
    value = obj.child
    obj.field = value
    return obj.method(value), obj.field
class Owner:
    first = source.field
    second = source.method(first)
    def private(self):
        return self.__private
'''
    path = tmp_path / 'application.py'
    prepared = prepare_source_text(path, text, project_root=tmp_path, root_is_package=False)
    catalog = inspect_lexical(prepared.tree, path=str(path), namespace_root=str(tmp_path),
        fingerprint=prepared.semantics.sources[str(path)].fingerprint, semantic=prepared.semantic, source_text=text)
    compilation = compile_source_unit(prepared)
    def lower(entry):
        source = decode(SourceReference, entry['source_ref'])
        definition = decode(OperationDefinitionID, entry['semantic_definition_ids'][0])
        plan = plan_static_entry(prepared.tree, entry, path=str(path), fingerprint=source.fingerprint)
        return prepared.lower(entry['name'], source=source, profile=BodyLoweringProfile.STRUCTURED_ENV,
            expand_candidates=False, language_options=SourceLanguageOptions(
                tuple(SourceLanguageCapability(c) for c in plan['capabilities']),
                compilation.for_definition(definition, source)))
    public_entry, = (r for r in catalog['entries'] if r['kind'] == 'FUNCTION' and r['name'] == 'read')
    public = lower(public_entry)
    private_entry, = (r for r in catalog['entries'] if r['kind'] == 'FUNCTION' and r['name'] == 'private')
    private = lower(private_entry)
    assert public.graph is not None, public.metadata.gaps
    assert private.graph is not None, private.metadata.gaps
    assert [r.selector.lookup_name for r in public.graph.attribute_lookups] == ['child', 'method', 'field']
    private_lookup, = private.graph.attribute_lookups
    assert private_lookup.selector.lookup_name == '_Owner__private'
    assert private_lookup.selector.resolution is SelectorResolution.LEXICAL_MANGLED

    entry, = (r for r in catalog['entries'] if r['kind'] == 'CLASS')
    definition = decode(OperationDefinitionID, entry['semantic_definition_ids'][0])
    source = decode(SourceReference, entry['source_ref'])
    suite = lower_class_suite(prepared, definition, source,
        code_evidence=compilation.for_definition(definition, source),
        profile='STATIC_CLASS_SUITE_METHOD_314_V1')
    assert suite.graph is not None
    forms = {r.form for r in suite.graph.attribute_lookups}
    assert forms == {AttributeLookupForm.CPYTHON_LOAD_ATTR, AttributeLookupForm.CPYTHON_LOAD_METHOD}

    for body in (public, private, suite):
        graph = body.graph
        assert loads(dumps(graph)) == graph
        index = ProgramIndex(graph)
        for lookup in graph.attribute_lookups:
            query = index.attribute_lookup(lookup.operation)
            assert query['status'] == 'RECORDED' and query['interface'] == lookup
            assert not query['effects_complete'] and not query['dispatch_resolved']
            assert not query['direct_storage_access_proved']
        legacy = replace(graph, attribute_lookups=None)
        assert loads(dumps(legacy)).attribute_lookups is None
        assert ProgramIndex(legacy).attribute_lookup(graph.attribute_lookups[0].operation)['status'] == 'NOT_RECORDED'

    # A structurally well-typed selector still needs independent source proof.
    first, *rest = public.graph.attribute_lookups
    forged = replace(first, selector=replace(first.selector, source_spelling='invented', lookup_name='invented'))
    with pytest.raises(ValueError, match='recorded lookup table differs'):
        validate_source_attribute_lookups(replace(public.graph, attribute_lookups=(forged, *rest)),
            public.metadata, source_text=text, semantic=prepared.semantic)
