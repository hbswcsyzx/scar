"""Finish from the saved single-chunk sample; never decompress a second chunk."""
from pathlib import Path
from hashlib import sha256
import json
B=Path(__file__).resolve().parents[3];O=Path(__file__).resolve().parent
G=B/'artifacts/experiments/source_native_context_gate_20261025/attempt01'
S=json.loads((O/'sample.json').read_text());C=json.loads((O/'stored-checks.json').read_text())
M=json.loads((G/'navigation/manifest.json').read_text());Q=json.loads((G/'query-2331.json').read_text())['result']
old=M['inputs']['scope_ledger_manifest'];raw=Path(old['uri']).read_bytes()
assert len(raw)==old['size_bytes'] and sha256(raw).hexdigest()==old['sha256']
assert json.loads(raw)['scope']['record']['revision']==M['inputs']['scope_revision']==Q['scope_revision']
sample_results=[]
for x in S['samples']:
 row=x['retained_row'];context=x['expected_context'];number=x['original_line']
 assert x['line_sha256_with_newline']==context['association']['line_sha256']
 assert row['sequence']==2331 and row['phase']==context['phase']
 assert row['observation_index']==number-1
 assert context['association']['declaration']==M['source_declaration']
 assert context['association']['original_stream_uri']==M['source_retention']['original_uri']
 assert context['namespace_field']=='#/lines/'+str(number)+'/region_namespace'
 assert row['region_namespace'] is not None
 assert row['region_namespace']['body']['definition']==context['definition']['definition']
 assert row['region_namespace']['body']['source']==context['definition']['source']
 assert row['definition']==context['definition'] and row['invocation']==context['invocation']
 assert row['source_binding_reference']==context['binding_fact']
 assert row['source_invocation_reference']==context['invocation_fact']
 assert row['region_activation_reference']==context['activation_fact']
 assert row['marker_reference'] in Q['native_facts']
 assert row['direct_callsite_established'] is False and row['relationship']=='RETAINED_ANCESTOR_CONTEXT'
 for key in ['frontiers','source_frontiers','source_interface_frontiers']:
  assert set(row[key])<=set(Q['frontiers'])
 sample_results.append({'sequence':2331,'original_line':number,'original_observation_index_zero_based':row['observation_index'],
  'phase':row['phase'],'line_sha256':x['line_sha256_with_newline'],'namespace_field':context['namespace_field'],
  'namespace':row['region_namespace'],'invocation':row['invocation'],'marker_fact':row['marker_reference'],
  'source_binding_fact':row['source_binding_reference'],'source_invocation_fact':row['source_invocation_reference'],
  'direct_callsite_established':False,'query_fields_equal_saved_retained_row':True})
assert [x['phase'] for x in sample_results]==['span','output']
assert len(C['chunks'])==160
result={'status':'PASS_STORED_BYTES_AND_FIVE_REPORTS_ONE_DERIVED_RELATION_SAMPLE','navigation':C['root'],
 'actual_root_session':16093,'actual_exit_source':'root terminal exit0 plus retained launch-result exit_code0',
 'stored_gzip_files_verified':160,'stored_gzip_bytes_verified':sum(x['stored_bytes'] for x in C['chunks']),
 'declared_source_association_rows':79592,'declared_native_rows':39796,'declared_full_index_rows':39796,
 'index_descriptor_ranges_checked':[1,39796],'index_records_all_decoded_or_semantically_checked':False,
 'query_report_samples':C['query_summaries'],'old_scope_ledger':old,'old_scope_revision':M['inputs']['scope_revision'],
 'original_source_coordinate_URI':M['inputs']['source_coordinates']['uri'],'original_native_coordinate_URI':M['inputs']['native_coordinates']['uri'],
 'source_native_equal_coordinate_bytes_not_coalesced':True,
 'one_derived_sample_chunk':S['chunk'],'one_derived_sample_decoded_bytes':S['chunk']['decoded_bytes'],
 'derived_data_chunks_decompressed':1,'sample_phase_and_namespace_checks':sample_results,
 'assumption_retained':M['historical_assumption'],'raw_capture_reads':0,'original_EEG_reads':0,'SQLite_reads':0,
 'original_source_association_stream_reads':0,'queries_rerun':0,'native_or_source_producer_runs':0,'target_runs':0,
 'whole_39796_cross_shard_semantics_established':False,'direct_call_established':False,'object_identity_established':False,
 'logical_content_state_ready_established':False,'old_scope_obligations_closed':False,'full_model':'OPEN'}
