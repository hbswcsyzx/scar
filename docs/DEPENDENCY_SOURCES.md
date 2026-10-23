# 自动准入已观察到的依赖源码

状态：**Implemented；真实离线准入部分完成，独立 artifact／raw 审计通过**。日期：2026-10-23。
只新增 `scar/analysis/dependency_sources.py` 与本文档。没有修改旧 CLI、resolver、
workspace、wire 或原有的建模任务。实现后已获准针对现有 capture 执行一次离线
源码准入及三图导出；没有运行测试、GPU、目标程序或新的采集。第一阶段仍 **OPEN**。

## 1. 本次必要连接

已有调用绑定中的 71,368 条 `CODE_SOURCE_INCOMPLETE` 全部被原 project-root 边界
拒绝，其中多数实际源码文件存在。参见 [SOURCE_RECOVERY_FRONTIERS.md](SOURCE_RECOVERY_FRONTIERS.md)。
本模块增加一个独立准入入口，从实际 CapturedCode 选择环境中的来源 namespace，
复用现有 code/source resolver，保存已经准备的源码三图；不把外部结果塞入旧
inventory，也不伪造 ProgramInventory、program entry 或统一 ProgramSnapshot。

```python
from scar.analysis.dependency_sources import (
    DependencySourceBudget, admit_dependency_sources,
)
from scar.ir.program.call_edges import CallEdgeBudget
from scar.ir.program.expansion import ContextStoreBudget

report = admit_dependency_sources(
    trace_directory,
    project_root,
    fresh_output_directory,
    call_budget=CallEdgeBudget(),
    budget=DependencySourceBudget(),
    context_budget=ContextStoreBudget(),
)
```

调用方需要为真实 raw trace 提供足够的独立 `CallEdgeBudget`。示例默认预算并不是
当前 LeWM 采集的推荐参数，也没有自动提升输入报告自己的预算。输出目录必须不存在。

## 2. 自动路径与现有组件

1. 仅用原 `project_root` 调用一次 `scan_call_trace`，并用现有
   `_EnteredCodeSink` 保留每个 entered process/code 的计数与首尾 anchors。
   原 collector metadata、codes/events 原档、引用、计数仍由严格 reader 核验。
2. 保留所有 entered group。program 内的代码标为 `PROGRAM_SCOPE_RETAINED`，交回
   原 pipeline，不重复 prepare，不把这个状态当作新覆盖证明。
3. 逐 process 比较 collector 的完整 `python` 字符串与当前 `sys.version`；不相等
   或缺失时保留 `RECORDED_PYTHON_MISMATCH`，不使用当前 compiler 猜过去的 code。
   字符串匹配不证明 executable 二进制身份，报告保留这一条件。
4. 来源 namespace 只从当前同版本 interpreter 的 `sysconfig` purelib、platlib、
   stdlib 及本工具模块所在 root 建立，规范化、去重，并选取包含实际 filename 的
   最具体 root。原 program root 不变，不能扩成 `/home`、`/` 或任意捕获路径的
   公共祖先。root 身份包括来源角色、版本和 namespace。
5. 初期只准入实际存在、规范绝对路径的 `.py`。frozen、generated、relative、
   missing、noncanonical、native 等 code filename 均有单独 frontier，不造源码。
6. 按实际 filename 去重、按 root 分派现有 `_Sources`／`_SourceWorkspace`。
   workspace 的 `entry=None`，不调用 import closure discovery 或 `prime_sources`。
   只对实际需要的文件运行现有 prepare/projection/compiler matcher。
7. 编译语境保留 `RECORDED_FUTURE_FLAGS`、原 `compile_filename`，使用现有
   `future_flags_for`、`compile_cache_key`、完整 descriptor 比较和优化级别候选。
   不新增 compiler matcher，不按包名、函数名或 workload 规则认定匹配。

普通 `.py` 路径归属环境 root 只说明允许对它进行有界分析。是否匹配当前捕获 code、
是否有可绑定 DefinitionID、是否有完整 body、effect 或 runtime 关系，是不同结果。

## 3. 已安装 provider 归属

对确实有需求文件的 purelib/platlib root，只枚举其直接目录项里的 `.dist-info`，
读取有界 METADATA／RECORD，不 import 包、不调用 entry point、不递归遍历 package。
仅把 RECORD 中恰好对应本次需求路径的条目用于归属，不跟随脚本等 root 外路径。

每个 provider 保留 distribution Name／Version、原 METADATA／RECORD 路径、
原字节 SHA 和独立保存的 metadata artifact。多 owner 保留歧义；没有 RECORD、
metadata 缺失、读取失败或预算不足时保留 provider frontier，不能补造包版本。
当前未实现 egg-info／editable 等其它 ownership 协议。

stdlib provider 保存完整 Python 版本、implementation、sysconfig 角色与 namespace；
tool provider 保存本工具版本与模块来源。报告保留原 collector Python、当前
executable/prefix/cache tag 等依据，但不声称捕获时的 executable 二进制已被验证。

