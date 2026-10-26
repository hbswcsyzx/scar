"""Independent metadata/stored-byte postflight; never resumes either worker."""
from collections import Counter
from pathlib import Path
import hashlib, json, re, resource, time, traceback

HERE = Path(__file__).resolve().parent


def need(value, detail):
    if not value:
        raise ValueError(detail)


class Reader:
    def __init__(self):
        self.stored = self.decoded = 0
        self.receipts = []

    def charge(self, size):
        need(self.stored + size <= 512_000_000, 'postflight stored budget exceeded before read')
        self.stored += size

    def check(self, expected, *, metadata=False):
        path = Path(expected['path']); size = path.stat().st_size
        need(size == expected['bytes'], 'stored size differs: ' + str(path))
        need(not metadata or size <= 8_000_000, 'metadata record exceeds8MB')
        need(self.stored + size <= 512_000_000, 'postflight stored budget exceeded before read')
        digest = hashlib.sha256(); actual = 0; parts = []
        with path.open('rb') as stream:
            while raw := stream.read(1_048_576):
                actual += len(raw); self.stored += len(raw); digest.update(raw)
                if metadata:
                    parts.append(raw)
        need(actual == size and digest.hexdigest() == expected['sha256'], 'stored SHA/size differs: ' + str(path))
        self.receipts.append(expected)
        if metadata:
            need(self.decoded + size <= 32_000_000, 'postflight JSON budget exceeded')
            self.decoded += size
            return json.loads(b''.join(parts))


