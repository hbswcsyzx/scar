"""C2b namespace resolution from source ledgers; no native table or target execution."""
from __future__ import annotations
from collections import defaultdict
from dataclasses import replace
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis.source_declarations import read_source_declarations, _catalog as _declaration_catalog
from scar.analysis.source_contexts import SourceContextView
from scar.analysis.source_declaration_view import SourceDeclarationView
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.program.source_roles import SourceRolesMaterial, SlotRef
from scar.ir.program.source_contexts import SourceContextsMaterial
from scar.ir.program.source_bindings import (
    NameRef, BindingCatalog, BindingSlot, EnvironmentInterface, LookupStep, LookupPlan,
    ScopeNameResolution, PortResolution, ForwardHop, CaptureDemand, RootGlobalRequirement,
    ImplicitRequirement, BindingConflict, BindingFrontier, ScopeBindings,
    SourceBindingsInput, SourceBindingsProfile, SourceBindingsMaterial,
)
from scar.ir.record_codec import decode, encode

_VERSION = 'PYTHON_SOURCE_BINDINGS_C2B_V1'
_PHASE = 'SYMBOL_VISIT_PROJECTION'
_ROOT = frozenset(('ROOT_EXEC', 'ROOT_INTERACTIVE', 'ROOT_EVAL'))
_FUNCTION = frozenset(('FUNCTION', 'LAMBDA', 'COMPREHENSION', 'GENERATOR_EXPRESSION',
    'TYPE_PARAMETERS', 'ANNOTATION', 'TYPE_ALIAS', 'TYPE_PARAMETER_EVALUATOR'))
_ANNOTATION = frozenset(('TYPE_PARAMETERS', 'ANNOTATION', 'TYPE_ALIAS', 'TYPE_PARAMETER_EVALUATOR'))
_PROTOCOLS = ('__class__', '__classdict__', '__conditional_annotations__')
_INTERFACES = ('ROOT_LOCALS', 'ROOT_GLOBALS', 'ENV_GLOBALS', 'BUILTINS', 'LEXICAL_BINDING',
    'CLASS_PREPARED_MAPPING', 'CLASS_ANNOTATION_NAMESPACE', 'CLASS_PROTOCOL_CELL')
_RULES = ('OWN_GLOBAL', 'OWN_NONLOCAL', 'OWN_BOUND', 'ROOT_NAMESPACE', 'ROOT_DERIVED_GLOBAL',
    'ENCLOSING_BINDING', 'ENCLOSING_GLOBAL_BARRIER', 'IMPLICIT_GLOBAL',
    'CLASS_GLOBAL_ANNOTATION', 'CLASS_BOUND_ANNOTATION', 'CLASS_MAPPING_READ',
    'CLASS_FREE_MAPPING_READ', 'ANNOTATION_CLASS_MAPPING_READ', 'CLASS_CHILD_BYPASS',
    'TYPE_PARAMETER_NONLOCAL_FORBIDDEN', 'ESCAPED_WALRUS', 'ESCAPED_ROOT_WALRUS',
    'SUPER_CLASS_REQUIREMENT', 'CLASS_ANNOTATION_PROTOCOL', 'CLASS_PROTOCOL_BINDING',
    'DETACHED_TEMPLATE', 'IGNORED_ANNOTATION', 'TYPE_GRAMMAR', 'CAPTURE_PROPAGATION',
    'SOURCE_DECLARATION_CONFLICT', 'ESCAPED_WALRUS_HOME_CONFLICT', 'ESCAPED_WALRUS_GLOBAL',
    'ESCAPED_WALRUS_CAPTURE', 'NONLOCAL_AT_ROOT', 'NONLOCAL_BINDING_NOT_FOUND',
    'NONLOCAL_TYPE_PARAMETER_FORBIDDEN', 'NESTED_GLOBAL_DIRECTIVE',
    'CONDITIONAL_ANNOTATION_REQUIREMENT', 'SOURCE_ENVIRONMENT_INTERFACE_NOT_RUNTIME_OBJECT')
_CLASSIFICATIONS = ('LOCAL', 'CLASS_LOCAL', 'ROOT_LOCAL', 'FREE', 'GLOBAL_EXPLICIT',
    'GLOBAL_IMPLICIT', 'CONFLICT', 'NO_NAMESPACE')
_DISPOSITIONS = ('RESOLVED', 'CONFLICT', 'IGNORED_ANALYSIS', 'DETACHED_TEMPLATE', 'TYPE_GRAMMAR',
    'IMPORT_SPECIFICATION', 'NON_LEXICAL_LABEL', 'NO_BINDING_MARKER', 'WILDCARD_IMPORT', 'NON_BINDING_ANNOTATION')
