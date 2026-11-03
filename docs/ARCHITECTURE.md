# 建图架构

第一阶段只完成程序建模与建图；化简、改写和性能优化在后续阶段。
实体和关系定义见 [MODEL](MODEL.md)，实测范围与剩余缺口见 [STATUS](STATUS.md)。
LeWM 是外部 testcase；通用规则由语言协议、原端口和证据派发，不按业务名称选择。

## 六层流水线

| 层 | 输入 → 输出 | 主要代码 owner |
|---|---|---|
| 1 材料与版本 | 入口、源码/配置、依赖实现/stub/契约 → 材料身份、依赖请求、可用与缺失范围 | [static_sources.py](../scar/analysis/static_sources.py)、[static_program.py](../scar/analysis/static_program.py) |
| 2 识别与作用域/协议 | 版本化材料，经 CPython AST、符号表、编译布局 → 定义、occurrence、名称角色、调用/控制/异常协议 | [static_lexical.py](../scar/analysis/static_lexical.py)、[source_semantics_v2.py](../scar/analysis/source_semantics_v2.py)、[static_compilation.py](../scar/analysis/static_compilation.py) |
| 3 局部类型化子图 | 已识别构造与协议 → 原 Operation/Use/Value/状态/资源、typed CFG/SSA 及各完成端口 | [static_body.py](../scar/analysis/static_body.py)、[program_lowering.py](../scar/analysis/program_lowering.py)、[structured_lowering.py](../scar/analysis/structured_lowering.py) |
| 4 跨子图接线 | 原子图端口、来源路径及可选运行观察 → 实参/环境/字段/返回/异常/world 关系和实例绑定 | [program_dependencies.py](../scar/analysis/program_dependencies.py)、[static_calls.py](../scar/analysis/static_calls.py)、[observed_call_bindings.py](../scar/analysis/observed_call_bindings.py) |
| 5 条件固定点推理 | 第3/4层原关系、路径条件与效果前提 → 常量、类型、shape/dtype、身份/版本等属性及未定字段 | [program_value_analysis.py](../scar/analysis/program_value_analysis.py)、[static_namespace.py](../scar/analysis/static_namespace.py) |
| 6 发布与覆盖审计 | 原分片、ID 引用、关系和前沿 → 统一可查询图及明确覆盖范围 | [static_program.py](../scar/analysis/static_program.py)、[program_dependency_session.py](../scar/analysis/program_dependency_session.py)、[static_query.py](../scar/analysis/static_query.py) |

第5层的新事实回馈相关识别/接线任务，不重新扫描或复制无关主体。
先定位第一处缺失的是材料、识别、降低、连接还是推理，再修改对应 owner。
未支持的语法、缺实现、预算截断和实际运行字段未绑定分别记录，不能统一解释为动态未知。

## 共享子图与可组合接口

源码 AST/CST 是识别输入；执行依赖由可共享、可成环的规范图表示。
模块、函数、类体使用各自的原主体身份；未建主体保留缺口。
分支、循环和异常保留控制结构、合流及适用出口。
每个定义主体保存一份，调用与循环迭代引用它，不复制函数或按迭代展开节点。
循环视图引用原成员、header 参数、初始边和回边；它不另造一份 CFG。

接口必须保留输入、环境、正常/异常等完成的 payload 与前后状态。
数据返回、引用返回和状态返回分别连接；引用相同不证明可变内容不变。
每条关系携带原 namespace/typed ID、上下文、条件与证据；缺边不证明无依赖。
字段可以是已知、符号值、候选或 UNKNOWN；一个字段未知不能抹掉整个节点。
区域 cut 只描述输入、消费者、状态、效果与资源，不授权替换区域。

## 静态模板与动态实例

静态侧建立子图和可组合端口；动态侧观察实际选择，再对应到原端口。
运行绑定必须限定 run scope、process/thread、InvocationKey、attempt 及事件锚点。
静态 context 是接口选择；None、闭合栈和 Open 后缀有不同含义，均不是 Invocation。
同一调用点的不同 attempt、同一函数的不同激活不能因共用模板而合并。

[call_operands.py](../scar/trace/call_operands.py) 复用 CALL 事件采集；
[python_call_targets.py](../scar/trace/python_call_targets.py) 记录实际 callable，
[code_snapshot.py](../scar/trace/code_snapshot.py) 提供完整代码身份及指令位置。
采集仅保存必要原事实；静态对应、接口建图和推理在离线侧完成。
代码对应核源码版本、完整 CodeID、编译路径和原位置；名称或行号只用于筛选。
实际类对象的调用证据不证明它来自某条类声明；创建来源须另有证据。
一次观察只限定该运行事实，未覆盖路径与未知状态继续保留。

## 分片存储与统一读取

artifacts/current/static/ 是唯一当前程序模型；源码/主体/关系按分片保存。
每片附 stored/decoded SHA 与原 ID 引用，跨片引用不复制原图。
共同 reader 共享有界缓存、校核原收据；原输入稳定期间复用解码结果。
增补缺失主体保持已有主体和关系原样；旧关系仍只覆盖其原输入范围。
artifacts/current/queries/ 保存派生查询证据，不是第二份权威程序。

## 当前接通范围与下一项

已具备源码层、局部规范图、共同依赖查询、部分条件属性推理和循环边界查询。
真实 CEM 的59个CALL实例及3条函数接口已接入共同图的显式观测端口查询，静态邻接不变。
实例端口引用原点及run/Invocation/attempt/事件作用域；只有实际选中的return形成返回接口。
参数未定不丢入口/状态/返回；ABI布局保留条件备选、默认值义务和pack依赖，不猜receiver或容器身份。
对应 owner 是 [program_observed_dependencies.py](../scar/analysis/program_observed_dependencies.py)。
选中 CEM 循环的边界查询已在原预算内完成；这不证明状态、效果、资源或整个程序闭合。

下一项按真实缺口补部分参数/receiver/native接口，再补循环迭代/状态与共同推理消费。
不得把裸 context=None 的观测边注册为全局事实，也不得丢弃未执行的异常路径。
Python→native/runtime/kernel、Tensor 属性、alias/effects 与资源连接仍需按实际缺口补齐。
第一阶段只有在实体、结构、连接、属性和覆盖均经核查后才完成。
