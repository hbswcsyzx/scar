"""Finite supplied captures of the complete native wrapper final chain.

Each caller has its own W, B, wrapper/driver calls and extraction frames.
Only B spans the real zero/three body segments. Object identity declarations
use an external evidence artifact and confer no native capture authority.
"""
from dataclasses import replace

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.common import EvidencePoint, MissingEvidence, Unresolved
from scar.ir.execution.content import ObjectIdentity, ObjectRef, ValueDenotation
from scar.ir.execution.coordinates import (
    ControlTransfer, ExecutionRun, HostThreadInstance, InitialEntry,
    ProcessInstance, ResumeIngress,
)
from scar.ir.execution.ids import (
    CallActivationID, DenotationID, HostThreadInstanceID, ProcessInstanceID,
    RegionActivationID, RunID,
)
from scar.ir.execution.model import ExecutionModel
from scar.ir.execution.resumables import BodyActivationOrigin, BodyDriveExecution
from scar.ir.execution.snapshot import external_artifact, snapshot_for
from scar.ir.program.ids import BlockID, OperationID, ValueID
from scar.ir.program.model import ExitKind
from scar.ir.v2.evidence import EvidenceEndpoint, EvidenceGraph, EvidenceNodeKind
from scar.ir.v2.ids import ObjectID
from tests.fixtures.execution_async_pipeline_graphs import _body_path
from tests.fixtures.execution_call_graphs import _activation
from tests.fixtures.program_async_pipeline_graphs import _selected_path
from tests.fixtures.program_await_wrapper_final_graphs import await_wrapper_final_program


_TABLES = ("activations", "segments", "visits", "operations", "values", "uses", "transfers")


