"""C3-S first-pass scalar symbol events over the accepted C3-T visitor.

Native symbols/varnames are never read here. Native metadata is used only by
C3-T's existing topology replay. Source declarations supply canonical keys and
provenance, not the flags emitted by this visitor.
"""
from __future__ import annotations
from dataclasses import replace

from scar.analysis.compiler_topology import _Builder, _FUNCTIONLIKE, TopologyStop
from scar.analysis.source_declaration_view import SourceDeclarationView
from scar.ir.program.source_roles import SlotRef
from scar.ir.program.compiler_symbols import (
    INTRINSIC_NAMES, CompilerName, SymbolLimits, SymbolStop, RawCollection,
    RawContribution, RawSlot, RawParameters, SourceDisposition,
)

RAW_RULES = (
    'SOURCE_BINDER', 'SOURCE_PARAMETER', 'TYPE_PARAMETER', 'NAME_LOAD', 'NAME_STORE',
    'NAME_DELETE', 'ANNOTATED_TARGET', 'PATTERN_BINDER', 'EXCEPT_BINDER', 'IMPORT_BINDER',
    'GLOBAL_DIRECTIVE', 'NONLOCAL_DIRECTIVE', 'WALRUS_ORIGIN_DIRECTIVE', 'WALRUS_HOME_BINDING',
    'GLOBAL_ECHO', 'FORMAT_PARAMETER', 'FORMAT_USE', 'COMPREHENSION_PARAMETER',
    'GENERIC_DEFAULTS_PARAMETER', 'GENERIC_KWDEFAULTS_PARAMETER', 'TYPE_PARAMS_LOCAL',
    'TYPE_PARAMS_USE', 'GENERIC_BASE_LOCAL', 'GENERIC_BASE_USE', 'CLASS_TYPE_PARAMS_BINDING',
    'CLASS_TYPE_PARAMS_USE', 'SUPER_CLASS_USE', 'CLASSDICT_USE', 'CONDITIONAL_ANNOTATION_USE',
)
GLOBAL, LOCAL, PARAM, NONLOCAL, USE = 1, 2, 4, 8, 16
IMPORT, ANNOT, COMP_ITER, TYPE_PARAM = 128, 256, 512, 1024
_CONDITIONAL_FIELDS = {
    'For': frozenset(('body', 'orelse')), 'AsyncFor': frozenset(('body', 'orelse')),
    'While': frozenset(('body', 'orelse')), 'If': frozenset(('body', 'orelse')),
    'Match': frozenset(('cases',)), 'Try': frozenset(('body', 'handlers', 'orelse', 'finalbody')),
    'TryStar': frozenset(('body', 'handlers', 'orelse', 'finalbody')),
    'With': frozenset(('items', 'body')), 'AsyncWith': frozenset(('items', 'body')),
}


