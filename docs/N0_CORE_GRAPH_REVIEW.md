# N0：核心程序图设计审查记录

日期：2026-10-13。设计提交：`22d8bb8`。
结论：**有限设计审查通过；未证明四类分类完备。统一语义核心尚未实现，N1—N4 未验收。**

决策文件：[CORE_GRAPH_MODEL.md](CORE_GRAPH_MODEL.md)。机器记录：
`artifacts/reports/reviews/n0-core-program-graph.json`。

## 审查内容与依据

两个独立审查分别从必要语义与当前代码出发，主代理逐项核对并修正文档。
本轮选择 Operation、Value、StateLocation、Region 四类顶层节点；状态版本
是强类型 Value，输入输出是区域接口角色，控制与效果有明确依赖语义。

当前 SG 的端点清单有 operation、slot、control 等，却没有统一状态位置和
状态版本；有序计算—值依赖主要在可选 source overlay 中。state_slots 的
引用搜索未发现前端/normalizer 的填充路径。原先将窄引用采集作为语义核心
前置的顺序不合适，本轮调整为先实现完整小程序的统一模型和依赖查询。

## 已修复的设计问题

1. ReferenceValue 保留独立 referent identity；同 location/view 不代表同对象。
2. 引用元数据读取依赖状态；引用稳定不保证 shape/stride/selector 稳定。
3. 静态 Value 定义与动态 occurrence 分开，循环节点相同不代表运行版本不变。
4. 常量事实不改 producer；显式图替换才建立新的定义和 use 改接。
5. overwrite kill 不删除必要顺序；stdout 等效果域保留完整交互历史。
6. use 必须在对应路径上可用，分支/异常/循环合流保留逐前驱绑定。
7. N2 源码范围、N3 正例的源码/规则/合同来源明确，不以名称或 pure=True 审批。

两名审查者在修正后只读复核，确认该轮已列出的必修项得到处理。通过的是
已审查约束的一致性和可实施顺序，不是完整性证明，也不证明任意程序已可化简。
三个程序例子目前是设计压力案例，
尚未执行为 N1—N3 验收 fixture。

用户追问节点种类后，进一步核对了 LeWM CEM、policy、model、eval 和梯度
solver 源码。四类只是元模型家族，具体操作语义仍有大量未实现项。详见
[LEWM_SEMANTIC_COVERAGE_REVIEW.md](LEWM_SEMANTIC_COVERAGE_REVIEW.md)。机器记录
保留原 `22d8bb8` 审计快照及其哈希；本段是其后追加的范围澄清，不把原审计
改写成对完整 LeWM 的覆盖验收。

## 代码与版本检查

- main 的 `scar/`、`tests/`、`scripts/` 相对已接受的 `d5fa963` 无代码变化。
- LeWM 工作区仍干净；本轮没有执行新的 LeWM profiling 或改写。
- 不因文档修改重跑整仓测试；既有 1,064 项通过仍属于原验收范围。
- 未完成采集工作保存在已推送的 `wip/reference-evidence-20261013`，末提交
  `2e08b4c`，没有合并 main。冻结代码 `0b90f38` 的组件复查 80 passed，
  集成复查 1 failed，原始 XML 和失败原因在该分支；没有将其标为通过。

## 下一步验收

先执行 N1：四类节点、强类型值变体、状态位置、UseID 和区域接口，配合一个
包含输入、分支、状态读写、返回与外部效果的完整小程序 IR。必须可以沿接口
追踪依赖，并拒绝未定义使用、错版本、错误 alias 和丢失出口等反例。

再逐门接前端、依赖闭包/子图替换指导与运行证据。开发代理自行验收、记录和
提交，不让用户承担审批。当前没有已选 LeWM 变换或已验证加速比。
