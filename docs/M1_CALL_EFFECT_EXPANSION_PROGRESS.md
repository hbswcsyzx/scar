# 调用效果展开：实际结果与边界

2026-10-19，基线 `51a6eb3354eb05f7c02c9ff189239166f2cd4081`。
范围、精确旧测试迁移分别见 [计划](M1_CALL_EFFECT_EXPANSION_PLAN.md) 与
[迁移合同](M1_CALL_EFFECT_EXPANSION_CODEC_MIGRATION.md)。

## 1. 本门改变了什么

五类核心实体仍为 Operation、Value、StateLocation、Region、Resource。
新增薄关系 `CallEffectExpansion(operation, callee)`，引用原调用及其原实现区域，
表达整个调用的效果均在该区域中表示，包括入口、退出效果。
它不表达纯函数、内容相等、当前状态、真实来源或优化许可。

原 `.callee` 和动态 `CallActivation` 只能确定调用和端口，不能排除实现之外的效果。
因此不能只因看见函数体就越过旧父摘要。仅显式完整展开声明允许查询改查实际
实现；声明本身仍需未来自动前端和来源证据建立，不能靠人为标记完成自动分析。

保持查询从第一个实际子调用 source AFTER 的 suffix，经过准确 completion、
全部状态槽及 caller，走到第二个实际子调用 target BEFORE 的 prefix。
原父摘要、原输入输出和每个原 CFG 位置均保留；不消费 source 的独立写入也检查。
区间外写入仍在图和捕获里，只是不被错误纳入当前区间。
只进入 prefix 时不要求尚未经过的未来 completion；需要返回 caller 时必须要求。
原 WRITE、opaque primitive、缺关联或原端口、别名未排除、预算耗尽仍阻断。

## 2. 真实失败，没有删去

档案根目录：`artifacts/experiments/b1_call_operands/model_call_effect_expansions/`。
每次测试均有命令、解释器、JUnit、日志、源码前后指纹及所有相对基线改动的字节。

| 实际尝试 | 结果 | 发现及处理 |
| --- | --- | --- |
| initial-explicit-contract | 31 通过、14 失败 | 新 fixture 把原终结点改为 JUMP 后保留未绑定的旧 payload Uses；新子类用例前提错误；区间查询仍被父摘要阻断 |
| corrected-cfg-original-query | 3 通过、11 失败 | 纠正新 fixture 的真实端口后图合法，暴露精确区间/普通 CALL 状态缺口；旧子类限制仍在 |
| ordinary-current-version-counterexample | 1 失败 | 普通 CALL 返回实际 StateVersion 后，动态 current 仍指向 caller.initial |
| precise-expansion-and-current-state | 45 通过 | 12 个静态、20 个 codec、13 个动态用例，同一 884 文件源码指纹稳定 |
| verified-final | 2016 通过、0 失败/错误/跳过 | 原 1956 项义务、45 个新用例及 15 个既有相关 call-order 用例，同一冻结源码 |

子类失败不是新增关系引入的公共兼容性回归。隔离基线 reader24 已在新关系加入之前
以 `address_graph` 拒绝 Derived。修正的是 NEW 用例的错误假设，旧地址校验器未改。
该用例身份和全部失败快照保留；局部新关系校验可处理 Derived，不宣称公共支持已修。
见 [前提纠正](M1_CALL_EFFECT_EXPANSION_TEST_PREMISE.md)。

普通 CALL 状态问题是真实建模缺陷。静态校验原本按状态结果更新 current，动态
flow 却只更新值环境和 StateAccess.after。现按实际普通 CALL 状态结果更新 current
及 definition；结果或 occurrence 缺采时置 None，不能保留旧版本。
INVOKE、BodyDrive 仍仅沿实际完成 EDGE 更新，版本更新不证明内容相等或保持。
见 [状态流补充](M1_CALL_EFFECT_EXPANSION_STATE_FLOW.md)。

独立审查曾提出“普通 CALL 同时含 StateAccess”的反例，但核心校验明确禁止该图形。
该候选被撤回，未把不合法图当作产品缺陷，也未扩大修改或增加无效测试。

## 3. 查询前后对照

同一 `probe_interval.py` 的 before/after 输出分别绑定当时实际源码，不覆盖前档。
正常 suffix→caller→prefix、异常路径、不完备父摘要、无未来 completion 的 prefix、
普通 CALL、无未来结果的普通 CALL 六个供图查询，修复前 preserved 均为 None，
修复后均为 True。所有结果仍 `source_runtime_verified=False`、
`transformation_authorized=False`；原不完备父摘要标志没有改写。

这验证给定原结构与声明下的精确区间推导，不证明 adapter 可自动恢复该关系，
也不证明真实 Python/native 边界均已展开。底层真实 unknown 仍然是缺口。

## 4. 回归与兼容性

Program25 才允许非空新表及严格 tag；不带关系的图保留原 1–24 wire。
新 codec 测试从隔离真实基线 encoder 取得 Program24 字节 oracle。
Execution8 不变。旧 16 份测试只有迁移合同列明的 24 处字符串替换；旧 fixture 不改。
1951 个旧精确 testcase 身份与 5 个显式 future-version 身份迁移共同保留 1956 项义务。
15 个 call-order 用例是此次新增覆盖的既有回归，不算新实现用例。

最终相关回归为 **2016 passed in 862.05s**，wrapper 用时 863.1272216429934s。
884 个源码文件前后指纹均为
`8f1564e887ec631f21671274fa2ac25e26898ce9dd0aae0e2a1466636c4d19ad`，
与 45 项新测试定向通过时完全一致。命令为 conda `lewm` 环境、
`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.` 下调用本门 `run_focused.py verified-final --selection`。
机器 checkpoint 逐条核对 JUnit 身份、精确迁移、原条款 selectors 和所有历史源码快照。
这是 affected focused 的验收，不是 P4 component 或冻结全仓通过。

## 5. 对原目标的贡献与尚未完成事项

| 状态 | 本门结论 |
| --- | --- |
| Observed | 普通 CALL 实际返回状态后 current 仍旧；六个供图查询原均有具体阻断 |
| Inferred | whole-call 摘要不能直接代表内部局部区间；普通 callee 也不足以排除边界效果 |
| Proposed | 由自动前端/adapter 建立可信完整展开关系，再连接原完整程序 |
| Implemented | 薄展开关系、严格校验与 codec、精确区间查询、普通 CALL 状态派生修复 |
| Verified | 45 新用例、六个前后对照及 2016 项最终相关回归；范围和旧义务身份见上文 |
| Rejected | 无声明即跳过父效果、把独立写入排除在消费者图之外、以供图通过宣称自动恢复 |

本门补上跨多层函数检查依赖时的一个连接缺口：整调用的摘要不能无条件套到内部
局部区间，也不能无依据丢弃；现在显式表示覆盖关系并走原 CFG 检查。
这为以后分析上移、复用的合法区间提供基础，没有增加任何优化后端。

原 F16 的主 HOLD→当前 occupancy READ 仍含未展开 primitive 和其它真实阻断。
原 R3 四项阻断没有被改标签消除。此前七族及 A–H 的条件性结构验收保留；
本门没有新关闭任何族。剩余九族、P4 component/frozen-full、P5、M2 原 113 构造与
196 字段仍开放。不把 supplied graph 的通过当作完整程序自动抽象建图的完成。

LeWM 仍为外部 testcase，未改原仓库、未新增 LeWM 规则、未进行本门 GPU 性能实验。
本门无可信自动变换或新增 clean A/B 加速比。下一步见
[下一门](M1_CALL_EFFECT_EXPANSION_NEXT_GATE.md)。
