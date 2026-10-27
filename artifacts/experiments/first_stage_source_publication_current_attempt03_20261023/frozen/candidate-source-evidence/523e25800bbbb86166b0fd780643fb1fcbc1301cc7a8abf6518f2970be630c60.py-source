"""Fresh, per-binding compatibility of declared body values and object scopes."""
from scar.ir.program.model import DataValue, ReferenceValue, StateVersionValue

from .common import Unresolved
from .content import DataIdentity, ObjectIdentity
from .content_validation import artifact_key
from .resumable_flow import gap


def _identity(ctx, value):
    if value is None or type(value) is Unresolved:
        return None
    row = ctx.resolved_denotations.get(value.id)
    return None if row is None else row['denotation'].identity


def compatible(ctx, source, target, gaps, path):
    """Known conflicts reject; equal declarations never certify native values."""
    result = {'status': 'UNPROVED', 'source': source, 'target': target,
              'source_identity': _identity(ctx, source), 'target_identity': _identity(ctx, target),
              'source_runtime_verified': False, 'value_identity_verified': False,
              'transformation_authorized': False}
    if source is None or target is None or type(source) is Unresolved or type(target) is Unresolved:
        gap(ctx, gaps, 'body_binding_value_unobserved', path, 'one original binding endpoint is unresolved')
        return result
    a, b = ctx.core_values[source.value], ctx.core_values[target.value]
    if type(a) is not type(b):
        ctx.issue('body_binding_kind', path, 'original binding endpoints have different canonical value kinds')
        result['status'] = 'CONFLICT'
    elif type(a) is StateVersionValue:
        if a.location != b.location:
            ctx.issue('body_state_location', path, 'binding transports another state location')
            result['status'] = 'CONFLICT'
        else:
            result['status'] = 'DECLARED_STATE_ROUTE'
    elif type(a) is ReferenceValue:
        left, right = result['source_identity'], result['target_identity']
        if type(left) is ObjectIdentity and type(right) is ObjectIdentity:
            if artifact_key(left.object.artifact) == artifact_key(right.object.artifact):
                if left.object.object != right.object.object:
                    ctx.issue('body_reference_conflict', path, 'copy binding has different declared ObjectIDs in the same exact artifact scope')
                    result['status'] = 'CONFLICT'
                else:
                    result['status'] = 'DECLARED_SAME_OBJECT'
            else:
                gap(ctx, gaps, 'body_reference_scope_unproved', path, 'cross-artifact object correspondence is not established')
        else:
            gap(ctx, gaps, 'body_reference_identity_unproved', path, 'binding lacks both scoped ObjectID declarations')
    elif type(a) is DataValue:
        left, right = result['source_identity'], result['target_identity']
        if (type(left) is DataIdentity and type(right) is DataIdentity
                and artifact_key(left.version.artifact) == artifact_key(right.version.artifact)
                and left.version.version == right.version.version):
            result['status'] = 'DECLARED_SAME_VERSION'
        else:
            gap(ctx, gaps, 'body_data_correspondence_unproved', path,
                'different or missing scoped versions do not prove unequal numerical values')
    else:
        result['status'] = 'DECLARED_PROTOCOL_ROUTE'
    return result


def distinct_objects(ctx, left, right, gaps, path):
    """A declared fresh-object rule requires different scoped object identities.

    This is neither numerical inequality nor a new copy/alias relation.
    Different occurrences or artifact locators alone never establish it.
    """
    a, b = _identity(ctx, left), _identity(ctx, right)
    result = {'status': 'UNPROVED', 'left': left, 'right': right,
        'left_identity': a, 'right_identity': b,
        'source_runtime_verified': False, 'runtime_identity_verified': False,
        'value_identity_verified': False, 'transformation_authorized': False}
    if type(a) is ObjectIdentity and type(b) is ObjectIdentity:
        if artifact_key(a.object.artifact) == artifact_key(b.object.artifact):
            if a.object.object == b.object.object:
                ctx.issue('body_reference_distinct_conflict', path,
                    'fresh-object relation has the same declared ObjectID in one exact artifact scope')
                result['status'] = 'CONFLICT'
            else:
                result['status'] = 'DECLARED_DISTINCT_OBJECTS'
        else:
            gap(ctx, gaps, 'body_reference_distinct_scope_unproved', path,
                'cross-artifact object declarations do not establish distinctness')
    else:
        gap(ctx, gaps, 'body_reference_distinct_identity_unproved', path,
            'distinctness requires both exact scoped ObjectIdentity declarations')
    return result


