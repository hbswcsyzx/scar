# OS FD-table context：隔离的只读精化

**2026-10-23 correction：旧schema1的continuity资格撤销。** 原capture只选择
`%file,%process,%memory,%desc`；strace6.8的`unshare`与`close_range`不属于这些类。
本机隔离probe确认两个真实已调用的接口均被原filter漏掉。旧35端口gate的byte/typed/FK
结果仍是历史事实，但其InstanceTarget关联不能作为可信continuity结论；下文历史验收
不代表该缺失前提已满足。原artifact不改，当前publicreader显式拒绝schema1。

当前schema2的builder/read均必须收到`OSCaptureCoverage.read(...)`资格对象；它独立绑定
原coordinates、archive、collector实际exec argv、provider binary/version/architecture及
launch nonce，机械核显式required names或`trace=all`，不会由零计数/类名/任意trust bool
授予资格。本次旧capture没有这组独立launch绑定，无法补发该资格。见
[OS_CAPTURE_COVERAGE.md](OS_CAPTURE_COVERAGE.md)。原35 FD端口应使用public R2原选择，
container为Unresolved；现有FD值通过显式`FD_VALUES_ONLY_R2` schema2保留。

2026-10-23。**Implemented + Verified（限定端口范围）**：新增
`scar/trace/os_fd_table_contexts.py`，没有修改R1、R2、core、coordinates、import或CLI。
唯一真实35端口gate已exit0，见第6节。此前static-freeze保持原样记录；既有投影的实际
结果见`FD_TABLE_PROJECTION.md`。完整模型与上游witness自动发现仍OPEN。

## 1. 原图关系与边界

这是原R2选择视图上的一个固定关联精化，沿原实体连接：

```text
R1 original HandleBinding
  → R2 selected ProviderHandle
    → container = InstanceTarget
      → ResourceInstance(OTHER, HANDLE_TABLE, RunRealm, ImportedAt)
```

新增artifact只含所选context资源、所选handle替换、原输入/preimage及限定证明，不复制
其它base/producer/state图。相同HandleBinding ID的原record和精化record不是两个权威
节点：`record()`只选择其中一个，未选中的数据继续由原R2公开reader读取。

HANDLE_TABLE是descriptor namespace/context的观察身份。它不是FD整数、FD映射状态
版本、观察区间号、底层容量数组地址或physical allocation。`ImportedAt(first_port.start)`
只锚定实际第一次观察；无创建、销毁、retirement、quiescence或ready声明。exec本已
private时可能复用物理实现，因此不会每exec创造一个物理allocation。

## 2. 窄API

```python
from scar.trace.os_resource_refinement import OSResourceBase
from scar.trace.os_fd_table_contexts import (
    FDTableContextInputs, FDTableContextBudgets,
    build_os_fd_table_contexts, OSFDTableContexts,
)

base = OSResourceBase(original_r1_manifest, cached_chunks=2)
inputs = FDTableContextInputs(
    capture_root=retained_capture_root,
    archive=original_archive_index,
    coordinates=original_coordinates,
    r1_summary=original_r1_summary,
    r1_audit=original_audit03_summary,
    projection_summary=published_projection_summary,
    projection_files=published_projection_file_receipts,
    projection_events=published_projection_context_events,
    context_evidence=published_small_context_evidence,
)
result = build_os_fd_table_contexts(
    base, original_r2_manifest, inputs, fresh_output,
    budgets=FDTableContextBudgets(), progress=progress_callback,
    capture_coverage=independently_capture_bound_coverage,
)
view = OSFDTableContexts.read(
    base, original_r2_manifest, inputs, result["manifest_receipt"]["path"],
    capture_coverage=independently_capture_bound_coverage,
)
selected = view.record("handles", original_handle_ordinal)
work = view.record("submissions", original_work_ordinal)
resource = view.selected_resource(original_typed_resource_id)
```

