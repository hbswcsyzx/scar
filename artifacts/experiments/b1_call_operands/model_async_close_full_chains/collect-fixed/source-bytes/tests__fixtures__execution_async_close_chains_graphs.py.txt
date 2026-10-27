"""Exact async-close captures with independent, conditional frame identities.

The finished-request wrapper keeps the original Program and all actual ports.
Its object catalog is supplied evidence, not request-field recovery, original
copy equality, native execution evidence, or a physical lifetime claim.
"""
from dataclasses import replace

from scar.ir.execution.common import Unresolved
from scar.ir.execution.content import ObjectIdentity, ObjectRef, ValueDenotation
from scar.ir.execution.ids import DenotationID
from scar.ir.execution.snapshot import external_artifact
from scar.ir.program.model import ExitKind, TerminatorKind
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.v2.evidence import EvidenceEndpoint, EvidenceGraph, EvidenceNodeKind
from scar.ir.v2.ids import ObjectID
from tests.fixtures.execution_async_finished_requests_graphs import async_finished_requests_execution
from tests.fixtures.execution_frame_identity_graphs import _normal_value, _use_value
from tests.fixtures.native_coroutine_common import capture_program


def finished_frame_identity_execution(*, terminal='return', request='throw',
                                      constructor_raised=False, retry=False,
                                      instances=2):
    """Supply the four real terminal/new-request combinations without lowering Create.

    Every current READ, historical Drive owner, publication owner and original
    creation handle receives its own explicit denotation. The declarations do
    not certify that a request field retained its constructor payload.
    """
    program, model, details = async_finished_requests_execution(
        terminal=terminal, request=request, constructor_raised=constructor_raised,
        retry=retry, instances=instances)
    static = details['static']
    finished = static['finished_request']
    evidence = EvidenceGraph()
    identities, endpoints, assignments = [], [], {}
    for number, example in enumerate(details['instances']):
        identity = ObjectID(f'run.{details["point"].run.value}.process.{details["point"].process.value}'
                            f'.instance.{number}.finished.body.lifetime.0')
        evidence.register_external(EvidenceEndpoint(EvidenceNodeKind.OBJECT, identity))
        identities.append(identity)
        handle = _normal_value(program, model, example['creation'],
                               static['primary_creation'].handle_result.index)
        drive_owners, publication_owners = [], []
        for ordinal, driver in enumerate(static['drivers']):
            occurrences = example['driver_scopes'][ordinal][2]
            drive_owners.append(_use_value(model, occurrences[driver['drive'].operation],
                                           driver['drive'].instance))
            publication_owners.append(_use_value(model,
                occurrences[driver['publication'].operation], driver['publication'].instance))
        attempt = example['finished_requests'][0]
        current = _use_value(model, attempt['body_predicate'],
                            finished['body_row'].contract.subject.instance_use)
        own_body = _normal_value(program, model, attempt['association'],
                                 finished['body_source'].result.index)
        if current.id != own_body.id:
            raise ValueError('the current predicate must consume its own selected association result')
        for value in (handle, *drive_owners, *publication_owners, current):
            assignments[value.id] = identity
        endpoints.append({'object': identity, 'creation_handle': handle,
            'drive_owners': tuple(drive_owners), 'publication_owners': tuple(publication_owners),
            'read': attempt['body_predicate'], 'read_value': current, 'read_result': own_body,
            'association': attempt['association'], 'request_creation': example['new_request_creation'],
            'source': example['driver_scopes'][-1][2][finished['source_publication'].operation],
            'publication': finished['source_publication'], 'caller_activation': example['caller_activation']})
    artifact = external_artifact(evidence, 'memory:async-close-current-frame-identities')
    basis = Unresolved('supplied object identities without native capture or object epoch proof',
                       details['point'])
    denotations = tuple(ValueDenotation(DenotationID('async.close.frame.identity.' + value.value), value,
        ObjectIdentity(ObjectRef(artifact, identity)), basis, details['source'])
        for value, identity in assignments.items())
    return program, replace(model, denotations=(*model.denotations, *denotations)), {
        **details, 'frame_identities': tuple(endpoints), 'identity_artifact': artifact,
        'identity_graph': evidence, 'evidence_graphs': {artifact.sha256: evidence},
        'object_assignments': dict(assignments), 'objects': tuple(identities)}


def _selected_path(program, region, default, selected):
    """Choose original edges on one actual invocation, keeping visits separate."""
    if type(selected) is not tuple or any(type(edge) is not ControlEdgeReference for edge in selected):
        raise TypeError('path choices must be a tuple of exact original ControlEdgeReference records')
    operations = {row.id: row for row in program.operations}
    blocks = {row.id: row for row in region.blocks}
    fixed = {}
    for edge in selected:
        if edge.operation in fixed and fixed[edge.operation] != edge.successor_index:
            raise ValueError('one supplied invocation cannot select two edges of one operation')
        if not any(edge.operation in block.operations for block in region.blocks):
            raise ValueError('path choice must belong to this original region')
        fixed[edge.operation] = edge.successor_index
    prior = {blocks[identity].operations[-1]: edge for identity, edge in default if edge is not None}
    prior.update(fixed)
    current, result, seen = default[0][0], [], set()
    while current not in seen:
        seen.add(current)
        block = blocks[current]
        operation = operations[block.operations[-1]]
        term = operation.terminator
        if term.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE, TerminatorKind.SUSPEND):
            result.append((current, None))
            return tuple(result)
        number = prior.get(operation.id)
        if number is None:
            if len(term.successors) != 1:
                raise ValueError('the actual branch needs an explicit original edge choice')
            number = 0
        if not 0 <= number < len(term.successors):
            raise ValueError('path choice must name an original successor')
        result.append((current, number))
        current = term.successors[number].block
    raise ValueError('this finite supplied capture needs an explicit path without an unbounded loop')


