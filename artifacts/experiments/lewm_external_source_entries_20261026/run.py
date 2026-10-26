"""Ordinary archived external-entry worker; Root runs once after metadata review."""
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import resource
import signal
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
START = time.monotonic()

def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()

def need(value, detail):
    if not value:
        raise ValueError(detail)

def receipt(path):
    path = Path(path)
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}

def save(name, value):
    raw = canonical(value) + b'\n'
    need(len(raw) <= 128_000_000, 'gate metadata record exceeds128MB')
    with (HERE / name).open('xb') as stream:
        stream.write(raw)

class Meter:
    def __init__(self, limit=1_000_000_000):
        self.limit = limit
        self.stored = self.decoded = self.pending = 0
        self.exhausted = False
        self.calls = Counter()
    def begin(self, stored, decoded, kind):
        amount = stored + decoded
        if self.stored + self.decoded + self.pending + amount > self.limit:
            self.exhausted = True
            raise ValueError('input stored+decoded budget exhausted before normal read')
        self.pending += amount
        return stored, decoded, kind
    def done(self, token):
        stored, decoded, kind = token
        self.pending -= stored + decoded
        self.stored += stored
        self.decoded += decoded
        self.calls[kind] += 1
    def report(self):
        return {'ceiling_bytes': self.limit, 'stored_read_bytes': self.stored, 'decoded_payload_bytes': self.decoded,
                'stored_plus_decoded_bytes': self.stored + self.decoded,
                'pending_reserved_not_actual': self.pending, 'calls': dict(self.calls),
                'ceiling_refusal_observed': self.exhausted,
                'scope': 'normal attachment manifests/aux/graph; archive manifests/text/marshal; worker SP5 readback',
                'code_payload_accounting': 'marshal/text payload charged again as decoded size, not in-memory CodeType size',
                'excluded': 'source/runner/input/freeze SHA controls and Python runtime imports',
                'partial_read_on_exception': 'OPEN if pending is nonzero'}

def install_meter(meter, *, metadata_only):
    from scar.analysis import source_attachments as sa
    from scar.analysis import source_frontend_worklist as sf
    from scar.analysis.code_witness import CodeWitnessStore
    plain, aux, graph, read, replay = sa._plain, sa.SourceAttachments._aux, sa.load_source_graph_artifact, CodeWitnessStore._read, sf._read_receipt
    def bounded_plain(path, *args):
        n = Path(path).stat().st_size
        token = meter.begin(n, n, 'manifest')
        value = plain(path, *args)
        meter.done(token)
        return value
    def bounded_aux(self, locator, root, family):
        path, artifact = self._artifact_path(locator, root, family)
        if (str(path), artifact['canonical_sha256']) in self._auxiliary:
            return aux(self, locator, root, family)
        token = meter.begin(artifact['compressed_bytes'], artifact['canonical_bytes'], 'auxiliary')
        value = aux(self, locator, root, family)
        meter.done(token)
        return value
    def bounded_graph(path, **kw):
        need(not metadata_only, 'metadata prepare forbids graph decode')
        token = meter.begin(kw['compressed_bytes'], kw['canonical_bytes'], 'source_graph')
        value = graph(path, **kw)
        meter.done(token)
        return value
    def bounded_read(self, relative, limit):
        need(not metadata_only or relative == 'manifest.json', 'metadata prepare forbids CodeType/text loads')
        n = (self.root / relative).stat().st_size
        token = meter.begin(n, n, 'archive_manifest' if relative == 'manifest.json' else 'archive_payload')
        value = read(self, relative, limit)
        need(len(value) == n, 'archive bytes changed')
        meter.done(token)
        return value
    def bounded_replay(path, *, limit):
        # This normal worker reads its own just-created SP5; include both bytes.
        n = Path(path).stat().st_size
        trailer = meter.begin(4, 0, 'SP5_trailer')
        with Path(path).open('rb') as stream:
            stream.seek(-4, 2)
            declared = int.from_bytes(stream.read(4), 'little')
        meter.done(trailer)
        token = meter.begin(n, declared, 'worker_SP5_readback')
        value = replay(path, limit=limit)
        need(value[1]['decoded_bytes'] == declared, 'SP5 trailer/readback size differs')
        meter.done(token)
        return value
    sa._plain, sa.SourceAttachments._aux = bounded_plain, bounded_aux
    sa.load_source_graph_artifact, CodeWitnessStore._read = bounded_graph, bounded_read
    sf._read_receipt = bounded_replay


def create_catalog(config):
    from scar.analysis.code_witness import CodeWitnessBudget
    from scar.analysis.compiler_witness_archives import CompilerArchiveBudget, CompilerWitnessArchives
    from scar.analysis.source_attachments import SourceAttachments, SourceAttachmentBudget
    from scar.analysis.source_entry_catalog import SourceEntryCatalog
    from scar.analysis.source_frontend_worklist import SourceFrontendBudget
    for declaration in config['archives']:
        need(receipt(declaration['manifest']['path']) == declaration['manifest'], 'archive manifest changed')
    cont = config['continuation']
    need(receipt(cont['path']) == cont, 'original continuation changed')
    owner = SourceAttachments(cont['path'], expected_report_sha256=cont['sha256'], project_root=config['project_root'],
        budget=SourceAttachmentBudget(max_report_bytes=8_000_000, max_files=256, max_codes=8192,
            max_roots=8, max_artifact_bytes=512_000_000, max_record_bytes=128_000_000, cached_files=2))
    archives = CompilerWitnessArchives(tuple((x['directory'], x['manifest']['sha256']) for x in config['archives']),
        store_budget=CodeWitnessBudget(max_compile_keys=64, max_source_files=64, max_source_bytes=2_000_000,
            max_module_bytes=32_000_000, max_archive_bytes=64_000_000, max_manifest_bytes=8_000_000),
        budget=CompilerArchiveBudget(max_archives=3, max_total_modules=64, max_total_sources=64,
            max_declared_payload_bytes=64_000_000))
    catalog = SourceEntryCatalog(admissions=(owner,), projects=(), archives=archives,
        max_groups=8192, max_candidates=8192, max_selected_decode_bytes=512_000_000)
    budget = SourceFrontendBudget(max_catalog_files=256, max_catalog_bodies=8192, max_catalog_groups=8192,
        max_dispatch_bodies=256, max_source_files=16, max_source_bytes=2_000_000,
        max_operations_per_body=config['budgets']['max_operations_per_body'],
        max_total_operations=config['budgets']['max_total_operations'], max_record_bytes=128_000_000,
        max_output_bytes=512_000_000, max_elapsed_seconds=900)
    return owner, archives, catalog, budget

