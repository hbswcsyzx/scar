# 建模复用决策：范围有限的只读复审

2026-10-16；审查基线 `78c5fda` 及当前文档工作区。
范围：`docs/MODELING_REUSE_DECISION.md`、`TOOLING_SURVEY.md` §6、`STATUS.md` 顶部、
`WHOLE_PROGRAM_MODEL_PLAN.md` §3。只读对照既有产品、本机 Torch 源码和三份原审查。
未修改产品，未运行 import/capture/test、采集或 LeWM；仅新增本报告。

**结论：通过本次文档复审；未发现需要修订的实质问题。**
该结论仅覆盖事实表述及实施/阶段边界，不是 M0–M2、adapter 或模型完成验收。

## 核对结果

1. **当前能力没有被升级。** 决策 §1 将规格、机器接口、采集、自动图及化简分开；
   `MODELING_REUSE_DECISION.md:17–20` 明确冻结回归仅适用于已实现范围、cleanup 是待实施
   规格且 schema 仍 v8。与 `scar/ir/program/codec.py:16`、`model.py:679`、
   `control.py:43` 一致；当前仍无 C1 六表或 SAVED_HANDLED_CONTEXT 产品类型。

2. **五实体与关系被标为设计职责。** 决策 `:26–27` 先说明 owner/selector、动态资源、
   逻辑值对应未全部落实，因此后续实体例子、递归区域与全过程图没有冒充自动恢复结果。
   `:104` 明示全过程只是设计检验；§4 是表示分工，没有把已有部分 v2 图说成闭合整图。

3. **已接与未接工具分清。** 决策 `:12–14`、`:63–74` 以及 STATUS `:7–16` 保留
   profiler/Kineto/Python monitoring 已集成、FX/Export/ETO adapter 未实施的边界。
   TorchLens 是候选，torchview 是展示/交叉检查；没有声称本轮新安装、兼容性、采集或
   开销验收。MLIR/xDSL/CodeQL 均未被写为已经迁移或通过本机试验。

4. **新增 collector 局限有代码依据。** survey `:227–232` 的名字尾缀猜写、全部
   positional Tensor、kwargs/out 缺失及失败路径，对应 `trace/session.py:354–366`、
   `trace/inject.py:85–97,166–180`。文档描述的是这条路径，没有宣称所有 collector
   都用同一方法。schema 替代被正确标为 Proposed，没有把 schema 当外部效果完备证明。

5. **本机 Torch 来源可核对。** `_python_dispatch.py:773,783` 确实读取
   `alias_info.is_write`；`_dynamo/source.py:147,304,337,694,738` 有所列来源类；
   `_functorch/_aot_autograd/descriptors.py` 确实含 mutation、gradient、Philox、token
   等角色。survey `:240–246` 明示这些是版本限定的源码观察，不是生产 adapter 或
   可用性/开销实测；2.14 官方链接没有被写成本机 2.13 行为验收。

6. **没有重新引入完整编译器前提。** 决策 `:127–130` 明确先补组合缺口、复用原生
   artifact，不要求先写完整 Python 编译器或库内部。计划 `:45,54–56,65–68` 将
   source lowering 放在 M3，当前阶段限定接口/协议。保留 M2 的完整构造规则分母，
   不等于要求自己实现整套 source lowering。

7. **保留“第一阶段完成先停”。** 决策 `:131–135` 将停下来讲解放在后续最小导入
   闭环之前；计划 `:46,66–68` 也保留停止点。新顺序没有授权越过停止点直接采集、
   接 adapter、运行 LeWM 或开展优化。M0–M2 未关闭、无可信自动变换/加速比的状态一致。

无需产品修订或扩大本轮验证。后续执行仍须按各阶段限定范围验收；本报告不新增实施任务。
