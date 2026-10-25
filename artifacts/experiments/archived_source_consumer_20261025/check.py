"""Consume one existing CP2 with all live workload source reads forbidden."""
import builtins
from hashlib import sha256
import inspect
import io
import json
from pathlib import Path
import time
from unittest.mock import patch

from scar.analysis.code_witness import CodeWitnessStore
from scar.analysis.inventory_partitions import InventoryPartitions
from scar.analysis.program_composition import compose_source_publication
from scar.ir.record_codec import decode
from scar.ir.semantics_v2 import SourceSnapshot

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
GATE = ROOT / 'artifacts/experiments/source_call_kwargs_publication_20261025'


def main():
    started = time.perf_counter()
    config = json.loads((GATE / 'inputs.json').read_bytes())
    plan = json.loads((GATE / 'plan.json').read_bytes())['document']
    change = plan['expectations'][0]
    fi, bi = change['file_index'], change['body_index']
    inventory = InventoryPartitions(GATE / 'result/publication/manifest.json')
    snapshot = decode(SourceSnapshot, inventory.file(fi)['snapshot'])
    store = CodeWitnessStore(config['readonly_code_witnesses'])
    text = store.text(snapshot)
    reads_forbidden = []
    def forbid_live(original):
        def opened(file, *args, **kwargs):
            if isinstance(file, (str, bytes, Path)):
                name = str(Path(file).absolute()) if not isinstance(file, bytes) else file.decode()
                if name == snapshot.path or name.startswith('/home/zyf/AAA/le-wm/'):
                    reads_forbidden.append(name)
                    raise AssertionError('live workload source read: ' + name)
            return original(file, *args, **kwargs)
        return opened
    with patch('builtins.open', forbid_live(builtins.open)), patch('io.open', forbid_live(io.open)):
        body = inventory.typed_body(fi, bi, source_texts={snapshot.path: text})
    assert body.public_language_structure_validated and body.public_graph_validated
    assert len(body.body.graph.operations) == config['programs'][0]['operations']
    assert not reads_forbidden
    assert inspect.signature(compose_source_publication).parameters['source_texts'].default is None
    sources = []
    for relative in ('scar/analysis/program_composition.py', 'scar/analysis/source_body_access.py',
                     'scar/analysis/inventory_partitions.py', 'scar/analysis/source_program_publication.py'):
        raw = (ROOT / relative).read_bytes()
        sources.append({'path': str(ROOT / relative), 'bytes': len(raw), 'sha256': sha256(raw).hexdigest()})
    result = {'status': 'ARCHIVED_CP2_STRUCTURE_PASS', 'file_index': fi, 'body_index': bi,
        'operations': len(body.body.graph.operations), 'source_fingerprint': snapshot.fingerprint,
        'live_workload_source_reads': len(reads_forbidden), 'code_witness_compile_attempts': store.counts['compile_attempts'],
        'composer_forwarding_implemented': True, 'composer_reexecuted': False,
        'sba_forwarding_implemented': True, 'sba_runtime_reexecuted': False,
        'runtime_identity_or_effects_established': False, 'whole_first_stage_complete': False,
        'sources': sources, 'elapsed_s': time.perf_counter() - started}
    with (HERE / 'receipt.json').open('x') as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write('\n')
    print(json.dumps({key: result[key] for key in ('status', 'operations', 'live_workload_source_reads', 'elapsed_s')}))


if __name__ == '__main__':
    main()
