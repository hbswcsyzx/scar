"""Version-limited official CPython symtable(flags), with an isolated helper.

The adapter never executes its input source or edits it. When the running
interpreter hides the internal entry, a separately built copy of the fixed
official runtime hosts the same C++ wrapper as a built-in module. The existing
capture_raw_view runs beside the official native entries; only its normalized
rows cross the process boundary. No native addresses are serialized.
"""
import argparse
from dataclasses import dataclass
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import urllib.request
import warnings


ROOT = Path(__file__).resolve().parents[2]
CPP = ROOT/'scar/native/symtable_context.cpp'
DEFAULT = ROOT/'artifacts/current/native/symtable-context-3.14.7'
COMMIT = '823f0323ee6ec1402088b73bce1a38473cac36dc'
ARCHIVE_SHA256 = '50e9367f9b4593e8fb78aedf913172b506930b27cdf21be918214c233de1de46'
SETUP = '*static*\n_scar_symtable_context symtable_context.cpp -DSCAR_SYMTABLE_DIRECT -lstdc++\n'


def _hash(raw):
    return sha256(raw).hexdigest()


def _file(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return dict(path=str(path),bytes=len(raw),sha256=_hash(raw))


def _tree(directory, pattern='*.h'):
    directory = Path(directory)
    rows = [(str(p.relative_to(directory)),_hash(p.read_bytes())) for p in sorted(directory.rglob(pattern))]
    return dict(path=str(directory.resolve()),files=len(rows),
        sha256=_hash(json.dumps(rows,separators=(',',':')).encode()))


def _version():
    if (sys.implementation.name != 'cpython' or tuple(sys.version_info) != (3,14,7,'final',0)
            or sysconfig.get_config_var('Py_GIL_DISABLED')):
        raise ValueError('this prototype requires GIL-enabled CPython 3.14.7 final')


def _native_module(path):
    spec = importlib.util.spec_from_file_location('_scar_symtable_context',str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(command, log, *, cwd=None, env=None):
    with Path(log).open('ab') as output:
        subprocess.run(command,cwd=cwd,env=env,stdout=output,stderr=subprocess.STDOUT,check=True)


def build_adapter(directory=DEFAULT, *, jobs=24):
    """Explicit build only; artifacts stay below directory, with no install."""
    _version()
    if type(jobs) is not int or not 1 <= jobs <= 32:
        raise ValueError('helper jobs must be an integer from 1 to 32')
    directory = Path(directory).absolute()
    directory.mkdir(parents=True,exist_ok=True)
    include = Path(sysconfig.get_path('include'))
    compiler = Path(shutil.which('g++')).resolve()
    native = directory/('_scar_symtable_context'+sysconfig.get_config_var('EXT_SUFFIX'))
    native_command = [str(compiler),'-std=c++20','-shared','-fPIC','-O2','-I'+str(include),
        str(CPP),'-o',str(native),'-ldl']
    _run(native_command,directory/'native-build.log')
    probe = _native_module(native).probe()
    source = directory/('cpython-'+COMMIT)
    helper = None
    if not (probe['builder'] and probe['free']):
        archive = directory/'cpython.tar.gz'
        url = 'https://codeload.github.com/python/cpython/tar.gz/'+COMMIT
        if not archive.exists():
            urllib.request.urlretrieve(url,archive)
        if _hash(archive.read_bytes()) != ARCHIVE_SHA256:
            raise ValueError('fixed official CPython archive differs')
        if not source.exists():
            with tarfile.open(archive) as stream:
                stream.extractall(directory,filter='data')
        if '#define PY_VERSION              "3.14.7"' not in (source/'Include/patchlevel.h').read_text():
            raise ValueError('official helper source version differs')
        copied = source/'Modules/symtable_context.cpp'
        if not copied.exists() or copied.read_bytes() != CPP.read_bytes():
            shutil.copyfile(CPP,copied)
        setup = source/'Modules/Setup.local'
        if not setup.exists() or setup.read_text() != SETUP:
            setup.write_text(SETUP)
        configure = ['./configure','--without-ensurepip','--disable-test-modules','--with-pkg-config=no']
        environment = dict(os.environ,CFLAGS='-O1',CXX='g++ -std=c++20')
        if not (source/'Makefile').exists():
            _run(configure,directory/'configure.log',cwd=source,env=environment)
        _run(['make','-j'+str(jobs)],directory/'make.log',cwd=source)
        helper = dict(source=dict(repository='https://github.com/python/cpython',tag='v3.14.7',
            commit=COMMIT,url=url,archive=_file(archive)), executable=_file(source/'python'),
            headers=_tree(source/'Include'),configuration=_file(source/'pyconfig.h'),
            makefile=_file(source/'Makefile'),setup=_file(setup),wrapper=_file(copied),
            extension_modules=_tree(source/'build','*.so'),
            official_symtable=_file(source/'Python/symtable.c'),
            official_public_wrapper=_file(source/'Modules/symtablemodule.c'),
            source_patch='ADD_BUILTIN_MODULE_REGISTRATION_ONLY_NO_COMPILER_OR_SOURCE_REWRITE',
            build_commands=[configure,['make','-j'+str(jobs)]],
            configure_environment=dict(CFLAGS='-O1',CXX='g++ -std=c++20'))
    from scar.analysis import source_symbols
    from scar.ir import record_codec
    from scar.ir.program import source_symbols as symbol_types
    receipt = dict(schema='scar.cpython-symtable-context-adapter',schema_version=1,
        runtime=dict(version=sys.version,executable=_file(sys.executable),headers=_tree(include),
            pyconfig=_file(include/'pyconfig.h'),soabi=sysconfig.get_config_var('SOABI')),
        adapter=_file(__file__),cpp=_file(CPP),native=_file(native),native_probe=probe,
        compiler=dict(binary=_file(compiler),version=subprocess.check_output([str(compiler),'--version'],text=True)),
        normalizer_pins=[_file(module.__file__) for module in (source_symbols,symbol_types,record_codec)],
        native_build_command=native_command,helper=helper,
        backend='CURRENT_RUNTIME' if helper is None else 'ISOLATED_OFFICIAL_RUNTIME',
        native_unavailable_reason=None if helper is None else
            'CURRENT_PROCESS_DOES_NOT_EXPORT__Py_SymtableStringObjectFlags_AND_OR__PySymtable_Free',
        target_executed=False,environment_installed=False)
    (directory/'result.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
    return receipt


def _profile():
    import _symtable
    from types import MemberDescriptorType
    from scar.analysis.source_symbols import compiler_hash_context
    raw = _symtable.symtable('pass\n','<scar-native-schema>','exec')
    return dict(version=list(sys.version_info),python=sys.version,
        constants={n:v for n,v in vars(_symtable).items() if type(v) is int},
        raw_members=[n for n,v in vars(type(raw)).items() if type(v) is MemberDescriptorType],
        compiler_hash_context=compiler_hash_context())


def _capture(native, request):
    from scar.analysis.source_symbols import capture_raw_view
    from scar.ir.record_codec import encode
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        raw = native.symtable_flags(request['text'],request['filename'],request['mode'],request['effective_flags'])
        scopes = capture_raw_view(raw,max_scopes=request['max_scopes'],max_symbols=request['max_symbols'])
    return dict(scopes=encode(scopes),warnings=[dict(category=w.category.__module__+'.'+w.category.__qualname__,
        message=str(w.message),filename=w.filename,lineno=w.lineno) for w in caught])


@dataclass(frozen=True)
class SymbolContextCapture:
    scopes: tuple
    request: dict
    profile: dict
    warnings: tuple
    adapter_receipt: dict


class SymbolContextError(ValueError):
    def __init__(self, error):
        self.error = error
        super().__init__('official symtable compiler rejected input: '+json.dumps(error))


class SymbolContextAdapter:
    """Persistent isolated compiler worker; input text is never evaluated."""
    def __init__(self, directory=DEFAULT):
        _version()
        self.directory = Path(directory).absolute()
        raw = (self.directory/'result.json').read_bytes()
        self.receipt = json.loads(raw)
        if (self.receipt['schema'],self.receipt['schema_version']) != ('scar.cpython-symtable-context-adapter',1):
            raise ValueError('symtable adapter receipt schema differs')
        for field,path in (('adapter',__file__),('cpp',CPP),('native',self.receipt['native']['path'])):
            if _file(path) != self.receipt[field]:
                raise ValueError('symtable adapter implementation changed: '+field)
        if _file(sys.executable) != self.receipt['runtime']['executable']:
            raise ValueError('current interpreter binary differs from adapter build')
        for pin in self.receipt['normalizer_pins']:
            if _file(pin['path']) != pin:
                raise ValueError('raw symbol-view normalizer differs')
        self.parent = dict(path=str(self.directory/'result.json'),sha256=_hash(raw))
        self.process = None
        self.native = None
        if self.receipt['backend'] == 'CURRENT_RUNTIME':
            self.native = _native_module(self.receipt['native']['path'])
            self.profile = _profile()
        else:
            helper = self.receipt['helper']
            for field in ('executable','configuration','setup','wrapper','official_symtable','official_public_wrapper'):
                if _file(helper[field]['path']) != helper[field]:
                    raise ValueError('official helper changed: '+field)
            if _tree(Path(helper['executable']['path']).parent/'build','*.so') != helper['extension_modules']:
                raise ValueError('official helper extension artifacts changed')
            # -I/-E would also ignore PYTHONHASHSEED. Safe-path plus no site,
            # with all other Python environment inputs removed, keeps this
            # worker independent while making official symbol order replayable.
            environment = {k:v for k,v in os.environ.items() if not k.startswith('PYTHON')}
            environment['PYTHONHASHSEED'] = '0'
            self.process = subprocess.Popen([helper['executable']['path'],'-P','-S','-B',__file__,'--worker'],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=environment)
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError('official symtable worker did not start: '+self.process.stderr.read())
            ready = json.loads(line)
            self.profile = ready['profile']
            if not ready['probe']['builder'] or not ready['probe']['free']:
                self.close();raise ValueError('helper has no direct official flags entry')
        original = _profile()
        if (self.profile['version'] != original['version'] or self.profile['constants'] != original['constants']
                or self.profile['raw_members'] != original['raw_members']):
            self.close();raise ValueError('helper native public symbol schema/catalog differs')

    def capture(self, text, filename, mode='exec', *, flags=0, dont_inherit=True,
                inherited_flags=None, max_scopes=100_000, max_symbols=1_000_000):
        from scar.analysis.call_compilation import supported_future_flag_mask
        from scar.ir.program.source_symbols import SourceScope
        from scar.ir.record_codec import decode
        if type(text) is not str or type(filename) is not str or mode not in ('exec','eval','single'):
            raise ValueError('retained text/filename and executable parser mode required')
        if type(flags) is not int or flags < 0 or type(dont_inherit) is not bool:
            raise ValueError('explicit nonnegative integer flags and bool dont_inherit required')
        if not dont_inherit and inherited_flags is None:
            raise ValueError('dont_inherit=False requires explicitly supplied caller future flags')
        inherited = 0 if dont_inherit else inherited_flags
        if type(inherited) is not int or inherited < 0 or inherited & ~supported_future_flag_mask():
            raise ValueError('inherited_flags must contain only known caller future bits')
        if any(type(v) is not int or v < 0 for v in (max_scopes,max_symbols)):
            raise ValueError('raw-view budgets must be nonnegative exact integers')
        effective = flags | inherited
        request = dict(text=text,filename=filename,mode=mode,effective_flags=effective,
                       max_scopes=max_scopes,max_symbols=max_symbols)
        if self.native is not None:
            response = _capture(self.native,request)
        else:
            if self.process is None or self.process.poll() is not None:
                raise RuntimeError('official symtable worker is closed')
            self.process.stdin.write(json.dumps(request)+'\n');self.process.stdin.flush()
            response = json.loads(self.process.stdout.readline())
            if 'error' in response:
                raise SymbolContextError(response['error'])
        scopes = decode(tuple[SourceScope,...],response['scopes'])
        context = dict(text_utf8_sha256=_hash(text.encode('utf-8')),characters=len(text),filename=filename,
            mode=mode,requested_flags=flags,dont_inherit=dont_inherit,inherited_future_flags=inherited,
            effective_flags=effective,caller_flag_merging='EXPLICIT_ONLY_NO_PYTHON_CALLER_INHERITANCE')
        return SymbolContextCapture(scopes,context,self.profile,tuple(response['warnings']),self.parent)

    def close(self):
        if self.process is not None:
            self.process.stdin.close()
            self.process.wait(timeout=10)
            self.process.stdout.close();self.process.stderr.close()
            self.process = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _worker():
    sys.path.insert(0,str(ROOT))
    import _scar_symtable_context as native
    print(json.dumps(dict(profile=_profile(),probe=native.probe())),flush=True)
    for line in sys.stdin:
        try:
            response = _capture(native,json.loads(line))
        except Exception as error:
            response = dict(error=dict(type=type(error).__name__,message=str(error),
                filename=getattr(error,'filename',None),lineno=getattr(error,'lineno',None),
                offset=getattr(error,'offset',None),end_lineno=getattr(error,'end_lineno',None),
                end_offset=getattr(error,'end_offset',None),text=getattr(error,'text',None)))
        print(json.dumps(response),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',action='store_true')
    parser.add_argument('--directory',default=str(DEFAULT))
    parser.add_argument('--jobs',type=int,default=24)
    parser.add_argument('--worker',action='store_true')
    args = parser.parse_args()
    if args.worker:
        _worker()
    elif args.build:
        receipt = build_adapter(args.directory,jobs=args.jobs)
        print(json.dumps(dict(backend=receipt['backend'],native_probe=receipt['native_probe'])))
    else:
        with SymbolContextAdapter(args.directory) as adapter:
            print(json.dumps(dict(profile=adapter.profile,receipt=adapter.parent)))


if __name__ == '__main__':
    main()
