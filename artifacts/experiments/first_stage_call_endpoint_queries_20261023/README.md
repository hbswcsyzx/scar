# 原报告→限定原图端点：实际公开查询验收

2026-10-23。attempt01一次exit0，wall2.98s、脚本2.87s、RSS62,052KiB。
只读旧272038已发布report，全部27参数+27completion经CallEndpointQueries回到原
InventoryPartitions typed body及GraphIndex实体；4个实际公开入口反例均拒绝。
详细示例保queries.json、rejections.json、producer/imported-producer与summary。

attempt01输入Run为capture:91a2ed5e...，不计作当前369749报告已验收。脚本不
prepare/compile/回放源码或目标，没有producer/状态图复制、world或alias等价证明。
原条件与所有权限限制完整保留；详见docs/CALL_ENDPOINT_QUERIES.md。

当前报告完成后另以同一公开入口运行`current369749`，实际exit0：27+27与4种拒绝
均通过，脚本2.90s、RSS78,480KiB。原输入为当前run/source/bindings/coordinates，
全部原Run独立绑定，没有借旧调用权重或endpoint记录。两个目录互不覆盖。

运行方式：

```bash
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" python artifacts/experiments/first_stage_call_endpoint_queries_20261023/run.py \
  --report artifacts/experiments/first_stage_partitioned_operand_routes_attempt02_20261023/result/analysis/manifest.json \
  --coordinates artifacts/experiments/first_stage_partitioned_operand_routes_attempt02_20261023/result/capture-coordinates.json \
  --out artifacts/experiments/first_stage_call_endpoint_queries_20261023/fresh-output
```

输出必须为新目录；不覆盖attempt01。新运行验收须显式换用新report及其coordinates。
脚本从该报告读原source/bindings/inventory receipts，检查匹配与实际导入代码SHA，
不会移植旧Invocation/计数到新Run。
