# 返回后下传：原图连接实施与验收

2026-10-18。依据[冻结计划](M1_CALL_COMPOSITION_PLAN.md)，基线 `ea13ecf`。
这是 M1/P4 的一项有界连接修复；固定 F12–F24/X25–X27 共 16 组仍全部 OPEN。

## 1. 建模含义

Operation / Value / StateLocation / Region / Resource 类型不变。函数调用是
Operation，函数体是可展开 Region。调用实际参数、entry formal、Return/Raise
Use 与调用结果都是原图端口，不能因为属于同一函数或同一存储位置就合并。

```text
独立指定 expected source
  → H1 的准确 actual → entry formal → Return/Raise Use
  → H1 的准确结果槽 → H2 的准确 actual
  → H2 的 entry formal → ... → 最终 consumer Use
```

**Observed:** 旧查询在合法 `H(H(x))` 的函数体内消费者处返回 None。返回流分析
已经能连接第一段，但跨 region 查询仍依赖 recipe leaf 是否直接等于 expected；
leaf 停在前一个调用结果时，无法继续向下。这是连接缺失，不是张量内容变化。
首红在 `model_call_composition/red-downward/`，保留真实断言失败。

**Implemented:** 新 `call_composition.py` 沿原 `CALL_ACTUAL_TO_FORMAL` 配方逐段
组合已经存在的 return-aware fresh-copy 分析。每段验证准确 original actual
OwnedUse，把该调用中所有已证复制的 actual ordinals 同时种入对应 formals。
重复实参不会只保留第一个槽；相同 callee 的不同调用不会被合并。

内部 source 可以通过既有唯一 caller export 返回共同 caller，再进入下一层。
用户全局 guard 与每条 recipe 的 caller-prefix 局部选择分别作用，不能把一次
visit 的分支套在另一个 sibling 调用上。仍使用原 fresh reset、同时 CFG rename、
状态版本及 N/R 完成槽。自身未来的调用结果不能供应自己的 entry。

每条 route 报告保留原 recipe、准确 frame inventory、逐段 actual/formal/seeds、
局部 guards、support 和未决原因。拒绝 occurrence 前提不满足的 route 时，原
recipe/path 仍保留，但不再构造没有用途的 frame inventory。

## 2. 缺失分支不能从分母消失

**Observed:** 独立审查构造了一份通过 core validation 的图：其中一个合法 typed
edge-use ID 被逆向来源库存判为 `cfg_source_kind_unresolved`。该分支只留下 gap，
没有产生 recipe；剩余的已知成功 recipe 使旧连接查询整体返回 True。
`red-missing-origin/` 保存这个真实假阳性，未绕过验证或伪造 producer。

**Implemented:** `input_origins` 区分“有已知路径但 occurrence 未证”和“原输入路径
未完整入库”，新增派生诊断 `source_inventory_complete`、`missing_origin_routes`，
并在 recipe 上保留整体库存标记。标记传播到 request input、上下文关联、来源
availability 和 async 投影/packet/return 检查。已知路线的证据继续保留，缺失
路线阻止整体 True/False；不能把不存在的配方当成不存在的输入分支。

这是实际反例要求的诊断补充，没有添加 wire record、producer、状态 SSA 或第二
套数据图。库存完整只指供应静态模型的路径枚举；`caller_scope_complete=False`
等运行时边界保持原含义，不能据此声称源程序与模型已经一致。

## 3. 成本回归与修复

**Observed:** 首次统一 `final-focused/` 为 **809 PASS / 2 FAIL**。旧确定性查询的
4096 预算被耗尽；声明表重排后截断前的成本明细也不同。诊断临时以更大预算
完成清点，两种声明顺序都实际使用 4103，其中 128 来自本轮新增 recipe 扫描。
`budget-diagnostic/unbounded.json` 仅是成本诊断，不能当作验收通过。

**Implemented:** 把已由计费 `_context` 判定的 STATIC_CYCLE/not-rooted 前提检查
移到路径扫描和 frame materialization 之前。这些 route 本来就必须返回 None，
无需再扫描它们；原 route 分母和 occurrence gap 不变。没有提高预算、修改旧
断言、跳过已执行工作收费或增加广义结果缓存。`budget-repair/` 的 26 项包括
原八 hash 进程、声明表重排及本轮 23 新例，全部通过。

## 4. 自主验收记录

所有必要测试串行，作者冻结后统一受影响测试。各次记录都独立保存，不覆盖
失败批次。`state-first/` 的七个失败来自新增夹具中未定义的 `call` 变量；修正
新夹具为原 `call_id` 后重跑，保留原失败，不修改原有夹具或断言。

**Verified:** 最终 `model_call_composition/final-focused-repair/`：

- **811 PASS，0 failure/error/skip**；上一轮 788 个身份全部保留，新增 23。
- pytest **32.19s**，外部 runner **32.977299s**。
- **702 份源码**前后相同：
  `fd97098b4e65b5923b7ac07f328eaee3603e7258a12155b3a2a9504e3822db1c`。
- 三路只读审查覆盖准确调用、状态版本、路径分母；最终成本修复另经只读复审。
- 旧失败与修复批次的全部案例身份、旧证据与基线夹具通过 archive-only 检查保留。

| 本轮节点 | 验收结论 |
| --- | --- |
| D | 原连接、状态与上下文设计审查；计划指纹冻结 |
| R0 | 合法返回后下传的首红保留，修后进入最终统一测试 |
| C | serial/nested/sibling、准确实参、重复槽、opaque、guard、循环新旧值覆盖 |
| S | N/R 状态更新、未改域、内部新版本返回再下传、自身未来结果反例覆盖 |
| Q | 缺来源分母假阳性修复；部分/截断保持未知；原 4096 确定性测试通过 |
| V | 三路只读复审与 811 affected focused 通过；不等于组件/full |
| A | 独立 WIP 版本、原夹具/证据和保护 checkout 核对；归档检查启动 0 测试 |

## 5. 边界与下一步

**Rejected:** 按类型、数值相同、同 Location 或 source 仍可用就判定 actual 来源；
跨 caller 拼接、未证递归按无副作用处理、遗漏路线、未知转为 NONE/False、把
静态复制证据当运行时身份或转换授权。

**Inferred:** 这项连接能力是跨层 provenance 的必要部分，尚不能独立得出 hoist、
常量替换或删除 import 的完整修改指导。False 只表示没有该 must-copy 关系，
不是数值必然不同。一般计算的逻辑值等价、动态 occurrence 与 native 语义仍有边界。

**Proposed:** 继续冻结的 P4 异常类别 matcher：独立 packet、handler、自身
NORMAL/RAISE 和真实分支；lookup RAISE 不能直接视为 AttributeError。之后
完成原 16 组 family/组合义务，全部就绪才进入统一组件、冻结 full，再做 P5/M2。

完整 M0–M2、整个 LeWM 自动拆解建模和可信 TRANSFORM **仍未完成**。本轮没有
新增 detector/backend，没有运行组件/full、重型 LeWM 或 A/B，没有新的加速比。
所有 runtime/native applicability、identity 与 transformation 权限仍不授予。
