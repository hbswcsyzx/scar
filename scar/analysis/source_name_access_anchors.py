"""Anchor original name facts to sealed F4 access operations and entries.

This is a unit-local material projection, without relation-table scans or a
solver. Scope selection does not enter bodies. Original logical fact URIs are
retained; the separate fact-material routing layer resolves collection URIs.
"""
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis.source_graph_material import source_graph_material
from scar.analysis.source_namespace_interfaces import extract_namespace_interfaces
from scar.analysis.source_productions import _digest
from scar.analysis.source_reference_slice import ReferenceSlicer, source_port
from scar.analysis.static_query import _Fragments
from scar.ir.program import normal_graph as G, normal_links as F, normal_targets as T, source_productions as P
from scar.ir.program import source_bindings as B, source_declarations as D
from scar.ir.program import source_binding_variants as V, source_name_access_anchors as A
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import decode, encode


def _checked(path, expected_sha, expected_size, schema, remembered):
    path = Path(path).absolute(); raw = path.read_bytes()
    if len(raw) != expected_size or sha256(raw).hexdigest() != expected_sha:
        raise ValueError('name anchor original material receipt differs: '+str(path))
    remembered[path] = raw
    return ProviderArtifact(str(path), expected_sha, expected_size, schema), raw


def _bindings(material, remembered):
    """Read original C2 materials, including context-qualified compiled C2."""
    store = material.fact_store; unit = material.unit
    if unit in store.original_source_units:
        reference = material.catalog.namespace_graph.report['binding_variants']
        root = Path(reference['path']).absolute(); raw = (root/'result.json').read_bytes()
        if sha256(raw).hexdigest() != reference['sha256']:
            raise ValueError('name anchor compiled binding catalog differs')
        from scar.analysis import source_binding_variants
        report = json.loads(raw)
        if ((report['schema'], report['schema_version']) != ('scar.source-binding-variants', 1)
                or report['implementation_sha256'] != sha256(Path(source_binding_variants.__file__).read_bytes()).hexdigest()
                or report['pins'] != source_binding_variants.pins()):
            raise ValueError('name anchor compiled binding producer differs')
        remembered[root/'result.json'] = raw
        descriptor = report['variants'][unit]
        artifact, raw = _checked(root/descriptor['path'], descriptor['sha256'], descriptor['bytes'],
            'scar.source-binding-variant', remembered)
        variant = decode(V.SourceBindingVariant, json.loads(raw))
        if variant.namespace != unit:
            raise ValueError('name anchor compiled bindings belong to another namespace')
        bindings, declarations = variant.bindings, variant.declarations
        materials = (artifact, ProviderArtifact(str(root/'result.json'), reference['sha256'],
            len(remembered[root/'result.json']), report['schema']))
    else:
        model = store.model_units[unit]; root = store.model_for(unit); reader = _Fragments(root)
        decoded = []; materials = []
        for name, cls, schema in (('source_bindings', B.SourceBindingsMaterial, 'scar.source-bindings'),
                ('source_declarations', D.SourceDeclarationsMaterial, 'scar.source-declarations')):
            descriptor = model['artifacts'][name]
            document = reader.read(descriptor)
            artifact, _ = _checked(root/descriptor['path'], descriptor['sha256'], descriptor['bytes'], schema, remembered)
            decoded.append(decode(cls, document)); materials.append(artifact)
        bindings, declarations = decoded
    # These are the precise C2 documents sealed into every F4 plan, not fresh
    # namespace resolution and not a source filename or identifier heuristic.
    if (material.graph.input.bindings_sha256 != _digest(encode(bindings))
            or material.graph.input.declarations_sha256 != _digest(encode(declarations))):
        raise ValueError('name anchor C2 materials differ from the sealed F4 input')
    return bindings, declarations, tuple(materials)


