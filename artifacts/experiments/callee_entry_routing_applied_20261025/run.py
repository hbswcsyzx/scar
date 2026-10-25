"""Read-only main-tree compatibility; not a replacement for live routing proof."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ISO = ROOT.parent / 'frame-entry-routing'
charged = 0


def read(path, *, sha=None, decoded_sha=None):
    global charged
    path = Path(path)
    with path.open('rb') as stream:
        data = stream.read(32_000_000 - charged + 1)
    charged += len(data)
    if charged > 32_000_000 or (sha and hashlib.sha256(data).hexdigest() != sha):
        raise ValueError('stored input receipt/budget mismatch')
    if path.suffix == '.gz':
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            data = stream.read(32_000_000 - charged + 1)
        charged += len(data)
    if charged > 32_000_000 or (decoded_sha and hashlib.sha256(data).hexdigest() != decoded_sha):
        raise ValueError('decoded input receipt/budget mismatch')
    return data


def main():
    started = time.monotonic()
    application = json.loads(read(HERE / 'APPLICATION.json'))
    for item in application['files']:
        read(ROOT / item['path'], sha=item['after_sha256'])
    from scar.analysis import source_invocations, source_entry_routing, source_entry_routing_validation
    from scar.analysis.code_witness import CodeWitnessStore
    from scar.analysis.program_lowering import SourceProgram
    from scar.ir.program.call_edges import ReferenceOccurrence, ReferenceRole
    from scar.ir.record_codec import decode, encode
    from scar.ir.semantics_v2 import SourceSnapshot
    prior = ROOT / 'artifacts/experiments/source_entry_catalog_gate_20261025/result/worker/attempt-00001/result.json'
    original = json.loads(read(prior))
    receipt = original['program']
    doc = json.loads(read(receipt['uri'], sha=receipt['physical_sha256'], decoded_sha=receipt['decoded_sha256']))
    snapshot = decode(SourceSnapshot, original['entry_reference']['snapshot'])
    evidence_store = CodeWitnessStore(Path(original['code_witness']['witness']['store']['path']).parent,
                                     create=False, compile_missing=False)
    source = evidence_store.text(snapshot)
    program = SourceProgram.read_structure(doc, max_operations=4000, source_texts={snapshot.path: source})
    if program.to_dict() != doc or program.interface is None:
        raise ValueError('ordinary original SP5 body/ports changed')
    gate = ISO / 'artifacts/experiments/callee_entry_routing_20261025/attempt01'
    result = json.loads(read(gate / 'result.json'))
    projection = result['report']['entry_parameter_projection']
    raw = read(gate / 'products/bindings/entry-parameters.jsonl.gz', decoded_sha=projection['raw_sha256'])
    if len(raw) != projection['raw_bytes']:
        raise ValueError('projection decoded size mismatch')
    rows = [json.loads(line) for line in raw.splitlines()]
    ports = {p.slot: p.value for p in program.interface.parameters}
    total = qualified = frontiers = 0
    for row in rows:
        for parameter in row['parameters']:
            occurrence = decode(ReferenceOccurrence, parameter['occurrence'])
            if encode(occurrence) != parameter['occurrence'] or occurrence.role is not ReferenceRole.PARAMETER:
                raise ValueError('typed parameter occurrence changed')
            total += 1
            if row['status'] == 'QUALIFIED_CALLEE_ENTRY_SNAPSHOT':
                from scar.ir.v2.ids import ValueSlotID
                slot = decode(ValueSlotID, parameter['formal_slot'])
                if slot not in ports or occurrence.core_value != ports[slot]:
                    raise ValueError('original formal port changed')
                qualified += 1
        if row['status'] == 'FRONTIER':
            frontiers += 1
    if (len(rows), total, qualified, frontiers) != (271, 566, 520, 11):
        raise ValueError('saved real gate denominator changed')
    if evidence_store.counts['compile_attempts']:
        raise ValueError('read-only consumer compiled executable code')
    report = dict(schema='scar.entry-routing-main-compatibility/1', status='PASSED_WITH_OPEN',
        original_sp5_roundtrip=True, typed_parameter_occurrences=total,
        preserved_existing_formal_port_projections=qualified, frontier_invocations=frontiers,
        new_live_qualification=False, caller_actual_expression_route=False,
        default_publication_schema='UNCHANGED_BY_THIS_PATCH', main_core='29', isolated_gate_core='28',
        code_witness_activity=evidence_store.counts, direct_input_bytes=charged,
        new_capture=False, target_execution=False, whole_model='OPEN', wall_seconds=time.monotonic()-started)
    (HERE / 'RESULT.json').write_text(json.dumps(report, sort_keys=True, indent=2)+'\n')
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
