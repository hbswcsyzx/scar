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


def _reuse_source_model(run, model, roots, sources):
    """Admit existing F0--F3 inputs, leaving prerequisite replay to F4.

    The receipt covers the original manifest and selected current source
    bytes. It does not recertify the earlier stages for the entire corpus.
    No source artifact, identity or parent receipt is copied or rewritten.
    """
    model = Path(model).absolute()
    row = dict(stage='source-model', status='RUNNING', model=str(model))
    started = time.monotonic()
    with run.lock:
        run.rows.append(row); run._progress()
    try:
        if (model.resolve() != model or not model.is_dir() or model.is_symlink()
                or model.is_relative_to(run.out) or run.out.is_relative_to(model)):
            raise ValueError('source-model requires an existing canonical directory independent of output')
        manifest = model/'manifest.json'
        if manifest.is_symlink() or not manifest.is_file():
            raise ValueError('source-model manifest must be an original regular file')
        original = manifest.read_bytes(); document = json.loads(original)
        if (document.get('schema') != 'scar.static-program'
                or type(document.get('schema_version')) is not int or document['schema_version'] != 1
                or document.get('phase') != 'sources' or document.get('source_catalog_status') != 'COMPLETE'
                or document.get('worker_errors') != [] or document.get('source_changed') != []):
            raise ValueError('source-model requires a completed source manifest without worker errors or changed sources')
        units = document.get('units')
        if type(units) is not list or not units:
            raise ValueError('source-model requires its original nonempty source unit directory')
        by_path = {}
        for unit in units:
            if type(unit) is not dict or type(unit.get('path')) is not str or not Path(unit['path']).is_absolute():
                raise ValueError('source-model unit lacks its original absolute source path')
            by_path.setdefault(unit['path'], []).append(unit)
        selected = tuple(sources) or tuple(Path(path) for path in by_path)
        receipts = []
        for source in selected:
            candidates = by_path.get(str(source))
            if not candidates or not any(source.is_relative_to(root) for root in roots):
                raise ValueError('selected source is outside the source-model units or supplied roots: '+str(source))
            if source.resolve() != source or source.is_symlink() or not source.is_file():
                raise ValueError('selected source must retain its original canonical regular file: '+str(source))
            before = source.stat(); raw = source.read_bytes(); after = source.stat()
            stamp = lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
            digest = sha256(raw).hexdigest()
            if (stamp(before) != stamp(after) or len(raw) != before.st_size
                    or any(unit.get('raw_sha256') != digest or unit.get('source_bytes') != len(raw)
                        for unit in candidates)):
                raise ValueError('selected current source bytes differ from the source-model manifest: '+str(source))
            receipts.append(dict(path=str(source),bytes=len(raw),sha256=digest,
                units=[unit['key'] for unit in candidates]))
        if manifest.read_bytes() != original:
            raise ValueError('source-model manifest changed during input admission')
        receipt = dict(schema='scar.source-frontend-input',schema_version=1,
            model=str(model),manifest=dict(path=str(manifest),bytes=len(original),sha256=sha256(original).hexdigest()),
            selected_sources=receipts,reused_layers=['source',*(name for name,_ in _LAYERS)],
            scope='ORIGINAL_F0_F3_INPUTS_WITH_SELECTED_SOURCE_IDENTITY_AND_CURRENT_BYTES_CHECKED',
            whole_f0_f3_corpus_revalidated=False,f4_prerequisite_replay_required=True,
            source_ids_rewritten=False,target_executed=False)
        _durable_bytes(run.out/'source-input.json',json.dumps(receipt,indent=2).encode()+b'\n',replace=False)
        row.update(status='REUSED_INPUT',report=_receipt(run.out/'source-input.json'))
    except Exception as error:
        row.update(status='FAILED',error_type=type(error).__name__,error=str(error))
        raise
    finally:
        with run.lock:
            row['seconds'] = time.monotonic()-started; run._progress()
            print(json.dumps({key:row[key] for key in ('stage','status','seconds')}),flush=True)
    return model, original


