"""Two focused C3-S first-pass families; no target execution or bytecode."""
from dataclasses import replace
import json
import sys

import pytest

from scar.analysis.source_bytes import source_bytes_document
from scar.analysis.source_tokens import source_tokens_document
from scar.analysis.source_syntax import source_syntax_document
from scar.analysis.source_roles import source_roles_document
from scar.analysis.source_contexts import source_contexts_document
from scar.analysis.source_declarations import source_declarations_document
from scar.analysis.source_symbols import source_symbols_document
from scar.analysis.compiler_topology import compiler_topology_document
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.program.source_roles import SourceRolesMaterial
from scar.ir.program.source_contexts import SourceContextsMaterial
from scar.ir.program.source_declarations import SourceDeclarationsMaterial
from scar.ir.program.source_symbols import SourceSymbolsMaterial
from scar.ir.program.compiler_topology import CompilerTopologyMaterial
from scar.ir.program.compiler_symbols import SymbolLimits, SymbolStop, RawCollection
from scar.ir.record_codec import decode, encode

pytestmark = pytest.mark.skipif(
    sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 14, 7),
    reason='first-pass compiler rules are pinned to CPython 3.14.7')


def _inputs(text, mode='exec'):
    f0 = source_bytes_document(text.encode(), path='/source/symbol-collect.py', namespace_root='/source')
    f1 = source_tokens_document(f0)
    f2 = source_syntax_document(f0, f1, mode=mode)
    b = source_roles_document(f0, f1, f2)
    c = source_contexts_document(f0, f1, f2, b)
    d = source_declarations_document(f0, f1, f2, b, c)
    a = source_symbols_document(f0, f1, f2)
    t = compiler_topology_document(f0, f1, f2, b, c, a)
    return tuple(decode(cls, doc) for cls, doc in (
        (SourceSyntaxMaterial, f2), (SourceRolesMaterial, b), (SourceContextsMaterial, c),
        (SourceDeclarationsMaterial, d), (SourceSymbolsMaterial, a), (CompilerTopologyMaterial, t)))


def _text(name, declarations):
    return declarations.names[name.source].value if name.kind == 'SOURCE' else name.intrinsic


