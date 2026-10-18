# P1 Q 账本独立只读审查

范围：`composition.py`、`composition_requirements.py`，以及对现 public wrapper/原 Q records 的接口核对。没有修改产品/测试，没有运行 pytest、probe 或目标程序。本文不是作者自审，也不替代冻结组件/全仓。

## 初次审查指纹

```text
6190ab8faa17c4b2823a061ce5179fb850fa9dd32c77806f04bc478052171852 scar/ir/execution/composition.py
5f9ab2d35da66962174feaf7ea7962c472bc108276efe3c134744114791d46ad scar/ir/execution/composition_requirements.py
```

## Q1 — OPEN：多 requirement 的预算游标没有精确定位当前组

`composition_requirements.py:398–418` 同一 output slot/facet 可以匹配多条原 ObservationRequirement，每条又可以有多个 roots。`root_owner_joins` 截断游标只包含 scope、obligation、当前 roots 的 index/pending，没有 requirement ID/ordinal。`pending_root_joins` 只累加当前 requirement 的剩余 roots，随后外循环 break，未给出后续 requirement groups 的数量/位置。

最小结构反例（源推断，**未运行**）：一份合同/slot 对应 r0、r1、r2；每组至少一个 root；预算恰好在 r1 的 root[0] 失败。现游标 index=0 不能区分 r0/r1，pending_root_joins=1 也没有说明 r2 未处理。原全量 requirements/roots 仍在，状态仍 TRUNCATED，所以不是错误授予优化或假成功；问题是本门承诺的精确未检查账本不完整。

最小修正：游标附原 requirement ID 与 candidate ordinal，保留当前组 remaining roots，并明确 remaining requirement groups/下一组位置。无需为得到精确总 roots 提前做未预算扫描。已通知 root 与 P1 owner；root 已要求 owner 最小修正并用 bounded 反例验收。等待其最终 SHA 后只对这一点追加 closure，不覆盖本初审。

## 其他已审关键关系（静态结论，有范围）

- **原合同分母独立**：`_resolve_contracts` 从 exact SemanticGraph Contract 读取 required_outputs/required facets；`planned` 不从存在的 requirement/root/read 集合反推。删除整个 Q 行仍能得到 REQUIREMENT_MISSING；删除根为 ROOT_MISSING，截断状态不变成缺失已证。外部合同缺失保持 UNRESOLVED；存在图中的错 ContractID 明确失败。
- **全量行保留**：返回的 requirements/roots/content_reads 引用原 model tuple，不由 scope 或预算过滤。候选匹配索引可部分，但 `*_scan_complete`、pending/cursor 与 per-scope pending_obligations 区分派生扫描与原分母。
- **owner 不按 same-run 合并调用**：`_root_owner_match:175–219` 对 activation 要求已知 scope 一致且 anchor 属于该 activation；已知另一 activation 即使同 run 也只为 UNRESOLVED。operation scope 要求 anchor_operation 精确等于 owner，同时排查 run/activation 冲突。Run scope 只能说明所选 run 的归属，不自动变成每次调用的独立义务。
- **跨调用声明不冒 identity**：Root 的 anchor、interval、actual owner 共同参与匹配；actual 为别的 activation 时保留未决，不按相同合同/同类型/原始名称直接消账。此层只对账已有 root 声明，不证实际 required-output slot 的内容；输出状态明确为 ROOT_PRESENT_OUTPUT_SLOT_UNVERIFIED。
- **读缺失不造工作**：`_root_read_links:264–279` 无 read 保留 NO_CONTENT_READ_DECLARED_PROTOCOL_UNCLASSIFIED；不会创建 Mat/ContentRead/ticket，且 root 身份与义务仍在。`scope_complete_for_request` 的窄定义是已请求义务的声明映射推导，不是 content/协议/native/runtime 完成；公共顶层相应权限仍 False，不能把此局部字段用于安全删除。
- **facet 不伪闭合**：required facets 的所有状态始终 FACET_TARGETS_UNINTERPRETED，存在 endpoint candidate 也只追加声明候选后缀；未定义目标/基数不报全部满足。
- **scope 仅查询输入**：CompositionScope frozen/slots，exact ContractRef、typed owner、FactSource；重复 exact artifact+ContractID+owner 拒绝，URI 只是 locator。ProgramGraph/ExecutionModel 无新增 scope 表，codec 无对应新能力或 scope 序列化。公开方法对 scope/owner/budget 的预校验与外部图读取分开。

## 终态范围

初审为 **OPEN(Q1)**，其余上述点没有发现权限提升或 scope 分母被已连接 roots 替代的具体缺陷。没有宣称完成自动合同恢复、所有调用实例适用性、endpoint 协议解释或 runtime capture。作者 focused 数据由作者日志负责，本审查未重复执行。

## Q1 窄复审 closure（保留以上原 OPEN）

最终读取 SHA256：

```text
6190ab8faa17c4b2823a061ce5179fb850fa9dd32c77806f04bc478052171852 scar/ir/execution/composition.py
7f3c536a36ddcc905a0200c440c2e2d62660aba49fd1be3104bd9de7893da601 scar/ir/execution/composition_requirements.py
2accdc3ee3992892fba56f5f97bc71dddf457ee3eb7e4b4785e3a3cc2d2d080e tests/unit/test_execution_composition_scopes.py
```

**Q1 CLOSED，PASS_WITH_SCOPE（静态窄复审）**：当前 lines 398–418 在 candidate requirement 迭代中保留 ordinal；截断 cursor 同时附原 requirement ID、requirement_ordinal、组内 root index、当前组 pending_root_joins 和 pending_requirement_groups。lines 471–472 在 obligation 本身保留两种 pending 数；全量 candidate_requirements 仍回显，故无需未预算扫描后续 roots 即可定位剩余组。原 TRUNCATED 与 owner_scan_complete=False 分支保留，没有借修正提高任何 proof 权限。

新增原 canonical 反例 `test_root_owner_join_cursor_names_current_and_later_requirement_groups` 实际构造三条同 slot requirements/roots，先断言 `_analyze` 有效，再用 budget=8；其断言精确要求在 requirement[1]/root[0] 截断，当前组剩余 1、后续组剩余 1，并保留所有 requirements 与 TRUNCATED。这直接针对原 Q1，而非仅匹配任意 gap/无效 fixture。作者报告本轮 10 PASS；本复审没有重跑，也未将作者终态冒充独立执行。

仅关闭本次多 requirement 游标问题；不扩展到自动 Q 恢复、真实 output slot 对应、endpoint 基数/协议或整个 R3.2 验收。此后报告冻结。
