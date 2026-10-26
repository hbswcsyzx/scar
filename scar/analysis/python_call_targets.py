"""Normal bounded v2 target/entry reader over the same retained frame/operand scan."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from scar.analysis.call_operand_reader import CallOperandTrace
from scar.ir.program.python_call_targets import PythonCallTarget,PythonEntryBinding,PythonTargetGap,PythonTargetKind,PythonSourcePortBinding,PythonSourcePortIssue,ObservedPythonCallGraph,PythonSourcePortModel,read_target_record
from scar.ir.program.call_edges import CallRecordAnchor, CallTraceFile
from scar.ir.program.call_operands import CallableKind
from scar.ir.record_codec import decode,encode,loads as strict_loads



def read_python_call_targets(trace,*,max_bytes=32_000_000,max_rows=100_000):
    if type(trace) is not CallOperandTrace:raise TypeError('matching normal frame/operand trace required')
    if any(type(x) is not int or x<1 for x in (max_bytes,max_rows)):raise ValueError('positive independent reader ceilings required')
    root=Path(trace.directory);metas=sorted(root.glob('python-call-target-meta.*.json'))
    if not metas:raise ValueError('explicit v2 Python target capability missing')
    targets=[];entries=[];gaps=[];target_anchors=[];entry_anchors=[];total=rows=0;digests=[];processes=set()
    attempts={(a.process_id,a.index):a for a in trace.attempts}
    frames={e.invocation:e for e in trace.entries}
    descriptors={(c.process_id,c.code.key):c.code for c in trace.frame_scan.captures}
    for meta_path in metas:
        raw=meta_path.read_bytes()
        if len(raw)>1_000_000:raise ValueError('Python target metadata ceiling')
        meta=strict_loads(raw.decode('utf-8'))
        expected={'schema','schema_version','capabilities','process_id','project_root','scope_policy','budget','counts','stopped','file','legacy_inputs','receiver_is_separate_from_monitoring_arg0','contents_state_ready_or_complete_program_established'}
        if type(meta) is not dict or set(meta)!=expected:raise ValueError('closed Python target metadata contract required')
        if type(meta['schema_version']) is not int or type(meta['stopped']) is not bool or meta['receiver_is_separate_from_monitoring_arg0'] is not True or meta['contents_state_ready_or_complete_program_established'] is not False:raise ValueError('exact target transport types/scope declarations required')
        if type(meta['budget']) is not dict or set(meta['budget'])!={'max_records','max_bytes','max_selected_codes'} or any(type(v) is not int or v<1 for v in meta['budget'].values()):raise ValueError('closed positive target collection budgets required')
        if type(meta['counts']) is not dict or set(meta['counts'])!={'TARGET','ENTRY','GAP'} or any(type(v) is not int or v<0 for v in meta['counts'].values()):raise ValueError('closed exact target counters required')
        if (meta.get('schema'),meta.get('schema_version'),meta.get('capabilities'))!=('scar.python-call-target-collection',2,['PYTHON_CALL_TARGETS_V2','OBSERVED_PYTHON_CALLEE_SCOPE_V1']):raise ValueError('unsupported Python target capability')
        if meta['project_root']!=trace.project_root or meta['stopped']:raise ValueError('target scope changed or capture partial')
        process=meta['process_id']
        if type(process) is not int or process<1 or process in processes or meta_path.name!=f'python-call-target-meta.{process}.json':raise ValueError('target metadata process/filename conflict')
        processes.add(process)
        if meta['scope_policy']!='OBSERVED_EXACT_PYTHON_CALLEES_V1':raise ValueError('unknown observed Python scope policy')
        legacy=tuple(decode(CallTraceFile,item) for item in meta['legacy_inputs'])
        original=tuple(f for f in (*trace.frame_scan.files,*trace.files) if f.process_id==process)
        if len(legacy)!=5 or {f.family:f for f in legacy}!={f.family:f for f in original}:raise ValueError('target sidecar does not bind exact original frame and operand artifacts')
        legacy_meta=next((m for m in trace.metadata if m.process_id==process),None)
        if legacy_meta is None or legacy_meta.errors or legacy_meta.io_failed or legacy_meta.dropped_events or legacy_meta.previous_profile or any(i.process_id==process for i in trace.issues):raise ValueError('partial/interposed normal operand inputs cannot establish Python target entries')
        ref=meta['file'];path=Path(ref['path'])
        if any(type(ref[k]) is not int or ref[k]<0 for k in ('bytes','rows')):raise ValueError('exact target artifact byte/row counts required')
        if set(ref)!={'path','bytes','sha256','rows'} or path!=root/f'python-call-targets.{process}.jsonl' or path.is_symlink() or not path.is_file():raise ValueError('target file outside original trace scope')
        digest=hashlib.sha256();file_bytes=file_rows=0
        counts={'TARGET':0,'ENTRY':0,'GAP':0}
        with path.open('rb') as stream:
            while raw:=stream.readline(2_000_001):
                total+=len(raw);file_bytes+=len(raw);file_rows+=1;rows+=1
                if total>max_bytes or rows>max_rows or len(raw)>2_000_000:raise ValueError('target stream ceiling')
                if not raw.endswith(b'\n') or not raw.strip():raise ValueError('complete nonempty target JSONL records required')
                digest.update(raw);kind,value=read_target_record(strict_loads(raw.decode('utf-8')))
                counts[kind]+=1
                if kind!='GAP' and value.caller.process_id!=process:raise ValueError('target/entry belongs to another process')
                anchor=CallRecordAnchor(str(path),file_rows,hashlib.sha256(raw).hexdigest(),file_rows)
                if kind=='TARGET':targets.append(value);target_anchors.append(anchor)
                elif kind=='ENTRY':entries.append(value);entry_anchors.append(anchor)
                else:gaps.append(value)
        if (file_bytes,file_rows,digest.hexdigest())!=(ref['bytes'],ref['rows'],ref['sha256']):raise ValueError('target original EOF/SHA/rows differ')
        if counts!=meta['counts'] or file_rows>meta['budget']['max_records'] or file_bytes>meta['budget']['max_bytes']:raise ValueError('target kind counts or declared budgets differ')
        digests.append((str(meta_path),hashlib.sha256(meta_path.read_bytes()).hexdigest(),str(path),digest.hexdigest()))
    target_map={(t.caller.process_id,t.attempt_index):t for t in targets}
    if len(target_map)!=len(targets) or set(target_map)!=set(attempts):raise ValueError('complete original attempt denominator differs')
    for key,t in target_map.items():
        a=attempts[key]
        if a.invocation!=t.caller:raise ValueError('target caller differs from original attempt')
        if t.callable_reference!=a.dispatch.reference:raise ValueError('actual callable reference differs from original monitored CALL')
        if a.dispatch.kind is CallableKind.EXACT_FUNCTION and (t.code!=a.dispatch.code or t.layout!=a.dispatch.layout or t.function_reference!=a.dispatch.reference):raise ValueError('target contradicts original exact function/code/layout')
        descriptor=descriptors.get((t.caller.process_id,t.code))
        if descriptor is not None:
            filename=Path(descriptor.filename)
            expected_scope=('PROJECT' if filename.is_absolute() and filename.is_relative_to(Path(trace.project_root)) else 'OBSERVED_EXTERNAL_PYTHON' if filename.is_absolute() else 'NONFILESYSTEM_PYTHON')
            if t.scope.value!=expected_scope:raise ValueError('target code scope contradicts its original captured code filename')
    # Preserve the original exact-function ENTRY_HANDSHAKE authority. The
    # sidecar does not duplicate those rows or reinterpret their v1 wire.
    new_entry_keys={(e.caller.process_id,e.attempt_index) for e in entries}
    for handshake in trace.handshakes:
        key=handshake.process_id,handshake.attempt_index
        target=target_map[key]
        if key in new_entry_keys or target.kind is not PythonTargetKind.FUNCTION:continue
        entries.append(PythonEntryBinding(target.attempt_index,target.caller,handshake.invocation,
            handshake.entry_index,target.code,None,None))
        entry_anchors.append(handshake.anchor);new_entry_keys.add(key)
    seen=set()
    for e in entries:
        key=e.caller.process_id,e.attempt_index
        if key in seen or key not in target_map:raise ValueError('entry has no unique original target')
        seen.add(key);t=target_map[key];f=frames.get(e.callee)
        attempt=attempts[key]
        if (f is None or f.anchor.index!=e.entry_index or f.caller_invocation!=e.caller or f.code!=e.code or t.code!=e.code or len(f.path)!=1 or f.path[0]!=attempt.site or not attempt.frame_index<e.entry_index):raise ValueError('target/entry differs from real frame/code/caller/site')
        if bool(t.receiver)!=(e.receiver_parameter_index is not None):raise ValueError('receiver role lost between target and entry')
        if e.receiver_parameter_index is not None:
            if t.receiver is None or e.receiver_reference!=t.receiver.reference or not f.parameters_complete or not f.parameters:raise ValueError('receiver entry role differs from target/frame')
            # Weak tokens come from the recorder's shared issuer. Event-local
            # snapshots do not become cross-event identity proofs.
            if e.receiver_reference.startswith('weak:') and f.parameters[0].ref!=e.receiver_reference:raise ValueError('receiver weak identity contradicts first actual formal')
    combined=hashlib.sha256(json.dumps(digests,sort_keys=True).encode()).hexdigest()
    return ObservedPythonCallGraph(str(root),combined,tuple(targets),tuple(entries),tuple(gaps),tuple(target_anchors),tuple(entry_anchors))




def build_python_source_ports(*,trace,call_model,inventory,sources,inventory_artifact=None):
    """Bind current normal source/Use/formal ports without minting a core value.

    Partitioned bodies retain their original locator; unpartitioned normal
    inventories require their exact saved producer artifact, checked here.
    External entry capture does not waive the source reader's namespace guard.
    """
    import ast,dis,inspect
    from bisect import bisect_left
    from collections import defaultdict
    from scar.analysis.source_call_bindings import _Session,_Boundary,_need,Issue
    from scar.analysis.call_operand_routes import _Boundary as CoreBoundary,_has_index,_layout_matches,_span
    from scar.analysis.function_binding import bind_call
    from scar.ir.program.python_call_targets import PythonSourcePortBinding,PythonSourcePortIssue,SourceReceiverPort
    from scar.ir.program.source_call_bindings import SourceArgumentPort,SourceBodyNamespace
    from scar.ir.program.source_references import SourceArtifactLocator
    from scar.ir.program.providers import ProviderFactReference
    from scar.ir.program.call_edges import CallLinkStatus,CapturedSite
    from scar.ir.program.functions import CallArgument,ArgumentKind,ParameterBinding,BindingOrigin,ParameterKind,CallBindingStatus
    from scar.ir.program.model import TerminatorKind,UseRole,ReferenceValue,StateVersionValue
    from scar.trace.code_snapshot import site as code_site
    # A serialized target graph is a query product, never an authorization
    # token. This producer reads the original sidecar against the same normal
    # frame/operand scan; it does not rescan those raw streams or restore owners.
    observed=read_python_call_targets(trace)
    class Session(_Session):
        def namespace(self,definition):
            if self.sources.source_access is not None:return super().namespace(definition)
            if definition in self.namespaces:return self.namespaces[definition]
            _need(inventory_artifact is not None,Issue.BODY_NAMESPACE_UNAVAILABLE,'exact original saved inventory artifact required')
            for fi,file in enumerate(inventory.files):
                for bi,body in enumerate(file.bodies):
                    if body.definition!=definition:continue
                    graph_doc=inventory_document['files'][fi]['bodies'][bi]['graph']
                    locator=SourceArtifactLocator(inventory_artifact.artifact,inventory_artifact.decoded_sha256,
                        inventory_artifact.decoded_bytes,inventory_artifact.representation,
                        f'#/files/{fi}/bodies/{bi}/graph',inventory_artifact.declaration)
                    value=SourceBodyNamespace(locator,'scar.program-graph/'+str(graph_doc['schema_version']),
                        definition,self.sources.signatures[definition].source,body.metadata.entry,body.graph.root)
                    self.namespaces[definition]=value;return value
            raise _Boundary(Issue.BODY_NAMESPACE_UNAVAILABLE,'definition has no original inventory body')
    inventory_document=None
    if sources.source_access is None:
        if type(inventory_artifact) is not SourceArtifactLocator:raise TypeError('normal inventory requires its typed original artifact locator')
        inventory_artifact.__post_init__()
        if inventory_artifact.pointer!='#' or inventory_artifact.representation!='canonical-json' or inventory_artifact.artifact.schema!='scar.program-inventory':raise ValueError('unsupported normal inventory artifact contract')
        declaration=inventory_artifact.declaration
        if declaration is None or declaration.artifact.schema!='scar.python-call-source-catalog/1' or declaration.locator!='#/inventory':raise ValueError('normal inventory requires its actual catalog artifact declaration')
        declaration_path=Path(declaration.artifact.uri)
        if declaration_path.is_symlink() or not declaration_path.is_file() or declaration_path.stat().st_size>64_000:raise ValueError('bounded source catalog required')
        declaration_raw=declaration_path.read_bytes()
        if (len(declaration_raw),hashlib.sha256(declaration_raw).hexdigest())!=(declaration.artifact.size_bytes,declaration.artifact.sha256):raise ValueError('normal inventory catalog original receipt differs')
        catalog=strict_loads(declaration_raw.decode('utf-8'))
        if type(catalog) is not dict or set(catalog)!={'schema','schema_version','inventory'} or catalog['schema']!='scar.python-call-source-catalog' or type(catalog['schema_version']) is not int or catalog['schema_version']!=1 or catalog['inventory']!=encode(inventory_artifact.artifact):raise ValueError('catalog does not declare this exact original inventory artifact')
        path=Path(inventory_artifact.artifact.uri)
        if path.is_symlink() or not path.is_file() or path.stat().st_size>32_000_000:raise ValueError('bounded original normal inventory required')
        raw=path.read_bytes()
        if (len(raw),hashlib.sha256(raw).hexdigest())!=(inventory_artifact.decoded_bytes,inventory_artifact.decoded_sha256):raise ValueError('original normal inventory receipt differs')
        inventory_document=strict_loads(raw.decode('utf-8'))
        if inventory_document!=inventory.to_dict():raise ValueError('saved inventory differs from this normal source session')
    session=Session(call_model,trace,inventory,sources)
    attempts={(a.process_id,a.index):a for a in trace.attempts}
    entry_map={(e.caller.process_id,e.attempt_index):(e,a) for e,a in zip(observed.entries,observed.entry_anchors)}
    watermarks=defaultdict(list);operand_indices=defaultdict(list)
    for event in trace.events:
        watermarks[event.process_id].append(event.frame_index);operand_indices[event.process_id].append(event.index)
    bindings=[];issues=[]
    for target,target_anchor in zip(observed.targets,observed.target_anchors):
        try:
            attempt=attempts[target.caller.process_id,target.attempt_index]
            _need(target.code is not None,Issue.DISPATCH_BOUNDARY,'native/unclassified callable has no Python target')
            _need((target.caller.process_id,target.attempt_index) in entry_map,Issue.HANDSHAKE_BOUNDARY,'no exact retained Python entry')
            entry,entry_anchor=entry_map[target.caller.process_id,target.attempt_index]
            caller,callee=session.edges.get(target.caller),session.edges.get(entry.callee)
            _need(caller is not None and callee is not None and callee.caller_identity_verified
                and caller.target.status is callee.target.status is CallLinkStatus.VERIFIED
                and len(callee.path)==1 and callee.path[0].status is CallLinkStatus.VERIFIED
                and caller.target.definition in sources.core and callee.target.definition in sources.core
                and callee.target.definition in sources.ports,Issue.SOURCE_CORE_BOUNDARY,'normal caller/callee source/core ports unavailable')
            call=callee.path[0]
            _need(call.site==attempt.site and call.execution_owner==caller.target.definition
                and callee.entry.anchor.index==entry.entry_index and callee.entry.caller_invocation==target.caller,
                Issue.HANDSHAKE_BOUNDARY,'normal direct caller/site/entry differs')
            _need(target.code in sources.objects and attempt.site.code in sources.objects,
                Issue.CODE_WITNESS_UNAVAILABLE,'normal complete caller/callee CodeWitness unavailable')
            code,caller_code=sources.objects[target.code],sources.objects[attempt.site.code]
            layout=target.layout
            suspended=inspect.CO_GENERATOR|inspect.CO_COROUTINE|inspect.CO_ASYNC_GENERATOR
            _need(_layout_matches(layout,code) and not layout.flags&(suspended|inspect.CO_VARARGS|inspect.CO_VARKEYWORDS)
                and layout.kwonlyargcount==0 and not caller_code.co_flags&suspended,
                Issue.DISPATCH_BOUNDARY,'unsupported Python positional/suspended entry layout')
            _need(target.caller.process_id not in session.bad_processes,Issue.CAPTURE_GAP,'normal operand capture process incomplete')
            # Operand and target-sidecar indices are different domains. The
            # normal frame watermark locates the first operand row at entry.
            indices=operand_indices[target.caller.process_id]
            position=bisect_left(watermarks[target.caller.process_id],entry.entry_index)
            entry_operand_index=indices[position] if position<len(indices) else indices[-1]+1
            for table,key in ((session.global_gaps,target.caller.process_id),(session.local_gaps,target.caller),
                    (session.local_gaps,entry.callee),(session.read_issues,target.caller),(session.read_issues,entry.callee)):
                _need(not _has_index(table.get(key,()),attempt.index,entry_operand_index),Issue.CAPTURE_GAP,'call-to-entry capture gap')
            node=sources.node(call.source)
            _need(isinstance(node,ast.Call) and not node.keywords and not any(isinstance(a,ast.Starred) for a in node.args),Issue.DISPATCH_BOUNDARY,'only explicit positional AST arguments')
            offset=int(target.receiver is not None)
            _need(layout.argcount==len(node.args)+offset and callee.entry.parameters_complete
                and tuple(p.name for p in callee.entry.parameters)==layout.parameters,
                Issue.DISPATCH_BOUNDARY,'receiver/explicit argument/entry layout mismatch')
            if attempt.site.code not in session.instructions:
                session.instructions[attempt.site.code]={i.offset:i for i in dis.get_instructions(caller_code)}
            instruction=session.instructions[attempt.site.code].get(attempt.site.offset)
            _need(instruction is not None and instruction.opname=='CALL' and instruction.arg==len(node.args)
                and attempt.site.position==_span(node) and decode(CapturedSite,code_site(caller_code,attempt.site.offset))==attempt.site,
                Issue.CALL_INSTRUCTION_BOUNDARY,'normal CALL n/current source position mismatch')
            signature=sources.signatures[callee.target.definition]
            formals=session.core.formal_ports(callee.target.definition)
            _need(tuple(p.name for p in signature.parameters)==layout.parameters
                and all(p.kind in (ParameterKind.POSITIONAL,ParameterKind.POSITIONAL_ONLY) for p in signature.parameters)
                and not signature.decorators,Issue.SOURCE_CORE_BOUNDARY,'normal signature differs/has unexpanded decorators')
            body,operations,uses,_=sources.core[call.execution_owner];operation=operations[call.core_operation]
            _need(operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
                and len(operation.invoke_arguments)==len(node.args)+2 and operation.invoke_arguments[0]==call.callee_use
                and uses[call.callee_use].value==call.callee_value,Issue.SOURCE_CORE_BOUNDARY,'original callee/explicit actual/world partition differs')
            values=session.core.values(call.execution_owner);world=uses[operation.invoke_arguments[-1]]
            _need(world.role is UseRole.STATE_CONTENT and type(values[world.value]) is StateVersionValue
                and all(type(values[uses[u].value]) is ReferenceValue for u in operation.invoke_arguments[:-1]),Issue.SOURCE_CORE_BOUNDARY,'original reference/world roles differ')
            if call.execution_owner not in session.use_sources:
                grouped=defaultdict(list)
                for link in body.metadata.use_links:grouped[link.operation,link.use].append(link.source)
                session.use_sources[call.execution_owner]=grouped
            source_uses=session.use_sources[call.execution_owner]
            actuals=[]
            for index,arg in enumerate(node.args):
                use=operation.invoke_arguments[index+1];source=sources.source(call.source.path,arg)
                _need(source_uses[operation.id,use]==[source],Issue.SOURCE_CORE_BOUNDARY,'actual Use is not its unique source expression')
                actuals.append(CallArgument(index,source,ArgumentKind.POSITIONAL,use=use))
            caller_body,callee_body=session.namespace(caller.target.definition),session.namespace(callee.target.definition)
            receiver=None;candidate=None
            if offset:
                parameter,formal=signature.parameters[0],formals[0]
                receiver=SourceReceiverPort(caller_body,operation.id,call.callee_use,call.callee_value,
                    callee_body,parameter.slot,formal.value,parameter.name,target.receiver)
            else:
                candidate=bind_call(signature,call=call.call,target=signature.definition,source=call.source,arguments=tuple(actuals))
                _need(candidate.status is CallBindingStatus.CONDITIONAL and all(r.origin is BindingOrigin.ARGUMENT for r in candidate.routes),Issue.BINDING_INCOMPLETE,'original function binder did not cover explicit arguments')
            ports=tuple(SourceArgumentPort(index,caller_body,operation.id,actual.source,actual.use,uses[actual.use].value,
                callee_body,parameter.slot,formal.value,parameter.name,ParameterBinding(parameter.slot,BindingOrigin.ARGUMENT,(index,)))
                for index,(actual,parameter,formal) in enumerate(zip(actuals,signature.parameters[offset:],formals[offset:])))
            bindings.append(PythonSourcePortBinding(target,target_anchor,entry,entry_anchor,attempt.anchor,callee.entry.anchor,
                caller.target,callee.target,call,caller_body,callee_body,receiver,ports,candidate))
        except (_Boundary,CoreBoundary) as error:
            issues.append(PythonSourcePortIssue(target_anchor,target.attempt_index,error.detail))
    model=PythonSourcePortModel(observed,tuple(bindings),tuple(issues))
    if len(bindings)+len(issues)!=len(observed.targets):raise ValueError('full observed target denominator lost')
    return model
