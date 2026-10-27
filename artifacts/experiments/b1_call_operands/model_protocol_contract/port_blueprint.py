"""Exercise proposed ports with existing IR, not a new SCAR validator or trace."""
from dataclasses import fields, is_dataclass, replace
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
import traceback

from scar.ir.execution.codec import dumps as execution_dumps
from scar.ir.execution.coordinates import ExecutionSegment, ResumeIngress
from scar.ir.execution.ids import ExecutionSegmentID
from scar.ir.execution.query import ExecutionIndex
from scar.ir.program.codec import dumps as program_dumps
from scar.ir.program.ids import BlockID, OperationID
from scar.ir.program.queries import InstanceCaptureInput, ProgramIndex
from scar.ir.program.validation import require_valid
from scar.ir.v2.ids import Identifier
from tests.fixtures.execution_call_graphs import _model
from tests.fixtures.program_driver_graphs import driver_program

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def second_driver():
    graph = driver_program(target='value')
    region = next(row for row in graph.regions if row.id == graph.root)
    operation_ids = {identity for block in region.blocks for identity in block.operations}
    operations = [row for row in graph.operations if row.id in operation_ids]
    identities = [graph.root, *(block.id for block in region.blocks), *operation_ids,
        *(row.id for row in graph.values if row.region == graph.root),
        *(use.id for op in operations for use in op.uses),
        *(row.id for row in graph.control_scopes if row.region == graph.root)]
    mapping = {value: type(value)('second.' + value.value) for value in identities}

    def rename(value):
        if isinstance(value, Identifier):
            return mapping.get(value, value)
        if type(value) is tuple:
            return tuple(rename(item) for item in value)
        if is_dataclass(value):
            return replace(value, **{field.name: rename(getattr(value, field.name))
                                     for field in fields(value) if field.init})
        return value

    return rename(graph)


def build():
    first, second = driver_program(), second_driver()
    new_region = next(row for row in second.regions if row.id == second.root)
    new_operation_ids = {identity for block in new_region.blocks for identity in block.operations}
    program = replace(first,
        regions=(*first.regions, replace(new_region, parent=first.root)),
        operations=(*first.operations, *(op for op in second.operations if op.id in new_operation_ids)),
        values=(*first.values, *(value for value in second.values if value.region == second.root)),
        control_scopes=(*first.control_scopes, *(row for row in second.control_scopes if row.region == second.root)),
        driver_interfaces=(*first.driver_interfaces, *second.driver_interfaces),
        final_body_gates=(*first.final_body_gates, *second.final_body_gates),
        body_drives=(*first.body_drives, *second.body_drives))
    require_valid(program)
    body = program.resumable_bodies[0].region
    model, scopes, source = _model(program, (
        (first.root, ((BlockID('driver.entry'), 0), (BlockID('driver.ingress'), 0),
                      (BlockID('driver.outcome'), None)), 'drive.start'),
        (second.root, ((BlockID('second.driver.entry'), 0), (BlockID('second.driver.ingress'), 0),
                       (BlockID('second.driver.outcome'), None)), 'drive.resume'),
        (body, ((BlockID('resume.entry'), 0), (BlockID('resume.value'), None)), 'body'),
    ))
    body_activation, body_visits, body_operations = scopes[2]
    suspension = body_operations[OperationID('resume.suspend')]
    initial = next(row for row in model.segments if row.activation == body_activation)
    resumed = ExecutionSegment(ExecutionSegmentID('body.resumed'), body_activation,
                              initial.host_thread, ResumeIngress(suspension, 0, initial.ingress.source))
    model = replace(model, segments=(*model.segments, resumed),
        visits=tuple(replace(row, segment=resumed.id) if row.id == body_visits[1] else row
                     for row in model.visits))
    index = ExecutionIndex(model, program)
    ctx, static = index._ctx, ProgramIndex(program)
    blueprint = []
    for number, drive in enumerate(program.body_drives):
        caller = scopes[number][2][drive.operation]
        transfer = ctx.outgoing[caller]
        selected = static.operations[drive.operation].terminator.successors[transfer.successor_index]
        outcome = body_operations[selected.source]
        entry = body_visits[number]
        inputs = []
        for binding in static.drive_input_bindings(drive.operation):
            formal = ctx.results[entry, binding.formal]
            if type(binding.source) is InstanceCaptureInput:
                inputs.append({'formal': str(formal.id), 'kind': 'INSTANCE_CAPTURE_UNRESOLVED',
                               'instance_use': str(binding.source.instance.use.id)})
                continue
            site = binding.source
            occurrence = (body_operations[site.operation] if site.operation in body_operations
                          else scopes[number][2][site.operation])
            use = ctx.uses[occurrence, site.use.id]
            inputs.append({'formal': str(formal.id), 'kind': 'ORIGINAL_USE',
                           'source_operation': str(occurrence), 'source_use': str(use.use),
                           'source_value': str(use.value)})
        outputs = []
        for binding in static.drive_bindings(drive.operation, selected.source):
            actual = ctx.uses[outcome, binding.actual.use.id]
            formal = ctx.results[transfer.target, binding.formal]
            outputs.append({'source_operation': str(outcome), 'source_use': str(actual.use),
                'source_value': str(actual.value), 'driver_formal': str(formal.id)})
        blueprint.append({'drive': str(caller), 'activation': str(body_activation),
            'entry': str(entry), 'derived_segment': str(ctx.visits[entry].segment),
            'outcome': str(outcome), 'original_static_source': str(selected.source),
            'inputs': inputs, 'outputs': outputs,
            'instance_identity_verified': False, 'source_runtime_verified': False})
    assert len(blueprint) == 2 and blueprint[0]['activation'] == blueprint[1]['activation']
    assert blueprint[0]['entry'] != blueprint[1]['entry']
    assert blueprint[0]['derived_segment'] != blueprint[1]['derived_segment']
    assert len(blueprint[0]['inputs']) > 0 and len(blueprint[1]['inputs']) > 0
    assert all(row['outputs'] for row in blueprint)
    return program, model, blueprint, index.report


def main():
    number = 1
    while (HERE / f'port-blueprint-attempt{number:03}.json').exists():
        number += 1
    path = HERE / f'port-blueprint-attempt{number:03}.json'
    before, sources = runpy.run_path(str(ROOT / 'scripts/run_gate.py'))['fingerprint']()
    report = {'schema': 'scar.protocol-port-design-blueprint',
        'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'python': sys.version, 'source_sha256': before, 'source_files': len(sources),
        'scope': 'Existing hand-authored IR and proposed FK rows; not an implementation of O records, runtime capture, or protocol proof.',
        'new_product_capability': False, 'new_pytest_run': False,
        'source_runtime_verified': False, 'transformation_authorized': False}
    try:
        program, model, rows, validation = build()
        report.update(status='DESIGN_PORTS_CONNECTED', rows=rows,
            existing_execution_issues=[row.code for row in validation.issues],
            existing_execution_gaps=[row.code for row in validation.gaps])
        (HERE / f'port-blueprint-attempt{number:03}.program.json').write_text(program_dumps(program))
        (HERE / f'port-blueprint-attempt{number:03}.execution.json').write_text(execution_dumps(model))
    except Exception:
        report.update(status='DESIGN_PROBE_FAILED', traceback=traceback.format_exc())
    after, final = runpy.run_path(str(ROOT / 'scripts/run_gate.py'))['fingerprint']()
    report['source_unchanged'] = before == after and sources == final
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('status', 'source_unchanged', 'source_files')}))
    if report['status'] != 'DESIGN_PORTS_CONNECTED':
        print(report['traceback'])
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
