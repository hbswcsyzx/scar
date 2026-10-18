"""Canonical effects resolve original core endpoints without owning work policy."""
from dataclasses import replace

import pytest

from scar.ir.execution.common import Unresolved
from scar.ir.execution.effects import resolve_canonical_effect
from scar.ir.execution.ids import ValueOccurrenceID
from scar.ir.execution.production_validation import _effect as resolve_production_effect
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import _analyze, validate
from scar.ir.program.model import BlockArgument, CompletionResult
from scar.ir.v2.common import Completeness
from tests.fixtures.execution_effect_reads import invoke_state_content_read
from tests.fixtures.execution_work_graphs import invoke_work_execution, ordinary_work_execution


@pytest.mark.parametrize("raised", (False, True))
def test_shared_resolver_returns_original_actual_invoke_ports(raised):
    program, model, value_graphs = invoke_work_execution(raised=raised)
    effect = model.submissions[0].effects[0]
    report, ctx = _analyze(model, program, value_graphs=value_graphs)
    assert report.valid

    view = resolve_canonical_effect(ctx, effect, "test.effect")
    operation = next(row for row in program.operations if row.id.value == "invoke.call")
    occurrence = next(row for row in model.operations if row.id == effect.invocation)
    edge = int(raised)
    successor = operation.terminator.successors[edge]
    assert view["reference"] is effect
    assert view["operation"] is occurrence
    assert view["input"] is ctx.uses[effect.invocation, effect.state_input.use]
    assert view["declared_successor"] is successor
    assert view["actual_successor"] is successor
    assert view["actual_transfer"] is ctx.outgoing[effect.invocation]
    assert view["declared_result"] == CompletionResult(effect.post.result_index)
    assert view["formal"] is ctx.values[effect.post.formal]
    assert view["formal"].id == ValueOccurrenceID(
        "1.invoke.failure.world" if raised else "1.invoke.normal.world")
    assert view["activation"] == ctx.activation_of(effect.invocation)
    assert view["run"] == model.runs[0].id


def test_unresolved_invoke_post_preserves_actual_edge_without_inventing_formal():
    program, model, value_graphs = invoke_work_execution(raised=True)
    effect = model.submissions[0].effects[0]
    unresolved = Unresolved("actual state result not captured", model.activations[0].entry)
    changed_effect = replace(effect, post=unresolved)
    changed = replace(model,
        submissions=(replace(model.submissions[0], effects=(changed_effect,)),),
        outcomes=(replace(model.outcomes[0], effect_frontier=(changed_effect,)),))
    report, ctx = _analyze(changed, program, value_graphs=value_graphs)
    assert report.valid

    view = resolve_canonical_effect(ctx, changed_effect, "test.unresolved")
    assert view["declared_post"] is unresolved
    assert view["actual_transfer"] is ctx.outgoing[effect.invocation]
    assert view["actual_successor_index"] == 1
    assert view["actual_successor"] is not None
    assert view["declared_successor"] is None
    assert view["declared_result"] is None
    assert view["formal"] is None
    adapted = resolve_production_effect(ctx, changed_effect, "test.unresolved.production")
    assert adapted["after"] is None
    assert adapted["transfer"] is ctx.outgoing[effect.invocation]


def test_access_view_keeps_original_mode_and_state_endpoints():
    program, model, value_graphs = ordinary_work_execution()
    effect = model.submissions[0].effects[0]
    report, ctx = _analyze(model, program, value_graphs=value_graphs)
    assert report.valid

    view = resolve_canonical_effect(ctx, effect, "test.access")
    occurrence = ctx.occurrences[effect.operation]
    operation = ctx.core_operations[occurrence.operation]
    access = operation.accesses[effect.index]
    assert view["access"] is access
    assert view["mode"] is access.mode
    assert view["before"] is ctx.uses[effect.operation, access.before]
    assert view["after"] is ctx.results[effect.operation, access.after]