_ACTIVATIONS = ('ELIGIBLE', 'SUPPRESSED', 'TEMPLATE_ONLY', 'TYPE_GRAMMAR')
_ACCESSES = ('READ', 'WRITE', 'DELETE', 'IMPLICIT_READ')
_DOMAINS = ('LOCAL_BINDING', 'TYPE_PARAMETER_BINDING', 'CLASS_PROTOCOL')
_MISSING = ('RAISE_NAME_ERROR', 'RAISE_UNBOUND_LOCAL', 'RAISE_UNBOUND_FREE')


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()


@lru_cache(maxsize=1)
def _catalog():
    decl = _declaration_catalog()
    payload = dict(rule_version=_VERSION, projection_phase=_PHASE,
        f2_schema_sha256=decl.f2_schema_sha256, context_catalog_sha256=decl.context_catalog_sha256,
        declaration_catalog_sha256=decl.content_sha256, rules=list(_RULES),
        interface_kinds=list(_INTERFACES), classifications=list(_CLASSIFICATIONS),
        port_dispositions=list(_DISPOSITIONS), activations=list(_ACTIVATIONS), capture_accesses=list(_ACCESSES),
        binding_domains=list(_DOMAINS), missing_outcomes=list(_MISSING), schema='scar.source-binding-catalog', schema_version=1)
    return BindingCatalog(_VERSION, _PHASE, decl.f2_schema_sha256, decl.context_catalog_sha256,
        decl.content_sha256, _RULES, _INTERFACES, _CLASSIFICATIONS, _DISPOSITIONS,
        _ACTIVATIONS, _ACCESSES, _DOMAINS, _MISSING, _digest(payload))


def source_binding_catalog() -> dict:
    return encode(_catalog())


class BindingBudgetExceeded(ValueError):
    def __init__(self, code, port, processed):
        self.frontier = BindingFrontier(code, port, processed,
            'namespace budget reached; no partial graph published')
        super().__init__(self.frontier.detail)


