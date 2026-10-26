"""Bounded representation measurements; no model/target evaluation."""
from pathlib import Path
from collections import Counter, defaultdict
import gzip, hashlib, io, json

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def canonical(v):return json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
def need(v,m):
    if not v:raise ValueError(m)

def fields(raw):
    """Locate complete top-level JSON values without materializing source graphs."""
    n=len(raw);i=0
    def ws(i):
        while i<n and raw[i]in b' \t\r\n':i+=1
        return i
    def string_end(i):
        need(raw[i]==34,'JSON string required');i+=1
        while i<n:
            if raw[i]==92:i+=2
            elif raw[i]==34:return i+1
            else:i+=1
        raise ValueError('unterminated JSON string')
    i=ws(i);need(raw[i]==123,'object expected');i+=1;out={}
    while True:
        i=ws(i)
        if raw[i]==125:break
        end=string_end(i);key=json.loads(bytes(raw[i:end]));need(key not in out,'duplicate JSON key')
        i=ws(end);need(raw[i]==58,'colon expected');i=ws(i+1);start=i
        if raw[i]==34:i=string_end(i)
        elif raw[i]in (123,91):
            stack=[125 if raw[i]==123 else 93];i+=1
            while stack:
                need(i<n,'unterminated JSON container')
                if raw[i]==34:i=string_end(i);continue
                if raw[i]in (123,91):stack.append(125 if raw[i]==123 else 93)
                elif raw[i]in (125,93):need(raw[i]==stack.pop(),'mismatched JSON delimiter')
                i+=1
        else:
            while i<n and raw[i]not in b',} \t\r\n':i+=1
        out[key]=(start,i);i=ws(i)
        if raw[i]==44:i+=1;continue
        need(raw[i]==125,'object separator expected');break
    need(ws(i+1)==n,'unexpected trailing JSON tokens')
    return out


