"""Owned opt-in strace execution and immutable capture receipts.

Intent is configuration, launch is a trusted producer's actual Popen receipt,
and coverage is a later Run/archive-bound derivation. None proves event/effect
completeness. Existing raw providers retain their original schemas and bytes.
"""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import platform
import secrets
import shutil
import signal
import subprocess
import time

from scar.ir.record_codec import loads as strict_loads
from scar.store.bundle_partitions import BundleBudgets, _line


INTENT_SCHEMA='scar.os-capture-intent'
LAUNCH_SCHEMA='scar.os-capture-launch'
PROFILE_SCHEMA='scar.os-capture-coverage'
VERSION=2
# Rendering only: this does not add or remove calls from trace=all. No raw
# exec/path/clone flags. Unknown interface semantics remain importer frontiers.
RAW_DATA_CALLS=('read','write','readv','writev','pread64','pwrite64','preadv','pwritev',
    'preadv2','pwritev2','ioctl','sendto','recvfrom','sendmsg','recvmsg','sendmmsg','recvmmsg',
    'getdents','getdents64','getrandom','process_vm_readv','process_vm_writev','setsockopt','getsockopt')
# Structure detail only for file identity providers. execve stays abbreviated;
# global -v would unnecessarily expand environment and unrelated structures.
STAT_DETAIL_EXPRESSION='abbrev=!stat,lstat,fstat,newfstatat,statx'


@dataclass(frozen=True)
class OSCaptureBudgets:
    max_os_bytes:int=128_000_000
    max_raw_bytes:int=256_000_000
    max_stored_bytes:int=128_000_000
    max_os_lines:int=2_000_000
    max_files:int=4096
    max_metadata_bytes:int=2_000_000
    max_seconds:int=300

    def __post_init__(self):
        _need(all(type(v) is int and v>0 for v in vars(self).values()),'positive exact budgets required')


def _need(value,message):
    if not value:raise ValueError('owned OS capture: '+message)


def _limits(budget):
    return BundleBudgets(max_record_bytes=budget.max_metadata_bytes,
        max_chunk_decoded_bytes=max(16_000_000,budget.max_metadata_bytes),
        max_chunk_stored_bytes=budget.max_stored_bytes,max_total_stored_bytes=budget.max_stored_bytes,
        max_total_decoded_bytes=budget.max_raw_bytes,max_manifest_bytes=budget.max_metadata_bytes)


def _receipt(path,schema,maximum=None):
    path=Path(path).absolute();_need(path.is_file() and not path.is_symlink(),'receipt file absent/symlinked')
    digest=hashlib.sha256();size=0
    with path.open('rb') as stream:
        while block:=stream.read(1_048_576):
            size+=len(block);_need(maximum is None or size<=maximum,'receipt byte budget exceeded');digest.update(block)
    return {'uri':str(path),'sha256':digest.hexdigest(),'size_bytes':size,'schema':schema}


def _document(path,maximum=2_000_000):
    path=Path(path).absolute();receipt=_receipt(path,'application/json',maximum)
    raw=path.read_bytes();_need(len(raw)==receipt['size_bytes'] and hashlib.sha256(raw).hexdigest()==receipt['sha256'],'metadata changed')
    doc=strict_loads(raw.decode());_need(type(doc) is dict,'metadata must be a document')
    receipt['schema']=doc.get('schema','application/json')
    return doc,receipt


def publish_bytes(path,raw):
    path=Path(path);temporary=path.with_name('.'+path.name+'.'+secrets.token_hex(16)+'.tmp')
    with temporary.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    os.link(temporary,path);temporary.unlink()


def _publish(path,doc,budget):
    publish_bytes(path,_line(doc,_limits(budget)))
    return _receipt(path,doc['schema'],budget.max_metadata_bytes)


