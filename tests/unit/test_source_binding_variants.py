"""Namespace templates consume the same effective context as their C1."""
from dataclasses import replace
import __future__

from scar.analysis.source_context_variants import context_variant_document
from scar.analysis.source_binding_variants import binding_variant_document, read_binding_variant
from scar.ir.program.source_compiled_values import EffectiveCompileContext
from scar.ir.program.source_bytes import SourceBytesProfile
from scar.ir.record_codec import decode
from tests.unit.test_source_contexts import _inputs


def test_future_annotation_ports_are_detached_with_c1_parent_identity():
    text = 'field: ModuleType\ndef fn(value: ArgumentType) -> ReturnType:\n    return value\n'
    f0,f1,f2,b = _inputs(text)
    runtime = decode(SourceBytesProfile,f0['profile']);flag = __future__.annotations.compiler_flag
    plain = EffectiveCompileContext(f0['path'],'exec',0,True,0,0,0,0,0,runtime)
    future = replace(plain,caller_dont_inherit=False,inherited_future_flags=flag,
        compiler_input_flags=flag,compiled_future_flags=flag,compiled_code_flags=flag)
    variants = []
    for context in (plain,future):
        c1 = context_variant_document('controlled-source',f0,f1,f2,b,context,text)
        c2 = binding_variant_document(f0,f1,f2,b,c1,text)
        variants.append(read_binding_variant(c2,f0,f1,f2,b,c1,text))
    p,f = variants
    assert p.namespace!=f.namespace and p.context_material_sha256!=f.context_material_sha256
    assert f.bindings.input.c1_document_sha256==f.declarations.input.c1_document_sha256
    assert not p.declarations.conflicts and not f.declarations.conflicts
    assert not p.bindings.conflicts and not f.bindings.conflicts
    assert any(x.analysis_visibility=='DETACHED_FUTURE_ANNOTATION' for x in f.bindings.ports)
    assert not any(x.analysis_visibility=='DETACHED_FUTURE_ANNOTATION' for x in p.bindings.ports)
    assert 'CONTEXT_QUALIFIED_DECLARATIONS_AND_BINDINGS_NOT_BUILT' in f.discharges
