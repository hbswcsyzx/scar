"""Consume the original passed v6 and v5 artifacts; never lower or run a target."""
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ISO = ROOT.parent / 'source-call-model'
GATE = ISO / 'artifacts/experiments/module_mapping_entry_g1_20261025/candidate04'
charged = 0


def read(path, *, sha=None, decoded_sha=None):
    global charged
    path = Path(path)
    remaining = 32_000_000 - charged
    with path.open('rb') as stream:
        data = stream.read(remaining + 1)
    charged += len(data)
    if charged > 32_000_000 or (sha and hashlib.sha256(data).hexdigest() != sha):
        raise ValueError('direct input limit or exact stored receipt mismatch')
    if path.suffix == '.gz':
        import io
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            decoded = stream.read(32_000_000 - charged + 1)
        charged += len(decoded)
    else:
        decoded = data
        charged += len(decoded)
    if charged > 32_000_000 or (decoded_sha and hashlib.sha256(decoded).hexdigest() != decoded_sha):
        raise ValueError('direct decoded input limit or exact decoded receipt mismatch')
    return decoded


def document(path, **kwargs):
    return json.loads(read(path, **kwargs))


def main():
    started = time.monotonic()
    application = document(HERE / 'APPLICATION.json')
    for row in application['files']:
        if hashlib.sha256(read(ROOT / row['path'])).hexdigest() != row['after_sha256']:
            raise ValueError('applied production source changed')
    selection = document(GATE / 'selection.json')
    original = document(GATE / 'attempt01/worker-result.json')
    artifact = original['sourceprogram']
    doc = document(artifact['uri'], sha=artifact['stored_sha256'], decoded_sha=artifact['decoded_sha256'])
    text = read(selection['archived_source']).decode('utf8')
    from scar.analysis.code_witness import CodeWitnessStore
    from scar.analysis.program_composition import CompositionIndex
    from scar.analysis.program_lowering import SourceProgram, lower_source
    from scar.analysis.source_frontend_worklist import module_entry_catalog
    from scar.analysis.source_language import SourceCodeEvidence
    from scar.ir.program.call_edges import CodeCapture, CodeSourceLink, CallLinkStatus
    from scar.ir.record_codec import decode, encode
    composition = CompositionIndex(selection['composition'], max_input_bytes=4_000_000,
                                   max_record_bytes=4_000_000, cached_files=1)
    catalog = module_entry_catalog(composition, max_files=1)
    if len(catalog) != 1 or encode(catalog[0].unit) != selection['expected_unit']:
        raise ValueError('main catalog changed the original qualified module unit')
    unit = catalog[0].unit
    model = composition.inventory_component('call_sources')['model']
    captures = {decode(CodeCapture, row).code.key: decode(CodeCapture, row).code for row in model['codes']}
    store = CodeWitnessStore(selection['witness_archive'], create=False, compile_missing=False)
    evidence = []
    for row in model['code_links']:
        link = decode(CodeSourceLink, row)
        if link.status is CallLinkStatus.VERIFIED and link.snapshot == unit.snapshot:
            proof = SourceCodeEvidence(store, composition, captures[link.code])
            if proof.witness['constant_path'] == []:
                evidence.append(proof)
    if len(evidence) != 1:
        raise ValueError('main readonly root witness differs')
    sp7_gate = ISO / 'artifacts/experiments/module_import_prefix_g1_20261025'
    measurement = document(sp7_gate / 'postflight01/ARTIFACT_MEASUREMENT.json')
    # The stream receipt is postflight measurement, never an original writer receipt.
    artifact7 = measurement
    doc7 = document(artifact7['uri'], sha=artifact7['stored_sha256'], decoded_sha=artifact7['decoded_sha256'])
    restored7 = SourceProgram.read_structure(doc7, max_operations=4000,
        source_texts={unit.snapshot.path: text}, module_code_evidence=evidence[0])
    if restored7.to_dict() != doc7 or len(restored7.graph.regions) != 4:
        raise ValueError('main ordinary SP7 reader changed the original graph')
    restored = SourceProgram.read_structure(doc, max_operations=4000,
        source_texts={unit.snapshot.path: text}, module_code_evidence=evidence[0])
    if restored.to_dict() != doc or restored.summary() != original['summary']:
        raise ValueError('main ordinary module reader changed original model')
    prior = ROOT / 'artifacts/experiments/source_entry_catalog_gate_20261025/result/worker/attempt-00001'
    row = document(prior / 'result.json')
    ref = row['program']
    old_doc = document(ref['uri'], sha=ref['physical_sha256'], decoded_sha=ref['decoded_sha256'])
    from scar.ir.semantics_v2 import SourceSnapshot
    snapshot = decode(SourceSnapshot, row['entry_reference']['snapshot'])
    old_store = CodeWitnessStore(Path(row['code_witness']['witness']['store']['path']).parent,
                                create=False, compile_missing=False)
    old_text = old_store.text(snapshot)
    old = SourceProgram.read_structure(old_doc, max_operations=4000,
                                      source_texts={snapshot.path: old_text})
    if old.to_dict() != old_doc or old.module is not None:
        raise ValueError('main v6 support changed original v5 document')
    import inspect
    defaults = inspect.signature(lower_source).parameters
    if defaults['max_operations'].default != 10000:
        raise ValueError('historical operation default changed')
    counts = store.counts
    if counts['compile_attempts'] or old_store.counts['compile_attempts']:
        raise ValueError('readonly application acquired executable code')
    result = {'schema': 'scar.module-import-prefix-main-readback/1', 'status': 'PASSED_WITH_OPEN',
        'module_summary': restored7.summary(), 'ordinary_v7_readback': True, 'ordinary_v6_readback': True,
        'original_v5_readback': True, 'original_module_catalog': True,
        'code_witness_activity': counts, 'v5_source_archive_activity': old_store.counts,
        'direct_stored_plus_decoded_bytes': charged, 'cumulative_all_API_IO': 'OPEN',
        'new_lowerings': 0, 'target_run': False, 'Torch_imported': 'torch' in sys.modules,
        'publication': 'NOT_RUN', 'runtime_binding': 'NOT_RUN', 'whole_model': 'OPEN',
        'wall_seconds': time.monotonic() - started}
    output = json.dumps(result, sort_keys=True, indent=2) + '\n'
    if len(output.encode()) > 1_000_000:
        raise ValueError('application output limit')
    with (HERE / 'RESULT.json').open('x') as stream:
        stream.write(output)
    print(output)


if __name__ == '__main__':
    main()
