# 原 F16：首次 ASEND 的来源、联合控制与后态

2026-10-19。基线 `96b8a322590217151ff6a5e839c7ab17d068f560`。
上一门 2016 项相关测试、884 文件稳定指纹、提交/远端相等及干净状态已重核。
本门继续原 M0–M2、16 族和 M2 的 113 构造/196 字段，不新增优化后端或业务规则。

## G0：原要求与边界

原 F16 是四种 async request 的来源、关联、交付、首次发送、复用和竞争。
四来源、同 R 三段驱动、完成后复用、R1/R2 竞争、后续 scheduler packet 已有
准确正反证据，不重做。原 R3 四个真实 opaque/write 阻断及主 occupancy 未知
应保留；原条款不要求把它们改成 preserved=True。完整区间正例已独立验收。
不能把真实未知当作模型未表达，也不能把未知变成纯性或优化许可。

本门真实结构欠项为：独立 R.initial、关联 B.Created、准确有效 SEND operand
及 None 检查，经原 bool/BRANCH 和同一控制上下文，到 Start、Resume 或拒绝
helper 的 own N/R、全部当前状态与 host。BodyStart 不虚构 SENT_VALUE resume slot。
preentry 拒绝没有 Drive，其原谓词、helper、端口、状态仍须进入分母。

## G1：已观察的原生事实

本门 `model_async_initial_control/native-probe.json` 的本机 Python 3.14.7
有限探针有 11 条观察，运行前后仍为原 884 文件指纹：

- B Created 时 L nonNone、首次 S=None：TypeError；B 仍 Created，未进入 body。
  同 R 再调用 RuntimeError；新 R(None) 可以启动同一 B。
- B 已在 ASYNC_YIELD 处暂停且无活动 session：新 R 的 nonNone L 可合法恢复。
- 首次 S nonNone 会覆盖 L：实际 suspended B 接收 77 而不是保存的 61；
  Created B 即使 L=None，也不能据此允许首次 S=43。
- 同 R 后续恢复 await 使用本次 S，不回借 L。

