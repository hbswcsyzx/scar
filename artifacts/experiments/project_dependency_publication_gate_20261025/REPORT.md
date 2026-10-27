# 同 Run project/dependency qualified publication 实测

Root 持有的三次实际 session 均退出 0：唯一 capture70391；bootstrap→dependency72518；source-entries→bindings31699。没有重复采集或拼接旧 Run。最终普通 CLI root 为 `SOURCE_ENTRY_BINDINGS_WITH_OPEN`。

| 本次原分母/结果 | 实测 |
|---|---:|
| captured code groups / invocations / exits / orphan exits | 5 / 12 / 12 / 0 |
| source-entry candidates / actual lower returns | 4 / 4 |
| SUCCEEDED / UNSUPPORTED / operation charge | 3 / 1 / 68 |
| publication bodies / ordinary qualified queries | 3 / 3 |
| project REVISE_GRAPH / dependency ADD_GRAPH | 2 / 1 |
| BODY_LINKED / SOURCE_LINKED / UNRESOLVED calls | 10 / 1 / 1 |

Project 两个原真实槽位 fi0/bi0、fi0/bi1 各关联 3 次；dependency 新 ADD 关联 4 次。机械选择全部三个成功 SP5，没有按函数名单过滤。原 12 调用中，工具导入 helper 的 Try 协议未实现，保 UNSUPPORTED/source-only 1 次；project module 无唯一函数定义，保 unresolved 1 次。bootstrap 的 body-linked6 是同 Run 基线；最终10不是新增10次调用。

schema2 显式计划绑定准确 parent composition/source inputs、原 body/root/artifact/namespace。此次真实覆盖 project REVISE 和 dependency ADD，project ADD、父 overlay 继承和拒绝过期 CAS 的运行验证未发生，保持 OPEN。原 project compiler witness 使用原 inventory 证据，entry origin v2 仅导航，未改名或冒充 origin；原 project indices、父文档和 dependency qualified namespace 保留。三个原 SP5 URI/SHA 不变，普通 AST/CodeWitness/STRUCTURE reader 独立准入，CP2 construction cost UNKNOWN；publication/binder lower、source prepare、compile、target 均 0，不恢复已失效 live owner，也不复制第二份规范图。

| 实际阶段 | 内部秒 | GNU秒 / peak RSS KiB |
|---|---:|---:|
| capture（唯一一次） | 25.301814290 | 见原 capture receipt |
| bootstrap | 104.905808553 | 106.14 / 829732 |
| dependency-sources | 11.086025422 | 11.96 / 132572 |
| source-entries | 19.457279617 | 20.37 / 188512 |
| source-entry-bindings CLI | 20.913908863 | 21.93 / 198296 |

后者四阶段为 publication6.120757s、ordinary body reader7.020119s、fresh genuine coordinates0.579264s、普通 v4 binder6.917203s。后段只消费已存同 capture 模型，未重建 native/OS。readonly publication阶段 dependency1load/2matches、project1load/4matches，compile/source-read0；source-entry 阶段 dependency2loads/3matches、project1load/4matches。前两阶段正常 witness writer 允许的编译活动与后段 readonly 资格分列在原 roots。

每个离线 CLI 外部180s；entry window16/sourcefiles6/4000ops每body/16000总ops；binding全成功程序上限16。source decode128MB/record64MB/output128MB、actual scan2MB/2048lines/1MBline/1024events、坐标64MB预算不变。原 seed metadata 64MB 等十字段只用于原 seed 解码，不能授当前 raw 权限。binder actual scan24,858B/63lines/5codes；坐标 reservations 完成20,810,882B（不是 kernel I/O）。binding planning metadata stored702,040B/decoded926,111B；final attempt post-stage672,063B。record/output是阶段后检查，累计全输入 stored+decoded 与 runtime binary freeze 仍 OPEN。

capture producer freeze9b76、实际前两消费者 afterB8ef245、后段081e96 独立保存；前B f8f88 准备但未运行，不授执行资格。Root 核后段369源前后不变。第五源 routing 的 inherited signature lookup 修正已实现并经过有限只读 code review，本门默认 v4 未启用 CALLEE_ENTRY_ROUTING；不授 v5 或 inherited-signature 动态验证，原 flat520 门保原范围，不补门。

五类 unconnected interfaces（actual-formal、control completion、environment、return、state/effects）各仍12。Python/Torch correspondence、execution/state/effect/readiness、whole program、旧 SBA v2/3 和第一阶段仍 OPEN。LeWM source858/runtime843/6699不变；本次同 CPU 新资格不迁移给旧 LeWM。

[ACTUAL_TERMINAL.json](ACTUAL_TERMINAL.json) 固定原根、精确预算、五源和原产物引用；[RETENTION.json](RETENTION.json) 与 [stage-paths.txt](stage-paths.txt) 列明保存范围。留存使用现成 metadata/receipts 和文件 stat；没有重跑消费者、重读 raw 或解图。大 capture/OS/provider 只保原 manifest receipts，完整离线重放仍需本地原依赖，不能宣称 clone 后完整自足。
