# N2.entry 自主验收：运行来源到自动源码/定义图

日期：2026-10-15。状态：**PASS_BOUNDED_RUNTIME_SOURCE_BRIDGE**。
专项、全仓回归和原外部入口的当前源码/trace 严格重放均已通过。

冻结实现：`b886e406380576e1b847df46e4c45a6baf23867a`。
源码/测试/脚本/gate 联合 SHA256：
`8609a8631db70f4bb810dd3f17d649d4117d8afb57dc04866a7182eb1a4d6790`。
本门计划：[N2_ENTRY_PLAN.md](N2_ENTRY_PLAN.md)。

## 1. 本门实际做了什么

输入是普通 Python 源码入口、项目文件边界和已有真实 trace。不输入动态文件
列表、函数列表或手工 workload IR。SCAR 自动完成：

```text
有摘要的 JSONL 流 -> CodeID/process 观察 -> 来源候选/边界
  -> 与静态 import 共享发现预算 -> 当前源码快照
  -> 精确离线代码复现或明确不匹配 -> 持久化定义索引
  -> 可用时连接 DefinitionInventory / body Region
```

观察范围不代替静态候选范围；未执行的 import 分支仍保留。源码文件名只用于
选择候选，不证明旧运行使用了当前文件。code object 精确复现不证明实际
callee、closure、参数值、effects 或优化合法性。全部变化属于通用分析连接，
没有按 LeWM/包/函数/变量名写规则，没有新 detector/backend。

## 2. 冻结测试与开发失败

| 检查 | 实测结果 |
| --- | --- |
| mapped gate `gates/n2_entry.json` | **429 passed**，47.662 秒 |
| 全仓 `pytest -q` | **1,477 passed**，2 条原有 warning，无失败/跳过；wrapper 121.353 秒 |
| 冻结及回归后的实现 fingerprint | 相同；启动测试时工作树干净 |
| 公共接口 | `inventory-program --trace` 与 `check-inventory` |
| 旧纯源码 v1 路径 | 保持原 envelope/排序；无 trace 不产生 v2 runtime_scope |

通用端到端 fixture 使用真实有限子进程和已有 TraceSession：启动器动态执行
没有静态 import 边的源码，动态源码再 import helper；另有未执行静态分支。
实际输入经公共 API 自动发现、绑定、构图、压缩保存并重放，无手工补图。
多次调用共享编译缓存；观察定义在同一文件内优先获得 body 预算。

独立测试暴露：读取器最初只查顶层 PID，而已有 collector 的 process_id 在
metadata，导致两个进程的同一代码组错误合并。开发两次运行分别是 53/58 项
通过、1 项失败；修复后相关 60 项通过。现在对 metadata 和顶层 PID 的类型、
值和冲突进行检查，不将非法身份合为未知进程。失败原始 XML 与修复后证据
均 gzip 保存，并核对解压 SHA256。

另一轮审查发现空 module initializer 的定义引用需要落地；已加入 typed
definition_index 及悬空引用/错误 core root/源码失败失效反例。来源索引不会
凭观察文件名取得 callee/effect 权限。独立 agent 的全部写入已在冻结前完成。

## 3. 原始外部 LeWM 自动重建

输入：原 `le-wm/run_inference.py`、原项目边界、文件预算 256、body 尝试预算
256、构造操作预算 10,000，以及归档的
`lewm_resource_sampled_c_call_20260917/events.jsonl.gz`。
没有提供动态文件/函数名单；本次不执行 LeWM，不修改它。

归档逻辑 trace 有 **45,894** 条记录、解压原始字节 **72,574,698**，SHA256 为
`f2c0c169aa01524d9ab021d5279101e01097a2e909cddd10286a63ec44e98d6f`。
这是历史采集证据，不是本次 workload 性能或经过认证的执行声明。

| 指标 | 纯源码 N2.b0 | 加入运行来源 N2.entry |
| --- | ---: | ---: |
| 自动发现文件 | 143 | **151** |
| 定义 / 源码调用 | 2,122 / 9,674 | **2,217 / 10,235** |
| 有核心来源对应的 atoms | 163 | **920** |
| 带缺口的 body 图 | 16 | **41** |
| unsupported body 尝试 | 240 | **215** |
| 核心操作 | 215 | **1,035** |
| analysis wall | 401.595 秒 | **402.571 秒** |
| analysis peak RSS | 293,052 KiB | **336,224 KiB** |
| strict replay wall | 405.052 秒 | **423.913 秒** |
| strict replay peak RSS | 689,104 KiB | **785,256 KiB** |

