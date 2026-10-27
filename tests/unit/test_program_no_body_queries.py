"""Predicate and no-body queries return existing endpoints, not evaluated guards."""
from dataclasses import replace

import pytest

from scar.ir.program.codec import dumps
from scar.ir.program.ids import OperationID
from scar.ir.program.model import AccessMode, OperationResult, TerminatorKind
from scar.ir.program.queries import ProgramIndex
from tests.fixtures.program_no_body_graphs import no_body_program
from tests.fixtures.program_publication_graphs import publication_program


@pytest.mark.parametrize("receiver", ["BODY", "ASYNC_REQUEST"])
@pytest.mark.parametrize("direct_owner", [False, True])
def test_predicate_query_returns_original_roles_bool_actual_branch_and_read_accesses(receiver, direct_owner):
    graph = no_body_program(receiver=receiver, direct_owner=direct_owner, strict_subset=True, extra_domain=True)
    before = dumps(graph)
    index = ProgramIndex(graph)
    row = graph.created_close_tests[0]
    assert index.created_close_test(row.operation) is row
    view = index.created_close_predicate(row.operation)
    assert view.test is row
    assert view.instance is index.use_site(row.instance)
    assert view.scheduler_request is index.use_site(row.scheduler_request)
    assert view.effective_request is index.use_site(row.effective_request)
    assert view.session is (None if row.session is None else index.use_site(row.session))
    assert view.result is index.values[row.result]
    assert view.result.data_type == "builtins.bool"
    assert type(view.result.origin) is OperationResult
    assert view.result.origin.operation == row.operation
    assert view.branch is index.operations[view.branch.id]
    assert view.branch.terminator.kind is TerminatorKind.BRANCH
    assert view.condition is index.use_site(view.branch.terminator.condition)
    assert view.condition.use.value == row.result
    assert view.true_successor is view.branch.terminator.successors[0]
    assert view.false_successor is view.branch.terminator.successors[1]
    for item, access in zip(view.accesses, index.operations[row.operation].accesses):
        assert item.access is access
        assert access.mode is AccessMode.READ
        assert item.before is index.use_site(access.before)
        assert item.after is None
    assert dumps(graph) == before


@pytest.mark.parametrize("receiver", ["BODY", "ASYNC_REQUEST"])
def test_finish_query_follows_exact_true_edge_and_preserves_real_written_after(receiver):
    graph = no_body_program(receiver=receiver, strict_subset=True, extra_domain=True)
    index = ProgramIndex(graph)
    finish = graph.no_body_finishes[0]
    assert index.no_body_finish(finish.operation) is finish
    view = index.no_body_publication(finish.operation)
    assert view.finish is finish
    assert view.instance is index.use_site(finish.instance)
    assert finish.precondition.operation == view.predicate.branch.id
    assert finish.precondition.successor_index == 0
    block = next(block for region in graph.regions for block in region.blocks
                 if block.id == view.predicate.true_successor.block)
    assert block.operations[0] == finish.operation
    assert any(item.after is not None for item in view.accesses)
    for item, access in zip(view.accesses, index.operations[finish.operation].accesses):
        assert item.access is access
        assert item.before is index.use_site(access.before)
        if access.after is not None:
            assert item.after is index.values[access.after]
            assert item.after.origin.operation == finish.operation
            assert index.producer(access.after) is item.after.origin
        else:
            assert item.after is None


def test_predicate_only_does_not_fabricate_finish_or_body_outcome():
    graph = no_body_program(predicate_only=True)
    index = ProgramIndex(graph)
    test = graph.created_close_tests[0]
    assert graph.no_body_finishes == ()
    assert index.created_close_predicate(test.operation)
    assert index.no_body_finish(test.operation) is None
    assert index.no_body_publication(test.operation) is None


def test_explicit_association_uses_its_real_normal_ports_without_merging_scheduler_and_latent():
    graph = no_body_program(receiver="ASYNC_REQUEST", association=True)
    index = ProgramIndex(graph)
    row = graph.created_close_tests[0]
    view = index.created_close_predicate(row.operation)
    read = graph.request_association_reads[0]
    body = index.normal_result(read.operation, read.body_result)
    latent = index.normal_result(read.operation, read.latent_result)
    assert view.instance.use.value == body.id
    assert view.effective_request.use.value == latent.id
    assert view.scheduler_request is index.use_site(row.scheduler_request)
    assert view.effective_request is index.use_site(row.effective_request)
    assert view.effective_request.use.id != view.scheduler_request.use.id
    assert index.request_association_read(read.operation) is read


def test_existing_publication_has_no_implicit_no_body_records_and_queries_remain_strict():
    graph = publication_program()
    index = ProgramIndex(graph)
    op = graph.body_outcome_commits[0].operation
    assert index.created_close_test(op) is None
    assert index.created_close_predicate(op) is None
    assert index.no_body_finish(op) is None
    assert index.no_body_publication(op) is None
    assert index.body_publication(op)
    for method in (index.created_close_test, index.created_close_predicate,
                   index.no_body_finish, index.no_body_publication):
        with pytest.raises(TypeError):
            method("not-an-operation-id")
        with pytest.raises(KeyError):
            method(OperationID("missing"))


def test_query_construction_cannot_bypass_validation_of_finish_edge():
    graph = no_body_program()
    finish = graph.no_body_finishes[0]
    invalid = replace(finish, precondition=replace(finish.precondition, successor_index=1))
    with pytest.raises(ValueError):
        ProgramIndex(replace(graph, no_body_finishes=(invalid,)))