class _Collector(_Builder):
    def __init__(self, syntax, roles, contexts, declarations, native, topology, limits):
        self.limits_symbols, self.accepted = limits, topology
        self.symbol_steps = 0
        super().__init__(syntax, roles, contexts, native,
            (max(1, len(topology.blocks)), max(1, len(topology.rewrites)), limits.max_steps))
        SourceDeclarationView(roles, contexts, declarations, contexts=self.view).verify()
        self.declarations = declarations
        self.source_by_site = {}
        for index, row in enumerate(declarations.contributions):
            if row.site in self.source_by_site:
                raise SymbolStop('DUPLICATE_SOURCE_CONTRIBUTION_SITE', 'C2a contributions repeat an original source site', source=index)
            self.source_by_site[row.site] = index
        self.pool = {row.value: index for index, row in enumerate(declarations.names)}
        self.names = {}
        self.raw_slots, self.slot_index, self.events = [], {}, []
        self.source_events = [[] for _ in declarations.contributions]
        self.ignored = set()
        self.param_slots, self.formals_emitted = {}, set()
        self.target_mode, self.iter_expression, self.unevaluated, self.conditional = {}, {}, {}, {}
        self.has_conditional = set()

    def step(self, *, block=None, source=None):
        if self.symbol_steps >= self.limits_symbols.max_steps:
            raise SymbolStop('SYMBOL_STEP_BUDGET', 'symbol visitor budget reached', block=block, source=source, budget=True)
        self.symbol_steps += 1

    def tick(self, occurrence, role=None):
        self.step(block=self.current)
        super().tick(occurrence, role)

    def site(self, occurrence, name, item_path=()):
        return SlotRef(occurrence, 'FIELD', self.fields.fields[self.syntax.nodes[occurrence].constructor][name], item_path)

    def source(self, occurrence, name, item_path=(), *, required=True):
        site = self.site(occurrence, name, item_path)
        index = self.source_by_site.get(site)
        if index is None and required:
            raise SymbolStop('SOURCE_CONTRIBUTION_MISSING', 'visitor name lacks its original C2a contribution', block=self.current)
        return index, site

    def name(self, text):
        if text not in self.names:
            if text in self.pool:
                self.names[text] = CompilerName('SOURCE', source=self.pool[text])
            elif text in INTRINSIC_NAMES:
                self.names[text] = CompilerName('INTRINSIC', intrinsic=text)
            else:
                raise SymbolStop('COMPILER_NAME_SOURCE_MISSING', 'non-intrinsic compiler name is absent from the source pool', block=self.current)
        return self.names[text]

    def source_name(self, source):
        return self.declarations.names[self.declarations.contributions[source].name].value

    def slot(self, block, text):
        name = self.name(text)
        key = block, name
        if key not in self.slot_index:
            if len(self.raw_slots) >= self.limits_symbols.max_symbol_slots:
                raise SymbolStop('SYMBOL_SLOT_BUDGET', 'raw compiler slot budget reached', block=block, budget=True)
            self.slot_index[key] = len(self.raw_slots)
            self.raw_slots.append([block, name, 0, []])
        return self.slot_index[key]

    def emit(self, text, flags, rule, *, source=None, anchor=None, target=None, context=None,
             derived_from=None, echo=True):
        context = self.current if context is None else context
        target = context if target is None else target
        self.step(block=context, source=source)
        if rule not in RAW_RULES:
            raise ValueError('compiler collector used an undeclared raw rule')
        if len(self.events) >= self.limits_symbols.max_contributions:
            raise SymbolStop('COMPILER_CONTRIBUTION_BUDGET', 'raw compiler contribution budget reached',
                block=context, source=source, budget=True)
        slot = self.slot(target, text)
        old = self.raw_slots[slot][2]
        if flags & PARAM and old & PARAM or flags & TYPE_PARAM and old & TYPE_PARAM:
            raise SymbolStop('DUPLICATE_COMPILER_PARAMETER', 'first-pass parameter declaration is repeated', block=target, source=source)
        effective = flags
        if self.target_mode[context] and rule != 'GLOBAL_ECHO':
            if (old | flags) & (GLOBAL | NONLOCAL):
                raise SymbolStop('COMPREHENSION_TARGET_DIRECTIVE_CONFLICT', 'comprehension target conflicts with a directive', block=target, source=source)
            effective |= COMP_ITER
        event = len(self.events)
        self.events.append(RawContribution(context, slot, effective, rule, source, anchor, derived_from))
        self.raw_slots[slot][2] |= effective
        self.raw_slots[slot][3].append(event)
        if source is not None:
            self.source_events[source].append(event)
        if flags & PARAM:
            self.param_slots[target].append(slot)
        elif flags & GLOBAL and echo:
            # The helper mirrors the original flag, not target-mode decoration,
            # into st_global immediately. The root self-echo is idempotent but
            # retained as explicit causal provenance.
            self.emit(text, flags, 'GLOBAL_ECHO', source=source, anchor=anchor, target=0,
                context=context, derived_from=event, echo=False)
        return event

    def emit_source(self, occurrence, name, flags, rule, item_path=(), *, target=None):
        source, anchor = self.source(occurrence, name, item_path)
        return self.emit(self.source_name(source), flags, rule, source=source, anchor=anchor, target=target)

    def block(self, occurrence, role, *, can_see=False, attach=True):
        index = super().block(occurrence, role, can_see=can_see, attach=attach)
        parent = self.blocks[index].parent
        self.target_mode[index] = False
        self.iter_expression[index] = 0 if parent is None else self.iter_expression[parent]
        self.unevaluated[index] = False
        self.conditional[index] = False
        self.param_slots[index] = []
        origin = self.blocks[index].origin
        if role in ('HEADER_ANNOTATIONS', 'VARIABLE_ANNOTATIONS', 'TYPE_PARAMETER_BOUND',
                    'TYPE_PARAMETER_DEFAULT', 'TYPE_ALIAS'):
            field = ('args' if role == 'HEADER_ANNOTATIONS' else 'bound' if role == 'TYPE_PARAMETER_BOUND'
                else 'default_value' if role == 'TYPE_PARAMETER_DEFAULT' else 'value' if role == 'TYPE_ALIAS' else None)
            anchor = (self.site(occurrence, field) if field is not None else
                self.contexts.scopes[self.blocks[index].source_scope].anchor)
            self.emit('.format', PARAM, 'FORMAT_PARAMETER', context=index, anchor=anchor)
            self.emit('.format', USE, 'FORMAT_USE', context=index, anchor=anchor)
            if can_see:
                self.emit('__classdict__', USE, 'CLASSDICT_USE', context=index, anchor=anchor)
        elif role == 'TYPE_PARAMETERS':
            anchor = self.site(occurrence, 'type_params')
            if can_see:
                self.emit('__classdict__', USE, 'CLASSDICT_USE', context=index, anchor=anchor)
            kind = self.syntax.nodes[occurrence].constructor
            if kind == 'ClassDef':
                for text, local_rule, use_rule in (('.type_params', 'TYPE_PARAMS_LOCAL', 'TYPE_PARAMS_USE'),
                        ('.generic_base', 'GENERIC_BASE_LOCAL', 'GENERIC_BASE_USE')):
                    self.emit(text, LOCAL, local_rule, context=index, anchor=anchor)
                    self.emit(text, USE, use_rule, context=index, anchor=anchor)
            elif kind in ('FunctionDef', 'AsyncFunctionDef'):
                arguments = self.field(occurrence, 'args').reference
                # The pinned source parser supplies a non-NULL defaults ASDL
                # sequence even for []; official code tests NULL, not length.
                self.emit('.defaults', PARAM, 'GENERIC_DEFAULTS_PARAMETER', context=index,
                    anchor=self.site(arguments, 'defaults'))
                if any(value.kind == 'NODE' for value in self.field(arguments, 'kw_defaults').items):
                    self.emit('.kwdefaults', PARAM, 'GENERIC_KWDEFAULTS_PARAMETER', context=index,
                        anchor=self.site(arguments, 'kw_defaults'))
        elif role == 'CLASS_BODY':
            if self.field(occurrence, 'type_params').items:
                anchor = self.site(occurrence, 'type_params')
                self.emit('__type_params__', LOCAL, 'CLASS_TYPE_PARAMS_BINDING', context=index, anchor=anchor)
                self.emit('.type_params', USE, 'CLASS_TYPE_PARAMS_USE', context=index, anchor=anchor)
        elif role in ('COMPREHENSION', 'GENERATOR_EXPRESSION'):
            self.emit('.0', PARAM, 'COMPREHENSION_PARAMETER', context=index, anchor=self.site(occurrence, 'generators', (0,)))
        return index

    def enter(self, block, fields):
        role = self.blocks[block].origin.role
        if role in ('FUNCTION_BODY', 'LAMBDA_BODY') and block not in self.formals_emitted:
            self.formals_emitted.add(block)
            occurrence = self.blocks[block].origin.occurrence
            arguments = self.field(occurrence, 'args').reference
            previous, self.current = self.current, block
            try:
                for name in ('posonlyargs', 'args', 'kwonlyargs', 'vararg', 'kwarg'):
                    value = self.field(arguments, name)
                    members = value.items if value.kind == 'LIST' else (value,)
                    for item in members:
                        if item.kind == 'NODE':
                            self.emit_source(item.reference, 'arg', PARAM, 'SOURCE_PARAMETER')
            finally:
                self.current = previous
        return super().enter(block, fields)

    def visit_field(self, occurrence, name):
        if self.syntax.nodes[occurrence].constructor == 'comprehension' and name in ('target', 'iter'):
            block = self.current
            if name == 'target':
                old, self.target_mode[block] = self.target_mode[block], True
                try:
                    return super().visit_field(occurrence, name)
                finally:
                    self.target_mode[block] = old
            self.iter_expression[block] += 1
            try:
                return super().visit_field(occurrence, name)
            finally:
                self.iter_expression[block] -= 1
        return super().visit_field(occurrence, name)

    def variable_annotation(self, occurrence):
        target = self.field(occurrence, 'target').reference
        value = self.field(occurrence, 'value')
        if self.syntax.nodes[target].constructor == 'Name':
            simple = self.field(occurrence, 'simple').scalar.to_python()
            if simple:
                self.emit_source(target, 'id', LOCAL | ANNOT, 'ANNOTATED_TARGET')
            elif value.kind == 'NODE':
                self.emit_source(target, 'id', LOCAL, 'ANNOTATED_TARGET')
        else:
            self.visit_field(occurrence, 'target')
        creator = self.current
        if (self.blocks[creator].origin.role == 'ROOT'
                or self.blocks[creator].origin.role == 'CLASS_BODY' and self.conditional[creator]):
            if creator not in self.has_conditional:
                self.has_conditional.add(creator)
                self.emit('__conditional_annotations__', USE, 'CONDITIONAL_ANNOTATION_USE',
                    anchor=self.site(occurrence, 'annotation'))
        if creator not in self.variable_annotations:
            block = self.block(self.blocks[creator].origin.occurrence, 'VARIABLE_ANNOTATIONS',
                can_see=self.blocks[creator].origin.role == 'CLASS_BODY' and not self.future)
            self.variable_annotations[creator] = block
        annotation = self.variable_annotations[creator]
        # All FunctionBlock kinds share this rule; nested blocks reset the bit.
        old = self.unevaluated[annotation]
        self.unevaluated[annotation] = self.blocks[creator].origin.role in (
            'FUNCTION_BODY', 'LAMBDA_BODY', 'COMPREHENSION', 'GENERATOR_EXPRESSION')
        try:
            self.enter(annotation, ((occurrence, 'annotation'),))
        finally:
            self.unevaluated[annotation] = old
        self.visit_field(occurrence, 'value')

    def named_expression(self, occurrence):
        if self.iter_expression[self.current]:
            raise SymbolStop('WALRUS_IN_COMPREHENSION_ITERABLE', 'named expression in an inherited comprehension iterable context', block=self.current)
        if self.blocks[self.current].origin.role not in ('COMPREHENSION', 'GENERATOR_EXPRESSION'):
            return
        target = self.field(occurrence, 'target').reference
        source, anchor = self.source(target, 'id')
        text = self.source_name(source)
        block = self.current
        while block is not None:
            self.step(block=block, source=source)
            role = self.blocks[block].origin.role
            if role in ('COMPREHENSION', 'GENERATOR_EXPRESSION'):
                slot = self.slot_index.get((block, self.name(text)))
                flags = 0 if slot is None else self.raw_slots[slot][2]
                if flags & COMP_ITER and flags & LOCAL:
                    raise SymbolStop('WALRUS_REBINDS_COMP_TARGET', 'named expression conflicts with a comprehension target', block=block, source=source)
            elif role in ('FUNCTION_BODY', 'LAMBDA_BODY'):
                slot = self.slot_index.get((block, self.name(text)))
                flags = 0 if slot is None else self.raw_slots[slot][2]
                self.emit(text, GLOBAL if flags & GLOBAL else NONLOCAL, 'WALRUS_ORIGIN_DIRECTIVE', source=source, anchor=anchor)
                self.emit(text, LOCAL, 'WALRUS_HOME_BINDING', source=source, anchor=anchor, target=block)
                return
            elif role == 'ROOT':
                self.emit(text, GLOBAL, 'WALRUS_ORIGIN_DIRECTIVE', source=source, anchor=anchor)
                self.emit(text, GLOBAL, 'WALRUS_HOME_BINDING', source=source, anchor=anchor, target=block)
                return
            else:
                raise SymbolStop('WALRUS_FORBIDDEN_COMPILER_HOME', 'named expression escapes into a class/type compiler scope', block=block, source=source)
            block = self.blocks[block].parent
        raise SymbolStop('WALRUS_COMPILER_HOME_MISSING', 'named expression has no enclosing compiler home', source=source)

    def generic(self, occurrence):
        node, block = self.syntax.nodes[occurrence], self.current
        constructor = self.constructors[node.constructor]
        for rule_id in constructor.fields:
            rule = self.catalog.fields[rule_id]
            if rule.dispatch not in ('ORDERED_VISIT', 'HANDLER_FIELD'):
                continue
            old = self.conditional[block]
            if rule.name in _CONDITIONAL_FIELDS.get(node.constructor, ()):
                self.conditional[block] = True
            try:
                self.value(node.fields[rule.ordinal])
            finally:
                self.conditional[block] = old

    def visit(self, occurrence):
        node = self.syntax.nodes[occurrence]
        kind = node.constructor
        if kind == 'Name':
            self.tick(occurrence)
            source, anchor = self.source(occurrence, 'id', required=False)
            if source is None:
                raise SymbolStop('NAME_SOURCE_CONTRIBUTION_MISSING', 'visited Name has no original source contribution', block=self.current)
            if self.unevaluated[self.current]:
                self.ignored.add(source)
                return
            ctx = self.syntax.nodes[self.field(occurrence, 'ctx').reference].constructor
            flags, rule = (USE, 'NAME_LOAD') if ctx == 'Load' else (LOCAL, 'NAME_DELETE' if ctx == 'Del' else 'NAME_STORE')
            self.emit(self.source_name(source), flags, rule, source=source, anchor=anchor)
            if ctx == 'Load' and self.source_name(source) == 'super' and self.blocks[self.current].origin.role in _FUNCTIONLIKE:
                self.emit('__class__', USE, 'SUPER_CLASS_USE', anchor=anchor)
            return
        if kind in ('FunctionDef', 'AsyncFunctionDef', 'ClassDef'):
            self.emit_source(occurrence, 'name', LOCAL, 'SOURCE_BINDER')
        elif kind in ('TypeVar', 'TypeVarTuple', 'ParamSpec'):
            self.emit_source(occurrence, 'name', LOCAL | TYPE_PARAM, 'TYPE_PARAMETER')
        elif kind in ('Global', 'Nonlocal'):
            for index, _ in enumerate(self.field(occurrence, 'names').items):
                self.emit_source(occurrence, 'names', GLOBAL if kind == 'Global' else NONLOCAL,
                    'GLOBAL_DIRECTIVE' if kind == 'Global' else 'NONLOCAL_DIRECTIVE', (index,))
        elif kind == 'alias':
            # Only the binder contribution, not IMPORT_*_SPEC or a star marker,
            # is in the C2a contribution table.
            for field in ('asname', 'name'):
                source, anchor = self.source(occurrence, field, required=False)
                if source is not None:
                    self.emit(self.source_name(source), IMPORT, 'IMPORT_BINDER', source=source, anchor=anchor)
                    break
        elif kind == 'MatchStar':
            source, anchor = self.source(occurrence, 'name', required=False)
            if source is not None:
                self.emit(self.source_name(source), LOCAL, 'PATTERN_BINDER', source=source, anchor=anchor)
        elif kind == 'NamedExpr':
            self.named_expression(occurrence)
        elif kind == 'ExceptHandler':
            self.tick(occurrence)
            self.visit_field(occurrence, 'type')
            source, anchor = self.source(occurrence, 'name', required=False)
            if source is not None:
                self.emit(self.source_name(source), LOCAL, 'EXCEPT_BINDER', source=source, anchor=anchor)
            self.visit_field(occurrence, 'body')
            return
        constructor = self.constructors[kind]
        if constructor.dispatch in ('ROOT', 'ORDERED_CHILDREN'):
            self.tick(occurrence)
            self.generic(occurrence)
        else:
            super().visit(occurrence)
        if kind in ('MatchMapping', 'MatchAs'):
            source, anchor = self.source(occurrence, 'rest' if kind == 'MatchMapping' else 'name', required=False)
            if source is not None:
                self.emit(self.source_name(source), LOCAL, 'PATTERN_BINDER', source=source, anchor=anchor)

    def collect(self):
        scopes = super().run()
        if (tuple(self.blocks) != self.accepted.blocks or scopes != self.accepted.scopes
                or tuple(self.rewrites) != self.accepted.rewrites):
            raise SymbolStop('COMPILER_TOPOLOGY_REPLAY_CHANGED', 'scalar visitor changed the accepted C3-T graph')
        sources = []
        for source, row in enumerate(self.declarations.contributions):
            events = tuple(self.source_events[source])
            if events:
                disposition = 'DETACHED_RAW' if row.analysis_visibility == 'DETACHED_FUTURE_ANNOTATION' else 'EMITTED'
            elif source in self.ignored:
                disposition = 'IGNORED_LOCAL_ANNOTATION'
            else:
                raise SymbolStop('SOURCE_CONTRIBUTION_UNDISPOSED', 'source contribution lacks a first-pass event or explicit suppression', source=source)
            sources.append(SourceDisposition(source, disposition, events))
        return RawCollection(tuple(RawSlot(block, name, flags, tuple(events)) for block, name, flags, events in self.raw_slots),
            tuple(self.events), tuple(sources), tuple(RawParameters(i, tuple(self.param_slots[i])) for i in range(len(self.blocks))),
            tuple(sorted(self.has_conditional)), self.symbol_steps)


def collect_symbols(syntax, roles, contexts, declarations, native, topology, *, limits: SymbolLimits) -> RawCollection:
    if type(limits) is not SymbolLimits:
        raise ValueError('raw compiler collection requires typed SymbolLimits')
    if topology.status == 'SOURCE_ONLY_MODE':
        return RawCollection((), (), tuple(SourceDisposition(i, 'GRAMMAR_ONLY', ())
            for i in range(len(declarations.contributions))), (), (), 0)
    if topology.status != 'PROJECTED' or declarations.status != 'DECLARED':
        raise SymbolStop('UPSTREAM_NOT_READY', 'raw symbol collection requires accepted source declarations and compiler topology')
    try:
        return _Collector(syntax, roles, contexts, declarations, native, topology, limits).collect()
    except TopologyStop as error:
        raise SymbolStop(error.frontier.code, error.frontier.detail, budget=error.budget) from error


__all__ = ['RAW_RULES', 'collect_symbols']
