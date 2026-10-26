"""Normal main-tree readers for saved SP8 and prior function SP5; no lowering."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ISO = ROOT.parent / 'source-call-model'
charged = 0


def read(path, *, sha=None, decoded_sha=None):
    global charged
    path = Path(path)
    with path.open('rb') as stream:
        data = stream.read(32_000_000-charged+1)
    charged += len(data)
    if charged > 32_000_000 or sha and hashlib.sha256(data).hexdigest() != sha:
        raise ValueError('stored receipt/input budget mismatch')
    if path.suffix == '.gz':
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            data = stream.read(32_000_000-charged+1)
        charged += len(data)
    if charged > 32_000_000 or decoded_sha and hashlib.sha256(data).hexdigest() != decoded_sha:
        raise ValueError('decoded receipt/input budget mismatch')
    return data


def document(path, **checks):
    return json.loads(read(path, **checks))


def main():
    start = time.monotonic()
    application = document(HERE / 'APPLICATION.json')
    for row in application['files']:
        read(ROOT / row['path'], sha=row['after_sha256'])
    from scar.analysis.code_witness import CodeWitnessStore
    from scar.analysis.program_composition import CompositionIndex
    from scar.analysis.program_lowering import SourceProgram
    from scar.analysis.source_language import SourceCodeEvidence
    from scar.ir.program.call_edges import CapturedCode
    from scar.ir.record_codec import decode
    from scar.ir.semantics_v2 import SourceSnapshot
    gate = ISO / 'artifacts/experiments/module_try_propagation_g1_20261026/postflight01'
    selection = document(gate / 'selection.json')
    original = document(gate / 'attempt01/worker-result.json')
    receipt = original['sourceprogram']
    doc = document(receipt['uri'], sha=receipt['stored_sha256'], decoded_sha=receipt['decoded_sha256'])
    composition = CompositionIndex(selection['composition'], max_input_bytes=4_000_000,
                                   max_record_bytes=4_000_000, cached_files=1)
    evidence_store = CodeWitnessStore(selection['witness_archive'], create=False, compile_missing=False)
    code = decode(CapturedCode, doc['module']['declaration']['witness']['captured'])
    evidence = SourceCodeEvidence(evidence_store, composition, code)
    source = read(selection['archived_source']).decode('utf8')
    logical_path = selection['expected_unit']['snapshot']['path']
    module = SourceProgram.read_structure(doc, max_operations=4000,
        source_texts={logical_path: source}, module_code_evidence=evidence)
    if module.to_dict() != doc or module.summary() != original['current_graph_summary']:
        raise ValueError('ordinary main SP8 reader changed original model')
    prior = document(ROOT / 'artifacts/experiments/source_entry_catalog_gate_20261025/result/worker/attempt-00001/result.json')
    ref = prior['program']
    old_doc = document(ref['uri'], sha=ref['physical_sha256'], decoded_sha=ref['decoded_sha256'])
    snapshot = decode(SourceSnapshot, prior['entry_reference']['snapshot'])
    old_store = CodeWitnessStore(Path(prior['code_witness']['witness']['store']['path']).parent,
                                create=False, compile_missing=False)
    function = SourceProgram.read_structure(old_doc, max_operations=4000,
        source_texts={snapshot.path: old_store.text(snapshot)})
    if function.to_dict() != old_doc or function.module is not None:
        raise ValueError('shared dispatcher change affected prior SP5 function reader')
    if evidence_store.counts['compile_attempts'] or old_store.counts['compile_attempts']:
        raise ValueError('read-only consumer compiled executable code')
    report = dict(schema='scar.module-try-c-main-readback/1', status='PASSED_WITH_OPEN',
        ordinary_original_sp8_readback=True, prior_function_sp5_readback=True,
        module_summary=module.summary(), code_witness_activity=evidence_store.counts,
        direct_input_bytes=charged, cumulative_all_API_IO='OPEN',
        new_lowerings=0, new_capture=False, target_execution=False,
        actual_namespace_state_ready_bound=False, whole_model='OPEN', wall_seconds=time.monotonic()-start)
    with (HERE / 'RESULT.json').open('x') as stream:
        json.dump(report, stream, sort_keys=True, indent=2)
        stream.write('\n')
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