参考 [CPython 3.14 genobject.c](https://raw.githubusercontent.com/python/cpython/3.14/Objects/genobject.c)
的 `gen_send_ex2`、`async_gen_asend_send`、`async_gen_unwrap_value`。
移动分支源码只作独立参考，不冒充本机确切实现；本机行为以存档探针为准。
R 完成、B frame phase、B active session 和 host 返回是不同事实。

## G2：复用现有类型，先保存缺口反例

五类实体仍为 Operation / Value / StateLocation / Region / Resource。
不增加 predicate subject、phase 状态机、影子 world 或第二套 dataflow：

| 已有合同 | 本门使用 |
| --- | --- |
| RequestStateCondition(IS_INITIAL_STEP) | 原 R READ、本次 bool、真实 branch |
| BodyStateCondition(IS_CREATED) | 独立关联到 B 的原 READ，不能把 driver receiver R 当 B |
| ReferenceIsNoneCondition | 真正有效 operand 的原引用，不是整个 RAW 或任意同型引用 |
| RequestProcessing(CHECK_INITIAL_ASEND) | 原 raw carrier、精确 ordinal0、拒绝 helper own result 及原 state sites |
| CallActivation / SessionUpdate / 原 CFG/state | 实际调用、拒绝后的 R post 与 B 未进入事实分别表达 |

当前 async profile 拒绝已有 BodyStateCondition/ReferenceIsNoneCondition；
通用 body owner 还按 R 检查 B；None 查询仅看 scheduler raw；request_delivery
跳过 BodyStart，initial=True 又不加条件地选 L。这些均须准确收束。
先写 core 合法、含真正 R/B/operand 控制的有限新图，在旧产品保存具体首红，
再接新查询。禁止用幽灵 Use/consumer、翻旧 opaque 或修改旧 fixture 迎合新图。

## G3：原依赖上的派生检查

1. 窄扩 async profile 对已有 Body/None subjects 的准入。body owner 由独立的
   R→Create/Association→B 来源核对；不从未来 Drive 倒选 B，不把语义投影加入 copy。
2. None 输入分别核 raw ordinal0 与原 caller/CFG 选择。首次 scheduler 为已证
   NEXT/None 时才使用 L；首次 S nonNone 使用 S，未能确定有效输入则给准确 gap。
   后续调用使用 S。不得以 R.initial 代替 B.Created 或 None。
3. 联合控制必须来自同一原 CFG 路径和整组来源；保所有 nested branch choices、
   caller context、state support 与预算。不能 AND 来自不同路径的单谓词 frontier。
   复用已有 selected choices、request binding、correlate 和原控制图。
4. 核 phase 条件与真实目标的局部兼容性：Created+有效 None 到 Start；Created+
   nonNone 到拒绝；非 Created 的新 R 可到 Resume。其它资格仍由本来的 gate
   检查，不宣称一个 None 或 Created 判断足以授予完整 admission。
5. callback 后原历史 bool 仍合法；当前版本支持丢失时保持 Unknown。缺 R/B/Use/
   selected transfer、错 ordinal/独立 bool、预算截断不可借 sibling 或已检查前缀。
6. 原协议行、bool/branch、helper N/R、全部 gate、状态与 source 的库存先保全，
   再预算化检查。删附件不删除原 core 分母；拒绝链无 Drive 也不能消失。

新派生模块拟为 `scar/ir/program/async_initial.py`，提供
`async_predicate_errors(ctx,row)`、`async_predicate_view(ctx,row)` 与
`initial_asend_connections(ctx)`。公开 protocol obligations 复用该结果，不
另存可写的判定事实。结果继续 source/runtime/native/transform authority=False。

## G4：有限正反验收

复用现有 async pipeline 的真实 Create、一 B、两 AWAIT、最终 item、原 caller
与 capture helpers，不再搭建完整解释器。最少语义组合：

- Created + R initial + L=None/S=None：真实 Start，后续原 HOLD/HOLD/COMPLETE
  整链仍用各次 S；same B/source/current states 不变。
- Created + L nonNone/S=None：拒绝 helper own N/R、全槽到 host，无实际 Drive/
  frame attach/终结 F；新 R(None) 重新读取后可启动同一 B，R post 独立表达。
- 原 ASYNC_YIELD 后新 R nonNone：同 B suspended、session 已释放，真实 Resume。
  不能把 AWAIT/HOLD 期间的竞争当合法。
- 首次 S nonNone 覆盖 L 的来源条件，以及后续错用 L 代替 S 的反例。
- 错 B、错 ordinal/同型值、错 bool、历史 callback 支持、必要缺采与 budget1。
  只围绕实际接缝补反例，不构造参数笛卡尔积。

静态声明正例、实际 occurrence 与缺采分别验收。原生探针不是自动 lowering；
供应图与 capture 通过也不是自动整 LeWM 建图或优化证明。

## G5：旧 wire、回归及原义务合账

新 subject 仍是旧形状，变化是固定 async profile 的准入语义，因此需明确
Program26 能力门；无新准入的 1–25 wire 和原字节保持，Execution8 不变。
旧 reader/future 断言仅依本门另行冻结的精确迁移 ledger 替换，不豁免整文件。
旧 fixture、其它测试字节和原 2016 项义务保留；真实参数身份迁移显式记账。

所有源码作者 FROZEN 后 root 串行运行并保存命令、源码、JUnit、日志与前后指纹。
最终相关回归覆盖原 2016 与新接缝；扩大范围只为具体的旧规则/查询风险。
按原 F16 条款逐条合账，条件性 M1 整族是否成立由证据决定，不预填关闭。
剩余八族、P4 component/frozen-full、P5、113/196 和完整 M0–M2 不被本门替代。

## G6：报告与版本

root 自行验收、保所有首红与假设撤回、写进度/下一门/checkpoint、正常提交推送，
核远端 SHA 与干净状态。不让用户逐门批准，不修改 LeWM 或主目录旧 checkout。
第一阶段完整完成后先向用户讲解；不以更多手工图拖延后续自动恢复交付。

作者划分须在写入前固定；所有解释器仅 root 串行启动，运行期间不得修改源码。

### 本门文件所有权

- root：本计划/档案/原义务审计/Git；`protocol_rules.py`、`admission.py`、
  `protocol_validation.py`、`protocol_query.py`、`protocol_connection_validation.py`
  的准入/公开接线；仅 NEW `program_async_initial_selection_graphs.py` 和
  `test_program_async_initial_selection.py` 已保存两个准确旧产品首红。
- A：仅 NEW `scar/ir/program/async_initial.py` 与旧 `protocol_async.py`，
  独立 B/operand 谓词视图、联合原路径检查及首次有效 S/L 来源选择；旧 packet
  normalizer 与后续 S 路线保留。新 API 如 G3，async 报告增加 `initial_asend`。
- B：旧 `program/codec.py`、`program/protocol_connections.py` 的能力检测，
  仅 NEW `test_program_async_initial_control_codec.py`；先冻结独立的旧测试
  字面量迁移合同和机器 ledger，再依合同改旧测试，不改任何旧 fixture。
- C：仅 NEW `tests/fixtures/{program,execution}_async_initial_control_graphs.py`
  与 `tests/unit/test_{program,execution}_async_initial_control.py`。
  保准确实际 R/B/来源、全状态及拒绝 helper N/R，不运行解释器。

作者先互通新 API 与 fixture 字段，只修改自己路径。任何范围变化先记录具体
模型缺口与合同补充；全部作者明确 FROZEN 后 root 才执行。新 codec 规则只对
新准入语义启用，不将旧 CHECK_INITIAL_ASEND 的单行声明伪装成完整联合证据。
