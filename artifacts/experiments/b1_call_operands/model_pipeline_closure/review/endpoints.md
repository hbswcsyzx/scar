# R3.3 endpoint / P-V 有限独立复审

初始状态：**OPEN，等待 A 修复两项具体接线问题及冻结 SHA**。
本报告只审其他 owner 新增端点规则/接线，不把本人已有 P/V shared 内核或 host-order 自审算独立复审。
只读源码与已存日志；本人没有运行 pytest/OS/probe，也没有改 product/fixture。

## 初始源码发现（source-inferred，未运行旧实现反例）

### R1：Work OutcomeProduction 没有转接 actual_selector

`production_ranges.resolve_actual_range:202–204` 新增 `actual_selector`，但初始
`production_validation.produced_errors` 的最终 resolved dict 只取 actual/requested/rawprofile，没保留该字段。
`validity_query._fragments:83` 已统一改成 `actual.get('actual_selector')`，因此原 Work OutcomeProduction 的
actual selector 变 None；Host EstablishedProduction 通过 `**ranges` 保留字段，故 pipeline Host endpoint 正例不一定暴露该错误。

最小机制：既有 `visibility_execution(right_terminal=True)` 的两个 WorkWrite 有准确 OutcomeProduction，
进入 _fragments 后 actual=None，不能生成已知 Region coverage。现成旧用例
`test_two_actual_partial_results_cover_whole_only_after_each_own_support_matches` 即对应此义务。
新 endpoint WorkWrite 同样无法让 `_endpoint_visibility_matches` 取到 actual descriptor。
建议：resolved_produced 保留原 ranges.actual_selector，原 RegionRef 与新 endpoint descriptor 一起传递；不改 producer/selector 原记录。
已立即通知 root 与作者，尚不将其写成运行复现或已验证关闭。

### R2：endpoint coverage 后半段未按共享预算计费

初始 `validity_query._endpoint_coverage:189–208` 在已按 offer 计费后，免费构建/排序 boundaries，
并对每个 portion 重扫所有 accepted offers 生成 labels。N 个不同 prefix 最坏 N² 次标签比较。
之后 support_formula 的扣费在该物化之后，不能反过来约束先前派生工作。
建议：边界构造/排序和每段 labels 扫描都用同一 budget，在工作发生前扣费，失败保留 TRUNCATED/未完成部分。
不要求新复杂算法、提高默认预算或扩大规则。root 已确认交作者最小修复及必要预算反例。

## 已核对的范围和正确约束（待最终 SHA 重核）

- `endpoint_protocol.py:69–159` 仅解析 exact artifact schema/root locator/UTF8/固定六字段 JSON，最多4096bytes。
  重复键、bool/负数/零 READ/零 WRITE_REQUEST 非法；这些检查先于非零 offset 的 unsupported gap，不能借未知 offset 掩盖已知错误。
- READ/WRITE_REQUEST/WRITE_ACTUAL 是独立定义；WRITE_ACTUAL 允许0。Read demand来自原 ContentRead 的 READ profile，
  不能从 native written count 把8byte请求缩成4byte。selector/interval/visibility三者要求相同 scoped FactRef/READ角色。
- `source_byte_input` 只连接 writer-owned 原 Use→actual ValueOccurrence→唯一 ContentRead→DataIdentity→scoped Mat/version。
  source storage 与 destination endpoint Mat 可以不同，但不能仅凭版本推断 encoding 等价；native consumption 仍条件未证。
  源 rank-one contiguous uint8 几何长度核请求；storage offset 与 endpoint offset 分开。
- `production_ranges` 仍核原 RawRecordRef、closed native count payload、准确 result locator/原结果；request与actual count分别匹配。
  Endpoint actual 保留原 target 和 MatRef；unknown rule/协议不靠 enum 或相同 FactRef 自证成功。