新增 8 个文件，旧发现文件未移除；其中 `eval.py` 来自动态执行证据，其依赖
使用同一发现队列自动展开。文件列表和逐定义阻断见机器生成 comparison。
新增源码使覆盖分母由 115,723 变为 122,323，不能将绝对数量增长当依赖完整度。

运行来源有 **285** 个 code/process 组，读取 issue=0；262 组为项目内 Python
候选，23 组在边界外。252 次独立编译尝试复用到各代码组：

- VERIFIED 34：精确 code witness 且唯一源定义；
- MISMATCH 222：当前默认编译假设下未复现，不能据此断言源码已改变；
- MISSING 6：未建立完整定义连接，其中 code-only witness 仍可保留；
- OUT_OF_SCOPE 23。

总计 40 组有 code-only witness。旧 trace 未完整记录编译配置/原始 filename；
默认仅尝试本机 Python、flags=0、optimize=0/1/2。没有归一化原 marshal 摘要来
提高匹配数，也没有把 filename/qualname 候选升级为已验证代码。

## 4. 不能忽略的实际剩余断点

256 个持久化来源候选定义只产生 **1 个 core Region 连接**：

| body/index 状态 | 数量与含义 |
| --- | --- |
| LOWERED_WITH_GAPS | 1；来源结构对应，仍非优化证明 |
| UNSUPPORTED | 8；有定位明确的 body 阻断 |
| NOT_ATTEMPTED / budget | 27；全局 body 预算耗尽 |
| NOT_ATTEMPTED / scope interface | 137；class/lambda/comprehension 等接口不支持 |
| NO_BODY_INVENTORY | 83；例如 module initializer，不是普通函数 body |

这张表不能被“41 个 body 成功”替代；多数成功 body 并未形成运行来源连接。
当前每文件内部优先观察定义，但全局仍先处理完一个文件；早期文件的其余
定义会消耗后续文件需求的预算。这是需要改进的调度问题。

215 个失败尝试的首个阻断中，111 个为 defaults/decorator/async/variadic/
keyword-only 接口，17 个为 closure/cell，其他包括局部写接口、BoolOp、循环、
raise、容器/推导式等。数字只代表当前首先遇到的阻断，不是全部缺失功能。
源码/定义数量、观察次数和结构合法均不能授予 cache、删除或上移权限。

当前 body 仍使用粗 world；按文件生成的 world ID 不证明状态独立。未闭合
参数绑定、跨文件状态映射、alias/写入、循环版本和消费者之前，不能拼接后
宣称有完整依赖闭包。下一门详见 [N2_SIGNATURE_PLAN.md](N2_SIGNATURE_PLAN.md)：
全局调度 -> body/formal 与定义/绑定分离 -> 循环 -> 状态及调用组合 -> 子图指导。

## 5. 外部重放与归档

严格重放 exit=0，自动报告完全一致；所有 151 个已读源码、trace、外部 HEAD/
干净状态和实现 fingerprint 前后均不变，没有文件准备失败。LeWM 保持
`f70fed80288462ca4d006cb3607ec6da6eaa851f`。机器汇总
`n2-entry-acceptance.json` 重新核对三个冻结 receipt、外部版本和全部证据文件
SHA256。本门 E1–E6 有限验收通过；不接受完整父 N2。报告路径：

- `artifacts/reports/gates/n2-entry-verified.json`：独立标准与全部测试；
- `n2-entry-full-regression.json` / `.xml.gz`：全仓冻结运行与摘要；
- `n2-entry-lewm-inventory.json.gz`：实际自动构图清单；
- `n2-entry-lewm-comparison.json`：新增来源及所有观察定义阻断；
- `n2-entry-lewm-receipt.json`：原始命令、时间、哈希与外部不变核对；
- `n2-entry-source-pressure.py` / `n2-entry-compare.py`：可重现分析和比较脚本。

代码/报告分提交保存，压缩清单约 6.60 MiB；没有展开或复制历史大型 trace，
没有保存新的 Tensor 内容。开发失败 XML 归档均经过解压原始 SHA256 核对。

当前无新 LeWM transform、clean A/B、正确性闭环或已验证加速比。本文统计的
402.571 秒是 SCAR 分析成本。完整自动 LeWM 模型及父 N2 门仍未完成。
