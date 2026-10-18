# R2.2 composition/source 独立有界审查

结论：**PASS_WITH_SCOPE（静态组合审查）**。本轮未运行任何 pytest、probe、采集、LeWM/GPU 或 full regression；未修改产品/测试。以下确认针对本报告所列源码指纹，不是“已实测 native 顺序”或全模型验收。

## 两项风险及关闭记录

### S1：ExternalRealm queue 的 prefix/FIFO 路径绕过 scope 门

初读代码中 dependency/wait 有 same_scope，但 prefix-member/frontier、FIFO 和 capture 派生没有完整对照。静态反例：ExternalRealm 的同一 queue instance 在 RunA/RunB 各有合法登记 work/prefix；R2.1 对外部 realm 仅保留缺口。若 pB.previous=pA、profile through=pB，原代码可以直接派生 End(A)→Start(B)，绕过已知跨 run 矛盾。相同 queue ID 不能替代跨采集/进程对应。

Root 已修，当前逐处读到：

- prefix-member 对 work scope 与 prefix observation scope；
- prefix-frontier 对前后两个 observation scope；
- FIFO 要求两个 member 已对齐，并对二者 work scope；
- record capture 对 captured prefix observation 与 marker work scope。

known cross-run 返回 issue；未知/cross-process 返回明确 gap，且不派该弧。该静态绕门关闭。这里只检查代码路径，不声称运行过新跨 run fixture。

### S2：process None 相等被当成已建立同进程

原 same_scope 对 `(run,None)` 与 `(run,None)` 返回 True。缺失身份相等不能建立同进程关系。

当前同一谓词显式检查任一 process 为 None、任一 run 为 None 或 process 不同：gap + False；已知不同 run 仍先 issue。原风险记录保留，当前静态关闭。

## 组合关系核对

1. **开始/结束区分正确。** WorkStart→WorkEnd 是资源工作边界，不是 host BEFORE/AFTER。PrefixEnd 仅是确切前缀的完成 frontier。成员 End→PrefixEnd 及前缀 End→后前缀 End 不会倒推 consumer Start。
2. **wait 是独立 queued ordering work。** 精确 event signal 约束 wait work 的 End；只有目标 queue 的适用 FIFO profile，或显式 dependency，才继续到真正 consumer 的 Start。`work_order` 固定 End(producer)→Start(consumer)。移除目标 profile 时，仅有 ConsumerEnd/frontier 路径不能冒充其 Start。
3. **pending 顺序不需要 CPUCompleted。** 派生路径不要求 outcomes/quiescences 存在；WorkEnd 节点表示条件化边界，不是“已经观测完成”。FAILED/CANCELLED 不在本门被升级成成功 content；后续生产/ready 义务独立。
4. **profile 有范围。** FIFO 只遍历 through prefix 的已知祖先链；没有 profile 不凭 queue 名、ID 大小或 host 表顺序生成 End→Start。未知 head 保留 coverage gap，不制造缺失成员，也不声明完整贡献全集。
5. **事件代次与原端口相连。** record 指准确 marker work、captured queue、该 marker 的原 predecessor，以及原 event resource access/location。AccessRef post 和 INVOKE 真实 completion/formal 均回查原 core；缺口不捏造 post。requirement-only ResourceUse 通过本 activation 的真实 realization 查 location，缺映射给 gap。
6. **旧 r1 不覆盖 r2。** wait 用原 selection Use，经真实 CFG formal→predecessor Use 追溯到同 event 的确切 post-state。已知另一 record 的 root 给 generation issue；未知中间写只给 unresolved，且不派 wait 弧。未自动把任何 state write 识别成新 EventRecord。重录新增 row，不修改旧捕获 prefix 或“取最新代次”。
7. **缺失事实不豁免明确错误。** 当前代码先检查已知 event access / selection FK；未知 marker、record 或 predecessor 不让用户自填 capture 闭合缺口。INVOKE bare argument 不能单独当 event read，须有 work 中已验证的准确 boundary effect。
8. **联合循环检查。** work intrinsic、原 dependencies、prefix frontier、FIFO、record capture、exact wait 共入同一 DAG 检查。不存在只把各自无环当总图无环的捷径；重复弧的 indegree 与 adjacency 计数一致。原始死锁/失败证据仍不等于可用顺序证明。
9. **查询有界且保留来源。** order_path 返回 typed 起终点、原关联/协议条件、路径与全报告缺口；预算截断或无路径均 UNRESOLVED，不能当 independence。相同起终点不返回严格顺序的空证明。返回 detached 副本，runtime/source/transform 标志保持 False，未派 ready/free/host visibility。

## schema 迁移边界

当前 v3 的字段/可达标签 profile 按版本分开；v1/v2 补出的新空表是 representation defaults，不是“没有 work/event”。没有代码因这些空表给出完成、ready、独立性或无副作用证明；查询缺端点/无路径不推断工作不存在。显式空 v3 同样不授覆盖全集；R2.3 不得把任何这类空表用作 vacuous production proof。

透明性：本 agent 是 codec 作者，因此本段为实现边界核对，**不计为 codec 的独立作者外审**。根部 order_validation/query 及组合逻辑是本次独立审查对象。先前 codec focused 证据属于另一轮，本报告没有新增执行证据，也不复述为本轮 tested。

## 有限结论与后续验收

在已审路径中未发现剩余具体阻断。FIFO/event/wait 协议适用仍是声明条件，来源和真实 enqueue/上下文/错误传播尚未由 native adapter 证实。该结论不覆盖实际 GPU 完成、所有跨进程导入协议、content/placement/alias 有效期、AND/OR 生产覆盖、free/quiescence 或变换合法性；这些不能由一条条件顺序路径获得。

Root/其他 agent 的新增回归、最终 component 与冻结后的 full regression 仍须独立报告。本审查不把它们标为运行或通过。Root 另计划保留原 work-codec 参数 case `[3]`，在 v3 已受支持后改为正向 roundtrip，并追加 `[4]` 非法版本反例；这是能力演进后的显式预期更新，不是伪用旧测试标签。本报告未运行该修改，也不改写此前首跑的源指纹/输出。

## 所审 SHA256

- `scar/ir/execution/order_validation.py`: `e26435e2ddbf71d7276e9ece32875f24983cbbbcb470ec973fa330437e1057ba`
- `scar/ir/execution/query.py`: `4a45323b4f213ac5fd86f2a9054f6adc1a9371fcee0414ee44348cf0505aee72`
- `scar/ir/execution/validation.py`: `6c167f7a3594bcc2e6c8872520e1b14f7c453d7f3439026028a36343e6b48f2d`
- `scar/ir/execution/work_validation.py`: `7494f8e16a3cf8d6b91224e1f75f3c4fa7f14c1a43a361fbc5818948baf7852b`
- `scar/ir/execution/order.py`: `e4ce65c33bb8169e643eb5bebd8bf5f3620d8d2cc5c8d333b62b52e2e4aea43a`
- `scar/ir/execution/work.py`: `c092b7b39691fce22d8cc00d8922cce5df4800c6ece615d28492edbd3fc6bd70`
- `scar/ir/execution/model.py`: `6d592afa5a7b8f9eab774c41f52322da6ad742c405a03e2f8448e06afdd1dd92`
- `scar/ir/execution/codec.py`: `1835a75c44b039a02a7ff79535e78786318ac37dd0e0e6bbf122e1d8f8d61ea4`
- `docs/M1_RESOURCE_ORDER_PLAN.md`: `a1f815cf4f61fd3c96056751c2eae411cdb9252a802e8659d8ce5bb49590149f`