def main():
    post=ROOT/'artifacts/experiments/source209_resume01_postflight01_20261026/receipt.json'
    success=json.loads(post.read_bytes())['result']['successful_programs']
    old=json.loads((ROOT/'artifacts/experiments/source209_model_20261026/result/entry-ledger.json').read_bytes())
    new=json.loads((ROOT/'artifacts/experiments/source209_resume01_20261026/result/entry-ledger.json').read_bytes())
    latest={r['entry_key']:r for r in old['entries']};latest.update({r['entry_key']:r for r in new['entries']})
    groups=defaultdict(list)
    for r in success:groups[latest[r['entry_key']]['file_key']].append(r)
    pairs=[sorted(g,key=lambda r:(r['program']['decoded_bytes'],r['entry_key']))[:2]for g in groups.values()if len(g)>1]
    pair=min(pairs,key=lambda g:(sum(r['program']['decoded_bytes']for r in g),g[0]['entry_key']))
    remainder=100_000_000-sum(r['program']['decoded_bytes']for r in pair)
    large=max((r for r in success if r not in pair and r['program']['decoded_bytes']<=remainder),key=lambda r:(r['program']['decoded_bytes'],r['entry_key']))
    selected=pair+[large];need(sum(r['program']['physical_bytes']for r in selected)<=64_000_000,'stored SP5 sample limit')
    results=[];decoded_total=stored_total=0
    for r in selected:
        p=r['program'];stored=Path(p['uri']).read_bytes();stored_total+=len(stored)
        need(len(stored)==p['physical_bytes']and hashlib.sha256(stored).hexdigest()==p['physical_sha256'],'original stored SP5 SHA differs')
        need(decoded_total+p['decoded_bytes']<=100_000_000,'decoded sample limit')
        with gzip.GzipFile(fileobj=io.BytesIO(stored))as stream:
            raw=stream.read(p['decoded_bytes']+1)
            need(not stream.read(1),'unexpected gzip suffix data')
        decoded_total+=len(raw);need(len(raw)==p['decoded_bytes']and hashlib.sha256(raw).hexdigest()==p['decoded_sha256'],'original canonical SP5 SHA differs')
        view=memoryview(raw);table=fields(view);metrics={}
        for key,(a,b)in table.items():metrics[key]={'bytes':b-a,'sha256':hashlib.sha256(view[a:b]).hexdigest()}
        nested={}
        for parent in ('language','metadata'):
            if parent not in table:continue
            a,b=table[parent]
            if view[a]!=123:continue
            children=fields(view[a:b]);nested[parent]={k:{'bytes':end-start,'sha256':hashlib.sha256(view[a+start:a+end]).hexdigest()}for k,(start,end)in children.items()}
            if parent=='language'and'code_evidence'in children:
                c,d=children['code_evidence']
                if view[a+c]==123:
                    proof=fields(view[a+c:a+d]);nested['language.code_evidence']={k:{'bytes':end-start,'sha256':hashlib.sha256(view[a+c+start:a+c+end]).hexdigest()}for k,(start,end)in proof.items()}
        overhead=len(raw)-sum(v['bytes']for v in metrics.values())
        results.append({'entry_key':r['entry_key'],'file_key':latest[r['entry_key']]['file_key'],'program':p,'fields':metrics,'nested':nested,'top_key_delimiter_newline_bytes':overhead})
        del view,raw,stored
    common=[]
    for name in results[0]['fields']:
        a,b=results[0]['fields'][name],results[1]['fields'].get(name)
        if b==a:common.append({'field':name,**a})
    context_names=('semantic','semantics','control')
    contexts=[sum(row['fields'].get(k,{'bytes':0})['bytes']for k in context_names)for row in results]
    common_context=sum(x['bytes']for x in common if x['field']in context_names)
    relation=json.loads((HERE/'relation-samples.json').read_bytes());objects=[]
    def fact_kind(v):
        if not isinstance(v,dict):return None
        keys=set(v)
        if keys=={'coordinates','process','run'}:return'RuntimeScope'
        if keys=={'schema','sha256','size_bytes','uri'}:return'ProviderArtifact'
        if keys=={'artifact','locator'}:return'FactSourceLocator'
        if keys=={'atom_id','end_column','end_line','fingerprint','path','start_column','start_line'}:return'SourceReference'
        return None
    def walk(v,path,prune=False):
        kind=fact_kind(v)
        if kind:
            raw=canonical(v);objects.append({'kind':kind,'path':path,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'pruned':prune})
            if prune:return
        if isinstance(v,dict):
            for k,x in v.items():walk(x,path+'/'+k,prune)
        elif isinstance(v,list):
            for i,x in enumerate(v):walk(x,path+'/'+str(i),prune)
    for row in relation['samples']:walk(row['value'],row['kind']+str(row['row_ordinal']))
    inclusive=objects;objects=[]
    for row in relation['samples']:walk(row['value'],row['kind']+str(row['row_ordinal']),True)
    def stats(rows):
        groups=defaultdict(list)
        for r in rows:groups[(r['kind'],r['sha256'])].append(r)
        out={}
        for kind in sorted({r['kind']for r in rows}):
            g=[values for(key,digest),values in groups.items()if key==kind]
            out[kind]={'occurrences':sum(len(x)for x in g),'unique_exact_objects':len(g),'payload_bytes':sum(len(x)*x[0]['bytes']for x in g),'duplicate_payload_bytes_before_refs':sum((len(x)-1)*x[0]['bytes']for x in g)}
        return out
    nonoverlap=stats(objects);row_bytes=sum(x['decoded_line_bytes']for x in relation['samples'])
    summary={'scope':'bounded representation audit, no graph logical changes, no typed-model validation or whole-corpus extrapolation',
        'SP5_selection_policy':'minimum combined decoded same-file pair, then largest remaining artifact fitting100MB; no name filter',
        'SP5_sample_count':3,'SP5_stored_bytes_read':stored_total,'SP5_decoded_bytes':decoded_total,
        'SP5_samples':results,'same_file_pair_exact_equal_top_fields':common,
        'context_fields':list(context_names),'context_bytes_per_sample':contexts,'context_total_bytes':sum(contexts),
        'context_fraction_of_three_samples':sum(contexts)/decoded_total,
        'same_file_pair_context_duplicate_payload_bytes':common_context,
        'same_file_pair_duplicate_context_fraction':common_context/sum(x['program']['decoded_bytes']for x in results[:2]),
        'largest_declared_program_excluded_by100MB_budget':max(r['program']['decoded_bytes']for r in success),
        'relation_sample_rows':6,'relation_stored_chunk_bytes':relation['stored_chunk_bytes_read'],
        'relation_decoded_manifest_and_rows':relation['decoded_manifest_and_rows_bytes'],
        'relation_row_bytes':row_bytes,'relation_inclusive_fact_stats_do_not_sum':stats(inclusive),
        'relation_nonoverlap_maximal_fact_stats':nonoverlap,
        'relation_nonoverlap_duplicate_payload_bytes_before_reference_overhead':sum(r['duplicate_payload_bytes_before_refs']for r in nonoverlap.values()),
        'relation_nonoverlap_duplicate_fraction':sum(r['duplicate_payload_bytes_before_refs']for r in nonoverlap.values())/row_bytes,
        'actual_new_compact_transport_savings':'NOT_MEASURED; refs/table/check overhead not implemented',
        'original_programs_relations_unchanged':True,'target_worker_fixture':'NOT_RUN'}
    (HERE/'MEASUREMENTS.json').write_text(json.dumps(summary,sort_keys=True,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items()if k not in('SP5_samples','same_file_pair_exact_equal_top_fields','relation_inclusive_fact_stats_do_not_sum')},indent=2),flush=True)

if __name__=='__main__':main()
