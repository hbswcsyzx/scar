# 实际捕获的外部源码准入：部分完成，预算边界已审计

日期：2026-10-23。**本实验不是新的 LeWM 执行，不是优化或加速比实验。**
仅对已经成功保存的真实 capture 做一次离线源码准入／原三图导出，再做一次
独立只读 hash、计数与引用审计。目标程序、GPU、新采集、测试均未运行。
第一阶段完整建模仍 **OPEN**。

## 1. 可复核输入与执行

- 原 capture：`../first_stage_lewm_dispatch_20261023/trace`，process 272038。
- 原 program root：`/home/zyf/AAA/le-wm`，没有扩大到环境目录或 `/home`。
- 执行脚本：[run.sh](run.sh)、[run.py](run.py)；逐文件进度：[progress.jsonl](progress.jsonl)。
- Git revision：`4fb1432f7f642199cd5208930a3c99d7a4e90874`；运行模块为尚未提交的独立新文件，
  故还保存了 [dependency_sources.snapshot.py](dependency_sources.snapshot.py)。其 SHA-256：
  `249aaacbfdaf71ad9ecbef886438dcbbd886b387104d301f11b6bce75631e283`。
- Python：conda `lewm`，3.14.7。报告保存 collector 与当前完整版本字符串和环境依据；
  版本字符串相等，不等同于已验证 executable 二进制身份。
- 原始报告：[result/admissions.json](result/admissions.json)，文件 SHA-256：
  `fc97075aa66a92758938ad8416347d895e6b18ef0e454053fc7f9c1a7d2f0424`。

独立审计重新读取了原 capture 全部内容，不只抽样：

| 原逻辑文件 | 字节数 | 行数 | 解压原内容 SHA-256 |
|---|---:|---:|---|
| call-codes.272038.jsonl | 226,156 | 855 | `4d1f4c2b675481a1af7bc65f7ad6073796e2f1e85695d3538ecdc92988d8eff4` |
| call-events.272038.jsonl | 187,485,595 | 200,876 | `f44ee6c7616566f8cf670b51de23afd0cae33cd4929cd18443af177d4e463ff9` |
| call-meta.272038.json | 956 | 34 | `297df87ea99ff7fce1ce6ba1522878675ccdea4434bcd2d132eb713045c96747` |

实际为 **855 个 captured descriptors、817 个有 entered
invocation 的 process/code group、100,438 enter 和 100,438 exit**。855 与 817 的区别
是有些已捕获 descriptor 没有 entered invocation；报告没有删除它们的原始文件。

## 2. Observed：产物与未完成原因

准入 root 由 interpreter 的 sysconfig 和工具来源自动确定：stdlib、purelib/platlib、
SCAR tool source，共三个 namespace。没有按 LeWM、Torch、NumPy 或函数名称写规则，
没有扫描传递 import closure，没有修改旧 inventory／CLI／wire。

| 状态 | process/code groups | entered invocations | 含义 |
|---|---:|---:|---|
| PROGRAM_SCOPE_RETAINED | 553 | 12,933 | 原 program 内代码交回原 pipeline；不是新的 source/body 覆盖证明 |
| SOURCE_VERIFIED | 199 | 65,554 | 原 compiler matcher 得到 VERIFIED CodeSourceLink；不代表 body／effect 已恢复 |
| UNRESOLVED | 65 | 21,951 | 见下列严格区分的原因 |

UNRESOLVED 的 **44 groups／21,148 次调用**来自 20 个实际存在的 `.py` 文件：
共享 archive 的 1.5GB canonical 预算已耗尽，连后续小型源码 snapshot 都无法写入，
所以未继续 prepare／compiler match。它们是**预算未完成**，不是“不支持这些源码”。
其余 **21 groups／803 次调用**是 frozen／generated 等非实际文件名，明确保留
`NONFILE_CODE_FILENAME` frontier；本次没有为它们合成源码。

106 个需求源码文件共 4,270,568 原始字节，实际保存：

- **86 个 source snapshot**；其中 **79 个原 semantic／semantics／control 三图 artifact**。
- 7 个已完成 matcher 的文件因相同 archive 预算未保存三图，对应 181 次调用。
  这些调用已包含在 SOURCE_VERIFIED 中，不能再次计数，也不能宣称图已完整。
- 87 个文件有已安装 distribution ownership；328 个 provider metadata 原文件被保存，
  本次 provider frontier 为 0。metadata 不是 source/body/purity 证明。
- 总共 **493 个 gzip artifacts**，未压缩 canonical 总字节 **1,499,996,718**，
  压缩总字节 **175,309,649**。artifact 路径／canonical SHA 在原报告内；独立审计逐个核验。

## 3. 实际预算与代价

参数以 [run.py](run.py) 和报告内完整 budget 为准，关键上限：

- raw bytes 256,000,000；lines 300,000；events 250,000；references 2,000,000；
  source files 256；source bytes 16,000,000。
- archive canonical 1,500,000,000；单 record 256,000,000；report 64,000,000。
- shared context store compressed 512,000,000；单 record 128,000,000。

实际 source prepare 86 次；compile 预留及原 cache entries 均为 258。
shared scratch 累计压缩写入 83,840,835 字节、解压序列化写入 318,634,994 字节。
474 个进度事件，callback errors 为空。没有 source、compile 或 scratch 预算失败；
本次观察到的门槛是 archive 总 canonical 预算。

