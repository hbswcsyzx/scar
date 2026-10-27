"""Design witness using existing INVOKE/SSA, not a BodyDrive implementation.

The second opaque INVOKE stands for a future dedicated BodyDrive only to check
the proposed corridor's canonical state/reference wiring. Local draft checks
are explicitly separate from current product validation. No Python callable,
runtime admission, saved frame, resumption or native equivalence is established.
"""
from dataclasses import replace
import json
from pathlib import Path

from scar.ir.program import (
    Behavior, Block, BlockArgument, BlockID, CompletionResult,
    CompletionSignature, CompletionSuccessor, ExitKind, Operation,
    OperationID, ReferenceValue, StateVersionValue, Terminator, TerminatorKind,
    Use, UseID, UseRole, ValueID, dumps, loads,
)
from scar.ir.program.validation import require_valid, validate
from tests.unit.test_program_completions_adversarial import _invoke_graph, _forward_slot


GATE, DRIVE = OperationID('main.invoke'), OperationID('proposed.body.step')


def corridor():
    graph = _forward_slot(_invoke_graph(), ExitKind.NORMAL, 0)
    gate = next(op for op in graph.operations if op.id == GATE)
    target = next(e.block for e in gate.terminator.successors if e.kind is ExitKind.NORMAL)
    region = graph.regions[0]
    landing = next(b for b in region.blocks if b.id == target)
    uses = (
        Use(UseID('step.owner'), landing.arguments[0], UseRole.REFERENCE),
        Use(UseID('step.world'), landing.arguments[1], UseRole.STATE_CONTENT),
    )
    values, blocks, terminals, edges = [], [], [], []
    for kind in (ExitKind.NORMAL, ExitKind.RAISE):
        stem = 'step.' + kind.value.lower()
        block_id = BlockID(stem)
        ref_id, state_id = ValueID(stem + '.value'), ValueID(stem + '.world')
        values.extend((
            ReferenceValue(ref_id, graph.root, BlockArgument(block_id, 0)),
            StateVersionValue(state_id, graph.root, BlockArgument(block_id, 1), graph.locations[0].id),
        ))
        final_uses = (Use(UseID(stem + '.value'), ref_id, UseRole.REFERENCE),
                      Use(UseID(stem + '.world'), state_id, UseRole.STATE_CONTENT))
        terminal = Operation(OperationID(stem + '.done'), stem, (Behavior.CONTROL,),
            final_uses, effects_complete=True, terminator=Terminator(
                TerminatorKind.RETURN if kind is ExitKind.NORMAL else TerminatorKind.RAISE,
                exit=kind.value.lower(), values=tuple(u.id for u in final_uses)))
        blocks.append(Block(block_id, (ref_id, state_id), (terminal.id,)))
        terminals.append(terminal)
        edges.append(CompletionSuccessor(kind, block_id, (CompletionResult(0), CompletionResult(1))))
    drive = Operation(DRIVE, 'opaque placeholder, NOT BodyDrive',
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), uses,
        terminator=Terminator(TerminatorKind.INVOKE, tuple(edges)),
        invoke_arguments=tuple(u.id for u in uses), completions=tuple(
            CompletionSignature(port.kind, port.types) for port in region.exits))
    updated_blocks = tuple(replace(b, operations=(drive.id,)) if b.id == target else b
                           for b in region.blocks)
    graph = replace(graph,
        regions=(replace(region, blocks=(*updated_blocks, *blocks)),),
        operations=tuple(op for op in graph.operations if op.id not in landing.operations)
                   + (drive, *terminals), values=(*graph.values, *values))
    require_valid(graph)
    return graph


