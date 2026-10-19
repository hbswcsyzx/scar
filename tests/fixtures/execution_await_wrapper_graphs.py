"""Finite captures of a native W != B wrapper and its original held-body read.

ObjectIDs below are supplied declarations, without native capture evidence.
Original value occurrences remain separate across every CFG/call/body port.
"""
from dataclasses import replace

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.common import Unresolved
from scar.ir.execution.content import ObjectIdentity, ObjectRef, ValueDenotation
from scar.ir.execution.ids import CallActivationID, DenotationID
from scar.ir.execution.resumables import BodyActivationOrigin, BodyDriveExecution
from scar.ir.execution.snapshot import external_artifact
from scar.ir.program.ids import BlockID, OperationID, ValueID
from scar.ir.v2.evidence import EvidenceEndpoint, EvidenceGraph, EvidenceNodeKind
from scar.ir.v2.ids import ObjectID
from tests.fixtures.execution_call_graphs import _model
from tests.fixtures.program_await_wrapper_graphs import await_wrapper_program


def await_wrapper_execution(*, attach_link=True, same_object=False, other_body=False):
    """Return (program, model, details), with two real synchronous call links."""
    program, static = await_wrapper_program(attach_link=attach_link, second_create=other_body)
    drive = static["drive"]
    drive_operation = next(row for row in program.operations if row.id == drive.operation)
    selected = next(index for index, edge in enumerate(drive_operation.terminator.successors)
                    if edge.source == OperationID("resume.suspend"))
    body_region = next(row for row in program.regions if row.id == static["body"].region)
    paths = (
        (program.root, (
            (BlockID("factory.entry"), 0), (BlockID("factory.created"), 0),
            *(((BlockID("factory.second.created"), 0),) if other_body else ()),
            (BlockID("factory.awaitable"), 0), (BlockID("factory.normal"), None),
        ), "await.wrapper.factory"),
        (static["wrapper_region"].id, (
            (BlockID("wrapper.advance.entry"), 0),
            (BlockID("wrapper.advance.normal"), None),
        ), "await.wrapper.adapter"),
        (static["driver"].region, (
            (BlockID("driver.entry"), 0), (BlockID("driver.ingress"), selected),
            (BlockID("driver.outcome"), None),
        ), "await.wrapper.driver"),
        (body_region.id, ((body_region.entry, None),), "await.wrapper.body"),
    )
    model, scopes, source = _model(program, paths)
    factory, adapter, driver, body = scopes
    calls = (
        CallActivation(CallActivationID("await.wrapper.outer.call"),
            factory[2][static["call"].id], adapter[0], adapter[1][0],
            adapter[2][static["inner_return"].id], source),
        CallActivation(CallActivationID("await.wrapper.inner.call"),
            adapter[2][static["inner_call"].id], driver[0], driver[1][0],
            driver[2][OperationID("driver.outcome.exit")], source),
    )
    drive_occurrence = driver[2][drive.operation]
    body_link = BodyDriveExecution(drive_occurrence, body[0], body[1][0],
        body[2][OperationID("resume.suspend")], source)
    actual_creation = static["second_create"] if other_body else static["create"]
    origin = BodyActivationOrigin(body[0], factory[2][actual_creation.operation], source)

    evidence = EvidenceGraph()
    names = ("body", "other.body", "wrapper", *(f"capture.{index}"
              for index in range(len(static["create"].captures))))
    for name in names:
        evidence.register_external(EvidenceEndpoint(EvidenceNodeKind.OBJECT, ObjectID(name)))
    artifact = external_artifact(evidence, "memory:await-wrapper-declared-objects")
    gap = Unresolved("declared object identity; no native wrapper capture", model.activations[0].entry)
    occurrences = {(value.origin, value.value): value for value in model.values}
    assignments = {}
    visits = {visit.block: visit.id for visit in model.visits
              if visit.id in factory[1]}

    def denote(owner, definition, name):
        occurrence = occurrences[(owner, definition)]
        assignments[occurrence.id] = name

    denote(visits[BlockID("factory.created")], ValueID("factory.created.arg.0"), "body")
    if other_body:
        denote(visits[BlockID("factory.second.created")],
               ValueID("factory.second.created.arg.0"), "body")
        denote(visits[BlockID("factory.second.created")],
               ValueID("factory.second.created.arg.1"), "other.body")
    wrapper_name = "body" if same_object else "wrapper"
    denote(visits[BlockID("factory.awaitable")], ValueID("factory.awaitable.arg.0"), wrapper_name)
    denote(adapter[1][0], static["wrapper_entry"][0], wrapper_name)
    actual_body = "other.body" if other_body else "body"
    denote(adapter[2][static["read"].id], static["read_body"], actual_body)
    denote(driver[1][0], ValueID("driver.entry.arg.0"), actual_body)
    denote(driver[1][1], ValueID("driver.ingress.arg.0"), actual_body)
    create_operation = next(row for row in program.operations if row.id == actual_creation.operation)
    create_uses = {use.id: use for use in create_operation.uses}
    for index, capture in enumerate(actual_creation.captures):
        name = f"capture.{index}"
        denote(factory[1][0], create_uses[capture.source].value, name)
        denote(body[1][0], capture.formal, name)
    # This original body exports its first captured parameter on this AWAIT.
    for owner, value in (
        (driver[1][2], ValueID("driver.outcome.arg.0")),
        (adapter[1][1], ValueID("wrapper.advance.normal.arg.0")),
        (visits[BlockID("factory.normal")], ValueID("factory.normal.arg.0")),
    ):
        denote(owner, value, "capture.0")
    denotations = tuple(ValueDenotation(DenotationID(identity.value), identity,
        ObjectIdentity(ObjectRef(artifact, ObjectID(name))), gap, source)
        for identity, name in assignments.items())
    model = replace(model, call_activations=calls, body_drive_executions=(body_link,),
        body_activation_origins=(origin,), denotations=denotations)
    return program, model, {
        **static, "source": source, "scopes": scopes,
        "factory_activation": factory[0], "factory_visits": factory[1],
        "factory_operations": factory[2], "wrapper_activation": adapter[0],
        "wrapper_visits": adapter[1], "wrapper_operations": adapter[2],
        "driver_activation": driver[0], "driver_visits": driver[1],
        "driver_operations": driver[2], "body_activation": body[0],
        "body_visits": body[1], "body_operations": body[2],
        "calls": calls, "drive_occurrence": drive_occurrence,
        "body_drive_execution": body_link, "body_activation_origin": origin,
        "evidence_artifact": artifact, "evidence_graphs": {artifact.sha256: evidence},
        "body_object": ObjectID("body"), "wrapper_object": ObjectID(wrapper_name),
        "actual_body_object": ObjectID(actual_body),
        "object_assignments": dict(assignments),
    }


__all__ = ["await_wrapper_execution"]
