"""Independently declared current frame identities on the real finished graph.

Every ValueOccurrence retains its original producer. ObjectIDs below are
supplied endpoint declarations, not identities recovered from a Create,
request field, type, branch or native runtime. No copy recipe is added.
"""
from dataclasses import replace

from scar.ir.execution.common import Unresolved
from scar.ir.execution.content import ObjectIdentity, ObjectRef, ValueDenotation
from scar.ir.execution.ids import DenotationID
from scar.ir.execution.snapshot import external_artifact, snapshot_for
from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, CompletionResult, ExitKind, Footprint, FootprintKind,
    Operation, OperationResult, StateAccess, StateVersionValue, Use, UseRole,
)
from scar.ir.program.state_addresses import (
    AddressCoverage, AddressEffect, ExistingAccess, ObjectField, ReferenceOwner,
    StateAddressRefinement,
)
from scar.ir.v2.evidence import EvidenceEndpoint, EvidenceGraph, EvidenceNodeKind
from scar.ir.v2.ids import ObjectID
from tests.fixtures.execution_async_finished_requests_graphs import async_finished_requests_execution
from tests.fixtures.execution_call_graphs import _activation


def _use_value(model, occurrence, use):
    actual, = tuple(row for row in model.uses if (row.operation, row.use) == (occurrence, use))
    return next(row for row in model.values if row.id == actual.value)


def _normal_value(program, model, occurrence, slot):
    definition = next(row.operation for row in model.operations if row.id == occurrence)
    operation = next(row for row in program.operations if row.id == definition)
    transfer, = tuple(row for row in model.transfers if row.operation == occurrence)
    edge = operation.terminator.successors[transfer.successor_index]
    if edge.kind is not ExitKind.NORMAL:
        raise ValueError('the supplied endpoint must be its own NORMAL result')
    block = next(block for region in program.regions for block in region.blocks if block.id == edge.block)
    formal, = tuple(formal for argument, formal in zip(edge.arguments, block.arguments, strict=True)
                    if type(argument) is CompletionResult and argument.index == slot)
    result, = tuple(row for row in model.values if row.origin == transfer.target and row.value == formal)
    return result


def _with_body_write(program, model, details):
    """A new caller heap effect, not a claim that native R fields are writable.

    The original mutable-state operation consumes R and a replacement Ref.
    Current READ identities are supplied independently below; an address or
    this operation's label never derives the value returned by the getter.
    """
    static = details['static']
    finished = static['finished_request']
    call = finished['caller_calls'][0]
    values = {row.id: row for row in program.values}
    context = finished['context_location']
    state_use = next(use for use in call.uses if use.id in call.invoke_arguments
        and type(values[use.value]) is StateVersionValue and values[use.value].location != context)
    location = values[state_use.value].location
    receiver = next(use for use in call.uses if use.id == call.invoke_arguments[0])
    identity = OperationID('frame.identity.current_body.write')
    owner = Use(UseID('frame.identity.write.request'), receiver.value, UseRole.REFERENCE)
    replacement = Use(UseID('frame.identity.write.replacement'), static['root_entry'][0], UseRole.REFERENCE)
    before = Use(UseID('frame.identity.write.before'), state_use.value, UseRole.STATE_CONTENT)
    after = StateVersionValue(ValueID('frame.identity.write.after'), static['caller'].id,
                              OperationResult(identity, 0), location)
    write = Operation(identity, 'explicit mutable held-reference effect',
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), (owner, replacement, before), (after.id,),
        (StateAccess(location, before.id, AccessMode.READ_WRITE, after.id,
                     Footprint(FootprintKind.WHOLE), reference=owner.id),), effects_complete=False)
    # The write is explicit, while its unknown reference range does not
    # certify that every possible alias or additional effect is represented.
    refinement = StateAddressRefinement(ExistingAccess(write.id, 0),
        (AddressEffect(ReferenceOwner(owner.id), (ObjectField('held_body'),), AccessMode.READ_WRITE),),
        AddressCoverage.DECLARED_COMPLETE, finished['interface'].rule.implementation)
    call = replace(call, uses=tuple(replace(use, value=after.id) if use.id == state_use.id else use
                                    for use in call.uses))
    caller = replace(static['caller'], blocks=tuple(replace(block,
        operations=tuple(item for old in block.operations for item in
                         ((write.id, old) if old == call.id else (old,))))
        if call.id in block.operations else block for block in static['caller'].blocks))
    program = replace(program,
        regions=tuple(caller if region.id == caller.id else region for region in program.regions),
        operations=tuple(call if operation.id == call.id else operation for operation in program.operations) + (write,),
        values=(*program.values, after), state_address_refinements=(*program.state_address_refinements, refinement))
    finished = {**finished, 'caller_call': call, 'caller_calls': (call, *finished['caller_calls'][1:])}
    static = {**static, 'caller': caller, 'finished_request': finished}
    # Re-supply the changed caller from canonical operations. Existing IDs for
    # visits/calls/body segments stay exact; no Use borrows a peer occurrence.
    rebuilt, examples = {}, []
    for number, example in enumerate(details['instances']):
        rows, activation, visits, operations = _activation(program, caller.id, static['caller_path'],
            f'async.finished.request.{number}.caller', details['point'], details['thread'])
        for field, items in rows.items():
            rebuilt.setdefault(field, []).extend(items)
        attempts = tuple({**item, 'caller': operations[finished['caller_calls'][ordinal].id]}
                         for ordinal, item in enumerate(example['finished_requests']))
        examples.append({**example, 'caller_activation': activation, 'caller_visits': visits,
            'caller_operations': operations, 'finished_requests': attempts})
    changes = {'snapshot': snapshot_for(program)}
    for field, additions in rebuilt.items():
        def key(row):
            if field == 'uses':
                return row.operation, row.use
            if field == 'transfers':
                return row.operation
            return row.id
        replacement_rows = {key(row): row for row in additions}
        existing = getattr(model, field)
        old_keys = {key(row) for row in existing}
        changes[field] = tuple(replacement_rows.get(key(row), row) for row in existing) + tuple(
            row for row in additions if key(row) not in old_keys)
    model = replace(model, **changes)
    return program, model, {**details, 'static': static, 'instances': tuple(examples),
        'body_write': write, 'body_write_refinement': refinement, 'body_write_call': call}


