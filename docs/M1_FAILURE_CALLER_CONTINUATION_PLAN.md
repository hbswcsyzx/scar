# 获取失败与外层清理：原失败端口、当前完成分开

2026-10-19；基线 `2c427b7b2923ac6e177b4ecac2200aa25ea31fa0`。
上一单位1716 affected focused通过、原1693 identities守恒，归档核验通过，
提交/推送与远端精确SHA已核。本单位延续原 A–H 的 B/H，不重置十六组、
P5 或 M2 原113构造/196字段分母，不称完整模型已经完成。

## 模型与两处接缝

仍为 Operation / Value / StateLocation / Region / Resource；获取、lookup、
调用、资格分支、异常构造与清理是不同 Operation；候选 Reference、whole
exception packet 与 pending token 是不同 Value。协议视图引用唯一原 CFG、
SSA、Uses 和执行实例，不另造 producer/state 图，不加 wire 或 codec。

```text
lookup / method-call own RAISE，或资格拒绝控制腿
 → 真实 whole packet / helper 的 RAISE 与状态
 → 获取操作自己不可变的 RAISE 结果（kind/fullslot/edge）
 → caller 同步 C1（保留 / 新 Raise / 新 Return）
 → caller 当前 terminal 的 typed tuple、状态 Uses、消费者
```

必须分开核对：

1. **内部失败交付。** lookup/call own R 或资格拒绝臂的真实 packet，沿 helper
   精确出口交给获取操作自己的 RAISE。分开记录 stage packet→helper terminal
   与 helper terminal→获取 own R 的 binding；后者 True 不能替代前者。保既有
   packet/state 的全 slot 连接。
   资格 branch 的首 landing formal 只是候选/遍历锚点，不能作为 whole packet。
   packet 来源沿该臂真实 terminal payload 的原 producer/ExceptionPacketDefinition
   查询；禁止按名字、异常类型或最终替换值反选来源。
2. **caller 当前完成。** 从上述获取 own RAISE，在 caller 内复用既有
   completion_continuations(cross_resume=False) 与原收据，连接真实同步 C1。
   caller Return 不把获取改成 NORMAL，也不能套用“按当前 kind 选择获取 N/R”
   的 structured_completion parent 连接。没有更外层调用时，当前 Region.exits
   的真实终端 typed tuple/Uses 就是出口，不捏造外层 CallActivation。

## 查询与执行合同

- 原 failure key、stage、stage edge、prefix choices 和 scope 分母全保留；
  新增字段仅在 caller 的原 RAISE 端口所属 region 有 C1 时启用。无 C1 的默认
  查询保持旧语义。原获取 RAISE source_result/source_edge 不能被覆盖。
- helper `terminals` 仍证明内部失败→获取 RAISE；与 caller 的最终 terminal
  分列。own acquisition/constructor 无内部 helper 义务，可有空 helper terminals，
  但必须保其 own result、caller continuation 与消费者义务，不当作缺失或完成。
- expanded helper 的 stage_source/stage_binding 独立于原 incoming binding；
  资格拒绝不伪造 copy，而引用准确 reject control edge 及 terminal payload 的
  原 origins recipes/packet definition、exception/traceback Uses。此 provenance
  记录仍是原图查询；未核 native 异常类别不会因结构已齐而变成已证。
- 新 caller_continuations 引用原 walker；caller_terminals 保 root_source、
  current_source、choices、actual、role、binding、root_binding 与当前终端。
  root_binding=False 可表示显式合法替换；current binding=False 仍拒绝；未知
  不当作替换许可。不添加最终提取义务。
- 原 source 的消费者（例如 pending constructor 的 payload Use）与当前终端
  消费者分开。更改/删除 receipt 不能删除原实际 Use 库存。当前状态收据引用
  terminal 全 tuple ordinal、准确 location、canonical StateVersionValue 和
  owned Use；不将旧获取 state 与新清理 state 强制相等。当前 state 的来源仍由
  原 SSA 与实际采集约束，单个 capture 收据不冒充 native 状态正确性证明。
