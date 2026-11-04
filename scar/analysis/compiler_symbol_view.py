"""Queries and reference validation for C3-S versioned compiler-symbol facts."""
from hashlib import sha256
import json

from scar.ir.program.compiler_symbols import CompilerName, CompilerSymbolsMaterial
from scar.ir.program.compiler_topology import CompilerTopologyMaterial
from scar.ir.program.source_declarations import SourceDeclarationsMaterial
from scar.ir.program.source_symbols import SourceSymbolsMaterial
from scar.ir.record_codec import encode


_LOW_MASK = 1 | 2 | 4 | 8 | 16 | 64 | 128 | 256 | 512 | 1024 | 2048


def _digest(document):
    return sha256(json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()


def _index(index, size, label):
    if type(index) is not int or not 0 <= index < size:
        raise ValueError('C3-S ' + label + ' is outside its original table')
    return index


class CompilerSymbolView:
    """Source contribution, compiler slot and original native row are distinct."""

    def __init__(self, declarations, topology, native, material, *, contexts=None):
        from scar.analysis.compiler_symbols import _catalog
        if (type(declarations) is not SourceDeclarationsMaterial or declarations.status != 'DECLARED'
                or type(topology) is not CompilerTopologyMaterial
                or type(native) is not SourceSymbolsMaterial
                or type(material) is not CompilerSymbolsMaterial
                or material.status not in ('PROJECTED', 'SOURCE_ONLY_MODE')):
            raise ValueError('C3-S queries require typed declared/projected inputs')
        self.declarations, self.topology, self.native, self.material = declarations, topology, native, material
        self.context_view, self.catalog = contexts, _catalog()
        basis = material.input
        if (basis.c2a_document_sha256 != _digest(encode(declarations))
                or basis.topology_document_sha256 != _digest(encode(topology))
                or basis.f3a_document_sha256 != _digest(encode(native))
                or basis.declaration_status != declarations.status or basis.topology_status != topology.status
                or basis.source_count != len(declarations.contributions) or basis.block_count != len(topology.blocks)
                or basis.native_symbol_count != sum(len(row.symbols) for row in native.scopes)
                or basis.native_parameter_count != sum(len(row.varnames) for row in native.scopes)
                or any(getattr(basis, field) != getattr(topology.input, field)
                    for field in ('f0_document_sha256', 'f1_document_sha256', 'f2_document_sha256',
                        'f3b_document_sha256', 'c1_document_sha256', 'f3a_document_sha256', 'path', 'mode'))
                or material.profile.symbol_catalog_sha256 != self.catalog.content_sha256
                or material.profile.topology_catalog_sha256 != topology.profile.topology_catalog_sha256
                or material.profile.declaration_catalog_sha256 != declarations.profile.declaration_catalog_sha256
                or material.profile.native_profile_sha256 != _digest(encode(native.profile))):
            raise ValueError('C3-S source/compiler receipts or catalog profile differ')
        if contexts is not None and _digest(encode(contexts.material)) != basis.c1_document_sha256:
            raise ValueError('C3-S source context view belongs to another source unit')
        self._source_names = {row.value for row in declarations.names}
        self._symbols = {(row.native_scope, row.ordinal): row for row in material.symbols}
        self._parameters = {(row.native_scope, row.ordinal): row for row in material.parameters}

    def name(self, reference):
        if type(reference) is not CompilerName:
            raise ValueError('C3-S compiler name must have a typed source/intrinsic reference')
        if reference.kind == 'SOURCE':
            return self.declarations.names[_index(reference.source, len(self.declarations.names), 'source name')].value
        if reference.intrinsic not in self.catalog.intrinsic_names or reference.intrinsic in self._source_names:
            raise ValueError('C3-S intrinsic name is not canonical against the source pool')
        return reference.intrinsic

    def slot(self, index):
        return self.material.slots[_index(index, len(self.material.slots), 'compiler slot')]

    def fact(self, index):
        return self.material.facts[_index(index, len(self.material.facts), 'symbol fact')]

    def contribution(self, index):
        return self.material.contributions[_index(index, len(self.material.contributions), 'raw contribution')]

    def source(self, index):
        return self.material.sources[_index(index, len(self.material.sources), 'source contribution')]

    def block(self, index):
        return self.material.blocks[_index(index, len(self.material.blocks), 'compiler block')]

    def port(self, index):
        row = self.declarations.ports[_index(index, len(self.declarations.ports), 'original source port')]
        return None if row.contribution is None else self.source(row.contribution)

    def symbol(self, native_scope, ordinal):
        _index(native_scope, len(self.native.scopes), 'original native scope')
        _index(ordinal, len(self.native.scopes[native_scope].symbols), 'original native symbol')
        return self._symbols[native_scope, ordinal]

    def parameter(self, native_scope, ordinal):
        _index(native_scope, len(self.native.scopes), 'original native scope')
        _index(ordinal, len(self.native.scopes[native_scope].varnames), 'original parameter')
        return self._parameters[native_scope, ordinal]

    def why(self, native_scope, ordinal, *, max_facts=100_000):
        """Return bounded proof references, retaining source/derived distinctions."""
        if type(max_facts) is not int or max_facts < 0:
            raise ValueError('proof query budget must be an exact nonnegative integer')
        projection = self.symbol(native_scope, ordinal)
        pending, found, raw = [projection.fact], set(), set()
        while pending:
            index = pending.pop()
            if index in found:
                continue
            if len(found) >= max_facts:
                raise ValueError('compiler symbol proof query budget reached')
            found.add(index)
            fact = self.fact(index)
            pending.extend(fact.inputs)
            raw.update(self.slot(fact.slot).contributions)
        source = set()
        todo = list(raw)
        while todo:
            event = self.contribution(todo.pop())
            if event.source is not None:
                source.add(event.source)
            if event.derived_from is not None and event.derived_from not in raw:
                raw.add(event.derived_from)
                todo.append(event.derived_from)
        return dict(symbol=projection, facts=tuple(sorted(found)), contributions=tuple(sorted(raw)),
            source_contributions=tuple(sorted(source)))

    def verify(self):
        data = self.material
        if tuple(row.source for row in data.sources) != tuple(range(len(self.declarations.contributions))):
            raise ValueError('C3-S source dispositions do not preserve every original C2a ordinal')
        if data.status == 'SOURCE_ONLY_MODE':
            if data.input.mode != 'func_type' or self.topology.status != 'SOURCE_ONLY_MODE':
                raise ValueError('C3-S grammar-only record has a different compiler boundary')
            return dict(sources=len(data.sources), slots=0, symbols=0, parameters=0, facts=0)
        if tuple(row.block for row in data.blocks) != tuple(range(len(self.topology.blocks))):
            raise ValueError('C3-S block symbol tables do not cover the accepted original templates')
        keys, events = set(), [[] for _ in data.slots]
        for index, slot in enumerate(data.slots):
            _index(slot.block, len(self.topology.blocks), 'original compiler template')
            key = slot.block, self.name(slot.name)
            if key in keys or slot.disposition not in self.catalog.slot_dispositions:
                raise ValueError('C3-S compiler slot key is duplicated or its disposition is undeclared')
            keys.add(key)
            if slot.initial_fact is not None:
                fact = self.fact(slot.initial_fact)
                if fact.slot != index or fact.rule != 'COLLECT' or fact.scope_code is not None:
                    raise ValueError('C3-S initial slot fact is not its raw collection')
            if slot.final_fact is None or self.fact(slot.final_fact).slot != index:
                raise ValueError('C3-S compiler slot loses its final value/deletion provenance')
            if bool(slot.contributions) != (slot.initial_fact is not None):
                raise ValueError('C3-S raw/derived slot origin contradicts its initial fact')
        for index, event in enumerate(data.contributions):
            _index(event.context_block, len(self.topology.blocks), 'contribution context')
            self.slot(event.slot)
            if (type(event.flags) is not int or event.flags <= 0 or event.flags & ~_LOW_MASK
                    or event.rule not in self.catalog.raw_rules):
                raise ValueError('C3-S raw contribution has an undeclared low mask/rule')
            if event.source is not None:
                _index(event.source, len(self.declarations.contributions), 'original C2a contribution')
            if event.derived_from is not None:
                _index(event.derived_from, index, 'prior raw provenance')
            if event.anchor is not None and self.context_view is not None:
                self.context_view.role_view.locate(event.anchor)
            if event.source is None and event.anchor is None and event.derived_from is None:
                # These language operations are sourced by their original block
                # origin, never a fabricated source name/port.
                block = self.topology.blocks[event.context_block]
                if block.origin.role == 'ROOT' and event.rule not in ('CONDITIONAL_ANNOTATION_USE',):
                    raise ValueError('C3-S derived raw contribution lacks a source/block protocol origin')
            events[event.slot].append(index)
        for index, slot in enumerate(data.slots):
            if slot.contributions != tuple(events[index]):
                raise ValueError('C3-S slot/raw contribution inverse edges are incomplete or reordered')
            if slot.initial_fact is not None:
                flags = 0
                for event in events[index]:flags |= data.contributions[event].flags
                if self.fact(slot.initial_fact).low_flags != flags:
                    raise ValueError('C3-S initial fact does not equal its explicit raw contributions')
        for row in data.sources:
            if row.disposition not in self.catalog.source_dispositions or len(set(row.contributions)) != len(row.contributions):
                raise ValueError('C3-S source disposition is undeclared or has duplicated provenance')
            for event in row.contributions:
                self.contribution(event)
            if (row.disposition in ('EMITTED', 'DETACHED_RAW')) != bool(row.contributions):
                raise ValueError('C3-S source participation loses its effective/ignored distinction')
        for index, fact in enumerate(data.facts):
            self.slot(fact.slot)
            if (type(fact.low_flags) is not int or fact.low_flags < 0 or fact.low_flags & ~_LOW_MASK
                    or fact.scope_code is not None and (type(fact.scope_code) is not int or fact.scope_code not in (1, 2, 3, 4, 5))
                    or fact.rule not in self.catalog.fact_rules):
                raise ValueError('C3-S fact has an undeclared low mask/scope enum/rule')
            if len(set(fact.inputs)) != len(fact.inputs):
                raise ValueError('C3-S fact dependencies are duplicated')
            for dependency in fact.inputs:_index(dependency, index, 'prior versioned fact')
            for block in fact.witness_blocks:_index(block, len(self.topology.blocks), 'witness block')
        for row in data.transforms:
            if row.rule not in self.catalog.transform_rules:
                raise ValueError('C3-S transform has an undeclared rule')
            self.slot(row.source_slot)
            if self.fact(row.input_fact).slot != row.source_slot:
                raise ValueError('C3-S transform input fact belongs to another slot')
            if row.target_slot is not None:self.slot(row.target_slot)
            if row.output_fact is not None:
                expected = row.source_slot if row.target_slot is None else row.target_slot
                if self.fact(row.output_fact).slot != expected:
                    raise ValueError('C3-S transform output fact belongs to another slot')
        protocols = [[] for _ in self.topology.blocks]
        for index, row in enumerate(data.protocols):
            _index(row.block, len(self.topology.blocks), 'protocol block')
            self.name(row.name)
            if row.rule not in self.catalog.protocol_rules:
                raise ValueError('C3-S class protocol has an undeclared rule')
            for fact in row.inputs:self.fact(fact)
            protocols[row.block].append(index)
        present, parameters = set(), set()
        for row in data.blocks:
            if len(set(row.slots)) != len(row.slots) or len(set(row.parameters)) != len(row.parameters):
                raise ValueError('C3-S final slots or parameter positions are duplicated')
            for slot in row.slots:
                if self.slot(slot).block != row.block or self.slot(slot).disposition == 'DELETED':
                    raise ValueError('C3-S present compiler slot belongs to another block or was deleted')
                present.add(slot)
            for slot in row.parameters:
                if self.slot(slot).block != row.block or self.slot(slot).initial_fact is None:
                    raise ValueError('C3-S parameter lacks its original declaration slot')
                if not self.fact(self.slot(slot).initial_fact).low_flags & 4:
                    raise ValueError('C3-S ordered parameter is not a DEF_PARAM contribution')
                parameters.add(slot)
            if row.protocols != tuple(protocols[row.block]):
                raise ValueError('C3-S block/protocol inverse edges are incomplete')
        if present != {i for i, slot in enumerate(data.slots) if slot.disposition != 'DELETED'}:
            raise ValueError('C3-S compiler slots have an unexplained final disappearance')
        if parameters != {i for i, slot in enumerate(data.slots)
                if slot.initial_fact is not None and self.fact(slot.initial_fact).low_flags & 4}:
            raise ValueError('C3-S ordered parameters do not cover every original DEF_PARAM slot')
        expected_symbols = [(i, j) for i, row in enumerate(self.native.scopes) for j in range(len(row.symbols))]
        expected_parameters = [(i, j) for i, row in enumerate(self.native.scopes) for j in range(len(row.varnames))]
        if ([(row.native_scope, row.ordinal) for row in data.symbols] != expected_symbols
                or [(row.native_scope, row.ordinal) for row in data.parameters] != expected_parameters):
            raise ValueError('C3-S public projections do not preserve every original row/parameter ordinal')
        for row in data.symbols:
            slot, fact = self.slot(row.slot), self.fact(row.fact)
            expected = self.native.scopes[row.native_scope].symbols[row.ordinal]
            if (self.topology.blocks[slot.block].public_scope != row.native_scope
                    or slot.disposition != 'PUBLIC' or slot.final_fact != row.fact or fact.slot != row.slot
                    or self.name(slot.name) != expected.name or fact.scope_code is None
                    or fact.low_flags | (fact.scope_code << 12) != expected.flags):
                raise ValueError('C3-S projected native word loses its source-derived final fact')
        for row in data.parameters:
            slot = self.slot(row.slot)
            if (self.topology.blocks[slot.block].public_scope != row.native_scope
                    or self.name(slot.name) != self.native.scopes[row.native_scope].varnames[row.ordinal]
                    or data.blocks[slot.block].parameters[row.ordinal] != row.slot):
                raise ValueError('C3-S projected parameter loses its exact original order')
        return {key: len(getattr(data, key)) for key in ('slots', 'contributions', 'sources',
            'facts', 'transforms', 'protocols', 'blocks', 'symbols', 'parameters')}


__all__ = ['CompilerSymbolView']
