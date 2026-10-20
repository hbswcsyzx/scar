"""Local comparison of independently declared current Reference identities.

This query creates no copy edge and says nothing about an object's fields
between two reads. Equal scoped ObjectIDs are conditional declarations, not
native identity, address-generation or physical-lifetime verification.
"""
from scar.ir.program.model import ReferenceValue
from scar.ir.v2.evidence import EvidenceGraph, EvidenceNodeKind
from scar.ir.v2.values import ValueGraph

from .common import Unresolved
from .content import ObjectIdentity
from .content_validation import artifact_key
from .coordinates import ValueOccurrence
from .snapshot import SnapshotError
from .validity_budget import ValidityBudget


def _flags():
    return {'source_runtime_verified': False, 'native_identity_verified': False,
            'runtime_identity_verified': False, 'value_identity_verified': False,
            'transformation_authorized': False}


def _endpoint(ctx, role, value):
    if value is not None and type(value) not in (ValueOccurrence, Unresolved):
        raise TypeError('object_identity endpoints must be ValueOccurrence or unresolved')
    captured = (value if type(value) is ValueOccurrence
                and ctx.values.get(value.id) == value else None)
    resolved = None if captured is None else ctx.resolved_denotations.get(captured.id)
    denotation = None if resolved is None else resolved['denotation']
    return {'role': role, 'value': value,
            'definition': None if captured is None else ctx.core_values.get(captured.value),
            'denotation': denotation,
            'declared_basis': None if denotation is None else denotation.basis,
            'basis': None if resolved is None else resolved['basis'],
            'identity': None if denotation is None else denotation.identity,
            'process': None, 'run': None, 'registered': None,
            'captured': captured is not None, 'gaps': ()}


