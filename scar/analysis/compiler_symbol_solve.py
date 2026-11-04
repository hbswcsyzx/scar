"""Pinned CPython symbol analysis from source facts; native tables are not inputs."""
from dataclasses import dataclass
import sys

from scar.ir.program.compiler_symbols import (
    BlockSymbols, CompilerName, CompilerSlot, INTRINSIC_NAMES, ProtocolRequirement,
    RawCollection, SlotTransform, SymbolFact, SymbolLimits, SymbolSolution, SymbolStop,
)

FACT_RULES = ('COLLECT', 'GLOBAL_DIRECTIVE', 'NONLOCAL_BINDING', 'LOCAL_BINDING',
    'CLASS_GLOBAL', 'CLASS_BOUND', 'ENCLOSING_BINDING', 'IMPLICIT_GLOBAL',
    'INLINE_COPY', 'CELL_PROMOTION', 'COMP_CELL', 'FREE_CLASS', 'FREE_RELAY', 'DELETE_MAGIC')
TRANSFORM_RULES = ('COPY', 'KEEP_PARENT', 'SKIP_PARAM', 'DELETE_MAGIC')
PROTOCOL_RULES = ('CLASS_CLOSURE', 'CLASSDICT_CLOSURE',
    'CONDITIONAL_ANNOTATION_CAPTURE', 'CONDITIONAL_ANNOTATION_DECLARATION')

_GLOBAL, _LOCAL, _PARAM, _NONLOCAL, _USE = 1, 2, 4, 8, 16
_FREE_CLASS, _IMPORT, _ANNOT, _COMP_ITER, _TYPE_PARAM, _COMP_CELL = 64, 128, 256, 512, 1024, 2048
_BOUND = _LOCAL | _PARAM | _IMPORT
_LOW_MASK = 4095
_LOCAL_SCOPE, _GLOBAL_EXPLICIT, _GLOBAL_IMPLICIT, _FREE, _CELL = 1, 2, 3, 4, 5
_MAGIC = ('__class__', '__classdict__', '__conditional_annotations__')
_PROTOCOL = dict(zip(_MAGIC, PROTOCOL_RULES[:3]))


def _unique(items):
    return tuple(dict.fromkeys(items))


class _Environment:
    """Set operations mirror compiler operations; evidence does not set iteration order."""
    __slots__ = ('keys', 'facts', 'providers')

    def __init__(self):
        self.keys = set()
        self.facts = {}
        self.providers = {}

    def copy(self):
        other = _Environment()
        other.keys = set(self.keys)
        other.facts = dict(self.facts)
        other.providers = dict(self.providers)
        return other

    def add(self, name, facts=(), providers=()):
        self.keys.add(name)
        self.facts[name] = _unique((*self.facts.get(name, ()), *facts))
        self.providers[name] = _unique((*self.providers.get(name, ()), *providers))

    def discard(self, name):
        self.keys.discard(name)
        self.facts.pop(name, None)
        self.providers.pop(name, None)

    def update(self, other):
        self.keys |= other.keys
        for name in other.keys:
            self.facts[name] = _unique((*self.facts.get(name, ()), *other.facts.get(name, ())))
            self.providers[name] = _unique((*self.providers.get(name, ()), *other.providers.get(name, ())))


@dataclass(slots=True)
class _Frame:
    block: int
    bound: _Environment | None
    free: _Environment
    global_: _Environment
    type_params: _Environment
    class_entry: int | None
    scopes: dict
    newbound: _Environment
    newglobal: _Environment
    newfree: _Environment
    cells: _Environment
    cursor: int = 0


