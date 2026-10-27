"""Two supplied P instances, each calling a complete H before P's own cuts."""
from dataclasses import replace

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.common import Unresolved
from scar.ir.execution.coordinates import ControlTransfer, InitialEntry, ResumeIngress
from scar.ir.execution.ids import CallActivationID, RegionActivationID
from scar.ir.execution.resumables import BodyDriveExecution
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.program.model import ExitKind
from tests.fixtures.execution_async_pipeline_graphs import _body_path
from tests.fixtures.execution_await_final_region_graphs import await_final_region_execution
from tests.fixtures.execution_call_graphs import _activation
from tests.fixtures.program_async_pipeline_graphs import _selected_path
from tests.fixtures.program_await_parent_post_cleanup_graphs import await_parent_post_cleanup_program


_TABLES = ("activations", "segments", "visits", "operations", "values", "uses", "transfers")


def await_parent_post_cleanup_execution(*, depth=1, helper_zero_cut=True,
                                        instances=2, helper_raised=False,
                                        missing_resume=None, missing_terminal_use=None,
                                        missing_helper_call=None):
    if type(helper_raised) is not bool:
        raise TypeError("helper_raised requires exact bool")
    for name, value in (("missing_resume", missing_resume),
                        ("missing_terminal_use", missing_terminal_use),
                        ("missing_helper_call", missing_helper_call)):
        if value is not None and (type(value) is not int or not 0 <= value < instances):
            raise ValueError(f"{name} must select one captured instance")
    if helper_raised and any(value is not None for value in (missing_resume, missing_terminal_use)):
        raise ValueError("the actual early H failure has no later P resume/Return capture")
    program, static = await_parent_post_cleanup_program(depth=depth, helper_zero_cut=helper_zero_cut)
    _, model, base = await_final_region_execution(zero_cut=helper_zero_cut,
        depth=depth, instances=instances, child_raised=helper_raised)
    source, point = base["source"], base["point"]
    rows = {name: list(getattr(model, name)) for name in _TABLES}
    calls, drives = list(model.call_activations), list(model.body_drive_executions)
    operations = {operation.id: operation for operation in program.operations}
    blocks = {block.id: block for region in program.regions for block in region.blocks}
    examples = []

    def append(captured, *, activation=True):
        for name in _TABLES:
            if name != "activations" or activation:
                rows[name].extend(captured[name])

    for number, helper in enumerate(base["implementation_instances"]):
        prefix = f"await.parent.post.instance.{number}"
        thread = next(segment.host_thread for segment in model.segments
                      if segment.activation == helper["caller_activation"])
        host_choices = {record["call"].id: record["selected_edge"] for record in static["outer_drivers"]}
        if helper_raised:
            first = static["outer_drivers"][0]["call"]
            host_choices[first.id] = next(slot for slot, edge in enumerate(first.terminator.successors)
                                          if edge.kind is ExitKind.RAISE)
        host_path = _selected_path(program, static["host"], host_choices)
        captured, host_activation, host_visits, host_operations = _activation(program,
            static["host"].id, host_path, prefix + ".host", point, thread)
        append(captured)
        outer = static["outer_drivers"][:1] if helper_raised else static["outer_drivers"]
        outer_scopes, outer_calls, instance_drives = [], [], []
        selected_outcomes = (static["parent_failure"].id,) if helper_raised else (
            *static["parent_cuts"], static["parent_return"].id)
        for ordinal, record in enumerate(outer):
            path = record["path"]
            if helper_raised:
                choices = dict(record["part"]["choices"])
                drive_operation = operations[record["drive"].operation]
                choices[drive_operation.id] = next(slot for slot, edge in enumerate(
                    drive_operation.terminator.successors) if edge.source == static["parent_failure"].id)
                path = _selected_path(program, record["region"], choices)
            captured, activation, visits, mapped = _activation(program, record["region"].id,
                path, prefix + f".outer.driver.{ordinal}", point, thread)
            append(captured)
            completion = mapped[blocks[path[-1][0]].operations[-1]]
            association = CallActivation(CallActivationID(prefix + f".outer.call.{ordinal}"),
                host_operations[record["call"].id], activation, visits[0], completion, source)
            calls.append(association)
            outer_calls.append(association)
            outer_scopes.append((activation, visits, mapped))

        parent_activation = RegionActivationID(prefix + ".P")
        previous, literals = None, set()
        parent_entries, parent_segments, parent_visits, parent_operations = [], [], [], []
        for ordinal, (record, outcome_id) in enumerate(zip(outer, selected_outcomes, strict=True)):
            if ordinal == 0:
                start, ingress = static["parent"].entry, InitialEntry(point)
            else:
                target = record["drive"].target
                prior = operations[static["parent_cuts"][ordinal - 1]]
                if target.suspend != prior.id:
                    raise AssertionError("P must resume its own immediately preceding cut")
                start = prior.terminator.successors[target.successor].block
                ingress = ResumeIngress(previous, target.successor, point)
            path = _body_path(program, static["parent"], start, outcome_id)
            captured, temporary, entered, mapped = _activation(program, static["parent"].id,
                path, prefix + f".P.segment.{ordinal}", point, thread)
            captured["activations"] = tuple(replace(row, id=parent_activation)
                                              for row in captured["activations"])
            captured["segments"] = tuple(replace(row, activation=parent_activation, ingress=ingress)
                                           for row in captured["segments"])
            values = []
            for value in captured["values"]:
                if value.origin == temporary:
                    if value.value in literals:
                        continue
                    literals.add(value.value)
                    value = replace(value, origin=parent_activation)
                values.append(value)
            captured["values"] = tuple(values)
            append(captured, activation=ordinal == 0)
            if ordinal:
                rows["transfers"].append(ControlTransfer(previous,
                    record["drive"].target.successor, entered[0]))
            outcome = mapped[outcome_id]
            association = BodyDriveExecution(outer_scopes[ordinal][2][record["drive"].operation],
                parent_activation, entered[0], outcome, source)
            drives.append(association)
            instance_drives.append(association)
            parent_entries.append(entered[0])
            parent_segments.append(captured["segments"][0].id)
            parent_visits.append(entered)
            parent_operations.append(mapped)
            previous = outcome
        helper_link = CallActivation(CallActivationID(prefix + ".H.call"),
            parent_operations[0][static["parent_helper_call"].id], helper["caller_activation"],
            helper["caller_visits"][0], helper["final"], source)
        if missing_helper_call != number:
            calls.append(helper_link)
        definition = static["helper"]["stage_records"][-1]
        frame = helper["implementation_frames"][-1]
        own_definition = definition["landing_values"][ExitKind.NORMAL][0].id
        candidates = tuple(value for value in rows["values"]
            if value.value == own_definition and value.origin in frame["visits"])
        if len(candidates) != (0 if helper_raised else 1):
            raise AssertionError("only this H's actual NORMAL F result can supply the source")
        examples.append({"helper": helper, "helper_call": helper_link,
            "source_value": None if helper_raised else candidates[0].id,
            "source_definition": own_definition, "anchor": helper_link.caller,
            "host_activation": host_activation, "host_operations": host_operations,
            "host_visits": host_visits, "outer_scopes": tuple(outer_scopes),
            "outer_calls": tuple(outer_calls), "parent_activation": parent_activation,
            "parent_entries": tuple(parent_entries), "parent_segments": tuple(parent_segments),
            "parent_visits": tuple(parent_visits), "parent_operations": tuple(parent_operations),
            "parent_drives": tuple(instance_drives),
            "parent_final": parent_operations[-1][selected_outcomes[-1]],
            "pending_constructor": None if helper_raised else
                parent_operations[0][static["pending_constructor"].id]})

    for number, example in enumerate(examples):
        if missing_terminal_use == number:
            owned = static["parent_pending"]["actual"]
            rows["uses"] = [row for row in rows["uses"]
                if (row.operation, row.use) != (example["parent_final"], owned.use)]
        if missing_resume == number:
            omitted = set(example["parent_visits"][-1])
            absent_operations = {row.id for row in rows["operations"] if row.visit in omitted}
            rows["segments"] = [row for row in rows["segments"]
                                 if row.id != example["parent_segments"][-1]]
            rows["visits"] = [row for row in rows["visits"] if row.id not in omitted]
            rows["operations"] = [row for row in rows["operations"] if row.id not in absent_operations]
            rows["values"] = [row for row in rows["values"]
                if row.origin not in omitted and row.origin not in absent_operations]
            rows["uses"] = [row for row in rows["uses"] if row.operation not in absent_operations]
            rows["transfers"] = [row for row in rows["transfers"]
                if row.operation not in absent_operations and row.target not in omitted]
            drives = [replace(row, entry=Unresolved("P's second Resume entry was not captured", point),
                outcome=Unresolved("P's final Return was not captured", point))
                if row.drive == example["parent_drives"][-1].drive else row for row in drives]
    model = replace(model, snapshot=snapshot_for(program),
        **{name: tuple(items) for name, items in rows.items()},
        call_activations=tuple(calls), body_drive_executions=tuple(drives))
    return program, model, {"static": static, "instances": tuple(examples), "source": source,
        "point": point, "helper_raised": helper_raised, "missing_resume": missing_resume,
        "missing_terminal_use": missing_terminal_use, "missing_helper_call": missing_helper_call}


__all__ = ["await_parent_post_cleanup_execution"]
