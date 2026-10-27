"""Read the one actual retained graph through main's unchanged public reader."""
from hashlib import sha256
import ast
import gzip
import inspect
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OTHER = Path('/home/zyf/AAA/scar-worktrees/source-call-model')
ATTEMPT = OTHER / 'artifacts/experiments/generator_expression_p0_20261025/candidate03/attempt01'


def main():
    started = time.monotonic()
    application = json.loads((HERE / 'APPLICATION.json').read_bytes())
    for row in application['files']:
        raw = (ROOT / row['path']).read_bytes()
        assert sha256(raw).hexdigest() == row['after_sha256']
        ast.parse(raw, filename=row['path'])
    worklist = ROOT / 'scar/analysis/source_frontend_worklist.py'
    assert sha256(worklist.read_bytes()).hexdigest() == application['main_worklist_sha256']
    from scar.analysis.source_language import SourceLanguageOptions
    from scar.analysis.source_frontend_worklist import plan_source_frontend
    from scar.analysis.program_lowering import SourceProgram
    from scar.ir.program.source_language import SourceLanguageCapability as Capability
    assert Capability.GENEXPR_314_V1 not in SourceLanguageOptions().capabilities
    signature = inspect.signature(plan_source_frontend)
    assert len(signature.parameters['capabilities'].default) == 4
    assert Capability.GENEXPR_314_V1 not in signature.parameters['capabilities'].default
    assert 'eligible_body_keys' in signature.parameters
    prior = json.loads((ATTEMPT / 'body-01-result.json').read_bytes())
    receipt = prior['artifact']
    stored = Path(receipt['path']).read_bytes()
    assert len(stored) == receipt['bytes'] and sha256(stored).hexdigest() == receipt['sha256']
    with gzip.open(receipt['path'], 'rb') as stream:
        raw = stream.read(64_000_001)
    assert len(raw) == receipt['decoded_bytes'] and sha256(raw).hexdigest() == receipt['decoded_sha256']
    document = json.loads(raw)
    freeze = json.loads((ATTEMPT.parent / 'freeze.json').read_bytes())
    sources = [Path(row['path']) for row in freeze['inputs'] if row['path'].endswith('.source.utf8')]
    assert len(sources) == 1
    source = sources[0].read_bytes()
    snapshot = document['metadata']['source']
    assert 'sha256:' + sha256(source).hexdigest() == snapshot['fingerprint']
    loaded = SourceProgram.read_structure(document, max_operations=4000,
        source_texts={snapshot['path']: source.decode('utf-8')})
    assert loaded.to_dict() == document
    assert len(loaded.graph.resumable_creates) == 1
    assert len(loaded.graph.resumable_bodies) == 1
    assert len(loaded.graph.body_drives) == 2
    assert len(loaded.graph.regions) == 5
    assert 'torch' not in sys.modules
    result = {'status': 'MAIN_PUBLIC_STRUCTURE_READBACK_VERIFIED_WITH_OPEN',
        'graph_bytes': receipt['decoded_bytes'], 'graph_sha256': receipt['sha256'],
        'all_five_regions_and_original_records_retained': True,
        'default_capabilities_unchanged': True, 'main_eligible_body_keys_preserved': True,
        'target_runs': 0, 'body_lowerings': 0, 'CodeWitness_loads': 0,
        'source_semantics_runtime_effects_ready': 'OPEN', 'published_or_runtime_integrated': False,
        'whole_model': 'OPEN', 'elapsed_seconds': time.monotonic() - started}
    with (HERE / 'MAIN_READBACK.json').open('x') as output:
        json.dump(result, output, indent=2, sort_keys=True)
        output.write('\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