class _Solver:
    def __init__(self, raw, topology, source_names, limits):
        if (sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 14, 7)):
            raise ValueError('compiler symbol solver requires CPython 3.14.7')
        if not isinstance(raw, RawCollection) or not isinstance(limits, SymbolLimits):
            raise TypeError('expected typed raw compiler facts and limits')
        if topology.status != 'PROJECTED' or not topology.blocks:
            raise ValueError('symbol solver requires projected compiler topology')
        if type(source_names) is not tuple or any(type(n.value) is not str for n in source_names):
            raise TypeError('source_names must be a tuple of source name keys')
        self.raw, self.topology, self.limits = raw, topology, limits
        self.source_values = tuple(n.value for n in source_names)
        self.source_names = {n.value: i for i, n in enumerate(source_names)}
        if len(self.source_names) != len(source_names):
            raise ValueError('source name pool repeats a key')
        if type(raw.steps) is not int or raw.steps < 0:
            raise ValueError('invalid raw step counter')
        self.steps = raw.steps
        self.slots, self.facts, self.transforms, self.protocols = [], [], [], []
        self.present = [dict() for _ in topology.blocks]
        self.parameters = [() for _ in topology.blocks]
        self.protocol_indices = [[] for _ in topology.blocks]
        self.current = []
        self.deleted = set()
        self.effective_children = [None for _ in topology.blocks]
        self.names = {}
        self._budget('STEPS', self.steps, limits.max_steps)
        self._budget('SLOTS', len(raw.slots), limits.max_symbol_slots)
        self._budget('CONTRIBUTIONS', len(raw.contributions), limits.max_contributions)
        self._validate_topology()
        for index, slot in enumerate(raw.slots):
            self._block(slot.block)
            if type(slot.flags) is not int or slot.flags < 0 or slot.flags & ~_LOW_MASK:
                raise ValueError('raw slot flags must contain only low compiler bits')
            text = self.text(slot.name)
            if text in self.present[slot.block]:
                raise ValueError('duplicate compiler slot in one original block')
            for contribution in slot.contributions:
                if (type(contribution) is not int or not 0 <= contribution < len(raw.contributions)
                        or raw.contributions[contribution].slot != index):
                    raise ValueError('raw contribution does not belong to its slot')
            self.names.setdefault(text, slot.name)
            self.slots.append(CompilerSlot(slot.block, slot.name, slot.contributions, None, None, 'DETACHED'))
            self.current.append(None)
            self.present[slot.block][text] = index
            fact = self.fact(index, slot.flags, None, 'COLLECT')
            self.slots[index] = CompilerSlot(slot.block, slot.name, slot.contributions, fact, fact, 'DETACHED')
        seen = set()
        for row in raw.parameters:
            self._block(row.block)
            if row.block in seen:
                raise ValueError('duplicate raw parameter sequence')
            seen.add(row.block)
            if any(type(i) is not int or not 0 <= i < len(raw.slots)
                   or raw.slots[i].block != row.block or not raw.slots[i].flags & _PARAM for i in row.slots):
                raise ValueError('raw parameter sequence does not reference its parameter slots')
            self.parameters[row.block] = row.slots
        if seen != set(range(len(topology.blocks))):
            raise ValueError('one raw parameter sequence is required for every compiler block')
        if len(set(raw.conditional_blocks)) != len(raw.conditional_blocks):
            raise ValueError('duplicate conditional annotation block')
        for block in raw.conditional_blocks:
            self._block(block)
            if topology.blocks[block].origin.role not in ('ROOT', 'CLASS_BODY'):
                raise ValueError('conditional annotation requirement lacks creator block')
            self.protocol(block, self.name('__conditional_annotations__'), PROTOCOL_RULES[3], ())

    def _block(self, block):
        if type(block) is not int or not 0 <= block < len(self.topology.blocks):
            raise ValueError('invalid original compiler block reference')

    def _validate_topology(self):
        blocks = self.topology.blocks
        if blocks[0].parent is not None or blocks[0].origin.role != 'ROOT':
            raise ValueError('compiler topology lacks original root')
        seen = set()
        pending = [0]
        while pending:
            block = pending.pop()
            if block in seen:
                raise ValueError('original compiler children contain cycle or alias')
            seen.add(block)
            for child in blocks[block].children:
                self._block(child)
                if blocks[child].parent != block or blocks[child].attachment != 'DIRECT':
                    raise ValueError('compiler child does not preserve direct original parent')
                pending.append(child)
        for i, block in enumerate(blocks):
            if (i in seen) != (block.projection in ('PUBLIC', 'INLINED')):
                raise ValueError('public/inlined projection contradicts root attachment')

    def _budget(self, kind, count, maximum):
        if count > maximum:
            raise SymbolStop(kind + '_BUDGET', 'compiler symbol ' + kind.lower() + ' budget reached', budget=True)

    def tick(self):
        self._budget('STEPS', self.steps + 1, self.limits.max_steps)
        self.steps += 1

    def text(self, name):
        if not isinstance(name, CompilerName):
            raise TypeError('invalid compiler name reference')
        if name.kind == 'SOURCE':
            if name.source >= len(self.source_names):
                raise ValueError('compiler source name is outside original pool')
            # This map is constructed in the canonical source pool's order.
            return self.source_values[name.source]
        return name.intrinsic

    def name(self, text):
        if text in self.source_names:
            return CompilerName('SOURCE', source=self.source_names[text])
        if text in INTRINSIC_NAMES:
            return CompilerName('INTRINSIC', intrinsic=text)
        if text in self.names:
            return self.names[text]
        raise ValueError('free relay has no original source or language name')

    def fact(self, slot, low, scope, rule, inputs=(), witnesses=()):
        self.tick()
        self._budget('FACTS', len(self.facts) + 1, self.limits.max_facts)
        inputs = _unique(inputs)
        if rule not in FACT_RULES or any(type(i) is not int or not 0 <= i < len(self.facts) for i in inputs):
            raise ValueError('symbol proof is not a prior-fact DAG')
        if scope is not None and scope not in (1, 2, 3, 4, 5):
            raise ValueError('invalid symbol scope code')
        for block in witnesses:
            self._block(block)
        index = len(self.facts)
        self.facts.append(SymbolFact(slot, low, scope, rule, inputs, _unique(witnesses)))
        self.current[slot] = index
        return index

    def transform(self, rule, source, target, input_fact, output_fact):
        self.tick()
        self._budget('TRANSFORMS', len(self.transforms) + 1, self.limits.max_transforms)
        self.transforms.append(SlotTransform(rule, source, target, input_fact, output_fact))

    def protocol(self, block, name, rule, inputs):
        self.tick()
        index = len(self.protocols)
        self.protocols.append(ProtocolRequirement(block, name, rule, _unique(inputs)))
        self.protocol_indices[block].append(index)

    def new_slot(self, block, name, low, scope, rule, inputs, witnesses=()):
        self.tick()
        self._budget('SLOTS', len(self.slots) + 1, self.limits.max_symbol_slots)
        slot = len(self.slots)
        self.slots.append(CompilerSlot(block, name, (), None, None, 'DETACHED'))
        self.current.append(None)
        self.present[block][self.text(name)] = slot
        fact = self.fact(slot, low, scope, rule, inputs, witnesses)
        return slot, fact

    def latest(self, slot):
        index = self.current[slot]
        return index, self.facts[index]

    def _class(self, block):
        return self.topology.blocks[block].origin.role == 'CLASS_BODY'

    def _functionlike(self, block):
        return self.topology.blocks[block].origin.role not in ('ROOT', 'CLASS_BODY')

    def enter(self, block, bound, free, global_, type_params, class_entry):
        self.tick()
        scopes, local = {}, _Environment()
        newbound, newglobal = _Environment(), _Environment()
        if self._class(block):
            newglobal.update(global_)
            if bound is not None:
                newbound.update(bound)
        for text, slot in self.present[block].items():
            self.tick()
            old, rawfact = self.latest(slot)
            flags = rawfact.low_flags
            inputs, witnesses = (old,), ()
            if flags & _GLOBAL:
                if flags & _NONLOCAL:
                    raise SymbolStop('GLOBAL_NONLOCAL_CONFLICT', 'name is both global and nonlocal', block=block)
                scope, rule = _GLOBAL_EXPLICIT, 'GLOBAL_DIRECTIVE'
            elif flags & _NONLOCAL:
                if bound is None or text not in bound.keys:
                    raise SymbolStop('NONLOCAL_BINDING_MISSING', 'nonlocal name has no enclosing binding', block=block)
                if text in type_params.keys:
                    raise SymbolStop('NONLOCAL_TYPE_PARAMETER', 'nonlocal cannot rebind a type parameter', block=block)
                scope, rule = _FREE, 'NONLOCAL_BINDING'
                inputs += bound.facts.get(text, ())
                witnesses = bound.providers.get(text, ())
            elif flags & _BOUND:
                scope, rule = _LOCAL_SCOPE, 'LOCAL_BINDING'
            else:
                class_slot = None if class_entry is None else self.present[class_entry].get(text)
                class_fact = None if class_slot is None else self.latest(class_slot)
                if class_fact is not None and class_fact[1].low_flags & _GLOBAL:
                    scope, rule = _GLOBAL_EXPLICIT, 'CLASS_GLOBAL'
                    inputs += (class_fact[0],)
                    witnesses = (class_entry,)
                elif (class_fact is not None and class_fact[1].low_flags & _BOUND
                        and not class_fact[1].low_flags & _NONLOCAL):
                    scope, rule = _GLOBAL_IMPLICIT, 'CLASS_BOUND'
                    inputs += (class_fact[0],)
                    witnesses = (class_entry,)
                elif bound is not None and text in bound.keys:
                    scope, rule = _FREE, 'ENCLOSING_BINDING'
                    inputs += bound.facts.get(text, ())
                    witnesses = bound.providers.get(text, ())
                else:
                    scope, rule = _GLOBAL_IMPLICIT, 'IMPLICIT_GLOBAL'
                    inputs += global_.facts.get(text, ())
            fact = self.fact(slot, flags, scope, rule, inputs, witnesses)
            scopes[text] = scope
            if rule == 'GLOBAL_DIRECTIVE':
                global_.add(text, (fact,))
                if bound is not None:
                    bound.discard(text)
            elif rule in ('NONLOCAL_BINDING', 'ENCLOSING_BINDING'):
                free.add(text, (fact,))
            elif rule == 'LOCAL_BINDING':
                local.add(text, (fact,))
                global_.discard(text)
                if flags & _TYPE_PARAM:
                    type_params.add(text, (fact,))
                else:
                    type_params.discard(text)
        if not self._class(block):
            if self._functionlike(block):
                newbound.update(local)
            if bound is not None:
                newbound.update(bound)
            newglobal.update(global_)
        else:
            for text in _MAGIC:
                newbound.add(text, providers=(block,))
        return _Frame(block, bound, free, global_, type_params, class_entry,
                      scopes, newbound, newglobal, _Environment(), _Environment())

    def child_needs(self, block, text):
        for child in self.effective_children[block]:
            self.tick()
            slot = self.present[child].get(text)
            if slot is not None and self.latest(slot)[1].scope_code == _FREE:
                return True
        return False

    def inline(self, parent, child, child_free):
        deleted = []
        for text, source in self.present[child].items():
            self.tick()
            input_fact, value = self.latest(source)
            flags, scope = value.low_flags, value.scope_code
            if flags & _PARAM:
                if text != '.0':
                    raise ValueError('inlined comprehension has unexpected parameter')
                self.transform('SKIP_PARAM', source, None, input_fact, None)
                continue
            if scope == _CELL or flags & _COMP_CELL:
                parent.cells.add(text, (input_fact,))
            target = self.present[parent.block].get(text)
            if scope == _FREE and self._class(parent.block) and text in _MAGIC:
                scope = _GLOBAL_IMPLICIT
                if not self.child_needs(child, text):
                    child_free.discard(text)
                deleted.append((text, source, input_fact, value))
            if target is None:
                target, output = self.new_slot(parent.block, self.name(text), flags, scope,
                    'INLINE_COPY', (input_fact,), (child, parent.block))
                parent.scopes[text] = scope
                self.transform('COPY', source, target, input_fact, output)
            else:
                output, existing = self.latest(target)
                self.transform('KEEP_PARENT', source, target, input_fact, output)
                if existing.low_flags & _BOUND and not self._class(parent.block):
                    if not self.child_needs(child, text):
                        child_free.discard(text)
        for text, slot, old, value in deleted:
            output = self.fact(slot, value.low_flags, value.scope_code, 'DELETE_MAGIC', (old,), (parent.block, child))
            del self.present[child][text]
            self.deleted.add(slot)
            self.transform('DELETE_MAGIC', slot, None, old, output)

    def finish(self, frame):
        block = frame.block
        effective = []
        for child in self.topology.blocks[block].children:
            if self.topology.blocks[child].projection == 'INLINED':
                effective.extend(self.effective_children[child])
            else:
                effective.append(child)
        self.effective_children[block] = tuple(effective)
        if self._functionlike(block):
            for text, scope in frame.scopes.items():
                self.tick()
                if scope == _LOCAL_SCOPE and (text in frame.newfree.keys or text in frame.cells.keys):
                    slot = self.present[block][text]
                    old, value = self.latest(slot)
                    inputs = (old, *frame.newfree.facts.get(text, ()), *frame.cells.facts.get(text, ()))
                    self.fact(slot, value.low_flags, _CELL, 'CELL_PROMOTION', inputs, (block,))
                    frame.scopes[text] = _CELL
                    frame.newfree.discard(text)
        elif self._class(block):
            for text in _MAGIC:
                if text in frame.newfree.keys:
                    self.protocol(block, self.name(text), _PROTOCOL[text], frame.newfree.facts.get(text, ()))
                    frame.newfree.discard(text)
        for text, slot in self.present[block].items():
            self.tick()
            old, value = self.latest(slot)
            if text in frame.cells.keys:
                self.fact(slot, value.low_flags | _COMP_CELL, frame.scopes[text], 'COMP_CELL',
                          (old, *frame.cells.facts.get(text, ())), (block,))
        classflag = self._class(block) or self.topology.blocks[block].can_see_class_scope
        for text in frame.newfree.keys:
            self.tick()
            slot = self.present[block].get(text)
            origins = frame.newfree.facts.get(text, ())
            if slot is not None:
                if classflag:
                    old, value = self.latest(slot)
                    self.fact(slot, value.low_flags | _FREE_CLASS, value.scope_code, 'FREE_CLASS',
                              (old, *origins), (block,))
            elif frame.bound is None or text in frame.bound.keys:
                self.new_slot(block, self.name(text), 0, _FREE, 'FREE_RELAY', origins,
                              frame.bound.providers.get(text, ()) if frame.bound is not None else ())
        frame.free.update(frame.newfree)
        return frame.free

    def run(self):
        stack = [self.enter(0, None, _Environment(), _Environment(), _Environment(), None)]
        while stack:
            frame = stack[-1]
            children = self.topology.blocks[frame.block].children
            if frame.cursor < len(children):
                child = children[frame.cursor]
                frame.cursor += 1
                child_class = None
                if self.topology.blocks[child].can_see_class_scope:
                    child_class = frame.block if self._class(frame.block) else frame.class_entry
                stack.append(self.enter(child, frame.newbound.copy(), frame.newfree.copy(),
                    frame.newglobal.copy(), frame.type_params.copy(), child_class))
            else:
                out_free = self.finish(frame)
                stack.pop()
                if stack:
                    parent = stack[-1]
                    if self.topology.blocks[frame.block].projection == 'INLINED':
                        self.inline(parent, frame.block, out_free)
                    parent.newfree.update(out_free)
        finalized = []
        for index, slot in enumerate(self.slots):
            if index in self.deleted:
                disposition = 'DELETED'
            else:
                projection = self.topology.blocks[slot.block].projection
                disposition = projection if projection in ('PUBLIC', 'INLINED') else 'DETACHED'
            finalized.append(CompilerSlot(slot.block, slot.name, slot.contributions,
                                         slot.initial_fact, self.current[index], disposition))
        blocks = tuple(BlockSymbols(i, tuple(self.present[i].values()), self.parameters[i],
                                    tuple(self.protocol_indices[i])) for i in range(len(self.present)))
        return SymbolSolution(tuple(finalized), tuple(self.facts), tuple(self.transforms),
                              tuple(self.protocols), blocks, self.steps)


def solve_symbols(raw: RawCollection, topology, source_names: tuple, *, limits: SymbolLimits) -> SymbolSolution:
    """Analyze original compiler blocks without consuming any native symbol answers."""
    return _Solver(raw, topology, source_names, limits).run()


__all__ = ['solve_symbols', 'FACT_RULES', 'TRANSFORM_RULES', 'PROTOCOL_RULES']