def object_identity(ctx, source, target, *, shared):
    """Compare two original endpoints under one shared, query-local budget.

    The complete two-endpoint inventory precedes budgeted joins. A missing
    source catalog remains unknown even when both denotations name the same
    ObjectID. No diagnostic is added to ``ctx`` for different candidate IDs.
    The public caller refreshes external snapshots and detaches the report.
    """
    if not isinstance(shared, ValidityBudget):
        raise TypeError('object_identity requires a shared ValidityBudget')
    inventory = (_endpoint(ctx, 'source', source), _endpoint(ctx, 'target', target))
    gaps, cursor = [], None

    def gap(code, endpoint=None):
        if code not in gaps:
            gaps.append(code)
        if endpoint is not None and code not in endpoint['gaps']:
            endpoint['gaps'] = (*endpoint['gaps'], code)

    def spend(phase, endpoint=None, *, cost=1):
        nonlocal cursor
        path = 'object_identity.' + (endpoint['role'] + '.' if endpoint else '') + phase
        if shared.truncated or not shared.spend('object_identity_' + phase, cost, path=path):
            if cursor is None:
                cursor = {'phase': phase, 'endpoint': None if endpoint is None else endpoint['role']}
            gap('object_identity_budget_exhausted', endpoint)
            return False
        return True

    for endpoint in inventory:
        if not spend('endpoints', endpoint):
            break
        if not endpoint['captured']:
            gap('object_identity_value_unobserved', endpoint)
            continue
        if type(endpoint['definition']) is not ReferenceValue:
            gap('object_identity_reference_required', endpoint)
            continue
        if not spend('scopes', endpoint):
            break
        activation = ctx.activations.get(ctx.value_activation(endpoint['value'].id))
        process = None if activation is None else ctx.processes.get(activation.process)
        if process is None or process.run not in ctx.runs:
            gap('object_identity_execution_scope_unproved', endpoint)
        else:
            endpoint['process'], endpoint['run'] = process.id, process.run
        if not spend('denotations', endpoint):
            break
        if endpoint['denotation'] is None:
            gap('object_identity_denotation_missing', endpoint)
            continue
        identity = endpoint['identity']
        if type(identity) is not ObjectIdentity:
            gap('object_identity_identity_unresolved', endpoint)
            continue
        if type(endpoint['declared_basis']) is Unresolved or endpoint['basis'] is None:
            # The declaration remains a conditional model fact. Its missing
            # source/native correspondence is retained, never promoted.
            gap('object_identity_basis_unresolved', endpoint)
        if not spend('registries', endpoint):
            break
        reference = identity.object
        family = (EvidenceGraph if reference.artifact.schema == EvidenceGraph.SCHEMA
                  else ValueGraph if reference.artifact.schema == ValueGraph.SCHEMA else None)
        if family is None:
            gap('object_identity_artifact_scope_unproved', endpoint)
            continue
        try:
            graph = ctx.snapshots.graph(reference.artifact, family)
        except SnapshotError as error:
            endpoint['catalog_error'] = {'code': error.code, 'message': str(error)}
            gap('object_identity_catalog_invalid', endpoint)
            continue
        if graph is None:
            gap('object_identity_catalog_unavailable', endpoint)
            continue
        if family is EvidenceGraph:
            endpoint['registered'] = (EvidenceNodeKind.OBJECT, reference.object.wire) in graph.external_references
        else:
            registered = False
            if graph.objects:
                if spend('registry_objects', endpoint):
                    registered = reference.object in graph.objects
                else:
                    registered = None
            if registered is False:
                for binding in graph.bindings:
                    if not spend('registry_bindings', endpoint):
                        registered = None
                        break
                    if binding.object_id == reference.object:
                        registered = True
                        break
            endpoint['registered'] = registered
        if endpoint['registered'] is False:
            gap('object_identity_object_unregistered', endpoint)
        if shared.truncated:
            break

    # Keep only the two endpoints' original source diagnostics. Repeating all
    # unrelated model gaps in every candidate would inflate detached reports.
    # This actual scan is charged, including paths which do not match.
    prefixes = tuple(f'denotations[{row["denotation"].id}]'
                     for row in inventory if row['denotation'] is not None)
    source_gaps = ()
    if spend('source_gap_rows', cost=len(ctx.gaps)):
        source_gaps = tuple(row for row in ctx.gaps
                            if any(row.path.startswith(prefix) for prefix in prefixes))

    match, status = None, 'UNPROVED'
    left, right = inventory
    ready = all(type(row['definition']) is ReferenceValue
                and type(row['identity']) is ObjectIdentity
                and row['captured'] and row['process'] is not None
                and row['run'] is not None and row['registered'] is True
                for row in inventory)
    if ready and spend('comparisons'):
        if (left['process'], left['run']) != (right['process'], right['run']):
            gap('object_identity_execution_scope_unproved')
        elif artifact_key(left['identity'].object.artifact) != artifact_key(right['identity'].object.artifact):
            gap('object_identity_artifact_scope_unproved')
        elif left['identity'].object.object == right['identity'].object.object:
            match, status = True, 'DECLARED_SAME_OBJECT'
        else:
            match, status = False, 'DECLARED_DISTINCT_OBJECTS'
    if shared.truncated:
        match, status = None, 'UNPROVED'
        gap('object_identity_budget_exhausted')
        if cursor is None:
            cursor = {'phase': 'comparison', 'endpoint': None}
    return {'source': source, 'target': target, 'match': match, 'status': status,
            'inventory': inventory, 'gaps': tuple(gaps), 'source_gaps': source_gaps,
            'cursor': cursor,
            'budget': {'limit': shared.limit, 'used': shared.used,
                       'costs': dict(shared.costs), 'truncated': shared.truncated},
            'conditions': ('scoped ObjectIdentity declarations remain conditional model facts',
                           'same object does not establish original copy or stored-field preservation',
                           'ObjectRef has no epoch; bare addresses, PIDs and URIs do not supply one'),
            **_flags()}


__all__ = ['object_identity']