def await_wrapper_final_execution(*, zero_cut=True, depth=1, instances=2,
                                  child_raised=False, attach_link=True,
                                  same_object=False, other_body=None,
                                  missing_wrapper_call=None, missing_child_call=None,
                                  missing_terminal_use=None, stale_child_state=False):
    """Return the same graph and exact instance/call/segment occurrences.

    ``other_body`` selects one instance whose getter/driver use the actual
    decoy Create; expected B remains the constructor's independent operand.
    Missing tuples select (instance, advance), (instance, parent frame), or
    (instance, frame, full produced slot), respectively.
    """
    if type(instances) is not int or instances < 1:
        raise ValueError("instances must be a positive exact integer")
    if type(child_raised) is not bool or type(same_object) is not bool:
        raise TypeError("completion and identity switches require exact bools")
    if other_body is not None and (type(other_body) is not int or not 0 <= other_body < instances):
        raise ValueError("other_body must select one exact captured instance")
    for label, item, size, bounds in (
            ("missing_wrapper_call", missing_wrapper_call, 2, (instances, 1 if zero_cut else 3)),
            ("missing_child_call", missing_child_call, 2, (instances, depth - 1)),
            ("missing_terminal_use", missing_terminal_use, 3, (instances, depth, 3))):
        if item is not None and (type(item) is not tuple or len(item) != size
                or any(type(value) is not int for value in item)):
            raise TypeError(f"{label} requires an exact tuple of integer coordinates")
        if item is not None and any(not 0 <= value < bound
                                    for value, bound in zip(item, bounds, strict=True)):
            raise ValueError(f"{label} is outside the captured coordinates")
    program, static = await_wrapper_final_program(zero_cut=zero_cut, depth=depth,
        attach_link=attach_link, stale_child_state=stale_child_state)
    source = MissingEvidence("supplied wrapper/body/final call associations; no native runtime proof")
    run = RunID("await.wrapper.final.run")
    process = ProcessInstanceID("await.wrapper.final.process")
    thread = HostThreadInstanceID("await.wrapper.final.thread")
    point = EvidencePoint(run, process, source)
    rows = {name: [] for name in _TABLES}
    calls, drives, origins, examples, assignments = [], [], [], [], {}
    selected_kind = ExitKind.RAISE if child_raised else ExitKind.NORMAL
    operations = {operation.id: operation for operation in program.operations}
    blocks = {block.id: block for region in program.regions for block in region.blocks}
    objects = []

    def append(captured, *, activation=True):
        for name in _TABLES:
            if name != "activations" or activation:
                rows[name].extend(captured[name])

    def denote(owner, definition, name):
        matches = tuple(value for value in rows["values"]
                        if value.origin == owner and value.value == definition)
        if len(matches) != 1:
            raise AssertionError("object declaration must identify one original occurrence")
        assignments[matches[0].id] = name

    for instance in range(instances):
        prefix = f"await.wrapper.final.instance.{instance}"
        body_name, decoy_name = prefix + ".B", prefix + ".decoy"
        wrapper_name = body_name if same_object else prefix + ".W"
        actual_body_name = decoy_name if other_body == instance else body_name
        capture_names = tuple(prefix + f".capture.{slot}"
                              for slot in range(len(static["capture_formals"])))
        objects.extend((body_name, decoy_name, wrapper_name, *capture_names))
        caller_choices = {blocks[block].operations[-1]: choice
            for block, choice in static["caller_path"] if choice is not None}
        caller_choices[static["extract"].id] = next(slot for slot, edge in enumerate(
            static["extract"].terminator.successors) if edge.kind is selected_kind)
        caller_path = _selected_path(program, static["caller"], caller_choices)
        captured, caller_activation, caller_visits, caller_operations = _activation(
            program, static["caller"].id, caller_path, prefix + ".caller", point, thread)
        append(captured)
        visits_by_block = {visit.block: visit.id for visit in captured["visits"]}
        for number in range(2):
            block = BlockID(f"await.resume.create.{number}.normal")
            denote(visits_by_block[block], ValueID(block.value + ".arg.0"), body_name)
        block = BlockID("await.resume.create.1.normal")
        denote(visits_by_block[block], ValueID(block.value + ".arg.1"), decoy_name)
        acquired = BlockID("await.resume.acquired")
        for slot, name in enumerate((wrapper_name, body_name, decoy_name)):
            denote(visits_by_block[acquired], ValueID(acquired.value + f".arg.{slot}"), name)
        for number in range(0 if zero_cut else 2):
            block = BlockID(f"await.resume.call.{number}.normal")
            for slot, name in enumerate((body_name, decoy_name, wrapper_name)):
                denote(visits_by_block[block], ValueID(block.value + f".arg.{slot}"), name)

        wrapper_scopes, driver_scopes, instance_calls, outer_calls, inner_calls = [], [], [], [], []
        for ordinal, item in enumerate(static["drivers"]):
            wrapper = item["wrapper"]
            captured, activation, visits, occurrence_map = _activation(program,
                wrapper["region"].id, wrapper["path"], prefix + f".wrapper.{ordinal}", point, thread)
            append(captured)
            wrapper_scopes.append((activation, visits, occurrence_map))
            denote(visits[0], wrapper["entry"][0], wrapper_name)
            denote(occurrence_map[wrapper["read"].id], wrapper["read_body"], actual_body_name)
            terminal_kind = ExitKind.RAISE if zero_cut or ordinal == 2 else ExitKind.NORMAL
            outer = CallActivation(CallActivationID(prefix + f".outer.{ordinal}"),
                caller_operations[item["caller_call"].id], activation, visits[0],
                occurrence_map[wrapper["terminals"][terminal_kind].id], source)
            outer_calls.append(outer)
            instance_calls.append(outer)
            if missing_wrapper_call != (instance, ordinal):
                calls.append(outer)

            captured, driver_activation, driver_visits, driver_operations = _activation(
                program, item["driver_region"].id, item["path"],
                prefix + f".driver.{ordinal}", point, thread)
            append(captured)
            driver_scopes.append((driver_activation, driver_visits, driver_operations))
            driver_entry = blocks[item["driver_region"].entry]
            denote(driver_visits[0], driver_entry.arguments[0], actual_body_name)
            driver_ingress = next(visit for visit in captured["visits"]
                                  if visit.block.value.endswith("driver.ingress"))
            denote(driver_ingress.id, blocks[driver_ingress.block].arguments[0], actual_body_name)
            inner = CallActivation(CallActivationID(prefix + f".inner.{ordinal}"),
                occurrence_map[wrapper["inner_call"].id], driver_activation, driver_visits[0],
                driver_operations[item["host_terminal"].id], source)
            inner_calls.append(inner)
            instance_calls.append(inner)
            calls.append(inner)

        body_activation = RegionActivationID(prefix + ".body")
        body_entries, body_segments, body_occurrences, instance_drives = [], [], [], []
        previous_suspend, body_literals = None, set()
        region = static["body"]
        for ordinal, item in enumerate(static["drivers"]):
            target = operations[item["outcome_source"]]
            if ordinal == 0:
                start, ingress = region.entry, InitialEntry(point)
            else:
                resume = item["drive"].target
                previous = operations[static["drivers"][ordinal - 1]["outcome_source"]]
                if resume.suspend != previous.id:
                    raise AssertionError("resume must use this B's immediately preceding real cut")
                start = previous.terminator.successors[resume.successor].block
                ingress = ResumeIngress(previous_suspend, resume.successor, point)
            path = _body_path(program, region, start, target.id)
            captured, temporary, visits, occurrence_map = _activation(program,
                region.id, path, prefix + f".body.segment.{ordinal}", point, thread)
            segment = replace(captured["segments"][0], activation=body_activation, ingress=ingress)
            captured["segments"] = (segment,)
            captured["activations"] = tuple(replace(row, id=body_activation)
                                              for row in captured["activations"])
            values = []
            for value in captured["values"]:
                if value.origin == temporary:
                    if value.value in body_literals:
                        continue
                    body_literals.add(value.value)
                    value = replace(value, origin=body_activation)
                values.append(value)
            captured["values"] = tuple(values)
            append(captured, activation=ordinal == 0)
            if ordinal:
                rows["transfers"].append(ControlTransfer(previous_suspend,
                    item["drive"].target.successor, visits[0]))
            outcome = occurrence_map[target.id]
            association = BodyDriveExecution(driver_scopes[ordinal][2][item["drive"].operation],
                body_activation, visits[0], outcome, source)
            drives.append(association)
            instance_drives.append(association)
            body_entries.append(visits[0])
            body_segments.append(segment.id)
            body_occurrences.append(occurrence_map)
            previous_suspend = outcome
        creation_definition = static["decoy_creation"] if other_body == instance else static["primary_creation"]
        origin = BodyActivationOrigin(body_activation,
            caller_operations[creation_definition.operation], source)
        origins.append(origin)
        creation = operations[creation_definition.operation]
        creation_uses = {use.id: use for use in creation.uses}
        for number, capture in enumerate(creation_definition.captures):
            denote(caller_visits[0], creation_uses[capture.source].value, capture_names[number])
            denote(body_entries[0], capture.formal, capture_names[number])

        frames, nested_calls = [], []
        for number, definition in enumerate(static["stage_records"]):
            captured, activation, visits, occurrence_map = _activation(program,
                definition["region"].id, definition["paths"][selected_kind],
                prefix + f".final.stage.{number}", point, thread)
            append(captured)
            frames.append({"definition": definition, "activation": activation,
                "visits": visits, "operations": occurrence_map, "entry": visits[0],
                "completion": occurrence_map[definition["terminals"][selected_kind].id],
                "terminal": definition["terminals"][selected_kind]})
        root_call = CallActivation(CallActivationID(prefix + ".final.root"),
            caller_operations[static["extract"].id], frames[0]["activation"],
            frames[0]["entry"], frames[0]["completion"], source)
        calls.append(root_call)
        for number in range(len(frames) - 1):
            parent, child = frames[number], frames[number + 1]
            link = CallActivation(CallActivationID(prefix + f".final.child.{number}"),
                parent["operations"][parent["definition"]["operation"].id],
                child["activation"], child["entry"], child["completion"], source)
            nested_calls.append(link)
            if missing_child_call != (instance, number):
                calls.append(link)
        if missing_terminal_use is not None and missing_terminal_use[0] == instance:
            _, number, slot = missing_terminal_use
            owned = frames[number]["definition"]["terminal_uses"][selected_kind][slot]
            occurrence = frames[number]["operations"][owned.operation]
            rows["uses"] = [row for row in rows["uses"]
                if (row.operation, row.use) != (occurrence, owned.use)]
        final = blocks[caller_path[-1][0]].operations[-1]
        examples.append({"caller_activation": caller_activation, "caller_visits": caller_visits,
            "caller_operations": caller_operations, "wrapper_scopes": tuple(wrapper_scopes),
            "driver_scopes": tuple(driver_scopes), "call_activations": tuple(instance_calls),
            "wrapper_calls": tuple(outer_calls), "driver_calls": tuple(inner_calls),
            "body_activation": body_activation, "body_entries": tuple(body_entries),
            "body_segments": tuple(body_segments), "body_occurrences": tuple(body_occurrences),
            "body_drives": tuple(instance_drives), "body_origin": origin,
            "creation": origin.creation, "expected_creation": caller_operations[static["primary_creation"].operation],
            "decoy_creation": caller_operations[static["decoy_creation"].operation],
            "acquisition": caller_operations[static["constructor"].id],
            "constructor": caller_operations[static["constructor"].id],
            "advance": caller_operations[static["calls"][-1].id],
            "extraction": caller_operations[static["extract"].id],
            "conversion": driver_scopes[-1][2][static["conversion"].id],
            "driver_terminal": inner_calls[-1].completion,
            "body_outcome": instance_drives[-1].outcome,
            "final": caller_operations[final], "implementation_frames": tuple(frames),
            "implementation_root_call": root_call, "implementation_nested_calls": tuple(nested_calls),
            "implementation_kind": selected_kind, "body_object": ObjectID(body_name),
            "wrapper_object": ObjectID(wrapper_name), "actual_body_object": ObjectID(actual_body_name)})

    evidence = EvidenceGraph()
    for name in dict.fromkeys(objects):
        evidence.register_external(EvidenceEndpoint(EvidenceNodeKind.OBJECT, ObjectID(name)))
    artifact = external_artifact(evidence, "memory:await-wrapper-final-supplied-objects")
    gap = Unresolved("declared object identity; no native wrapper capture", point)
    denotations = tuple(ValueDenotation(DenotationID(identity.value), identity,
        ObjectIdentity(ObjectRef(artifact, ObjectID(name))), gap, source)
        for identity, name in assignments.items())
    model = ExecutionModel(snapshot_for(program),
        runs=(ExecutionRun(run, source),),
        processes=(ProcessInstance(process, run, 303, source),),
        threads=(HostThreadInstance(thread, process, 404, source),),
        **{name: tuple(items) for name, items in rows.items()},
        call_activations=tuple(calls), body_drive_executions=tuple(drives),
        body_activation_origins=tuple(origins), denotations=denotations)
    return program, model, {"static": static, "instances": tuple(examples),
        "implementation_instances": tuple(examples), "source": source, "point": point,
        "drive_outcome": static["drive_outcome"], "zero_cut": zero_cut,
        "child_raised": child_raised, "evidence_artifact": artifact,
        "evidence_graphs": {artifact.sha256: evidence}, "object_assignments": dict(assignments)}


__all__ = ["await_wrapper_final_execution"]