METADATA 和 RECORD 是归属证据，不能替代源码 SHA、实际 code/source 比较或 purity。
进入 tool root 也不会自动将每次调用判为 observer；callback／mode 身份、生效区间
仍须另行连接。现有 1,905 条工具 callback 不会按文件路径从分母删除。

## 4. 不丢弃已准备的源码结构

新 `_ArchivingWorkspace.prepare` 在第一次 `super().prepare()` 返回时立即导出该
PreparedSource 的原三图。此时它们仍在内存中，不需要第二次 prepare。

```text
严格 raw scan → 实际 code/filename → namespace/provider
    → 保留精确 source snapshot
    → 原 workspace 的第一次 prepare
    → 原 semantic / semantics / control 三图归档
    → 原 _Sources 完整 descriptor 匹配
    → 原 CodeSourceLink + root/artifact 限定引用
```

源文件先保留原始 bytes 的 base64、原字节 SHA、原文件名、按 `tokenize` 解码且
通用换行后的 text／UTF-8 fingerprint。随后保存三图原 canonical 文档、原
SourceSnapshot，以及与原 inventory 一致算法计算的 SourceContextDigest。

归档只复用 `source_layers._write_gzip_exclusive` 的通用独占 gzip 写入。不调用
`reconstruct_source_layers`：后者需要真实 inventory 输入，并会重新 prepare。
新三图 artifact 明确标为 `EXPORTED_DURING_FIRST_SOURCE_PREPARATION`，**不是**
“已独立 replay 并匹配某个 inventory”的旧 archive 收据。

若三图 canonical 归档超过 record／total byte 预算，保留先前独立 source snapshot
与 `SOURCE_GRAPH_ARCHIVE_BUDGET`／`SOURCE_GRAPHS_UNAVAILABLE`，不只留下标签然后
悄悄丢失来源。source 本身无法保存时，该文件不继续 prepare／匹配；逐 code
保留失败。snapshot 导出后若准备或匹配时内容已变化，保留 mismatch，不连接旧图。

## 5. 全局预算与输出

所有 namespace 共用一次调用的 source 文件数／原始字节预算和同一个有界
`PreparedContextStore`。各 worker 不各自获得一份总预算，也不永久保留重型
PreparedSource；现有 workspace 保留轻 projection，重上下文进入有界 scratch。
计量报告区分 source、metadata、archive、compile reservations 和实际 cache entries。

编译按现有 cache key 预留最多三个 optimize 变体；重复代码复用同 key，失败不退款。
这个计数是保守的工作预算预留，不宣称所有预留都实际执行了 compile。
metadata 目录项／文件／字节、archive record／总 canonical bytes、report bytes
另有全局上限。归档字节上限按未压缩 canonical bytes 收费，另报实际压缩字节。

```text
fresh_output_directory/
├── admissions.json
├── sources/<sha>.json.gz       # 独立原始源码与解码 snapshot
├── graphs/<sha>.json.gz        # 第一次 prepare 的原三图及 digest
└── providers/<sha>.json.gz     # 原始 distribution metadata
```

`admissions.json` 使用新 `scar.dependency-source-admissions` v1，包含：

- 原 program/capture、raw file identity、collector metadata 与扫描问题；
- namespace registry、provider artifact、每个 source snapshot／三图引用；
- 所有 entered process/code、完整 descriptor 与原 anchors、原 CodeSourceLink；
- 原 DefinitionID／SourceReference／SourceSnapshot（resolver 有结果时），以及
  source-root 和 artifact 限定关系，不能跨 root 只按短 ID 字符串连接；
- 每条准入、保留、匹配、拒绝和具体 frontier；group 与 entry 权重两种 summary。

`SOURCE_VERIFIED` 只表示原 resolver 成功验证 code/source；它可以同时有 provider、
定义、图归档等 frontier，不能把此状态作为“完整恢复”的总开关。
`PROGRAM_SCOPE_RETAINED` 也不是依赖解析成功或原 body 已恢复的证明。

全局 raw scan 或最终 report 发布失败会抛出异常，不发布成功报告。已经创建的本次
独立 artifacts 可能保留，供定位问题；不能把缺少 `admissions.json` 的目录当作
完成产物。现有目录与旧产物始终不覆盖。

## 6. 当前验收边界与下一步

真实离线验收位于 `artifacts/experiments/first_stage_dependency_sources_20261023`。
单次运行 exit 0，保存 86 个 source snapshots、79 个原三图 artifacts。
817 个 entered process/code groups／100,438 次调用中：199 groups／65,554 次原
CodeSourceLink VERIFIED，553 groups／12,933 次保留给原 program pipeline，65 groups／
21,951 次 unresolved。其中 44 groups／21,148 次是 archive 总预算阻止后续 20 个
文件的 snapshot／prepare／匹配；**是预算未完成，不是代码不支持**。另 21 groups／
803 次是非实际文件名。7 个已有 matcher 结果的文件缺图，对应 181 次调用。

