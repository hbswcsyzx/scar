"""Design probe for resumption cuts on existing valid canonical CFG fixtures.

No Suspend record exists in the product yet. Extra roots below are hypothetical
resume landings, not runtime observations or a newly accepted program schema.
The probe isolates why ordinary dominance cannot validate saved-frame coverage.
"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from scar.ir.program.ids import BlockID, UseID, ValueID
from scar.ir.program.model import BlockArgument, LiteralOrigin, OperationResult, Use
from scar.ir.program.validation import validate
from tests.fixtures.program_graphs import loop_state_program


def thread_limit(*, through_body):
    graph = loop_state_program()
    template = next(v for v in graph.values if v.id == ValueID('limit'))
    extra = [replace(template, id=ValueID('saved.header.limit'),
                     origin=BlockArgument(BlockID('header'), 1))]
    if through_body:
        extra.append(replace(template, id=ValueID('saved.body.limit'),
                             origin=BlockArgument(BlockID('body'), 1)))
    operations = []
    for op in graph.operations:
        name = op.id.value
        if name in ('enter', 'backedge'):
            source = ('limit' if name == 'enter' else
                      'saved.body.limit' if through_body else 'saved.header.limit')
            owned = Use(UseID(name + '.saved-limit'), ValueID(source))
            edge = op.terminator.successors[0]
            op = replace(op, uses=(*op.uses, owned), terminator=replace(
                op.terminator, successors=(replace(edge, arguments=(*edge.arguments, owned.id)),)))
        elif name == 'compare':
            op = replace(op, uses=tuple(replace(u, value=ValueID('saved.header.limit'))
                         if u.id == UseID('compare.limit') else u for u in op.uses))
        elif name == 'loop.choose' and through_body:
            owned = Use(UseID('choose.saved-limit'), ValueID('saved.header.limit'))
            body, done = op.terminator.successors
            op = replace(op, uses=(*op.uses, owned), terminator=replace(
                op.terminator, successors=(replace(body, arguments=(*body.arguments, owned.id)), done)))
        operations.append(op)
    region, = graph.regions
    blocks = tuple(replace(b, arguments=(*b.arguments, ValueID('saved.' + b.id.value + '.limit')))
                   if b.id == BlockID('header') or through_body and b.id == BlockID('body')
                   else b for b in region.blocks)
    return replace(graph, regions=(replace(region, blocks=blocks),),
                   operations=tuple(operations), values=(*graph.values, *extra))


def unavailable(graph, extra_roots):
    region, = graph.regions
    blocks = {b.id: b for b in region.blocks}
    operations = {o.id: o for o in graph.operations}
    values = {v.id: v for v in graph.values}
    op_blocks = {oid: b.id for b in region.blocks for oid in b.operations}
    predecessors = {b: set() for b in blocks}
    for block in region.blocks:
        for edge in operations[block.operations[-1]].terminator.successors:
            predecessors[edge.block].add(block.id)
    roots = {region.entry, *(BlockID(b) for b in extra_roots)}
    dom = {b: {b} if b in roots else set(blocks) for b in blocks}
    while True:
        updated = {b: {b} if b in roots else {b} | set.intersection(
            *(dom[p] for p in predecessors[b])) for b in blocks}
        if updated == dom:
            break
        dom = updated
    bad = []
    for op in graph.operations:
        for use in op.uses:
            origin = values[use.value].origin
            if isinstance(origin, LiteralOrigin):
                continue
            source = origin.block if isinstance(origin, BlockArgument) else op_blocks[origin.operation]
            if source not in dom[op_blocks[op.id]]:
                bad.append(str(use.id))
    return sorted(bad)


def main():
    cases = [
        ('ordinary core', loop_state_program(), (), []),
        ('header cut, missing saved limit', loop_state_program(), ('header',), ['program_use:compare.limit']),
        ('limit forwarded into header', thread_limit(through_body=False), ('header',), []),
        ('second cut exposes transitive omission', thread_limit(through_body=False),
         ('header', 'body'), ['program_use:backedge.saved-limit']),
        ('limit forwarded across both cuts', thread_limit(through_body=True), ('header', 'body'), []),
    ]
    rows = []
    for name, graph, roots, expected in cases:
        core_issues = [issue.code for issue in validate(graph)]
        actual = unavailable(graph, roots)
        rows.append({'case': name, 'hypothetical_roots': roots, 'core_issues': core_issues,
                     'unavailable_uses': actual, 'expected': expected,
                     'passed': not core_issues and actual == expected})
    result = {'scope': 'Design-only extra-root availability on existing synchronous core fixtures',
              'not_verified': ['actual Suspend/Resume records', 'fresh shared-state ingress',
                               'context switching', 'C1 composition', 'source/runtime recovery'],
              'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
              'python': sys.version, 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'cases': rows, 'status': 'PASS' if all(row['passed'] for row in rows) else 'FAIL'}
    destination = Path(__file__).with_suffix('.json')
    if destination.exists():
        raise FileExistsError('Preserve prior observations; choose a new probe filename')
    destination.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
