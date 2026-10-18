# Root gate 修正闭合复核

2026-10-18；仅复核原 `root-gate-contract-review.md` 的 R1/R2，未新增设计范围。
所审 `docs/M1_DRIVER_CONTRACT_V2.md` SHA-256：
`7899527b3896b316a4cecaea9acfd430ac1ccd6f88f2801bf8d13425210a862c`。
只读文档、无新实验/代码/测试；原报告保持冻结，SHA-256 仍为
`a46e5675b3c91c90ac25b4f8462cf05bd73dc79091c690d4a6349fb01f647875`。

## 有限结论

**R1/R2 已闭合；本次范围内 D1 gate 字段与连接规则可实施，无剩余阻断。**
这不是产品实现/实测签核，不关闭完整 D0、D1 实施验收、D2/D3 或 source/runtime 门。

- **R1 闭合：**`docs/M1_DRIVER_CONTRACT_V2.md:123`–137 明定 interface receiver 为
  Reference、scheduler 为 RAW_DRIVER_REQUEST entry；gate S 对固定入口 S must-copy；
  BODY 的 B 对 receiver must-copy 且 session=None；ASYNC_REQUEST 的 session 必非 None
  并对 receiver must-copy。每条真实 incoming 参与、拒无种子环，不以同类型/latent 请求
  或 origin 集合代替角色绑定。B/R 当前关联继续由 final gate 条件合同核验。
- **R2 闭合：**`:138`–145 明定各 gate 角色索引互异，NORMAL 转发槽与 Drive 实际端口
  各有独立 UseID；允许不同 occurrence 指同 Value。delivery 与非 STATE resume inputs
  按目标 slot 顺序一一对应，Start 两表均空；结合 §3.3 对全部非 STATE 槽精确覆盖，
  配对不再依赖猜测类型/Value。原输入→独立 edge Use→formal→Drive Use 逐槽核验。
- **相关限制保持：**`:129`–131 的唯一私有单 op landing 与 `:146`–154 的全域
  NORMAL/RAISE 后态、无回调成功窗口、拒绝不等于本 Drive 执行均未收窄。
  `:142`–144 区分真正 lookup 新结果与把新结果冒充已输入角色，不误拒正常 body lookup。
- **已撤回规则未回流：**`:156`–162 不强制独立 RequestGate/父 permit/U-A；保留真实
  早期 helper/state/source 顺序。适用失败不捏造 Python 新异常，不要求 source 自动恢复
  作为本轮字段冻结前提。
- **阶段边界保持：**`:200`–202 明确 §4 为 D2 未冻结候选，不能直接发布；有限 D1
  gate 结论不授 lifecycle/session/release 或全 family 合同通过。