def test_host_invoke_content_read_and_public_projection_need_no_work_ticket():
    program, model, value_graphs, details = invoke_state_content_read(consumer="host")
    assert not model.submissions and not model.outcomes
    report = validate(model, program, value_graphs=value_graphs)
    assert report.valid
    codes = {row.code for row in report.issues}
    gaps = {row.code for row in report.gaps}
    assert "content_invoke_effect" not in codes
    assert "content_invoke_read_unverified" in gaps

    index = ExecutionIndex(model, program, value_graphs=value_graphs)
    effect = details["effect"]
    projection = index.canonical_effect(effect)
    assert projection["kind"] == "invoke_boundary"
    assert projection["reference"] == effect
    assert projection["actual_transfer"] is not None


def test_public_projection_and_production_adapter_use_the_actual_formal():
    program, model, value_graphs = invoke_work_execution(raised=True)
    effect = model.submissions[0].effects[0]
    report, ctx = _analyze(model, program, value_graphs=value_graphs)
    assert report.valid

    projection = ExecutionIndex(model, program, value_graphs=value_graphs).canonical_effect(effect)
    adapted = resolve_production_effect(ctx, effect, "test.production")
    assert projection["post"] == ctx.values[effect.post.formal]
    assert adapted["after"] is ctx.values[effect.post.formal]
    assert projection["successor"].kind.name == "RAISE"


@pytest.mark.parametrize("malformation", ("wrong_actual_edge", "wrong_result", "foreign_formal"))
def test_public_projection_rejects_malformed_completion_without_mutating_context(malformation):
    program, model, value_graphs = invoke_work_execution(raised=True)
    effect = model.submissions[0].effects[0]
    index = ExecutionIndex(model, program, value_graphs=value_graphs)
    ctx = index._ctx
    before_report_gaps = tuple(index.report.gaps)
    before_issues = tuple(ctx.issues)
    before_gaps = tuple(ctx.gaps)

    if malformation == "wrong_actual_edge":
        post = replace(effect.post, successor_index=0)
    elif malformation == "wrong_result":
        post = replace(effect.post, result_index=1)
    else:
        operation = next(row for row in program.operations if row.id.value == "invoke.call")
        sibling = operation.terminator.successors[0]
        sibling_block = next(block for region in program.regions for block in region.blocks
                             if block.id == sibling.block)
        sibling_formal = next(value for value, argument in
                              zip(sibling_block.arguments, sibling.arguments, strict=True)
                              if type(argument) is CompletionResult
                              and argument.index == effect.post.result_index)
        # The declared path visits block 1 after the entry; this sibling formal
        # is a different completion landing and is not present in the actual trace.
        foreign = ValueOccurrenceID(f"1.{sibling_formal.value}")
        post = replace(effect.post, formal=foreign)

    malformed = replace(effect, post=post)
    with pytest.raises(ValueError, match="invoke_"):
        index.canonical_effect(malformed)
    assert tuple(index.report.gaps) == before_report_gaps
    assert tuple(ctx.issues) == before_issues
    assert tuple(ctx.gaps) == before_gaps


@pytest.mark.parametrize("coverage", (Completeness.PARTIAL, Completeness.UNKNOWN))
def test_resource_consumer_ticket_absence_from_partial_list_is_a_gap_not_an_issue(coverage):
    program, model, value_graphs, _ = invoke_state_content_read(
        consumer="work", other_ticket_coverage=coverage)
    report = validate(model, program, value_graphs=value_graphs)
    assert report.valid
    assert "content_invoke_effect_unresolved" in {row.code for row in report.gaps}
    assert "content_invoke_effect" not in {row.code for row in report.issues}


def test_resource_consumer_ticket_absence_from_complete_list_is_an_issue():
    program, model, value_graphs, _ = invoke_state_content_read(
        consumer="work", other_ticket_coverage=Completeness.COMPLETE)
    report = validate(model, program, value_graphs=value_graphs)
    assert "content_invoke_effect" in {row.code for row in report.issues}
