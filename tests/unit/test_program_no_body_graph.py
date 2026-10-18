"""D2.2 exact predicate/CFG/current-state joins, without executing a guard."""
from dataclasses import replace

import pytest

from scar.ir.program.control import ProtocolValueKind
from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, BlockArgument, DataValue, Operation, OperationResult,
    ProtocolValue, ReferenceValue, StateVersionValue, TerminatorKind, Use, UseRole,
)
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_no_body_graphs import no_body_program


def op(graph, identity):
    return next(row for row in graph.operations if row.id == identity)


def change(graph, operation):
    return replace(graph, operations=tuple(operation if row.id == operation.id else row
                                           for row in graph.operations))


def codes(graph):
    return {issue.code for issue in validate(graph)}


def use_value(operation, identity):
    return next(use.value for use in operation.uses if use.id == identity)


def add_input(graph, *, raw=False):
    interface, = graph.driver_interfaces
    region = next(row for row in graph.regions if row.id == interface.region)
    entry = next(block for block in region.blocks if block.id == region.entry)
    identity = ValueID("independent.external.input")
    origin = BlockArgument(entry.id, len(entry.arguments))
    value = (ProtocolValue(identity, region.id, origin, ProtocolValueKind.RAW_DRIVER_REQUEST)
             if raw else ReferenceValue(identity, region.id, origin))
    graph = replace(graph, values=(*graph.values, value), regions=tuple(
        replace(row, blocks=tuple(replace(block, arguments=(*block.arguments, identity))
                                  if block.id == entry.id else block for block in row.blocks))
        if row.id == region.id else row for row in graph.regions))
    return graph, identity


def replace_use(operation, identity, value):
    return replace(operation, uses=tuple(replace(use, value=value) if use.id == identity else use
                                          for use in operation.uses))


@pytest.mark.parametrize("receiver", ("BODY", "ASYNC_REQUEST"))
@pytest.mark.parametrize("target", ("start", "value", "packet"))
@pytest.mark.parametrize("direct", (False, True))
def test_true_mark_and_real_false_drive_paths_preserve_roles_sources_and_current_domains(receiver, target, direct):
    graph = no_body_program(receiver=receiver, target=target, direct_owner=direct,
                            strict_subset=True, extra_domain=True)
    require_valid(graph)
    test, = graph.created_close_tests
    finish, = graph.no_body_finishes
    predicate = op(graph, test.operation)
    branch = op(graph, finish.precondition.operation)
    assert branch.terminator.kind is TerminatorKind.BRANCH
    assert use_value(branch, branch.terminator.condition) == test.result
    assert finish.precondition.successor_index == 0
    true_block = next(block for region in graph.regions for block in region.blocks
                      if block.id == branch.terminator.successors[0].block)
    assert true_block.operations[0] == finish.operation
    assert op(graph, true_block.operations[-1]).terminator.kind is TerminatorKind.RETURN
    # The ordinary alternative and its actual body source publications survive.
    assert graph.body_drives and graph.final_body_gates and graph.body_outcome_commits
    assert all(row.outcome.drive == graph.body_drives[0].operation for row in graph.body_outcome_commits)
    assert {access.location for access in predicate.accesses} == set(graph.driver_interfaces[0].lifecycle)
    writes = {access.location for access in op(graph, finish.operation).accesses
              if access.mode is AccessMode.READ_WRITE}
    assert writes < set(graph.driver_interfaces[0].lifecycle)


@pytest.mark.parametrize("create", (False, True))
def test_external_or_local_creation_does_not_require_unique_static_creator(create):
    graph = no_body_program(create=create)
    require_valid(graph)
    assert bool(graph.resumable_creates) is create


def test_multiple_creates_do_not_require_a_unique_static_creation_source():
    from tests.fixtures.program_driver_graphs import multiple_creates_program

    graph = no_body_program(base_graph=multiple_creates_program())
    require_valid(graph)
    assert len(graph.resumable_creates) == 2


@pytest.mark.parametrize("receiver", ("BODY", "ASYNC_REQUEST"))
def test_test_without_finish_is_valid_and_does_not_invent_body_completion(receiver):
    graph = no_body_program(receiver=receiver, predicate_only=True)
    require_valid(graph)
    assert graph.created_close_tests and not graph.no_body_finishes
    assert not hasattr(graph.created_close_tests[0], "finished")


def test_async_association_is_real_normal_ports_with_a_real_failure_path():
    graph = no_body_program(receiver="ASYNC_REQUEST", association=True)
    require_valid(graph)
    read, = graph.request_association_reads
    operation = op(graph, read.operation)
    assert operation.terminator.kind is TerminatorKind.INVOKE
    assert len(operation.completions) == 2
    assert graph.created_close_tests[0].session is not None