def _namespace(bindings, interface, key):
    # Same source interface -> sparse Namespace projection as normal_links.
    descriptor = bindings.interfaces[interface.index]
    if descriptor.kind in ('LEXICAL_BINDING', 'CLASS_PROTOCOL_CELL'):
        return F.Namespace(F.NamespaceKind.LEXICAL, descriptor.binding, key)
    if descriptor.kind in ('CLASS_PREPARED_MAPPING', 'CLASS_ANNOTATION_NAMESPACE'):
        return F.Namespace(F.NamespaceKind.CLASS, descriptor.owner, key)
    return F.Namespace(F.NamespaceKind.BUILTINS if descriptor.kind == 'BUILTINS'
        else F.NamespaceKind.MODULE, 0, key)


def _formal_namespace(bindings, declarations, function, parameter):
    """Check the original parameter-admission rule, not a synthetic WRITE."""
    index = parameter.binding_port
    if index is None:
        if parameter.kind is P.DeferredParameterKind.INITIAL_ITERATOR:
            return None
        raise ValueError('named formal has no original binding port')
    port = bindings.ports[index]
    if port.declref is None or port.resolution is None or port.name is None:
        raise ValueError('formal has no original parameter contribution/resolution')
    contribution = declarations.contributions[port.declref]
    resolution = bindings.resolutions[port.resolution]
    if ('PARAMETER_INTERFACE' not in contribution.operations or contribution.port != index
            or resolution.binding is None or port.name.kind != 'SOURCE'):
        raise ValueError('formal does not select an original parameter admission')
    binding = bindings.bindings[resolution.binding]
    if (binding.domain != 'LOCAL_BINDING' or binding.owner != function.environment.scope
            or binding.name != port.name or resolution.name != port.name):
        raise ValueError('formal admission owner/name differs from original binding')
    return F.Namespace(F.NamespaceKind.LEXICAL, resolution.binding, declarations.names[port.name.index].value)


