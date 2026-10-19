# P4：清理载荷到实际消费者的完整连接

2026-10-19，基线 `f2b4781a9afc399352a534517bc2e26a8b12b794`。
上一轮完成共享 pending payload 来源、1018 affected focused 和推送，属于 progress。
本轮继续原 P4；F12–F24/X25–X27 的16组及 P5/M2 均不删除、不提前关闭。

## 1. 模型中的缺连接

Operation、Value、StateLocation、Region、Resource 仍是规范实体；Use、原 CFG、
state SSA、pending 定义和 C1/恢复附件仍是唯一规范关系。不加第二份执行图。

三路只读审查发现：`packet_frontiers` 正确只报告下一边界，但
`protocol_continuations._close_route` 同样在 CleanupEnter/Resume/Replace 停止，
却可能把局部包来源正确写成整段 `DECLARED`。pending pack 是中间表示，不是
最终消费者；上轮已能查 source→投影后的实际 Use，本轮必须让家族检查使用它。

```text
独立 expected packet + 准确 selected completion / input case
 → 实际首交付 / pending payload Use
 → C1 action + 当前 context/state
 → 原保存/恢复、Route、Dispatch 的准确 selector/port
 → PendingPayload landing
 → 实际终端、准确父恢复槽，或尚不能解释的调用/处理器边界
```

## 2. 实施合同

- 保留旧 `packet_frontiers` 的下一边界合同和原测试。共享内部 continuation
  解析器提供另一个明确的完整性结论，接入既有 close 和 lookup fallback 家族
  查询与验证；不是只新增一个未被产品使用的 getter。
- 所有 source binding、caller/copy/pending fixed point、预算和索引复用同一个
  ConnectionContext。原 constructor/dispatch/Use 的真实位置保留为 witness。
- 从原 CFG 与固定规则发现后继和必需消费者，再对照来源；不能由用户列出的
  targets、好 pack 或一个好 terminal 定义完整性分母。known inventory 与
  source/native inventory、动态发生、变换权限分开。
- 首次交付必须保存独立 expected packet。任意 fresh Replace 不能替错包免责。
  后续合法覆盖必须保独立控制意图、准确 fresh payload 与后继；无法区分合法
  覆盖和错接时报告具体缺口，不把旧包未到 terminal 一概判错或一概判通过。
- Suspend 后继只是声明的条件恢复，保存关系和状态由原 core 核；不声称它
  在本次 Drive 已发生。Route/Dispatch 只走本条件下可能的 selector/port；
  不遍历不可能 RETURN case 来错拒 RAISE，也不把无来源 case 当空成功。
- 真正 terminal/parent packet slot 需核准确原 Use；known helper 不能凭名称、
  effects_complete 或唯一可见输出当 terminal。精确调用摘要足够则沿原结果
  继续，否则保已知消费者及明确缺口。opaque/handler/循环未解时保 PARTIAL。
- 不完整 effects 的旧 JUMP 不悄悄改为完整。旧 fixture 字节不改；新增正例若
  显式声明完整作用域，必须说明它验证供应 IR，不冒自动恢复或 native 证明。
- 截断保已发现义务、未查位置/cursor，不能得完整结论；新结果权限位仍 False。
  不更改 Program1–22 / Execution8，不加 backend/detector 或 LeWM 规则。

## 3. 自主验收节点

| 门 | 证据与拒绝条件 |
| --- | --- |
| D | 本计划、三路只读审查；冻结后再产品实现。 |
| R | 既有 close 家族在正确 pack 后错 terminal 仍 DECLARED 的真实缺陷首红；core-valid，不能只测新 API 不存在。 |
| C | 同一个真实两cut C1 及实际 dispatch/host；N→E0、R→本次自有包分别核；原 opaque 图仍有准确缺口。 |
| L | lookup fallback 的 E0/EL/EM 原三腿均有后续连接结论，删除附件不删分母。 |
| E | 错同型终端、投影后 opaque、兄弟分支/无后继、覆盖/guard、source 重求值和预算的适用反例。 |
| V | 独立复审后冻结所有源码，一次统一 affected focused，保前1018项义务。原16组未齐前不跑 component/full。 |
| A | 保失败/旧 fixture/合同/wire/保护目录，更新模型和状态，commit、push 并核远端。 |

若现有局部 DECLARED 断言需要迁移，保 case ID 和实际旧证据，明确旧断言只
证明 first handoff 的错误含义；用正确完整报告和真实末端断言替换，不能删除义务。
证据路径：`artifacts/experiments/b1_call_operands/model_packet_continuations/`。

## 4. 所有权与后续

A实现共享 continuation 解析及 close/fallback 接入；B负责首红与真实 C1/家族
正反例；C负责独立来源/opaque/预算审查和必要反例。root负责合同、串行运行、
整合、报告和版本。所有子代理不运行测试/Python/探针，不提交；不同文件所有权。

本门不是整个 X25/F23/P4 完成。后续仍须完成原家族与 P3 occurrence 组合、统一
组件/冻结全仓，再 P5、M2 原构造映射；完整第一阶段后停下向用户解释模型。
