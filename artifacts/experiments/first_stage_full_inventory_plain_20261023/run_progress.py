"""Public inventory with progress and durable records of returned body graphs."""
from functools import wraps
import gzip
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis import program_lowering, program_inventory, call_demand
from scar.ir.program.codec import dumps as dump_graph
from scar.ir.record_codec import encode
from scar import cli

HERE = Path(__file__).resolve().parent
started = time.perf_counter()
log = (HERE / 'progress.jsonl').open('x', buffering=1)
checkpoint_dir = HERE / 'checkpoints'
checkpoint_dir.mkdir(exist_ok=False)
checkpoint_index = (checkpoint_dir / 'index.jsonl').open('x', buffering=1)
sequence = 0


def write(stage, status, **fields):
    log.write(json.dumps({'stage': stage, 'status': status,
                          'elapsed_s': time.perf_counter() - started, **fields}) + '\n')


original_prepare = program_lowering.prepare_source
@wraps(original_prepare)
def prepare(path, **kwargs):
    write('prepare', 'BEGIN', path=str(path))
    result = original_prepare(path, **kwargs)
    write('prepare', 'END', path=str(path))
    return result

program_lowering.prepare_source = program_inventory.prepare_source = call_demand.prepare_source = prepare
original_lower = program_lowering.PreparedSource.lower
@wraps(original_lower)
def lower(self, entry, **kwargs):
    global sequence
    sequence += 1
    serial = sequence
    source = kwargs.get('source')
    fields = {'path': str(self.path), 'entry': entry, 'sequence': serial}
    write('body', 'BEGIN', **fields)
    result = original_lower(self, entry, **kwargs)
    # These are original adapter returns, not a successful whole-inventory
    # receipt. Preserve failed-body metadata too; never fabricate its graph.
    document = {'schema': 'scar.body-construction-checkpoint', 'schema_version': 1,
        'entry': entry, 'source': encode(source) if source else None,
        'profile': encode(kwargs.get('profile')), 'max_operations': kwargs.get('max_operations'),
        'graph': json.loads(dump_graph(result.graph)) if result.graph is not None else None,
        'metadata': encode(result.metadata), 'interface': encode(result.interface),
        'frame': encode(result.frame), 'structured': encode(result.structured),
        'operations_emitted': result.operations_emitted, 'whole_program_established': False}
    name = f'{serial:05d}.json.gz'
    payload = (json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    temporary = checkpoint_dir / ('.' + name + '.tmp')
    with temporary.open('xb') as output:
        with gzip.GzipFile(filename='', fileobj=output, mode='wb', mtime=0) as zipped:
            zipped.write(payload)
    temporary.replace(checkpoint_dir / name)
    checkpoint_index.write(json.dumps({'file': name, 'raw_sha256': sha256(payload).hexdigest(),
        'raw_bytes': len(payload), 'sequence': serial, 'path': str(self.path), 'entry': entry,
        'recovered': result.graph is not None}) + '\n')
    write('body', 'END', **fields, recovered=result.graph is not None,
          operations=result.operations_emitted, checkpoint=name,
          last_gap=result.metadata.gaps[-1].detail if result.metadata.gaps else None)
    return result

program_lowering.PreparedSource.lower = lower
try:
    raise SystemExit(cli.main())
finally:
    checkpoint_index.close()
    log.close()