def async_close_chains_execution(*, route='graceful-return', instances=2, choices=None):
    """Re-supply the exact close-chain program, including only actual body segments.

    Choices are per invocation: ``drivers`` and ``body`` map original stage
    ordinals to tuples of original edges; ``caller`` is its own edge tuple.
    No choice from another visit is merged into an invocation's default path.
    """
    from tests.fixtures.program_async_close_chains_graphs import async_close_chains_program

    program, static = async_close_chains_program(route=route)
    if choices is None:
        choices = {}
    if type(choices) is not dict or set(choices) - {'drivers', 'body', 'caller'}:
        raise TypeError('choices must contain only per-driver, per-body and caller original paths')
    driver_choices, body_choices = choices.get('drivers', {}), choices.get('body', {})
    if type(driver_choices) is not dict or type(body_choices) is not dict:
        raise TypeError('driver and body choices must be maps keyed by original stage ordinal')
    capture = static['capture_details']
    definitions = {row.id: row for row in program.operations}
    blocks = {block.id: block for region in program.regions for block in region.blocks}
    stage_count = len(capture['drivers'])
    if any(type(key) is not int or not 0 <= key < stage_count
           for key in (*driver_choices, *body_choices)):
        raise ValueError('path choices must name an existing original stage ordinal')
    stages, body_paths, caller_edges = [], {}, []
    for ordinal, original in enumerate(capture['drivers']):
        path = _selected_path(program, original['driver_region'], original['path'],
                              driver_choices.get(ordinal, ()))
        operations = {site for identity, _ in path for site in blocks[identity].operations}
        terminal = definitions[blocks[path[-1][0]].operations[-1]]
        drive = original.get('drive') or original.get('available_drive')
        drive = drive if drive is not None and drive.operation in operations else None
        stage = {**original, 'path': path, 'host_terminal': terminal, 'drive': drive}
        if drive is not None:
            operation = definitions[drive.operation]
            selected, = tuple(number for identity, number in path
                              if blocks[identity].operations[-1] == operation.id)
            outcome = operation.terminator.successors[selected].source
            body_path = _selected_path(program, capture['body'], static['body_paths'][ordinal],
                                       body_choices.get(ordinal, ()))
            if blocks[body_path[-1][0]].operations[-1] != outcome:
                raise ValueError('the body path must end at this actual Drive successor source')
            stage['outcome_source'] = outcome
            body_paths[ordinal] = body_path
        elif ordinal in body_choices:
            raise ValueError('a no-Drive request cannot invent a body path')
        stages.append(stage)
        call = original['caller_call']
        kind = ExitKind.NORMAL if terminal.terminator.kind is TerminatorKind.RETURN else ExitKind.RAISE
        numbers = tuple(number for number, edge in enumerate(call.terminator.successors) if edge.kind is kind)
        if len(numbers) != 1:
            raise ValueError('the actual caller completion must match this driver terminal')
        caller_edges.append(ControlEdgeReference(call.id, numbers[0]))
    caller_path = _selected_path(program, capture['caller'], capture['caller_path'],
        (*caller_edges, *choices.get('caller', ())))
    supplied = {**capture, 'caller_path': caller_path, 'drivers': tuple(stages)}
    model, details = capture_program(program, supplied, instances=instances,
        label='async.close.chain', body_paths=body_paths,
        extra_calls=static.get('extra_calls', ()))
    examples = []
    for example in details['instances']:
        rows = []
        for ordinal, stage in enumerate(stages):
            activation, visits, occurrences = example['driver_scopes'][ordinal]
            association = example['call_activations'][ordinal]
            body = example['body_scopes'].get(ordinal)
            actual_drive = next((item for item in example['body_drives']
                                 if stage['drive'] is not None
                                 and item.drive == occurrences[stage['drive'].operation]), None)
            rows.append({'definition': stage, 'stage': ordinal,
                'activation': activation, 'visits': visits, 'operations': occurrences,
                'call': association, 'caller': association.caller,
                'host': occurrences[stage['host_terminal'].id],
                'drive': actual_drive, 'body': body})
        examples.append({**example, 'stages': tuple(rows)})
    return program, model, {**details, 'static': static, 'capture_static': supplied,
                            'instances': tuple(examples), 'choices': choices}


__all__ = ['finished_frame_identity_execution', 'async_close_chains_execution']
