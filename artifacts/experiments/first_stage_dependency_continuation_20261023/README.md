# 外部源码建模的精确增量：27 文件实际完成并审计

日期：2026-10-23。**Observed／Verified：本次缺失 source artifacts 已补齐；第一阶段完整建模仍 OPEN。**
仅对已保存 capture 做一次离线增量和一次独立只读审计。没有执行目标程序／GPU，
没有新增 trace、测试 suite、detector 或 optimization backend。

## 1. 原档、模块与实际命令

- 原 capture：`../first_stage_lewm_dispatch_20261023/trace`，process 272038；原 program
  root `/home/zyf/AAA/le-wm` 不变，没有扩大到依赖根目录。
- 原 parent：`../first_stage_dependency_sources_20261023/result/admissions.json`，固定原文件
  SHA `fc97075aa66a92758938ad8416347d895e6b18ef0e454053fc7f9c1a7d2f0424`。
  [原预算失败及审计报告](../first_stage_dependency_sources_20261023/README.md) 全部保留。
- 本次新报告：[result/continuation.json](result/continuation.json)，原文件 SHA
  `c9ff2f87a0e90ee42297501d256d9d24aeeab60273c6172fe692c0323207173e`。
- 运行脚本：[run.sh](run.sh)／[run.py](run.py)；逐文件原进度：[progress.jsonl](progress.jsonl)。
- 基础 Git revision `49ea6f032c6a95c39801ccc0d188a2ae179ef14a`；新模块当时未提交，
  另保存精确源码副本与 SHA：
  - `dependency_continuation.snapshot.py`：`e87ddba3cca2d350890947ae80c92a43a043ca534c4a829824fdb4c5f1a2123a`；
  - 原冻结 producer `dependency_sources.snapshot.py`：`249aaacbfdaf71ad9ecbef886438dcbbd886b387104d301f11b6bce75631e283`。
- conda `lewm`、Python 3.14.7；完整版本保存在 `python-version.txt`。

执行脚本和独立审计原文件 SHA-256：

| 文件 | SHA-256 |
|---|---|
| run.sh | `28896294549a359d70ba2096b37e1d8cc4150a5363d92d782939dfacb7de33d2` |
| run.py | `597dd557ac7b6423a5674a1bda1c6d8c51f7599388e82c4b90d3142b083f0a13` |
| audit.py | `7268a3f8d79697bc5e528f38076e0af17a28a342941a439af37245aa57225efe` |
| audit.json | `8c61c34dcd0579fcfb9d28589baa11acdacbf167ddf844d972ed89f2cbc38604` |

[SHA256SUMS](SHA256SUMS) 记录脚本、日志、报告及所有新 artifact 的存储文件 SHA；
gzip 文件 SHA 与报告中的**解压 canonical SHA**分别记录，不能混用。

原结果、调用分母、source namespace、源码 ID／路径均未改写。新的 locator 用 parent
报告 SHA、directory、source-root 和原 artifact SHA 限定来源，不复制旧大图。

## 2. Observed：只补缺口，没有全量重建

| 原 cohort | 文件数 | 本轮操作 |
|---|---:|---|
| 已有 snapshot／三图 | 79 | 校验并引用；没有 prepare／compiler matching／重复导出 |
| 已有 snapshot／compiler witness，缺图 | 7 | 只重建缺图，全部匹配原 SourceContextDigest；未重复匹配 codes |
| 缺 snapshot，未匹配 | 20 | 先全部保存 snapshot，再用原 workspace／matcher 处理 |

新增 **27 次 source prepare、44 个 code groups 的 compiler matching**，并非重新处理
全部 106 文件。原 **86 snapshots／79 三图／199 compiler witnesses** 全部显式继承。
44 个新增 groups 共 21,148 次历史调用，原 matcher 全部返回 VERIFIED。

最终 106 个需求普通源码文件均已有 snapshot 与三图 artifact。
这不表示全部程序 body／state／resource／effects 已恢复；source correspondence
和完整执行模型是不同的验收项。

## 3. 完整分母与剩余 frontier

完整 raw 在运行开始重新严格扫描，结束后又由独立 stdlib-only 审计逐条复核：
**855 captured descriptors、817 entered process/code groups、100,438 enter 和 100,438 exit**。
三个原 raw 文件 SHA／bytes／lines 与 parent 完全一致，没有采样或缩小分母。

| 最终状态 | groups | entered invocations | 证明边界 |
|---|---:|---:|---|
| PROGRAM_SCOPE_RETAINED | 553 | 12,933 | 保留给原 program pipeline；不是本轮新增 source/body 证明 |
| SOURCE_VERIFIED | 243 | 86,702 | 原 compiler matcher 已匹配或显式继承旧 witness；不是 purity/body 证明 |
| UNRESOLVED | 21 | 803 | 全部为 frozen／generated 等非文件名代码，未捏造 `.py` 来源 |

