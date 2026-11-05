"""C1 reuses original syntax while separating effective compiler contexts."""
from copy import deepcopy
from dataclasses import replace
import __future__

import pytest

from scar.analysis.source_contexts import source_contexts_document, read_source_contexts
from scar.analysis.source_context_variants import context_variant_document, read_context_variant
from scar.ir.program.source_compiled_values import EffectiveCompileContext
from scar.ir.program.source_bytes import SourceBytesProfile
from scar.ir.record_codec import decode
from tests.unit.test_source_contexts import _inputs


def test_effective_future_context_controls_regions_and_template_identity():
    text = 'field: ModuleType\ndef fn(value: ArgumentType) -> ReturnType:\n    return value\n'
    f0,f1,f2,b = _inputs(text)
    saved = deepcopy((f0,f1,f2,b))
    runtime = decode(SourceBytesProfile,f0['profile'])
    annotation = __future__.annotations.compiler_flag
    base = EffectiveCompileContext(f0['path'],'exec',0,True,0,0,0,0,0,runtime)
    inherited = replace(base,caller_dont_inherit=False,inherited_future_flags=annotation,
        compiler_input_flags=annotation,compiled_future_flags=annotation,compiled_code_flags=annotation)
    plain = context_variant_document('controlled-source',f0,f1,f2,b,base,text)
    future = context_variant_document('controlled-source',f0,f1,f2,b,inherited,text)
    p = read_context_variant(plain,f0,f1,f2,b,text)
    f = read_context_variant(future,f0,f1,f2,b,text)
    assert p.namespace!=f.namespace
    assert p.ast_correspondence_sha256==f.ast_correspondence_sha256
    assert any(r.suppression_reason=='FUTURE_ANNOTATION_STRINGIZED' for r in f.material.regions)
    assert not any(r.suppression_reason=='FUTURE_ANNOTATION_STRINGIZED' for r in p.material.regions)
    assert f.material.input==p.material.input
    assert f.material.profile!=p.material.profile
    assert saved==(f0,f1,f2,b)
    assert plain==context_variant_document('controlled-source',f0,f1,f2,b,base,text)
    original = source_contexts_document(f0,f1,f2,b)
    assert plain['material']['profile']!=original['profile']
    with pytest.raises(ValueError,match='profile mismatch'):
        read_source_contexts(future['material'],f0,f1,f2,b)
    with pytest.raises(ValueError,match='new F2'):
        context_variant_document('controlled-source',f0,f1,f2,b,inherited,text+'another = 3\n')
    with pytest.raises(ValueError,match='future flags are inconsistent'):
        context_variant_document('controlled-source',f0,f1,f2,b,
            replace(base,compiled_future_flags=annotation),text)
    with pytest.raises(ValueError,match='requested and inherited'):
        context_variant_document('controlled-source',f0,f1,f2,b,
            replace(inherited,compiler_input_flags=0),text)
