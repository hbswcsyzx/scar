"""One real official flags worker, original parents, and unjoined C1 views."""
from copy import deepcopy
from dataclasses import replace
import __future__
from hashlib import sha256
import json
import sys

import pytest

from scar.analysis.source_context_variants import context_variant_document
from scar.analysis.source_symbol_context_adapter import DEFAULT
from scar.analysis.source_symbol_variants import SymbolVariantWorker, symbol_variant_document, read_symbol_variant
from scar.analysis.source_symbols import source_symbols_document, read_source_symbols, _digest
from scar.ir.program.source_bytes import SourceBytesProfile
from scar.ir.program.source_compiled_values import EffectiveCompileContext
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_text import TextOpenInterpretation
from scar.ir.program.source_symbol_variants import SymbolSourceParent, SymbolTextInput
from scar.ir.record_codec import decode
from tests.unit.test_source_contexts import _inputs


@pytest.mark.skipif(sys.implementation.name!='cpython' or sys.version_info[:3]!=(3,14,7),
                    reason='native context adapter is pinned to CPython 3.14.7')
def test_context_symbol_view_uses_explicit_flags_and_actual_worker_profile(tmp_path):
    if not (DEFAULT/'result.json').exists():
        pytest.skip('build the isolated official adapter explicitly before this fixture')
    text = 'def function(value: Missing):\n    return value\n'
    f0,f1,f2,roles = _inputs(text);original = deepcopy((f0,f1,f2,roles))
    parents = []
    for name,document in zip(('source_bytes','source_tokens','source_syntax','source_roles'),original):
        raw = json.dumps(document,sort_keys=True,separators=(',',':')).encode();path = tmp_path/(name+'.json')
        path.write_bytes(raw);digest = sha256(raw).hexdigest()
        locator = SourceArtifactLocator(ProviderArtifact(str(path),digest,len(raw),'fixture'),digest,len(raw),'canonical-json')
        parents.append(SymbolSourceParent(name,locator,_digest(document)))
    source_text = SymbolTextInput(parents[0].source,_digest(f0),sha256(text.encode()).hexdigest(),len(text.encode()),
        TextOpenInterpretation('utf-8','strict',None,True,True,
            conditions=('TEXT_OPEN_DEFAULT_ENCODING_SELECTS_UTF8',),
            obligations=('DEFAULT_ENCODING_CONTEXT_NOT_DECLARED_CONDITIONAL_UTF8_INTERPRETATION_ONLY',)),
        sha256(text.encode()).hexdigest(),len(text),('CAPTURED_FILE_VERSION_SELECTED',),('CONDITIONAL_ENCODING',))
    runtime = decode(SourceBytesProfile,f0['profile']);flag = __future__.annotations.compiler_flag
    plain = EffectiveCompileContext(f0['path'],'exec',0,True,0,0,0,0,0,runtime)
    future = replace(plain,caller_dont_inherit=False,inherited_future_flags=flag,
        compiler_input_flags=flag,compiled_future_flags=flag,compiled_code_flags=flag)
    contexts = [context_variant_document('fixture',f0,f1,f2,roles,c,text) for c in (plain,future)]
    with SymbolVariantWorker() as worker:
        values = []
        for context in contexts:
            document = symbol_variant_document(context,f0,f1,f2,roles,text,[source_text,source_text],worker,parents=parents)
            values.append(read_symbol_variant(document,context,f0,f1,f2,roles,text,worker,parents=parents))
        zero,annotation = values
        assert len(zero.material.scopes)==3 and len(annotation.material.scopes)==2
        assert zero.namespace!=annotation.namespace and zero.material.input==annotation.material.input
        assert annotation.request.effective_flags==flag and not annotation.request.dont_inherit
        assert len(annotation.text_inputs)==1 and annotation.text_inputs[0]==source_text
        assert annotation.context_material_sha256==_digest(contexts[1]['material'])
        assert annotation.material.ast_join=='UNJOINED' and not annotation.material.complete_lexical_scopes
        assert 'CONTEXT_QUALIFIED_F4_BODY_NOT_BUILT' in annotation.obligations
        assert annotation.discharged==('CONTEXT_QUALIFIED_NATIVE_SYMBOL_VIEW_NOT_CAPTURED',)
        assert annotation.material.profile.api.endswith('explicit_flags)')
        receipt = json.loads((DEFAULT/'result.json').read_bytes())
        assert annotation.material.profile.native_sha256==receipt['helper']['executable']['sha256']
        assert annotation.material.profile.hash_randomization==0
        assert annotation.material.profile.runtime.version_string!=runtime.version_string
        with pytest.raises(ValueError,match='profile mismatch'):
            read_source_symbols(document['material'],f0,f1,f2)
        bad = deepcopy(document);bad['request']['effective_flags'] = 0
        with pytest.raises(ValueError,match='differs'):
            read_symbol_variant(bad,contexts[1],f0,f1,f2,roles,text,worker,parents=parents)
    assert zero.material.scopes==decode(type(zero.material),source_symbols_document(f0,f1,f2)).scopes
    assert original==(f0,f1,f2,roles)