def native_intent(trace_directory,native_nonce):
    """Read only the exact environment-selected intent under this trace root."""
    keys=('SCAR_OS_CAPTURE_NONCE','SCAR_OS_CAPTURE_INTENT','SCAR_OS_CAPTURE_INTENT_SHA256')
    values=[os.environ.get(k) for k in keys]
    if not any(values):return None
    _need(all(values),'incomplete native intent environment')
    nonce,path,sha=values;root=Path(trace_directory).absolute().parent
    _need(len(nonce)==32 and all(c in '0123456789abcdef' for c in nonce),'invalid capture nonce')
    expected=root/f'os-capture-intent.{nonce}.json'
    _need(Path(path).absolute()==expected,'intent is outside exact capture namespace')
    doc,receipt=_document(expected)
    _need(doc.get('schema')==INTENT_SCHEMA and doc.get('schema_version')==1
          and doc.get('nonce')==nonce and receipt['sha256']==sha
          and doc.get('capture_root')==str(root) and doc.get('trace_directory')==str(Path(trace_directory).absolute()),
          'native intent namespace/bytes differ')
    return {'capture_nonce':nonce,'intent':receipt,'native_nonce':native_nonce,
        'basis':'owned launcher environment and exact intent bytes; intent alone is not execution'}


def launch_os_capture(target_argv,*,env,capture_root,strace_executable='strace',budgets=None,
                      selection_profile='all'):
    """Execute exactly one owned provider; no attach, shell, or foreign process."""
    budget=budgets or OSCaptureBudgets();_need(type(budget) is OSCaptureBudgets,'explicit OS budgets required')
    from scar.trace.os_capture_selection import selection_contract
    selection=selection_contract(selection_profile)
    root=Path(capture_root).absolute()
    _need(root.is_dir() and not root.is_symlink() and (root/'trace').is_dir(),'fresh capture/trace root required')
    _need(not (root/'os').exists(),'fresh OS output required')
    _need(type(target_argv) is list and target_argv and all(type(v) is str for v in target_argv),'target argv required')
    binary=shutil.which(strace_executable,path=env.get('PATH'))
    _need(binary is not None,'strace executable unavailable');binary=Path(binary).resolve()
    binary_receipt=_receipt(binary,'application/x-executable',64_000_000)
    version=subprocess.run([str(binary),'-V'],capture_output=True,timeout=10,check=True)
    version_text=(version.stdout+version.stderr).decode('utf-8','replace')
    _need(len(version_text)<=16_384 and 'strace -- version' in version_text,'unrecognized provider version')
    nonce=secrets.token_hex(16);(root/'os').mkdir(mode=0o700)
    string_limit='4096' if env.get('SCAR_PROCESS_IMAGE_RECEIPTS')=='1' else '256'
    options=['-ff','-ttt','-T','-s',string_limit,'-e',selection['expression'],'-e','raw='+','.join(RAW_DATA_CALLS),
             '-o',str(root/'os/syscalls')]
    if selection['kernel_filter']=='REQUESTED_NOT_VERIFIED':
        options+=['--seccomp-bpf']
    if env.get('SCAR_PROCESS_IMAGE_RECEIPTS')=='1':
        options+=['-e',STAT_DETAIL_EXPRESSION]
    argv=[str(binary),*options,*target_argv];boundary=1+len(options)
    intent={'schema':INTENT_SCHEMA,'schema_version':1,'nonce':nonce,'capture_root':str(root),
        'trace_directory':str(root/'trace'),'actual_exec_argv_planned':argv,'target_argv_index':boundary,
        'target_argv':target_argv,'provider_precheck':binary_receipt,'budgets':vars(budget),
        'authority':'INTENT_ONLY_NOT_EXECUTION','raw_rendering':list(RAW_DATA_CALLS),
        'selection_contract':selection}
    intent_path=root/f'os-capture-intent.{nonce}.json';intent_receipt=_publish(intent_path,intent,budget)
    child_env=dict(env);child_env.update(SCAR_OS_CAPTURE_NONCE=nonce,
        SCAR_OS_CAPTURE_INTENT=str(intent_path),SCAR_OS_CAPTURE_INTENT_SHA256=intent_receipt['sha256'])
    started=time.monotonic();pid=None;process=None;returncode=None;failure=None;budget_stop=None
    image={'status':'OPEN','reason':'owned provider not started'}
    stderr_path=root/f'os-provider-stderr.{nonce}.txt'
    try:
        with stderr_path.open('xb') as diagnostic:
            process=subprocess.Popen(argv,env=child_env,stderr=diagnostic,start_new_session=True)
            pid=process.pid
            try:
                # An explicit kernel symlink is intended here, never a generic
                # artifact pathname or an unrelated PID lookup.
                digest=hashlib.sha256();size=0
                with (Path('/proc')/str(pid)/'exe').open('rb') as stream:
                    while block:=stream.read(1_048_576):
                        size+=len(block);_need(size<=64_000_000,'running image budget exceeded');digest.update(block)
                image={'status':'OBSERVED' if (size,digest.hexdigest())==(binary_receipt['size_bytes'],binary_receipt['sha256']) else 'OPEN',
                    'pid':pid,'source':f'/proc/{pid}/exe','sha256':digest.hexdigest(),'size_bytes':size,
                    'basis':'open kernel proc executable of own unreaped Popen child'}
            except (OSError,ValueError) as error:image={'status':'OPEN','reason':type(error).__name__+': '+str(error)[:512]}
            while process.poll() is None:
                os_bytes=sum(p.stat().st_size for p in (root/'os').iterdir() if p.is_file())
                diagnostic_bytes=stderr_path.stat().st_size
                # Sidecars can dwarf syscall output. Bound the whole owned raw
                # capture while it runs, rather than discover overflow only at
                # post-run archival. Do not read application data or contents.
                capture_bytes=os_bytes+diagnostic_bytes
                capture_files=0
                for path in (root/'trace').rglob('*'):
                    try:
                        if path.is_file():
                            capture_files+=1;capture_bytes+=path.stat().st_size
                    except FileNotFoundError:
                        continue  # A producer may atomically publish a file.
                if (os_bytes>budget.max_os_bytes or capture_bytes>budget.max_raw_bytes
                        or capture_files>budget.max_files or time.monotonic()-started>budget.max_seconds):
                    budget_stop=('OS_BYTES' if os_bytes>budget.max_os_bytes else
                        'CAPTURE_BYTES' if capture_bytes>budget.max_raw_bytes else
                        'CAPTURE_FILES' if capture_files>budget.max_files else 'WALL_SECONDS')
                    os.killpg(pid,signal.SIGTERM)
                    try:process.wait(timeout=5)
                    except subprocess.TimeoutExpired:os.killpg(pid,signal.SIGKILL)
                    break
                time.sleep(0.05)
            returncode=process.wait()
    except (OSError,subprocess.SubprocessError,ValueError) as error:
        failure={'type':type(error).__name__,'message':str(error)[:1024]}
        if process is not None and process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL);process.wait()
        if process is not None:returncode=process.returncode
    diagnostic_receipt=(_receipt(stderr_path,'text/plain',budget.max_raw_bytes)
        if stderr_path.stat().st_size<=budget.max_raw_bytes else
        {'uri':str(stderr_path),'size_bytes':stderr_path.stat().st_size,'sha256':None,'schema':'text/plain',
         'verification':'OPEN_DIAGNOSTIC_BYTE_BUDGET'})
    launch={'schema':LAUNCH_SCHEMA,'schema_version':VERSION,'nonce':nonce,'capture_root':str(root),
        'observation_kind':'COLLECTOR_EXEC_ARGV','status':'CLOSED','intent':intent_receipt,
        'actual_exec_argv':argv,'target_argv_index':boundary,'provider_pid':pid,'returncode':returncode,
        'provider_version':version_text,'architecture':platform.machine(),
        'executable_sha256':binary_receipt['sha256'],'executable_precheck':binary_receipt,'running_image':image,
        'budget_stop':budget_stop,'failure':failure,'elapsed_seconds':time.monotonic()-started,
        'diagnostics':diagnostic_receipt,
        'diagnostic_scope':'mixed inherited tracer/target stderr; no loss-free claim',
        'producer':{'entrypoint':'scar.trace.os_capture_launch.launch_os_capture',
            'source':_receipt(__file__,'text/x-python',2_000_000)},
        'selection':selection['expression']+' with follow-forks; raw affects rendering only',
        'selection_profile':selection_profile,'selection_contract':selection,
        'event_loss':'UNKNOWN','effect_completeness':'UNKNOWN','budgets':vars(budget)}
    launch_path=root/f'os-capture-launch.{nonce}.json';receipt=_publish(launch_path,launch,budget)
    _need(failure is None,'provider spawn failed; exact launch failure receipt retained')
    return subprocess.CompletedProcess(target_argv,returncode),receipt


