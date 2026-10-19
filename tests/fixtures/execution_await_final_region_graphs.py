"""Captured child-region implementations of the original await extraction.

The original caller, body drives, source calls, and final consumer come from
the existing await outcome execution fixture.  This fixture adds only the
actual child-region activations and their canonical call associations.
"""
from dataclasses import replace

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.common import Unresolved
from scar.ir.execution.ids import CallActivationID
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.program.model import ExitKind
from tests.fixtures.execution_await_outcome_graphs import await_outcome_execution
from tests.fixtures.execution_call_graphs import _activation
from tests.fixtures.program_await_final_region_graphs import await_final_region_program


_OCCURRENCE_TABLES = (
    "activations", "segments", "visits", "operations", "values", "uses", "transfers",
)


def await_final_region_execution(*, zero_cut=True, depth=1, instances=2,
                                 child_raised=False, wrong_child_exit=False,
                                 missing_child_call=None, missing_child_use=None,
                                 missing_return=None):
    """Return ``(program, model, details)`` with nested exact call occurrences.

    ``missing_child_call=(instance, parent_stage)`` omits only the association
    from that implementation frame to its nested callee.  ``missing_child_use``
    removes one selected child terminal's original payload Use occurrence.
    ``missing_return`` removes the outer implementation's selected terminal
    occurrence and marks that exact call completion unresolved.
    """
    if type(child_raised) is not bool or type(wrong_child_exit) is not bool:
        raise TypeError("child completion switches require exact bools")
    if type(instances) is not int or instances < 1:
        raise ValueError("instances must be a positive exact integer")
    for field, item in (("missing_child_call", missing_child_call),
                        ("missing_child_use", missing_child_use)):
        if item is not None and (type(item) is not tuple or len(item) != 2
                or any(type(value) is not int or value < 0 for value in item)):
            raise TypeError(f"{field} must be None or an exact (instance, stage) pair")
        if item is not None and item[0] >= instances:
            raise ValueError(f"{field} instance is outside the captured instances")
        if field == "missing_child_call" and item is not None and item[1] >= depth - 1:
            raise ValueError("missing_child_call must name a frame with a nested callee")
        if field == "missing_child_use" and item is not None and item[1] >= depth:
            raise ValueError("missing_child_use stage is outside the implementation depth")
    if missing_return is not None and (type(missing_return) is not int
                                       or not 0 <= missing_return < instances):
        raise ValueError("missing_return must select an exact captured instance")

    program, static = await_final_region_program(zero_cut=zero_cut, depth=depth,
        final_adapters=True, wrong_child_exit=wrong_child_exit)
    base_program, model, base_details = await_outcome_execution(
        zero_cut=zero_cut, instances=instances, extractor_raised=child_raised,
        attach_final_adapter=True)
    # The static extension preserves the original sites and uses; only the
    # parent extractor gains its declared callee and the helper regions are new.
    base_extract = next(row for row in base_program.operations if row.id == static["extract"].id)
    if (base_extract.terminator != static["extract"].terminator
            or base_extract.uses != static["extract"].uses):
        raise AssertionError("the final-region fixture must retain original parent ports")
    model = replace(model, snapshot=snapshot_for(program))
    source = base_details["source"]
    point = base_details["point"]
    selected_kind = ExitKind.RAISE if child_raised else ExitKind.NORMAL
    all_rows = {name: list(getattr(model, name)) for name in _OCCURRENCE_TABLES}
    call_rows = list(model.call_activations)
    examples = []

    for instance_number, example in enumerate(base_details["instances"]):
        thread = next(row.host_thread for row in model.segments
                      if row.activation == example["caller_activation"])
        frames = []
        for stage_number, definition in enumerate(static["stage_records"]):
            path = definition["paths"][selected_kind]
            label = f"await.final.instance.{instance_number}.stage.{stage_number}"
            rows, activation, visits, operation_occurrences = _activation(
                program, definition["region"].id, path, label, point, thread)
            for name in _OCCURRENCE_TABLES:
                all_rows[name].extend(rows[name])
            terminal_occurrence = operation_occurrences[definition["terminals"][selected_kind].id]
            frames.append({"definition": definition, "activation": activation,
                "visits": visits, "operations": operation_occurrences,
                "entry": visits[0], "completion": terminal_occurrence,
                "terminal": definition["terminals"][selected_kind]})

        root_link = CallActivation(
            CallActivationID(f"await.final.instance.{instance_number}.root"),
            example["extraction"], frames[0]["activation"], frames[0]["entry"],
            frames[0]["completion"], source)
        root_link_record = root_link
        root_link_index = len(call_rows)
        call_rows.append(root_link)
        nested_links = []
        for stage_number in range(len(frames) - 1):
            parent, child = frames[stage_number], frames[stage_number + 1]
            definition = parent["definition"]
            call_occurrence = parent["operations"][definition["operation"].id]
            link = CallActivation(
                CallActivationID(f"await.final.instance.{instance_number}.stage.{stage_number}.child"),
                call_occurrence, child["activation"], child["entry"], child["completion"], source)
            nested_links.append(link)
            if missing_child_call != (instance_number, stage_number):
                call_rows.append(link)

        if missing_return == instance_number:
            terminal_occurrence = frames[0]["completion"]
            all_rows["operations"] = [row for row in all_rows["operations"]
                if row.id != terminal_occurrence]
            all_rows["uses"] = [row for row in all_rows["uses"]
                if row.operation != terminal_occurrence]
            all_rows["values"] = [row for row in all_rows["values"]
                if row.origin != terminal_occurrence]
            root_link = replace(root_link, completion=Unresolved(
                "outer extraction implementation completion was not captured", point))
            call_rows[root_link_index] = root_link
            root_link_record = root_link

        if missing_child_use is not None and missing_child_use[0] == instance_number:
            stage_number = missing_child_use[1]
            frame = frames[stage_number]
            owned = frame["definition"]["terminal_payloads"][selected_kind]
            occurrence = frame["operations"][owned.operation]
            all_rows["uses"] = [row for row in all_rows["uses"]
                if (row.operation, row.use) != (occurrence, owned.use)]

        examples.append({**example, "implementation_frames": tuple(frames),
            "implementation_root_call": root_link_record,
            "implementation_nested_calls": tuple(nested_links),
            "implementation_kind": selected_kind,
            "implementation_missing_child_call": (missing_child_call is not None
                and missing_child_call[0] == instance_number),
            "implementation_missing_return": missing_return == instance_number,
            "implementation_missing_child_use": (missing_child_use
                if missing_child_use is not None and missing_child_use[0] == instance_number else None)})

    model = replace(model, snapshot=snapshot_for(program),
        **{name: tuple(rows) for name, rows in all_rows.items()},
        call_activations=tuple(call_rows))
    return program, model, {**base_details, "static": static,
        "implementation_instances": tuple(examples), "child_raised": child_raised,
        "wrong_child_exit": wrong_child_exit,
        "missing_child_call": missing_child_call,
        "missing_child_use": missing_child_use,
        "missing_return": missing_return}


__all__ = ["await_final_region_execution"]
