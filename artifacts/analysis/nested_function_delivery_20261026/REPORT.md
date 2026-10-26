通用 nested FunctionDef 已在原档入口形成 **7 个完整 body**，均通过普通 SP5 structure reader 与独立 Source/CodeWitness 检查。机械选择的 13 项最新结果为 7 SUCCEEDED / 6 UNSUPPORTED，FAILED/PENDING 为 0；158 是成功项的历史调用权重，不增加当前 runtime bindings。原 18 成功和 main 均未改。

创建采用 **一个语义接口**：原 code 引用、globals、已求值 defaults、按序捕获的 cell identity → function reference 与正常/异常 post-world，再连接原 name/slot/cell 写入。7 个 body 共 8 个创建接口；没有新增子 body Region、执行子 body、复制第二份来源上下文或逐 MAKE/SET 主图节点。固定 bytecode 阶段只核接口合同。旧 SP5 的整文件上下文仍在，需后续共享表示解决；本次不改旧 wire。

实际过程：原 13 项首次运行 exit1 / 222.589 s，7 项被旧 environment consumer 的 source-link guard 拒绝，6 项已到具体前沿。精确新 cap + FunctionDef + definition_time declaration 分支保留旧 unknown guard。单入口先验 retry01 exit1 / 10.438 s 暴露 checker 对普通 INVOKE 状态表示的错误假设；修为原 world Use + completion-specific StateVersion，未增冗余 StateAccess。随后同一小入口 retry02 **exit0 / 14.581 s**，211 ops；通过后才补其余 6 项，**exit0 / 388.628 s，6/6 成功**。单例不重复 lower，原失败保留（21 history = 8 failed + 6 unsupported + 7 succeeded）。将 globals Ref 换作 code Ref 的单一反例被独立 checker 拒绝。

| 保留的真实前沿 | 原位置 | 项 / 历史权重 |
|---|---|---:|
| Decorator application 未实现 | `contextlib.py:304`、`hydra/main.py:81` | 2 / 3 |
| 旧 computational overlay 缺记录，非新 FunctionDef 接口 | `PIL/ImageDraw.py:581`，准确 AST 为 for-target `Name(line, Store)` | 1 / 78 |
| Delete | `torch/nn/modules/module.py:2619` | 1 / 1 |
| Comprehension scope | `PIL/ImageFont.py:914` | 1 / 1 |
| ImportFrom | `torch/serialization.py:1520` | 1 / 1 |

未扩大 decorator、type-parameter、keyword-default 或其它名称绑定 scope。实际带 defaults 的递归定义已推进到后继 Delete，但该整个 body 未成功，不能声称 defaults 全路径已普通读回。源码/CodeType 精确合同检查 11 项匹配、2 项 decorator 前沿；不等于 13 个完整 body。

全 catalog 分母仍为 817 groups / 100,438 calls / 243 candidates，仅相关入口执行 worker。成功两段 readonly 共 7 module loads / 14 complete matches，compile/live-source read 均 0（owner 原归档文本另读）；raw、source prepare、target、publication、current binding 均为 0。每段 source pins 前后不变；累计 stored+decoded I/O 未全计量，保 OPEN。动态环境、实际 callable/cell identity、formal/state/resource/lifetime 与完整建模仍 OPEN，JSON 不恢复 live owner。

7 个原 SP5 stored 共 18,770,001 B，declared decoded 168,022,930 B，保原 URI/七字段，报告阶段不再解图。[successful-programs-delta7.json](successful-programs-delta7.json) 可供正常独立准入，成本资格届时为 UNKNOWN，不重 lower。SOURCE_RECEIPTS 给出每个生产文件 `44fae988` 前像与 `57911760` 后像 SHA；精确 diff 仅 10 个生产文件。提交顺序：`db2546b6` → `d892c7d3` → `8434f243` → `57911760`。CLI 未改，新 `automatic_nested_functions=True` 为显式 AST 自动选择，默认行为不变。
