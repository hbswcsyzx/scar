"""F3-D: compose original source/namespace/compiler references, without copying IR.

These queries describe a static compiler correspondence. In particular a
KEEP_PARENT route is an association, not a causal input to the parent's flags.
Use the strict document reader to establish language-rule correctness; direct
typed construction only checks references and the declared composition rules.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass

from scar.analysis.compiler_symbol_view import CompilerSymbolView
from scar.analysis.source_binding_view import SourceBindingView
from scar.ir.program.source_roles import SlotRef, SourceRolesMaterial
from scar.ir.program.source_contexts import SourceContextsMaterial
from scar.ir.program.source_declarations import SourceDeclarationsMaterial
from scar.ir.program.source_symbols import SourceSymbolsMaterial
from scar.ir.program.compiler_topology import CompilerTopologyMaterial
from scar.ir.record_codec import decode


class FrontendError(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(code + ': ' + detail)


def _require(condition, detail):
    if not condition:
        raise FrontendError('REFERENCE_CONTRADICTION', detail)


def _index(index, size):
    if type(index) is not int or not 0 <= index < size:
        raise FrontendError('QUERY_ARGUMENT', 'expected an original table ordinal')
    return index


@dataclass(frozen=True, slots=True)
class SourcePortPath:
    port: int
    site: SlotRef
    source_scope: int
    region: int
    declaration: int | None
    namespace: int
    compiler_state: str
    raw_events: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ImplicitPath:
    requirement: int | None
    block: int | None
    raw_event: int | None
    rule: str
    outcome: str


@dataclass(frozen=True, slots=True)
class CompilerEndpoint:
    raw_event: int
    slot: int
    native_scope: int
    ordinal: int
    transforms: tuple[int, ...]
    association: bool
    parameter_ordinal: int | None = None


@dataclass(frozen=True, slots=True)
class ProjectionBoundary:
    raw_event: int | None
    slot: int | None
    reason: str


@dataclass(frozen=True, slots=True)
class ProjectionFrontier:
    raw_event: int | None
    slot: int | None
    transforms: tuple[int, ...]
    reason: str
    remaining: int = 1


@dataclass(frozen=True, slots=True)
class EndpointQuery:
    endpoints: tuple[CompilerEndpoint, ...]
    boundaries: tuple[ProjectionBoundary, ...]
    frontier: tuple[ProjectionFrontier, ...]
    complete: bool
    steps: int


_IMPLICIT = {
    'SUPER_CLASS_REQUIREMENT': ('SUPER_CLASS_USE', '__class__'),
    'CLASS_ANNOTATION_PROTOCOL': ('CLASSDICT_USE', '__classdict__'),
    'CONDITIONAL_ANNOTATION_REQUIREMENT': ('CONDITIONAL_ANNOTATION_USE', '__conditional_annotations__'),
}
_TRANSFORMS = ('COPY', 'KEEP_PARENT', 'SKIP_PARAM', 'DELETE_MAGIC')


def frontend_binding_contract():
    """Closed rule domains; observed counts are deliberately not language rules."""
    return dict(schema='scar.frontend-binding-contract', schema_version=1,
        rule_version='F3D_ORIGINAL_REFERENCE_COMPOSITION_V1',
        source_routes=('DIRECT', 'WALRUS_HOME', 'GLOBAL_ECHO'),
        implicit_rules=tuple(_IMPLICIT), compiler_only_rules=(
            'COMPILER_ONLY_HEADER_CLASSDICT_USE', 'COMPILER_ONLY_DETACHED_SUPER_USE'),
        transforms=_TRANSFORMS, source_dispositions=('EMITTED', 'DETACHED_RAW',
            'IGNORED_LOCAL_ANNOTATION', 'GRAMMAR_ONLY'),
        slot_dispositions=('PUBLIC', 'INLINED', 'DETACHED', 'DELETED'),
        runtime_binding='NOT_OBSERVED', optimization_legality='NOT_CLAIMED')


class FrontendBindingView:
    """Unit-local lazy graph view. All returned ordinals belong to parent tables."""

    def __init__(self, roles, contexts, declarations, bindings, native, topology, symbols):
        if (bindings.status not in ('RESOLVED', 'RESOLVED_WITH_CONFLICTS')
                or symbols.status not in ('PROJECTED', 'SOURCE_ONLY_MODE')
                or topology.status not in ('PROJECTED', 'SOURCE_ONLY_MODE')):
            raise FrontendError('UPSTREAM_NOT_ACCEPTED', 'no complete source/compiler inputs')
        self.roles, self.contexts, self.declarations = roles, contexts, declarations
        self.bindings, self.native, self.topology, self.symbols = bindings, native, topology, symbols
        self.namespace = SourceBindingView(roles, contexts, declarations, bindings)
        self.compiler = CompilerSymbolView(declarations, topology, native, symbols)
        self._summary = None
        self._outgoing, self._markers = defaultdict(list), defaultdict(list)
        self._native, self._parameters = {}, {}
        self._implicit, self._synthetic = (), ()

    def _ready(self):
        if self._summary is None:
            self.verify()

    def _verify_implicit(self):
        q, s, t = self.bindings, self.symbols, self.topology
        events = defaultdict(list)
        for index, event in enumerate(s.contributions):
            if event.rule in ('SUPER_CLASS_USE', 'CLASSDICT_USE', 'CONDITIONAL_ANNOTATION_USE'):
                _require(s.slots[event.slot].block == event.context_block and event.flags & 16,
                    'implicit USE changed its original compiler block or base flag')
                events[event.context_block, event.rule].append(index)
        used, paths, counts = Counter(), [], Counter()
        creators = set()
        for index, demand in enumerate(q.implicit):
            _require(demand.rule in _IMPLICIT, 'undeclared implicit requirement rule')
            raw_rule, name = _IMPLICIT[demand.rule]
            projection = t.scopes[demand.scope]
            block = projection.block
            if s.status == 'SOURCE_ONLY_MODE':
                _require(block is None, 'grammar-only source acquired a compiler block')
                # Grammar-only material cannot claim a compiler event.
                paths.append(ImplicitPath(index, None, None, demand.rule, 'GRAMMAR_ONLY'))
                counts['IMPLICIT_GRAMMAR_ONLY'] += 1
                continue
            _require(block is not None and t.blocks[block].source_scope == demand.scope,
                'implicit requirement lost its original source scope projection')
            template = t.blocks[block]
            _require(self.namespace.name(demand.name) == name, 'implicit requirement name differs')
            options = events[block, raw_rule]
            if demand.rule == 'CLASS_ANNOTATION_PROTOCOL' and not template.can_see_class_scope:
                current, detached = block, False
                while current is not None:
                    detached |= t.blocks[current].attachment == 'FUTURE_DETACHED'
                    current = t.blocks[current].parent
                _require(demand.analysis_visibility == 'DETACHED_FUTURE_ANNOTATION'
                    and demand.activation == 'TEMPLATE_ONLY' and detached and not options,
                    'class namespace omission lacks its complete future-stringization rule')
                paths.append(ImplicitPath(index, block, None, demand.rule, 'OMITTED_FUTURE_STRINGIZATION'))
                counts['IMPLICIT_FUTURE_OMISSION'] += 1
                continue
            if demand.rule == 'CLASS_ANNOTATION_PROTOCOL':
                _require(template.can_see_class_scope, 'class annotation block lost class namespace access')
                matches = options
            else:
                _require(demand.analysis_visibility == 'SYMBOL_VISIT' and demand.anchor is not None,
                    'implicit source event lost its active original anchor')
                matches = [event for event in options if s.contributions[event].anchor == demand.anchor]
                if demand.rule == 'SUPER_CLASS_REQUIREMENT':
                    _require(len(demand.cause_ports) == 1, 'super protocol lost its original load port')
                    port = q.ports[demand.cause_ports[0]]
                    _require(port.source_scope == demand.scope, 'super protocol load moved source scope')
                else:
                    _require(block not in creators and len(options) == 1,
                        'conditional annotation creator is not a singleton')
                    creators.add(block)
            _require(len(matches) == 1, 'implicit requirement has missing or ambiguous compiler events')
            event = matches[0]
            _require(self.compiler.name(s.slots[s.contributions[event].slot].name) == name,
                'implicit event compiler name differs')
            used[event] += 1
            if demand.rule != 'CLASS_ANNOTATION_PROTOCOL':
                _require(used[event] == 1, 'singleton implicit event reused by another source demand')
            paths.append(ImplicitPath(index, block, event, demand.rule, 'MATCHED'))
            counts[demand.rule] += 1
        synthetic, detached_loads = [], None
        for (block, rule), indices in events.items():
            for event in indices:
                if used[event]:
                    continue
                template = t.blocks[block]
                if rule == 'SUPER_CLASS_USE':
                    # A future-stringized annotation retains the compiler's
                    # raw visit of a nested lambda but no active source-side
                    # super demand. Join to its original load, not a fake
                    # active implicit port.
                    if detached_loads is None:
                        detached_loads = defaultdict(list)
                        for load_id, load in enumerate(s.contributions):
                            if load.rule == 'NAME_LOAD' and load.source is not None:
                                source = self.declarations.contributions[load.source]
                                if source.analysis_visibility == 'DETACHED_FUTURE_ANNOTATION':
                                    detached_loads[load.context_block, load.anchor].append(load_id)
                    matches = detached_loads[block, s.contributions[event].anchor]
                    _require(len(matches) == 1, 'detached super event lacks a unique original source load')
                    source = self.declarations.contributions[s.contributions[matches[0]].source]
                    port = q.ports[source.port]
                    current, detached = block, False
                    while current is not None:
                        detached |= t.blocks[current].attachment == 'FUTURE_DETACHED'
                        current = t.blocks[current].parent
                    _require(detached and self.declarations.names[source.name].value == 'super'
                        and source.source_scope == template.source_scope
                        and port.analysis_visibility == 'DETACHED_FUTURE_ANNOTATION'
                        and port.activation == 'TEMPLATE_ONLY'
                        and self.compiler.name(s.slots[s.contributions[event].slot].name) == '__class__',
                        'unmatched super event lacks the detached compiler protocol rule')
                    synthetic.append(ImplicitPath(None, block, event, 'COMPILER_ONLY_DETACHED_SUPER_USE',
                        'DETACHED_COMPILER_PROTOCOL'))
                    counts['COMPILER_ONLY_DETACHED_SUPER_USE'] += 1
                    continue
                _require(rule == 'CLASSDICT_USE' and len(indices) == 1
                    and template.origin.role == 'HEADER_ANNOTATIONS' and template.source_scope is None
                    and template.can_see_class_scope,
                    'uncovered implicit event has no source or synthetic header origin')
                _require(self.compiler.name(s.slots[s.contributions[event].slot].name) == '__classdict__',
                    'synthetic header class namespace event has a different name')
                synthetic.append(ImplicitPath(None, block, event, 'COMPILER_ONLY_HEADER_CLASSDICT_USE',
                    'COMPILER_ONLY_HEADER'))
                counts['COMPILER_ONLY_HEADER_CLASSDICT_USE'] += 1
        self._implicit, self._synthetic = tuple(paths), tuple(synthetic)
        return counts

    def verify(self):
        if self._summary is not None:
            return {**self._summary, 'rule_counts': dict(self._summary['rule_counts'])}
        self.namespace.verify()
        self.compiler.verify()
        b, d, q, t, s = self.roles, self.declarations, self.bindings, self.topology, self.symbols
        _require(len(b.ports) == len(d.ports) == len(q.ports), 'original port domains differ')
        counts = Counter()
        for index, (port, declaration, namespace) in enumerate(zip(b.ports, d.ports, q.ports)):
            _require(declaration.port == namespace.port == index, 'original port ordinal changed')
            if declaration.contribution is None:
                _require(namespace.declref is None and namespace.home == declaration.source_scope
                    and namespace.disposition == declaration.disposition
                    and namespace.analysis_visibility == 'NO_CONTRIBUTION'
                    and all(value is None for value in (namespace.resolution, namespace.read_plan,
                        namespace.write_target, namespace.delete_target)),
                    'non-contributing source port gained a fabricated binding or consumer')
                counts['NO_CONTRIBUTION'] += 1
            else:
                source = d.contributions[declaration.contribution]
                _require(source.port == index and source.site == port.site
                    and source.source_scope == declaration.source_scope and source.region == declaration.region
                    and source.name == declaration.name, 'source contribution lost its original site/port')
                counts[s.sources[declaration.contribution].disposition] += 1
        inverse = [[] for _ in d.contributions]
        for index, event in enumerate(s.contributions):
            if event.source is None:
                continue
            source = d.contributions[event.source]
            inverse[event.source].append(index)
            _require(event.anchor == source.site and t.blocks[event.context_block].source_scope == source.source_scope
                and self.compiler.name(s.slots[event.slot].name) == d.names[source.name].value,
                'compiler contribution lost original source context/key/anchor')
            target_scope = t.blocks[s.slots[event.slot].block].source_scope
            if event.rule == 'GLOBAL_ECHO':
                _require(event.derived_from is not None and event.derived_from < index,
                    'global echo lacks a prior causal event')
                cause = s.contributions[event.derived_from]
                _require(cause.source == event.source and cause.flags & 1
                    and s.slots[cause.slot].name == s.slots[event.slot].name
                    and target_scope is not None and self.contexts.scopes[target_scope].parent is None,
                    'global echo does not reference the same source/global root')
                counts['SOURCE_GLOBAL_ECHO'] += 1
            elif event.rule == 'WALRUS_HOME_BINDING':
                _require(source.reason == 'NAMED_EXPR_BINDING_SYNTAX' and target_scope == source.home,
                    'walrus compiler binding lost its declared home')
                counts['SOURCE_WALRUS_HOME'] += 1
            else:
                _require(target_scope == source.source_scope, 'direct contribution changed source scope')
                counts['SOURCE_DIRECT'] += 1
        _require(len(s.sources) == len(inverse), 'compiler source disposition domain differs')
        for index, source in enumerate(s.sources):
            _require(source.source == index and source.contributions == tuple(inverse[index]),
                'compiler source/raw inverse edges differ')
        outgoing, markers = defaultdict(list), defaultdict(list)
        for index, transform in enumerate(s.transforms):
            source = s.slots[transform.source_slot]
            origin = t.blocks[source.block]
            _require(transform.rule in _TRANSFORMS and origin.projection == 'INLINED',
                'compiler transform has an undeclared rule or non-inline origin')
            value = s.facts[transform.input_fact]
            if transform.rule in ('COPY', 'KEEP_PARENT'):
                _require(transform.target_slot is not None and transform.output_fact is not None,
                    'compiler projection lost its target/output')
                target = s.slots[transform.target_slot]
                output = s.facts[transform.output_fact]
                _require(target.block == origin.parent and target.name == source.name
                    and output.slot == transform.target_slot,
                    'compiler projection does not follow its original parent/name')
                if transform.rule == 'COPY':
                    _require(target.initial_fact is None and output.rule == 'INLINE_COPY'
                        and output.inputs == (transform.input_fact,), 'COPY lost its original fact provenance')
                outgoing[transform.source_slot].append(index)
            else:
                _require(transform.target_slot is None, 'compiler terminal transform gained a target')
                if transform.rule == 'SKIP_PARAM':
                    _require(self.compiler.name(source.name) == '.0' and value.low_flags & 4
                        and transform.output_fact is None, 'SKIP_PARAM is not the original inline parameter')
                else:
                    output = s.facts[transform.output_fact]
                    _require(source.disposition == 'DELETED' and output.slot == transform.source_slot
                        and output.rule == 'DELETE_MAGIC' and output.inputs == (transform.input_fact,)
                        and (output.low_flags, output.scope_code) == (value.low_flags, value.scope_code),
                        'DELETE_MAGIC lost its deletion fact')
                markers[transform.source_slot].append(index)
            counts[transform.rule] += 1
        self._outgoing, self._markers = dict(outgoing), dict(markers)
        self._native = {row.slot: (row.native_scope, row.ordinal) for row in s.symbols}
        self._parameters = {row.slot: (row.native_scope, row.ordinal) for row in s.parameters}
        _require(len(self._native) == len(s.symbols)
            and set(self._native) == {i for i, slot in enumerate(s.slots) if slot.disposition == 'PUBLIC'},
            'public compiler/native symbol reverse projection is not one-to-one')
        _require(len(self._parameters) == len(s.parameters) and set(self._parameters) <= set(self._native),
            'native parameter projection is not an ordered subset of original public symbols')
        counts.update(self._verify_implicit())
        # Each inline symbol has exactly one parent projection, or one skip
        # marker. Deletion may coexist with its earlier parent projection.
        for index, slot in enumerate(s.slots):
            _require(len(self._outgoing.get(index, ())) <= 1 and len(self._markers.get(index, ())) <= 1,
                'inline symbol has duplicated projection or terminal rules')
            if slot.disposition == 'INLINED':
                _require(index in self._outgoing or index in self._markers,
                    'inline compiler slot has no projection or parameter boundary')
        # Memoized validation of sparse routes is linear, even for deep source
        # nesting. No transitive closure is copied per original source port.
        finished = set()
        for start in self._outgoing:
            slot, seen = start, set()
            while slot not in finished:
                _require(slot not in seen, 'compiler projection closure repeats a slot')
                seen.add(slot)
                if slot in self._outgoing:
                    slot = s.transforms[self._outgoing[slot][0]].target_slot
                else:
                    _require(s.slots[slot].disposition in ('PUBLIC', 'DETACHED', 'DELETED')
                        or slot in self._markers, 'inline projection route has no declared boundary')
                    break
            finished.update(seen)
        self._summary = dict(ports=len(b.ports), sources=len(d.contributions), raw_events=len(s.contributions),
            slots=len(s.slots), facts=len(s.facts), transforms=len(s.transforms), native_symbols=len(s.symbols),
            parameters=len(s.parameters), implicit=len(q.implicit),
            implicit_matches=sum(path.outcome == 'MATCHED' for path in self._implicit),
            implicit_omissions=sum(path.outcome == 'OMITTED_FUTURE_STRINGIZATION' for path in self._implicit),
            synthetic_implicit=len(self._synthetic), conflicts=len(q.conflicts),
            source_only=s.status == 'SOURCE_ONLY_MODE', rule_counts=dict(sorted(counts.items())))
        return self.verify()

    def port(self, index):
        self._ready()
        row = self.declarations.ports[_index(index, len(self.roles.ports))]
        source = None if row.contribution is None else self.symbols.sources[row.contribution]
        return SourcePortPath(index, self.roles.ports[index].site, row.source_scope, row.region,
            row.contribution, index, 'NO_CONTRIBUTION' if source is None else source.disposition,
            () if source is None else source.contributions)

    def implicit(self, index):
        self._ready()
        return self._implicit[_index(index, len(self._implicit))]

    def compiler_only_implicit(self):
        self._ready()
        return self._synthetic

    def why(self, native_scope, ordinal, *, max_facts=100_000):
        self._ready()
        return self.compiler.why(native_scope, ordinal, max_facts=max_facts)

    def parameter(self, native_scope, ordinal):
        """Original ordered parameter projection; not a runtime locals layout."""
        self._ready()
        return self.compiler.parameter(native_scope, ordinal)

    def endpoints(self, index, *, max_steps=100_000, max_results=10_000):
        path = self.port(index)
        if any(type(n) is not int or n < 0 for n in (max_steps, max_results)):
            raise FrontendError('QUERY_ARGUMENT', 'query budgets must be nonnegative exact integers')
        if not path.raw_events:
            if max_results == 0:
                return EndpointQuery((), (), (ProjectionFrontier(None, None, (), 'RESULT_BUDGET'),), False, 0)
            return EndpointQuery((), (ProjectionBoundary(None, None, path.compiler_state),), (), True, 0)
        endpoints, boundaries, steps, next_source = [], [], 0, 0
        event, slot, route, association = None, None, [], False
        while slot is not None or next_source < len(path.raw_events):
            if steps >= max_steps or len(endpoints) + len(boundaries) >= max_results:
                reason = 'STEP_BUDGET' if steps >= max_steps else 'RESULT_BUDGET'
                # One bounded frontier identifies the next original reference
                # and the number of pending source starts. Rerun with a larger
                # budget to expand; never copy an unbounded pending list.
                remaining = len(path.raw_events) - next_source + (slot is not None)
                if slot is None:
                    event = path.raw_events[next_source]
                    slot, route = self.symbols.contributions[event].slot, []
                frontier = (ProjectionFrontier(event, slot, tuple(route), reason, remaining),)
                return EndpointQuery(tuple(endpoints), tuple(boundaries), frontier, False, steps)
            if slot is None:
                event = path.raw_events[next_source]
                next_source += 1
                slot, route, association = self.symbols.contributions[event].slot, [], False
            steps += 1
            current = self.symbols.slots[slot]
            if slot in self._native:
                scope, ordinal = self._native[slot]
                parameter = self._parameters.get(slot)
                endpoints.append(CompilerEndpoint(event, slot, scope, ordinal, tuple(route), association,
                    None if parameter is None else parameter[1]))
                slot = None
            else:
                # DELETE is an annotation on this source slot, not termination
                # of the COPY/KEEP routes emitted before its deletion.
                if current.disposition == 'DELETED':
                    boundaries.append(ProjectionBoundary(event, slot, 'DELETED'))
                elif current.disposition == 'DETACHED':
                    boundaries.append(ProjectionBoundary(event, slot, 'DETACHED_TEMPLATE'))
                for marker in self._markers.get(slot, ()):
                    if self.symbols.transforms[marker].rule == 'SKIP_PARAM':
                        boundaries.append(ProjectionBoundary(event, slot, 'SKIP_PARAM'))
                _require(current.disposition in ('DELETED', 'DETACHED') or slot in self._markers
                    or slot in self._outgoing, 'query route has no compiler endpoint or declared boundary')
                outgoing = self._outgoing.get(slot)
                if outgoing:
                    transform = outgoing[0]
                    row = self.symbols.transforms[transform]
                    route.append(transform)
                    association |= row.rule == 'KEEP_PARENT'
                    slot = row.target_slot
                else:
                    slot = None
        return EndpointQuery(tuple(endpoints), tuple(boundaries), (), True, steps)


def read_frontend_bindings(f0, f1, f2, roles, contexts, declarations, bindings, native, topology, symbols):
    """Recompute accepted parents before exposing compositional query edges."""
    from scar.analysis.source_bindings import read_source_bindings
    from scar.analysis.compiler_symbols import read_compiler_symbols
    q = read_source_bindings(bindings, f0, f1, f2, roles, contexts, declarations)
    s = read_compiler_symbols(symbols, f0, f1, f2, roles, contexts, declarations, native, topology)
    b, c, d, a, t = (decode(cls, doc) for cls, doc in (
        (SourceRolesMaterial, roles), (SourceContextsMaterial, contexts),
        (SourceDeclarationsMaterial, declarations), (SourceSymbolsMaterial, native),
        (CompilerTopologyMaterial, topology)))
    view = FrontendBindingView(b, c, d, q, a, t, s)
    view.verify()
    return view