def anchor_name_accesses(snapshot, unit_identity, *, scopes=None, material=None):
    """Return typed operation anchors; matching never grants a name version.

    snapshot is a ContextTargetGraph or exposes its original catalog and
    fact_store. scopes is None or original CodeScopeRefs. One shared unit and
    one batch of sealed plans are read; all plans are needed to retain DELETE
    operations, which the legacy names table omits. Ambiguous joins remain
    frontiers. The caller retains responsibility for snapshot validation.
    """
    if type(unit_identity) is not str or unit_identity not in snapshot.fact_store.rows:
        raise ValueError('name anchors require an original catalog unit identity')
    unit = snapshot.fact_store.load(unit_identity); slicer = ReferenceSlicer(snapshot)
    available = {group.owner for group in unit.scope_groups}
    chosen = available if scopes is None else set((scopes,) if type(scopes) is F.CodeScopeRef else scopes)
    if any(type(scope) is not F.CodeScopeRef or scope.unit != unit_identity or scope not in available for scope in chosen):
        raise ValueError('name anchor scopes must belong to the original unit')
    chosen = tuple(sorted(chosen, key=lambda scope: scope.ordinal)); selected = set(chosen)
    if not chosen:
        return A.NameAccessAnchorGraph(unit_identity, (), (), (), (), (), (), ())
    if material is None:
        material = source_graph_material(getattr(snapshot, 'catalog', snapshot), unit_identity)
    if material.fact_store is not snapshot.fact_store or material.unit != unit_identity:
        raise ValueError('name anchor material must use the snapshot original fact catalog')
    remembered = {}; bindings, declarations, materials = _bindings(material, remembered)
    keys = tuple(node.key for node in material.graph.templates)
    plans = material.plans(keys)
    accesses = []; candidates = defaultdict(list); deletes = []
    for plan in plans.values():
        for access in extract_namespace_interfaces(unit_identity, plan, bindings, declarations)[0]:
            if access.owner.owner not in selected:
                continue
            ordinal = len(accesses); accesses.append(access)
            if access.action is P.BindingActionKind.READ:
                for lookup in access.lookup:
                    namespace = _namespace(bindings, lookup.interface, access.key)
                    candidates[access.owner.owner, namespace, access.value, False].append((ordinal, lookup.ordinal, None))
            elif access.action is P.BindingActionKind.WRITE:
                namespace = _namespace(bindings, access.target, access.key)
                candidates[access.owner.owner, namespace, access.value, True].append((ordinal, None, access.target))
            else:
                deletes.append(A.NameDeleteAnchor(ordinal, _namespace(bindings, access.target, access.key), access.target))
    formal_candidates = defaultdict(list)
    for ordinal, function in enumerate(unit.functions):
        owner = function.body_scope
        if owner is None or owner.owner not in selected:
            continue
        if len(function.formals[1:-1]) != len(function.environment.parameters):
            raise ValueError('formal admission does not match the original body interface')
        for index, (parameter, local) in enumerate(zip(function.environment.parameters, function.formals[1:-1])):
            namespace = _formal_namespace(bindings, declarations, function, parameter)
            if namespace is None:
                continue
            formal = source_port(unit, local)
            expected = G.Port(function.template, function.body, G.PortKind.PARAMETER, index+1)
            if formal.port != expected or owner.template != function.template or owner.region != function.body:
                raise ValueError('formal admission differs from the original body parameter')
            formal_candidates[owner.owner, namespace, formal, True].append((ordinal, function, index, parameter.binding_port))
    owners = defaultdict(set)
    for group in unit.scope_groups:
        for span in group.tables:
            if span.table is F.FactTable.NAMES:
                for index in range(span.start, span.stop): owners[index].add(group.owner)
    anchors = []; formals = []; frontiers = []; used = set()
    for ordinal, record in enumerate(unit.names):
        scopes_for_fact = owners[ordinal]
        if not scopes_for_fact & selected:
            continue
        fact = slicer.fact(unit, 'names', ordinal)
        if len(scopes_for_fact) != 1:
            frontiers.append(A.NameAccessAnchorFrontier(fact, None, None, 'NAME_FACT_CODE_SCOPE_NOT_UNIQUE'))
            continue
        scope = next(iter(scopes_for_fact)); key = scope, record.namespace, source_port(unit, record.value), record.write
        matches = candidates.get(key, ()); admissions = formal_candidates.get(key, ())
        if len(matches)+len(admissions) != 1:
            reason = 'NAME_FACT_OPERATION_OR_ENTRY_UNRESOLVED' if not matches and not admissions else 'NAME_FACT_OPERATION_OR_ENTRY_NOT_UNIQUE'
            frontiers.append(A.NameAccessAnchorFrontier(fact, None, scope, reason,
                tuple(dict.fromkeys(row[0] for row in matches)),
                tuple(slicer.fact(unit, 'functions', row[0]) for row in admissions)))
        elif matches:
            access, lookup, target = matches[0]; used.add((access, lookup))
            anchors.append(A.NameAccessAnchor(fact, record, scope, access, record.namespace, lookup, target))
        else:
            function_ordinal, function, parameter, binding_port = admissions[0]
            formals.append(A.FormalNameAdmission(fact, record, slicer.fact(unit, 'functions', function_ordinal),
                source_port(unit, function.value), function.body_scope, parameter, binding_port,
                source_port(unit, record.value), T.GlobalPort(unit_identity,
                    G.Port(function.template, function.body, G.PortKind.ENTER))))
    for key, matches in candidates.items():
        for access, lookup, _ in matches:
            if (access, lookup) not in used:
                frontiers.append(A.NameAccessAnchorFrontier(None, access, key[0],
                    'SOURCE_OPERATION_HAS_NO_UNIQUE_LEGACY_NAME_FACT_ANCHOR', (access,)))
    material.validate_parents()
    if any(path.read_bytes() != raw for path, raw in remembered.items()):
        raise ValueError('name anchor original C2 material changed during projection')
    return A.NameAccessAnchorGraph(unit_identity, chosen, (material.result_artifact, *materials),
        tuple(accesses), tuple(anchors), tuple(formals), tuple(deletes), tuple(frontiers))