@pytest.mark.parametrize("table,code", (("created_close_tests", "no_body_test_operation"),
                                       ("no_body_finishes", "no_body_operation")))
def test_metadata_does_not_invent_a_missing_operation(table, code):
    graph = no_body_program()
    row, = getattr(graph, table)
    assert code in codes(replace(graph, **{table: (replace(row, operation=OperationID("missing")),)}))


def test_finish_cannot_exist_without_its_predicate_or_use_false_edge():
    graph = no_body_program()
    finish, = graph.no_body_finishes
    assert "no_body_precondition" in codes(replace(graph, created_close_tests=()))
    bad = replace(finish, precondition=replace(finish.precondition, successor_index=1))
    assert "no_body_precondition" in codes(replace(graph, no_body_finishes=(bad,)))


@pytest.mark.parametrize("role,raw", (("instance", False), ("scheduler_request", True),
                                    ("effective_request", True)))
def test_body_fixed_roles_cannot_be_replaced_by_an_unrelated_same_typed_input(role, raw):
    graph, unrelated = add_input(no_body_program(), raw=raw)
    row, = graph.created_close_tests
    assert "no_body_test_roles" in codes(change(graph, replace_use(op(graph, row.operation), getattr(row, role), unrelated)))


def test_async_fixed_session_cannot_be_replaced_but_external_body_and_latent_are_not_illtyped():
    graph, external = add_input(no_body_program(receiver="ASYNC_REQUEST"))
    row, = graph.created_close_tests
    assert "no_body_test_roles" in codes(change(graph, replace_use(op(graph, row.operation), row.session, external)))
    # A wrong association can be false. Static typing must not invent a raise
    # or reject B merely because it is not the fixed R role.
    graph = change(graph, replace_use(op(graph, row.operation), row.instance, external))
    finish, = graph.no_body_finishes
    graph = change(graph, replace_use(op(graph, finish.operation), finish.instance, external))
    require_valid(graph)


def test_async_effective_request_may_equal_scheduler_without_claiming_guard_is_true():
    graph = no_body_program(receiver="ASYNC_REQUEST")
    row, = graph.created_close_tests
    predicate = op(graph, row.operation)
    graph = change(graph, replace_use(predicate, row.effective_request, use_value(predicate, row.scheduler_request)))
    require_valid(graph)


def test_owner_same_type_or_same_state_location_is_insufficient():
    graph, unrelated = add_input(no_body_program())
    row, = graph.no_body_finishes
    assert "no_body_owner" in codes(change(graph, replace_use(op(graph, row.operation), row.instance, unrelated)))


def test_ordinary_true_edge_preserves_legacy_use_id_subclass_copy():
    class LegacyUse(UseID):
        pass

    graph = no_body_program()
    finish, = graph.no_body_finishes
    branch = op(graph, finish.precondition.operation)
    true = branch.terminator.successors[0]
    landing = next(block for region in graph.regions for block in region.blocks if block.id == true.block)
    owner = use_value(op(graph, finish.operation), finish.instance)
    actual = true.arguments[landing.arguments.index(owner)]
    legacy = LegacyUse(actual.value)
    uses = tuple(replace(use, id=legacy) if use.id == actual else use for use in branch.uses)
    edges = tuple(replace(edge, arguments=tuple(legacy if item == actual else item for item in edge.arguments))
                  for edge in branch.terminator.successors)
    require_valid(change(graph, replace(branch, uses=uses, terminator=replace(branch.terminator, successors=edges))))


@pytest.mark.parametrize("site,code", (("test", "no_body_test_branch"), ("finish", "no_body_landing")))
def test_even_pure_work_cannot_split_test_branch_or_precede_private_mark(site, code):
    graph = no_body_program()
    target = graph.created_close_tests[0].operation if site == "test" else graph.no_body_finishes[0].operation
    extra = Operation(OperationID("intervening.work"), "ordinary work", (Behavior.CONTROL,), effects_complete=True)
    regions = []
    for region in graph.regions:
        blocks = []
        for block in region.blocks:
            ids = list(block.operations)
            if target in ids:
                ids.insert(ids.index(target) + (1 if site == "test" else 0), extra.id)
            blocks.append(replace(block, operations=tuple(ids)))
        regions.append(replace(region, blocks=tuple(blocks)))
    assert code in codes(replace(graph, operations=(*graph.operations, extra), regions=tuple(regions)))