剩余 unresolved 具体为 **17 个 frozen groups／469 次**与 **4 个 `<string>` groups／334 次**。
其中有 importlib、abc、collections/os 等解释器代码，以及 lambda／动态创建函数。
完整 descriptor、CodeID、首尾 anchors 与权重仍在新报告，不按包名或 observer 猜测删除。

另有 `CURRENT_SOURCE_DRIFT` **14 次**：归档的 `execution_evidence.py` 为原 capture
版本 18,375 bytes／SHA `cd64d7fbf5d2ccf079d325a3bfba547b90bf272b45f859f38d5010c871293688`；
运行时当前源码为 21,209 bytes／SHA `5655ab4131926e96bcd494bbdc1db20a77ca4d75465d58a4c014078464bbf2e5`。
历史 importing callback witness 保留且没有重编译；current guard 明确 false，未删除调用。
因此当前源码 guards **105／106 一致**，历史 source artifacts **106／106 存在**。

## 4. 真实字节数与独立预算

| 本次新 artifact | 数量 | 实际 canonical bytes | 实际 compressed bytes | 独立总上限 |
|---|---:|---:|---:|---:|
| source snapshots | 20 | 2,098,293 | 546,735 | 8,000,000 |
| 原三图包 | 27 | 591,960,596 | 68,125,461 | 1,200,000,000 |
| 合计 | 47 | 594,058,889 | 68,672,196 | 分开计费 |

最大新三图包：`torch/nn/functional.py`，**111,660,136 canonical bytes**，小于本轮
512,000,000 单 record 上限。最终 report 2,026,468 bytes，小于独立 64,000,000 上限。
没有 snapshot／graph／report／compile 预算拒绝。原预算失败没有从原档中删除或改称 unsupported。

新图原先按 79 个实际图样本估计约 644MB；现在以 **591,960,596 bytes 实测值**替代。
估计从未被当作硬上限。snapshot 精确预测 2,098,293 bytes 与实际完全一致。

其它实测：

- 新 compiler cache entries 60，预留变体 60；原 199 witnesses 未调用 matcher。
- shared scratch 累计压缩写入 30,073,053 bytes、未压缩序列化写入 114,744,481 bytes。
- 初次 guard 读取 source 共 4,273,402 bytes，含上述当前工具源码 drift 的 2,834 bytes 增长。
- 1,302 条进度事件，callback errors 为空。

## 5. 实际分析器成本

| 工作 | wall | user CPU | system CPU | 峰值 RSS | exit |
|---|---:|---:|---:|---:|---:|
| 一次完整离线增量 | 437.87 s | 432.32 s | 4.53 s | 758,140 KiB | 0 |
| 一次只读独立审计 | 38.03 s | 36.00 s | 1.96 s | 792,892 KiB | 0 |

运行进度显示：严格 raw scan 56.71s；原 493 artifacts／1,499,996,718 canonical bytes
核验 84.07s；143.26s 时全部 guards 已 checkpoint，145.30s 才开始第一次 prepare。
20 snapshots 已先全部写入，未被后续大图占用配额。

stdout、空 stderr、`time -v` 与逐文件 checkpoints 原档全部保留。这些是 SCAR 离线
分析器代价，**不是 LeWM benchmark、优化时间或加速比**。

## 6. Verified：只读审计边界

[audit.py](audit.py)／[audit.json](audit.json) 未 import SCAR，未 prepare／compile 或执行目标。

1. 核全部 **47 新 artifacts**的 canonical JSON／SHA／size、source raw bytes SHA／解码
   fingerprint、新三图各 digest、snapshot 与 qualified locator。
2. 7 个重建缺图均与原 context digests 相同；新图中有 definition 的 code links，
   DefinitionID／SourceReference／source atom 成员关系一致。
3. 原 86 snapshot／79 图 locators 与固定 parent 一致；原 199 code links 逐条完整相等，
   标为历史 witness 继承，matching_performed=false；仅 44 个原缺 witness 的 groups 新匹配。
4. 完整 raw SHA／计数／所有 entered groups 与完整 descriptors 再次一致，所有新统计
   与每条记录一致；27 个原缺图文件均只进入本轮 prepare 一次。
5. 检查实际 snapshot／graph bytes、各 record 与总预算、新源码模块保存副本 SHA。

全部通过。post-audit 没有再次解析全部原 1.5GB 图：这部分在本次增量入口开始已完整
核验。没有独立重跑 compiler 或 public source replay，不把继承 witness 冒充重编译。

## 7. 第一阶段下一条必要连接

本次已关闭“普通依赖源码因 archive 预算而缺失”的缺口。仍须继续：

- 为 21 个非文件名 code groups 建立自动来源／代码 provider；没有证据时保留准确边界。
- 将独立 source-root fragments 接入原 program／execution 关系，恢复涉及到的 body、
  actual/formal、状态与软硬件资源连接；本次没有伪造统一 inventory 或整体覆盖率。

所有 whole-program／effect／state／observer-origin／transformation authority 继续 false。
下一步仍是第一阶段建模，不能据此进入优化 backend。
