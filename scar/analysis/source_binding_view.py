"""C2b reference queries over source namespace templates, never runtime dicts.

Fresh readers establish the language-rule result. This view separately checks
the graph's original references, inverse edges and shared capture forwarding.
"""
from hashlib import sha256
import json

from scar.ir.program.source_bindings import NameRef, SourceBindingsMaterial
from scar.ir.program.source_contexts import SourceContextsMaterial
from scar.ir.program.source_declarations import SourceDeclarationsMaterial
from scar.ir.program.source_roles import SourceRolesMaterial
from scar.ir.record_codec import encode


def _digest(document):
    return sha256(json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()


def _index(index, size, label):
    if type(index) is not int or not 0 <= index < size:
        raise ValueError('C2b ' + label + ' reference is outside its original table')
    return index


_VISIBILITY = frozenset(('SYMBOL_VISIT', 'IGNORED_LOCAL_ANNOTATION',
    'DETACHED_FUTURE_ANNOTATION', 'TYPE_GRAMMAR_ONLY', 'NO_CONTRIBUTION'))
_PROTOCOLS = frozenset(('__class__', '__classdict__', '__conditional_annotations__'))


class SourceBindingView:
    """All integer IDs are unit-local; interfaces describe source parameters."""

    def __init__(self, roles, c1, declarations, material, *, contexts=None):
        from scar.analysis.source_bindings import _catalog
        if (type(roles) is not SourceRolesMaterial or roles.status != 'CLASSIFIED'
                or type(c1) is not SourceContextsMaterial or c1.status != 'CONTEXTUALIZED'
                or type(declarations) is not SourceDeclarationsMaterial or declarations.status != 'DECLARED'
                or type(material) is not SourceBindingsMaterial
                or material.status not in ('RESOLVED', 'RESOLVED_WITH_CONFLICTS')):
            raise ValueError('C2b queries require classified/contextualized/declared/resolved inputs')
        self.roles, self.contexts, self.declarations = roles, c1, declarations
        self.material, self.context_view, self.catalog = material, contexts, _catalog()
        basis, previous = material.input, declarations.input
        if (basis.port_count != len(roles.ports) or basis.scope_count != len(c1.scopes)
                or basis.c2a_status != declarations.status
                or basis.c2a_document_sha256 != _digest(encode(declarations))
                or basis.c1_document_sha256 != _digest(encode(c1))
                or basis.f3b_document_sha256 != _digest(encode(roles))
                or any(getattr(basis, field) != getattr(previous, field)
                    for field in ('f0_document_sha256', 'f1_document_sha256', 'f2_document_sha256',
                        'f3b_document_sha256', 'c1_document_sha256', 'path', 'mode'))
                or material.profile.binding_catalog_sha256 != self.catalog.content_sha256
                or material.profile.context_catalog_sha256 != c1.profile.context_catalog_sha256
                or material.profile.declaration_catalog_sha256 != declarations.profile.declaration_catalog_sha256
                or material.profile.projection_phase != 'SYMBOL_VISIT_PROJECTION'):
            raise ValueError('C2b source receipts/catalogs differ from its original B/C1/C2a inputs')
        if contexts is not None and (contexts.roles != roles or contexts.material != c1):
            raise ValueError('C2b context view belongs to another original source unit')
        self._source_names = {row.value for row in declarations.names}

    def name(self, reference):
        if type(reference) is not NameRef:
            raise ValueError('C2b name must be a typed source/language reference')
        if reference.kind == 'SOURCE':
            return self.declarations.names[_index(reference.index, len(self.declarations.names), 'source name')].value
        if reference.symbol not in _PROTOCOLS or reference.symbol in self._source_names:
            raise ValueError('C2b language name is not canonical against the source-name pool')
        return reference.symbol

    def port(self, index):
        return self.material.ports[_index(index, len(self.material.ports), 'port')]

    def scope(self, index):
        return self.material.scopes[_index(index, len(self.material.scopes), 'scope')]

    def binding(self, index):
        return self.material.bindings[_index(index, len(self.material.bindings), 'binding')]

    def interface(self, index):
        return self.material.interfaces[_index(index, len(self.material.interfaces), 'interface')]

    def plan(self, index):
        return self.material.plans[_index(index, len(self.material.plans), 'plan')]

    def resolution(self, index):
        return self.material.resolutions[_index(index, len(self.material.resolutions), 'resolution')]

    def capture(self, index):
        return self.material.captures[_index(index, len(self.material.captures), 'capture')]

    def relay(self, index):
        return self.material.relays[_index(index, len(self.material.relays), 'relay')]

    def _source_scope(self, index):
        return self.contexts.scopes[_index(index, len(self.contexts.scopes), 'source scope')]

    def _region(self, index):
        return self.contexts.regions[_index(index, len(self.contexts.regions), 'region')]

    def _ports(self, ports):
        if len(set(ports)) != len(ports):
            raise ValueError('C2b source-port evidence is duplicated')
        for index in ports:
            self.port(index)

    def verify(self):
        data = self.material
        if (tuple(row.port for row in data.ports) != tuple(range(len(self.roles.ports)))
                or tuple(row.scope for row in data.scopes) != tuple(range(len(self.contexts.scopes)))):
            raise ValueError('C2b does not cover original B ports/C1 scopes exactly once in order')
        slots = set()
        for row in data.bindings:
            owner, name = self._source_scope(row.owner), self.name(row.name)
            key = row.domain, row.owner, name
            if (row.domain not in self.catalog.binding_domains
                    or type(row.cell_required) is not bool or key in slots
                    or row.domain == 'CLASS_PROTOCOL' and (owner.kind != 'CLASS' or name not in _PROTOCOLS)
                    or row.domain == 'TYPE_PARAMETER_BINDING' and owner.kind != 'TYPE_PARAMETERS'):
                raise ValueError('C2b binding slot has an invalid domain, owner or duplicate key')
            slots.add(key)
            self._ports(row.evidence)
        interfaces = set()
        for row in data.interfaces:
            owner = self._source_scope(row.owner)
            key = row.kind, row.owner, row.binding
            if row.kind not in self.catalog.interface_kinds or key in interfaces:
                raise ValueError('C2b namespace interface is undeclared or duplicated')
            interfaces.add(key)
            if row.kind in ('LEXICAL_BINDING', 'CLASS_PROTOCOL_CELL'):
                slot = self.binding(row.binding)
                if (slot.owner != row.owner
                        or (row.kind == 'CLASS_PROTOCOL_CELL') != (slot.domain == 'CLASS_PROTOCOL')):
                    raise ValueError('C2b binding interface does not reference its source provider')
            elif row.binding is not None:
                raise ValueError('C2b namespace mapping cannot masquerade as a lexical binding slot')
            if (row.kind in ('CLASS_PREPARED_MAPPING', 'CLASS_ANNOTATION_NAMESPACE') and owner.kind != 'CLASS'
                    or row.kind in ('ROOT_LOCALS', 'ROOT_GLOBALS') and owner.parent is not None
                    or row.kind == 'ENV_GLOBALS' and owner.parent is None):
                raise ValueError('C2b namespace interface owner is not its declared source domain')
        plans = set()
        for row in data.plans:
            if not row.steps or row.missing_outcome not in self.catalog.missing_outcomes or row in plans:
                raise ValueError('C2b lookup plan is empty, duplicated or has an undeclared missing outcome')
            plans.add(row)
            for index, step in enumerate(row.steps):
                self.interface(step.interface)
                expected = row.missing_outcome if index == len(row.steps) - 1 else 'NEXT'
                if step.on_hit != 'RETURN_VALUE' or step.on_miss != expected or step.on_exception != 'PROPAGATE':
                    raise ValueError('C2b lookup fallback/exception protocol is not closed')
        resolved, by_scope = set(), [[] for _ in self.contexts.scopes]
        for index, row in enumerate(data.resolutions):
            self._source_scope(row.scope)
            name = self.name(row.name)
            key = row.scope, name
            if key in resolved or row.classification not in self.catalog.classifications or row.reason not in self.catalog.rules:
                raise ValueError('C2b scope/name resolution has a duplicate key or undeclared rule/classification')
            resolved.add(key)
            by_scope[row.scope].append(index)
            if row.classification in ('LOCAL', 'FREE'):
                slot = self.binding(row.binding)
                if self.name(slot.name) != name or (slot.owner == row.scope) != (row.classification == 'LOCAL'):
                    raise ValueError('C2b local/free resolution does not refer to the named source provider')
            elif row.binding is not None:
                raise ValueError('C2b non-lexical namespace resolution cannot claim a local binding slot')
            self._ports(row.evidence)
        for index, row in enumerate(data.ports):
            source = self.declarations.ports[index]
            self._source_scope(row.source_scope)
            self._source_scope(row.home)
            contribution = None if source.contribution is None else self.declarations.contributions[source.contribution]
            expected_home = source.source_scope if contribution is None else contribution.home
            expected_name = None if source.name is None else NameRef('SOURCE', source.name)
            if ((row.source_scope, row.home, row.name, row.declref)
                    != (source.source_scope, expected_home, expected_name, source.contribution)
                    or row.disposition not in self.catalog.port_dispositions or row.activation not in self.catalog.activations
                    or row.analysis_visibility not in _VISIBILITY):
                raise ValueError('C2b port loses its original C2a scope/home/name/contribution or has an undeclared disposition')
            if row.name is not None:
                self.name(row.name)
            if row.resolution is not None:
                resolution = self.resolution(row.resolution)
                if resolution.scope != row.source_scope or resolution.name != row.name:
                    raise ValueError('C2b port resolution belongs to a different original scope/name')
            if row.read_plan is not None:
                self.plan(row.read_plan)
                if row.resolution is None:
                    raise ValueError('C2b read plan lacks its original scope/name resolution')
            for target in (row.write_target, row.delete_target):
                if target is not None:
                    self.interface(target)
                    if row.resolution is None:
                        raise ValueError('C2b write/delete target lacks its original resolution')
            for conflict in row.conflicts:
                _index(conflict, len(data.conflicts), 'conflict')
            if len(set(row.conflicts)) != len(row.conflicts):
                raise ValueError('C2b port conflict references are duplicated')
            if contribution is not None and row.analysis_visibility != contribution.analysis_visibility:
                raise ValueError('C2b port changed C2a analysis participation')
        # Each relay edge follows one original C1 parent edge. Iterative colors
        # additionally reject a cycle without expanding a path for every port.
        relay_keys = set()
        for row in data.relays:
            source, slot = self._source_scope(row.scope), self.binding(row.binding)
            key = row.scope, row.binding
            if key in relay_keys or row.scope == slot.owner:
                raise ValueError('C2b relay duplicates a shared hop or forwards inside its owner')
            relay_keys.add(key)
            if row.parent is None:
                if source.parent != slot.owner:
                    raise ValueError('C2b relay terminates before reaching its source provider')
            else:
                parent = self.relay(row.parent)
                if parent.scope != source.parent or parent.binding != row.binding:
                    raise ValueError('C2b relay does not follow an original source parent edge')
        finished = set()
        for index in range(len(data.relays)):
            current, active = index, set()
            while current is not None and current not in finished:
                if current in active:
                    raise ValueError('C2b capture forwarding contains a cycle')
                active.add(current)
                current = data.relays[current].parent
            finished.update(active)
        captures, scope_captures = set(), [[] for _ in self.contexts.scopes]
        for index, row in enumerate(data.captures):
            self._source_scope(row.requester)
            slot = self.binding(row.binding)
            key = row.requester, row.binding, row.access, row.activation
            if (key in captures or row.access not in self.catalog.capture_accesses
                    or row.activation not in self.catalog.activations):
                raise ValueError('C2b capture demand is duplicated or has an undeclared access/activation')
            captures.add(key)
            self._ports(row.ports)
            scope_captures[row.requester].append(index)
            if row.requester == slot.owner:
                if row.hop is not None:
                    raise ValueError('C2b same-owner demand cannot claim a forwarding path')
            else:
                hop = self.relay(row.hop)
                if hop.scope != row.requester or hop.binding != row.binding:
                    raise ValueError('C2b capture does not start at its requesting source scope')
            if row.activation not in ('TEMPLATE_ONLY', 'TYPE_GRAMMAR') and not slot.cell_required:
                raise ValueError('C2b active capture lacks a source cell requirement')
        for row in data.scopes:
            if row.resolutions != tuple(by_scope[row.scope]) or row.captures != tuple(scope_captures[row.scope]):
                raise ValueError('C2b scope resolution/capture inverse edges are incomplete or reordered')
        root_globals = set()
        for row in data.root_globals:
            key = self.name(row.name), row.rule
            if key in root_globals or row.rule not in self.catalog.rules:
                raise ValueError('C2b root-global requirement is duplicated or lacks a declared source rule')
            root_globals.add(key)
            self._ports(row.ports)
        for row in data.implicit:
            self._source_scope(row.scope)
            region = self._region(row.region)
            name = self.name(row.name)
            if (name not in _PROTOCOLS or row.rule not in self.catalog.rules
                    or row.activation not in self.catalog.activations
                    or row.analysis_visibility not in ('SYMBOL_VISIT', 'DETACHED_FUTURE_ANNOTATION')
                    or row.activation != ('TEMPLATE_ONLY' if row.analysis_visibility == 'DETACHED_FUTURE_ANNOTATION'
                        else region.eligibility)):
                raise ValueError('C2b implicit requirement lacks its closed language protocol/rule')
            self._ports(row.cause_ports)
            if row.anchor is not None:
                if self.context_view is not None:
                    context = self.context_view.context_at_slot(row.anchor).state
                    if row.rule == 'CONDITIONAL_ANNOTATION_REQUIREMENT':
                        creator = self.contexts.scopes[context.environment].parent
                        if creator != row.scope or row.analysis_visibility != 'SYMBOL_VISIT':
                            raise ValueError('C2b conditional protocol must reference its original annotation creator')
                        source = self.contexts.scopes[creator]
                        creator_region = (self.contexts.root_context.region if source.anchor is None
                            else self.context_view.context_at_slot(source.anchor).state.region)
                        if row.region != creator_region:
                            raise ValueError('C2b conditional protocol loses its creator evaluation region')
                    elif (context.environment, context.region) != (row.scope, row.region):
                        raise ValueError('C2b implicit requirement loses its original region/environment')
                    if (row.rule == 'CLASS_ANNOTATION_PROTOCOL'
                            and (region.anchor != row.anchor or region.owner != self.contexts.scopes[row.scope].owner)):
                        raise ValueError('C2b class annotation protocol must keep each original region owner/anchor')
            elif not row.cause_ports:
                raise ValueError('C2b implicit requirement lacks original source evidence')
            if row.binding is not None:
                if self.name(self.binding(row.binding).name) != name:
                    raise ValueError('C2b implicit binding uses a different protocol name')
            if row.resolution is not None:
                resolution = self.resolution(row.resolution)
                if resolution.scope != row.scope or resolution.name != row.name:
                    raise ValueError('C2b implicit requirement resolution belongs to another source scope/name')
            if row.read_plan is not None:
                self.plan(row.read_plan)
        for row in data.conflicts:
            self._source_scope(row.scope)
            if row.name is not None:
                self.name(row.name)
            self._ports(row.ports)
        return {key: len(getattr(data, key)) for key in ('ports', 'scopes', 'bindings',
            'interfaces', 'plans', 'resolutions', 'captures', 'relays', 'root_globals', 'implicit', 'conflicts')}


__all__ = ['SourceBindingView']
