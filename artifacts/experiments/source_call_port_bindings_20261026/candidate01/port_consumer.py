"""One same-session consumer; all actual endpoints come from normal linker IO."""
from collections import Counter
from dataclasses import replace
import gzip
import hashlib
import json
from pathlib import Path

from config import BUDGETS, EXPECTED_ATTEMPTS
from report_archive import receipt, write_json
from scar.ir.program.source_call_bindings import SourceCallPortModel
from scar.ir.program.call_edges import InvocationKey
from scar.ir.v2.ids import ValueSlotID
from scar.ir.record_codec import encode


def need(value, detail):
    if not value:
        raise ValueError('source-port gate: '+detail)


class PortConsumer:
    def __init__(self, directory):
        self.directory=Path(directory)
        self.calls=0
        self.model=None
        self.checks=[]
        self.artifact=None

    def __call__(self, model, check_binding):
        self.calls+=1
        need(self.calls == 1 and type(model) is SourceCallPortModel and callable(check_binding),
             'consumer must run once inside the owned normal linker')
        need(model.attempt_count == EXPECTED_ATTEMPTS, 'complete original attempt denominator differs')
        self.model=model
        chosen=next((b for b in model.bindings if b.ports),None)
        need(chosen is not None, 'no real nonzero-argument binding was produced')
        need(check_binding(chosen) == chosen, 'normal same-session binding check differs')
        self.checks.append('real_nonzero_binding_recomputed_from_same_source_code_entry_ports')
        source=replace(chosen.call.source,end_column=chosen.call.source.end_column+1)
        changed_call=replace(chosen.call,source=source)
        changed_candidate=replace(chosen.candidate,source=source)
        negatives=[('call_source',replace(chosen,call=changed_call,candidate=changed_candidate))]
        port=chosen.ports[0]
        wrong_slot=ValueSlotID('negative-not-an-original-formal')
        route=replace(port.parameter,slot=wrong_slot)
        routes=tuple(route if r.slot==port.formal_slot else r for r in chosen.candidate.routes)
        candidate=replace(chosen.candidate,routes=routes)
        ports=(replace(port,formal_slot=wrong_slot,parameter=route),)+chosen.ports[1:]
        negatives.append(('formal_slot',replace(chosen,candidate=candidate,ports=ports)))
        caller=InvocationKey(chosen.caller.process_id,chosen.caller.thread_id,chosen.caller.invocation_id+1_000_000)
        negatives.append(('caller',replace(chosen,caller=caller)))
        last=chosen.ports[-1]
        candidate=replace(chosen.candidate,arguments=chosen.candidate.arguments[:-1],
            routes=tuple(r for r in chosen.candidate.routes if r.slot!=last.formal_slot))
        negatives.append(('arity',replace(chosen,candidate=candidate,ports=chosen.ports[:-1])))
        rejected=[]
        for name,record in negatives:
            try:
                check_binding(record)
            except ValueError as error:
                rejected.append({'case':name,'type':type(error).__name__,'detail':str(error),
                    'method':'normal same-session source/code/entry/ports recomputation, not a hash comparison'})
            else:
                raise ValueError('accepted changed '+name+' binding')
        self.checks.extend('real_'+n['case']+'_rejected_by_session_recomputation' for n in rejected)
        self.directory.mkdir(exist_ok=False)
        document=model.to_dict()
        payload=json.dumps(document,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        need(len(payload)<=BUDGETS['source_port_decoded_bytes'],'new model decoded output exceeds 512MB')
        path=self.directory/'model.json.gz'
        with path.open('xb') as raw:
            with gzip.GzipFile(fileobj=raw,mode='wb',filename='',mtime=0) as stream:
                stream.write(payload)
        need(path.stat().st_size<=BUDGETS['source_port_stored_bytes'],'new model stored output exceeds 128MB')
        self.artifact={**receipt(path),'decoded_bytes':len(payload),
            'decoded_sha256':hashlib.sha256(payload).hexdigest(),'schema':'scar.source-call-port-bindings/1'}
        del document,payload
        with gzip.open(path,'rb') as stream:
            raw=stream.read(BUDGETS['source_port_decoded_bytes']+1)
        need(len(raw)==self.artifact['decoded_bytes'] and hashlib.sha256(raw).hexdigest()==self.artifact['decoded_sha256'],
             'normal new model EOF/decoded receipt differs')
        need(receipt(path)=={k:self.artifact[k] for k in ('path','sha256','bytes')},'new model stored receipt changed during normal read')
        decoded=SourceCallPortModel.loads(raw.decode('utf-8'))
        need(decoded==model,'new model strict normal reader roundtrip differs')
        del raw,decoded
        self.checks.append('normal_full_model_strict_reader_roundtrip')
        write_json(self.directory/'manifest.json',{'schema':'scar.source-call-port-gate-artifact/1',
            'model':self.artifact,'summary':model.summary(),'consumer_calls':self.calls,
            'same_fresh_owned_session':True,'selected_binding':encode(chosen),'negative_checks':rejected,
            'runtime_value_identity_proved':False,'state_contents_ready_proved':False,
            'old_argument_route_semantics_changed':False,'whole_program_complete':False})

    def compare_legacy(self,routing):
        need(self.calls==1 and self.model is not None,'same-session consumer did not complete')
        old={route.attempt for route in routing.arguments}
        new={binding.attempt:binding for binding in self.model.bindings}
        issues={issue.attempt:issue for issue in self.model.issues}
        need(len(old)==27,'legacy narrow reference-route call group count differs from original 27')
        shared=old & new.keys()
        missing=[{'attempt':encode(anchor),'issue':encode(issues[anchor])} for anchor in sorted(old-new.keys(),key=lambda a:(a.path,a.index))]
        need(shared,'all original 27 supported source call groups were lost')
        result={'status':'CONDITIONAL_SOURCE_PORTS_WITH_OPEN_RUNTIME_IDENTITY',
            'summary':self.model.summary(),'legacy_reference_route_groups':len(old),
            'legacy_groups_with_source_ports':len(shared),'legacy_groups_missing_source_ports':len(missing),
            'legacy_missing_reasons':missing,'new_groups_outside_legacy_reference_rule':len(new.keys()-old),
            'new_issue_detail_counts':dict(Counter(i.kind.value+': '+i.detail for i in self.model.issues)),
            'checks':self.checks,'artifact':self.artifact,'new_reference_identity_or_contents_proof':False,
            'coverage_of_all_2656_old_name_restrictions_claimed':False,'whole_program_complete':False}
        return result
