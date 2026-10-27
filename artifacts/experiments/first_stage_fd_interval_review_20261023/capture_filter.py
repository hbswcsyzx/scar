"""Primary-source capture-category review; no target, ptrace or raw re-read."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import tarfile
import urllib.request


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
CAPTURE=ROOT/'artifacts/experiments/first_stage_lewm_physical_20261023'
urls={
 'amd64_sysent':'https://raw.githubusercontent.com/strace/strace/v6.8/src/linux/x86_64/syscallent.h',
 'common_sysent':'https://raw.githubusercontent.com/strace/strace/v6.8/src/linux/generic/syscallent-common.h',
 'class_definitions':'https://raw.githubusercontent.com/strace/strace/v6.8/src/sysent_shorthand_defs.h',
 'class_selection':'https://raw.githubusercontent.com/strace/strace/v6.8/src/basic_filters.c',
 'ubuntu_patches':'https://launchpad.net/ubuntu/+archive/primary/+sourcefiles/strace/6.8-0ubuntu2/strace_6.8-0ubuntu2.debian.tar.xz',
}


def fetch(item):
 name,url=item
 with urllib.request.urlopen(url,timeout=20) as response:raw=response.read(5_000_001)
 assert len(raw)<=5_000_000
 receipt={'url':url,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
 if name=='ubuntu_patches':
  headers={}
  with tarfile.open(fileobj=io.BytesIO(raw),mode='r:xz') as archive:
   for member in archive.getmembers():
    if member.isfile() and member.name.startswith('debian/patches/'):
     text=archive.extractfile(member).read().decode()
     headers[member.name]=[line for line in text.splitlines() if line.startswith(('--- ','+++ '))]
  receipt['patch_target_headers']=headers
 else:
  lines=raw.decode().splitlines();selected=set()
  needles={'amd64_sysent':('SEN(unshare)','syscallent-common.h'),
    'common_sysent':('SEN(close_range)',),
    'class_definitions':('# define TD','# define TF','# define TM','# define TP'),
    'class_selection':('TRACE_DESC,','TRACE_FILE,','TRACE_MEMORY,','TRACE_PROCESS,','sys_flags & n')}[name]
  for number,line in enumerate(lines):
   if any(needle in line for needle in needles):selected.update(range(max(0,number-1),min(len(lines),number+2)))
  receipt['excerpts']=[{'line':number+1,'text':lines[number]} for number in sorted(selected)]
 return name,receipt


with ThreadPoolExecutor(max_workers=4) as pool:sources=dict(pool.map(fetch,urls.items()))
result={'schema':'scar.capture-filter-coverage-review','schema_version':1,
 'status':'MISSING_MUTATOR_CAPTURE_COVERAGE','capture_strace_version':(CAPTURE/'strace-version.txt').read_text(),
 'capture_command_sha256':hashlib.sha256((CAPTURE/'run.sh').read_bytes()).hexdigest(),
 'capture_filter':'%file,%process,%memory,%desc','primary_sources':sources,
 'installed_strace_binary_sha256':hashlib.sha256(Path('/usr/bin/strace').read_bytes()).hexdigest(),
 'installed_package_observed':'strace 6.8-0ubuntu2 amd64',
 'captured_binary_at_run_not_hash_identified':True,
 'unshare_zero_observed_count_implies_absence':False,
 'close_range_zero_observed_count_implies_absence':False,
 'new_interval_container_bindings_approved':0,
 'previous_12110_count_means':'exact source/Run/line-range candidates only; required capture coverage is OPEN',
 'existing_35_continuity_claim':'conditional/unverified where it depends on absence of omitted mutators; old artifacts unchanged',
 'fd_scalar_projection_gate':'raw output values/record invariants remain valid; not a proof of container continuity',
 'production_changed':False,'new_raw_reads':0,'new_target_or_ptrace_runs':0,
 'full_execution_model_semantics':'OPEN','first_stage_complete':False}
with (HERE/'capture-coverage-correction.json').open('x') as stream:json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
print(json.dumps({'status':result['status'],'new_interval_container_bindings_approved':0,'sources':len(sources)}))
