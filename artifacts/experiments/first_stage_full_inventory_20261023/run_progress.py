"""Run the public inventory command with observation-only construction progress."""
from functools import wraps
import json
from pathlib import Path
import time

from scar.analysis import program_lowering, program_inventory, call_demand
from scar import cli

HERE = Path(__file__).resolve().parent
started = time.perf_counter()
log = (HERE / 'progress.jsonl').open('x', buffering=1)


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
original_seal = program_lowering.PreparedSource.seal_for_lowering
@wraps(original_seal)
def seal(self):
    write('seal', 'BEGIN', path=str(self.path))
    result = original_seal(self)
    write('seal', 'END', path=str(self.path))
    return result

program_lowering.PreparedSource.seal_for_lowering = seal
original_lower = program_lowering._SealedLoweringSession.lower
@wraps(original_lower)
def lower(self, entry, **kwargs):
    source = kwargs.get('source')
    fields = {'path': source.path if source is not None else None, 'entry': entry}
    write('body', 'BEGIN', **fields)
    result = original_lower(self, entry, **kwargs)
    write('body', 'END', **fields, recovered=result.graph is not None,
          operations=result.operations_emitted,
          gaps=[item.detail for item in result.metadata.gaps])
    return result

program_lowering._SealedLoweringSession.lower = lower
try:
    raise SystemExit(cli.main())
finally:
    log.close()
