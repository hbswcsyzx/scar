# 最小公共覆盖账本：小门与真实 runner 准备

2026-10-25。真实现档门未运行；没有打开100k调用报告、大archive或raw，没有目标执行。

小必要检查：
`PYTHONPATH=. python3 -B artifacts/experiments/modeling_scope_membership_20261025/check_small.py`

3组检查通过，包含正常 API/codec/query 与关键拒绝、中断情况。fixture只是保留的 source/call
metadata，未创建手写程序IR或执行fixture源码。`small-cost.json` / `small-cost-final.json` 保留64个
合成call+5定义的两次早期成本；后者含其当时producer SHA，在原URI修正之前，文件名不代表
当前代码最终验收。两次SELF peak分别39816/1073056KiB，不用小测保证真实吞吐或内存。
状态、限制和API见
[实现说明](../../../docs/MODELING_SCOPE_MEMBERSHIP_IMPLEMENTATION.md)。

真实 runner 默认不读 inputs：
`PYTHONPATH=. python3 -B artifacts/experiments/modeling_scope_membership_20261025/run_retained.py --catalog /absolute/catalog.json --out /absolute/fresh-ledger`

root确认主联合门终态、准确输入和预算后才加 `--read-inputs`。catalog envelope为
`scar.modeling-scope-input-catalog`1，字段仅 schema/schema_version/catalog。catalog固定字段：
coordinates/source_inventory/source_invocations/contract/native_bundle/os_fragment/native_capture_batch。
每个非空 InputArtifact 均有 path、physical_sha256、physical_bytes、encoding；optional字段显式null。
contract encoding为TEXT，其它根为JSON或GZIP_JSON。native_capture_batch当前必须null，发布明确
schema后再接固定adapter。不得传caller自制的verified/PASS、业务名单或IR来授权成员或语义。

增量组合检查：
`PYTHONPATH=. python3 -B artifacts/experiments/modeling_scope_membership_20261025/check_inventory_binding.py`

只用小fixture核current source-invocations2/3的准确inventory receipt，拒绝同Run旧snapshot、
原URI不符、缺字段/未知格式、bool计数及gzip physical/decoded混淆；不会读取真实报告或raw。
原 `implementation-receipt.json` 保留，新增组合检查结果另存增量receipt，不覆盖旧检查记录。

输出账本始终OPEN，source/call可完整枚举，其它域保独立未访或缺provider债；四轴具体缺口可查。

当前新账本record2/transport2/policyV2，旧prototype1不自动迁移；input catalog envelope仍为1，
原source inventory/report格式不因此改版。新增`check_scope_revision.py`核全部输入根、4源码版本
冻结及assessment/身份分离；`scope-v2-checks-01.json`保存5+3+3组必要检查的完整stdout/stderr。
v2增量收据另存`scope-revision-increment-02.json`；不覆盖旧implementation及inventory-binding收据。
