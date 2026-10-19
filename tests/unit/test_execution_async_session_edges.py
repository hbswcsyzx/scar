"""Independent async scope and identity edges over the supplied original IR."""
from dataclasses import fields, is_dataclass, replace

import pytest

from scar.ir.execution.common import Unresolved
from scar.ir.execution.content import ObjectIdentity, ObjectRef, ValueDenotation
from scar.ir.execution.ids import DenotationID
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.snapshot import external_artifact, snapshot_for
from scar.ir.execution.validation import validate
from scar.ir.program.ids import ProtocolScopeID
from scar.ir.program.model import ReferenceValue
from scar.ir.program.protocol_connections import AsyncSessionOutcome
from scar.ir.program.protocols import ProtocolProfile
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid
from scar.ir.v2.evidence import EvidenceEndpoint, EvidenceGraph, EvidenceNodeKind
from scar.ir.v2.ids import ObjectID
from tests.fixtures.execution_async_pipeline_graphs import async_pipeline_execution


def _remap_scope(value, original, replacement):
    if type(value) is ProtocolScopeID:
        return replacement if value == original else value
    if type(value) is tuple:
        return tuple(_remap_scope(item, original, replacement) for item in value)
    if is_dataclass(value):
        return replace(value, **{field.name: _remap_scope(getattr(value, field.name), original, replacement)
                                 for field in fields(value)})
    return value


def test_another_scope_cannot_borrow_the_existing_scope_session_binding():
    program, model, details = async_pipeline_execution()
    stage = details['static']['drivers'][0]
    original, = (scope for scope in program.protocol_scopes
        if scope.profile is ProtocolProfile.ASYNC_GENERATOR_BODY_V1
        and scope.subject.interface_region == stage['driver_region'].id)
    duplicate = replace(original, id=ProtocolScopeID('async.pipeline.independent.scope'))
    operations = tuple(_remap_scope(row, original.id, duplicate.id)
                       for row in program.protocol_operations if row.scope == original.id)
    bindings = tuple(_remap_scope(row, original.id, duplicate.id)
        for row in program.protocol_bindings
        if getattr(row, 'scope', None) == original.id and type(row) is not AsyncSessionOutcome)
    inputs = tuple(_remap_scope(row, original.id, duplicate.id)
                   for row in program.protocol_call_inputs if row.site.scope == original.id)
    consumers = tuple(_remap_scope(row, original.id, duplicate.id)
        for row in program.protocol_result_consumers if row.site.scope == original.id)
    changed = replace(program, protocol_scopes=(*program.protocol_scopes, duplicate),
        protocol_operations=(*program.protocol_operations, *operations),
        protocol_bindings=(*program.protocol_bindings, *bindings),
        protocol_call_inputs=(*program.protocol_call_inputs, *inputs),
        protocol_result_consumers=(*program.protocol_result_consumers, *consumers))
    require_valid(changed)
    static = ProgramIndex(changed).protocol_obligations(duplicate.id, budget=131072)
    sources = static['connections']['families']['async']['session_consumers']
    missing, = (row for row in sources
                if row['scope'] == duplicate.id and row['source'] == stage['outcome'])
    assert missing['status'] == 'MISSING'
    assert missing['targets'] and all(row['binding'] is None for row in missing['targets'])

    changed_model = replace(model, snapshot=snapshot_for(changed))
    report = validate(changed_model, changed)
    assert report.valid, report.issues
    session = ExecutionIndex(changed_model, changed).drive_execution(
        details['body_drive_occurrences'][0])['session']
    target, = session['targets']
    by_scope = {row['scope'].id: row for row in target['source_bindings']}
    assert set(by_scope) == {original.id, duplicate.id}
    assert by_scope[original.id]['binding'] is not None
    assert by_scope[duplicate.id]['binding'] is None
    assert target['binding'] is None
    assert session['expected_consumer_count'] == 2
    assert session['status'] == 'PARTIAL'
    assert any(row.code == 'body_session_source_binding_missing' for row in session['gaps'])
    assert session['source_runtime_verified'] is session['transformation_authorized'] is False


