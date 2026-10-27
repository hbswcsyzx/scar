# R3.2：Q 与原执行依赖组合验收

日期：2026-10-18。实施前基线 `f0dbbd478095b07a684fe4d35ba3b53be20ed17c`。
依据：[计划](M1_PIPELINE_COMPOSITION_PLAN.md)、[API](M1_PIPELINE_COMPOSITION_API.md)。
本门完成限定组合接口，**没有完成完整 M0–M2 或自动 LeWM 建图**。

## 1. 已实现的连接

- `CompositionScope` 准确指定合同及 run/activation/operation 分析范围；它是查询
  输入，不新增执行事实、wire 表或节点类型。没有范围时为 UNRESOLVED。
- 从原合同 required_outputs/facets 建立期望分母，再与原 requirement/root/read
  对账。整行删除不消除义务；另一次调用的 root 不自动抵消本次义务。facet 缺端点
  目标/基数，始终保留未解释；输出槽声明相容不证明 runtime 对应。
- 全部原 ProgramGraph/ExecutionModel 与计数始终保留；组合查询派生原有序 Use、
  producer、state、actual CFG、typed completion/resumption/drive 与 call 路由。
  未达 root 的操作不因此被判死；没有 source_use 的 marker 不成为无依赖。
- 原 read 的 P/V、实际产出前缀、来源、work/order/lifetime 同页回查。独立来源
  EEG edges 不依赖 ContentRead 才列账。RAISE、terminal、quiescence、borrow release、
  handle end、retirement 分开；标量/引用观察根不虚构 Mat 或物理读取。
- 一份 fresh external context 重查原 11 阶段关联，复用 canonical/call 基础。
  派生查询共享一个预算；内部 P/V 不反复 replay 或 detach，顶层复制一次。
  Q 阶段预算是普通快照，顶层是总账；原公开 P/V 保留布局与默认 4096。

这些是已提供模型的结构与证据组合，不证明来源完整、跨调用值身份、native
可见性、端点完成或可变换。原五类实体不变，没有新的 detector/backend/lowerer。

## 2. 自主验收数据

| 项目 | 真实结果 |
| --- | --- |
| 组件 | 677 项 / 13 条件，全部通过；20.8s。 |
| 冻结实现 | `31bf2e4ef8d3cd6df5c0387d5c27f571b5643d41`，干净工作树。 |
| 单次全仓 | 5,011 passed；0 failed/error/skipped；4 warnings。 |
| 时间与内存 | 外部 486.67018712777644s；pytest 484.42s；最大 RSS 1,028,760 KiB。 |
| 源码 | 567 个登记文件前后相同；合并 SHA `f24eb1400a29300bcb512d95721df8c7127932faa56b67194df931c0b88adbd4`。 |
| 保留情况 | 原 4,951 case ID 全保留；新增 60。旧 555 源文件无删除，550 不变、5 扩展；新增 12。 |
| fixtures | 原 68 个 hash 全保留；新增 1，当前 69 个前后相同。 |
| 环境 | `conda activate lewm`；Python 3.14.7、pytest 9.1.1、Torch 2.13.0+cu132、NumPy 2.5.2；未升级依赖。 |
| 保护与清理 | LeWM `f70fed8`、主工作区 `84f165f` 前后均干净；仅删除已退出子进程的 owned basetemp。 |

全仓只运行一次；运行期间没有源码/文档编辑或另启测试。测试时间是验收成本，
不是 clean workload benchmark。没有新增 LeWM profiling、优化或加速比。

新增 60 cases：Q scopes 10、原路由 10、公开边界 16、刷新/预算 16、跨层集成 8。
集成反例覆盖 actual 左段与 pending 右段、4/8-byte 前缀、host RAISE 后 work pending、
资源生命周期区别、两次函数调用、budget=1 的完整 inventory，以及 scalar/ref root。
这些是通用声明模型验证，不冒充真实程序的自动恢复。

## 3. 失败与独立复审

原失败完整保留在
`artifacts/experiments/b1_call_operands/model_pipeline_composition/`：

- routes 初次测试给 CALL 加了未绑定 Use，原 validator 正确拒绝；改用已有双 Use。
- Q scopes 初次导入错误及 output/facet 断言错误、各次真实收尾均见
  `scopes/history-receipt.md`；首次未采集的 hash/可靠 exit 不补造。
- public boundary 早期测试试图修改 frozen tuple、留下已删除 read 的 support FK、
  使用错误的 model 字段；原日志保留，最后组件验收使用修正的有效反例。
- 独立源审发现 source-only EEG 未展开与多 requirement 预算游标缺口。分别修复为
  原 edge 独立账本，以及准确 requirement ID/ordinal、当前组剩余 roots 与后续组数。
  原 OPEN 报告与窄 closure 均保留，不把源推断冒充修复前实测失败。
- 三份独立复审分别检查组合/复制、Q 分母和 fresh context/P/V。私有 shared helpers
  使用可信内部预算对象；不声称防御任意 Python 调用方改写控制器。公开入口自建
  准确预算，不能通过外部传入控制器重置预算。此范围记录不扩张优化权限。

## 4. 尚未关闭与下一门

完整 R3.3 仍需 load→materialize→compute→consume→write→flush/close 通用模型与
有界 OS 见证。具体 endpoint read/flush/persist、native/coherence 与 whole-work
来源对应仍未解释；缺采集、缺合同适用性或原生边界不能写成无效果。

随后继续 selector/literal、C2/D3 等接口与 M2 全构造分母。自动 source/runtime
恢复属于后续适配阶段；当前没有完整 LeWM 自动抽象图或可信新变换。完整 M0–M2
完成后按用户要求停止讲解；本门不提前关闭第一阶段。

归档包含精确命令、环境、JUnit、逐 case 身份、源码/fixture hash、保护目录、
旧失败与 reviews。`check_archive.py` 是只读核验，启动零测试/工作负载。
