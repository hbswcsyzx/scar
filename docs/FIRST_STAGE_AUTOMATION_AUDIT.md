# 第一阶段自动化审计：连接缺口，而非继续堆组件

日期：2026-10-20。方法：主代理与两个独立只读审查，未运行新的目标程序。
本报告定位实施起点，不是第一阶段验收报告。

## 1. 设计与实现必须分开

审计未找到必须增加第六种规范结构的具体反例，但这不证明五类实体已经完备。
`WHOLE_PROGRAM_MODEL.md`、`ir/program/resources.py`、`ir/execution/resources.py`
和 `ir/v2/values.py` 能表达程序结构、资源身份、逻辑版本与物理表示；当前主要
问题是自动生成与对应。完整身份清单与第一阶段条件见
[当前合同](FIRST_STAGE_MODEL_CONTRACT.md)。

| 当前代码证据 | 真实含义 | 不能声称 |
| --- | --- | --- |
| `analysis/program_inventory.py:636` 及 `call_demand.py` | 原入口与 trace 可以自动发现/调度局部 body | 自动化完全不存在，或全程序已经恢复 |
| `analysis/program_inventory.py:141` | summary 明确 whole_program_graph/fine_state_effects 为 false | 几千通过测试已建立整个 LeWM 模型 |
| `analysis/program_lowering.py:617` | 默认 frame profile 拒绝许多语句/接口 | 额外协议声明已自动解决 source lowering |
| `analysis/structured_lowering.py:443` | 存在独立有限循环/local-binding 前端 | 它已自动用于 inventory，或支持所有语言构造 |
| `sitecustomize.py:6` | calls-only 和旧 Torch/profiler 注入是互斥分支 | 同次真实运行已提供两链精确对应 |
| `trace/normalize_v2.py:483` | 输出 v2 bundle/stubs，仍有 correspondence 缺口 | 已自动产出完整 canonical ExecutionModel |
| `trace/resources.py:20` | process CPU 与设备总 utilization/memory 抽样 | 已恢复资源实例、活动归属与完整生命周期 |

## 2. 三项实际阻塞

1. **源码结构自动恢复。** 入口包含动态 `compile/exec`；模块初始化、class/
   closure、属性/下标写、循环与上下文不能只保留无连接清单。原 source inventory
   已保留各 atom 的 owner/phase，不能称整个源码归属被丢弃。真正丢失的是 typed
   overlay：两个 lowerer 遇单个 `_Unsupported` 后清空整个 body 的图/来源链接。
   应复用已有 source CFG，保留成功片段与准确边界；不能把未知 try/with/finally
   压成一个会普通落下的 INVOKE，也不能让未知写之后沿用旧 local binding。
   保留片段不能让未知构造自动变成“已展开”。
2. **同一运行的证据适配。** call/operand 报告与 v2 profiler 报告没有自动组成
   canonical ProgramModel/ExecutionModel。先固定共享 run/process/code/activation
   命名和有序端口映射，再复用 ETO/Kineto，不能按事件名称/时间邻近猜配。
3. **资源与外部输出闭包。** 实际文件、mmap、pipe、编码器、线程/进程、设备和
   allocation/stream/ready 必须连接到使用操作与数据来源。已有同 owner CHILD
   requirement 不等于已恢复跨 owner 的物理拓扑；已有 utilization 不等于该绑定。

## 3. 外部压力范围核实

原命令明确 `policy=pusht/weights.pt`。不能用配置默认 random policy 代替。
`le-wm/run_inference.py:70` 动态运行 `eval.py`；`eval.py:87` 起加载模型并调用
规划/环境，末尾写结果。`stable_worldmodel/plot/video_utils.py:8` 的视频路径
含 imageio/libx264 writer、逐帧写和 close；这些是资源和输出观察根，不能只建 GPU 图。

旧真实采集 `windows_lewm/trace/run.json` 退出码 0；operand sidecar 的 945 gaps
与零 drop 是不同指标，不能混称“完整采集”。旧库存 151 文件/2,217 定义，50
带缺口 body/206 不支持/1,961 未尝试，属于历史事实。本轮 current-code 重建
使用新目录，不能把旧数字重新包装为新结果。

## 4. 继续实施的选择准则

每次改动先指出它修复哪个原入口的必需 obligation，然后自动重建同一分母，
对比实际断点是否消失。优先已有前端/profile、已有 provider 和共享对应；仅做
必要的集成与通用规则。未证明阻塞真实路径的 F20 等协议细化暂不开展。

S1/S2/S3/S4 都属于本次第一阶段内部检查点；不新增优化任务。S4 未通过，
就不称完成，不向用户报新的 LeWM 加速比。

### 4.1 同次采集的具体约束

- call recorder 仍使用 `sys.setprofile`；只有 operand sidecar 采用 monitoring。
  不能直接再调用 `inject.install()`；sidecar 会检测 hook 改动并停止记录。
- 一个 recorder 持有 Python profile hook，现有 monitoring sidecar 继续使用，
  单个 torch.profiler/ETO 共享采集生命周期。复用 provider，不新增 Tensor tracer。
- ETO 属于 EXECUTION_EVIDENCE；不能直接用只接受 DEFINITION_GRAPH 的
  ProviderBinding 将其节点绑定成原静态定义。先用 OBSERVATION_SCOPE，若生成
  observed-path 子区域，须明确其独立表示、条件与来源对应。
- ETO inputs/outputs 保留有序嵌套槽；tensor/storage ID 不等于 LogicalVersion。
  `rf_id` 与 Kineto 只在同窗口且唯一等约束满足时连接；缺少 Python→Torch 的
  共同 ID 时，需要准确 span 对应，不能用时间或名字猜测。
- `with_stack=False` 的现 profiler 不能直接宣称已有完整 memory DataFlowGraph；
  本机对应接口另有采集 flags 要求。利用率抽样仍不能替代 allocation 生命周期。

对应生产接入按“同次采集共存→原字段保真导入→规范端口/资源绑定”执行，每项
都检查丢失、预算和未解析关系。此为设计审计，尚未实现新适配器或新的真实 run。