class _Resolver:
    def __init__(self, syntax, roles, contexts, declarations, limits):
        self.syntax, self.roles, self.contexts, self.decl, self.limits = syntax, roles, contexts, declarations, limits
        self.view = SourceContextView(syntax, roles, contexts)
        SourceDeclarationView(roles, contexts, declarations, contexts=self.view).verify()
        self.bindings, self.interfaces, self.plans, self.ports, self.resolutions = [], [], [], [], []
        self.captures, self.relays, self.root_globals, self.implicit, self.conflicts = [], [], [], [], []
        self.binding_keys, self.interface_keys, self.plan_keys, self.resolved = {}, {}, {}, {}
        self.capture_keys, self.hop_keys, self.conflict_keys, self.enclosing_cache = {}, {}, {}, {}
        self.flags, self.evidence, self.escapes = defaultdict(set), defaultdict(list), defaultdict(list)
        self.port_conflicts, self.name_conflicts, self.class_cache = defaultdict(list), defaultdict(list), {}
        self.pool = {row.value: i for i, row in enumerate(declarations.names)}
        self.root = next((i for i, scope in enumerate(contexts.scopes) if scope.parent is None), None)
        if self.root is None:
            raise ValueError('C2b requires the original C1 root scope')
        self.root_global_names, self.steps, self.search_steps, self.current = set(), 0, 0, None
        self.regions_by_owner = defaultdict(list)
        for region, row in enumerate(contexts.regions):
            self.regions_by_owner[row.owner].append(region)
        self.future_annotations = self._future_annotations()
        self._prepare()

    def limit(self, index, count, code):
        if count > self.limits[index]:
            raise BindingBudgetExceeded(code, self.current, len(self.ports))

    def search(self):
        self.limit(6, self.search_steps + 1, 'SEARCH_BUDGET')
        self.search_steps += 1

    def name(self, text):
        return NameRef('SOURCE', self.pool[text]) if text in self.pool else NameRef('LANGUAGE', symbol=text)

    def text(self, name):
        return self.decl.names[name.index].value if name.kind == 'SOURCE' else name.symbol

    def conflict(self, code, scope, text, ports, detail):
        ports = tuple(dict.fromkeys(ports))
        key = code, scope, text, ports
        if key not in self.conflict_keys:
            self.limit(7, len(self.conflicts) + 1, 'CONFLICT_BUDGET')
            index = len(self.conflicts)
            self.conflict_keys[key] = index
            self.conflicts.append(BindingConflict(code, scope, None if text is None else self.name(text), ports, detail))
            if text is not None:
                self.name_conflicts[scope, text].append(index)
            for port in ports:
                self.port_conflicts[port].append(index)
        return self.conflict_keys[key]

    @staticmethod
    def template_flags(row):
        ops = row.operations
        if 'GLOBAL_DIRECTIVE' in ops:
            return {'DEF_GLOBAL'}
        if 'NONLOCAL_DIRECTIVE' in ops:
            return {'DEF_NONLOCAL'}
        if 'PARAMETER_INTERFACE' in ops:
            return {'DEF_PARAM'}
        if 'TYPE_PARAMETER_INTERFACE' in ops:
            return {'DEF_LOCAL', 'DEF_TYPE_PARAM'}
        if 'DECLARE' in ops:
            return {'DEF_LOCAL'}
        return {'USE'} if 'USE_SYNTAX' in ops else set()

    def _future_annotations(self):
        # Same reviewed prefix rule as C2a, including literal-only annotations
        # that have no sparse B port. This reads syntax, never imports a module.
        fields = self.view.role_view
        root = self.syntax.nodes[self.syntax.root]
        if root.constructor not in ('Module', 'Interactive'):
            return False
        for i, item in enumerate(fields.field(self.syntax.root, 'body').items):
            node = self.syntax.nodes[item.reference]
            if i == 0 and node.constructor == 'Expr':
                value = fields.field(item.reference, 'value')
                if value.kind == 'NODE' and self.syntax.nodes[value.reference].constructor == 'Constant':
                    if type(fields.field(value.reference, 'value').scalar.to_python()) is str:
                        continue
            if node.constructor != 'ImportFrom':
                break
            module = fields.field(item.reference, 'module')
            if (module.kind != 'SCALAR' or module.scalar.to_python() != '__future__'
                    or fields.field(item.reference, 'level').scalar.to_python() != 0):
                break
            if any(fields.field(alias.reference, 'name').scalar.to_python() == 'annotations'
                    for alias in fields.field(item.reference, 'names').items):
                return True
        return False

    def annotation_ancestor(self, site):
        # The anchor can itself be the annotation slot, rather than a node
        # nested below it. Future does not detach type-parameter bound/default.
        fields = self.view.role_view
        while True:
            rule, _ = fields.locate(site)
            constructor = self.syntax.nodes[site.occurrence].constructor
            if (constructor, rule.name) in (('AnnAssign', 'annotation'), ('arg', 'annotation'),
                    ('FunctionDef', 'returns'), ('AsyncFunctionDef', 'returns')):
                return True
            site = fields.parents.get(site.occurrence)
            if site is None:
                return False

    def _prepare(self):
        for old in self.decl.conflicts:
            text = None if old.name is None else self.decl.names[old.name].value
            self.conflict(old.code, old.scope, text, old.ports, old.detail)
        roots = defaultdict(list)
        for row in self.decl.contributions:
            text, key = self.decl.names[row.name].value, (row.home, self.decl.names[row.name].value)
            self.evidence[key].append(row.port)
            if row.analysis_visibility == 'SYMBOL_VISIT':
                self.flags[key].update(row.visit_flags)
            elif row.analysis_visibility == 'DETACHED_FUTURE_ANNOTATION':
                self.flags[key].update(self.template_flags(row))
            if row.analysis_visibility == 'SYMBOL_VISIT' and 'DEF_GLOBAL' in row.visit_flags:
                roots[text, 'NESTED_GLOBAL_DIRECTIVE'].append(row.port)
            if row.reason == 'NAMED_EXPR_BINDING_SYNTAX' and row.source_scope != row.home:
                self.escapes[row.source_scope, text].append(row)
                if self.contexts.scopes[row.home].kind in _ROOT and row.analysis_visibility == 'SYMBOL_VISIT':
                    roots[text, 'ESCAPED_ROOT_WALRUS'].append(row.port)
        for (text, rule), ports in roots.items():
            self.root_global_names.add(text)
            self.root_globals.append(RootGlobalRequirement(self.name(text), tuple(dict.fromkeys(ports)), rule))

    def class_view(self, scope):
        if scope not in self.class_cache:
            current = self.contexts.scopes[scope]
            result = None
            if current.lookup_policy == 'ANNOTATION_CLASS_NAMESPACE_ALLOWED':
                parent = current.parent
                while parent is not None:
                    self.search()
                    item = self.contexts.scopes[parent]
                    if item.kind == 'CLASS':
                        result = parent
                        break
                    if item.kind not in _ANNOTATION:
                        raise ValueError('C1 class-visible annotation has no corresponding class ancestor')
                    parent = item.parent
                if result is None:
                    raise ValueError('C1 class-visible annotation lacks class namespace interface')
            self.class_cache[scope] = result
        return self.class_cache[scope]

    def binding(self, owner, text, domain='LOCAL_BINDING', evidence=()):
        if domain == 'LOCAL_BINDING' and 'DEF_TYPE_PARAM' in self.flags[owner, text]:
            domain = 'TYPE_PARAMETER_BINDING'
        key = domain, owner, text
        if key not in self.binding_keys:
            self.limit(0, len(self.bindings) + 1, 'BINDING_BUDGET')
            self.binding_keys[key] = len(self.bindings)
            self.bindings.append(BindingSlot(domain, owner, self.name(text), False,
                tuple(dict.fromkeys((*self.evidence[owner, text], *evidence)))))
        else:
            index = self.binding_keys[key]
            old = self.bindings[index]
            more = tuple(dict.fromkeys((*old.evidence, *evidence)))
            if more != old.evidence:
                self.bindings[index] = replace(old, evidence=more)
        return self.binding_keys[key]

    def enclosing(self, scope, text):
        key = scope, text
        if key in self.enclosing_cache:
            return self.enclosing_cache[key]
        parent = self.contexts.scopes[scope].parent
        path = []
        while parent is not None:
            self.search()
            path.append(parent)
            item, flags = self.contexts.scopes[parent], self.flags[parent, text]
            if item.kind == 'CLASS':
                if text in _PROTOCOLS:
                    result = 'BOUND', self.binding(parent, text, 'CLASS_PROTOCOL')
                    break
            elif item.kind in _ROOT or item.kind == 'TYPE_GRAMMAR':
                result = 'GLOBAL', None
                break
            elif item.kind in _FUNCTION:
                if 'DEF_GLOBAL' in flags:
                    result = 'GLOBAL_BARRIER', None
                    break
                if flags & {'DEF_LOCAL', 'DEF_PARAM', 'DEF_IMPORT'} and 'DEF_NONLOCAL' not in flags:
                    result = 'BOUND', self.binding(parent, text)
                    break
            else:
                raise ValueError('unreviewed C1 scope kind in enclosing-name search')
            parent = item.parent
        else:
            result = 'GLOBAL', None
        self.enclosing_cache[key] = result
        return result

    def resolve(self, scope, text):
        key = scope, text
        if key in self.resolved:
            return self.resolved[key]
        self.search()
        item, flags, binding = self.contexts.scopes[scope], self.flags[key], None
        evidence = tuple(dict.fromkeys(self.evidence[key]))
        if key in self.name_conflicts:
            classification, reason = 'CONFLICT', 'SOURCE_DECLARATION_CONFLICT'
        elif key in self.escapes:
            rows = self.escapes[key]
            home = rows[0].home
            if any(row.home != home for row in rows):
                raise ValueError('one origin walrus name has inconsistent source aggregation homes')
            target = self.resolutions[self.resolve(home, text)]
            evidence = tuple(row.port for row in rows)
            if target.classification == 'CONFLICT':
                classification, reason = 'CONFLICT', 'ESCAPED_WALRUS_HOME_CONFLICT'
            elif self.contexts.scopes[home].kind in _ROOT or target.classification in ('GLOBAL_EXPLICIT', 'GLOBAL_IMPLICIT'):
                classification, reason = 'GLOBAL_EXPLICIT', 'ESCAPED_WALRUS_GLOBAL'
            else:
                classification, reason, binding = 'FREE', 'ESCAPED_WALRUS_CAPTURE', target.binding
                if binding is None:
                    raise ValueError('escaped function walrus has no logical binding target')
        elif item.kind == 'TYPE_GRAMMAR':
            classification, reason = 'NO_NAMESPACE', 'TYPE_GRAMMAR'
        elif 'DEF_GLOBAL' in flags or (scope == self.root and text in self.root_global_names):
            classification, reason = 'GLOBAL_EXPLICIT', 'OWN_GLOBAL' if 'DEF_GLOBAL' in flags else 'ROOT_DERIVED_GLOBAL'
        elif 'DEF_NONLOCAL' in flags:
            found, binding = self.enclosing(scope, text)
            if item.kind in _ROOT:
                code = 'NONLOCAL_AT_ROOT'
            elif found != 'BOUND':
                code = 'NONLOCAL_BINDING_NOT_FOUND'
            elif self.bindings[binding].domain == 'TYPE_PARAMETER_BINDING':
                code = 'NONLOCAL_TYPE_PARAMETER_FORBIDDEN'
            else:
                code = None
            if code is not None:
                self.conflict(code, scope, text, evidence, 'nonlocal requires an enclosing non-type-parameter logical binding')
                classification, reason, binding = 'CONFLICT', code, None
            else:
                classification, reason = 'FREE', 'OWN_NONLOCAL'
        elif flags & {'DEF_LOCAL', 'DEF_PARAM', 'DEF_IMPORT'}:
            if item.kind in _ROOT:
                classification, reason = 'ROOT_LOCAL', 'ROOT_NAMESPACE'
            elif item.kind == 'CLASS':
                classification, reason = 'CLASS_LOCAL', 'OWN_BOUND'
            elif item.kind in _FUNCTION:
                classification, reason, binding = 'LOCAL', 'OWN_BOUND', self.binding(scope, text)
            else:
                raise ValueError('unreviewed local source namespace kind')
        else:
            class_owner = self.class_view(scope)
            class_flags = self.flags[class_owner, text] if class_owner is not None else set()
            if 'DEF_GLOBAL' in class_flags:
                classification, reason = 'GLOBAL_EXPLICIT', 'CLASS_GLOBAL_ANNOTATION'
            elif class_flags & {'DEF_LOCAL', 'DEF_PARAM', 'DEF_IMPORT'} and 'DEF_NONLOCAL' not in class_flags:
                classification, reason = 'GLOBAL_IMPLICIT', 'CLASS_BOUND_ANNOTATION'
            else:
                found, binding = self.enclosing(scope, text)
                if found == 'BOUND':
                    classification, reason = 'FREE', 'ENCLOSING_BINDING'
                else:
                    classification = 'GLOBAL_IMPLICIT'
                    reason = 'ENCLOSING_GLOBAL_BARRIER' if found == 'GLOBAL_BARRIER' else 'IMPLICIT_GLOBAL'
        index = len(self.resolutions)
        self.resolved[key] = index
        self.resolutions.append(ScopeNameResolution(scope, self.name(text), classification, binding, reason, evidence))
        return index

    def interface(self, kind, owner, binding=None):
        key = kind, owner, binding
        if key not in self.interface_keys:
            self.limit(1, len(self.interfaces) + 1, 'INTERFACE_BUDGET')
            self.interface_keys[key] = len(self.interfaces)
            self.interfaces.append(EnvironmentInterface(*key))
        return self.interface_keys[key]

    def binding_interface(self, binding):
        slot = self.bindings[binding]
        kind = 'CLASS_PROTOCOL_CELL' if slot.domain == 'CLASS_PROTOCOL' else 'LEXICAL_BINDING'
        return self.interface(kind, slot.owner, binding)

    def plan(self, interfaces, missing):
        steps = tuple(LookupStep(interface, on_miss=missing if i == len(interfaces) - 1 else 'NEXT')
            for i, interface in enumerate(interfaces))
        value = LookupPlan(steps, missing)
        if value not in self.plan_keys:
            self.limit(2, len(self.plans) + 1, 'PLAN_BUDGET')
            self.limit(3, self.steps + len(steps), 'PLAN_STEP_BUDGET')
            self.steps += len(steps)
            self.plan_keys[value] = len(self.plans)
            self.plans.append(value)
        return self.plan_keys[value]

    def global_interface(self, resolution):
        row = self.resolutions[resolution]
        # Escaping to a root is an explicit language route; other globals are
        # callable/environment references whose runtime identity is unobserved.
        routes = self.escapes.get((row.scope, self.text(row.name)), ())
        scope = self.root if routes and self.contexts.scopes[routes[0].home].kind in _ROOT else row.scope
        return self.interface('ROOT_GLOBALS' if scope == self.root else 'ENV_GLOBALS', scope)

    def read_plan(self, resolution):
        row = self.resolutions[resolution]
        item = self.contexts.scopes[row.scope]
        if row.classification in ('CONFLICT', 'NO_NAMESPACE'):
            return None
        if row.classification in ('LOCAL', 'FREE'):
            interfaces = [self.binding_interface(row.binding)]
            if row.classification == 'FREE':
                if item.kind == 'CLASS':
                    interfaces.insert(0, self.interface('CLASS_PREPARED_MAPPING', row.scope))
                elif self.class_view(row.scope) is not None:
                    interfaces.insert(0, self.interface('CLASS_ANNOTATION_NAMESPACE', self.class_view(row.scope)))
            return self.plan(interfaces, 'RAISE_UNBOUND_LOCAL' if row.classification == 'LOCAL' else 'RAISE_UNBOUND_FREE')
        interfaces = [self.global_interface(resolution), self.interface('BUILTINS', row.scope)]
        if row.classification != 'GLOBAL_EXPLICIT':
            if item.kind in _ROOT:
                interfaces.insert(0, self.interface('ROOT_LOCALS', self.root))
            elif item.kind == 'CLASS':
                interfaces.insert(0, self.interface('CLASS_PREPARED_MAPPING', row.scope))
            elif self.class_view(row.scope) is not None:
                interfaces.insert(0, self.interface('CLASS_ANNOTATION_NAMESPACE', self.class_view(row.scope)))
        return self.plan(interfaces, 'RAISE_NAME_ERROR')

    def target(self, resolution):
        row = self.resolutions[resolution]
        if row.classification in ('LOCAL', 'FREE'):
            return self.binding_interface(row.binding)
        if row.classification == 'CLASS_LOCAL':
            return self.interface('CLASS_PREPARED_MAPPING', row.scope)
        if row.classification == 'ROOT_LOCAL':
            return self.interface('ROOT_LOCALS', self.root)
        if row.classification in ('GLOBAL_EXPLICIT', 'GLOBAL_IMPLICIT'):
            return self.global_interface(resolution)
        return None

    def hop(self, scope, binding):
        owner = self.bindings[binding].owner
        path = []
        while scope != owner and (scope, binding) not in self.hop_keys:
            self.search()
            path.append(scope)
            scope = self.contexts.scopes[scope].parent
            if scope is None:
                raise ValueError('logical capture binding is not an original C1 ancestor')
        parent = self.hop_keys.get((scope, binding))
        for item in reversed(path):
            self.limit(5, len(self.relays) + 1, 'RELAY_BUDGET')
            self.hop_keys[item, binding] = len(self.relays)
            self.relays.append(ForwardHop(item, binding, parent))
            parent = len(self.relays) - 1
        return parent

    def capture(self, scope, binding, access, ports, activation):
        if binding is None or self.bindings[binding].owner == scope:
            return None
        key = scope, binding, access, activation
        if key not in self.capture_keys:
            self.limit(4, len(self.captures) + 1, 'CAPTURE_BUDGET')
            self.capture_keys[key] = len(self.captures)
            self.captures.append(CaptureDemand(scope, binding, access, tuple(dict.fromkeys(ports)),
                activation, self.hop(scope, binding)))
        else:
            index, old = self.capture_keys[key], self.captures[self.capture_keys[key]]
            self.captures[index] = replace(old, ports=tuple(dict.fromkeys((*old.ports, *ports))))
        if activation not in ('TEMPLATE_ONLY', 'TYPE_GRAMMAR'):
            slot = self.bindings[binding]
            self.bindings[binding] = replace(slot, cell_required=True)
        return self.capture_keys[key]

    def activation(self, region, visibility='SYMBOL_VISIT'):
        if visibility == 'DETACHED_FUTURE_ANNOTATION':
            return 'TEMPLATE_ONLY'
        if visibility == 'TYPE_GRAMMAR_ONLY':
            return 'TYPE_GRAMMAR'
        return self.contexts.regions[region].eligibility

    def _port(self, port, source):
        self.current = port
        name = None if source.name is None else NameRef('SOURCE', source.name)
        if source.contribution is None:
            state = self.view.context_for_port(port).state
            conflicts = tuple(self.port_conflicts[port])
            return PortResolution(port, 'CONFLICT' if conflicts else source.disposition,
                source.source_scope, source.source_scope, name, None, None, None, None, None,
                self.activation(state.region), 'NO_CONTRIBUTION', conflicts)
        index = source.contribution
        row = self.decl.contributions[index]
        activation = self.activation(row.region, row.analysis_visibility)
        text = self.decl.names[row.name].value
        if row.analysis_visibility in ('IGNORED_LOCAL_ANNOTATION', 'TYPE_GRAMMAR_ONLY'):
            disposition = 'IGNORED_ANALYSIS' if row.analysis_visibility == 'IGNORED_LOCAL_ANNOTATION' else 'TYPE_GRAMMAR'
            return PortResolution(port, disposition, row.source_scope, row.home, name, index,
                None, None, None, None, activation, row.analysis_visibility, tuple(self.port_conflicts[port]))
        scope = row.source_scope
        resolution = self.resolve(scope, text)
        resolved = self.resolutions[resolution]
        read = self.read_plan(resolution) if 'USE_SYNTAX' in row.operations else None
        write = self.target(resolution) if 'STORE_CANDIDATE' in row.operations else None
        delete = self.target(resolution) if 'DELETE_CANDIDATE' in row.operations else None
        if resolved.classification == 'FREE':
            for access, present in (('READ', read), ('WRITE', write), ('DELETE', delete)):
                if present is not None:
                    self.capture(scope, resolved.binding, access, (port,), activation)
        conflicts = tuple(dict.fromkeys((*self.port_conflicts[port], *self.name_conflicts[scope, text],
            *self.name_conflicts[row.home, text])))
        disposition = ('CONFLICT' if conflicts or resolved.classification == 'CONFLICT' else
            ('DETACHED_TEMPLATE' if row.analysis_visibility == 'DETACHED_FUTURE_ANNOTATION' else 'RESOLVED'))
        return PortResolution(port, disposition, scope, row.home, name, index, resolution,
            read, write, delete, activation, row.analysis_visibility, conflicts)

    def _creator_region(self, scope):
        item = self.contexts.scopes[scope]
        if item.kind not in _ROOT and item.kind != 'CLASS':
            raise ValueError('conditional annotation creator must be a class/root source scope')
        state = (self.contexts.root_context if item.anchor is None else
            self.view.context_at_slot(item.anchor).state)
        if state.environment != scope or state.owner != item.owner:
            raise ValueError('conditional annotation creator context belongs to another source scope/owner')
        original = self.contexts.regions[state.region]
        if original.owner != item.owner:
            raise ValueError('conditional annotation creator region belongs to another source owner')
        return state.region

    def _implicit(self):
        # This is a compiler language rule over a verified Name/Load, not a
        # call-name heuristic. An augmented assignment has no visitor USE.
        for row in self.decl.contributions:
            if (row.reason != 'REFERENCE_SYNTAX' or 'USE' not in row.visit_flags
                    or row.analysis_visibility != 'SYMBOL_VISIT'
                    or self.decl.names[row.name].value != 'super'
                    or self.contexts.scopes[row.source_scope].kind not in _FUNCTION):
                continue
            occurrence = row.site.occurrence
            if self.syntax.nodes[occurrence].constructor != 'Name':
                raise ValueError('REFERENCE_SYNTAX super port is not its original Name node')
            ctx = self.view.role_view.field(occurrence, 'ctx')
            if ctx.kind != 'NODE' or self.syntax.nodes[ctx.reference].constructor != 'Load':
                raise ValueError('super visitor USE is not its original Load context')
            resolution = self.resolve(row.source_scope, '__class__')
            value = self.resolutions[resolution]
            activation = self.activation(row.region, row.analysis_visibility)
            plan = self.read_plan(resolution)
            self.capture(row.source_scope, value.binding, 'IMPLICIT_READ', (row.port,), activation)
            self.implicit.append(ImplicitRequirement(row.source_scope, row.region, row.analysis_visibility,
                self.name('__class__'), 'SUPER_CLASS_REQUIREMENT', row.site, (row.port,), value.binding, resolution, plan, activation))
        # The class namespace transport is a hidden protocol requirement. It is
        # distinct from ordinary source lookups of a same-spelled mapping key.
        for scope, item in enumerate(self.contexts.scopes):
            owner = self.class_view(scope)
            if owner is None:
                continue
            binding = self.binding(owner, '__classdict__', 'CLASS_PROTOCOL')
            plan = self.plan((self.binding_interface(binding),), 'RAISE_UNBOUND_FREE')
            for region in self.regions_by_owner[item.owner]:
                raw = self.contexts.regions[region]
                if raw.anchor is None or self.view.context_at_slot(raw.anchor).state.environment != scope:
                    raise ValueError('class-visible evaluation region lacks its original source scope')
                visibility = ('DETACHED_FUTURE_ANNOTATION' if self.future_annotations
                    and self.annotation_ancestor(raw.anchor) else 'SYMBOL_VISIT')
                activation = self.activation(region, visibility)
                self.capture(scope, binding, 'IMPLICIT_READ', (), activation)
                self.implicit.append(ImplicitRequirement(scope, region, visibility, self.name('__classdict__'),
                    'CLASS_ANNOTATION_PROTOCOL', raw.anchor, (), binding, None, plan, activation))

    def run(self):
        # Resolve whole-scope declarations even when a directive has no read or
        # store consumer. Nonlocal validity cannot be skipped for unused names.
        for scope, summary in enumerate(self.decl.scopes):
            for name in summary.names:
                self.resolve(scope, self.decl.names[name].value)
        for port, source in enumerate(self.decl.ports):
            self.ports.append(self._port(port, source))
        self.current = None
        self._implicit()
        self._conditionals()
        resolutions, captures = defaultdict(list), defaultdict(list)
        for i, row in enumerate(self.resolutions):
            resolutions[row.scope].append(i)
        for i, row in enumerate(self.captures):
            captures[row.requester].append(i)
        return tuple(ScopeBindings(scope, tuple(resolutions[scope]), tuple(captures[scope]))
            for scope in range(len(self.contexts.scopes)))

    def _conditionals(self):
        conditional = {'For', 'AsyncFor', 'While', 'If', 'Match', 'Try', 'TryStar', 'With', 'AsyncWith'}
        seen = set()
        fields = self.view.role_view
        for occurrence, node in enumerate(self.syntax.nodes):
            if node.constructor != 'AnnAssign':
                continue
            anchor = SlotRef(occurrence, 'FIELD', fields.fields['AnnAssign']['annotation'])
            state = self.view.context_at_slot(anchor).state
            annotation = state.environment
            parent = self.contexts.scopes[annotation].parent
            if parent is None:
                raise ValueError('variable annotation scope has no source creator')
            creator = self.contexts.scopes[parent]
            if creator.kind == 'CLASS':
                current, enabled = occurrence, False
                while current != creator.owner.occurrence:
                    self.search()
                    edge = fields.parents.get(current)
                    if edge is None:
                        raise ValueError('class annotation lacks its original source ancestor')
                    if self.syntax.nodes[edge.occurrence].constructor in conditional:
                        enabled = True
                    current = edge.occurrence
                if not enabled:
                    continue
            elif creator.kind not in _ROOT:
                continue
            if (annotation, parent) in seen:
                continue
            seen.add((annotation, parent))
            creator_region = self._creator_region(parent)
            activation = self.activation(creator_region)
            name = self.name('__conditional_annotations__')
            if creator.kind == 'CLASS':
                binding = self.binding(parent, '__conditional_annotations__', 'CLASS_PROTOCOL')
                plan = self.plan((self.binding_interface(binding),), 'RAISE_UNBOUND_FREE')
            else:
                binding = None
                plan = self.plan((self.interface('ROOT_GLOBALS', parent),
                    self.interface('BUILTINS', parent)), 'RAISE_NAME_ERROR')
                self.root_globals.append(RootGlobalRequirement(name, (), 'CONDITIONAL_ANNOTATION_REQUIREMENT'))
            self.implicit.append(ImplicitRequirement(parent, creator_region, 'SYMBOL_VISIT', name,
                'CONDITIONAL_ANNOTATION_REQUIREMENT', anchor, (), binding, None, plan, activation))