def draft_issues(graph):
    """Proposed shape/reference conditions only; not a product validator."""
    operations = {op.id: op for op in graph.operations}
    blocks = {b.id: b for r in graph.regions for b in r.blocks}
    values = {v.id: v for v in graph.values}
    gate, drive = operations[GATE], operations[DRIVE]
    normal = next(e for e in gate.terminator.successors if e.kind is ExitKind.NORMAL)
    block = blocks[normal.block]
    errors = []
    if block.operations != (DRIVE,):
        errors.append('not-immediate-single-operation-corridor')
    gate_inputs = {u.id: u for u in gate.uses}
    owner_actual = gate_inputs[gate.invoke_arguments[0]].value
    owner = next(u for u in drive.uses if u.id == UseID('step.owner'))
    if owner.value not in block.arguments:
        errors.append('owner-not-corridor-formal')
    else:
        edge_actual = normal.arguments[block.arguments.index(owner.value)]
        if (not isinstance(edge_actual, UseID)
                or gate_inputs[edge_actual].value != owner_actual):
            errors.append('owner-not-exact-forwarded-input')
    state = next(u for u in drive.uses if u.id == UseID('step.world'))
    if (state.value not in block.arguments
            or not isinstance(normal.arguments[block.arguments.index(state.value)], CompletionResult)
            or not isinstance(values[state.value], StateVersionValue)):
        errors.append('state-not-gate-normal-poststate')
    return errors


def change_op(graph, operation, **changes):
    return replace(graph, operations=tuple(replace(op, **changes) if op.id == operation else op
                                           for op in graph.operations))


def main():
    rows = []

    def check(name, graph, core_codes=(), draft_codes=()):
        actual_core = {i.code for i in validate(graph)}
        actual_draft = set(draft_issues(graph))
        assert actual_core == set(core_codes), (name, actual_core)
        assert actual_draft == set(draft_codes), (name, actual_draft)
        rows.append({'name': name, 'status': 'PASS', 'core_issues': sorted(actual_core),
                     'draft_issues': sorted(actual_draft)})

    graph = corridor()
    check('fresh-state-and-exact-forwarded-owner', graph)
    assert loads(dumps(graph)) == graph
    rows.append({'name': 'existing-wire-roundtrip', 'status': 'PASS'})
    drive = next(op for op in graph.operations if op.id == DRIVE)
    stale_uses = tuple(replace(u, value=ValueID('main.before.world'))
                       if u.id == UseID('step.world') else u for u in drive.uses)
    check('old-gate-state-is-already-rejected-by-core',
          change_op(graph, DRIVE, uses=stale_uses), ('stale_state',),
          ('state-not-gate-normal-poststate',))
    produced_owner = _invoke_graph()
    fresh_gate = next(op for op in produced_owner.operations if op.id == GATE)
    check('invented-owner-result-needs-new-adapter-rule', change_op(graph, GATE,
          uses=fresh_gate.uses, completions=fresh_gate.completions,
          terminator=fresh_gate.terminator), (), ('owner-not-exact-forwarded-input',))
    region = graph.regions[0]
    extra = Operation(OperationID('interposed'), 'interposed opaque operation',
                      (Behavior.OPAQUE,), effects_complete=False)
    inserted = replace(graph, operations=(*graph.operations, extra), regions=(replace(region,
        blocks=tuple(replace(b, operations=(extra.id, *b.operations))
                     if b.operations == (DRIVE,) else b for b in region.blocks)),))
    check('even-an-unmodeled-interposition-needs-corridor-rejection', inserted, (),
          ('not-immediate-single-operation-corridor',))
    canonical_gate = next(op for op in graph.operations if op.id == GATE)
    assert canonical_gate.invoke_arguments[0] != next(e for e in canonical_gate.terminator.successors
        if e.kind is ExitKind.NORMAL).arguments[0]
    original = {u.id: u for u in canonical_gate.uses}
    forwarded = next(e for e in canonical_gate.terminator.successors if e.kind is ExitKind.NORMAL).arguments[0]
    assert original[canonical_gate.invoke_arguments[0]].value == original[forwarded].value
    rows.append({'name': 'one-reference-two-distinct-canonical-use-sites', 'status': 'PASS'})
    report = {'schema': 'scar.driver-corridor-design-witness', 'schema_version': 1,
              'status': 'PASS', 'scope': __doc__, 'cases': rows,
              'body_drive_implemented': False, 'runtime_gate_verified': False}
    destination = Path(__file__).with_suffix('.json')
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