def body_identity_errors(ctx):
    """Called after content resolution on construction and each external refresh."""
    if not hasattr(ctx, 'resolved_body_drives'):
        return
    # Keep a representative per artifact, rather than comparing all Drive pairs.
    owners_by_activation = {}
    creation_handles = ctx.body_known_create_handles
    ctx.body_copy_compatibility = {}
    for target, recipe in ctx.body_copy_recipes.items():
        gaps = []
        comparison = compatible(ctx, ctx.values[recipe['source']], ctx.values[target],
                                gaps, f'body-copy:{target}')
        ctx.body_copy_compatibility[target] = {**recipe, 'compatibility': comparison, 'gaps': tuple(gaps)}
    for activation, origin in ctx.resolved_body_origins.items():
        origin['gaps'] = origin['canonical_gaps']
    comparisons = 0
    for identity, view in ctx.resolved_body_drives.items():
        gaps = list(view['canonical_gaps'])
        for row in (*view['inputs'], *view['outputs'], *view['forwards']):
            row['compatibility'] = compatible(ctx, row['source_value'], row['formal'], gaps,
                f'{identity}:{row["role"]}:{row["formal_definition"].id}')
            comparisons += 1
        owner = view['instance']['value']
        expected = view['instance']['creation_handle']
        view['instance']['compatibility'] = compatible(ctx, expected, owner, gaps, f'{identity}:instance')
        comparisons += 1
        row = view['association']
        if row is not None:
            scope_representatives = owners_by_activation.setdefault(row.activation, {})
            owner_identity = _identity(ctx, owner)
            if type(owner_identity) is ObjectIdentity:
                key = artifact_key(owner_identity.object.artifact)
                if key in scope_representatives:
                    view['instance']['persistent_compatibility'] = compatible(
                        ctx, scope_representatives[key], owner, gaps, f'{identity}:persistent-instance')
                    comparisons += 1
                else:
                    scope_representatives[key] = owner
            # Follow only original declared CFG/call/body copy recipes. Different
            # arbitrary roots never imply unequal objects. Another known Create
            # handle is a concrete contrary source under the frame-create rule.
            actual_root = None if owner is None or type(owner) is Unresolved else ctx.body_value_roots.get(owner.id)
            expected_root = None if expected is None else ctx.body_value_roots.get(expected.id)
            if actual_root in creation_handles and expected_root in creation_handles and actual_root != expected_root:
                ctx.issue('body_instance_source', identity, 'Drive instance is copied from another concrete Create handle')
            if expected is not None and actual_root != expected_root:
                gap(ctx, gaps, 'body_instance_copy_unproved', identity, 'original copy recipe does not connect Drive owner to this Create handle')
        view['gaps'] = tuple(gaps)
    from .resumable_sessions import body_session_identity_errors
    session_comparisons = body_session_identity_errors(ctx)
    ctx.body_identity_preparation = {'binding_comparisons': comparisons,
        'copy_edge_comparisons': len(ctx.body_copy_compatibility),
        'session_binding_comparisons': session_comparisons,
        'fresh_external_context': True, 'cost_scope': 'declared compatibility checks, not native identity proof'}


__all__ = ['compatible', 'distinct_objects', 'body_identity_errors']
