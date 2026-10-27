"""Save exact changed source bytes for each immutable attempt, without tests.

Unchanged files are retained in the resulting Git revision. Historical files
are accepted only if their bytes match that attempt's pre-existing registry.
"""
import hashlib
import json
from pathlib import Path
import subprocess

from scripts.run_gate import fingerprint

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
BASE = '9293836d75e9c1d9a64849749d1b8b92529908b1'
PRODUCT = 'scar/ir/program/protocol_async.py'
TEST = 'tests/unit/test_program_async_scheduler_packets.py'

def sha(data):
    return hashlib.sha256(data).hexdigest()

product, test = (ROOT / PRODUCT).read_text(), (ROOT / TEST).read_text()
old_test = test.split('\n\ndef test_last_raise_candidate_scan_exhaustion_cannot_leave_scheduler_packet_match_true():')[0]
for before, after in (
    ('    BlockArgument, CompletionResult,', '    CompletionResult,'),
    ('from scar.ir.program.protocol_async import _Analysis, async_connections',
     'from scar.ir.program.protocol_async import async_connections'),
    ("    scheduler_formal = values[original['interface'].scheduler_request].origin\n"
     '    assert type(scheduler_formal) is BlockArgument and scheduler_formal.block == driver.entry\n', ''),
    ("        'scheduler_formal': scheduler_formal,\n", ''),
    ("    assert ProgramIndex(_core(graph)).source_binding(details['scheduler_formal'], details['raw'],\n"
     "        budget=QUERY_BUDGET)['match'] is True\n", ''),
    ("source_binding(details['scheduler_formal'], details['raw'],", 
     "source_binding(details['scheduler_source'], details['raw'],"),
):
    assert before in old_test, before
    old_test = old_test.replace(before, after)
first = json.loads((HERE / 'first-scheduler/sources.before.json').read_text())
variants = [old_test.rstrip('\n') + '\n' * count for count in range(1, 5)]
old_test, = (row.encode() for row in variants if sha(row.encode()) == first[TEST])
without_budget = product.replace(
    '        # A successful prefix cannot stand for an unfinished candidate scan.\n'
    '        # The shared accounting also covers the bindings and context join.\n'
    '        if self.ctx.budget.truncated:\n'
    '            match = None\n', '')
assert without_budget != product
prior_product = subprocess.check_output(['git', 'show', BASE + ':' + PRODUCT])
overrides = {'first-scheduler': {PRODUCT: prior_product, TEST: old_test},
             'first-combined': {PRODUCT: without_budget.encode()},
             'corrected-local': {}, 'verified-final': {}}
fingerprint_before, current = fingerprint()
records, pending = {}, []
for attempt, changed in overrides.items():
    before = json.loads((HERE / attempt / 'sources.before.json').read_text())
    after = json.loads((HERE / attempt / 'sources.after.json').read_text())
    assert before == after and set(before) == set(current)
    for name, digest in before.items():
        assert sha(changed[name] if name in changed else (ROOT / name).read_bytes()) == digest, (attempt, name)
    saved = {}
    for name, data in changed.items():
        path = HERE / 'source-snapshots' / attempt / (name.replace('/', '__') + '.txt')
        assert not path.exists(), path
        saved[name] = {'path': str(path.relative_to(ROOT)), 'sha256': sha(data)}
        pending.append((path, data))
    records[attempt] = {'source_count': len(before), 'overrides': saved,
        'unchanged_sources_from_final_revision': len(before) - len(changed)}
target = HERE / 'source-snapshots.json'
assert not target.exists()
for path, data in pending:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
assert fingerprint()[0] == fingerprint_before
target.write_text(json.dumps({'attempts': records, 'tests_started': 0}, indent=2) + '\n')
print(json.dumps({'verified_attempts': len(records), 'historical_files': len(pending),
                  'source_unchanged': True, 'tests_started': 0}))