def _native_input_archive_paths(root, budget):
    """Follow only the exact opt-in declaration, never glob companion members."""
    from scar.trace.tensor_physical import NATIVE_INPUT_PROFILE, PROVIDER_REVISION
    from scar.trace.native_tensor_inputs import read_native_tensor_inputs
    declarations = []
    for path in sorted((root/'trace').glob('execution-evidence.*.json')):
        native, _ = _document(path, budget.max_metadata_bytes)
        request = native.get('configuration', {}).get('native_tensor_input_observations')
        if request is not None:
            declarations.append((path, native, request))
    if not declarations:
        return []
    _need(len(declarations) == 1, 'one native input companion declaration required')
    path, native, request = declarations[0]
    _need(type(request) is dict, 'native input companion declaration must be an object')
    pid = native.get('pid')
    _need(type(pid) is int and pid > 0 and path.name == f'execution-evidence.{pid}.json'
          and native.get('status') == 'CLOSED' and native.get('failures') == []
          and native.get('provider', {}).get('torch_git_version') == PROVIDER_REVISION,
          'native input companion owner/provider is not closed')
    declared = Path(request.get('manifest', ''))
    stem = declared.parent.name
    prefix = f'native-tensor-inputs.{pid}.'
    nonce = stem[len(prefix):] if stem.startswith(prefix) else ''
    _need(len(nonce) == 32 and all(c in '0123456789abcdef' for c in nonce)
          and declared == root/'trace'/f'{prefix}{nonce}'/'manifest.json'
          and not declared.parent.is_symlink() and declared.parent.resolve().is_relative_to(root.resolve())
          and request.get('requested') is True and request.get('profile') == NATIVE_INPUT_PROFILE,
          'native input companion exact namespace/profile differs')
    _need(all(native.get('artifacts', {}).get(label, {}).get('path') == str(root/'trace'/name)
              for label, name in (('execution_trace', f'execution-trace.{pid}.{nonce}.json'),
                                  ('kineto', f'kineto.{pid}.{nonce}.json'))),
          'native input companion nonce differs from native artifacts')
    doc, receipt = _document(declared, budget.max_metadata_bytes)
    read_native_tensor_inputs(declared, expected_sha256=receipt['sha256'],
        max_bytes=budget.max_raw_bytes)
    return [declared.parent / chunk['path'] for chunk in doc['chunks']]


