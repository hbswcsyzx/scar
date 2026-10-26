"""Exact original ref closure for input pins; no CompositionIndex, graph or raw scan."""
from pathlib import Path
import gzip,hashlib,json
from config import HERE,ORIGINAL_GATE,REMAINDER

LIMIT=128_000_000
RECORD_LIMIT=16_000_000
pins={};missing={};read={};edges=[];deferred=[];total=0


def add(path,sha,size,*,basis):
    path=Path(path)
    if not path.is_absolute() or '..' in path.parts:raise ValueError('noncanonical original ref '+str(path))
    row={'path':str(path),'sha256':sha,'bytes':size}
    if str(path) in pins and pins[str(path)]!=row:raise ValueError('contradictory original physical ref '+str(path))
    pins[str(path)]=row
    edges.append({'from':basis,'to':str(path)})
    if not path.is_file():missing[str(path)]=row
    elif path.is_symlink() or path.resolve()!=path or path.stat().st_size!=size:raise ValueError('original stat differs '+str(path))
    return path


def reference(ref,root,basis):
    path=Path(ref['uri']) if ref.get('external',True) else root/ref['uri']
    return add(path,ref['physical_sha256'],ref['physical_bytes'],basis=basis)


def load(path,expected=None):
    global total
    path=Path(path)
    if str(path) in read:return read[str(path)]['document']
    if not path.is_file():return None
    if path.stat().st_size>RECORD_LIMIT:raise ValueError('metadata physical ceiling '+str(path))
    raw=path.read_bytes()
    if expected and (len(raw)!=expected['bytes'] or hashlib.sha256(raw).hexdigest()!=expected['sha256']):raise ValueError('metadata original digest differs '+str(path))
    payload=gzip.decompress(raw) if path.suffix=='.gz' else raw
    total+=len(payload)
    if len(payload)>RECORD_LIMIT or total>LIMIT:raise ValueError('metadata-only closure budget exceeded')
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:raise ValueError('duplicate JSON member')
            result[k]=v
        return result
    d=json.loads(payload,object_pairs_hook=pairs)
    read[str(path)]={'stored_bytes':len(raw),'decoded_bytes':len(payload),'document':d}
    return d


def walk(value,base,basis):
    if isinstance(value,list):
        for item in value:walk(item,base,basis)
    elif isinstance(value,dict):
        if value.get('schema')=='scar.partitioned-file-inventory':
            file=value['file']
            for key,child in file.items():
                if key!='bodies':walk(child,base,basis)
            for body in file['bodies']:
                if body['status'] not in ('UNSUPPORTED','NOT_ATTEMPTED'):
                    walk(body,base,basis)
            return
        if {'uri','physical_sha256','physical_bytes'}<=value.keys():
            reference(value,base,basis)
        elif {'artifact','decoded_sha256','decoded_bytes','representation','pointer'}<=value.keys():
            # Typed SourceArtifactLocator: physical source artifact. A bare
            # ProviderArtifact can instead be a logical archived raw URI.
            a=value['artifact']
            if {'uri','sha256','size_bytes'}<=a.keys():
                add(a['uri'],a['sha256'],a['size_bytes'],basis=basis)
        elif {'path','raw_sha256','raw_bytes'}<=value.keys() and Path(value['path']).is_absolute():
            add(value['path'],value['raw_sha256'],value['raw_bytes'],basis=basis)
        for child in value.values():walk(child,base,basis)


def main():
    original=json.loads((ORIGINAL_GATE/'inputs.json').read_text())
    for r in original['inputs']:add(r['path'],r['sha256'],r['bytes'],basis='original1313')
    previous_path=HERE/'NEEDED_INPUT_CLOSURE.json'
    if previous_path.is_file():
        for r in json.loads(previous_path.read_text())['all_pins']:
            add(r['path'],r['sha256'],r['bytes'],basis='previous exact metadata closure declaration; conservative retained pin')
    path=REMAINDER/'result/publication/manifest.json'
    ancestors=[]
    for depth in range(16):
        manifest=load(path,pins.get(str(path)))
        if manifest is None:break
        if manifest['schema']!='scar.partitioned-program-inventory':raise ValueError('not original inventory manifest')
        ancestors.append(str(path))
        refs=list(manifest['components'].items())+[("file-header",r) for r in manifest['files']]
        for name,r in refs:
            target=reference(r,path.parent,str(path))
            if name in ('interfaces','structured') or (name=='file-header' and depth>0):
                # Closed inventory schema: these body's artifact references
                # duplicate each file header's exact checkpoint references.
                # Pin the component, leave full normal typed decode to gate.
                deferred.append({'path':str(target),'component':name,'basis':'checkpoint refs enumerated from original file headers; no second interface/body authority'})
                continue
            d=load(target,pins.get(str(target)))
            if d is not None:
                if d.get('schema') not in ('scar.inventory-component','scar.partitioned-file-inventory'):
                    raise ValueError('metadata closure cannot decode body graphs '+str(target))
                walk(d,target.parent,str(target))
        if manifest['schema_version']==1:break
        r=manifest['parent_inventory'];path=reference(r,path.parent,str(path))
    else:raise ValueError('ancestor cycle/depth')
    # Dependency discovery only: old source858 binding metadata does not create
    # the fresh gate's owner, accepted bindings, or dynamic output facts.
    binding_path=ORIGINAL_GATE/'result/connections/source/bindings.json'
    r={'path':str(binding_path),'sha256':hashlib.sha256(binding_path.read_bytes()).hexdigest(),'bytes':binding_path.stat().st_size}
    add(r['path'],r['sha256'],r['bytes'],basis='retained858 source metadata dependency discovery only')
    d=load(binding_path,r)
    walk(d,binding_path.parent,str(binding_path))
    out={'schema':'scar.source-call-port-needed-input-closure/1','original_pins':1313,
        'all_pins':sorted(pins.values(),key=lambda r:r['path']),
        'new_pins':[r for r in sorted(pins.values(),key=lambda r:r['path']) if r['path'] not in {x['path'] for x in original['inputs']}],
        'missing':sorted(missing.values(),key=lambda r:r['path']),
        'missing_count':len(missing),'missing_stored_bytes':sum(r['bytes'] for r in missing.values()),
        'inventory_ancestors':ancestors,'metadata_reads':[{'path':p,**{k:v for k,v in r.items() if k!='document'}} for p,r in read.items()],
        'metadata_decoded_bytes':total,'metadata_decoded_ceiling_bytes':LIMIT,
        'reference_edges':edges,'deferred_component_payloads':deferred,'raw_or_graph_payload_read':False,'old_owner_reconstructed':False,
        'scope':'original inventory manifests/components/file headers plus retained858 reference metadata; all source/canonical bodies remain unparsed original refs'}
    (HERE/'NEEDED_INPUT_CLOSURE.json').write_text(json.dumps(out,indent=2)+'\n')
    (HERE/'MISSING_PINS.json').write_text(json.dumps({'inputs':out['missing'],'total_bytes':out['missing_stored_bytes'],'basis':str(HERE/'NEEDED_INPUT_CLOSURE.json')},indent=2)+'\n')
    print(json.dumps({k:out[k] for k in ('missing_count','missing_stored_bytes','metadata_decoded_bytes')}))


if __name__=='__main__':main()