def admit_external_sources(run, catalog, trace, project_root, jobs):
    """Finish bounded admission batches before projecting global call links.

    Each extension keeps the original leaves. A later batch discovers only
    codes not represented by that catalog; it neither reruns the target nor
    raises the per-batch source/compile/byte budgets. Progress must strictly
    reduce unresolved captured codes, bounding the number of batches.
    """
    catalog=Path(catalog);batches=[];previous=None;limit=None
    while True:
        suffix='' if not batches else '-'+str(len(batches)+1)
        find='external-source-matches'+suffix
        material='external-source-materials'+suffix
        publish='complete-source-catalog'+suffix
        found=run.stage(find,'scar.analysis.observed_source_admission',
            ['discover','--catalog',catalog,'--trace',trace,'--project-root',project_root,
                '--out',run.out/find],run.out/find/'result.json',
            'scar.observed-external-source-matches',target_executed=False,
            original_compile_options_proven=False,historical_source_version_proven=False,
            first_stage_complete=False)
        requested=found['counts']['requested']
        if limit is None:limit=found['counts']['captures']+1
        if (previous is not None and requested>=previous) or len(batches)>=limit:
            raise RuntimeError('external source admission made no progress; unresolved reasons remain in '+find)
        row=dict(discovery=_receipt(run.out/find/'result.json'),
            requested=requested,matched=found['counts']['matched_captures'],
            search_complete=found['search_complete'])
        if not found['matches']:
            batches.append(row)
            if not found['search_complete']:
                raise RuntimeError('external source admission exhausted its budget without new material; see '+find)
            return catalog,batches
        run.stage(material,'scar.analysis.external_source_materials',
            ['--matches',run.out/find,'--out',run.out/material,'--jobs',min(jobs,8)],
            run.out/material/'result.json','scar.external-source-materials',
            status='EXTERNAL_SOURCE_MATERIALS_BUILT',target_executed=False,first_stage_complete=False)
        run.stage(publish,'scar.analysis.observed_source_admission',
            ['extend','--catalog',catalog,'--materials',run.out/material,'--out',run.out/publish],
            run.out/publish/'result.json','scar.observed-source-catalog',
            target_executed=False,first_stage_complete=False)
        catalog=run.out/publish
        row.update(materials=_receipt(run.out/material/'result.json'),
            catalog=_receipt(catalog/'result.json'))
        batches.append(row)
        if found['search_complete']:return catalog,batches
        previous=requested


