# 原 F18/F19：先核实际边界，再连接原图

2026-10-19。基线 `54118247d4ff4c764dbe6f66493bc8609041f24b`。
上一门真实 2058 项通过、892 文件稳定指纹和 checkpoint 已重核；远端同 SHA、
0/0 且干净，LeWM 与原 scar checkout 仍为原 HEAD/干净。上一目标轮归类为
VERIFIED_PROGRESS，不是等待或无进展。

## G0：保完整原要求

继续原十六族、P4/P5、M2 的 113 构造/196 字段。八族条件性接受：
F12/F13/F14/F15/F16/F17/F21/F23；F18/F19/F20/F22/F24/X25/X26/X27 仍开放。
本门有两个完整原单位：先完成 F18 自然完成/主动终止异常/非法源 return 的
结构合账，再按原 F19 核 closed/athrow/aclose/失败续体；不由前者代验后者。
已有自然 Return、四 raw 来源、复用、竞争、packet 及当前状态不重做。
第一阶段完整后仍先向用户解释，不添加 detector/backend 或 LeWM 特殊规则。

## G1：真实观察先于新的固定规则

本门有限 native 观察、编译观察及首个探针前提失败保存在
`artifacts/experiments/b1_call_operands/model_async_terminal_semantics/`。
运行前后仍为原 892 文件/f8e32575…；没有执行目标模块或升级环境。

- 主动 StopIteration/StopAsyncIteration 变为 RuntimeError，cause/context 指向
  原异常；普通 ValueError 原样传播。
- 非法 close-yield 后，同 R 重试与新 R 回复不同；frame 仍可有续体，随后
  anext 才实际恢复 finally 并终结。native ag_closed 位未由探针读取。
- inspect API 的 AGEN_RUNNING 可与 ag_suspended=True 同时出现；它不证明
  frame 正在执行。active session、continuation、frame release 必须分开。
- bare return 与显式 return None 的最终 payload 可同为 None，后者在 async
  generator 源中仍非法。嵌套 def 默认参数中的 yield 属于外层求值，不能用
  “跳过所有嵌套定义”重写 Python 作用域规则。

固定 [v3.14.7 intrinsics.c](https://raw.githubusercontent.com/python/cpython/v3.14.7/Python/intrinsics.c)
与 [codegen.c](https://raw.githubusercontent.com/python/cpython/v3.14.7/Python/codegen.c)
表明转换在当前 frame 的 handler/intrinsic 内发生，之后才真正 RERAISE。
[genobject.c](https://raw.githubusercontent.com/python/cpython/v3.14.7/Objects/genobject.c)
单独描述 request/closed-bit/session 后果。源码存档及哈希不冒充本机二进制重放。

## G2：F18 使用已有核心类型

五类实体仍为 Operation / Value / StateLocation / Region / Resource。
原 packet→body 内 ExceptionMatcher own bool/BRANCH→原 constructor own N/R→
cause/context 状态写→最终 BodyRaise→Drive→driver/host，用原 Uses、状态、
completion 与 occurrence 连接。普通异常走原 packet，构造失败走自己的包。
不能先给原 Stop* 建终结事实，再把构造器放到 driver 伪装实际 native 时序。

使用原 ProviderEnvelope/ProviderRegion/NativeBoundary 的精确 artifact、原
entry/exit 端口作为条件性声明锚；名称或 RuntimeError 标签不证明语义。
既有 constructor 没有合适 async driver scope，不强挂 ProtocolCall，不偷用
created-throw/close profile。本轮先接真实原操作展开，不新增 adapter enum、
profile、核心实体或 wire。native/source 适用与变换权限仍各自为 False。

自然 Return 的已知非 None payload 检查应由原 source inventory 驱动；删可选
AsyncSessionOutcome 不得让已知错误消失。先保存旧产品定向反例，再改检查。
已有自然 Return 的 own N/R/packet/host 和缺采单独保留，不重建基础流水线。

## G3：源级非法程序不伪造运行图

新增派生编译检查，复用 SourceSnapshot/SourceReference/OperationSource。
明确接收 caller-owned text，先核 fingerprint/encoding/版本，再用本机 CPython
编译检查而不 import/exec；保 Return AST 原站点库存及可选 operation links。
源级有表达式与运行值是否 None 分开。完整 AST 库存不表示 compiler 在首个
错误后诊断了所有位置；缺 bytes、版本不符、预算/范围不足、错 span 保精确 gap。
不新建 SourceForm 标签代替 replay，不顺便实现 async lowering 或任意源码恢复。

## G4：有限正反和动态验收

F18 围绕两个 Stop* 转换、普通异常旁路、constructor 自身失败四种真实选择。
保 matcher 原 source、own bool/branch/state、constructor own N/R 全槽、chaining
原异常及新异常、最终当前 packet/host/call state。关键反例是错原异常/旧包、
错误生命周期边界、缺本实例构造/chaining/关联、删除可选附件和 budget1。
不做 raw×phase×出口笛卡尔积；不让 observed bool 或同型值代替独立来源。

源码检查核 bare/explicit None、嵌套同步 return、仅嵌套 yield、默认参数 yield，
以及 fingerprint/版本/缺源码/预算/错误 span；编译失败仅生成准确源诊断。
所有目标代码执行数为零。已有完整自然 Return 与旧 2058 项义务同源保留。

F19 下一有限组先复用本门 native 观察与既有端口：真实终结后的新 athrow/aclose
无 Drive 回复；graceful aclose/await handoff；非法 yield 后同 R、新 R、同 B
续体及最终终结；准确 helper/packet/fullstate、错误 F/release、缺采与预算。
新规则确有必要时另冻结最小合同，不能默认由本轮 F18 关闭。

## G5：所有权与串行执行

本计划冻结后才授权源码写。作者只写下列路径，先互通 fixture/capture API。

- root：计划/原义务/档案/检查点/Git；NEW `test_program_async_terminal_inventory.py`
  的旧产品首红；旧 `protocol_async.py`、`async_session_sources.py`、
  `execution/resumable_sessions.py` 的 source-first 校验和准确 BodyRaise 传播。
- A：仅 NEW `tests/fixtures/program_async_terminal_graphs.py` 与
  `tests/unit/test_program_async_terminal.py`，F18 body 内原图和静态正反。
- B：仅 NEW `scar/analysis/source_compilation.py` 与
  `tests/unit/test_source_compilation.py`，G3 派生检查/源码正反，不碰 codec。
- C：仅 NEW `tests/fixtures/execution_async_terminal_graphs.py` 与
  `tests/unit/test_execution_async_terminal.py`，实际发生、当前状态与缺采。

所有作者 FROZEN 后，只有 root 串行执行 Python/pytest/probe/compile；运行中
不改源码。先首红→定向→一次完整 affected selection；扩大仅为具体旧 gate 风险。
本门 Program26/旧 wire 和 Execution8 不变，旧测试/fixture 字节不改，原 2058
身份必须精确保留。若发现必须改旧合同/能力，先补具体设计再改，不能静默扩域。

## G6：收门与后续

保首败、撤回前提、所有源码快照、命令/JUnit/指纹、独立只读复审和原条目映射。
原单位真正成立才关对应行；仍开放条目逐项保留。正常 commit/push、核远端
完整 SHA/0–0/干净及保护仓库状态。完成剩余族后返回 P4 component/冻结 full、
P5、M2 原清单，按第一阶段矩阵核完才向用户解释完成情况。
测试时间不是性能结果；本轮没有可信 LeWM 变换或加速比。
