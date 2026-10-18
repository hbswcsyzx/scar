# R3.1：动态调用与物化集合连接验收

2026-10-18。**限定接口通过；完整 R3 与第一阶段 M0–M2 未完成。**
实现提交：`881cbfbed5d13c56ea68d3adbd45d6808e092c52`。
[计划](M1_RESOURCE_COMPOSITION_PLAN.md)、[API](M1_CALL_ACTIVATION_API.md)、
[原始记录及只读 checker](../artifacts/experiments/b1_call_operands/model_resource_composition/README.md)。

## 1. 本门实际补了什么

- 新增显式 `CallActivation` 关系，将原 caller occurrence 接到准确 child
  activation、initial entry 和 actual RETURN/RAISE。不复制原 producer、Use、
  result 或 state；参数与结果从原 canonical 端口派生。
- `call_activation` / `call_entries` 可以回查不同调用、状态端口以及实际 INVOKE
  CompletionResult→landing formal。缺 entry/completion/transfer 不猜 NORMAL、
  pending 或无输出；返回视图隔离，不污染原图。
- 同步调用的所有已知 segment 线程必须相容，未知入口/线程不能豁免其它已知矛盾。
  同一同步 child 的多个已捕获终止、重复 caller/activation 和动态调用环被拒绝。
  有终止分支的静态递归可用不同 activation 表示，不等于证明真实运行终止。
- 完整 work 物化集合与该 ticket 明确声明的 read、write、Mat borrow target
  相容。PARTIAL/UNKNOWN 缺项为准确缺口；其它 ticket 或相同 URI 不补身份。
  allocation 的 Mat 依据不自动意味着借用了那个逻辑版本。

来源引用不是事件或数据身份。独立 entry FactRef 或 URI alias 不因不相等就被
判错。同 scope、callee、类型都相容的整对声明交换，未必能由结构识别；
`source_runtime_verified`、`runtime_identity_verified`、`value_identity_verified`、
`transformation_authorized` 均保持 False。调用完成不授 work terminal、quiet、free。

## 2. 自主验收结果

| 检查 | 实测结果 |
| --- | --- |
| 联合组件 | **591 cases / 8 criteria / 16.611s**；555 个源码文件哈希前后相同。 |
| 唯一干净冻结全仓 | **4,951 passed / 0 failed / 0 error / 0 skipped**；4 warnings。外部 **490.692706s**，pytest **488.50s**，峰值 **1,025,300 KiB**。 |
| 源码指纹 | `2c9bdf125adfc9c34ae9e3a9a6042317397ff1c64f4d107dc229dfd4808b6c3d`；full 前后 HEAD 为 `881cbfb` 且工作树干净。 |
| 测试守恒 | 原 **4,826** case ID 全保留，新增 **125**；原 **65** fixtures 不变，当前 **68** 全部前后相同。 |
| 源码守恒 | 原 **544** 文件全保留，530 不变、14 延伸；新增 11，共 555。 |
| 清理及保护 | full 子进程退出后只删除其独占 basetemp；原 LeWM 与 SCAR main 的 HEAD/干净状态不变。 |

新增 cases：records 14、canonical validation 9、独立边界 10、query 11、call wire 63、
物化集合 17、旧 work codec 新增 unsupported-v8 1。原 case 身份没有改名丢弃。
独立边界首跑 10/10、查询首跑 11/11；这些定向组和组件有重叠，不相加制造总数。

使用原 `conda activate lewm`：Python 3.14.7、pytest 9.1.1、PyTorch 2.13.0+cu132、
NumPy 2.5.2。**上述耗时是验收成本，不是 LeWM A/B 或加速比。** 没有升级环境。

## 3. 失败、复审与历史兼容

原物化集合检查缺失由修前 **10 failed / 7 passed** 复现；修后受影响接口联合
148 项通过，最终再由冻结组件/full 绑定准确源码。原失败不删除。夹具 smoke 首次
runner 将 core validator 的 tuple 当作 `.issues` 导致的 API 错误也保留；只修 runner。
线程及双终止问题原先属于独立源码审查推导，修后才有拒绝回归，不伪称旧实现实测。

核心、逻辑值/端点、生命周期三项设计审查，root 与其它作者的独立复审，以及
最初 OPEN、最终 closure 都保存在 archive/review。最后核对 validator
`79febd82eea06447ad045e8302a62a17164bb04771c9a2ef852b28640a127f4b`，无剩余实质阻断。
source/FK/snapshot 准备与 copying 不被宣称受某个小查询预算或总线性成本限制。

execution v7 仅用于新调用能力；v1–v6 的字节、字段及 tag 隔离保持。旧 v6 golden
由不可变 `348d182` 的 codec 和原丰富 validity fixture 独立生成：**94,738 bytes**，
SHA `fa27345cfc12c97865e975206099970e61621b0689f60967fc6445045a96a570`。
它是 codec 声明夹具，不是有效物理 execution；旧 blob/import 路径与 owned temp
清理有独立 receipt。空表迁移不证明没有发生调用，低版本拒绝静默丢弃新能力。

## 4. 下一个验收节点

R3.2 从完整显式 Q requirement 分母连接原 read/write、版本/Mat、work/order/support/
lifetime 和本门跨调用端口；删 join 不缩小义务。随后 R3.3 验收通用 load→materialize→
compute→consume→write→flush/close 组合与失败路径。端点协议未解释时明确保留
UNSUPPORTED，不由相同 FactRef 自证。完整 native/source/runtime 恢复、selector/literal、
C2/D3 等剩余构造与 M2 分母继续按原计划推进。

本门没有新增 detector、backend、lowerer、LeWM 特例、GPU profiling 或性能测量。
完整自动 LeWM 建模/化简及新的可信加速比仍未获得；不把此局部接口验收算成第一阶段完成。
