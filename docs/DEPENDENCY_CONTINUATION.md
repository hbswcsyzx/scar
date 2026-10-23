# 精确增量继续外部源码建模

状态：**Implemented；一次真实 27 文件离线增量与独立审计通过**。日期：2026-10-23。
本轮只新增 `scar/analysis/dependency_continuation.py` 和本文档。
原 `dependency_sources.py`、resolver、workspace、public validate／replay、inventory
与任何目标程序均未修改。没有新增 detector／backend，没有运行目标／GPU／测试。
真实执行和逐项证据见
[增量报告](../artifacts/experiments/first_stage_dependency_continuation_20261023/README.md)。
第一阶段完整程序建模仍 **OPEN**。

## 1. 为什么需要这个入口

原离线依赖准入已保存 86 snapshots／79 三图、199 个 compiler/source witnesses；
1.5GB archive 预算阻止了另 20 个小 snapshot 和 7 个大图的保存。
详见 [原真实报告](../artifacts/experiments/first_stage_dependency_sources_20261023/README.md)。
这些是**预算缺口**，不是“不支持该包”。继续处理全部 106 文件会重复已有证据构造。

这个入口以一个显式 SHA 固定的原报告为起点，只补原档缺失的 source artifacts。
原 program root、依赖 namespace 和每条调用分母全部保留，不把依赖目录塞入 program
root，不创建或声称已得到新的 ProgramInventory／统一程序图。

## 2. API 与独立预算

```python
from scar.analysis.dependency_continuation import (
    DependencyContinuationBudget, continue_dependency_sources,
)
from scar.ir.program.call_edges import CallEdgeBudget
from scar.ir.program.expansion import ContextStoreBudget

report = continue_dependency_sources(
    trace_directory, project_root, parent_result_directory, fresh_out,
    expected_parent_report_sha256=parent_admissions_json_sha256,
    call_budget=CallEdgeBudget(
        max_raw_bytes=256_000_000, max_lines=300_000,
        max_events=250_000, max_references=2_000_000,
        max_source_files=256, max_source_bytes=16_000_000,
    ),
    budget=DependencyContinuationBudget(),
    context_budget=ContextStoreBudget(
        max_compressed_bytes=512_000_000, max_record_bytes=128_000_000,
    ),
    progress=caller_owned_callback,
)
```

示例 raw/context 预算用于已经测得的本次 capture；默认 CallEdgeBudget 不能容纳
当前真实 capture，调用方必须显式提供独立上限。所有预算要求精确类型和正整数。
`fresh_out` 必须不存在，不能位于原 parent 或 raw capture 目录内。原档不覆盖。

新增预算的默认值：

| 分类 | 独立上限 | 计量 |
|---|---:|---|
| parent report 读取 | 64,000,000 | 原文件 bytes |
| parent artifacts 读取 | 1,600,000,000；单个 512,000,000；最多 4,096 个 | 解压 canonical bytes |
| source snapshot 增量 | 8,000,000；单个 8,000,000 | canonical bytes |
| graph 增量 | 1,200,000,000；单个 512,000,000 | canonical bytes |
| checkpoint／最终 report | 每份 64,000,000 | canonical bytes |
| 新 compiler 工作预留 | 768 变体 | 沿原 `compile_cache_key`／原 ledger |

parent 读取不占增量容量，snapshot／graph／report 三类不能借用彼此配额。
每次 checkpoint 受 report record 上限；这是可重复更新的当前状态文件，不按写入次数
消耗 graph 配额。没有预分配占用 64MB 磁盘文件。

graph 1.2GB／record 512MB 是本轮明确采用的工作上限，**不是证明所有剩余图必然装得下**。
原 79 图样本推算剩余 27 图约 644MB，按各文件比率 P90 推算约 1.036GB；最大剩余
文件 277,195 source bytes，原 256MB record cap 不能保证足够，所以本轮采用 512MB。
实际图大小仍须首次构造后计量，不能把估计写成实际结果。

## 3. 先验证原档，再记录全部 guard

以下任一步失败，都不进入新的 source 准备或 compiler matching：

1. 有界读原 `admissions.json`，核对调用方提供的**原文件 SHA**、canonical JSON、
   schema v1、原 program root、compiler profile 以及全部 authority false。
2. 校验原 namespace ID 的完整内容摘要；与当前同版本 interpreter 的 sysconfig／
   tool root 自动 registry 比较。没有按包名选 root，也不扩大 program root。