def frame_identity_execution(*, instances=2, retry=True, body_write=False):
    """Keep the old unannotated fixture intact and add explicit object guards.

    The namespace names run/process/instance/lifetime for this supplied
    catalog. ObjectRef itself has no epoch field and these names do not
    certify a physical object lifetime or source correspondence.
    """
    program, model, details = async_finished_requests_execution(
        terminal='return', request='throw', instances=instances, retry=retry)
    if type(body_write) is not bool:
        raise TypeError('body_write must be an exact bool')
    if body_write:
        if instances != 2:
            raise ValueError('the bounded body-write counterexample uses two existing instances')
        program, model, details = _with_body_write(program, model, details)
    static = details['static']
    finished = static['finished_request']
    evidence = EvidenceGraph()
    identities, endpoints = [], []
    assignments = {}
    for number, example in enumerate(details['instances']):
        name = ObjectID(f'run.{details["point"].run.value}.process.{details["point"].process.value}'
                        f'.instance.{number}.body.lifetime.0')
        evidence.register_external(EvidenceEndpoint(EvidenceNodeKind.OBJECT, name))
        identities.append(name)
        handle = _normal_value(program, model, example['creation'], static['primary_creation'].handle_result.index)
        drive_owners, publication_owners = [], []
        for ordinal, driver in enumerate(static['drivers']):
            occurrences = example['driver_scopes'][ordinal][2]
            drive_owners.append(_use_value(model, occurrences[driver['drive'].operation], driver['drive'].instance))
            publication_owners.append(_use_value(model, occurrences[driver['publication'].operation],
                                                 driver['publication'].instance))
        attempt = example['finished_requests'][0]
        read_value = _use_value(model, attempt['body_predicate'],
                               finished['body_row'].contract.subject.instance_use)
        read_result = _normal_value(program, model, attempt['association'],
                                    finished['body_source'].result.index)
        if read_value.id != read_result.id:
            raise ValueError('the supplied current READ must consume its exact association NORMAL result')
        # Each endpoint is an explicit supplied declaration. This table is
        # neither computed from copy roots nor used to build model flow.
        for value in (handle, *drive_owners, *publication_owners, read_value):
            assignments[value.id] = name
        endpoints.append({'object': name, 'creation_handle': handle,
            'drive_owners': tuple(drive_owners), 'publication_owners': tuple(publication_owners),
            'read': attempt['body_predicate'], 'read_value': read_value, 'read_result': read_result,
            'source': example['driver_scopes'][-1][2][finished['source_publication'].operation],
            'publication': finished['source_publication'], 'caller_activation': example['caller_activation']})
    if body_write:
        # A separate current-value declaration says instance 0 now reads B2;
        # it is not inferred from Create.body, the write operand or its name.
        # Instance 1 remains a complete independent B2 witness.
        assignments[endpoints[0]['read_value'].id] = identities[1]
        write = details['body_write']
        for number, example in enumerate(details['instances']):
            replacement = _use_value(model, example['caller_operations'][write.id], write.uses[1].id)
            assignments[replacement.id] = identities[1]
    artifact = external_artifact(evidence, 'memory:explicit-current-frame-identities')
    basis = Unresolved('supplied object identities without native capture or object epoch proof', details['point'])
    denotations = tuple(ValueDenotation(DenotationID('frame.identity.' + identity.value), identity,
        ObjectIdentity(ObjectRef(artifact, object_id)), basis, details['source'])
        for identity, object_id in assignments.items())
    model = replace(model, denotations=(*model.denotations, *denotations))
    return program, model, {**details, 'frame_identities': tuple(endpoints),
        'identity_artifact': artifact, 'identity_graph': evidence,
        'evidence_graphs': {artifact.sha256: evidence}, 'object_assignments': dict(assignments),
        'objects': tuple(identities)}


__all__ = ['frame_identity_execution']
