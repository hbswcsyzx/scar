"""C3-S source-derived compiler symbol facts and original public projections."""
from __future__ import annotations
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis.compiler_topology import read_compiler_topology, _catalog as _topology_catalog
from scar.analysis.source_declarations import read_source_declarations, _catalog as _declaration_catalog
from scar.ir.program.compiler_symbols import (
    INTRINSIC_NAMES, SymbolLimits, SourceDisposition, CompilerSymbolCatalog,
    CompilerSymbolsInput, CompilerSymbolsProfile, CompilerSymbolsMaterial,
    SymbolProjection, ParameterProjection, SymbolStop, SymbolFrontier,
)
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.program.source_roles import SourceRolesMaterial
from scar.ir.program.source_contexts import SourceContextsMaterial
from scar.ir.program.source_symbols import SourceSymbolsMaterial
from scar.ir.record_codec import decode, encode


_VERSION = 'CPYTHON_3_14_7_COMPILER_SYMBOLS_C3S_V1'
_SOURCE_DISPOSITIONS = ('EMITTED', 'DETACHED_RAW', 'IGNORED_LOCAL_ANNOTATION', 'GRAMMAR_ONLY')
_SLOT_DISPOSITIONS = ('PUBLIC', 'INLINED', 'DETACHED', 'DELETED')
_KW_LIMITS = ('max_symbol_slots', 'max_compiler_contributions', 'max_symbol_facts',
    'max_symbol_transforms', 'max_symbol_steps')