3. 用原严格 `scan_call_trace` 重新扫描完整 codes／events／meta，检查全部 SHA、
   bytes、lines、完整 metadata、scan issues；逐 entered process/code 比较完整
   captured descriptor、descriptor anchor、首尾 anchors、count 与 summary。
   原录制 Python 的完整字符串必须仍与当前一致。
4. 有界逐个读取 parent 的 sources／graphs／providers artifacts，检查 canonical SHA／
   文件名／size／JSON、raw bytes SHA／size、source 独立解码 fingerprint。
   核三图 context digests、snapshot、namespace、artifact refs；原 link 有 definition
   且图存在时，核 DefinitionID／SourceReference／atom 的完整成员关系。
5. 每个需求源码做一次当前 raw SHA／size／decoded fingerprint guard，逐文件计量，
   不超过独立 source 文件／字节预算。保留 MATCH、DRIFT、UNAVAILABLE 的具体结果。

此处复用的是 **SHA 固定的原 producer/compiler witness**，不是独立重新编译得出的
新证明。artifact／descriptor 核验通过不自动建立 body、effect 或 graph rewrite 权威。
public replay 的完整校验没有被缓存或跳过。

所有 106 guards 与三个 cohort 的计划先写入 `checkpoint.json`，阶段为
`GUARDS_RECORDED_NO_NEW_SOURCE_WORK`；随后才进行 snapshot／prepare。

## 4. 历史源码与当前源码不能混为一谈

当前已观察到的 `execution_evidence.py` drift 对应 14 次历史 importing callback：

- 原 source snapshot／三图／captured code 的连接仍表示**过去 capture 的版本**。
- `source_compiler_witness_reused=true`，`source_compiler_matching_performed=false`，
  `witness_origin=PARENT_SOURCE_COMPILER_WITNESS_NOT_RECOMPILED`。
- 当前 `current_source_guard_matches=false`，保留 current-drift frontier。
- 不删除这 14 次调用；不重新编译当前文件并冒充原历史代码。

guard 是读取时刻的观测，不保证外部文件以后永久不变。对需要新构图的文件，prepare
前再 guard；第一次图导出还需 current raw guard、prepared text／snapshot fingerprint
一致，防止最初 guard 之后的变化被当成已确认来源。

## 5. 每个 cohort 只做必要工作

| 原档情况 | 当前操作 | compiler/source witness |
|---|---|---|
| 79 文件：snapshot 与图都在 | 引用原 artifacts；不 prepare／compile／导出 | 明确继承原 witness；current guard 单独记录 |
| 7 文件：snapshot 在，图缺失 | guard 必须一致；只重建缺失三图，逐项匹配原 SourceContextDigest | 不调用 `_Sources.code` 重新匹配这些 codes |
| 20 文件：snapshot 与图都缺失 | 先保存精确 bytes snapshot；每文件原 workspace 准备一次，首次导出三图 | 仅其原缺 witness 的 groups 调原 `_Sources` 完整 descriptor／future-flags matcher |

cohort 完全由原 artifact 是否存在决定，不按文件名、包名、module 类别或 workload
规则决定。本 capture 对应 44 个新增匹配 groups／21,148 次调用；这是当前输入计数，
不是代码硬编码的条件。

7 个原缺图的私有 scratch 已释放；本轮是从未变化的原源码**重建缺失图并匹配原
context digests**，不能宣称仅凭 digest 就还原了原对象。若当前源码变化，拒绝构图；
若 producer 改动造成新 digest 不同，保留准确 mismatch，不改写旧 digest。

20 个缺 snapshot 文件先全部尝试写入独立 8MB 配额，再开始任何大图准备。
按原 schema 实测这 20 snapshots 精确共需 2,098,293 canonical bytes。
新的 distribution ownership 只解析已归档 METADATA／RECORD，不重新枚举环境、
扫描 transitive imports 或导入目标包；stdlib／tool 的 provider 依据沿用原 namespace
记录。仍未唯一归属时保留 provider frontier。

## 6. locator、归档与 checkpoint

新报告使用独立 `scar.dependency-source-continuation` v1。artifact locator 明确包含：

- `origin=PARENT` 或 `CONTINUATION`；
- 原 `source_root`，artifact 的原 path、canonical SHA／bytes、compressed bytes；
- 对 parent 引用额外包含原报告 raw SHA 和 parent directory。

