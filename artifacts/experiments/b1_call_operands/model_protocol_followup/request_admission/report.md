# Request predicate → gate：有限实施收据

2026-10-18，基线 `7dd8c54b8d8cfdb3454b9f3b671f3412d1a914f0`。
依据 `docs/M1_PROTOCOL_FOLLOWUP_PLAN.md` §4，SHA
`44437087abfe3fa1a7b074ca973c06a0f863eb0c4fc9073ef26f8881de412f78`。
本范围已实现并定向验证；**完整 F16/F17/F19/F24、P4 固定16组及 M0–M2 仍 OPEN**。

## 改动

- 仅改 `scar/ir/program/protocol_async.py`，新增独立 fixture/unit 文件。
  未改旧 fixture/test、共享 flow、记录、codec、schema、主文或旧证据。
- 从原 `FinalBodyGate` 先建立 `request_admissions` 分母；每项保原 gate/op/drive、
  predicate_count、原候选、status、gaps、cursor。删 predicate 仍 MISSING；预算不足仍
  保每个原 gate 和 NOT_CHECKED/cursor，不把空列表当准入完成。
- 原 FINAL_GATE frontier 追加 truth、request_binding、gate_request_binding、
  same_request、currentness、request_target_compatible_at_snapshot。
  所有绑定复用共享 index/flow/budget；每 context 缓存同一 predicate view，避免重复扫描。
- `IS_COMPLETE` 的 true + 原同 R must-copy + 非空完整当前 READ 支持，给兼容 **False**
  与 scoped `async_request_complete_success_incompatible_at_snapshot`。普通静态 CFG
  保持有效：潜在 gate NORMAL 边不是成功发生的证据。
- callback 后历史 true 仍是原控制事实，但当前支持变化给兼容 **None** 和重检 gap。
  false 分支的兼容 True 仅表示该谓词未排斥，不表示 admitted。
  `IS_INITIAL_STEP` 不解释为 B Created，也不推出一般 admission。
- 错 R 与错 bool 延续原 hard source 检查。所有 native/source/runtime/transform
  权限继续 False。family 顶层及 admission entry 均可见 scoped 不相容/stale 诊断。

## 新10项范围

1. COMPLETE true → 原 reject helper NORMAL/RAISE → host packet/current states；false → gate。
2. 当前同 R 的 true → gate frontier False，图不过度硬拒。
3. unknown callback 原 N/R 后态：历史 true 保留、currentness False、兼容 None。
4. 同型另 R 不能供应本 interface 的 predicate（admission_owner）。
5. 另一 bool 不能代本次 predicate result（admission_bool_source）。
6. request initial-step 与 body Created/一般 admission 分开。
7. 删 predicate 保原 gate MISSING 分母。
8. budget=1 保原 gate、predicate_count 与 NOT_CHECKED cursor。
9. 一个声明 Create 来源的两个原 INVOKE caller recipes 均保留。
   第一 RAISE landing 有真实 packet/context RW，第二调用消费其当前 state。
   这不是两个实际运行 occurrence、native request 复用或对象身份已证。
10. 公共 `ProgramIndex.protocol_obligations` 暴露缺失 admission，完整模型标志仍 False。

已知 scope：未做跨 callee session post 摘要传播，不从上一 callee post 无桥推断下一次
phase；未完成 HOLD→再调用→COMPLETE→reuse reject、竞争与版本限定 aclose 整图。
没有新增 phase flag、第二状态链、native parser 或调度器。

## 命令与实际结果

root 发 READY 后获得唯一测试时段，已明确释放。Python 3.14.7：

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python \
  artifacts/experiments/b1_call_operands/model_protocol_followup/run_focus.py \
  request_admission/attempt002 \
  tests/unit/test_program_request_admission.py \
  tests/unit/test_program_async_connections.py