所有metadata路径由调用方显式提供。provider URI不作为任意文件打开入口。raw只通过
原archive的精确logical/local映射，在显式capture_root下解析，拒绝symlink与越界。
当前R2公开base绑定原publication地址；本模块不隐式支持移动/重命名后的namespace。

`selected_resource()`明确返回三种coverage：

- `SELECTED_CONTEXT`：本artifact新增的context。
- `R2_SELECTED_BASE`：原R2已资格化的部分base资源。
- `NOT_IN_SELECTED_REGISTRY`：这里未选中；**不表示原模型中不存在该ID**。

返回值同时带原`base_total`、`base_selected`、`contexts_selected`及
`complete_registry=False`。`context_resources`只含新增资源，不能当完整资源表。
实际分母为原12,683资源、R2选中35资源、本轮新增3观察context；这38个selected资源
不能替代原完整资源registry。

## 3. 独立证明器做什么

不读取projection的`mechanically_bindable_selected_ports=35`或status布尔来授身份。
builder与公开reader均重新执行以下检查：

1. 用原`OSResourceRefinement.read`执行R2的全部限定preimage/typed endpoint校验。
   核原R1/R2 metadata精确bytes、SHA、schema、Run与原坐标绑定；结束再核输入未漂移。
2. 校验原audit03的完整count authority与原R1 manifest完全一致；全scope行分类必须只含
   COMPLETED/SIGNAL，保留原分母。原archive/coordinates/投影/小证据必须绑定同一组SHA。
3. 经R1公开artifact reader核全部原OS artifact范围/ordinal/整chunk双SHA。枚举当前OS目录
   必须与原archive的精确路径集合相同。唯一排除项来自原target_exec完整artifact receipt。
4. 独立重读其余小raw档，核全部stored/raw SHA、实际行/完整call计数，并重算相关事件。
   复用既有R1 parser grammar和flags拆分；与原projection的完整file receipts/context-events
   **逐内容相等**才接受。不信任“已验SHA”布尔。unfinished/resumed、context迁移marker、
   不完整必需字段或flags拒绝证明，预算失败不发布。
5. 验证相关成功exec的原birth/thread-group membership；不把TID数值相等独立当TGID证明。
   未绑定actor只允许精确target_birth指向的creator上下文，不能任意降为process=None。
6. 从完整补集计数重做target唯一exec证明；要求当前v1范围内全scope
   execveat/unshare/close_range计数为0。并非通过改时间排序恢复共享状态。
7. 小证据中的child birth经`OSResourceBase.resolve`再次核真实JSONL chunk、line、ordinal、
   row SHA和原source namespace；非共享birth必须有完整flags，不能拿后来的exec回填。
8. 各所选端口重新核原selector/真实source/actor，并确定其限定观察区间。target使用完整
   补集证明；其它actor使用实际先前exec或已资格化private birth。跨区间切换或无法证明的
   shared-child选择拒绝；CLONE_FILES本身不使一个已知container失效。
9. 资源/handle使用既有public typed codec，检查新增container的kind/role/RunRealm/ImportedAt
   与实际FK。原资源表只流式检查新ID碰撞并核12,683分母，不复制完整registry，不进行
   全百万Work codec验证。

当前v1是一个受限proof consumer，不是完整Linux fdtable解释器：对未满足上述证明形式
的输入显式拒绝，不把它们标NONE，也不为某个程序、函数名或actor数字写分支。

**自动化边界**：这是proof-consuming adapter。当前`context_evidence`携带了此前小读
定位的childbirth selector；本模块会独立核原row/flags/namespace，但不会自行从全部
已选ports+coordinates birth反查该R1 source位置。提供checked witness不等于上游已
自动发现，也不等于端到端完整建模。后续应泛化这个source→原selector查找，避免actor
数字或手选ordinal成为工具必需输入；该上游接线不在本次35端口gate中实现。

## 4. 存储schema与只读选择

