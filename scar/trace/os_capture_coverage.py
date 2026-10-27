"""Fail-closed, capture-bound syscall-filter coverage, never a run.sh guess.

Old captures have no independently bound actual-launch/profile declaration and
cannot obtain continuity qualification from their zero observed counters.
Explicit all-syscall selection or all required identity-control names are
admitted. Class filters contribute no inferred coverage without a catalog.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path

from scar.ir.record_codec import loads as strict_loads


class OSCaptureCoverageError(ValueError):
    pass


def _need(value,message):
    if not value:raise OSCaptureCoverageError('OS capture coverage: '+message)


def _document(path):
    path=Path(path).absolute()
    _need(path.is_file() and not path.is_symlink(),'explicit profile/launch artifact absent or symlinked')
    with path.open('rb') as stream:raw=stream.read(2_000_001)
    _need(len(raw)<=2_000_000,'coverage metadata budget exceeded')
    doc=strict_loads(raw.decode())
    _need(type(doc) is dict,'coverage artifact is not a document')
    receipt={'uri':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw),'schema':doc.get('schema')}
    return doc,receipt


def _explicit_all(options):
    """Interpret a small actual-strace-options grammar; no class catalog guesses."""
    _need(type(options) is list and all(type(x) is str for x in options),'actual option segment unavailable')
    safe_flags={'-f','-ff','-q','-qq','-qqq','-t','-tt','-ttt','-T','-v','-x','-xx','--seccomp-bpf'}
    safe_values={'-s','-o'}
    required={'clone','clone3','fork','vfork','execve','execveat','exit','exit_group','unshare','close_range'}
    _need(any(option in ('-f','-ff') for option in options),
          'descendant/thread following is not recorded in actual collector options')
    covered=False;i=0
    while i<len(options):
        option=options[i];i+=1
        if option in safe_flags:continue
        if option in safe_values:
            _need(i<len(options),'incomplete actual strace option');i+=1;continue
        if option=='-e':
            _need(i<len(options),'incomplete actual qualification');expression=options[i];i+=1
        elif option.startswith('-e') and len(option)>2:expression=option[2:]
        else:raise OSCaptureCoverageError('OS capture coverage: unsupported/filtering option '+option)
        if expression.startswith('trace='):
            selected=expression.split('=',1)[1]
            if selected=='all':covered=True
            else:
                tokens=selected.split(',')
                _need(tokens and all(token and (token.startswith('%') or token.replace('_','').isalnum())
                      and not any(marker in token for marker in ('!','?','/','@')) for token in tokens),
                      'unsupported/inverted syscall selection grammar')
                # Each trace qualification replaces the previous set. Class
                # tokens may add calls but are never credited here as coverage.
                covered=required<=set(token for token in tokens if not token.startswith('%'))
        elif expression.startswith('raw='):continue  # representation only; no selection authority.
        elif expression.startswith('abbrev='):
            _need(expression=='abbrev=!stat,lstat,fstat,newfstatat,statx',
                  'unsupported stat-detail representation contract')
            continue  # No syscall selection/completeness authority.
        else:raise OSCaptureCoverageError('OS capture coverage: selection is not explicit all: '+expression)
    _need(covered,'explicit all/control-name coverage not recorded; class-filter zero is not absence')


def _owned_v2(profile,launch,coords):
    """Validate the new owned producer chain, without arbitrary URI opens."""
    root=Path(coords['local_root']).absolute();nonce=profile['nonce']
    _need(str(root)==coords['original_root']==launch.get('capture_root'),
          'owned v2 relocation needs a separate explicit receipt adapter')
    intent,intent_receipt=_document(root/f'os-capture-intent.{nonce}.json')
    _need(intent.get('schema')=='scar.os-capture-intent' and intent.get('schema_version')==1
          and intent.get('nonce')==nonce and profile.get('intent')==launch.get('intent')==intent_receipt,
          'owned launch/intent exact receipts differ')
    _need(intent.get('capture_root')==str(root) and intent.get('trace_directory')==str(root/'trace')
          and intent.get('actual_exec_argv_planned')==launch['actual_exec_argv']
          and intent.get('target_argv_index')==launch['target_argv_index']
          and intent.get('target_argv')==launch['actual_exec_argv'][launch['target_argv_index']:],
          'owned actual target/intent namespace differs')
    from scar.trace.os_capture_selection import validate_launch_selection
    selection=validate_launch_selection(intent,launch,
        launch['actual_exec_argv'][1:launch['target_argv_index']])
    if selection is not None:
        _need(profile.get('selection_contract')==selection
              and profile.get('selection_profile')==selection['profile'],
              'capture-bound OS selection scope differs from actual launch')
    image=launch.get('running_image',{});precheck=launch.get('executable_precheck',{})
    _need(launch.get('status')=='CLOSED' and launch.get('returncode')==0 and launch.get('failure') is None
          and launch.get('budget_stop') is None and type(launch.get('provider_pid')) is int
          and launch['provider_pid']>0 and image.get('status')=='OBSERVED'
          and image.get('pid')==launch['provider_pid'] and image.get('source')==f"/proc/{launch['provider_pid']}/exe"
          and image.get('sha256')==precheck.get('sha256')==launch['executable_sha256']
          and image.get('size_bytes')==precheck.get('size_bytes')
          and launch.get('producer',{}).get('entrypoint')=='scar.trace.os_capture_launch.launch_os_capture',
          'owned running provider image/close receipt not qualified')
    expected=profile.get('native_manifest')
    found=[row for row in coords.get('membership',[]) if row.get('artifact')==expected]
    _need(len(found)==1,'native manifest has no unique exact capture membership')
    local=Path(found[0].get('local_path',found[0]['artifact']['uri']))
    _need(local.parent==root/'trace' and not local.is_symlink(),'native manifest escapes exact local namespace')
    native,receipt=_document(local)
    _need(receipt==expected and local.name==f"execution-evidence.{native.get('pid')}.json"
          and native.get('status')=='CLOSED' and native.get('failures')==[],
          'owned native manifest exact bytes/close differ')
    declaration=native.get('configuration',{}).get('os_capture_intent',{})
    native_nonce=Path(native['artifacts']['kineto']['path']).name.split('.')[2]
    _need(declaration.get('intent')==intent_receipt and declaration.get('capture_nonce')==nonce
          and declaration.get('native_nonce')==native_nonce,
          'owned native intent/capture/native nonce association differs')
    _need(profile.get('observation_completeness')=='UNKNOWN',
          'selection coverage cannot declare a complete event stream')
    _need(profile.get('provider_version')==launch.get('provider_version')
          and profile.get('architecture')==launch.get('architecture'),
          'owned provider version/architecture differ from actual launch')


@dataclass(frozen=True,init=False)
class OSCaptureCoverage:
    run: dict
    coordinates_receipt: dict
    archive_receipt: dict
    profile_receipt: dict
    launch_receipt: dict
    actual_strace_argv: tuple
    provider_version: str
    architecture: str
    profile: str='STRACE_EXPLICIT_SELECTION_CAPTURE_BOUND_V1'

    def __init__(self):
        raise TypeError('use OSCaptureCoverage.read with explicit capture-bound artifacts')

    @classmethod
    def read(cls,profile,*,launch,coordinates,archive):
        coords,coords_receipt=_document(coordinates)
        profile_doc,profile_receipt=_document(profile)
        launch_doc,launch_receipt=_document(launch)
        archive_doc,archive_receipt=_document(archive)
        binding=coords.get('os_capture_provider')
        _need(type(binding) is dict and binding.get('profile')==profile_receipt
              and binding.get('launch')==launch_receipt,
              'coordinates do not bind this actual-launch/provider profile; old metadata is not a coverage proof')
        protocol=profile_doc.get('schema_version')
        _need(profile_doc.get('schema')=='scar.os-capture-coverage' and type(protocol) is int and protocol in (1,2)
              and launch_doc.get('schema')=='scar.os-capture-launch' and launch_doc.get('schema_version')==protocol,
              'unsupported actual-launch/profile protocol')
        _need(profile_doc.get('run')==coords['run']['id'] and profile_doc.get('launch')==launch_receipt
              and profile_doc.get('archive')==archive_receipt
              and coords['seed']['archive_sha256']==archive_receipt['sha256'],'capture scope/receipts differ')
        nonce=launch_doc.get('nonce')
        _need(type(nonce) is str and len(nonce)>=16 and profile_doc.get('nonce')==nonce
              and binding.get('nonce')==nonce,'actual launch nonce is not capture-bound')
        _need(launch_doc.get('observation_kind')=='COLLECTOR_EXEC_ARGV'
              and launch_doc.get('actual_exec_argv')==profile_doc.get('actual_exec_argv'),
              'actual collector exec argv, not a proposed command/script, is required')
        argv=launch_doc['actual_exec_argv'];start=launch_doc.get('target_argv_index')
        _need(type(argv) is list and argv and all(type(x) is str for x in argv)
              and type(start) is int and 1<=start<len(argv),'actual executable/options/target boundary invalid')
        _explicit_all(argv[1:start])
        _need(type(profile_doc.get('provider_version')) is str and profile_doc['provider_version']
              and type(profile_doc.get('architecture')) is str and profile_doc['architecture']
              and profile_doc.get('executable_sha256')==launch_doc.get('executable_sha256')
              and type(profile_doc.get('executable_sha256')) is str and len(profile_doc['executable_sha256'])==64,
              'provider binary/version/architecture is not recorded')
        _need(profile_doc.get('stream_scope')=='CAPTURE_BOUND_REQUIRED_ACTORS'
              and profile_doc.get('known_selection_gaps')==[], 'capture selection scope has open gaps')
        if protocol==2:_owned_v2(profile_doc,launch_doc,coords)
        self=object.__new__(cls)
        values=(coords['run']['id'],coords_receipt,archive_receipt,profile_receipt,launch_receipt,
            tuple(argv),profile_doc['provider_version'],profile_doc['architecture'],
            'STRACE_EXPLICIT_SELECTION_CAPTURE_BOUND_V'+str(protocol))
        for name,value in zip(cls.__dataclass_fields__,values,strict=True):object.__setattr__(self,name,value)
        return self

    def require_fd_continuity(self,*,run,coordinates,archive):
        _need(self.run==run,'coverage belongs to another Run')
        _,actual_coords=_document(coordinates);_,actual_archive=_document(archive)
        _need(actual_coords==self.coordinates_receipt and actual_archive==self.archive_receipt,
              'coverage metadata changed or belongs to another capture')
        repeated=type(self).read(self.profile_receipt['uri'],launch=self.launch_receipt['uri'],
            coordinates=coordinates,archive=archive)
        _need(repeated==self,'actual-launch/profile coverage changed')


def require_fd_continuity_coverage(coverage,*,run,coordinates,archive):
    _need(type(coverage) is OSCaptureCoverage,
          'independently capture-bound actual filter coverage required; observed unshare/close_range=0 does not prove absence')
    coverage.require_fd_continuity(run=run,coordinates=coordinates,archive=archive)


__all__=['OSCaptureCoverage','OSCaptureCoverageError','require_fd_continuity_coverage']
