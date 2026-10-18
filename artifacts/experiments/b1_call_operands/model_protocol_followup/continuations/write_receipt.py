"""Render existing focused evidence and the unchanged sixteen-group ledger."""
from pathlib import Path
import hashlib
import json

root = Path.cwd()
here = root / 'artifacts/experiments/b1_call_operands/model_protocol_followup/continuations'
owned = ('scar/ir/program/protocols.py', 'scar/ir/program/protocol_rules.py',
         'scar/ir/program/protocol_continuations.py',
         'tests/fixtures/program_method_lookup_graphs.py',
         'tests/unit/test_program_method_lookup_connections.py')
hashes = {path: hashlib.sha256((root/path).read_bytes()).hexdigest() for path in owned}
hashes['docs/M1_PROTOCOL_FOLLOWUP_PLAN.md'] = hashlib.sha256((root/'docs/M1_PROTOCOL_FOLLOWUP_PLAN.md').read_bytes()).hexdigest()
prior = root/'artifacts/experiments/b1_call_operands/model_remaining_protocols/continuations/P4-2-coverage.json'
ledger = json.loads(prior.read_text())
ledger['stage'] = 'P4 followup: bounded expanded method lookup implementation, not full P4'
ledger['status'] = 'OPEN'
ledger['prior_ledger_sha256'] = hashlib.sha256(prior.read_bytes()).hexdigest()
ledger['sources'] = hashes
ledger['owned_focused'] = {'directory': str((here/'attempt002').relative_to(root)),
    'new_tests':25,'unchanged_continuation_tests':52,'passed':77,'failed':0,'seconds_pytest':3.12,
    'exit':0,'source_fingerprint':'d5d86be065efab759377e14834fbb7713375bdbab0f8b9868d90691558c1d242',
    'source_unchanged':True}
deltas = {
 'F20':'Four new lookup rules distinguish GetIterator from independent method lookup. Initial NEXT compares its marker with lookup iterator input, never the bound method. A real loop re-evaluation rejects an old carried bound method. The native lookup/iterator interpretation and full initial-failure family remain unproved.',
 'F21':'Real NEXT/SEND method lookup N/R and its own NORMAL bound-method-to-call receiver are checked. Wrong root, wrong method kind, other same-kind lookup, and crossed two-branch lookup/raw tuples reject. Missing-method category/fallback remains OPEN.',
 'F22':'THROW lookup is distinct from its bound call. Original 1-3 raw ordinals remain actual call operands; lookup has no raw argument or trigger. Complete missing-throw fallback still lacks a closed independent current-original-packet relationship and remains OPEN.',
 'F23':'CLOSE lookup N/R feeds the original injected-packet close call route, retaining existing close NORMAL/RAISE behavior. Lookup RAISE is not automatically AttributeError; exact own packet consumer plus category gap remain. Complete raw/GE and missing-close fallback stays OPEN.',
}
for row in ledger['groups']:
    row['status'] = 'OPEN'
    row['followup_delta'] = deltas.get(row['group'], 'No new whole-group acceptance in this bounded lookup followup. Original required work remains in the prior ledger.')
ledger['attempts'] = [{ 'path':str((here/name).relative_to(root)),
    **json.loads((here/name/'result.json').read_text())}
    for name in ('attempt001','prior-case-red001','prior-case-red002','attempt002')]
(here/'coverage.json').write_text(json.dumps(ledger,indent=2)+'\n')
(here/'source.final.json').write_text(json.dumps(hashes,indent=2)+'\n')
