# P2 完整矩阵：开发中记录

2026-10-18；父基线 `b88670b`。本文件报告本批实现与失败，**不是完整回归验收报告**。
终态定向已过272项，组件已过657项/36标准/18.55s；注册646源指纹在两次执行
内一致。完整回归仍待下一次干净冻结运行，不能复用父基线的5,401结果。
实施顺序见 [计划](M1_GENERATOR_MATRIX_PLAN.md)，原 16 格及 F01–F24/X25–X28
保留。最近一次已接受全仓仍属于 `8a62a98` 的 5,401 项，不能归给当前工作树。

## 模型如何落实到代码

规范实体仍为 Operation / Value / StateLocation / Region / Resource。
input/output 是原有端口角色；读取、计算、传输、存储、控制与外部效果使用
原操作/状态/资源接口。下列附件只连接这些记录，不另建可修改的 producer/use
图、phase 变量或第二条状态链：

```text
原 caller actual → 原 callee formal → 原输入 Use
原 read → 原 bool result → 原 branch condition → 原 successor
    → 中途实际操作/状态变化 → final gate 输入 → 原 BodyDrive
    → 本次首出口 → 本次 adapter/helper 结果 → host 输出
```

1. `AdmissionPredicate` 区分 body 状态读取与 reference-is-None。两者不添加
   原程序没有使用的 raw/body 参数。新 variant 与本轮准确 completion 子集选择
   Program18；无二者的旧 protocol 图仍选17。
2. `admission.py` 对接该次 bool 与原 BRANCH，核对 read 的准确 state version。
   原 read 在 branch/gate 前已过期时仍允许合法历史 bool，查询报告支持缺口。
   gate 比较的是输入状态，不能强求 gate 产出的新状态等于旧状态。
3. 控制路线查询走原 CFG 到首个 gate、host exit 或谓词重执行边界。阶段与
   Start/Resume 的相容性只在未变 snapshot 下报告；不证明 opaque gate 的 native
   实现或运行时会选择哪条边，也不因此授权变换。环路和预算保留义务。
4. 输入来源保留每条静态 CALL/INVOKE ordered actual/formal recipe。独立审查
   发现：raw pack 的 operand 必须与同一 caller context 配对；不能仅按 pack
   ValueID/ordinal 合并不同 caller。现在联合 raw/原operand/独立input 三路：同
   root caller context、相容CFG选择、准确原来源均需成立；原ports全部保留。
   prepared index/flow与budget共享、reverse indexes每个ProgramIndex只建一次，
   PARTIAL/TRUNCATED不会因已有候选recipe而变完整。
5. processing/call/adapter 的 owned Use 还必须是实际调用参数；edge forward
   即使指同一个 Value，也不能冒充参数。close/异常输出必须来自本次 body
   outcome 或其明确 adapter 自有结果，不能只检查类型。

## 已有定向证据及其范围

所有原输出在 `artifacts/experiments/b1_call_operands/model_generator_matrix/`。
以下项有重叠，不累加为完整门覆盖：

| 证据 | 实际结果 | 证明范围 |
| --- | --- | --- |
| `native/attempt001` | CPython3.14.7 有界观察：40 组合、6 补充场景 | 只观察本机行为，不算 SCAR 自动恢复或 source 对应。 |
| `admission-codec/attempt003` | 56 通过 | records/codec、独立 v17 golden 与旧 family；不是完整语义矩阵。 |
| `admission-connections/attempt002` | 10 通过 | 原 read/bool/branch、owner、历史状态与预算分母。 |
| `admission-routes/attempt003` | 27 通过，包含上面 10 项 | Start/Resume、true/false、gate 输入 snapshot 与 state 变化。 |
| `close-focused/attempt006` | 15 通过 | Return(value)、GeneratorExit 消解、其他异常、非法 YIELD 与本次 host packet。 |
| `close-retry-focused/attempt004` | 5 通过 | 两个真实 close 请求、最新状态、新 cut、新 packet 与真实终结后 release。 |
| `input-origins/origin_routes/attempt005` | 6 通过 | 初版静态来源；后续复审及修复见同目录和cache收口记录。 |
| `operand-roles/attempt001` | 3 通过；期间独立来源文件发生变化 | 参数角色的局部证据；不是冻结全源码证据，最终组合要重新绑定源码。 |
| `input-origins/origin_index_reuse/attempt002` | 16 通过 | 独立原caller/CFG recipes、精确pack operand、准备索引缓存与预算。 |
| `created-running/attempt006` | 57 通过，包含原18 | 完整16格原连接及逐格错误bool/state/host，direct NEXT/SEND与THROW两路线。 |
| `reentry/attempt004` | 8 通过 | 真实body callback INVOKE、当前packet/context与继续YIELD；非动态身份。 |
| `stopiter-focused/attempt003` | 20 通过 | 内部/外来逃逸adapter与initial不wrap，真实own N/R和错包反例。 |
| `processor-reachability/attempt001` | 4 通过 | 排除终端拒绝helper，不放过可达normalizer旧packet注入。 |
| `created-close-consumers/attempt001` | 62 通过，包含原57 | 精确test site、Finish→当前None host、已知非None拒与未知内容gap。 |
| `final-focused/attempt001` | 272 通过/8.35s | 所有本批定向，统一注册源指纹稳定。 |
| `component/attempt001` | 657 通过/36标准/18.55s | 含独立16cell selectors及旧回归，统一646源指纹稳定。 |

## 失败与尚未关闭的限制

- close 初次定向 5 失败，暴露真实 result/host 连接缺口及 fixture 问题；全部
  原输出保留。后来其他异常传播反例 1 通过/2 失败，暴露旧 packet 能冒充本次
  packet；产品修复后 15 项通过。不能把先前失败删掉。
- retry 初次构造失败：原 INVOKE 强制 NORMAL+RAISE，而静态只抛异常的
  callee 只有 RAISE。后续测试使用真实 body 分支产生两个实际出口，只证明
  两次请求连接。现在按[completion amendment](M1_INVOKE_COMPLETION_AMENDMENT.md)
  补准确子集能力及独立反例；产品已改，完整验收尚待完成。
- retry 第二次漏合并第二 driver 的 PacketDefinition；补齐原记录后单正例、
  五项分别通过，未降低断言。
- route 初次 9 通过/8 失败：新测试的 alternate RETURN 缺对应 ExitPort；
  补齐原出口签名后 17 项通过。没有修改产品去容忍无签名出口。
- 后续矩阵首跑28通过/21失败：除fixture/API问题外，暴露终端reject helper
  被误当body delivery竞争来源的产品误拒；按原selected edge→Drive可达性修复，
  reachable normalizer旧packet反例仍拒绝。原输出保留，未虚增processing。
- 独立复审另发现Created-close可借同region其他site、host可返回已知非None的
  消费者缺口；现在明确绑定原test并检查实际Finish→host，未知内容保gap。
- 完整16格的声明连接及原变体现已获独立PASS_WITH_SCOPE，并经本批组件验证；
  仍不证明source/native异常类别、holder read-from/coherence、动态activation/
  对象身份。P3–P5、D3、完整M0–M2保留原分母，未完成。

本批没有新增 detector/backend、LeWM 特殊规则或重型 profiling，没有新加速比。
下一步为干净提交 → 一次冻结全仓 → 归档核验与 push；全仓活跃时所有作者停写。
