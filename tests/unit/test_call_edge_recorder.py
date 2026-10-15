"""Real profile callbacks without Tensor materialization or application retention."""
import gc
import json
from pathlib import Path
import sys
import threading
import weakref

import pytest

from scar.trace.call_edges import CallEdgeRecorder


def execute(tmp_path, text, *, values=None, **limits):
    project = tmp_path/'project'
    project.mkdir(exist_ok=True)
    source = project/'entry.py'
    source.write_text(text)
    recorder = CallEdgeRecorder(tmp_path/'trace',project,**limits)
    before = sys.getprofile()
    namespace = dict(values or {})
    try:
        sys.setprofile(recorder.profile)
        exec(compile(text,str(source),'exec',dont_inherit=True),namespace)
    finally:
        sys.setprofile(before)
        recorder.close()
    events = [json.loads(line) for line in recorder.event_path.read_text().splitlines()]
    codes = {row['key']:row for row in map(json.loads,recorder.code_path.read_text().splitlines())}
    return recorder,events,codes,namespace


def entries(events,codes,name):
    return [event for event in events if event['kind']=='call_enter'
            and codes[event['code']]['qualname']==name]


def test_same_line_calls_have_distinct_offsets_and_invocations(tmp_path):
    _,events,codes,_ = execute(tmp_path,'def leaf(x): return x\ndef run(x):\n a=leaf(x); b=leaf(x)\n return a\nrun(value)\n',values={'value':object()})
    calls = entries(events,codes,'leaf')
    assert len(calls)==2
    assert len({c['caller']['offset'] for c in calls})==2
    assert len({tuple(c['caller']['position']) for c in calls})==2
    assert len({c['invocation_id'] for c in calls})==2
    assert all(c['caller_invocation_id']==c['ancestor_invocation_id'] for c in calls)
    assert all(c['path']==[c['caller']] for c in calls)


def test_normal_none_is_distinct_from_exception_unwind(tmp_path):
    _,events,codes,_ = execute(tmp_path,'def good(): return None\ndef bad(): raise ValueError()\ngood()\ntry: bad()\nexcept ValueError: pass\n')
    completed = {codes[e['code']]['qualname']:e for e in events if e['kind']=='call_exit'}
    assert completed['good']['completion']=='NORMAL'
    assert completed['bad']['completion']=='UNKNOWN'


def test_binding_failure_has_no_callee_body_entry(tmp_path):
    _,events,codes,_ = execute(tmp_path,'def need(x): return x\ntry: need()\nexcept TypeError: pass\n')
    assert not entries(events,codes,'need')


def test_recursion_is_paired_per_invocation(tmp_path):
    _,events,codes,_ = execute(tmp_path,'def descend(n):\n if n: return descend(n-1)\n return None\ndescend(4)\n')
    calls=entries(events,codes,'descend')
    assert len(calls)==5
    exits={e['invocation_id']:e for e in events if e['kind']=='call_exit'}
    assert all(exits[e['invocation_id']]['code']==e['code'] for e in calls)
    for previous,current in zip(calls,calls[1:]):
        assert current['caller_invocation_id']==previous['invocation_id']


def test_duplicate_parameters_preserve_ports_and_weak_identity(tmp_path):
    class Value: pass
    value=Value()
    recorder,events,codes,_ = execute(tmp_path,'def keep(a,b): return a\nkeep(value,value)\n',values={'value':value})
    call,=entries(events,codes,'keep')
    assert [p['name'] for p in call['parameters']]==['a','b']
    assert call['parameters'][0]['ref']==call['parameters'][1]['ref']
    assert call['parameters'][0]['ref'].startswith('weak:')
    end=next(e for e in events if e['kind']=='call_exit' and e['invocation_id']==call['invocation_id'])
    assert end['return_ref']==call['parameters'][0]['ref']
    assert recorder.references[id(value)][0]() is value


