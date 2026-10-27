# 原最终结果链：Region 实现、返回槽与实际执行

2026-10-19；基线 `f35939ad9d91572d51e1e0d3d928d6ecc0f0647c`。
本轮是原 P4 的连接进展，完整 A–H、F12–F24/X25–X27、P5、M2 仍开放。
[冻结计划](M1_AWAIT_FINAL_CHAIN_PLAN.md)及其 SHA 保持不变；原义务逐格见
[A–H 台账](M1_AWAIT_A_H_EVIDENCE_LEDGER.md)。本报告补充计划在独立反例审查后
明确的输入支持、局部枚举完整性与动态输出字段，不更改旧合同或测试分母。

## 1. 本轮落实的模型关系（Implemented）

五类实体保持 Operation / Value / StateLocation / Region / Resource。
原规范图仍拥有全部 producer、Use、状态版本和控制边，查询视图只引用这些记录：

```text
接口 E（原合同、自己的 N/R、调用方最终消费者）
  ↓ 原 callee / 完整有序实参 / 精确 static frame
实现 Region E → 可展开的 G → primitive F
  ↓ F 自己产生的正常、异常、状态结果：每个是独立 source
本 frame 原 terminal Use
  ↓ 原 exit kind / 完整 slot / 调用方 landing position
逐层 parent_call 结果 → E 原结果 → caller 最终 Use
```

E 真正实现原接口，保其原 scope 与 OutcomeAdapter。子 helper 只保其实际调用、
结果及出口，不制造它原本没有的 await 获取/资格义务。`operation_results.py`
抽取已有的原结果腿枚举，并加入全 produced slot 枚举，含状态；旧入口继续导出。
新增 program/execution `region_implementation.py` 被已有 await consumer 调用。
Program23 / Execution8 规范记录及 codec 没有修改，没有新增 producer 或 wire。

### 输入支持与输出拷贝分别证明

`path.binding` 只证明 F 自己的结果沿本次原出口逐层拷贝。输入 packet 传给 F，
不能据此推导 F 输出与 packet 相等。反方向也不能由输出能返回 E，推导 F 在
所有路径上都收到同一个来源的输入。

新增 `stage.input_support` / `path.input_support` 只检查 source-related 参数：
相关输入是 OR，至少一个原输入有 must-copy 才给 True；may-only 保 None。
其他状态参数不要求与 packet 是同一个值。新增 `path.contribution` 是输入支持
与输出拷贝的 AND。输出 terminal 的候选 contributions 是 OR，所有原 required
terminal / slot 的覆盖是 AND。expanded 中间调用保可读路径，但不能代替其内部
frontier 的贡献。未使用的同型结果或重抛旧包可以令一个候选 False，不能否定
另一个有效候选或直接判原程序非法。条件细化目前保守，不声称完整语义证明。

### 实际执行与静态定义分别保存

静态 frame 是调用路径，不是 Invocation。执行视图从当前 E occurrence 进入它
自己的准确 CallActivation，再从该 entry 沿实际 CFG 找下一 parent_call。每 hop
必须使用该 association 的 completion；不按同 code/region/type 选别的实例。
原输入、actual/formal、Own N/R、terminal Use、parent result、最终 Use 各自核对。
frame/stage 的输入缺口逐级汇总。缺 association、completion、Use 或 transfer
保 None / PARTIAL；已采集未选腿保 NOT_APPLICABLE。

执行 `outputs` 现在是实际证据投影，原静态行仅在 `definition`：

```text
output: definition/source/type/kind/slot/edge/value/selected/terminals/status/gaps
terminal: definition/terminal:OwnedUse/occurrence/use/value/witnesses
          match/selected/status/gaps
```

terminal.match 只能由本实例选中 terminal 与动态 contribution witness 满足。
原静态 True、另一实例的返回值都不能补缺采。静态完整枚举与实际已选分支也分开：
`output.enumeration_complete` 记录该静态 slot 的原 terminal 是否查完，不能由
已检查前缀的 all(True) 代替。

### 预算、开销与所有权

静态查询沿用同一个 ConnectionContext / ValidityBudget。frame 前缀检查、索引、
原 input 关联、返回路径复制、witness 复制和出口关联均计费。ProgramIndex 只
准备一次原 input 未知模板，不预计算 return joins。ordinary 参数不再逐项扫描
整个 consumer 列表；一次 lookup 后逐项收费，耗尽即复用原完整未知模板，保留
实参分母。witness OR 采用增量汇总。局部原出口枚举截断使该 output PARTIAL；
顶层 unknown totals / cursor 保留。原签名键的呈现与派生证明开销明确分开。