- `validity_validation._endpoint_visibility_matches` 要求 read/request/actual 同 target、同 exact MatRef、同 scoped版本和固定角色。
  不能用同版本/长度的另一个 Mat 代替；WORK 必须本 ticket 的 COMPLETED 与准确 quiescence，Ordered 不授 endpoint可见。
  Source/native/coherence/capture/identity/transformation 不因条件 MATCHED 获得证明。
- `validity_query._coverage` 显式按 RegionRef / endpoint descriptor 分类，异族 offers保留 unmatched/gap，
  不把 endpoint送 storage geometry，也不让 storage Region 冒充 file bytes。
- `validity_stability` 对 endpoint不同 declared target仍保留可能alias，不宣布 disjoint；同target按actual prefix判断，
  不把requested extent当实际覆盖。原独立来源、canonical WRITE/opaque/retirement/handle end扫描仍在。
- profile cache含snapshot identity+scopedartifact+locator；fresh reset明确排除 `_endpoint_profile_cache`。
  未执行 URI/provider；公开query重新核payload，老verified cache不能遮蔽catalog内容变化。
- parser/结构校验与prepared snapshot/replay成本另列；公开 P/V 的 profile/range/coverage/order/threat 派生必须沿sharedbudget。
  当前 IO fixture 的大预算是已报告的有限遍历成本，不把131072称默认4096或CPU/LeWM加速数据。

## 初始阅读 SHA256（不是最后冻结 receipt）

```text
4b9cf7163c498ce85e654c3c1ff2ac863dab8efb9fae471bf07398535ed037fb scar/ir/execution/endpoint_protocol.py
e54ec95c69d80b5e00d4b59e4f98aca1bf3c9a9029bde28f0b7bae0f9043071f scar/ir/execution/content_validation.py
2ee63f5d74cb9e75d3c7991318ca6fdcc125f2b9b3b09cfc0912726ce952ed17 scar/ir/execution/production_ranges.py
48cceaa0878db98508f4700ad24eb1b02b889219a8531aee0d7e69e3ca21c703 scar/ir/execution/production_query.py
05aa73928f0fc91dbae647031d57121ce19d4319e386d9e9961a8120987182a4 scar/ir/execution/production_validation.py
9fae7a4d2c0d171b6e370a4a153aa10f0483f8227f49318173bf75dab9ca16c5 scar/ir/execution/validity_query.py
81edc6774599ff508bcd55de10ba000a2e51f504f0b4bf3cd4e5823e82a9f564 scar/ir/execution/validity_validation.py
ef78805eba6be300dcc222836b8920910720b811ce19c15f1f327ac2000adea6 scar/ir/execution/validity_stability.py
```

以上两个风险只称源码推断；A 仍在收尾，需核实际最小修复、原失败日志和最终 SHA 后再追加有限结论。

## 窄关闭 receipt（保留以上初始 OPEN）

结论：**R1/R2 CLOSED；本次有限独立源码复审 PASS_WITH_SCOPE**。
这是源码接线关闭，不将未运行的旧实现反例改称实测失败，也不依赖新增 testcase 自证源码事实。
本人本次没有启动测试、OS witness 或 probe，没有修改 product/fixture。

- R1：`production_validation.py:248` 将原 `ranges['actual_selector']` 保存到 resolved_produced，
  `validity_query.py:83` 的统一读取因此同时保留原 Work RegionRef 和新端点 actual descriptor。
  没有另造 actual、producer 或回退成 requested extent。
- R2：`validity_query.py:223/230/243` 分别在构造边界、排序、逐段扫描 accepted offers 之前扣同一共享预算。
  不足时结果保持 UNRESOLVED/truncated；部分标签不会伪装成完整支持。
  已计费的边界序列与 next_pair_index 原样留在 pending_portions，未再将 cursor dict 转成仅含键名的 tuple；
  原独立 required read interval 及未处理 offers 保留，不把8byte需求缩成已写4byte。
- 未改动模块与初始阅读 SHA 一致；上文 exact profile、原 Use/Mat/target/result、selector family、fresh cache、
  whole-read stability 及条件权限边界仍适用。准备/FK/snapshot replay/copy 成本不冒充 shared derivation budget 的总 CPU 上界。
