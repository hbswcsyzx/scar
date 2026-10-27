# Retained source/call membership 实际结果

2026-10-25。root 持有 session11385，实际完成 exit0；launcher 为
`EXIT0_MEMBERSHIP_OPEN`，worker 为 `PUBLISHED_MEMBERSHIP_ONLY`。这次完成的是保留档中
2217 个 source 定义及 100438 次 source invocation 的完整原成员枚举与归属索引，共
102655 个成员；另有六个集合欠账，合计 102661 条 mandatory obligation。
**全程序模型与 ledger aggregate 均为 OPEN。** PUBLISHED 只代表本 scope 的受限账本发布。

原收据：[result.json](attempt01/result.json)、[launch-result.json](attempt01/launch-result.json)、
[GNU-time](attempt01/gnu-time.txt)、[ledger manifest](attempt01/ledger/manifest.json)。本报告
读取这些 small metadata，不重扫 source/call、chunks 或 raw，也不另开一次门。

## 准确范围与证据

本门使用 [typed catalog](catalog.json) 和 root 审核的 [freeze](freeze.json)，其 SHA 为
`09949422bdf67dae6f4d9f24772a8af4b80e6745171187fec0798c72c1eb87d3`。
scope revision 为
`scope_revision:1ae1c9387ba076a51170c9a60e0a0e5c63ef611c8e5fcc3320d6b0f6a3c03e73`。
四个 producer 的初始源码版本在 manifest 中保存并终检；原文件、runner 和输入冻结史未改。

source-invocations 原输入为
`first_stage_source_revision_current_20261025/result/connections/source/report.json`，SHA
`d175012f3aab241ffeafd27c3de7a189ac55011b579f79790244d448f8573937`。
当前 source inventory 直接取其 `inventory`，为
`first_stage_source_body_revision_20261023/result/publication/manifest.json`，SHA
`97342c29aaab8460f45b67a038e3a3cee22d1781393e1f57a4d7b22e58d26505`；coordinates
直接取原 `coordinate_binding`，SHA 为
`4d266b9ea62ed0d4c25cb5606dae31dea5aeab453405f79608ab5c038f012a25`。
2217 来自原 header 的 `summary.definitions` 并经全部原数组枚举守恒；不是 lowered body/graph 数。
100438 来自报告 descriptor 并经完整 retained JSONL 遍历、decoded SHA/字节/行数核验。
同 Run 的旧 inventory/report 不能互相替代；本门没有新建事实或修复原图关系。

输入全扫描是 retained source shards 与 source-invocations archive，账本记录 input accounting
为 710234125B（stored+decoded 计费量，不能当作唯一物理 I/O 字节数）。原 raw capture reads=0，
target executions=0；没有新 LeWM episode，也没有重新运行目标。native/OS 只读所选 manifests
以保留准确集合声明；未展开其大 chunks。`native_capture_batch` 没有作为已发布 adapter 输入。
独立 source_revision_current 复核的完成或结论由其自身报告负责，本门不提前采用。

## 独立分母与欠账

| domain | declared_count | enumerated_count | enumeration | 原 collection pointer | 本次未枚举 missing_count |
| --- | ---: | ---: | --- | --- | ---: |
| `SOURCE_DEFINITIONS` | 2217 | 2217 | ENUMERATED | `#/files` | 无未枚举差额 |
| `SOURCE_CONSTRUCTS` | 122323 | 0 | DECLARED | `#/files` | 122323 |
| `OBSERVED_PYTHON_CALLS` | 100438 | 100438 | ENUMERATED | `#/invocations` | 无未枚举差额 |
| `DISPATCH_ATTEMPTS` | 39796 | 0 | DECLARED | `#/dispatch_collector_declaration` | 39796 |
| `NATIVE_ACTIVITIES` | 461242 | 0 | DECLARED | `#/graphs/evidence/tables/instances` | 461242 |
| `OS_INTERFACES` | 1067768 | 0 | DECLARED | `#/tables/observations` | 1067768 |
| `OS_RESOURCES` | 38307 | 0 | DECLARED | `#/tables` | 38307 |
| `PHYSICAL_OBJECTS_AND_RESOURCES` | 225630 | 0 | DECLARED | `#/graphs/values/tables` | 225630 |

SOURCE_DEFINITIONS 与 SOURCE_CONSTRUCTS 引当前 inventory manifest；调用引准确 report；
dispatch 引 coordinates；native/physical 引 `first_stage_joined_physical_20261023/result/native/
bundle-partitions/manifest.json`；OS 引同 Run 的
`first_stage_os_interface_work_20261023/result/interfaces/manifest.json`。完整 URI、原 schema、
双 receipt 与 collection profile 均在 manifest 的 typed denominator 内，未用裸 ID 或手填业务名单。

