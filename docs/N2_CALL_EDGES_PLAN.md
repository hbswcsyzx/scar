# N2.call-edges：真实调用位置到程序图

2026-10-15。状态：**实施中，尚未验收**。前置 `a01d949`。
上一轮是有效进展：接口代码、冻结自验、外部证据和GitHub已更新。
完整SCAR自动化目标仍未达成，本门不增加detector/backend。

## 审计决定

旧归档有494次Python入口、480次返回和493条可配对的过滤后parent关系，但
没有caller CodeID/指令偏移/列范围。parent取过滤栈顶，可能跨过wrapper；
module_call在forward之后另行记录，不能代替frame调用。当前profile回调的
exception分支也不能证明普通Python异常退出，旧outcome:return不足以确认为
正常完成。这些是旧采集边界/缺陷，不通过改写旧证据修复。

新增轻量调用模式，真实采集callee入口时的immediate frame.f_back位置和
有界wrapper路径。稳定code结构指纹消除marshal引用布局依赖，但不证明函数
对象、defaults、closure或内容版本。多次调用共享CodeID，保留独立invocation。

## 必须交付的垂直关系

```text
真实 invocation
 → caller code + byte offset + 完整源码span
 → 源码 Call / core CALL operation / callable UseID
 → 观察到的目标code及有界frame路径
 → 可用的目标definition/body接口
 → 逐调用入口/返回引用关系与可遍历查询
```

direct caller、nearest recorded ancestor、wrapper path分开；中间层不丢弃。
同一行多个调用按指令位置区分。引用身份可跨观察比较时，仍不代表内容相等
或纯性；state、dispatch、环境和frame effects保留未证义务。

## 采集协议与限制

- `call-codes.<pid>.jsonl`：稳定code描述及指纹，不保存Tensor内容。
- `call-events.<pid>.jsonl`：逐事件index、pid/tid/invocation、入口/出口、
  caller位置、formal引用、caller局部引用、有界路径及完整性标记。
- `call-meta.<pid>.json`：范围、预算、丢弃、未知完成及未闭合调用等记录。
- weak引用使用自有epoch，不强持有应用对象；不能weakref的对象只在同一
  snapshot内比较。既不读取Tensor._version，也不把地址跨生命周期当身份。
- NORMAL须由匹配返回指令确认；异常展开/挂起/无法识别出口保留UNKNOWN或
  SUSPENDED。参数绑定失败没有callee入口，不能捏造body异常路径。
- 本模式采集启动进程及其新线程；子进程、native调用、设备完成和既有线程
  是明确范围边界。calls-only不安装Torch module patch或重度Tensor观察器。

## 自主验收门

| 门 | 验收要求 |
| --- | --- |
| E1 | stable code重编译一致，位置/常量/闭包布局变化失配；同一行两个CALL区分；无自定义repr/hash执行 |
| E2 | 实际Python采集，递归/多线程/别名/弱引用回收；绑定前失败不生成callee；异常None返回不误报NORMAL；预算明确 |
| E3 | 自动source/core/target连接，wrapper不跳过；动态调用引用查询可遍历；同code不同环境不提升为普遍绑定 |
| E4 | 两文件left/right不同对象真实调用，两条链不串线；篡改位置/代码/调用/来源/预算公共重放拒绝 |
| E5 | 冻结gate/回归、原LeWM命令真实采集、自动连接与严格重放；原仓库/环境不变；报告成本和残余缺口，提交推送 |

`return x`的源码规则应保留引用身份，同时保留退出/释放效果；当前core把它
交给opaque invoke产生新引用，仍需后续C0精化。当前运行引用查询必须明示
观测范围，不能把同一weak ref的alias路径写成一般内容依赖或批准缓存。

本门完成后继续C0–C2的captured environment、显式源码return与call完成/state
映射，再推进循环/alias/provenance。缺失字段不靠人工workload补图。

## 冻结前可信性审计

采集器/快照/独立采集反例95项通过，离线模型仍在修复，尚未冻结。
parent 必须匹配同进程/线程的实际活动区间；metadata 的可推导计数与预算
必须重算；源码参数计划不能替代实际 Python 调用约定。
尤其 `bound = object.method; bound(value)` 的运行 code 可与普通函数相同，
receiver 又可能与显式参数恰好是同一个对象。同引用不能证明参数来源。

在缺少实际约定证据时停止 actual→formal 来源推断；保留可核验的调用位置、
目标 code、当前 frame 引用及调用结果身份。E4 要求的完整跨层输入回溯因此
仍是未通过项，不以条件标签或局部链路通过替代。后续证据方案也必须自动
采集，不能要求 testcase 标注调用或手工补图。此处是模型关系所需事实的缺口，
新增重复 detector/backend 无法解决。
