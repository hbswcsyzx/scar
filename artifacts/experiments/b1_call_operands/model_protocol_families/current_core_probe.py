"""Inspect existing declared IR; execute no Python resumable workload or tests."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys

from scar.ir.program.queries import ProgramIndex
from scar.ir.program.resumption import ResumableKind
from scar.ir.program.validation import validate
from tests.fixtures.program_driver_graphs import driver_program
from tests.fixtures.program_resumption_graphs import resumption_program

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def main():
    out = HERE / 'current_core_probe.json'
    if out.exists():
        raise RuntimeError('Fresh observation required; existing evidence is immutable')
    before, sources = runpy.run_path(str(ROOT / 'scripts/run_gate.py'))['fingerprint']()
    cases = []
    for target, async_request in (('start', False), ('value', False),
                                  ('packet', False), ('value', True)):
        graph = driver_program(target=target, async_request=async_request)
        issues = validate(graph)
        index = ProgramIndex(graph)
        drive = graph.body_drives[0]
        operation = index.operations[drive.operation]
        region = next(row for row in graph.regions if row.id == graph.root)
        blocks = {block.id: block for block in region.blocks}
        rows = []
        for edge, source in zip(operation.terminator.successors,
                                index.drive_outcomes(drive.operation)):
            terminal = index.operations[blocks[edge.block].operations[-1]]
            rows.append({'original_body_source': str(source.operation),
                         'body_outcome': source.kind.value,
                         'driver_terminal': terminal.terminator.kind.value,
                         'driver_terminal_operation': str(terminal.id),
                         'producer_ports_retained': len(source.values)})
        cases.append({'target': target, 'receiver_kind': graph.driver_interfaces[0].receiver_kind.value,
                      'body_family': graph.resumable_bodies[0].kind.value,
                      'structural_issues': [issue.code for issue in issues],
                      'original_outcome_routes': rows,
                      'python_family_adapter_validated': False})
        assert not issues
    graph = resumption_program()
    graph = replace(graph, resumable_bodies=(replace(graph.resumable_bodies[0],
                                                    kind=ResumableKind.COROUTINE),))
    wrong_flavor = [issue.code for issue in validate(graph)]
    assert 'resumption_flavor' in wrong_flavor
    after, final = runpy.run_path(str(ROOT / 'scripts/run_gate.py'))['fingerprint']()
    assert before == after and sources == final
    document = {'schema': 'scar.protocol-family-current-core-observation',
        'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'python': sys.version, 'source_sha256': before, 'source_files': len(sources),
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'cases': cases, 'existing_wrong_flavor_guard': wrong_flavor,
        'scope': 'Five declared-IR observations; no pytest, compiler, Python resumable execution, GPU or LeWM run.',
        'interpretation': 'The old D1 contract checks generic structure. These examples do not claim native Python adapter equivalence; their acceptance is not an existing-contract defect.',
        'source_unchanged': True, 'family_protocol_complete': False,
        'source_runtime_verified': False, 'transformation_authorized': False}
    out.write_text(json.dumps(document, indent=2) + '\n')
    print(json.dumps({'declared_ir_observations': len(cases) + 1,
                      'source_unchanged': True, 'report': str(out)}))


if __name__ == '__main__':
    main()
