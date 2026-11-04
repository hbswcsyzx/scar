"""Handwritten source-fact oracles for the isolated compiler analysis pass."""
from dataclasses import replace
import sys

import pytest

from scar.analysis.compiler_symbol_solve import solve_symbols
from scar.ir.program.compiler_symbols import (
    CompilerName, INTRINSIC_NAMES, RawCollection, RawContribution, RawParameters,
    RawSlot, SymbolLimits, SymbolStop,
)
from scar.ir.program.compiler_topology import (
    BlockOrigin, CompilerBlock, CompilerTopologyInput, CompilerTopologyMaterial,
    CompilerTopologyProfile,
)
from scar.ir.program.source_declarations import NameKey

pytestmark = pytest.mark.skipif(sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 14, 7),
                               reason='pinned compiler analysis profile')


def _topology(spec):
    blocks = []
    public = 0
    for i, (role, parent, children, projection, visible) in enumerate(spec):
        attachment = 'FUTURE_DETACHED' if projection == 'FUTURE_DETACHED' else 'DIRECT'
        ordinal = public if projection == 'PUBLIC' else None
        public += projection == 'PUBLIC'
        blocks.append(CompilerBlock(BlockOrigin(i, role), parent, children, None, visible,
                                    attachment, projection, ordinal))
    digest = '0' * 64
    inputs = CompilerTopologyInput(*([digest] * 6), '/source/hand.py', 'exec',
                                   'CONTEXTUALIZED', 'CAPTURED', 0, public)
    profile = CompilerTopologyProfile('HANDWRITTEN_TEST', digest, digest, digest, digest, digest)
    return CompilerTopologyMaterial(inputs, profile, len(blocks), 0, 0, 'PROJECTED',
                                    tuple(blocks), (), (), (), 0)


def _raw(topology, rows, *, conditional=()):
    values = tuple(dict.fromkeys(name for _, name, _ in rows if name not in INTRINSIC_NAMES))
    names = tuple(NameKey(text) for text in values)
    slots, contributions = [], []
    for index, (block, name, flags) in enumerate(rows):
        ref = CompilerName('SOURCE', source=values.index(name)) if name in values else CompilerName('INTRINSIC', intrinsic=name)
        contributions.append(RawContribution(block, index, flags, 'HANDWRITTEN_SOURCE', None, None, None))
        slots.append(RawSlot(block, ref, flags, (index,)))
    parameters = tuple(RawParameters(block, tuple(i for i, slot in enumerate(slots)
                        if slot.block == block and slot.flags & 4)) for block in range(len(topology.blocks)))
    return RawCollection(tuple(slots), tuple(contributions), (), parameters, conditional, 7), names


def _text(slot, names):
    return names[slot.name.source].value if slot.name.kind == 'SOURCE' else slot.name.intrinsic


def _block_words(solution, block, names):
    return {_text(solution.slots[slot], names): (solution.facts[solution.slots[slot].final_fact].low_flags |
            ((solution.facts[solution.slots[slot].final_fact].scope_code or 0) << 12))
            for slot in solution.blocks[block].slots}


def _dag(solution, raw):
    for index, fact in enumerate(solution.facts):
        assert all(0 <= parent < index for parent in fact.inputs)
        assert fact.slot < len(solution.slots) and not fact.low_flags & ~4095
    for index, slot in enumerate(raw.slots):
        initial = solution.slots[index].initial_fact
        assert solution.facts[initial].rule == 'COLLECT'
        assert solution.facts[initial].low_flags == slot.flags
    for slot in solution.slots[len(raw.slots):]:
        assert slot.initial_fact is None and not slot.contributions
    assert solution.steps > raw.steps


def _cell_fixture(existing=False):
    topology = _topology((
        ('ROOT', None, (1,), 'PUBLIC', False),
        ('FUNCTION_BODY', 0, (2,), 'PUBLIC', False),
        ('COMPREHENSION', 1, (3,), 'INLINED', False),
        ('LAMBDA_BODY', 2, (), 'PUBLIC', False),
    ))
    rows = [(0, 'outer', 2), (1, 'DATA', 16), (2, '.0', 4),
            (2, 'item', 2 | 512), (3, 'item', 16)]
    if existing:
        rows.insert(1, (1, 'item', 2))
    return topology, *_raw(topology, rows)