| 运行 | wall | user CPU | system CPU | 峰值 RSS | exit |
|---|---:|---:|---:|---:|---:|
| 单次源码准入 | 852.45 s | 846.74 s | 3.95 s | 895,792 KiB | 0 |
| 独立只读审计 | 100.31 s | 95.12 s | 5.02 s | 1,183,580 KiB | 0 |

时间为离线分析器代价，**不能解释为 LeWM wall-clock 或加速比**。
stdout／stderr／`time -v` 原档全部保留；两次 stderr 均为空。

## 4. Verified：独立审计究竟检查了什么

[audit.py](audit.py) 是 stdlib-only 程序；[audit.json](audit.json) 为结果。
没有 import SCAR、重新 prepare 或重复 compiler matching。

1. 检查全部 493 个 artifact 的 gzip 内容、canonical JSON、文件名 SHA、字节数。
2. 检查 source／metadata 原 bytes 的 base64、SHA、size；独立解码 source，核对 decoded
   fingerprint；三图各自 digest 与原 SourceContextDigest 一致。
3. 检查所有 artifact 引用、source root、snapshot、CodeSourceLink；有归档图及 definition
   时，检查 DefinitionID、SourceReference／atom 在原 semantic 图中的完整成员关系。
4. 重读三个 raw 文件的全部 SHA／size／lines；855 descriptors、817 groups、全部
   enter／exit 与每条 admission 的完整 captured descriptor、权重和原 collector metadata 一致。
5. 核对运行模块保存副本 SHA。所有检查通过。

这些检查确认原档与连接自洽，**没有**独立重复 compiler 证明；没有证明 whole-program
graph、body、effect、state、实际参数绑定或 observer origin。所有对应 authority 仍 false。
尤其没有因“位于 SCAR 路径”就删除 callback，或把 14,224 次 dispatch lookup 判为已证实 observer。

## 5. Observed：继续之前的源码 guard 与剩余大小

[cohort_stats.py](cohort_stats.py) 仅只读原报告和当前 106 个源码文件，没有 prepare／compile；
[cohort_stats.json](cohort_stats.json) 保存每文件 raw SHA／size／decoded fingerprint guard。
**105／106 一致**；唯一 drift 为并行开发中的
`scar/trace/execution_evidence.py`：

- 保存版本：18,375 bytes，SHA `cd64d7fbf5d2ccf079d325a3bfba547b90bf272b45f859f38d5010c871293688`。
- 审计时当前版本：21,209 bytes，SHA `5655ab4131926e96bcd494bbdc1db20a77ca4d75465d58a4c014078464bbf2e5`。
- 影响一组 importing callback／14 次调用；历史 snapshot、三图和 code witness 原档仍有效，
  不能将其静默升级为“当前源码未变化”。保留历史 scope 与 current-drift frontier，不能覆盖原 artifact。

| 剩余 cohort | 文件数 | 原 source bytes | 当前已保存 |
|---|---:|---:|---|
| 缺 snapshot，未 prepare／match | 20 | 881,024 | 原报告已有 filename／raw SHA／fingerprint |
| 有 snapshot／matcher witness，缺图 | 7 | 412,731 | 原 snapshot、CodeSourceLink 和三图 context digests |
| 合计 | 27 | 1,293,755 | 只需继续这些缺口，不是重新处理全部 106 文件 |

按原 source artifact schema 直接计算，20 个缺失 snapshot 共需 **2,098,293 canonical bytes**
（未写入）；这是精确值，不是图大小估计。完整 cohort 路径及 bytes 在 `cohort_stats.json`。

已有 79 个三图 artifact：2,976,813 source bytes → 1,481,646,361 canonical bytes。
原三图 JSON 的 SourceReference／长路径等重复结构导致显著体积，不能按 raw bytes 等量计费。

## 6. Inferred：27 文件新三图的预算增长

以 79 个实际产物的 graph/source 比率估算，**不是上限或保证**：

| 观察到的比率取法 | canonical graph bytes / raw source byte | 27 文件推算 canonical bytes |
|---|---:|---:|
| 总字节加权比率 | 497.73 | 643,939,471 |
| 各文件比率中位数 | 512.97 | 663,663,427 |
| 各文件比率 P90（inclusive） | 801.13 | 1,036,461,253 |
| 已观察最大比率 | 1,048.87 | 1,356,985,915 |

最大已保存单图为 100,286,083 canonical bytes（153,786 raw bytes）。剩余最大文件
`torch/nn/functional.py` 有 277,195 raw bytes；按加权比率约 138MB，P90 比率约 222MB，
按已观察最大比率约 291MB，故现有 256MB record cap 也不能被假定必然足够。
不能把任何一个推算值写成“实际新图所需 bytes”；在首次构造时记录实际 canonical size，
预算拒绝也应报告所需 bytes 并保留已完成 checkpoint。

## 7. Rejected 与 Proposed：后续最短增量路径

**Rejected**：共享 archive 配额允许大图先耗尽全部空间，继而阻止微小 snapshot、
源码准入和 matcher；再全量重跑 106 文件也会重复 86 次 prepare。原报告及预算失败全部保留。

**Proposed，尚未实现／运行**：使用显式 parent-report／artifact 限定引用增量继续，
复用已审计 86 snapshots／79 图与原 matcher witness，只处理 20＋7。
具体门槛、drift 处理与预算策略见
[docs/DEPENDENCY_SOURCES.md](../../../docs/DEPENDENCY_SOURCES.md#7-最小增量继续方案proposed未运行)。
SQLite 归档接线可以并行进行；当前独立 artifact 足以继续必要源码准入，不以新存储实现为前提。