@pytest.mark.parametrize("site,code", (("test", "no_body_test_shape"), ("finish", "no_body_shape")))
@pytest.mark.parametrize("complete", (False, True))
def test_metadata_cannot_hide_unknown_effects_or_copy_sync_drop_work(site, code, complete):
    graph = no_body_program()
    identity = graph.created_close_tests[0].operation if site == "test" else graph.no_body_finishes[0].operation
    operation = op(graph, identity)
    changed = (replace(operation, behaviors=(*operation.behaviors, Behavior.ORDER)) if complete
               else replace(operation, effects_complete=False))
    assert code in codes(change(graph, changed))


@pytest.mark.parametrize("unknown", (False, True))
def test_guard_branch_itself_cannot_hide_unknown_effects(unknown):
    graph = no_body_program()
    branch = op(graph, graph.no_body_finishes[0].precondition.operation)
    branch = (replace(branch, effects_complete=False) if unknown
              else replace(branch, behaviors=(*branch.behaviors, Behavior.MEMORY)))
    assert "no_body_branch_shape" in codes(change(graph, branch))


def test_bool_from_an_unrelated_input_cannot_replace_the_test_result_condition():
    graph = no_body_program()
    test, = graph.created_close_tests
    finish, = graph.no_body_finishes
    predicate = op(graph, test.operation)
    other = ValueID("unrelated.bool")
    extra = DataValue(other, next(value.region for value in graph.values if value.id == test.result),
                      OperationResult(predicate.id, 1), "builtins.bool")
    graph = replace(graph, values=(*graph.values, extra))
    graph = change(graph, replace(predicate, results=(*predicate.results, other)))
    branch = op(graph, finish.precondition.operation)
    graph = change(graph, replace_use(branch, branch.terminator.condition, other))
    assert {"no_body_test_result", "no_body_test_branch"} <= codes(graph)


def test_unscoped_metadata_cannot_assert_no_body_completion():
    graph = no_body_program()
    assert codes(replace(graph, driver_lifecycles=()))


def test_stale_state_cannot_be_used_even_when_owner_and_guard_match():
    graph = no_body_program()
    finish, = graph.no_body_finishes
    operation = op(graph, finish.operation)
    predicate = op(graph, graph.created_close_tests[0].operation)
    access = operation.accesses[0]
    old = next(use_value(predicate, item.before) for item in predicate.accesses if item.location == access.location)
    assert "stale_state" in codes(change(graph, replace_use(operation, access.before, old)))


def test_finish_must_write_real_body_state():
    graph = no_body_program()
    finish, = graph.no_body_finishes
    operation = op(graph, finish.operation)
    # Preserve core state by rewiring consumers to unchanged current versions.
    substitution = {access.after: use_value(operation, access.before)
                    for access in operation.accesses if access.after is not None}
    graph = replace(graph, values=tuple(value for value in graph.values if value.id not in substitution),
                    operations=tuple(replace(row, uses=tuple(replace(use, value=substitution.get(use.value, use.value))
                                                            for use in row.uses)) for row in graph.operations))
    operation = op(graph, finish.operation)
    operation = replace(operation, results=(), accesses=tuple(replace(access, mode=AccessMode.READ, after=None)
                                                             for access in operation.accesses))
    assert "no_body_writes" in codes(change(graph, operation))


@pytest.mark.parametrize("extra", ("input", "result"))
def test_finish_cannot_hide_additional_input_or_scalar_work(extra):
    graph = no_body_program()
    row, = graph.no_body_finishes
    operation = op(graph, row.operation)
    if extra == "input":
        duplicate = Use(UseID("unrelated.input"), use_value(operation, row.instance), UseRole.REFERENCE)
        changed = replace(operation, uses=(*operation.uses, duplicate))
        expected = "no_body_uses"
    else:
        value = DataValue(ValueID("unrelated.result"), graph.driver_interfaces[0].region,
                          OperationResult(operation.id, len(operation.results)), "builtins.int")
        graph = replace(graph, values=(*graph.values, value))
        changed = replace(operation, results=(*operation.results, value.id))
        expected = "no_body_results"
    assert expected in codes(change(graph, changed))


def test_predicate_cannot_omit_a_lifecycle_domain():
    graph = no_body_program(strict_subset=True)
    row, = graph.created_close_tests
    operation = op(graph, row.operation)
    omitted = operation.accesses[-1]
    changed = replace(operation, accesses=operation.accesses[:-1],
                      uses=tuple(use for use in operation.uses if use.id != omitted.before))
    assert "no_body_test_access" in codes(change(graph, changed))