六个未枚举域各保留 mandatory 集合义务、`DOMAIN_UNENUMERATED` 与原 cursor。OS 38307 是
resources/handles/target_lifetime_events/processes/threads 的表项之和，不是现实所有 OS 资源
的数量；native 表计数也不证明运行活动或物理资源观察无遗漏。八域 observation_coverage
全部为 UNKNOWN；native 的 `CATALOG_RUN_BINDING_UNREVIEWED` 仍保留。本门只核原集合声明，
没有把 capture-model 的同 Run metadata 关系升级为全 provider 语义审查。

## 四轴实际资格

| 轴 | 本次结果 | manifest 中未满足 requirement 数 |
| --- | --- | ---: |
| STRUCTURAL_ATTRIBUTION | 102655 个原记录的 ORIGINAL_RECORD_MEMBERSHIP 实核；六个 collection 未枚举 | 6 |
| DEPENDENCY_CONNECTION | 所有 required_relations 仍 OPEN；未接入 accepted semantic scope 复用 | 1629202 |
| INTERNAL_EXPANSION | SOURCE_BODY/接口内部层级要求保留，未借成员归属判完成 | 102661 |
| RUNTIME_EVIDENCE | 原调用成员存在不证明 state/content/ready/effect 等语义；仍 OPEN | 102661 |

上述为 requirement 计数，不是去重缺失边数。成员归属成立不证明完整 source/body/run/provider
关系均已连接。原 argv/cwd/code-env/input/provider 范围字段仍按缺证据保留 UNKNOWN；未执行
路径、无 body、原 unsupported/not_attempted 均不会从成员分母中删除。账本不替代
ProgramGraph/ExecutionModel/ValueGraph/EvidenceGraph 的 producer/use/state/resource 事实。

result 保存十个只读查询样本：首/末 definition、首/末 invocation 和六个 collection debt。
每个样本均报告读取 1 个 index chunk、1 个 data chunk，`raw_replayed=false`，复用的是准确
retained byte/membership 资格，semantic evidence 仍 UNREVIEWED。这些是定位样本，不是
对每条义务逐查询的第二次全扫描，也没有测量逐查询延迟。

## 实际成本与编码限制

| 项目 | 实测 |
| --- | ---: |
| data+index chunks | 637 |
| stored bytes | 126695719 |
| decoded bytes | 4268542417 |
| manifest bytes | 244461 |
| worker wall seconds | 694.3875720299839 |
| launcher wall seconds | 694.529312846018 |
| GNU-time elapsed | 11:34.51 |
| GNU-time user / system seconds | 688.87 / 0.71 |
| worker SELF peak RSS KiB | 114576 |
| GNU-time maximum RSS KiB | 114576 |

GNU-time 的范围是其命令中的 conda lewm Python worker；SELF 是 worker 自报值。二者本次相同，
不能推为任意进程树或未来 producer 的内存上界。完整 locator、规则/证据引用和四轴要求在逐
义务编码中重复，decoded 体积超过 4.2GB；压缩后的约 127MB 不能掩盖编码膨胀、解析和发布
成本。本次证明当前预算内能发布和定位，不能称为高效，也不能从合成小样本或这一次耗时推算
其它域、其它运行的性能。后续可消除重复编码并保持同一原身份/验收语义；本次未修改冻结格式。

本次预算为输入200000 members、1000 files、root/shard各32MB、calls stored128MB/decoded1GB、
输入总计费2GB；输出 chunk stored/decoded各8MB且1000行、单记录1MB、总 decoded8GB/
stored1GB、200000 entries；producer1800s、外层2100s、20s heartbeat。此次没有超限或重试。
下一最小接线仍是实际发布的全39796 dispatch inventory 与准确原端点/范围资格；native、OS、
source constructs 的逐成员 producer 和全部语义审核也仍需实际完成，不能通过清空欠账获得 PASS。

## 收据身份

- result.json SHA256：`3f81280a5e595971533b794d2164ef7488e22678a1835f70ba2f0c8b1e7e3d3c`
- gnu-time.txt SHA256：`632b7e139e8dbceeaa0fa4ec09d32b0829a3bcae62704b64e0c651f6b41629d6`
- ledger manifest SHA256：`966374f50fff220dd6016e053b409e57127384f863e1e0c154a36821f39685cd`

本报告只新增 RESULT.md，并同步两份 owned 方案/实现文档的当前状态；未改生产、冻结文件或旧收据。
