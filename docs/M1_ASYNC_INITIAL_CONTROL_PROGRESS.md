# 首次 ASEND 联合控制：实施记录

2026-10-19，基线 `96b8a322590217151ff6a5e839c7ab17d068f560`。
状态：**原 F16 条件性结构验收；完整第一阶段未完成。**
最终相关回归 2058 通过，0 失败/错误/跳过；892 文件前后指纹相同。
验收范围见[原 F16 验收](M1_ASYNC_INITIAL_CONTROL_ACCEPTANCE.md)，
档案的完整性与原义务守恒由本门 `checkpoint.py --check` 逐项核验。

## 范围

沿用 Operation / Value / StateLocation / Region / Resource；复用已有 R 初始、
B frame phase、None 谓词与原 RequestProcessing，不新增节点类别或影子状态。
本门计划、旧测试迁移及原 F16 合账分别见：
[冻结计划](M1_ASYNC_INITIAL_CONTROL_PLAN.md)、
[精确迁移](M1_ASYNC_INITIAL_CONTROL_CODEC_MIGRATION.md)、
[原义务审查](M1_ASYNC_INITIAL_CONTROL_F16_AUDIT.md)。

## 已有实际证据

档案：`artifacts/experiments/b1_call_operands/model_async_initial_control/`。

| 尝试 | 实际结果 | 意义 |
| --- | --- | --- |
| native-initial | 11 条本机 Python 观察，0 测试 | 证明被拒 R 不可重用而 B 仍 Created；新 R 可启动同 B；首次非 None S 可覆盖 L，后续 S 独立 |
| initial-scheduler-counterexample | 2 失败、0 错误 | 旧产品错误接受 L=None 替代首次 S=77，错误拒绝正确 S=77；两图 core 合法 |
| first-joint-authored | 34 通过、4 失败；63.99 s pytest | 拒绝 helper ordinal 查询仍未知两项、已知无效负图误先查询一项、自然 Return 的动态 host 早停一项 |
| joint-completeness-counterexamples | 1 通过、1 失败；2.95 s pytest | 真实复现未知 S 被升级为 CreatedStart=True；association-state 反例通过，不称已复现失败 |
| revised-joint-control | 39 通过、3 失败；75.86 s pytest | 来源完整性/混合 caller/自然 Return 主链已过；helper 带 choices 的重复跨区域解析仍丢来源两项，新缺采测试误认 API 形状一项 |
| precise-original-input-chain | 3 通过；15.62 s pytest | 修复原两 helper 证明；必要缺采按既有 UNPROVED 报告断言，未弱化 copy/gap/另一实例断言 |
| verified-final | 2058 通过；945.95 s pytest，947.100503 s wrapper | 2010 精确旧身份 + 六项显式迁移保留 2016 义务；新增 42 项，892 文件稳定 |

原生探针运行在前门 884 文件稳定指纹
`8f1564e887ec631f21671274fa2ac25e26898ce9dd0aae0e2a1466636c4d19ad`。
两个旧产品反例运行在增加两份新测试文件后的 886 文件稳定指纹
`7db74853798c05ec5e7463c1e69aca46d8318230b0ac498db3952940ab8693d3`，
当时全部旧产品字节未修改。首红命令、JUnit、日志、差异源码和前后指纹均保留。

此缺陷是来源选择模型错误，属于 baseline defect，不是性能优化。
第三个新来源用例要求未知首次 S 不得无条件证明 L 有效；它不伪造非 None 内容。

`first-joint-authored` 为 892 文件稳定指纹 `cc77f944…`；
联合完整性反例为 `1e64226f…`；修订 42 项为 `42b1ef24…`；
最终修复定向三项为 `f8e32575…`。档案保存各自完整散列及全部实际差异字节。
最终完整指纹：
`f8e32575b74ba5eec077c1f18f2da7fcbaf03f2443b1579c92a5e40e791bf990`。
本门新测试构成为来源选择 6、静态联合控制 12、动态 9、codec 15。

## 具体模型修复

- **Observed / Implemented：**首次 S 只有已证 NEXT/None 才选 L；非 None S
  覆盖 L，内容未知则保留原候选而不升级证明。`source_coverage` 先保所有原
  scheduler recipes；有已知和 opaque own RAW 的两个调用时，未知来源不消失。
