"""Sparse C1 context queries over original, unchanged F2 parent slots.

This view checks record references and total query coverage. Source semantics
are granted by the fresh C1 reader; constructing a view is not that proof.
"""
from dataclasses import replace
from hashlib import sha256
import json

from scar.analysis.source_roles import SyntaxRoleView, _state
from scar.ir.program.source_contexts import ContextResolution, ContextState, OwnerRef, SourceContextsMaterial
from scar.ir.program.source_roles import RolePort, SlotRef, SourceRolesMaterial
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.record_codec import encode


def _digest(document):
    return sha256(json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()


def _index(value, size, label):
    if type(value) is not int or not 0 <= value < size:
        raise ValueError('C1 ' + label + ' reference is outside its original table')
    return value


def _acyclic(rows, root, label):
    """Validate a single-root parent forest iteratively, independent of ID order."""
    if [i for i, row in enumerate(rows) if row.parent is None] != [root]:
        raise ValueError('C1 ' + label + ' has a different or additional root')
    done = {root}
    for start in range(len(rows)):
        pending, active, current = [], set(), start
        while current not in done:
            if current in active:
                raise ValueError('cyclic C1 ' + label + ' parent relation')
            active.add(current)
            pending.append(current)
            current = _index(rows[current].parent, len(rows), label + ' parent')
        done.update(pending)


class SourceContextView:
    """One reusable parent index and sparse boundary map per source unit."""

    def __init__(self, syntax, roles, material):
        from scar.analysis.source_contexts import _catalog
        if (type(syntax) is not SourceSyntaxMaterial or syntax.status != 'PARSED'
                or type(roles) is not SourceRolesMaterial or roles.status != 'CLASSIFIED'
                or type(material) is not SourceContextsMaterial or material.status != 'CONTEXTUALIZED'):
            raise ValueError('context queries require typed PARSED/CLASSIFIED/CONTEXTUALIZED materials')
        self.syntax, self.roles, self.material = syntax, roles, material
        self.role_view, self.catalog = SyntaxRoleView(syntax), _catalog()
        if (material.profile.context_catalog_sha256 != self.catalog.content_sha256
                or material.profile.role_catalog_sha256 != self.role_view.catalog.content_sha256
                or material.profile.f2_schema_sha256 != self.role_view.catalog.f2_schema_sha256
                or material.input.f2_document_sha256 != _digest(encode(syntax))
                or material.input.f3b_document_sha256 != _digest(encode(roles))
                or roles.input.f2_document_sha256 != material.input.f2_document_sha256):
            raise ValueError('C1 references a different original syntax/role material or catalog')
        root = syntax.root
        parents = self.role_view.parents
        if root in parents or len(parents) != len(syntax.nodes) - 1:
            raise ValueError('C1 requires one original F2 occurrence root')
        # F2 normally grants this invariant; reject disconnected cycles even
        # for direct typed/synthetic callers before querying parent chains.
        seen, children = set(), {}
        for child, site in parents.items():
            children.setdefault(site.occurrence, []).append(child)
        pending = [root]
        while pending:
            occurrence = pending.pop()
            if occurrence in seen:
                raise ValueError('cyclic original F2 parent relation')
            seen.add(occurrence)
            pending.extend(children.get(occurrence, ()))
        if len(seen) != len(syntax.nodes):
            raise ValueError('disconnected original F2 occurrence graph')
        for scope in material.scopes:
            self._owner(scope.owner)
            self._anchor(scope.anchor)
        for region in material.regions:
            self._owner(region.owner)
            self._anchor(region.anchor)
            self._anchor(region.suppression_origin)
        for private in material.private_contexts:
            if private.class_owner is not None:
                self._owner(private.class_owner)
                if syntax.nodes[private.class_owner.occurrence].constructor != 'ClassDef':
                    raise ValueError('C1 private context owner is not an original class declaration')
            if private.parameter_group is not None:
                group = self.scope(private.parameter_group)
                if group.kind != 'TYPE_PARAMETERS':
                    raise ValueError('C1 selective private policy does not reference a type-parameter scope')
        self._state(material.root_context)
        _acyclic(material.scopes, material.root_context.environment, 'scope')
        _acyclic(material.regions, material.root_context.region, 'region')
        for region in material.regions:
            if region.parent is not None:
                parent = self.region(region.parent)
                if parent.eligibility == 'SUPPRESSED' and (
                        region.eligibility != 'SUPPRESSED'
                        or region.suppression_reason != parent.suppression_reason
                        or region.suppression_origin != parent.suppression_origin):
                    raise ValueError('C1 child region cancels or changes ancestor suppression')
        self._boundaries = {}
        counts = [0] * 484
        for boundary in material.boundaries:
            rule, _ = self.role_view.locate(boundary.site)
            self._state(boundary.state)
            expected = self.catalog.rules[rule.rule]
            if boundary.selector != expected.selector or boundary.content_policy != expected.content_policy:
                raise ValueError('C1 boundary differs from its shared field rule')
            key = (boundary.site.occurrence, boundary.site.group, boundary.site.ordinal)
            entries = self._boundaries.setdefault(key, {})
            if boundary.site.item_path in entries:
                raise ValueError('duplicate or conflicting C1 boundary prefix')
            entries[boundary.site.item_path] = boundary.state
            counts[rule.rule] += 1
        if counts != [row.boundaries for row in material.counts]:
            raise ValueError('C1 boundary references disagree with rule coverage')
        self._incoming = {root: material.root_context}
        self._ports = None

    def _owner(self, owner):
        if type(owner) is not OwnerRef:
            raise TypeError('C1 needs a typed static owner')
        _index(owner.occurrence, len(self.syntax.nodes), 'owner occurrence')

    def _anchor(self, site):
        if site is not None:
            self.role_view.locate(site)

    def _state(self, state):
        if type(state) is not ContextState:
            raise TypeError('C1 needs a typed context state')
        self._owner(state.owner)
        self.scope(state.environment)
        self.region(state.region)
        self.private_context(state.private_context)

    def scope(self, index):
        return self.material.scopes[_index(index, len(self.material.scopes), 'scope')]

    def region(self, index):
        return self.material.regions[_index(index, len(self.material.regions), 'region')]

    def private_context(self, index):
        return self.material.private_contexts[_index(index, len(self.material.private_contexts), 'private')]

    def _at(self, site, incoming):
        rule, _ = self.role_view.locate(site)
        transfer = self.catalog.rules[rule.rule]
        # Declaration qualifiers belong to a target edge. Receiver/index
        # expressions start a child context; scalar name payloads retain it.
        if transfer.content_policy == 'CHILD_ROUTING' and incoming.declaration_route != 'CURRENT_ENV':
            incoming = replace(incoming, declaration_route='CURRENT_ENV')
        entries = self._boundaries.get((site.occurrence, site.group, site.ordinal), {})
        path = site.item_path
        for depth in range(len(path), -1, -1):
            if path[:depth] in entries:
                return entries[path[:depth]]
        return incoming

    def entry_context(self, occurrence):
        _index(occurrence, len(self.syntax.nodes), 'occurrence')
        chain, current = [], occurrence
        while current not in self._incoming:
            edge = self.role_view.parents[current]
            chain.append((current, edge))
            current = edge.occurrence
        for child, edge in reversed(chain):
            self._incoming[child] = self._at(edge, self._incoming[edge.occurrence])
        return self._incoming[occurrence]

    def context_at_slot(self, site):
        rule, value = self.role_view.locate(site)
        transfer = self.catalog.rules[rule.rule]
        state = self._at(site, self.entry_context(site.occurrence))
        return ContextResolution(site, _state(value), transfer.selector, transfer.content_policy, state)

    resolve = context_at_slot

    def context_for_port(self, index):
        return self.context_at_slot(self.roles.ports[_index(index, len(self.roles.ports), 'role port')].site)

    def port_context(self, port):
        if type(port) is int:
            return self.context_for_port(port)
        if type(port) is not RolePort:
            raise TypeError('C1 role query needs an original RolePort or its exact ordinal')
        if self._ports is None:
            self._ports = frozenset(self.roles.ports)
        if port not in self._ports:
            raise ValueError('C1 role query is not an original port of this material')
        return self.context_at_slot(port.site)

    def verify_totality(self):
        """Stream every declared slot and original role port; retain no results."""
        counts = [[0] * 5 for _ in self.catalog.rules]
        for occurrence, node in enumerate(self.syntax.nodes):
            for group, values in (('FIELD', node.fields), ('ATTRIBUTE', node.attributes)):
                for ordinal, value in enumerate(values):
                    site = SlotRef(occurrence, group, ordinal)
                    answer = self.context_at_slot(site)
                    self._state(answer.state)
                    rule, _ = self.role_view.locate(site)
                    row = counts[rule.rule]
                    row[0] += 1
                    row[{'ABSENT': 1, 'NONE': 2, 'EMPTY_LIST': 3, 'VALUES': 4}[answer.slot_state]] += 1
        expected = [[c.slots, c.absent, c.none, c.empty_list, c.values] for c in self.material.counts]
        if counts != expected:
            raise ValueError('C1 total slot queries differ from their independent coverage counters')
        for index, port in enumerate(self.roles.ports):
            rule, _ = self.role_view.locate(port.site)
            if port.rule != rule.rule:
                raise ValueError('C1 role port does not reference its original field rule')
            self._state(self.context_for_port(index).state)
        return {'slots': sum(row[0] for row in counts), 'ports': len(self.roles.ports)}


__all__ = ['SourceContextView']