@pytest.mark.parametrize('family', ('inline_and_live_class', 'relay_protocol_detached_and_budgets'))
def test_pure_compiler_symbol_analysis(family):
    if family == 'inline_and_live_class':
        # The class annotation sees the live class table at its child visit,
        # not a frozen first-pass map or the final public child list.
        spec = [
            ('ROOT', None, (1,), 'PUBLIC', False),
            ('FUNCTION_BODY', 0, (2,), 'PUBLIC', False),
            ('CLASS_BODY', 1, (3, 4), 'PUBLIC', False),
            ('COMPREHENSION', 2, (), 'INLINED', False),
            ('VARIABLE_ANNOTATIONS', 2, (), 'PUBLIC', True),
        ]
        rows = [(0, 'outer', 2), (1, 'item', 2), (1, 'C', 18),
                (2, 'items', 2), (2, 'DATA', 16), (2, 'value', 258),
                (3, '.0', 4), (3, 'item', 2 | 16 | 512),
                (4, '.format', 4 | 16), (4, '__classdict__', 16), (4, 'item', 16)]
        for children, annotation_word, outer_word in (((3, 4), 12304, 4098), ((4, 3), 16400, 20482)):
            chosen = list(spec)
            chosen[2] = (*chosen[2][:2], children, *chosen[2][3:])
            topology = _topology(chosen)
            raw, names = _raw(topology, rows)
            result = solve_symbols(raw, topology, names, limits=SymbolLimits())
            assert _block_words(result, 4, names)['item'] == annotation_word
            assert _block_words(result, 1, names)['item'] == outer_word
            assert not result.blocks[2].parameters and '.0' not in _block_words(result, 2, names)
            assert [row.rule for row in result.transforms].count('SKIP_PARAM') == 1
            _dag(result, raw)
        # Missing parent slots copy child flags. Existing slots retain their own
        # low flags; either can become a cell for an inlined child lambda.
        for existing, word in ((False, 23042), (True, 22530)):
            topology, raw, names = _cell_fixture(existing)
            result = solve_symbols(raw, topology, names, limits=SymbolLimits())
            assert _block_words(result, 1, names)['item'] == word
            assert result.blocks[1].parameters == ()
            assert len(result.blocks[2].parameters) == 1
            assert any(row.rule == ('KEEP_PARENT' if existing else 'COPY') for row in result.transforms)
            assert any(fact.rule == 'COMP_CELL' for fact in result.facts)
            _dag(result, raw)
        # Class magic free reads through an inline comp are rewritten/deleted,
        # while the original inlined slot and its last proof remain inspectable.
        topology = _topology((('ROOT', None, (1,), 'PUBLIC', False),
            ('CLASS_BODY', 0, (2,), 'PUBLIC', False),
            ('COMPREHENSION', 1, (), 'INLINED', False)))
        raw, names = _raw(topology, [(0, 'C', 2), (2, '.0', 4), (2, '__class__', 16)])
        result = solve_symbols(raw, topology, names, limits=SymbolLimits())
        deleted = [i for i, slot in enumerate(result.slots) if slot.disposition == 'DELETED']
        assert len(deleted) == 1 and deleted[0] not in result.blocks[2].slots
        assert result.facts[result.slots[deleted[0]].final_fact].rule == 'DELETE_MAGIC'
        assert _block_words(result, 1, names)['__class__'] == 12304
        assert any(row.rule == 'DELETE_MAGIC' for row in result.transforms)
        return

    topology = _topology((
        ('ROOT', None, (1,), 'PUBLIC', False),
        ('FUNCTION_BODY', 0, (2,), 'PUBLIC', False),
        ('CLASS_BODY', 1, (3,), 'PUBLIC', False),
        ('FUNCTION_BODY', 2, (4,), 'PUBLIC', False),
        ('LAMBDA_BODY', 3, (), 'PUBLIC', False),
        ('HEADER_ANNOTATIONS', 0, (6,), 'FUTURE_DETACHED', False),
        ('LAMBDA_BODY', 5, (), 'DETACHED_DESCENDANT', False),
    ))
    raw, names = _raw(topology, [(0, 'outer', 2), (1, 'item', 2), (1, 'C', 18),
        (2, 'item', 2), (2, 'method', 2), (3, 'self', 4), (3, '__class__', 16),
        (4, 'item', 16), (5, '.format', 20), (6, 'NOT_ANALYZED', 16)], conditional=(2,))
    result = solve_symbols(raw, topology, names, limits=SymbolLimits())
    assert _block_words(result, 1, names)['item'] == 20482
    assert _block_words(result, 2, names)['item'] == 4162
    assert _block_words(result, 3, names)['item'] == 16384
    assert '__class__' not in _block_words(result, 2, names)
    rules = {row.rule for row in result.protocols}
    assert rules == {'CLASS_CLOSURE', 'CONDITIONAL_ANNOTATION_DECLARATION'}
    closure = next(row for row in result.protocols if row.rule == 'CLASS_CLOSURE')
    assert closure.block == 2 and closure.inputs
    method_class = next(i for i, slot in enumerate(result.slots) if slot.block == 3 and _text(slot, names) == '__class__')
    assert 2 in result.facts[result.slots[method_class].final_fact].witness_blocks
    relay = next(slot for slot in result.slots if slot.block == 3 and _text(slot, names) == 'item')
    assert result.facts[relay.final_fact].rule == 'FREE_RELAY' and relay.initial_fact is None
    for slot in result.slots:
        if slot.block in (5, 6):
            assert slot.disposition == 'DETACHED' and slot.initial_fact == slot.final_fact
            assert result.facts[slot.final_fact].scope_code is None
    _dag(result, raw)
    # The same handoff enforces budgets without returning a truncated solution.
    for changes in ({'max_facts': 0}, {'max_symbol_slots': len(raw.slots)}, {'max_steps': raw.steps}):
        with pytest.raises(SymbolStop) as stopped:
            solve_symbols(raw, topology, names, limits=replace(SymbolLimits(), **changes))
        assert stopped.value.budget
    inline_topology, inline_raw, inline_names = _cell_fixture()
    with pytest.raises(SymbolStop) as stopped:
        solve_symbols(inline_raw, inline_topology, inline_names, limits=replace(SymbolLimits(), max_transforms=0))
    assert stopped.value.budget
    # Nonlocal must not bind an enclosing type parameter, even though it is bound.
    bad = _topology((('ROOT', None, (1,), 'PUBLIC', False),
                    ('TYPE_PARAMETERS', 0, (2,), 'PUBLIC', False),
                    ('FUNCTION_BODY', 1, (), 'PUBLIC', False)))
    bad_raw, bad_names = _raw(bad, [(1, 'T', 2 | 1024), (2, 'T', 8)])
    with pytest.raises(SymbolStop) as stopped:
        solve_symbols(bad_raw, bad, bad_names, limits=SymbolLimits())
    assert not stopped.value.budget and stopped.value.frontier.code == 'NONLOCAL_TYPE_PARAMETER'
