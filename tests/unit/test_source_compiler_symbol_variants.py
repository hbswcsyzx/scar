"""Inherited future context preserves scalar symbol and parameter provenance."""
from copy import deepcopy
import __future__
from hashlib import sha256
import json
import sys

import pytest

from scar.analysis.source_context_variants import context_variant_document
from scar.analysis.source_binding_variants import binding_variant_document
from scar.analysis.source_symbol_context_adapter import DEFAULT
from scar.analysis.source_symbol_variants import SymbolVariantWorker, symbol_variant_document
from scar.analysis.source_topology_variants import topology_variant_document
from scar.analysis.source_compiler_symbol_variants import compiler_symbol_variant_document, read_compiler_symbol_variant
from scar.analysis.compiler_symbols import read_compiler_symbols, _digest
from scar.ir.program.source_bytes import SourceBytesProfile
from scar.ir.program.source_compiled_values import EffectiveCompileContext
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.source_symbol_variants import SymbolSourceParent, SymbolTextInput
from scar.ir.program.source_text import TextOpenInterpretation
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import decode, encode
from tests.unit.test_source_contexts import _inputs


@pytest.mark.skipif(sys.implementation.name != 'cpython' or sys.version_info[:3] != (3,14,7),
                    reason='official context symbol adapter is pinned to CPython 3.14.7')
def test_context_symbols_preserve_cells_globals_parameters_and_reject_other_namespace(tmp_path):
    if not (DEFAULT/'result.json').exists():
        pytest.skip('build the isolated official adapter explicitly before this fixture')
    text = ('def outer(seed):\n    local = seed\n'
        '    def inner(value: Missing, /, *, option=1):\n'
        '        return local, value, option, outside\n    return inner\n')
    f0,f1,f2,b = _inputs(text);original = deepcopy((f0,f1,f2,b));parents = []
    for name,document in zip(('source_bytes','source_tokens','source_syntax','source_roles'),original):
        raw = json.dumps(document,sort_keys=True,separators=(',',':')).encode()
        path = tmp_path/(name+'.json');path.write_bytes(raw);digest = sha256(raw).hexdigest()
        locator = SourceArtifactLocator(ProviderArtifact(str(path),digest,len(raw),'fixture'),
            digest,len(raw),'canonical-json')
        parents.append(SymbolSourceParent(name,locator,_digest(document)))
    text_sha = sha256(text.encode()).hexdigest()
    retained = SymbolTextInput(parents[0].source,_digest(f0),text_sha,len(text.encode()),
        TextOpenInterpretation('utf-8','strict',None,True,False),text_sha,len(text),('SOURCE_VERSION_SELECTED',),())
    flag = __future__.annotations.compiler_flag
    context = EffectiveCompileContext(f0['path'],'exec',0,False,flag,flag,flag,flag,0,
        decode(SourceBytesProfile,f0['profile']))
    c1 = context_variant_document('fixture',f0,f1,f2,b,context,text)
    c2 = binding_variant_document(f0,f1,f2,b,c1,text)
    with SymbolVariantWorker() as worker:
        native = symbol_variant_document(c1,f0,f1,f2,b,text,[retained],worker,parents=parents)
        topology = topology_variant_document(c1,native,f0,f1,f2,b,text,worker,parents=parents)
        document = compiler_symbol_variant_document(c1,c2,native,topology,f0,f1,f2,b,text,worker,parents=parents)
        value = read_compiler_symbol_variant(document,c1,c2,native,topology,
            f0,f1,f2,b,text,worker,parents=parents)
        m = value.material
        assert m.status == 'PROJECTED' and m.runtime_binding == 'NOT_OBSERVED'
        assert value.namespace == c1['namespace'] == c2['namespace'] == native['namespace'] == topology['namespace']
        assert value.binding_material_sha256 == _digest(c2['bindings'])
        assert len(m.symbols) == sum(len(row['symbols']) for row in native['material']['scopes'])
        names = c2['declarations']['names'];scopes = {}
        for projection in m.symbols:
            slot = m.slots[projection.slot];name = slot.name
            text_name = names[name.source]['value'] if name.kind == 'SOURCE' else name.intrinsic
            scopes.setdefault(text_name,set()).add(m.facts[projection.fact].scope_code)
        assert {4,5} <= scopes['local'] and 3 in scopes['outside']
        projected_parameters = [native['material']['scopes'][p.native_scope]['varnames'][p.ordinal] for p in m.parameters]
        assert projected_parameters == ['seed','value','option']
        assert 'CONTEXT_QUALIFIED_SYMBOL_ORIGIN_AND_PARAMETER_PROJECTION_NOT_BUILT' in value.discharges
        assert value.obligations == ('CONTEXT_QUALIFIED_F4_BODY_NOT_BUILT',)
        with pytest.raises(ValueError,match='profile mismatch'):
            read_compiler_symbols(encode(m),f0,f1,f2,b,c1['material'],c2['declarations'],
                native['material'],topology['material'])
        bad = deepcopy(c2);bad['namespace'] = '0'*64
        with pytest.raises(ValueError,match='binding variant differs'):
            read_compiler_symbol_variant(document,c1,bad,native,topology,
                f0,f1,f2,b,text,worker,parents=parents)
    assert original == (f0,f1,f2,b)