def _identity_edges(role):
    program, model, details = async_pipeline_execution()
    stage = details['static']['drivers'][0]
    uses = {(row.operation, row.use): row for row in model.uses}
    values = {row.id: row for row in model.values}
    if role == 'request':
        # R is copied by this exact CALL actual/formal. The update reuses the
        # driver's entry R itself, so contrasting two denotations on that one
        # ValueOccurrence would be an invalid duplicate-denotation test.
        receiver_ordinal = stage['entry_formals'].index(stage['interface'].receiver)
        caller = details['caller_operations'][stage['caller_call'].id]
        source_use = uses[caller, stage['caller_call'].invoke_arguments[receiver_ordinal]]
        target_use = uses[details['session_update_occurrences'][0], stage['update'].request]
    else:
        source_use = uses[details['body_drive_occurrences'][0], stage['drive'].instance]
        target_use = uses[details['session_update_occurrences'][0], stage['update'].body]
    source, target = values[source_use.value], values[target_use.value]
    assert source.id != target.id
    core = {row.id: row for row in program.values}
    assert type(core[source.value]) is type(core[target.value]) is ReferenceValue

    evidence = EvidenceGraph()
    same, wrong = ObjectID('session.edge.same'), ObjectID('session.edge.wrong')
    for identity in (same, wrong):
        evidence.register_external(EvidenceEndpoint(EvidenceNodeKind.OBJECT, identity))
    artifact = external_artifact(evidence, 'memory:async-session-edge-objects')
    basis = Unresolved('scoped declarations, not a native identity witness', model.activations[0].entry)
    denotations = tuple(ValueDenotation(DenotationID('session.edge.' + role + '.' + label), value.id,
        ObjectIdentity(ObjectRef(artifact, same)), basis, details['source'])
        for label, value in (('source', source), ('target', target)))
    consistent = replace(model, denotations=(*model.denotations, *denotations))
    catalogs = {'evidence_graphs': {artifact.sha256: evidence}}
    require_valid(program)
    baseline = validate(consistent, program, **catalogs)
    assert baseline.valid, baseline.issues
    contradictory = replace(consistent, denotations=tuple(
        replace(row, identity=ObjectIdentity(ObjectRef(artifact, wrong)))
        if row.value == target.id else row for row in consistent.denotations))
    assert contradictory.operations == model.operations
    assert contradictory.values == model.values
    assert contradictory.uses == model.uses
    assert contradictory.transfers == model.transfers
    return program, consistent, contradictory, details, catalogs, evidence, source, target


def _reject_identity_conflict(program, contradictory, catalogs):
    report = validate(contradictory, program, **catalogs)
    codes = {row.code for row in report.issues}
    assert not report.valid
    assert 'body_reference_conflict' in codes, report.issues
    assert not codes.intersection({'use_definition', 'use_activation', 'value_origin',
                                   'content_object', 'content_denotation_duplicate'})


def test_update_request_identity_conflict_checks_the_original_caller_copy_ancestor():
    program, _, contradictory, _, catalogs, _, _, _ = _identity_edges('request')
    _reject_identity_conflict(program, contradictory, catalogs)


def test_update_body_identity_conflict_and_fresh_catalog_cannot_reuse_old_compatibility():
    program, consistent, contradictory, details, catalogs, evidence, _, _ = _identity_edges('body')
    _reject_identity_conflict(program, contradictory, catalogs)
    index = ExecutionIndex(consistent, program, **catalogs)
    before = index.drive_execution(details['body_drive_occurrences'][0])
    target, = before['session']['targets']
    assert target['body']['compatibility']['status'] == 'DECLARED_SAME_OBJECT'
    # Mutating the caller's declared artifact cannot reuse the construction
    # snapshot or a previous body's per-binding compatibility receipt.
    evidence.external_references.clear()
    with pytest.raises(ValueError, match='snapshot|artifact|object'):
        index.drive_execution(details['body_drive_occurrences'][0])
    assert target['body']['compatibility']['status'] == 'DECLARED_SAME_OBJECT'
    assert index.report.valid