def _digest(document):
    return sha256(json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()


@lru_cache(maxsize=1)
def _catalog():
    from scar.analysis.compiler_symbol_collect import RAW_RULES
    from scar.analysis.compiler_symbol_solve import FACT_RULES, TRANSFORM_RULES, PROTOCOL_RULES
    topology, declarations = _topology_catalog(), _declaration_catalog()
    payload = dict(rule_version=_VERSION, topology_catalog_sha256=topology.content_sha256,
        declaration_catalog_sha256=declarations.content_sha256, intrinsic_names=list(INTRINSIC_NAMES),
        raw_rules=list(RAW_RULES), fact_rules=list(FACT_RULES), transform_rules=list(TRANSFORM_RULES),
        protocol_rules=list(PROTOCOL_RULES), source_dispositions=list(_SOURCE_DISPOSITIONS),
        slot_dispositions=list(_SLOT_DISPOSITIONS), schema='scar.compiler-symbol-catalog', schema_version=1)
    return CompilerSymbolCatalog(_VERSION, topology.content_sha256, declarations.content_sha256,
        INTRINSIC_NAMES, RAW_RULES, FACT_RULES, TRANSFORM_RULES, PROTOCOL_RULES,
        _SOURCE_DISPOSITIONS, _SLOT_DISPOSITIONS, _digest(payload))


def compiler_symbol_catalog() -> dict:
    return encode(_catalog())


def _profile(native):
    from scar.analysis import compiler_symbol_collect, compiler_symbol_solve, compiler_symbol_view
    from scar.ir.program import compiler_symbols as symbol_ir
    catalog = _catalog()
    implementation = _digest({name: sha256(Path(path).read_bytes()).hexdigest() for name, path in (
        ('analysis', __file__), ('collect', compiler_symbol_collect.__file__),
        ('solve', compiler_symbol_solve.__file__), ('view', compiler_symbol_view.__file__),
        ('ir', symbol_ir.__file__))})
    return CompilerSymbolsProfile(_VERSION, catalog.content_sha256, catalog.topology_catalog_sha256,
        catalog.declaration_catalog_sha256, _digest(encode(native.profile)), implementation)


def _name(reference, declarations):
    return declarations.names[reference.source].value if reference.kind == 'SOURCE' else reference.intrinsic


def _project(solution, topology, declarations, native):
    """Compare computed words/parameters; never supply native answers to solve."""
    symbols, parameters = [], []
    public = {block.public_scope: i for i, block in enumerate(topology.blocks) if block.projection == 'PUBLIC'}
    if set(public) != set(range(len(native.scopes))):
        raise SymbolStop('NATIVE_SCOPE_COVERAGE', 'accepted topology does not cover the original public rows')
    for native_scope, expected in enumerate(native.scopes):
        block = public[native_scope]
        row = solution.blocks[block]
        by_name = {}
        for slot in row.slots:
            name = _name(solution.slots[slot].name, declarations)
            if name in by_name:
                raise SymbolStop('DUPLICATE_FINAL_SYMBOL', 'computed final compiler name is not unique', block=block)
            by_name[name] = slot
        if set(by_name) != {symbol.name for symbol in expected.symbols}:
            missing = sorted({symbol.name for symbol in expected.symbols} - set(by_name))[:8]
            extra = sorted(set(by_name) - {symbol.name for symbol in expected.symbols})[:8]
            raise SymbolStop('NATIVE_SYMBOL_KEYS', 'computed/public symbol keys differ; missing=' + repr(missing)
                + '; extra=' + repr(extra), block=block)
        for ordinal, symbol in enumerate(expected.symbols):
            slot = by_name[symbol.name]
            fact_id = solution.slots[slot].final_fact
            fact = solution.facts[fact_id]
            if fact.scope_code is None or fact.low_flags | (fact.scope_code << 12) != symbol.flags:
                raise SymbolStop('NATIVE_SYMBOL_WORD', 'computed compiler word differs for ' + repr(symbol.name)
                    + ': ' + repr((fact.low_flags, fact.scope_code, symbol.flags)), block=block)
            symbols.append(SymbolProjection(native_scope, ordinal, slot, fact_id))
        actual_names = tuple(_name(solution.slots[slot].name, declarations) for slot in row.parameters)
        if actual_names != expected.varnames:
            raise SymbolStop('NATIVE_PARAMETER_ORDER', 'computed parameter order differs from original varnames', block=block)
        for ordinal, slot in enumerate(row.parameters):
            parameters.append(ParameterProjection(native_scope, ordinal, slot))
    return tuple(symbols), tuple(parameters)


def _derive(f0, f1, f2, f3b, c1, c2a, f3a, topology_document, limits):
    from scar.analysis.compiler_symbol_collect import collect_symbols
    from scar.analysis.compiler_symbol_solve import solve_symbols
    # Both public parent readers remain strict. A future owner-bound validated
    # bundle can remove repeated work without accepting an external boolean.
    topology = read_compiler_topology(topology_document, f0, f1, f2, f3b, c1, f3a)
    declarations = read_source_declarations(c2a, f0, f1, f2, f3b, c1)
    syntax, roles, contexts, native = (decode(SourceSyntaxMaterial, f2), decode(SourceRolesMaterial, f3b),
        decode(SourceContextsMaterial, c1), decode(SourceSymbolsMaterial, f3a))
    docs = (f0, f1, f2, f3b, c1, c2a, f3a, topology_document)
    inputs = CompilerSymbolsInput(*(_digest(doc) for doc in docs), f0['path'], syntax.mode,
        declarations.status, topology.status, len(declarations.contributions), len(topology.blocks),
        sum(len(row.symbols) for row in native.scopes), sum(len(row.varnames) for row in native.scopes))
    base = dict(input=inputs, profile=_profile(native), limits=limits)
    empty = dict(slots=(), contributions=(), sources=(), facts=(), transforms=(), protocols=(),
        blocks=(), symbols=(), parameters=(), frontiers=(), steps=0)
    if declarations.status != 'DECLARED' or topology.status not in ('PROJECTED', 'SOURCE_ONLY_MODE'):
        empty['frontiers'] = (SymbolFrontier('UPSTREAM_NOT_READY', None, None,
            'source declarations or compiler topology have no complete accepted projection'),)
        return CompilerSymbolsMaterial(**base, status='UPSTREAM_NOT_READY', **empty)
    if topology.status == 'SOURCE_ONLY_MODE':
        empty['sources'] = tuple(SourceDisposition(i, 'GRAMMAR_ONLY', ()) for i in range(len(declarations.contributions)))
        return CompilerSymbolsMaterial(**base, status='SOURCE_ONLY_MODE', **empty)
    try:
        raw = collect_symbols(syntax, roles, contexts, declarations, native, topology, limits=limits)
        solution = solve_symbols(raw, topology, declarations.names, limits=limits)
        symbols, parameters = _project(solution, topology, declarations, native)
    except SymbolStop as error:
        empty['frontiers'] = (error.frontier,)
        return CompilerSymbolsMaterial(**base,
            status='BUDGET_STOPPED' if error.budget else 'PROJECTION_CONTRADICTION', **empty)
    material = CompilerSymbolsMaterial(**base, status='PROJECTED', slots=solution.slots,
        contributions=raw.contributions, sources=raw.sources, facts=solution.facts,
        transforms=solution.transforms, protocols=solution.protocols, blocks=solution.blocks,
        symbols=symbols, parameters=parameters, frontiers=(), steps=solution.steps)
    from scar.analysis.compiler_symbol_view import CompilerSymbolView
    CompilerSymbolView(declarations, topology, native, material).verify()
    return material


def compiler_symbols_document(f0, f1, f2, f3b, c1, c2a, f3a, topology, *,
        max_symbol_slots=2_000_000, max_compiler_contributions=4_000_000,
        max_symbol_facts=4_000_000, max_symbol_transforms=2_000_000,
        max_symbol_steps=20_000_000) -> dict:
    limits = SymbolLimits(max_symbol_slots, max_compiler_contributions, max_symbol_facts,
        max_symbol_transforms, max_symbol_steps)
    return encode(_derive(f0, f1, f2, f3b, c1, c2a, f3a, topology, limits))


def read_compiler_symbols(document, f0, f1, f2, f3b, c1, c2a, f3a, topology):
    material = decode(CompilerSymbolsMaterial, document)
    native = decode(SourceSymbolsMaterial, f3a)
    if material.profile != _profile(native):
        raise ValueError('C3-S compiler symbol implementation/catalog profile mismatch')
    fresh = _derive(f0, f1, f2, f3b, c1, c2a, f3a, topology, material.limits)
    if material != fresh:
        raise ValueError('C3-S compiler symbol provenance differs from its original source/compiler inputs')
    return material


__all__ = ['compiler_symbol_catalog', 'compiler_symbols_document', 'read_compiler_symbols']
