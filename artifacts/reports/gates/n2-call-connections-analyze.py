"""Generic API equivalent of inventory verification, call linking and replay."""
import argparse
import gzip
import hashlib
import json
import resource
import subprocess
import time
from pathlib import Path

from scar.analysis.call_edges import CallEdgeReport, link_calls
from scar.analysis.program_inventory import ProgramInventory
from scar.cli import _call_json, _compressed_document
from scar.ir.program.call_edges import CallEdgeBudget

parser = argparse.ArgumentParser()
parser.add_argument('--trace', required=True)
parser.add_argument('--project-root', required=True)
parser.add_argument('--inventory', required=True)
parser.add_argument('--out', required=True)
args = parser.parse_args()
out = Path(args.out)
out.mkdir(parents=True, exist_ok=False)
budget = CallEdgeBudget(max_raw_bytes=256_000_000, max_events=250_000,
                       max_references=2_000_000)
measurements = {'instrumented_analysis': True, 'target_executed_by_analysis': False,
                'transformation_authorized': False, 'phases': {},
                'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                'arguments': vars(args), 'reference_budget_reason':
                'raw capture contains 1,386,048 reference observations, exceeding default 1,000,000'}

def save():
    measurements['peak_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    (out / 'measurements.json').write_text(json.dumps(measurements, indent=2) + '\n')

phase = 'inventory_verification'
started = time.perf_counter()
try:
    inventory = ProgramInventory.from_dict(_call_json(args.inventory), max_files=256)
    measurements['phases'][phase] = time.perf_counter() - started
    save()
    phase = 'call_linking'
    started = time.perf_counter()
    report = link_calls(args.trace, args.project_root, inventory=inventory, budget=budget)
    measurements['phases'][phase] = time.perf_counter() - started
    measurements['summary'] = report.summary()
    save()
    phase = 'serialization'
    started = time.perf_counter()
    analysis = report.to_dict()
    payload = {'schema': 'scar.call-links-envelope', 'schema_version': 1,
               'inventory': {'path': str(Path(args.inventory).resolve()),
                             'sha256': hashlib.sha256(Path(args.inventory).read_bytes()).hexdigest()},
               'analysis': analysis}
    _compressed_document(out / 'links.json.gz', payload)
    measurements['phases'][phase] = time.perf_counter() - started
    save()
    phase = 'call_replay'
    started = time.perf_counter()
    rebuilt = CallEdgeReport.from_dict(analysis, inventory=inventory, verification_budget=budget)
    assert rebuilt.summary() == report.summary()
    measurements['phases'][phase] = time.perf_counter() - started
    measurements['status'] = 'REPLAYED'
    save()
except Exception as error:
    measurements.update(status='FAILED', failed_phase=phase, error=type(error).__name__ + ': ' + str(error))
    save()
    raise
print(json.dumps(measurements))