def main():
    started = time.monotonic(); reader = Reader(); failure = None; result = None
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    try:
        freeze_path = HERE/'freeze.json'; freeze_size = freeze_path.stat().st_size
        need(freeze_size <= 8_000_000, 'postflight control record too large')
        with freeze_path.open('rb') as stream:
            raw = stream.read(freeze_size + 1)
        reader.charge(len(raw)); reader.decoded += len(raw)
        need(len(raw) == freeze_size, 'postflight control grew during read')
        config = json.loads(raw)
        reader.check(config['restoration_receipt'], metadata=True)
        for row in config['postflight_sources']:
            reader.check(row)
        oldfreeze = reader.check(config['original_freeze'], metadata=True)
        freeze = reader.check(config['resume_freeze'], metadata=True)
        oldledger = reader.check(config['original_ledger'], metadata=True)
        ledger = reader.check(config['resume_ledger'], metadata=True)
        oldterminal = reader.check(config['original_terminal'], metadata=True)
        terminal = reader.check(config['resume_terminal'], metadata=True)
        for doc in (oldterminal, terminal):
            need(doc['status'] == 'FAILED_RETAINED_WITH_OPEN', 'original failed status changed')
        need(Counter(oldledger['current_entry_statuses']) == Counter(SUCCEEDED=63, UNSUPPORTED=49, FAILED=17, PENDING_NOT_STARTED=80), 'old209 history differs')
        need(ledger['current_entry_statuses'] == {'SUCCEEDED':52, 'UNSUPPORTED':45}, 'resume97 terminal statuses differ')
        oldrows = {r['entry_key']:r for r in oldledger['entries']}
        newrows = {r['entry_key']:r for r in ledger['entries']}
        need(len(oldrows)==209 and len(newrows)==97, 'original209/resume97 duplicate keys/count differs')
        need(set(newrows)=={k for k,r in oldrows.items() if r['status'] in ('FAILED','PENDING_NOT_STARTED')}, 'resume redispatched a previous successful/unsupported key')
        need(ledger['retained_previous112_entries']==[r for r in oldledger['entries'] if r['status'] in ('SUCCEEDED','UNSUPPORTED')], 'retained previous112 history differs')
        latest = {**oldrows, **newrows}
        need(Counter(r['status'] for r in latest.values()) == Counter(SUCCEEDED=115, UNSUPPORTED=94), 'latest209 conservation differs')
        need(ledger['all209_latest_statuses']==dict(Counter(r['status'] for r in latest.values())), 'saved latest209 summary differs')
        public = {}
        for row in config['public_terminals']:
            record = reader.check(row, metadata=True)
            need(record['schema']=='scar.source-frontend-attempt' and record['entry_key']==row['entry_key'], 'ordinary public terminal identity/schema differs')
            public[row['path']] = record
        for ledger_rows in (oldrows, newrows):
            for key, row in ledger_rows.items():
                if 'public_terminal' not in row:
                    need(row['status']=='PENDING_NOT_STARTED', 'nonpending entry omitted terminal')
                    continue
                record = public[row['public_terminal']]
                need(record['entry_key']==key and record['status']==row['status'] and record['program']==row['program'], 'public result/ledger reference or status differs')
        need(len(public)==226 and Counter(r['status'] for r in public.values())==Counter(SUCCEEDED=115,UNSUPPORTED=94,FAILED=17), 'full226 immutable terminal history differs')
        for record in public.values():
            if record['status']=='FAILED':
                need(record['error']['type']=='FileNotFoundError' and record['error']['detail']==config['original_missing_continuation_detail'], 'historical17 failure changed')
        programs = []
        for key, row in latest.items():
            record = public[row['public_terminal']]
            if row['status']=='SUCCEEDED':
                need(record['public_structure_reader'] is True and record['independent_code_reader'] is True, 'successful program lacks original normal reader/code consumer result')
                program=record['program']
                need(program['representation']=='scar.source-program/5' and program['external'] is True, 'successful artifact representation differs')
                need(type(program['decoded_bytes']) is int and program['decoded_bytes']>0 and re.fullmatch('[0-9a-f]{64}',program['decoded_sha256']), 'canonical declaration malformed')
                reader.check({'path':program['uri'],'bytes':program['physical_bytes'],'sha256':program['physical_sha256']})
                programs.append({'entry_key':key,'program':program,'qualification':'stored SHA checked; canonical/semantic validation retained from original ordinary worker, not repeated'})
            else:
                need(record['program'] is None, 'unsupported row invented a program')
        need(len(programs)==len({p['program']['uri']for p in programs})==115, 'successful stored artifact set repeats or loses entry')
        # Current bytes against the ORIGINAL expected source/runtime/input pins.
        # Restored control files cannot retroactively repair the original exit1.
        categories = {}
        for name in ('sources','runtime','inputs'):
            for row in freeze[name]:
                reader.check(row)
            categories[name]={'files':len(freeze[name]),'bytes':sum(r['bytes']for r in freeze[name]),'all_original_SHA_and_sizes_match_now':True}
        need(len(freeze['inputs'])==463, 'original frozen input denominator differs')
        for directory, expected in freeze['archive_members'].items():
            need(sorted(str(p)for p in Path(directory).iterdir()if p.is_file())==expected, 'original readonly archive member set changed')
        early=[]
        for ref in config['early_terminal_receipts']:
            record=reader.check(ref,metadata=True)
            if record.get('schema')=='scar.source-frontend-attempt': early.append(record)
        need(Counter(r['status']for r in early)==Counter(SUCCEEDED=26,UNSUPPORTED=7) and len({r['entry_key']for r in early})==33, 'earlier33 preserved terminal scope differs')
        need(not ({r['entry_key']for r in early}&set(latest)), 'earlier33 overlap latest209')
        need(oldledger['original_groups']==ledger['original_groups']==817 and oldledger['original_calls']==ledger['original_calls']==100438 and ledger['source_verified_candidates']==243, 'original catalog denominators changed')
        need(len(ledger['resumable_frontiers'])==1, 'original resumable frontier lost')
        result={'status':'INDEPENDENT_METADATA_AND_STORED_POSTFLIGHT_PASS_WITH_OPEN','original_gates':[{'actual_exit':1,'status':oldterminal['status'],'elapsed_s':oldterminal['elapsed_s']},{'actual_exit':1,'status':terminal['status'],'elapsed_s':terminal['elapsed_s']}],
            'history226':dict(Counter(r['status']for r in public.values())),'latest209':dict(Counter(r['status']for r in latest.values())),
            'original817_groups_100438_calls_243_candidates_retained':True,'earlier33':{'SUCCEEDED':26,'UNSUPPORTED':7},'original_resumable_frontiers':ledger['resumable_frontiers'],
            'original_frozen_bytes_checked_now':categories,'four_readonly_archive_members_unchanged':True,
            'successful_programs':programs,'program_stored_bytes_checked':sum(r['program']['physical_bytes']for r in programs),'program_canonical_bytes_declared_not_decoded':sum(r['program']['decoded_bytes']for r in programs),
            'original_live_owners_restored':False,'source_graph_CodeType_compile_lower_worker_target_publication_currentRun_binding':False,
            'original_gate_exit1_requalified':False,'original_missing_at_finalcheck_history':'RETAINED; later byte restoration does not change either gate status',
            'runtime_source858_bodycalls6882_unchanged':True,'whole_first_stage_complete':False}
    except BaseException as error:
        failure={'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc()}
    final={'schema':'scar.source209-independent-postflight/1','result':result,'failure':failure,
           'actual_stored_bytes_read':reader.stored,'JSON_decoded_bytes':reader.decoded,'elapsed_s':time.monotonic()-started,
           'budget':{'stored':512_000_000,'JSON':32_000_000,'record':8_000_000,'output':8_000_000,'AS':1024**3,'external_wall_seconds':180},
           'scope':'metadata and stored hashes only; original canonical/normal consumer results are retained facts, not independently decoded again'}
    raw=json.dumps(final,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()+b'\n'
    need(len(raw)<=8_000_000,'postflight output exceeded8MB')
    with (HERE/'receipt.json').open('xb')as stream:stream.write(raw)
    print(json.dumps({'status':result['status']if result else'FAILED_RETAINED','failure':failure,'stored':reader.stored,'JSON':reader.decoded,'elapsed_s':final['elapsed_s']}),flush=True)
    return 1 if failure else 0


if __name__=='__main__':
    raise SystemExit(main())
