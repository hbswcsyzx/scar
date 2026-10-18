# D2.4 公开条件 scope：只读预审

**Proposed：建议采用下列最小 wrapper；当前产品未实施。** 只读当前查询、CLI、
DriverRule/ProviderFactReference 与冻结 D2 合同；没有测试、采集或 tracked 编辑。
审查源码指纹：queries `7f119421509b7a1237304e713fb6f52d461891b802395bb46e0326e556cd1aa6`；CLI `859fa00f44644303758c0a3a8a362704d4ba38befa23c21a6d73d6513e802135`；
合同 `94e0e84e918129875ae0f913095015ecef42ee9c25bb8305d96135ce9b8ef699`。

## 1. 实质缺口

当前 LifecyclePoint 只有 terminal/session；SessionPublication 只有 post 输入/支持，
TerminalReleasePublication 只有 owner/来源。离开 Index 后，三者均丢失显式
DriverLifecycle、原 DriverInterface.rule 与条件状态。docstring 不足以承载机器上下文。
CLI 保持 authority=false 是正确的，但只对存在 session/drop 表的图设置条件推导标志，
没有按 scope 暴露原 rule 来源；旧 v12/13 显式 scope 的实际分析也未显示。

## 2. 最小接口选择

```text
LifecyclePosition = BEFORE | AFTER | EDGE
LifecycleScope(declaration: DriverLifecycle, interface: DriverInterface)
    applicability -> ProofStatus.UNKNOWN  # 只读派生属性，不是构造字段
    rule -> interface.rule                # 可选便捷只读属性，不重复存储

LifecyclePoint(scope: LifecycleScope, operation: Operation,
               position: LifecyclePosition, successor_index: int | None,
               terminal: TerminalPointFacts, session: SessionPointFacts)
    successor -> operation.terminator.successors[successor_index] if EDGE else None

ProgramIndex.lifecycle_scope(region: RegionID) -> LifecycleScope | None
SessionPublication(...existing fields..., point: LifecyclePoint)
TerminalReleasePublication(...existing fields..., point: LifecyclePoint)
```

- Scope 保存原 scope/interface 对象（is 可核对），每 Region 可缓存同一 view。
  无显式 DriverLifecycle 必须返回 None，不凭旧 DriverInterface 或 schema 版本补造。
- Point 保存原 Operation；BEFORE/AFTER 的 index 必须 None；EDGE 必须 exact 非负
  int（拒 bool）且落在真实 successors 内。successor 是原 edge 派生属性，不再存
  第二份 edge/actual/type/producer；不可假定 NORMAL 总是 index0。
- SessionPublication.point：AFTER_OPERATION 用准确 AFTER；NORMAL_COMPLETION 用
  本操作实际 NORMAL EDGE。TerminalReleasePublication.point：该 release 的 BEFORE。
  两 publication 无需再重复存 scope/operation；其 point 已完整定位。
- interface.rule.implementation 原 FactReference 已含 artifact(uri/hash/schema/size)
  与 locator，足以携带条件来源。它不是 ProviderID；不能按同 uri/hash 猜连接某个
  ProviderEnvelope，更不能把 auxiliary artifact 强制替换成 primary。若已有显式
  provider-region 关系，可继续用现 provider_region_sources 查询，不必在 scope 复制。
- 不强制把 raw terminal/session 引擎改成另一套状态；公开 wrapper 承载条件足够。
  任意调用者仍可主动剥离 wrapper，不能靠更多重复字段解决恶意误用。没有 verified
  参数、证书、动态 occurrence 或新 ProgramGraph 字段，不改变 schema14。

## 3. CLI 最小机器可读 scope

成功 validate 后列 lifecycle_scopes 数组，每行至少：

```text
region: interface.region.wire
rule: {profile: interface.rule.profile.value,
        implementation: 原 ProviderFactReference 的严格编码}
applicability: UNKNOWN
conditional_facts_derived: true
declared_counts: {body_outcome_commits,created_close_tests,no_body_finishes,
                  session_updates,terminal_frame_releases}  # 按该 Region 归属计数
```

rule profile 连同显式 DriverLifecycle 定位 D2 的 direct-owner/same-lifetime/no-reset/
NO_FRAME_INTERPOSITION 条件合同；不把固定条件的适用伪装成已证，不发明 native 名单。
全局 conditional_lifecycle_facts_derived 可由非空合法 scope 派生，表示算法确已运行，
不是存在正事实或所有 D2 功能齐备。old v11：数组空、该标志 false；old v12/13：
可有条件推导和对应原 rule，但未声明的 session/drop 能力计数为0，不能标全 D2 完成。
现 session_release_structure_validated 仍只按本 capability，不能因 scope 存在改 true。
driver_lifecycle_verified/source/runtime/resource-release/transform 等权限继续 false。

## 4. 必要验收反例（本审查未运行）

1. old D1-only 图即使有 rule，也无 LifecycleScope/Point；旧 wire 字节不变。
2. v12/v13 明确 scope 可查询条件事实，但缺 session/drop 不变成 full D2。
3. detach 出来的 SessionPublication/TerminalReleasePublication 仍保留原 scope、
   interface、rule.implementation 与 UNKNOWN；不需要活 Index 才能辨认条件。
4. NORMAL 边调换实际位置后，SessionPublication.point 的 index/edge/support 均取
   真实 NORMAL；RAISE partial state 不冒作同一个 post。
5. callback 后 P 失效、F 保留的 point 仍明确 BEFORE/AFTER/EDGE 与同一未证条件，
   不由 UNKNOWN 变 PROVEN，也不推出 refs held/free/ready。
6. bool/负数/越界 edge、非 EDGE 带 index 均拒绝；返回原 Operation/edge/UseSite。
7. 辅助 artifact 的原 fact 引用保持，不按同名 provider 自动 join 或打开并猜验证。

## 5. 边界

这是 wrapper/CLI 条件来源闭环，不是新分析引擎、不补前端、不证明真实 source/guard、
模型完整性、runtime 或优化收益；上述接口的实现和测试仍待 root 分门交付。
