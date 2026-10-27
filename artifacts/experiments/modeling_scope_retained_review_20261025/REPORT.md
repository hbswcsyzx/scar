独立终态审查通过其限定范围。原门为 `PUBLISHED_MEMBERSHIP_ONLY`、exit 0；aggregate 与 whole-program model 仍为 `OPEN`，不是完整建模通过。

以原 `attempt01/result.json` 的准确根收据核实 manifest：244,461 bytes，SHA256 `966374f50fff220dd6016e053b409e57127384f863e1e0c154a36821f39685cd`。记录 schema 2、transport schema 2。公共 reader 解码并重新核对整个 typed ScopeRevision `scope_revision:1ae1c9387ba076a51170c9a60e0a0e5c63ef611c8e5fcc3320d6b0f6a3c03e73`；其中绑定的六个非空 catalog 输入根和四个 producer 源码均与当前保存字节/SHA一致。invocation report 的 source inventory 绑定也一致。

全部 637 个保存 chunk（534 entries、103 index）逐一核了 stored bytes/SHA，合计 126,695,719 bytes，零不符；实际目录文件集合与 manifest 完全相同。全量 decoded 4,268,542,417 bytes 仅保留为 manifest 声明，未重新解压或验证全部行语义。manifest 的数据行与索引行分母均为 102,661，其中成员 102,655、六个 collection debt。

| 域 | declared | enumerated | 状态 |
| --- | ---: | ---: | --- |
| SOURCE_DEFINITIONS | 2,217 | 2,217 | ENUMERATED；observation UNKNOWN |
| OBSERVED_PYTHON_CALLS | 100,438 | 100,438 | ENUMERATED；observation UNKNOWN |
| SOURCE_CONSTRUCTS | 122,323 | 0 | DECLARED，debt |
| DISPATCH_ATTEMPTS | 39,796 | 0 | DECLARED，debt |
| NATIVE_ACTIVITIES | 461,242 | 0 | DECLARED，debt |
| OS_INTERFACES | 1,067,768 | 0 | DECLARED，debt |
| OS_RESOURCES | 38,307 | 0 | DECLARED，debt |
| PHYSICAL_OBJECTS_AND_RESOURCES | 225,630 | 0 | DECLARED，debt |

2,217 对照原 source header，100,438 对照原 invocation report 的两个独立计数字段。六个其余域均保留 cursor、gap、零枚举及 UNKNOWN observation，未提升成已建模。

原 result 的十个 sample ID 均通过公共 `ScopePartitions.query` 返回精确 obligation、subject、scope revision；每次恰为 1 index + 1 data chunk，无 raw replay。source/call 样本中的 retained frontier 可查，六个 collection 的语义轴仍 OPEN。重新计算了样本 obligation ID；collection 样本另与各域原 denominator collection locator 核对，首末 call 的原行号为 1 / 100,438。十个样本不是全行语义验证。

source 补充检查按 `InputResolver.rows` 的 definition→body-header→status 路径自动选样；只解了 source shard 0 与第一个本地修订 shard 140。选中的 `LOWERED_WITH_GAPS` 为 shard 0 definition/body 1，`UNSUPPORTED` 为 shard 0 definition/body 0。两者公共查询的 `retained_gaps` 与准确原 metadata 的 `ORIGINAL_BODY_<status>`、`SOURCE_BODY`、`#/file/bodies/<ordinal>` 和原 reason（512 字符界限）完全一致。没有打开 body graph/checkpoint；NOT_ATTEMPTED 未另抽样。

原门成本为 worker wall 694.388 秒、peak RSS 114,576 KiB。此次校验主体（imports 后计时）1.430 秒，SELF peak RSS 报告 1,073,056 KiB；未作独立 RSS 采样。计量的物理读总量 130,228,323 bytes，包含全 chunk hash、输入根/源码与查询重读；其中 12 次查询合计读取 12 index + 12 data chunks，stored 1,566,399 bytes、decoded 53,831,287 bytes（均含重复读取）。两个 source shard stored 88,018、decoded 1,339,589 bytes；另有 source header stored 1,324、decoded 2,784 bytes。先前小源码/根 metadata 探查未计入这次校验主体成本。

本审查未运行 producer、target、compile 或大门；未读原 capture raw、100,438 invocation stream、native/OS 数据 chunks，未重解全量 ledger。原门的 raw/target 零执行结论由其终态结果和入口代码支持，本审查没有新增独立运行时观测。

复核入口与完整小收据：[review.py](review.py)、[receipt.json](receipt.json)。收据保存十个准确 subject、查询读取预算及两个 source 状态样本的 retained gaps。