- 执行复用现 actual continuation cursor，沿本 Get 的实际 RAISE transfer，
  selected dispatch、pending payload 与当前终端；helper association/completion
  与 caller terminal 分开。两实例缺采不得借另一实例。
- 该 cursor 的来源入口增加一种严格支持：本 anchor 的实际 selected
  CompletionResult→landing formal 对应的准确 ValueOccurrence；先共享预算计费，
  不接受任意同 activation 值、forwarded Use、另一 successor 或 sibling landing。
  核原 signature 的 typed slot 与该值的 origin/value，沿既有 activation/segment/
  run/process约束；泛用 cursor 支持其可表示的 packet/reference 类型，失败调用
  仍另外要求本获取实际选择原 RAISE。
  本地 own result 不要求存在 helper association；它不因此证明 helper 失败桥。
- 全部路径和 join 使用同一预算；raw 枚举完整不代表后续连接完整。中途截断、
  opaque、缺 Uses/dispatch/call 关联保 PARTIAL/gap/cursor 与原键。所有 source/
  runtime/value/transform authority 仍 False。
- 删除 expansion 附件不能凭唯一 helper 重建配对或称 expanded 总数已知；
  原 own RAISE 锚和尚未配对义务继续显式保留，按既有原分母规则报告缺口。

## 作者职责与冻结顺序

root 独占产品/文档、串行解释器执行、归档和 Git；作者不执行 Python、pytest、
probe、compile 或 Git，不改旧 tests/fixtures、合同、codec 或封存证据。
独立审查本合同后才授权新文件实现；各作者完成后报 SHA 冻结，root 才执行。

- A：新 tests/fixtures/program_await_failure_cleanup_graphs.py。
  await_failure_cleanup_program(stage='qualification_reject', mode='preserve')。
  stage 为 lookup_raise / method_call_raise / qualification_reject /
  wrapper_constructor_raise；mode 为 preserve / replace_raise / replace_return /
  opaque / wrong_terminal。以旧真实失败图为基础，只把 caller 的原失败 landing
  接同步 C1，保持获取 own RAISE 签名和所有其余正常 CFG。引用模板子图时不带
  无关 body/adapter/driver 操作。metadata failure_cleanup 明确原 source_result/
  edge、root packet/state、C1 definitions/actions/dispatch/current_source、当前
  terminals/payload/state Uses、完整 caller_path，helper region/path 独立。
- C：新 tests/fixtures/execution_await_failure_cleanup_graphs.py；同 stage/mode，
  instances=2；按新完整 caller/helper 路径重建采集，连接每实例准确 helper
  CallActivation，不假造 BodyDrive 或 Suspend。可缺单实例 payload Use、dispatch
  或 helper association，保其他实例完整。metadata 分开 source/parent/helper
  occurrences、原 RAISE landing 值、当前 terminal、pending constructor 与 Uses。
- B：新 program/execution failure_cleanup tests；独立整链断言，先首红。至少
  各真实失败来源到 current terminal 的保留/替换、获取 RAISE 不变、准确 whole
  packet 来源/state/消费者、两实例、错当前包/opaque、缺采和预算分母。新增
  own-result cursor 入口必须有另一 successor/sibling/forwarded值的反例或既有
  可准确指认的覆盖，不能只测试同 activation 正例。

## 自验与交付

模型/合同有限反对性审查→新图/断言冻结→公开 API 真实首红，作者错误与产品
缺口分列→复用公共关系修复→有限复核→全部冻结→原1716精确 identities 加新增
用例的 affected focused 回归→原 tests/fixtures/合同/codec/保护仓库/前档核验→
报告、commit/push 与远端SHA。每次保独立命令、全日志、JUnit、源码前后清单。

证据目录 `artifacts/experiments/b1_call_operands/model_failure_caller_continuations/`。
原 A–H、十六组、P5、M2 保 OPEN，除非原整格所有条件确实逐项完成。随后仍按
原来源/direct-vs-await、shared incoming、重执行/刷新等剩余组合推进。完整
M0–M2 后才先向用户讲解模型；本单位无 detector/backend、LeWM 特例、profiling
或加速比结论。