因此不存在跨 root 仅用短 DefinitionID 或相同路径就拼接来源的行为。保留原 snapshot、
DefinitionID、SourceReference，不重定位源码 namespace，也不复制 79 个已归档图。
新图采用独立 `scar.dependency-continuation-source-graphs` v1，保存原三图内容与 digest，
通过 `source_snapshot_locator` 显式引用 parent 或本次 snapshot；没有改旧 schema 的含义。

```text
fresh_out/
├── checkpoint.json             # 全部 guards；每个 snapshot／file 完成后原子更新
├── continuation.json           # 所有计划文件尝试完毕后写入
├── sources/<sha>.json.gz        # 仅本次新 snapshot
└── graphs/<sha>.json.gz         # 仅本次缺失图
```

每次序列化都会计量**完整实际 canonical bytes 和 SHA**，即使因为 record／total cap
拒绝保存，也记录实际所需大小；超出保留配额后继续计数，不继续积累 payload。
graph 预算拒绝不会阻止已保留 snapshot 的 compiler matching，也不会消耗 snapshot
或小报告配额。每文件及时保存 checkpoint；原始 budget frontier 与原报告均保留。

`continuation_attempt_complete=true` 只表示全部计划文件已尝试，**不是所有缺口解决**。
若仍缺 snapshot／图、current drift 或 matcher mismatch，最终报告继续列出 frontier。
进度 callback 有事件数上限，callback 异常有界记录，不能更改建模结果。

当前入口只接受原 dependency admissions v1 作为 parent，不接受本轮 continuation
当作新 parent。checkpoint 保留已完成 artifacts，便于检查或后续显式扩展增量协议；
没有先行声称实现任意多代恢复或统一 inventory 接线。

## 7. 本轮运行验收门槛

代码冻结后只运行一次完整 27 文件离线增量，原环境／目标程序／GPU 不运行。
独立记录 run.sh、版本／模块 SHA、stdout／stderr、time 与逐文件 progress。
之后核对完整 raw 分母、parent artifact 身份、所有新 artifact SHA／context digest、
199 原 witness 继承与仅 44 新匹配 groups、27 文件 prepare 次数及实际预算。
任何预算未完成都保留原原因；不能把 attempted 或 source VERIFIED 改称完整程序建模。

## 8. Observed／Verified：本轮真实结果

一次运行 exit 0，wall **437.87s**、峰值 RSS **758,140KiB**；随后一次只读独立审计
exit 0，wall **38.03s**、峰值 RSS **792,892KiB**。两个 stderr 均为空。
模块保持冻结 `e87ddba3cca2d350890947ae80c92a43a043ca534c4a829824fdb4c5f1a2123a`，
原 producer SHA 未改变。
原实验脚本、模块副本、日志、报告、47 新 artifacts 的存储文件 SHA 已写入实验
`SHA256SUMS`；独立审计结果 `audit.json` SHA 为
`8c61c34dcd0579fcfb9d28589baa11acdacbf167ddf844d972ed89f2cbc38604`。

- 继承原 86 snapshots／79 三图／199 compiler witnesses；恰好 **27 次 prepare**，
  仅 **44 个新 groups／21,148 次调用**进入原 matcher，全部 VERIFIED。
- 新增 **20 snapshots／2,098,293 canonical bytes** 和 **27 三图包／591,960,596
  canonical bytes**。全部 47 artifacts 的 SHA／source／context／引用审计通过。
- 106 个需求普通源码文件均有 snapshot／三图；current guard 仍 **105／106**，
  历史 execution_evidence.py callback 14 次的当前 drift 原样保留。
- 完整 raw 再次核对：855 descriptors、817 entered groups、100,438 enter／exit。
  最终 SOURCE_VERIFIED 243 groups／86,702 次，原 program pipeline 保留
  553 groups／12,933 次；21 个非文件名 groups／803 次仍 unresolved。
- graph／snapshot／report／compile 无新增预算拒绝，未重建已有 79 图或重复原 compiler
  matching。post-audit 未再次全量解析 parent 图，未执行 public source reprepare。

这些是 source fragments 的真实补齐结果，**不是完整程序建模或优化完成**。
非文件名来源、跨 fragments 的 body／state／resource 连接仍属于第一阶段未完成任务。