def _collector_witness_archive_paths(root,budget):
    """Only the explicit V2 owner declaration; keep plain CodeWitness readers working."""
    from scar.trace.collector_execution_witness import PROCESS_PROFILE,collector_witness_members
    declarations=[]
    for path in sorted((root/'trace').glob('execution-evidence.*.json')):
        native,_=_document(path,budget.max_metadata_bytes)
        request=native.get('configuration',{}).get('collector_execution_witness')
        if request is not None:declarations.append((path,native,request))
    if not declarations:return []
    _need(len(declarations)==1,'one explicit collector witness declaration required')
    native_path,native,request=declarations[0];pid=native.get('pid');issuer=request.get('issuer',{})
    token=issuer.get('uuid','');nonce=request.get('native_nonce')
    _need(type(pid)is int and issuer.get('process_id')==pid and issuer.get('generation')==1
          and type(token)is str and len(token)==32 and all(c in '0123456789abcdef' for c in token)
          and request.get('profile')==PROCESS_PROFILE and request.get('requested') is True
          and native.get('status')=='CLOSED' and native.get('failures')==[],
          'collector witness owner/profile is not a closed V2 capture')
    manifest=root/'trace'/('collector-witness.'+str(pid)+'.'+token)/'manifest.json'
    _need(request.get('manifest')==str(manifest) and
          native['artifacts']['kineto']['path']==str(root/'trace'/('kineto.'+str(pid)+'.'+str(nonce)+'.json')),
          'collector witness exact namespace/native nonce differs')
    _doc,r=_document(manifest,budget.max_metadata_bytes)
    witness,members=collector_witness_members(manifest,expected_sha256=r['sha256'])
    _need(witness['issuer']==issuer,'collector witness issuer differs from native declaration')
    return [Path(x['uri']) for x in members]


