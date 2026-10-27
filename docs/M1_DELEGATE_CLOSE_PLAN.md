# N3：close 原控制库存与实际后继

2026-10-19；基线 `4ac61ec63161dfdb9e66fc5a51ce2df02453b5ea`，开始时干净且
远端同步。上一节点1793项受影响定向通过、原1780准确 identities 保留、F17/F21
条件结构验收关闭；原 G 保持关闭。本节点只补原 N3/F23 与 X27 的两个交叉
缺项，不重置其余14组、A–H、P5、M2 原113构造/196字段。

## 1. 建模约束

规范实体保持 Operation / Value / StateLocation / Region / Resource。原
Operation 的 selected completion、原 CFG/SSA、pending/context 及真实 Use
决定结构义务库存。可选 inputs/consumers 声明只提供独立来源与声明的消费者，
不能定义程序有哪些原路径。缺源可以阻止来源证明，不能抹掉后继控制库存。

close NORMAL 的 own None 与原注入异常包是不同值；RAISE 使用此 close 自身
的完整新包与当前 state。若删独立注入来源，NORMAL 原 C1/host 路径继续可见，
原来源明确未知，不能倒取实际 pending payload 充当期望来源自证。已知显式
replacement 的当前来源与未知原来源分开报告。继续复用现有 bounded walker、
pending possibility、copy/binding 与实际 occurrence 查询，不新增 producer 图。

## 2. 静态验收

复用 packet_continuation_program(two_cuts=True, complete_transitions=True)，
先 core/full 合法。仅按两 exact close sites 删除可选附件，所有原规范记录、
两次 Suspend、N/R operations、pending definitions、control ports 不变。

1. 只删 consumers：两原 N/R close_routes、当前来源、实际 C1/actions/projections
   和 host target/check 不减，保原消费者分母与明确的缺附件说明。
2. 整删 inputs/consumers：两条原 close 义务和各自 C1/host 库存仍在；RAISE
   仍可从 own packet 绑定。NORMAL 缺独立注入锚时原来源检查为未知而非 True
   或伪反证，route 不可 DECLARED，保具体缺源原因。不可用 own None 替包。

类型相同、可支配、可见的旧来源均不自动取得独立来源资格。现 opaque、预算、
selected port、replacement、known/unknown helper 反例保留，按原 selector 合账。
若源未知需要独立 inventory 模式，仅在现 walker 内分开控制枚举和 copy 证明；
不以 bind(None) 或新 schema 绕过验证。

## 3. 实际发生验收

现 packet fixture 的 P 两次静态 Suspend 不等于每条路径都执行两次。需按真实
CFG 核选中路径：close own NORMAL 的 normal_jump 和 own RAISE 的 failure_jump
均进入原 shared=finally.failed，再经唯一 failed.jump 到第二 cut。绕过它的
handled 分支没有调用 close，不能当作 close own NORMAL。这里按边而非 block
名字判路径；不改原图，不增加任何 cut。

新测试在原 P 外供应准确 Start → DELEGATE_PACKET Resume → SENT_VALUE Resume，
两条实际 close selected completion 都有三个 Drive/segments。保原 pending/
saved/context/N/R CFG，每个实例一个持续 P；各同步 driver 经各自准确
CallActivation 返回。finally.invoke 是无 callee 的原 primitive，不编造 helper
activation。

NORMAL 从原 InjectedPacketTrigger 的实际 wholepacket 出发，RAISE 从 close
own selected packet slot 出发，均核到当前 C1、实际 host/current state。anchor
位于第一次 resume，cross_resume=True 只取其后两个 P segments；False 在第二
次 Suspend 停止。不得使用会改写 DELEGATE_PACKET 的 SEND 外壳。

最少 N/R 两正例与实例局部缺 pending Use、Resume transfer、terminal Use；有
完整 sibling 不能借其捕获。原包许可若确有首红，只窄接准确 close NORMAL、
独立 input case、packet-forward Use 与实际 guard/copy，不放开任意同 activation
或 forwarded 值。记录实际 capture 和供应模型的边界，不宣称源码自动恢复。

## 4. 执行顺序与自主验收

- A 仅新增 tests/unit/test_program_delegate_close_inventory.py；先两个删除变体。
- C 仅新增 tests/unit/test_execution_delegate_close_continuations.py；helper 同文件。
- B 独立只读复核原要求、来源许可和有限产品修复；不写代码或执行解释器。
- root 独占产品、文档、Python/pytest/probe/compile、归档、Git。作者冻结后
  串行记录每次 command/log/JUnit/源码前后清单；首红与作者构造错误分别记录。

冻结计划 → 有限新测试首轮 → 必要公共关系修复 → 独立复核 → 作者冻结 → 一次
原1793准确 identities 加新增的同源受影响定向回归 → codec/合同/旧测试与 fixture/
旧归档/两原仓库保护 → 报告与 checkpoint → commit/push/远端精确 SHA。
真正规范字段阻断先说明，不直接加字段。F23 各原条目齐备才关闭其条件结构格；
X27 全族交叉、其它家族、组件/full、P5、M2 按各自原要求，不能代关。

证据目录 artifacts/experiments/b1_call_operands/model_delegate_close_continuations/。
不增加 detector/backend、不做 LeWM 特例、GPU/native 实验或新加速比。