- A 的有限 budget/合法另 EndpointMat focused 收尾由作者/root 负责；本 receipt 不新增或合并其测试通过数，
  不将早先 pipeline 大预算结果当本次修复后的性能结果。

本次关闭绑定以下实际源码 SHA256；若之后 product 改动，须另追加 diff receipt，不能用本结论覆盖新代码。

```text
4b9cf7163c498ce85e654c3c1ff2ac863dab8efb9fae471bf07398535ed037fb scar/ir/execution/endpoint_protocol.py
e54ec95c69d80b5e00d4b59e4f98aca1bf3c9a9029bde28f0b7bae0f9043071f scar/ir/execution/content_validation.py
2ee63f5d74cb9e75d3c7991318ca6fdcc125f2b9b3b09cfc0912726ce952ed17 scar/ir/execution/production_ranges.py
48cceaa0878db98508f4700ad24eb1b02b889219a8531aee0d7e69e3ca21c703 scar/ir/execution/production_query.py
63f55ef4c4270f137d62799874ee51b783f562fc5086005e3f1769e8571158aa scar/ir/execution/production_validation.py
cf1ff0f076939d04357cb64a2b03af5d77fb7aad7a1d9243465d2ad452ffea0c scar/ir/execution/validity_query.py
81edc6774599ff508bcd55de10ba000a2e51f504f0b4bf3cd4e5823e82a9f564 scar/ir/execution/validity_validation.py
ef78805eba6be300dcc222836b8920910720b811ce19c15f1f327ac2000adea6 scar/ir/execution/validity_stability.py
4b828b9a95b5d46b82c5fb3045d514b277dd586bfa3747376807e64f2a624896 scar/ir/execution/validation.py
48f0ad6a8d6e124d73ca39816b30dfc3e52fdaece3cab02881acda706cdf407e docs/M1_PIPELINE_CLOSURE_API.md
```

范围：固定 zero-offset byte-prefix 端点协议与既有 P/V 的准确关联和预算；不是通用文件系统可见性、
flush/close/persistence、native identity/authority 或运行恢复证明。条件 MATCHED 不授 transformation；
完整 M0–M2 仍未完成，不产生 LeWM/GPU 加速结论。

## 联合组件兼容诊断窄关闭 receipt

联合组件首次 722 cases 中原两个 unsupported 端点用例失败（720P/2F，root 保留 component/attempt001），
不是上文两个源码推断问题的旧实现实测。两例原 status=MISSING 与 content_selector_protocol_unverified 仍正确，
回归在于少了原 `validity_endpoint_interpreter_unsupported` 诊断。作者在 endpoint_diagnostic/attempt001
另行复现相同2F；attempt002 原 JUnit 为2 tests/0 failures、pytest time0.522s。以上均为他人已存日志，本人未运行测试。

本次只读核对 `validity_validation._supports:459–475` 的最小修复：
在本条 support 的三个 profile 解析前记录 gap 起点；仅至少一个解析结果 None，且本次解析新产生
`endpoint_profile_unsupported` 时补回原 unsupported 诊断。不扫描之前 support 的旧 gap，
不将缺 bytes/malformed 单独改称 unsupported；三个固定受支持 profile 均解析成功时不进入此分支。
没有修改原状态判定、端点身份/Mat/请求长度/实际结果或权限条件，也没有修改旧测试以绕过兼容义务。

结论：**该兼容诊断回归 CLOSED；有限 PASS_WITH_SCOPE 保持**。
本次更新只绑定 `scar/ir/execution/validity_validation.py`
SHA256 `45e5e6cf5daf1a29b91778c03f7334a580e5bca311e76fb7895c5ab8a048a84f`，
替代上一 receipt 的 `81edc677…`。重核 production_validation `63f55ef4…`、validity_query `cf1ff0f0…` 未变，
R1/R2 关闭保持。本人没有运行测试/OS/probe，也没有改 product/fixture；不将本 receipt 写成最终联合组件通过。