```

- attempt001：新增文件 **10P / 1.49s**，runner 2.164518046s。
  源指纹前后 `e3bd2fca004ec0a99f08b624b13578f2d3a3c8dfed1abc16cf047249ba48e5dc`。
- root 只读意见补 scoped flat gap 可见性，沿原两个核心反例加断言；没有新加镜像 case。
- attempt002：新增10 + 受影响旧async39 = **49P / 3.35s**，runner 4.030436574s。
  源指纹前后 `dcfad8ffed9653d6db3587107cf47d987a19ecbb9bb4bbf59e91a26609d97e79`，
  changed_paths=[]。两个 attempt 原日志、命令、JUnit、前后源码清单均保留，无失败覆盖。

49是本次最终所选 case 数，不能与首轮10累加成59个独立验收。
没有运行 component/full/native probe/GPU/LeWM workload，没有 commit/push。

## 冻结自有文件

```text
bcd5d48b3236929933fec94578e0b156d5c393d19c9b81c3bcee6d95fe4addba  scar/ir/program/protocol_async.py
03eca25902b3cbafde467698e8fcc2b03c1bc7f9e7c8e8025f79df4c689817bd  tests/fixtures/program_request_admission_graphs.py
314fd571109d3bf95dc5b202ecd72564a9b0ec3fbdc0fb44328ba9965ea395a7  tests/unit/test_program_request_admission.py
```

以上三文件停止写入。后续只读交叉审查另作者模块，不运行新测试。

## 追加：窄预算复审修复与最终冻结

root 在上述49项收据后明确重开一项已确认的预算风险：原 `initial_step` 对每个
drive 扫描全部 protocol rows 及各 frontier，但未收费。此次仅作以下修复：

- 在 Analysis 原库存准备阶段建立每 scope 的 IS_INITIAL_STEP 原 row 索引；准备成本
  另列 `async_initial_predicate_index_rows` / `async_initial_predicates`。不是新增规范事实。
- 实际 predicate/frontier 遍历按共享预算逐项收费。任何截断返回 None 与 cursor，
  不使用已访问前缀拼成 True，也不为每个 drive 重置预算。
- 保留已批准的历史分支语义：旧 read 在 callback 后仍可解释当时 L/S 选择，不能
  由此证明当前 request phase 或 gate 资格。delivery 显式报告
  `selection_basis='ORIGINAL_PREDICATE_EDGE'`、`current_step_verified=False` 和条件。
- 新增两个真实图测试：充足/不足预算的同一 predicate/frontier 选择；已有 THROW
  normalization 路径的历史选择标识。未改旧39项或其 stale 正例。

root 再次发 READY 后，在唯一时段执行同上 runner，attempt 改为
`request_admission/attempt003`，selectors 保持新增测试文件及原 async 文件。
实际结果：**新增12 + 旧async39 = 51 PASS / 3.50s**，runner 4.153755782s。
源前后指纹均为
`fc5a4b495932dbc40cf798af908cb683d6dd7588e3e23d184526e16097bdd6b0`，
changed_paths=[]。原命令、输出、JUnit、源码清单及 result 均保留，无失败。
51是最终所选独立 case 数，不与前两次重复运行相加。默认预算未调高。

最终自有三文件 SHA（替代上方历史冻结哈希）：

```text
9e0cbbf1fed8fc1bf179bb4ca43445394d0359b4bf845cab4beb930e34770c69  scar/ir/program/protocol_async.py
03eca25902b3cbafde467698e8fcc2b03c1bc7f9e7c8e8025f79df4c689817bd  tests/fixtures/program_request_admission_graphs.py
63c1e6845ceca7fda50d9f04df72973032c78ba0563473cd4b2cdccde2f97484  tests/unit/test_program_request_admission.py
```

## 追加：C mixed-case InitialAdvance 只读交叉复审

原审查指出：prior SEND 的原 receiver 是 A/B phi 时，未加各 case guard 的
must-copy False 不表示每条路径都没有 advance A；后续 A InitialAdvance 不应因此
变为 DECLARED。作者保留原 red001 被不完整 CONTROL 遮蔽、修正该 fixture 声明后
red002 实际1FAIL的证据。本报告未运行或改写这些实验。

最终只读核对以下原文件：

```text
ef26888f07aa6934fe50009a5afc50606dced4f231e52eea8da5d942fa494635  scar/ir/program/protocol_continuations.py
22d1b4c41d6813a24200fa99b9c9ada76affb220c9f5e53fe4bbeb88c2c85412  tests/fixtures/program_method_lookup_graphs.py
7c2e597faec7523f535ce74799697a341c191d9c3138337a40dc9f7889502307  tests/unit/test_program_method_lookup_connections.py
```

已确认 prior case.guard 与当前 guard 联合；互斥选择保 None；must False 且 may
非 False 保 unknown；混合 True/False 不能产生 Initial=True；位置、边及共享绑定预算
不足均不能 True。新原图反例分别断言无 guard False、A guard True、B guard False，
再核后续两个实际 N/R obligation 均非 DECLARED。该具体漏检在所读源上闭合，未见
新增阻断；这是静态有界复审，不代替作者77项运行或完整 delegate/native 验收。

本次自有源码、测试及报告均停止写入，测试时段已释放。完整 P4 固定16组及前述
OPEN 分母不变；未运行 component/full 或任何新 native/workload。

## 最后追加：单谓词视图不重复准备全表库存

上述 attempt003 结束后，A/root 又确认相邻准备成本问题：每个 uncached
`request_state_view` 构造完整 `_Analysis`，会重复全表 rows/maps/inventory；多谓词时
形成重复准备开销。root 明确授权有限消除，不要求再自行运行51项。

`_Analysis(ctx, *, prepare=True)` 现只在默认路径建立库存；先初始化 context、局部
diagnostics 和 cursor，`prepare=False` 随即返回。`request_state_view` 用 False，
它仅调用原 support/formal/spend/site/use/gap 等不依赖库存的 helper。正常 async.run
及 initial_step 测试仍用默认准备路径。未改规范字段、预算限额或原选择语义。

最后源码 SHA：

```text
6551b7b7fb6b4970e7314cfb7b430fd9e5cad1910f40532117e94198e692072e  scar/ir/program/protocol_async.py
```

fixture/test SHA 保持上一节不变。**51 PASS 属于上一个源 SHA `9e0cbbf1...`，
不归给本次新 SHA。** 新路径等待 root 统一 affected 运行；本作者没有重跑定向，
没有新增测试或隐藏原结果。已请 A 只读复审两处构造路径，交回后停止文件写入。
