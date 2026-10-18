# V：domain 作者对 query / labeled G 的有限独立交叉审查

日期：2026-10-18。**源码审查，不运行测试/probe，不修改被审文件。** 本人自写 validator/order/stability 不计独立审查；其 owned 29P 证据另见 `domains/report.md`。

## 所审范围

- validity_query.py 的 source-first fragments、actual vs pending、source-result barrier 调用、exact production/support配对、OR alternatives、AND labeled coverage、独立 threats、预算及 detached output。
- coverage.py 的新 labeled wrapper：每个准确原 RegionRef 保留标签；union 与 single-offer 均复用原 geometry；holes/stride/unknown/empty/symbolic intervals 不换成 bounding box 证明。
- query.py 的 fresh snapshot refresh、调用前参数校验及公共 validity 接线；root effects/production_ranges 的共享原端口解释只作接线背景。
- 阅读了实际 `test_execution_labeled_coverage.py`、`test_execution_validity_query.py`、`test_execution_validity_connections.py`；query owner 的 attempt007/stdout.log 为 25P/2.34s，result.json wall time 2.996s。该结果由对方执行，本人未复跑，也不据测试数推模型覆盖率。

## 确认的有限正确连接

1. production(ctx,...) 的来源全集先枚举，fragment 不接受 caller 贡献全集；删除 Write/Outcome 不会自动删除 raw source。orphan support 被保留诊断，不成为独立来源 writer。
2. actual 只引用原 OutcomeProduction/EstablishedProduction selector；pending 无 terminal 时仍调用共用 source_result_barrier。strict source 结果已存在却未 join 时不使用 requested fallback，不从原 payload 发明 WorkOutcome/actual selector。
3. 匹配 tuple 保留原 write/stage/production/placement/version/consumer；错误版本不参与需求覆盖。OR 在相同 fragment 的 alternatives 内组合，一条 MISSING alternative 不覆盖另一条 MATCHED。partitions 保留每段 label，不把两个集合交叉配对。
4. 源/lineage、关联、geometry、order、threat、formula 共用 ValidityBudget；快照/重放、结构 FK 验证、detached copying 成本明确在该预算之外。没有“4096 限制所有 CPU 工作”的声明。
5. 外部图按 fresh snapshot 复核，输出 deepcopy；原 support/query flags 无 runtime visibility/transform 提升。Endpoint 无已解析协议时仍 unresolved/MISSING，whole-work HB 粗对应仍 ASSUMPTION；这两项不是来源已闭合或 full M0–M2 完成。

## 需 root 关闭的源码候选（未独立运行）

### Q1：不完整覆盖下，非必要的坏 fragment 可能污染全局状态

所审 query SHA `29a5311c...` 中，循环内 `blocked` 对任一 visibility-MATCHED 且 stability-CONTRADICTED 的同版本 fragment 做 OR；最后只在**整体** conditional coverage COVERED 时优先 MATCHED，否则任意 blocked 都使整体 CONTRADICTED。

最小机制：good A 覆盖 [0,4)，历史 A' 同样覆盖 [0,4) 且已被 A 后续写失效，缺 B=[4,8)。A' 不是所需覆盖中唯一可选的 leaf；剩下只有 B 未决。但现布尔式会给整体 CONTRADICTED，而非 MISSING。这与代码注释“only blocked necessary coverage”还不一致。完整好组合下能 MATCHED、单 fragment 多 alternatives 的 OR 正例，都不足以排除此形状。

已发 root/query owner，请其用一个真实历史/当前 duplicate + 缺另一半的 case 核定；本人未造 probe，不能称已复现。建议沿 labeled G 在需求 portions 中判断“无 good label 且有 blocked label”的必要被阻区域，不能只 OR 全部坏 leaf。

### P1：通用 actual 与 Mat scope/allocation/subset guard

query 作者独立指出 root production_ranges 中 Unresolved rule 不能绕过 scope/allocation/subset。root 已确认接管把这些通用结构 guards 提到 BytePrefix 外，并追加严格反例。本报告读取的 sharedrange SHA `e657ea85...` 是修正前背景，不把它当最终 closure；等待 root 给最终 source/hash 后只读补 receipt。本人不改/重测该文件。

## 读取绑定

```text
29a5311cbf91aed6b4a399a2ec8faab1e7a662cb8f38267ba142add80121b810  scar/ir/execution/validity_query.py
53da83b9cb3b67ae63a12163d74e58cf9d9d6d76511e2d4011a6918d43c59411  scar/ir/execution/coverage.py
b2bb3bfd92f2dd1ee6d71cc9a8b0bdebad519cfa43065244b1d2e1621739deec  scar/ir/execution/query.py
e657ea85c609c8e6f975b7bcfa9d0787f6ce00bc1cd704362a4de69c01f69f81  scar/ir/execution/production_ranges.py
fd3d756ea382af33916ae6076b17e71a7bc3bc59a45db30c2b7974b573534e6d  scar/ir/execution/effects.py
f2b4a216e1726412f5f16722cfbef98519869ef761df07e17374d4259d5427ee  docs/M1_VALIDITY_API.md
7f03a2d6a85daf35ad9fbf909be16fb5b2e3e9530d7145e102a8f549b259a35e  docs/M1_VALIDITY_PLAN.md
478eb976dc8aef267bce1d5fbd50beacb6cdeef6797d7c6c417c0cc21895a5fe  tests/fixtures/execution_visibility_graphs.py
26c010a776a3158357e2f4ce2a700bcc4a8258a9aed571f1b27ebf3d9ecf0794  tests/unit/test_execution_validity_query.py
0a53b32778478e531ef9b5515850071e775ce56770da7d04c1a9126157ce8808  tests/unit/test_execution_labeled_coverage.py
ae8d232b20240c951655cc3c944125e3dbd6936f0d80d7fb4a60820d88f8098b  tests/unit/test_execution_validity_connections.py
```

当前结论：labeled G、source-first tuple/OR、预算/新鲜快照接线的有限审查未见额外阻断；Q1 尚待 root 核定、P1 待最终 narrow closure，**此版本不写最终 PASS**。不将未解析端点或 whole-work protocol 冒称已支持；不要求当前 V 交付 native capture/backend/LeWM 自动化简。
