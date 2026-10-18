"""Finite adversarial IR-only review of D2.1; no source/runtime claims."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys
import traceback

from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.model import BlockArgument, ReferenceValue
from scar.ir.program.validation import validate
from tests.fixtures.program_publication_graphs import publication_program
from tests.fixtures.program_resumption_graphs import resumption_cleanup_invoke_program


def change_operation(graph, operation):
    return replace(graph, operations=tuple(operation if old.id == operation.id else old
                                           for old in graph.operations))


def operation(graph, identity):
    return next(op for op in graph.operations if op.id == identity)


def multiple_sources():
    return publication_program(target="value", body_graph=resumption_cleanup_invoke_program())


def crosswire_two_sources():
    graph = multiple_sources()
    first, second = graph.body_outcome_commits
    return replace(graph, body_outcome_commits=(replace(first, outcome=second.outcome),
                                               replace(second, outcome=first.outcome)))


def omit_unaccessed_lifecycle_domain():
    graph = publication_program(strict_subset=True)
    row, = graph.body_outcome_commits
    commit = operation(graph, row.operation)
    write, read = commit.accesses
    return change_operation(graph, replace(commit, accesses=(write,),
        uses=tuple(use for use in commit.uses if use.id != read.before)))


def second_same_owner_formal():
    graph = publication_program(target="value")
    row, = graph.body_outcome_commits
    drive = operation(graph, row.outcome.drive)
    edge, = drive.terminator.successors
    landing = next(block for region in graph.regions for block in region.blocks if block.id == edge.block)
    commit = operation(graph, row.operation)
    instance = next(use for use in commit.uses if use.id == row.instance)
    prior_actual = edge.arguments[landing.arguments.index(instance.value)]
    prior_use = next(use for use in drive.uses if use.id == prior_actual)
    extra_actual = replace(prior_use, id=UseID("review.second_owner.actual"))
    owner = next(value for value in graph.values if value.id == instance.value)
    alias = replace(owner, id=ValueID("review.second_owner.formal"),
                    origin=BlockArgument(landing.id, len(landing.arguments)))
    assert isinstance(alias, ReferenceValue)
    graph = replace(graph, values=(*graph.values, alias), regions=tuple(
        replace(region, blocks=tuple(replace(block, arguments=(*block.arguments, alias.id))
                                     if block.id == landing.id else block for block in region.blocks))
        for region in graph.regions))
    graph = change_operation(graph, replace(drive, uses=(*drive.uses, extra_actual),
        terminator=replace(drive.terminator, successors=(
            replace(edge, arguments=(*edge.arguments, extra_actual.id)),))))
    return change_operation(graph, replace(commit, uses=tuple(
        replace(use, value=alias.id) if use.id == row.instance else use for use in commit.uses)))


def foreign_owned_use():
    graph = publication_program()
    row, = graph.body_outcome_commits
    drive, = graph.body_drives
    return replace(graph, body_outcome_commits=(replace(row, instance=drive.instance),))


def missing_commit_operation():
    graph = publication_program()
    row, = graph.body_outcome_commits
    return replace(graph, body_outcome_commits=(replace(row, operation=OperationID("review.missing")),))


def corrupt_nested_source():
    graph = publication_program()
    object.__setattr__(graph.body_outcome_commits[0].outcome, "source", "not-an-operation-id")
    return graph


def corrupt_scope_region():
    graph = publication_program()
    object.__setattr__(graph.driver_lifecycles[0], "region", "not-a-region-id")
    return graph


def corrupt_duplicate_metadata():
    graph = publication_program()
    object.__setattr__(graph, "body_outcome_commits", graph.body_outcome_commits * 2)
    return graph


CASES = (
    ("two_distinct_return_raise_sources", multiple_sources, set()),
    ("write_subset_omits_unaccessed_read_domain", omit_unaccessed_lifecycle_domain, set()),
    ("same_owner_two_formals_choose_second", second_same_owner_formal, set()),
    ("source_references_swapped_across_private_landings", crosswire_two_sources, {"publication_landing"}),
    ("owner_use_owned_by_drive_not_commit", foreign_owned_use, {"publication_owner"}),
    ("missing_commit_operation", missing_commit_operation, {"publication_operation"}),
    ("mutated_nested_source_type", corrupt_nested_source, {"schema"}),
    ("mutated_scope_region_type", corrupt_scope_region, {"schema"}),
    ("mutated_duplicate_commit_rows", corrupt_duplicate_metadata, {"schema"}),
)


def main():
    sources = (
        "scar/ir/program/lifecycle_validation.py", "scar/ir/program/lifecycle.py",
        "scar/ir/program/validation.py", "scar/ir/program/model.py",
        "tests/fixtures/program_publication_graphs.py", "tests/unit/test_program_publication_graph.py",
    )
    result = {"python": sys.version, "executable": sys.executable,
              "scope": "nine finite IR/schema review cases only; no F/P/product-suite/source/runtime claim",
              "script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
              "source_sha256": {source: sha256(Path(source).read_bytes()).hexdigest() for source in sources},
              "cases": []}
    for name, factory, expected in CASES:
        item = {"name": name, "expected_required_codes": sorted(expected)}
        try:
            issues = validate(factory())
            actual = {issue.code for issue in issues}
            item.update(actual_codes=sorted(actual),
                        issues=[{"code": issue.code, "path": issue.path, "message": issue.message}
                                for issue in issues],
                        passed=(expected <= actual if expected else not actual))
        except Exception as error:
            item.update(passed=False, unexpected_exception=repr(error), traceback=traceback.format_exc())
        result["cases"].append(item)
    result["passed"] = all(item["passed"] for item in result["cases"])
    rendered = json.dumps(result, indent=2, sort_keys=True)
    Path(__file__).with_suffix(".json").write_text(rendered + "\n")
    print(rendered)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