def archive_owned_capture(capture_root,*,budgets=None,workers=4):
    """Existing lossless archive v1, bounded store sink, no new graph format."""
    budget=budgets or OSCaptureBudgets();root=Path(capture_root).absolute()
    launches=list(root.glob('os-capture-launch.*.json'));_need(len(launches)==1,'one owned closed launch required')
    launch,_=_document(launches[0],budget.max_metadata_bytes)
    _need(launch.get('schema')==LAUNCH_SCHEMA and launch.get('schema_version')==VERSION
          and launch['capture_root']==str(root) and launch['returncode']==0
          and launch['failure'] is None and launch['budget_stop'] is None,'successful owned provider required')
    index=root/'archive-index.json';_need(not index.exists(),'fresh archive required')
    paths=sorted((root/'os').glob('syscalls.*'))
    paths+=sorted((root/'trace').glob('*.jsonl'))
    paths+=sorted((root/'trace').glob('execution-trace.*.json'))
    paths+=sorted((root/'trace').glob('kineto.*.json'))
    paths+=_native_input_archive_paths(root,budget)
    collector_paths=_collector_witness_archive_paths(root,budget)
    paths+=collector_paths
    from scar.store.capture_compression import compress_capture_members,remove_verified_originals
    rows,accounting,stamps=compress_capture_members(paths,root=root,limits=_limits(budget),
        max_raw_bytes=budget.max_raw_bytes,max_files=budget.max_files,os_directory=root/'os',
        max_os_lines=budget.max_os_lines,workers=workers)
    document={'schema':'scar.lossless-capture-archive','schema_version':1,'verified_roundtrip':True,'files':rows,
        'producer':'owned OS capture; existing lossless archive profile',
        'io_accounting':accounting,
        'runtime_observation_completeness':'UNKNOWN'}
    if collector_paths:
        document['capabilities']=['COLLECTOR_WITNESS_MEMBERS_V2']
        document['retained_plain_members']=[str(p) for p in collector_paths]
        document['retained_plain_basis']='exact witness declarations; unchanged CodeWitnessStore needs original plain files'
    receipt=_publish(index,document,budget)
    # Only our generated duplicate originals, after all roundtrips + manifest.
    remove_verified_originals(rows,stamps,retain=collector_paths)
    return receipt


def archive_stopped_capture(capture_root,*,budgets=None,workers=4,remove_originals=False):
    """Retain failed owned bytes compactly, without minting a successful Run.

    The separate partial schema/path cannot be substituted for archive-index
    in normal capture coverage. Small launch/native/terminal metadata stay put.
    """
    _need(type(remove_originals) is bool,'explicit original retention option required')
    budget=budgets or OSCaptureBudgets();root=Path(capture_root).absolute()
    launches=list(root.glob('os-capture-launch.*.json'))
    _need(len(launches)==1,'one owned closed launch required')
    launch,launch_receipt=_document(launches[0],budget.max_metadata_bytes)
    _need(launch.get('schema')==LAUNCH_SCHEMA and launch.get('schema_version')==VERSION
          and launch.get('capture_root')==str(root) and launch.get('status')=='CLOSED'
          and (launch.get('returncode')!=0 or launch.get('budget_stop') is not None
               or launch.get('failure') is not None),'closed incomplete owned capture required')
    index=root/'partial-archive-index.json';_need(not index.exists(),'fresh partial archive required')
    paths=sorted((root/'os').glob('syscalls.*'))
    paths+=sorted((root/'trace').glob('*.jsonl'))
    paths+=sorted((root/'trace').glob('execution-trace.*.json'))
    paths+=sorted((root/'trace').glob('kineto.*.json'))
    from scar.store.capture_compression import compress_capture_members,remove_verified_originals
    rows,accounting,stamps=compress_capture_members(paths,root=root,limits=_limits(budget),
        max_raw_bytes=budget.max_raw_bytes,max_files=budget.max_files,os_directory=root/'os',
        max_os_lines=budget.max_os_lines,workers=workers)
    document={'schema':'scar.partial-capture-archive','schema_version':1,'launch':launch_receipt,
        'verified_roundtrip':True,'files':rows,'io_accounting':accounting,
        'original_retention':'REMOVE_AFTER_VERIFIED_ARCHIVE' if remove_originals else 'RETAIN',
        'original_returncode':launch.get('returncode'),'original_budget_stop':launch.get('budget_stop'),
        'runtime_observation_completeness':'UNKNOWN','whole_model_established':False}
    receipt=_publish(index,document,budget)
    if remove_originals:remove_verified_originals(rows,stamps)
    return receipt