## 2. 验证与审查（Verified 范围）

真实命令、JUnit、标准输出、前后 source 注册表均在
`artifacts/experiments/b1_call_operands/model_await_final_regions/`。
失败尝试不可覆盖。最终相关回归为 **1572 passed / 0 failed / 0 error / 0 skip**，
pytest 166.49s，串行 runner 167.4104013852775s。804 个 Python 源文件前后 SHA
一致：`63306959be2dcdd2bbfe83d4fe37146e93b466b213e770c71489876ec08b906c`。
原 1551 个 case identities 全保留，独立新增 21 项；归档器按精确 JUnit 身份核对，
不以测试总数代替该核对。此选择集是受影响 focused，不是 full regression。

| 尝试 | 结果 | 归因 |
| --- | --- | --- |
| first-red | 16 failed | program/boundary 为未实现视图；execution 新测试先有 consumer 选择器错误，未进入产品字段检查。 |
| static-implementation-01 | 6 passed / 4 failed | 真实静态路径已通过，缺顶层显式 value_identity_verified=False。 |
| whole-implementation-01 | 16 passed | 初版路径检查；不包含之后独立发现的边界。 |
| review-fixes-01 | 20 passed / 1 failed | 新增动态缺 Use 测试把已有 OccurrenceID 再取 .id，未进入产品逻辑；作者修新增文件，保断言及原失败。 |
| verified-final | 1572 passed | 最终相关选择集；原 1551 identities + 独立新增 21 项。 |

独立新增覆盖：静态零/两 cut × depth1/2，完整 N/R/三个 produced slot，原 parent
adapter 删除、旧包错源、budget1、late budget、public detach、候选 OR；动态
depth1 NORMAL 与 depth2 RAISE 的两实例、缺嵌套 association/terminal Use/outer
return；另有双 terminal 局部预算、may-only 输入，以及真实 state 输出/缺本实例
state Use 或 completion 的证据检查。

**动态 child 正例目前只覆盖零 cut 的上述两组配置。** 静态两 cut 与已有动态
两 cut 用例不能合并声称“两 cut child 整链已验证”。Ref 的未提供身份、primitive
native/effects 仍有明确缺口；局部 copy True 不授数值身份、纯度、来源适用性。
所有 source/runtime/value/transform authority flags 仍 False。

根负责全部串行 Python / pytest / probe 和产品；A/C 独立写新夹具/用例，B 写
独立边界用例；全部作者执行前冻结。有限只读复审核了 exact frame、N/R、slot、
OR/AND、输入支持及计费，审查只对记录 SHA 有效。旧 tests/fixtures 不变，不用
改旧断言或旧输入取得通过。原两 checkout 的 HEAD/status 由归档器再次校验。

## 3. 下一步与完成边界（Proposed）

1. 把同一实现/actual final-consumer 链接到原 native/self、general、W 三路来源，
   零/多 cut、BodyReturn/BodyRaise 的完整组合；不重做已有获取/资格内核。
2. 复用原 pending/Replace/Resume/C1 关系，接最终后继、准确当次状态与消费者；
   shared incoming、重执行和缺采均保原义务分母。
3. 原 A–H 和 16 组真缺项齐后，才做原要求的组件/full、P5、M2 113 构造/196
   字段总核；M0–M2 完成后按用户要求汇报讲解，再停下。

本轮没有新 detector/backend、LeWM 特例、GPU profiling 或 A/B 性能结果。
supplied-model 测试不证明自动 LeWM source recovery、完整采集或优化授权，
仍不能报告 LeWM 加速比。历史 full5822 仅属于其原归档源，不能移用于此版本。

## 4. 重放验收记录

在本分支 worktree 与 `lewm` 环境中：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python \
  artifacts/experiments/b1_call_operands/model_await_final_regions/checkpoint.py --check
```

这个命令只核 source、JUnit、文件摘要、旧测试字节、原 A–H 逐项证据与两个受保护
checkout，不启动测试或 workload。原执行命令在 `verified-final/command.json`；
重跑测试必须建立新的尝试目录，不能覆盖此归档。代码、夹具、报告、失败记录与
checkpoint 一同版本管理；验证完成后的提交号以 Git 历史为准。