@pytest.mark.parametrize('family', ('source_events', 'bounds_and_detached'))
def test_compiler_symbol_collect(family):
    from scar.analysis.compiler_symbol_collect import collect_symbols, RAW_RULES

    def collect(inputs, limits=SymbolLimits()):
        raw = collect_symbols(*inputs, limits=limits)
        assert decode(RawCollection, json.loads(json.dumps(encode(raw)))) == raw
        syntax, roles, contexts, declarations, native, topology = inputs
        assert tuple(x.source for x in raw.sources) == tuple(range(len(declarations.contributions)))
        assert tuple(x.block for x in raw.parameters) == tuple(range(len(topology.blocks)))
        assert set(x.rule for x in raw.contributions) <= set(RAW_RULES)
        for i, event in enumerate(raw.contributions):
            assert i in raw.slots[event.slot].contributions
            if event.source is not None:
                assert event.anchor == declarations.contributions[event.source].site
                assert i in raw.sources[event.source].contributions
            if event.rule == 'GLOBAL_ECHO':
                assert event.derived_from is not None and event.derived_from < i
                cause = raw.contributions[event.derived_from]
                assert cause.flags & 1
        for slot in raw.slots:
            flags = 0
            for index in slot.contributions:
                flags |= raw.contributions[index].flags
            assert flags == slot.flags
        return raw

    if family == 'source_events':
        inputs = _inputs('''import package.child
from package import item as imported
module: ROOT_TYPE
def fn[T](a,/,b=0,*args,k=1,**kwargs):
    local: UNUSED
    nested: (lambda: hidden)
    global remote
    counter += delta
    del gone
    try: pass
    except Error as caught: pass
    match value:
        case {'x': bound, **rest}: pass
    values = [(captured := rhs) for item in data]
    reads = [item for sink[index] in data]
    return super
class C[T]:
    if check:
        field: TYPE
    def method(self): return super
''')
        raw = collect(inputs)
        declarations, topology = inputs[3], inputs[5]

        def slots(role, text):
            return [(i, s) for i, s in enumerate(raw.slots)
                    if topology.blocks[s.block].origin.role == role and _text(s.name, declarations) == text]

        function = next(i for i, block in enumerate(topology.blocks)
                        if block.origin.role == 'FUNCTION_BODY' and
                        [_text(raw.slots[s].name, declarations) for s in raw.parameters[i].slots] == ['a', 'b', 'k', 'args', 'kwargs'])
        tp = topology.blocks[function].parent
        assert [_text(raw.slots[s].name, declarations) for s in raw.parameters[tp].slots] == ['.defaults', '.kwdefaults']
        for name, flags in (('counter', 2), ('gone', 2), ('caught', 2), ('bound', 2), ('rest', 2), ('captured', 2)):
            assert next(s.flags for s in raw.slots if s.block == function and _text(s.name, declarations) == name) == flags
        counter = slots('FUNCTION_BODY', 'counter')[0][1]
        assert {raw.contributions[e].rule for e in counter.contributions} == {'NAME_STORE'}
        assert len([e for e in raw.contributions if e.rule == 'EXCEPT_BINDER']) == 1
        assert not [s for s in raw.slots if _text(s.name, declarations) == 'UNUSED']
        assert slots('LAMBDA_BODY', 'hidden')[0][1].flags == 16
        for name in ('sink', 'index'):
            assert slots('COMPREHENSION', name)[0][1].flags == 16 | 512
        captured = slots('COMPREHENSION', 'captured')[0][1]
        assert captured.flags == 2 | 8
        assert {raw.contributions[e].rule for e in captured.contributions} == {'WALRUS_ORIGIN_DIRECTIVE', 'NAME_STORE'}
        home = next(s for s in raw.slots if s.block == function and _text(s.name, declarations) == 'captured')
        assert raw.contributions[home.contributions[0]].rule == 'WALRUS_HOME_BINDING'
        root = next(s for s in raw.slots if s.block == 0 and _text(s.name, declarations) == 'remote')
        assert root.flags == 1 and all(raw.contributions[e].rule == 'GLOBAL_ECHO' for e in root.contributions)
        assert slots('ROOT', 'package')[0][1].flags == 128
        assert slots('ROOT', 'imported')[0][1].flags == 128
        assert any(topology.blocks[i].origin.role == 'ROOT' for i in raw.conditional_blocks)
        assert any(topology.blocks[i].origin.role == 'CLASS_BODY' for i in raw.conditional_blocks)
        synthetic_headers = [i for i, block in enumerate(topology.blocks)
                             if block.origin.role == 'HEADER_ANNOTATIONS' and block.source_scope is None]
        assert synthetic_headers and all([_text(raw.slots[s].name, declarations) for s in raw.parameters[i].slots] == ['.format']
                                         for i in synthetic_headers)
        assert any(e.rule == 'SUPER_CLASS_USE' and e.source is None for e in raw.contributions)
        assert any(e.rule == 'CLASSDICT_USE' and e.source is None for e in raw.contributions)

        # Deliberately poison all native flag/parameter outputs. The first pass
        # uses only independently verified topology metadata and must not read
        # these fields to manufacture its answer.
        poisoned = replace(inputs[4], scopes=tuple(replace(scope,
            symbols=tuple(replace(symbol, flags=0) for symbol in scope.symbols),
            varnames=('NATIVE_PARAMETERS_MUST_NOT_BE_READ',)) for scope in inputs[4].scopes))
        assert collect((*inputs[:4], poisoned, inputs[5])) == raw
    else:
        inputs = _inputs('''from __future__ import annotations
class C:
    obj.attr: (lambda: hidden)
    field: TYPE
def f():
    local: UNUSED
''')
        raw = collect(inputs)
        declarations, topology = inputs[3], inputs[5]
        hidden = next(s for s in raw.slots if _text(s.name, declarations) == 'hidden')
        assert hidden.flags == 16 and topology.blocks[hidden.block].projection == 'DETACHED_DESCENDANT'
        type_slot = next(s for s in raw.slots if _text(s.name, declarations) == 'TYPE')
        assert type_slot.flags == 16 and topology.blocks[type_slot.block].projection == 'FUTURE_DETACHED'
        unused = next(i for i, row in enumerate(declarations.contributions)
                      if declarations.names[row.name].value == 'UNUSED')
        assert raw.sources[unused].disposition == 'IGNORED_LOCAL_ANNOTATION'
        assert any(s.disposition == 'DETACHED_RAW' for s in raw.sources)
        assert not any(_text(s.name, declarations) == '__classdict__' for s in raw.slots)
        for limits in (SymbolLimits(max_symbol_slots=0), SymbolLimits(max_contributions=0), SymbolLimits(max_steps=0)):
            with pytest.raises(SymbolStop) as error:
                collect_symbols(*inputs, limits=limits)
            assert error.value.budget
        with pytest.raises(ValueError):
            SymbolLimits(max_steps=True)
        grammar = _inputs('(T) -> R', mode='func_type')
        only = collect(grammar)
        assert not (only.slots or only.contributions or only.parameters)
        assert all(s.disposition == 'GRAMMAR_ONLY' for s in only.sources)
