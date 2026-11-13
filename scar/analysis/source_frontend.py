"""Run the existing formal source layers in dependency order, without execution.

Each layer owns its original typed shards and receipts. This driver only
records their order and admission; a completed local frontend is not proof
of runtime dispatch, resource placement or whole-program graph closure.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from scar.analysis.source_stage import _durable_bytes, _durable_mkdir


_LAYERS = (
    ('source-bytes', 'scar.source-material-gate'),
    ('source-tokens', 'scar.source-token-gate'),
    ('source-syntax', 'scar.source-syntax-gate'),
    ('source-symbols', 'scar.source-symbol-gate'),
    ('source-roles', 'scar.source-role-gate'),
    ('source-contexts', 'scar.source-context-gate'),
    ('source-declarations', 'scar.source-declaration-gate'),
    ('source-bindings', 'scar.source-binding-gate'),
    ('compiler-topology', 'scar.compiler-topology-gate'),
    ('compiler-symbols', 'scar.compiler-symbol-gate'),
)
_DOMAINS = ('expressions', 'statements', 'roots')


def _receipt(path):
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=sha256(raw).hexdigest())


class _Run:
    def __init__(self, out):
        self.out = out
        self.rows = []
        self.lock = threading.Lock()
        self.env = {**os.environ, 'PYTHONHASHSEED': '0'}

    def _progress(self):
        raw = json.dumps(dict(schema='scar.source-frontend-progress', schema_version=1,
            stages=self.rows), indent=2).encode()+b'\n'
        _durable_bytes(self.out/'progress.json', raw, replace=True)

    def stage(self, name, module, arguments, report, schema, **required):
        command = [sys.executable, '-B', '-m', module, *map(str, arguments)]
        log = self.out/(name+'.log')
        row = dict(stage=name, status='RUNNING', command=command, log=str(log))
        started = time.monotonic()
        with self.lock:
            self.rows.append(row)
            self._progress()
        error = None
        outcome = {}
        try:
            with log.open('wb') as stream:
                process = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                    env=self.env, check=False)
            outcome['returncode'] = process.returncode
            if process.returncode:
                raise RuntimeError(f'{name} exited {process.returncode}; see {log}')
            value = json.loads(report.read_bytes())
            if value.get('schema') != schema or any(value.get(k) != v for k,v in required.items()):
                raise ValueError(f'{name} did not publish its required original layer contract')
            outcome.update(status='ADMITTED', report=_receipt(report))
        except Exception as caught:
            error = caught
            outcome.update(status='FAILED', error_type=type(caught).__name__, error=str(caught))
        finally:
            with self.lock:
                row.update(outcome, seconds=time.monotonic()-started)
                self._progress()
                print(json.dumps({k:row[k] for k in ('stage','status','seconds')}), flush=True)
        if error is not None:
            raise error
        return value


def build_frontend(paths, out, *, sources=(), jobs=4, trace=None, project_root=None):
    """Build complete local declarations for the selected source corpus."""
    paths = tuple(dict.fromkeys(Path(p).resolve() for p in paths))
    sources = tuple(dict.fromkeys(Path(p).resolve() for p in sources))
    out = Path(out).absolute()
    if (trace is None) != (project_root is None):
        raise ValueError('trace and project_root must be supplied together')
    trace = None if trace is None else Path(trace).resolve()
    project_root = None if project_root is None else Path(project_root).resolve()
    if (not paths or any(not p.is_dir() for p in paths)
            or type(jobs) is not int or not 1 <= jobs <= 32):
        raise ValueError('frontend requires source directories and jobs in [1, 32]')
    if out.resolve() != out or out.exists() or any(p.is_relative_to(out) for p in paths):
        raise ValueError('frontend needs fresh canonical output outside its source ancestors')
    _durable_mkdir(out)
    run = _Run(out)
    model = out/'source'
    started = time.monotonic()
    report = dict(schema='scar.source-frontend', schema_version=1, source_roots=list(map(str,paths)),
        selected_sources=list(map(str,sources)), jobs=jobs, compiler_hash_seed='0',
        trace=None if trace is None else str(trace),
        project_root=None if project_root is None else str(project_root),
        workflow_complete=False, local_declarations_complete=False, first_stage_complete=False,
        target_executed=False, global_namespace_resolved=False, runtime_dispatch_proven=False)
    try:
        extra_roots = [part for p in paths[1:] for part in ('--source-root',p)]
        run.stage('source', 'scar.cli', ['static',paths[0],*extra_roots,'--out',model,
            '--phase','sources','--jobs',jobs], model/'manifest.json', 'scar.static-program',
            phase='sources', source_catalog_status='COMPLETE', worker_errors=[], source_changed=[])
        for command, schema in _LAYERS:
            run.stage(command, 'scar.cli', [command,'--model',model,'--out',out/command,
                '--jobs',jobs], out/command/'result.json', schema, complete_for_declared_units=True)

        selection = [part for p in sources for part in ('--source',p)]
        active = min(jobs, len(_DOMAINS))
        # Independent domains share this worker budget. Each domain finishes
        # collection before its required independent replay; dependent stages
        # never race mutations of the source model.
        allocations = [jobs//active+(i < jobs%active) for i in range(active)]

        def domain_task(domain, workers):
            singular = domain[:-1] if domain != 'roots' else 'root'
            schema = 'scar.source-'+singular+'-materials'
            common = ['source-'+domain,'--model',model,*selection,'--jobs',workers]
            run.stage(domain, 'scar.cli', [*common,'--out',out/domain],
                out/domain/'result.json', schema, status='LOCAL_RULES_VERIFIED', mode='COLLECTION')
            run.stage(domain+'-verified', 'scar.cli', [*common,'--out',out/(domain+'-verified'),
                '--materials',out/domain], out/(domain+'-verified')/'result.json', schema,
                status='LOCAL_RULES_VERIFIED', mode='FRESH_VERIFICATION')

        if active == 1:
            for domain in _DOMAINS:
                domain_task(domain, jobs)
        else:
            # At most active children execute at once. With two slots their
            # allocations are equal; with three there are exactly three tasks.
            with ThreadPoolExecutor(max_workers=active) as pool:
                futures = [pool.submit(domain_task,domain,allocations[i%active])
                    for i,domain in enumerate(_DOMAINS)]
                errors = []
                for future in as_completed(futures):
                    try: future.result()
                    except Exception as error: errors.append(error)
                if errors: raise errors[0]

        parents = [part for domain in _DOMAINS for part in
            ('--materials',domain,out/domain,out/(domain+'-verified'))]
        run.stage('templates', 'scar.analysis.source_template_links',
            ['--model',model,'--out',out/'templates',*parents,*selection,'--jobs',jobs],
            out/'templates/result.json','scar.source-template-link-store', status='SOURCE_INTERFACES_LINKED')
        run.stage('facts','scar.analysis.normal_links',
            ['--model',model,'--templates',out/'templates','--out',out/'facts',*selection,'--jobs',jobs],
            out/'facts/result.json','scar.normal-source-link-facts', status='SOURCE_LINK_FACTS_EXTRACTED')
        run.stage('interfaces','scar.analysis.source_interface_build',
            ['--facts',out/'facts','--out',out/'interfaces','--jobs',jobs],
            out/'interfaces/result.json','scar.local-source-interfaces',
            status='LOCAL_INTERFACES_PROJECTED', catalog_complete=True)
        run.stage('catalog','scar.analysis.source_declared_catalog',
            ['--facts',out/'facts','--interfaces',out/'interfaces','--out',out/'catalog'],
            out/'catalog/result.json','scar.declared-source-catalog', first_stage_complete=False,
            target_executed=False, global_namespace_resolved=False, runtime_dispatch_proven=False)
        active_catalog = out/'catalog'
        if trace is not None and (any(trace.glob('compilation-meta.*.json'))
                or any(trace.glob('compilation-disabled.*.json'))):
            run.stage('compilation-matches', 'scar.analysis.compilation_audit',
                ['--trace',trace,'--out',out/'compilation-matches'],
                out/'compilation-matches/result.json','scar.observed-compilation-matches',
                target_executed=False, original_compile_options_proven=False,
                execution_namespace_proven=False, first_stage_complete=False)
            run.stage('observed-source-catalog', 'scar.analysis.observed_source_catalog',
                ['--base',active_catalog,'--trace',trace,'--matches',out/'compilation-matches',
                    '--project-root',project_root,'--out',out/'observed-source-catalog'],
                out/'observed-source-catalog/result.json','scar.observed-source-catalog',
                target_executed=False, original_compile_options_proven=False,
                execution_namespace_proven=False, first_stage_complete=False)
            active_catalog = out/'observed-source-catalog'
        call_roots = [part for p in paths for part in ('--source-root',p)]
        run.stage('calls','scar.analysis.source_declared_calls',
            ['--catalog',active_catalog,*call_roots,'--out',out/'calls','--jobs',jobs],
            out/'calls/result.json','scar.source-declared-calls',
            status='ALL_SELECTED_SOURCE_CALL_DECLARATIONS_PROJECTED',
            first_stage_complete=False,target_executed=False,runtime_dispatch_proven=False)
        run.stage('function-interfaces','scar.analysis.source_function_interfaces',
            ['--calls',out/'calls','--out',out/'function-interfaces','--jobs',jobs],
            out/'function-interfaces/result.json','scar.source-function-interfaces',
            **{name:False for name in ('source_scopes_activated','caller_contexts_selected',
                'runtime_dispatch_proven','current_function_environment_versions_proven',
                'effects_proven','source_relations_rederived','namespace_semantics_rederived',
                'loops_unrolled','target_executed','first_stage_complete')})
        if trace is not None:
            run.stage('observed-function-interfaces','scar.analysis.source_observed_interfaces',
                ['--parent',out/'function-interfaces','--trace',trace,'--project-root',project_root,
                    '--out',out/'observed-function-interfaces','--boundaries-out',out/'observed-boundaries'],
                out/'observed-function-interfaces/result.json','scar.source-observed-function-interfaces',
                first_stage_complete=False,source_bodies_copied=False,loops_unrolled=False,
                future_dispatch_proven=False,creator_instances_proven=False,cell_contents_proven=False)
            report['observed_function_interfaces'] = _receipt(out/'observed-function-interfaces/result.json')
            boundary=json.loads((out/'observed-boundaries/result.json').read_bytes())
            if (boundary['schema']!='scar.source-observed-boundaries'
                    or boundary['first_stage_complete'] is not False
                    or boundary['target_executed'] is not False):
                raise ValueError('observed boundary publication contract differs')
            report['observed_boundaries'] = _receipt(out/'observed-boundaries/result.json')
        report.update(workflow_complete=True, local_declarations_complete=True,
            model=_receipt(model/'manifest.json'), catalog=_receipt(active_catalog/'result.json'),
            calls=_receipt(out/'calls/result.json'),
            function_interfaces=_receipt(out/'function-interfaces/result.json'))
    except Exception as error:
        report.update(error_type=type(error).__name__, error=str(error))
    report.update(seconds=time.monotonic()-started, stages=len(run.rows),
        admitted_stages=sum(row['status']=='ADMITTED' for row in run.rows),
        progress=_receipt(out/'progress.json'))
    _durable_bytes(out/'result.json', json.dumps(report,indent=2).encode()+b'\n', replace=False)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scar frontend', description=__doc__)
    parser.add_argument('paths', nargs='+', metavar='PATH', help='source directories; never imported or executed')
    parser.add_argument('--out', required=True, help='fresh output directory')
    parser.add_argument('--jobs', type=int, default=4, help='total lowering worker budget, 1..32')
    parser.add_argument('--source', action='append', default=[], help='exact file selected for F4; earlier source layers retain the corpus')
    parser.add_argument('--trace', help='existing trace to join after local call interfaces; no target execution')
    parser.add_argument('--project-root', help='original trace namespace root; required with --trace')
    args = parser.parse_args(argv)
    if (args.trace is None) != (args.project_root is None):
        parser.error('--trace and --project-root must be supplied together')
    report = build_frontend(args.paths,args.out,sources=args.source,jobs=args.jobs,
        trace=args.trace,project_root=args.project_root)
    print(json.dumps(report,indent=2),flush=True)
    return 0 if report['workflow_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