def create_plan(config, out_dir):
    from scar.analysis.source_frontend_worklist import plan_source_entries
    owner, archives, catalog, budget = create_catalog(config)
    plan = plan_source_entries(catalog, budget=budget, out_dir=out_dir,
                               dispatch_order=config['dispatch_order'])
    need(len(plan.groups) == 817 and plan.document['summary']['current_calls'] == 100438,
         'original817groups/100438calls changed')
    return owner, archives, catalog, budget, plan


def main():
    config = json.loads((HERE / 'inputs.json').read_bytes())
    frozen = json.loads((HERE / 'freeze.json').read_bytes())
    meter = Meter(config['budgets']['input_stored_plus_decoded_bytes'])
    class GateTermination(BaseException):
        pass
    def terminated(signum, frame):
        raise GateTermination('external gate termination; partials retained')
    signal.signal(signal.SIGTERM, terminated)
    def check_freeze():
        for row in frozen['sources'] + frozen['control_inputs']:
            need(receipt(row['path']) == row, 'frozen source/control input changed: ' + row['path'])
    try:
        need(not (HERE / 'started.json').exists() and not (HERE / 'worker').exists(), 'worker gate must be fresh')
        save('started.json', {'status': 'RUNNING', 'freeze': receipt(HERE / 'freeze.json')})
        check_freeze()
        maximum = 4 * 1024 ** 3
        resource.setrlimit(resource.RLIMIT_AS, (maximum, maximum))
        install_meter(meter, metadata_only=False)
        owner, archives, catalog, budget, plan = create_plan(config, HERE / 'actual-plan')
        prepared = json.loads((HERE / 'metadata-window.json').read_bytes())
        need(plan.digest == prepared['plan_sha256'], 'normal metadata dispatch/producer changed')
        from scar.analysis.source_frontend_worklist import run_source_entries
        def progress(row):
            with (HERE / 'progress.jsonl').open('a') as stream:
                stream.write((canonical({'elapsed_s': time.monotonic()-START, **row})+b'\n').decode())
        worker = run_source_entries(plan, HERE / 'worker', budget=budget, progress=progress)
        worker.require_unchanged()
        need(not meter.exhausted, 'normal worker retained budget-frontier rows; gate input ceiling refused a read')
        counts = [dict(archives.store_for(row).counts) for row in archives.receipts()]
        need(all(row['compile_attempts'] == 0 and row['source_bytes_read'] == 0 for row in counts),
             'readonly archive compiled or read live source')
        check_freeze()
        output_bytes = sum(p.stat().st_size for p in HERE.rglob('*') if p.is_file())
        need(output_bytes <= 512_000_000, 'post-stage output512MB exceeded; partials retained')
        save('result.json', {'status': 'SOURCE_ENTRY_WORKER_WITH_OPEN', 'worker': worker.document,
            'readonly_counts': counts, 'input_IO': meter.report(), 'post_stage_directory_bytes': output_bytes,
            'live_owned_returns_expire_with_process': len(worker.owned_returns),
            'publication': 'NOT_RUN', 'current369749_binding': 'NOT_RUN', 'first_stage_complete': False,
            'elapsed_s': time.monotonic()-START})
        print(json.dumps({'status': 'SOURCE_ENTRY_WORKER_WITH_OPEN', 'counts': worker.document['counts'],
                          'input_IO': meter.report(), 'elapsed_s': time.monotonic()-START}), flush=True)
    except BaseException as error:
        save('failure.json', {'status': 'FAILED_RETAINED', 'type': type(error).__name__, 'detail': str(error),
            'traceback': traceback.format_exc(), 'input_IO': meter.report(), 'elapsed_s': time.monotonic()-START})
        raise
    finally:
        if (HERE / 'worker').exists():
            terminals = {}
            for path in (HERE / 'worker').glob('attempt-*/result.json'):
                row = json.loads(path.read_bytes()); terminals[row['entry_key']] = row
            starts = {}
            for path in (HERE / 'worker').glob('attempt-*/started.json'):
                row = json.loads(path.read_bytes()); starts[row['entry_key']] = row
            window = json.loads((HERE / 'metadata-window.json').read_bytes())['dispatch_entries']
            save('window-accounting.json', {'entries': [{'entry_key': row['entry_key'], 'source_calls': row['calls'],
                'status': terminals[row['entry_key']]['status'] if row['entry_key'] in terminals else
                    'STARTED_NO_TERMINAL' if row['entry_key'] in starts else 'NOT_ATTEMPTED'} for row in window],
                'scope': 'terminal preferred; started without terminal never relabeled unattempted'})

if __name__ == '__main__':
    main()