def build_frontend(paths, out, *, sources=(), jobs=4, trace=None, project_root=None, source_model=None):
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
        from scar.analysis.source_connection_domains import connection_domains
        from scar.analysis.source_connection_contracts import connection_reference_catalog
        if not connection_domains()['type_domains_closed']:
            raise ValueError('connection input classification domains are not closed')
        connection_reference_catalog()
        if source_model is None:
            extra_roots = [part for p in paths[1:] for part in ('--source-root',p)]
            run.stage('source', 'scar.cli', ['static',paths[0],*extra_roots,'--out',model,
                '--phase','sources','--jobs',jobs], model/'manifest.json', 'scar.static-program',
                phase='sources', source_catalog_status='COMPLETE', worker_errors=[], source_changed=[])
            for command, schema in _LAYERS:
                run.stage(command, 'scar.cli', [command,'--model',model,'--out',out/command,
                    '--jobs',jobs], out/command/'result.json', schema, complete_for_declared_units=True)
        else:
            model, source_manifest = _reuse_source_model(run,source_model,paths,sources)
            report['source_input'] = _receipt(out/'source-input.json')

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

        # Independent typed-reference rules supply the denominator. In
        # particular this does not ask the edge producer what it emitted.
        run.stage('connection-contract', 'scar.analysis.source_connection_contracts',
            [*[part for domain in _DOMAINS for part in ('--materials',out/domain)],
                '--out',out/'connection-contract.json'],
            out/'connection-contract.json','scar.source-connection-gate',
            local_connection_schema_complete=True,local_entry_relations_complete=True,
            input_type_domains_closed=True,runtime_connections_checked=False,first_stage_complete=False)
        report['connection_contract'] = _receipt(out/'connection-contract.json')

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
        if trace is not None:
            active_catalog,report['external_admission_batches']=admit_external_sources(
                run,active_catalog,trace,project_root,jobs)
        run.stage('body-interfaces','scar.analysis.source_body_interfaces',
            ['--catalog',active_catalog,'--out',out/'body-interfaces','--jobs',jobs],
            out/'body-interfaces/result.json','scar.source-body-interfaces',
            source_bodies_copied=False,runtime_bindings_proven=False,first_stage_complete=False)
        run.stage('body-interfaces-verified','scar.analysis.source_body_interfaces',
            ['--read',out/'body-interfaces','--out',out/'body-interfaces-verified.json'],
            out/'body-interfaces-verified.json','scar.source-body-interfaces.readback',status='VERIFIED')
        report['body_interfaces'] = _receipt(out/'body-interfaces/result.json')
        report['body_interfaces_verified'] = _receipt(out/'body-interfaces-verified.json')
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
                    '--out',out/'observed-function-interfaces','--boundaries-out',out/'observed-boundaries',
                    '--activations-out',out/'body-activations',
                    '--graph-check-out',out/'body-activations-verified.json'],
                out/'observed-function-interfaces/result.json','scar.source-observed-function-interfaces',
                first_stage_complete=False,source_bodies_copied=False,loops_unrolled=False,
                future_dispatch_proven=False,creator_instances_proven=False,cell_contents_proven=False)
            report['observed_function_interfaces'] = _receipt(out/'observed-function-interfaces/result.json')
            report['body_activations'] = _receipt(out/'body-activations/result.json')
            graph_check=json.loads((out/'body-activations-verified.json').read_bytes())
            if (graph_check['schema']!='scar.source-body-activations.graph-check'
                    or graph_check['status']!='STRUCTURE_VERIFIED'
                    or graph_check['first_stage_complete'] is not False):
                raise ValueError('body graph readback is incomplete')
            report['body_activations_verified'] = _receipt(out/'body-activations-verified.json')
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
        if source_model is not None and (model/'manifest.json').read_bytes() != source_manifest:
            report.update(workflow_complete=False,local_declarations_complete=False)
            raise ValueError('reused source-model manifest changed during frontend execution')
    except Exception as error:
        report.update(error_type=type(error).__name__, error=str(error))
    report.update(seconds=time.monotonic()-started, stages=len(run.rows),
        admitted_stages=sum(row['status']=='ADMITTED' for row in run.rows),
        progress=_receipt(out/'progress.json'))
    if source_model is not None:
        report['reused_input_stages'] = sum(row['status']=='REUSED_INPUT' for row in run.rows)
    _durable_bytes(out/'result.json', json.dumps(report,indent=2).encode()+b'\n', replace=False)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scar frontend', description=__doc__)
    parser.add_argument('paths', nargs='+', metavar='PATH', help='source directories; never imported or executed')
    parser.add_argument('--out', required=True, help='fresh output directory')
    parser.add_argument('--jobs', type=int, default=4, help='total lowering worker budget, 1..32')
    parser.add_argument('--source', action='append', default=[], help='exact file selected for F4; earlier source layers retain the corpus')
    parser.add_argument('--source-model', help='reuse an existing F0--F3 source model; current F4 collection and fresh verification still run')
    parser.add_argument('--trace', help='existing trace to join after local call interfaces; no target execution')
    parser.add_argument('--project-root', help='original trace namespace root; required with --trace')
    args = parser.parse_args(argv)
    if (args.trace is None) != (args.project_root is None):
        parser.error('--trace and --project-root must be supplied together')
    report = build_frontend(args.paths,args.out,sources=args.source,jobs=args.jobs,
        trace=args.trace,project_root=args.project_root,source_model=args.source_model)
    print(json.dumps(report,indent=2),flush=True)
    return 0 if report['workflow_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
