"""C2a queries and reference checks over original B ports and C1 scopes.

This view validates a source ledger. Fresh readers grant its semantic evidence;
no query here returns a runtime namespace, value, cell object or storage address.
"""
from hashlib import sha256
import json

from scar.ir.program.source_declarations import SourceDeclarationsMaterial
from scar.ir.program.source_contexts import SourceContextsMaterial
from scar.ir.program.source_roles import SourceRolesMaterial
from scar.ir.record_codec import encode


def _digest(document):
    return sha256(json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()


def _index(index, size, label):
    if type(index) is not int or not 0 <= index < size:
        raise ValueError('C2a ' + label + ' reference is outside its original table')
    return index


class SourceDeclarationView:
    """One source-unit ledger; all public integer references are material-local."""

    def __init__(self, roles, c1, material, *, contexts=None):
        from scar.analysis.source_declarations import _catalog
        if (type(roles) is not SourceRolesMaterial or roles.status != 'CLASSIFIED'
                or type(c1) is not SourceContextsMaterial or c1.status != 'CONTEXTUALIZED'
                or type(material) is not SourceDeclarationsMaterial or material.status != 'DECLARED'):
            raise ValueError('C2a queries require typed classified/contextualized/declared inputs')
        self.roles, self.contexts, self.material, self.context_view = roles, c1, material, contexts
        self.catalog = _catalog()
        if (material.input.port_count != len(roles.ports)
                or material.input.f3b_document_sha256 != _digest(encode(roles))
                or material.input.c1_document_sha256 != _digest(encode(c1))
                or c1.input.f3b_document_sha256 != material.input.f3b_document_sha256
                or material.input.f2_document_sha256 != c1.input.f2_document_sha256
                or material.profile.role_catalog_sha256 != roles.profile.catalog_sha256
                or material.profile.context_catalog_sha256 != c1.profile.context_catalog_sha256
                or material.profile.declaration_catalog_sha256 != self.catalog.content_sha256):
            raise ValueError('C2a source receipts or shared catalogs differ from B/C1')
        if contexts is not None and (contexts.roles != roles or contexts.material != c1):
            raise ValueError('C2a query context belongs to a different original source unit')
        if len(material.scopes) != len(c1.scopes) or tuple(s.scope for s in material.scopes) != tuple(range(len(c1.scopes))):
            raise ValueError('C2a scope ledger does not cover every original C1 scope exactly once')
        if len({name.value for name in material.names}) != len(material.names):
            raise ValueError('C2a effective names are not uniquely interned')

    def port(self, index):
        return self.material.ports[_index(index, len(self.material.ports), 'port')]

    def scope(self, index):
        return self.material.scopes[_index(index, len(self.material.scopes), 'scope')]

    def contribution(self, index):
        return self.material.contributions[_index(index, len(self.material.contributions), 'contribution')]

    def name(self, index):
        return self.material.names[_index(index, len(self.material.names), 'name')]

    def _source_scope(self, index):
        return self.contexts.scopes[_index(index, len(self.contexts.scopes), 'source scope')]

    def _region(self, index):
        return self.contexts.regions[_index(index, len(self.contexts.regions), 'region')]

    def verify(self):
        """Check source references, all port dispositions and inverse scope edges."""
        data = self.material
        operations, visit_flags = set(self.catalog.operations), set(self.catalog.visit_flags)
        mentioned, named_order, contribution_refs = set(), [], []
        for index, row in enumerate(data.ports):
            if type(row.port) is not int or row.port != index:
                raise ValueError('C2a port dispositions must cover the original B order exactly once')
            self._source_scope(row.source_scope)
            self._region(row.region)
            projection = row.projection
            if projection.phase != 'SYMBOL_VISIT_PROJECTION' or projection.private_mode not in ('NONE', 'ALL', 'SELECTIVE'):
                raise ValueError('C2a projection has an undeclared phase or private-name policy')
            if row.name is not None:
                self.name(row.name)
                if row.name not in mentioned:
                    mentioned.add(row.name)
                    named_order.append(row.name)
                if projection.private_mode == 'SELECTIVE':
                    self._source_scope(projection.parameter_group)
                    if type(projection.prefix_count) is not int or projection.prefix_count < 0:
                        raise ValueError('C2a selective projection requires an original parameter prefix')
            if self.context_view is not None:
                context = self.context_view.context_for_port(index).state
                if (row.source_scope, row.region) != (context.environment, context.region):
                    raise ValueError('C2a port does not reference its original C1 environment/region')
                if row.name is not None:
                    private = self.context_view.private_context(context.private_context)
                    if (projection.value_rule != self.roles.ports[index].projection
                            or (projection.private_mode, projection.class_owner, projection.parameter_group)
                            != (private.mode, private.class_owner, private.parameter_group)):
                        raise ValueError('C2a name projection does not preserve its original B/C1 inputs')
                    if projection.private_mode == 'SELECTIVE':
                        group = self._source_scope(projection.parameter_group)
                        _, parameters = self.context_view.role_view.locate(group.anchor)
                        if parameters.kind != 'LIST' or projection.prefix_count > len(parameters.items):
                            raise ValueError('C2a selective prefix lies outside its original parameter group')
            if row.contribution is not None:
                contribution = self.contribution(row.contribution)
                if (contribution.port != index or contribution.name != row.name
                        or contribution.source_scope != row.source_scope or contribution.region != row.region):
                    raise ValueError('C2a port contribution does not round-trip to its source disposition')
                contribution_refs.append(row.contribution)
        if named_order != list(range(len(data.names))):
            raise ValueError('C2a name pool differs from first-port mentions')
        if sorted(contribution_refs) != list(range(len(data.contributions))):
            raise ValueError('C2a contribution references are duplicated, missing or unowned')
        by_scope = [[] for _ in self.contexts.scopes]
        for index, contribution in enumerate(data.contributions):
            _index(contribution.port, len(self.roles.ports), 'source port')
            source = self.roles.ports[contribution.port]
            if contribution.site != source.site:
                raise ValueError('C2a contribution does not reference its original B slot')
            self._source_scope(contribution.source_scope)
            self._source_scope(contribution.home)
            self._region(contribution.region)
            self.name(contribution.name)
            if (any(op not in operations for op in contribution.operations)
                    or any(flag not in visit_flags for flag in contribution.visit_flags)
                    or len(set(contribution.operations)) != len(contribution.operations)
                    or len(set(contribution.visit_flags)) != len(contribution.visit_flags)):
                raise ValueError('C2a contribution contains undeclared or duplicate operations/flags')
            by_scope[contribution.home].append(index)
        wildcard_refs = []
        for scope in data.scopes:
            expected = tuple(sorted(by_scope[scope.scope], key=lambda i: data.contributions[i].port))
            if scope.contributions != expected:
                raise ValueError('C2a scope contribution edges are incomplete or reordered')
            names = tuple(dict.fromkeys(data.contributions[i].name for i in expected))
            if scope.names != names:
                raise ValueError('C2a scope names differ from its original contribution order')
            for index in scope.directives:
                contribution = self.contribution(index)
                if index not in expected or not any(op in ('GLOBAL_DIRECTIVE', 'NONLOCAL_DIRECTIVE') for op in contribution.operations):
                    raise ValueError('C2a directive is not an original directive contribution of its scope')
            expected_directives = tuple(i for i in expected if any(op in ('GLOBAL_DIRECTIVE', 'NONLOCAL_DIRECTIVE') for op in data.contributions[i].operations))
            if scope.directives != expected_directives:
                raise ValueError('C2a whole-scope directive summary is incomplete')
            if len(set(scope.wildcards)) != len(scope.wildcards):
                raise ValueError('C2a namespace wildcard is duplicated')
            for index in scope.wildcards:
                row = self.port(index)
                if self.roles.ports[index].role != 'IMPORT_WILDCARD_SPEC' or row.source_scope != scope.scope or row.name is not None:
                    raise ValueError('C2a wildcard is not the original star import of its scope')
                wildcard_refs.append(index)
        expected_wildcards = [i for i, port in enumerate(self.roles.ports) if port.role == 'IMPORT_WILDCARD_SPEC']
        if sorted(wildcard_refs) != expected_wildcards:
            raise ValueError('C2a namespace wildcard coverage differs from original B')
        for conflict in data.conflicts:
            self._source_scope(conflict.scope)
            if conflict.name is not None:
                self.name(conflict.name)
            if not conflict.ports:
                raise ValueError('C2a conflict requires original source-port evidence')
            for index in conflict.ports:
                self.port(index)
        return {'ports': len(data.ports), 'contributions': len(data.contributions),
            'scopes': len(data.scopes), 'names': len(data.names), 'conflicts': len(data.conflicts)}


__all__ = ['SourceDeclarationView']