- **Implemented：**R.initial、关联 B.Created、有效原 operand/ordinal、
  bool/BRANCH、完整 association-state 及 caller/choices 分开核，再联合到
  Start、Resume 或无 Drive 的拒绝 own N/R/host。缺附件仍保原 core 分母。
- **Observed / Implemented：**普通 `RawOperandSource` 不跨语义关联。拒绝
  helper 另外联合 Create→保存 L→association→原 NonePredicate Use→helper
  的局部 copy，普通报告 None 保在 `raw_operand_binding`，独立来源报告标
  `semantic_projection`。不把这个投影加入 copy 闭包，也不放宽非 None literal
  的对象身份规则。
- **Observed：**首修后再次带 full choices 从 root L23 重算到 helper，真实
  触发 `reference_literal_not_none`，而既有原 ordinal/caller 证明为 True。
  [探针](../artifacts/experiments/b1_call_operands/model_async_initial_control/probe_processing.py)
  保留两种拒绝的实际报告。最终实现筛选既有完整原证明，再核后续局部传递；
  已知 False、完整性不足和预算截断不能升级。
- **Observed / Implemented：**第四次 BodyReturn 已有真实 adapter；遗漏是
  动态 `_hosts` 的早停。按[独立补充](M1_ASYNC_INITIAL_CONTROL_TERMINAL_SUPPLEMENT.md)
  窄接准确自然 Return/rule/source/selected own N/R、packet component 与 host，
  AWAIT 和其它未知 terminal 不冒充已支持。

## 撤回的前提

1. association-state 首次反例实际通过，因此它只验证应保依赖，不记录成
   “旧产品已实测错误”。Unknown S 升 True 则有真实失败收据。
2. fixture 的第四段原 adapter 和拒绝 helper 的 RAW/ordinal 端口原本正确；
   不通过复制图或换 raw source 绕过查询缺口。
3. 已知错源图应由公开 validate/ProgramIndex 拒绝；首轮测试误先对无效图
   查询，已校准负例前提并保原 testcase 身份。
4. 新必要缺采的 compatibility 按既有 API 返回 status=UNPROVED 的字典，
   不是 None；修正形状断言，保留 target=None、copy_status、具体 gap、当前
   session、先前 item 和另一实例完整链断言。

## 实施与验收分开

正在连接独立 association B、有效 operand 的原 ordinal、同一路径 nested choices、
真实 Start/Resume 或拒绝 own N/R/fullstate。Program26 隔离已有 subject 的新
async 准入；无新准入时保持旧 1–25 wire 和旧 oracle，Execution8 不变。
旧 17 文件仅按冻结合同允许 22 处字面量替换，六个 future testcase 身份明确迁移。

所有作者冻结后才启动每次新代码测试；最终来源正反与全部旧义务同源通过。
最终相关选择只追加四个新模块。原选择已经包含完整 generator admission 测试，
因此没有再追加重复 selector 或扩大回归。

## 尚未成立的结论

真实 R3 opaque/write 与主 occupancy 未知边界继续保留，不要求为关账变成 True。
原 F16 已依据整组原义务与新收据达到条件性结构验收；其余八族、P4/P5、
M2 的 113 构造/196 字段和完整第一阶段尚未关闭。
本门不是自动整程序建图、源码适用证明、变换授权或 LeWM 加速比。

## 结论状态

| 状态 | 本门结论 |
| --- | --- |
| Observed | 本机 11 条 native 观察；保存的实际首红、后续失败和最终 2058 项通过 |
| Inferred | R、B、L、S、state/来源/内容须独立连接；不能由 observed bool 推出当前保持 |
| Proposed | 按[下一门](M1_ASYNC_INITIAL_CONTROL_NEXT_GATE.md)核剩余八行，返回 P4/P5/M2 原验收 |
| Implemented | 有效 S/L 选择、联合原路径、独立关联投影、自然 Return host 桥和 Program26 能力门 |
| Verified | 原 F16 的 supplied-model 条件性结构验收；八族累计接受；不授自动获取或优化 |
| Rejected | 无条件首步用 L、Unknown 升 True、借 sibling/已查前缀、将真实 opaque 翻纯及 LeWM 加速声明 |