独立 stdlib-only 审计逐个验证全部 493 artifacts／1,499,996,718 canonical bytes，
重新核对完整 raw SHA／计数及所有 admission descriptor、artifact／definition／source 引用。
未重编译／prepare。详细真实结果、代价、预算失败与边界见
[实验报告](../artifacts/experiments/first_stage_dependency_sources_20261023/README.md)。
这只是代码来源恢复的必要连接，不是第一阶段完整建模完成。
没有新增 CLI，也没有修改旧 seed v1/v2、inventory v8、discovery、
composition 或 invocation wire。所有 body、effect、状态、observer origin、
实际参数绑定、统一 execution model 和 transformation 权威字段保持 false。

## 7. 最小增量继续方案（Proposed，未运行）

只补缺失证据，不重新准入全部 106 文件，也不重新 prepare 已保存的 79 图文件。
新入口／manifest 是独立 sidecar 的增量扩展；旧 v1 报告不可覆盖或原地补值。

### 7.1 先验证可复用的共同前提

1. 以原 `admissions.json` 原文件 SHA 与 schema 锁定 parent；重核原 capture 全部
   codes／events／meta 的 SHA、size、lines、descriptors、817 groups 与 100,438 次
   调用计数。不能只复用报告的 summary，或只按相同文件路径认定相同 capture。
2. 验证 parent 限定的原 86 snapshot／79 三图／metadata artifacts canonical SHA、
   context digests 与引用，保留原 source root，不重定位 DefinitionID／SourceReference。
   引用必须至少含 parent-report 身份、source-root 身份、artifact 路径与 SHA，不能把
   两个 namespace 中的短 ID 字符串直接合并。
3. 原 recorded/current Python 条件、未来 flags、compile filename、optimize levels、
   完整 captured-code digest 与 matcher profile 必须保留。旧 VERIFIED witness 标为
   **REUSED_SOURCE_COMPILER_WITNESS，非本次重新编译**；不调用新 matcher 猜测。
4. 每个需求源码做一次有界当前 raw SHA／size／decoded fingerprint guard。
   本次只读检查 105／106 一致；`scar/trace/execution_evidence.py` 存在并行修改，
   对应历史 importing callback／14 次调用。历史 artifact 可继续作为原 snapshot
   的证据；当前源证明须保留 drift frontier，不能静默改 SHA 或重用为当前版本。
   原 capture 的历史 witness 与当前源码一致性是不同命题。

### 7.2 三种 file cohort，分别做最少必要操作

| cohort | 操作 | 明确不重做 |
|---|---|---|
| 79 有图文件 | 引用已审计原三图、snapshot、原 code/source witness；保留 current guard／drift | 不 prepare、compile 或重新导出三图 |
| 7 有 snapshot／matcher、缺图 | 只为缺失图构造 source layers；从原 snapshot 与不变 fingerprint 得到三图并与原 context digests 比较 | 不重复匹配已验证 codes，不声称从 digest 还原原图对象 |
| 20 缺 snapshot 文件 | 先保存精确 snapshot；每文件一次现有 workspace prepare／导出；仅对其 44 个原未匹配 groups 运行原 `_Sources` matcher | 不重扫传递 imports，不按包名作推断 |

7 个缺图文件的旧私有 scratch 已释放；原档只有 snapshot 与三图 digests，不能宣称
仍握有原 graph objects。构造仅限这 7 个文件，而且必须匹配原 digest；若 producer
实现已变化导致不能一致，记录 producer／context mismatch，不能覆盖旧 digest。
新 manifest 同时列出 inherited artifacts、reused witnesses、new artifacts、仍未解决
frontiers；全部指向限定 artifact，不伪造统一 inventory 根或 whole-program 覆盖证明。

### 7.3 预算按真实 cohort 计算，逐文件持久化

实际剩余 source：20 缺 snapshot 共 **881,024 bytes**，7 缺图共 **412,731 bytes**。
20 snapshot 按现 schema 精确需 **2,098,293 canonical bytes**，应先持久化并预留
manifest／checkpoint 配额，避免再次被大图饿死。旧 provider metadata 只需引用及
hash 核验；不能再枚举／保存全部 metadata 后占用本次增量图预算。

79 个已有图的实际 canonical/raw 加权比为 497.73；27 文件推算新增图约 **644MB**，
按各文件比率 P90 推算约 **1,036MB**。这是实测样本的估计，**不是硬上限**。
最大剩余文件 `torch/nn/functional.py` 为 277,195 source bytes，现 256MB record
上限不能保证足够。完整逐文件 bytes 与比率在实验 `cohort_stats.json`。

实施时在每文件首次导出记录实际 canonical bytes、累计预算与 artifact SHA；预算
拒绝也必须保存实际所需 bytes 和完成 checkpoint。下一次仅重试缺失 artifact，
不丢失已完成结果。不得直接猜更大上限后全量盲跑；预算批准前先用上述实测增长量
说明所选 cap 的含义，并保持预算拒绝为预算 frontier，不改称 unsupported。

这个继续方案不需要等待 SQLite，也不修改原 public validate／replay 的完整校验。
当前只完成设计，**没有实现或启动任何增量任务**。