新artifact schema为`scar.os-fd-table-context-refinement`，version1。它不是新的IR根。

| 字段 | 作用 |
|---|---|
| `base` / `r2` / `run` | 原typed artifact与执行身份 |
| `inputs` | 所有显式原metadata/proof文件的准确receipt及原schema |
| `context_resources` | 新增既有ResourceInstance record |
| `handle_refinements[].r1_preimage` | 原R2所限定的R1真实selector、row SHA和ID |
| `handle_refinements[].r2_record_sha256` | 原R2选中record经既有有界encoder编码后的SHA，含末尾换行 |
| `handle_refinements[].replacement` | 同ID，仅container改变的既有HandleBinding |
| `context_proofs` | 每个观察context的真实witness/原行区间/所选handle IDs |
| `counts` | 原total、R2 selected、补集读取和本轮精化分母 |
| `validation` | 部分真实端点校验及明确未执行的完整模型语义边界 |

公开reader独立重算期望document并精确匹配，不能删proof、改端点或额外加record。
`record("handles", ordinal)`委托原R2后只选择批准的container精化；`submissions`完全委托
原R2，所有access/executor/Work保持原选择语义。原OFD、handle lifetime、rights、起止、
source和pipe不同OFD等字段不变。

输出目录必须fresh。先完成证明、typed/FK检查再以O_EXCL临时文件+fsync+link发布
`manifest.json`；失败不覆盖或变更原输入。PUBLISHED只表示这个限定片段发布成功。

## 5. 预算与仍OPEN的边界

默认：12MB raw、200k行、16KiB单行、512档、128ports、8contexts、20k原resource IDs、
2MB单metadata、4MB输出。只有12MB以内小raw重验；target主原档不重读。现有public
selector reader额外逐chunk有界核验实际选中行，不重导原百万表。

完整ExecutionModel validator仍需要真实ProgramSnapshot；本模块没有构造或绕过它，也
不能把局部typed/FK检查报告为全模型语义PASS。原canonical source/effects、FD映射内容、
继承/CLOEXEC/offset、并发顺序、retention、GPU ready均保持原前沿。ancestor的数字TGID
也不在本次补全；允许已知context资源位于RunRealm、原EvidencePoint.process继续None。

## 6. 唯一真实gate

实验：`artifacts/experiments/first_stage_fd_table_contexts_20261023/gate-attempt01/`。
builder→public reader→record/selected_resource实际**exit0**，wall **13.67s**，
RSS **188,896KiB**。没有修改代码或重复gate，没有新target/GPU/采集/优化。

- 全部35个实际HandleBinding typed codec、R2 ID/canonical preimage与原source/selector通过；
  除container外逐字段不变。新增3个实际ResourceInstance，所连端口数3/31/1，
  role/realm/ImportedAt/原point与FK全部通过。
- 22个实际producer Work中的13对pipe端口仍不同OFD，且每对同container。
- 原R2所选25个Work、38个provider access与3个executor选择完全不变。
- 从原公共resource reader实际取一个**确实存在但未被R2选中**的ID，查询得到
  NOT_IN_SELECTED_REGISTRY；保留其原locator证明这不代表全模型不存在。
- 10个freeze中Python模块SHA运行前后匹配。当前实际导入的97个SCAR源模块分别保存
  当前SHA，运行中无漂移；没有把其它source任务新修改的模块伪称为旧freeze字节。
- builder和公开reader各自独立核完整小补集及原public selectors；没有读取main raw或
  重新扫描百万observations。局部typed/FK PASS不提升为完整ExecutionModel语义PASS。

发布片段为**281,281bytes**，SHA256
`6084ad77231fd9790bd4706966ceb7d44370f58b3c5d47bcc3b660ca7941ee8c`。
原R1/R2未变；在这个指定的新选择视图中35个container已精化。第3节所述upstream
childbirth selector自动发现仍OPEN，因此本结果不是端到端完整自动建模验收。