def _profile():
    from scar.ir.program import source_bindings as bindings_ir
    from scar.analysis import source_binding_view as bindings_view
    catalog = _catalog()
    implementation = _digest({name: sha256(Path(path).read_bytes()).hexdigest() for name, path in (
        ('analysis', __file__), ('view', bindings_view.__file__), ('ir', bindings_ir.__file__))})
    return SourceBindingsProfile(_VERSION, _PHASE, catalog.f2_schema_sha256,
        catalog.context_catalog_sha256, catalog.declaration_catalog_sha256,
        catalog.content_sha256, implementation)


def _derive(f0, f1, f2, f3b, c1, c2a, limits):
    if any(type(n) is not int or n < 0 for n in limits):
        raise ValueError('namespace budgets must be exact nonnegative integers')
    declarations = read_source_declarations(c2a, f0, f1, f2, f3b, c1)
    syntax, roles, contexts = (decode(SourceSyntaxMaterial, f2), decode(SourceRolesMaterial, f3b),
        decode(SourceContextsMaterial, c1))
    inputs = SourceBindingsInput(*(_digest(doc) for doc in (f0, f1, f2, f3b, c1, c2a)),
        f0['path'], syntax.mode, declarations.status, len(roles.ports), len(contexts.scopes))
    profile = _profile()
    base = dict(input=inputs, profile=profile, **dict(zip((
        'max_bindings', 'max_interfaces', 'max_plans', 'max_plan_steps', 'max_captures',
        'max_relays', 'max_search_steps', 'max_conflicts'), limits)))
    empty = dict(bindings=(), interfaces=(), plans=(), ports=(), resolutions=(), scopes=(),
        captures=(), relays=(), root_globals=(), implicit=(), conflicts=(), frontiers=(), search_steps=0)
    if declarations.status != 'DECLARED':
        return SourceBindingsMaterial(**base, status='UPSTREAM_NOT_DECLARED', **empty)
    try:
        resolver = _Resolver(syntax, roles, contexts, declarations, limits)
        scopes = resolver.run()
    except BindingBudgetExceeded as error:
        empty['frontiers'] = (error.frontier,)
        return SourceBindingsMaterial(**base, status='BUDGET_STOPPED', **empty)
    material = SourceBindingsMaterial(**base,
        status='RESOLVED_WITH_CONFLICTS' if resolver.conflicts else 'RESOLVED',
        bindings=tuple(resolver.bindings), interfaces=tuple(resolver.interfaces),
        plans=tuple(resolver.plans), ports=tuple(resolver.ports), resolutions=tuple(resolver.resolutions),
        scopes=scopes, captures=tuple(resolver.captures), relays=tuple(resolver.relays),
        root_globals=tuple(resolver.root_globals), implicit=tuple(resolver.implicit),
        conflicts=tuple(resolver.conflicts), frontiers=(), search_steps=resolver.search_steps)
    from scar.analysis.source_binding_view import SourceBindingView
    SourceBindingView(roles, contexts, declarations, material, contexts=resolver.view).verify()
    return material