with (O/'result.json').open('x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
report='''独立复核通过，范围仅为stored字节、五份报告绑定和一个派生关系样本；不表示全部39,796跨片语义闭合。

导航root精确SHA `8cef855ccfe081830a4548aaee80b4226d10aab22d4aa5e102cd1ebe18be8fa6` /47,237B，PUBLISHED。160个gzip的stored SHA/bytes逐项核对：source80/native40/index40，共24,179,311B，无漏项/额外gzip。descriptor分母相合：source79,592/native39,796/index39,796，index声明区间连续1–39,796；未展开所有index/data记录。manifest成本decoded_bytes是原builder计费，不能当本次解码量或混同输出descriptor合计。

root session16093的actual exit0由root确认，保留launch-result也为0。五份query(1/4/244/2331/3182)均绑定准确导航root、八项原inputs和旧scope revision `scope_revision:1ae1c9387ba076a51170c9a60e0a0e5c63ef611c8e5fcc3320d6b0f6a3c03e73`；旧ledger原URI/bytes/SHA及其确切revision字段核对。source/native coordinates即使同SHA也保不同原URI，没有替换namespace或关闭旧scope义务。

四份RETAINED只报告RETAINED_SOURCE_CONTEXT，sample4为CONTEXT_UNRESOLVED且relationship为空、无invocation/definition关联。零Tensor选例1和native-only选例3182均仍保具体invoke+normal Return occurrence、同一原EEG instance/投影与原ETO ordinal事实，Return事实准确附/outputs；不是从Tensor/对象身份外推出上下文。所有报告保HISTORICAL_SCAR_COLLECTOR_EXECUTION_SOURCE_UNRECORDED assumption与相应source/interface前沿，不授directcall/object/content/effects/ready。

仅解一次派生source/000004.jsonl.gz，6,115,281decoded bytes，并核其decoded SHA/rows。样本2331原行4661/4662(原observation index4660/4661)的含换行SHA、span/output、invocation、definition、binding/activation/source事实、原region namespace及其body/source身份均与query相符；原marker事实也在query native_facts内。原行direct_callsite_established=false与source/interface frontiers保留。未解其它159chunks，也未重读原association stream/EEG/raw/DB、重跑query/producer/目标或277源/native门。这个样本不能推广成全39,796关系语义证明。
'''
(O/'REPORT.md').write_text(report)
def rec(p):
 raw=p.read_bytes();return {'path':str(p),'bytes':len(raw),'sha256':sha256(raw).hexdigest()}
files=[O/x for x in ['review.py','finish_review.py','sample.json','stored-checks.json','result.json','REPORT.md']]
receipt={'status':result['status'],'files':[rec(p) for p in files],'reviewed_root':C['root'],'stored_chunks':160,'stored_bytes':result['stored_gzip_bytes_verified'],
 'decompressed_derived_data_chunks':1,'sample_decoded_bytes':S['chunk']['decoded_bytes'],'whole_decoded_scan_performed':False,
 'queries_executed':0,'original_raw_EEG_DB_reads':0,'production_writes':0,'git_operations':0,'full_model':'OPEN',
 'existing_artifacts_unchanged':True,'scope':'stored integrity + declared counts/ranges + five report root/input/frontier bindings + one two-phase retained-row sample'}
with (O/'receipt.json').open('x') as f:json.dump(receipt,f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps({'status':result['status'],'REPORT':rec(O/'REPORT.md'),'receipt':rec(O/'receipt.json'),'stored_chunks':160,'stored_bytes':result['stored_gzip_bytes_verified'],'sample_chunks':1,'sample_decoded_bytes':S['chunk']['decoded_bytes'],'whole_relationships_verified':False},indent=2))
