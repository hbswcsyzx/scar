# D2.3 terminal E/F/T 独立有限审查

## 结论

**BOUNDED_PASS：未发现阻断性模型错接或权限提升。** 此审查针对另一 agent
编写的 terminal 流分析与其测试，不将本人先前 records/wire 自测算作独立审查。
只读源文件和已有日志；本轮没有新 pytest/probe/采集，没有 tracked 文件修改。

审查绑定：

- `lifecycle_flow.py`：`8adaa530a1801949a0706948c9aef2410148782fa95e49da18706ed5c794fae0`
- `test_lifecycle_flow.py`：`af4efa34a3fe50337050a6b20f08e32fdc92db47fb0f6d363dffc5414689efff`
- 冻结合同：`94e0e84e918129875ae0f913095015ecef42ee9c25bb8305d96135ce9b8ef699`

## 实质检查

1. **entry / bottom 分开**（87–89、182–199）：真 entry 只有引用自反、F=false；
   其他块从 None 不可达起步。meet 忽略不可达入边，而非把“可达但无F”当证明。
2. **E/F 沿边同时改名**（91–116、163–176、188–189）：每条真实 CFG successor
   分别从同一旧快照读 actual，完整覆盖本边的 Reference formals；fresh 边界独立
   forget。swap 不顺序污染，多个 formal 取相同 actual 恢复 alias；unknown 不当 disequal。
3. **静态 ID 不授旧 incarnation**（150–180）：ordinary Reference results 定义前
   forget；block formal 在 edge rename 时覆盖。只重置目标 carrier，其余准确 alias
   可继续承载历史。CompletionResult / BodyDriveResult / ResumeInput 无虚假 copy；
   SavedInput 与 ordinary Use 通过现 canonical resolver 处理。
4. **join 保留 owner 相关性**（106–116、188–189）：先逐边 actual→formal，再 E
   intersection / F must intersection；不独立 union owner/source 后配对。现真实多锚
   shared phi、错送未 finished payload、有锚 loop 与无锚 loop 用例对应这些风险。
5. **有限队列而非路径枚举**（182–209）：E/F 的 transfer 只有 fixed forget/copy、
   相等闭包和固定 seed，meet 是 must；None 为不可达底。有限关系/位域上的单调
   transfer 与工作队列不设“跑若干轮即通过”的限额。测试中的 concrete 枚举不在产品算法。
6. **T 真正分阶段**（211–253）：E/F 已完全固定后才从空来源求 T。transfer 仅固定
   mask、copy/同时 rename、forget、常量 seed、incoming union；seed 覆盖为常量是单调
   函数，不让解释来源反过来改变 F。最终 F=true 须有非空 seed witnesses。
7. **source / query 连接**（150–159、258–283）：来源只能是本 Region 的真实
   Return/Raise publication 或 NoBodyFinish anchor；Suspend 不种 F。只读核对 query
   `terminal_release_publication` 将 anchor 回连已有 `body_publication` /
   `no_body_publication`，因此保留原 records/UseSite/StateAccess，而非新增 producer。
8. **条件性历史和当前状态分离**：unknown callback/new gate 只会按实际结果
   forget 新引用，不无故消除同 owner 历史；算法没有 consumes/drop_once/held/free
   推导。release 的结构消费仍由 core current-state 与新 shape 检查配合；F 不证明
   native profile 条件、当前 P、仍持引用或物理释放。

## 证据范围和保守边界

已核对 flow/attempt-001/002/003 的原始 result 与报告：8 PASS，随后14 PASS，
最后4 PASS/14 deselected；最终文件共有18 cases，**未把它们说成最终18一次全跑**。
有界 concrete oracle、真实 CFG 正反图是有限测试，不是所有程序的完整性证明。

该 helper 明确依赖 core/D1/publication/no-body/shape 已有效且同 Region；不能
绕过 canonical value availability 把任意静态 carrier 查询当可执行操作的许可。
不把未证明 equality 当 disequality，也未实现跨函数/callee 的一般精确 alias 推导。
跨 Region literal 的合法性疑点已被 core cross_region_use 反证，本审查没有重提为 bug。

本结论不覆盖完整 session P 流、整个新 validator、前端自动建图、runtime/source
对应、native no-reset 条件或 M0–M2 完成度；也不授权任何优化或声明 LeWM 加速。