def source_bindings_document(f0, f1, f2, f3b, c1, c2a, *, max_bindings=1_000_000,
        max_interfaces=1_000_000, max_plans=1_000_000, max_plan_steps=4_000_000,
        max_captures=2_000_000, max_relays=2_000_000, max_search_steps=10_000_000,
        max_conflicts=100_000) -> dict:
    return encode(_derive(f0, f1, f2, f3b, c1, c2a, (max_bindings, max_interfaces,
        max_plans, max_plan_steps, max_captures, max_relays, max_search_steps, max_conflicts)))


def read_source_bindings(document, f0, f1, f2, f3b, c1, c2a) -> SourceBindingsMaterial:
    material = decode(SourceBindingsMaterial, document)
    if material.profile != _profile():
        raise ValueError('C2b namespace implementation/catalog profile mismatch')
    fresh = _derive(f0, f1, f2, f3b, c1, c2a, (material.max_bindings, material.max_interfaces,
        material.max_plans, material.max_plan_steps, material.max_captures, material.max_relays,
        material.max_search_steps, material.max_conflicts))
    if material != fresh:
        raise ValueError('C2b namespace plans differ from original C1 contexts/C2a source declarations')
    return material


from scar.analysis.source_binding_view import SourceBindingView

__all__ = ['source_binding_catalog', 'source_bindings_document', 'read_source_bindings', 'SourceBindingView']