def bind_os_capture_provider(root,*,run,native,native_artifact,command,archive,publish=False,
                             allow_plain_preflight=False):
    """Derive profile after Run exists; never create a launch for an old run."""
    _need(type(allow_plain_preflight) is bool, 'plain preflight phase must be explicit')
    declaration=native.get('configuration',{}).get('os_capture_intent')
    if declaration is None:return None,[]
    root=Path(root).absolute();nonce=declaration.get('capture_nonce')
    _need(type(nonce) is str and len(nonce)==32 and all(c in '0123456789abcdef' for c in nonce),'native capture nonce invalid')
    intent_path=root/f'os-capture-intent.{nonce}.json';launch_path=root/f'os-capture-launch.{nonce}.json'
    intent,intent_receipt=_document(intent_path);launch,launch_receipt=_document(launch_path)
    _need(intent.get('schema')==INTENT_SCHEMA and intent.get('schema_version')==1 and intent['nonce']==nonce
          and launch.get('schema')==LAUNCH_SCHEMA and launch.get('schema_version')==VERSION
          and launch['nonce']==nonce and launch['intent']==intent_receipt==declaration['intent'],
          'actual launch/intent/native declaration receipts differ')
    _need(intent['capture_root']==launch['capture_root']==str(root)
          and intent['trace_directory']==str(root/'trace') and intent['target_argv']==command
          and launch['actual_exec_argv']==intent['actual_exec_argv_planned']
          and launch['target_argv_index']==intent['target_argv_index']
          and launch['actual_exec_argv'][launch['target_argv_index']:]==command,
          'actual launch namespace/target boundary differs')
    native_nonce=Path(native['artifacts']['kineto']['path']).name.split('.')[2]
    _need(declaration.get('native_nonce')==native_nonce,'native/provider nonce association differs')
    _need(launch['status']=='CLOSED' and launch['returncode']==0 and launch['failure'] is None
          and launch['budget_stop'] is None,'closed successful capture required')
    from scar.trace.os_capture_coverage import _explicit_all
    _explicit_all(launch['actual_exec_argv'][1:launch['target_argv_index']])
    from scar.trace.os_capture_selection import validate_launch_selection
    selection=validate_launch_selection(intent,launch,
        launch['actual_exec_argv'][1:launch['target_argv_index']])
    gaps=[{'code':'os_event_loss_not_established','basis':'selection/roundtrip/exit do not prove an event-complete stream'}]
    if launch['running_image'].get('status')!='OBSERVED':gaps.append({'code':'os_running_provider_image_unverified'})
    if archive is None:
        _need(allow_plain_preflight and not publish,'closed successful archived capture required')
        return {'launch':launch_receipt,'nonce':nonce,'profile':None,
            'selection_qualification':'PENDING_LOSSLESS_ARCHIVE',
            'observation_completeness':'UNKNOWN'},gaps+[{'code':'owned_archive_publication_pending'}]
    profile={'schema':PROFILE_SCHEMA,'schema_version':VERSION,'run':run,'nonce':nonce,
        'launch':launch_receipt,'intent':intent_receipt,'native_manifest':native_artifact,'archive':archive,
        'actual_exec_argv':launch['actual_exec_argv'],'executable_sha256':launch['executable_sha256'],
        'provider_version':launch['provider_version'],'architecture':launch['architecture'],
        'stream_scope':'CAPTURE_BOUND_REQUIRED_ACTORS','known_selection_gaps':[],
        'observation_completeness':'UNKNOWN','observation_frontiers':gaps,
        'basis':'owned actual Popen receipt + native intent/exec membership + explicit selection; not an absence oracle'}
    if selection is not None:
        profile['selection_contract']=selection
        profile['selection_profile']=selection['profile']
    path=root/f'os-capture-coverage.{nonce}.json'
    if path.exists():
        previous,receipt=_document(path);_need(previous==profile,'existing profile differs; never overwrite')
    else:
        _need(publish,'owned capture profile not finalized; explicit publisher required')
        receipt=_publish(path,profile,OSCaptureBudgets())
    return {'profile':receipt,'launch':launch_receipt,'nonce':nonce,
        'selection_qualification':'EXPLICIT_ARGV','observation_completeness':'UNKNOWN'},gaps


__all__=['OSCaptureBudgets','launch_os_capture','archive_owned_capture','archive_stopped_capture','native_intent',
         'bind_os_capture_provider','publish_bytes']