def test_nonweak_references_are_snapshot_scoped(tmp_path):
    _,events,codes,_ = execute(tmp_path,'def keep(a,b): return a\nkeep(value,value)\n',values={'value':[]})
    call,=entries(events,codes,'keep')
    end=next(e for e in events if e['kind']=='call_exit' and e['invocation_id']==call['invocation_id'])
    assert call['parameters'][0]['ref']==call['parameters'][1]['ref']
    assert call['parameters'][0]['ref'].startswith('snapshot:')
    assert end['return_ref']!=call['parameters'][0]['ref']


def test_observer_does_not_keep_application_value_alive(tmp_path):
    class Value: pass
    value=Value()
    reference=weakref.ref(value)
    address=id(value)
    recorder,_,_,namespace=execute(tmp_path,'def keep(x): return x\nkeep(value)\n',values={'value':value})
    del namespace,value
    gc.collect()
    assert reference() is None
    assert address not in recorder.references


def test_user_repr_hash_eq_and_getattribute_are_not_called(tmp_path):
    class Value:
        def __repr__(self): raise AssertionError('repr')
        def __hash__(self): raise AssertionError('hash')
        def __eq__(self,other): raise AssertionError('eq')
        def __getattribute__(self,name): raise AssertionError('getattribute')
    recorder,events,_,_=execute(tmp_path,'def keep(x): return x\nkeep(value)\n',values={'value':Value()})
    assert events and not recorder.errors


@pytest.mark.parametrize('option,value', [('max_events',2),('max_bytes',2000),('max_codes',1)])
def test_budget_omissions_are_explicit(tmp_path,option,value):
    recorder,events,_,_=execute(tmp_path,'def leaf(x): return x\nfor x in range(10): leaf(x)\n',**{option:value})
    meta=json.loads((recorder.out/f'call-meta.{recorder.pid}.json').read_text())
    assert meta['events']==len(events)
    assert meta['dropped_events'] or meta['dropped_codes']
    assert meta['bytes']<=recorder.limits['max_bytes']
    assert meta['events']<=recorder.limits['max_events']


def test_generator_resume_is_not_normal_function_completion(tmp_path):
    _,events,codes,_=execute(tmp_path,'def generate(x):\n yield x\ng=generate(None)\nnext(g)\ng.close()\n')
    calls=entries(events,codes,'generate')
    assert calls and all(e['suspended'] for e in calls)
    ids={e['invocation_id'] for e in calls}
    assert all(e['completion']=='SUSPENDED' for e in events if e['kind']=='call_exit' and e['invocation_id'] in ids)


def test_parameter_and_local_capture_are_bounded(tmp_path):
    recorder,events,codes,_=execute(tmp_path,'def many(a,b,c): return a\nmany(1,2,3)\n',max_values=2)
    call,=entries(events,codes,'many')
    assert len(call['parameters'])==2 and not call['parameters_complete']
    assert all(len(e.get('locals',[]))<=2 and len(e.get('caller_locals',[]))<=2 for e in events)
    assert not recorder.errors


def test_weak_reference_limit_falls_back_to_snapshot(tmp_path):
    class Value: pass
    recorder,events,codes,_=execute(tmp_path,'def keep(a,b): return b\nkeep(first,second)\n',
        values={'first':Value(),'second':Value()},max_references=1)
    call,=entries(events,codes,'keep')
    assert len(recorder.references)<=1
    assert any(p['ref'].startswith('snapshot:') for p in call['parameters'])


def test_torch_identity_does_not_claim_content_or_materialize(tmp_path):
    import torch
    value=torch.ones(3,requires_grad=True)
    _,events,codes,_=execute(tmp_path,'def keep(x): return x\nkeep(value)\n',values={'value':value})
    call,=entries(events,codes,'keep')
    assert call['parameters'][0]['ref'].startswith('weak:')
    assert set(call['parameters'][0])=={'name','ref'}
    assert value.requires_grad and torch.equal(value.detach(),torch.ones(3))


def test_observer_weak_callbacks_do_not_become_application_calls(tmp_path):
    recorder,events,codes,_=execute(tmp_path,
        'class Value: pass\ndef leaf(x): return None\ndef run():\n x=Value()\n leaf(x)\n del x\nrun()\n')
    assert entries(events,codes,'leaf')
    assert all(code['filename'] not in recorder.observer_files for code in codes.values()
               if any(e['code']==code['key'] for e in events))
