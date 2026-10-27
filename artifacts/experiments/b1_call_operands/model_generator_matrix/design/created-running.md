# Created / Running：原端口审查与最小实施建议

2026-10-18。基线：根代理给定 `b88670b`，工作树 `/tmp/scar-structured-model-280qf4mi`。
状态：**SOURCE_REVIEW / PROPOSED，未实现、未测试**。本轮只读；没有运行 Python、构造探针、pytest、全仓或 workload。本报告不把 source inspection 称作实际反例测试。

## 1. 先给结论

1. 现 core 足以承载这些路径的值、状态、异常、调用和控制端口；缺的是“哪个当前 owner 的哪种只读条件，控制哪条准入路线”的精确协议连接，不是新 phase 状态链。
2. **仅现 RequestProcessing(bool result,state_sites)+BRANCH 不足**。它没有 instance role、predicate 规则、自己 bool→准确分支的约束；当前 validator 对 state_sites 仅做存在/归属检查。把 Closed fixture 改名不能补上这些事实。
3. 推荐只加一个固定、只读 `AdmissionPredicate` contract，引用原 owned instance/raw/operand Uses、StateAccess、bool result；真实 BRANCH 从原 block 派生。复用原 RequestProcessing、BodyStart、NoBodyFinish 和生命周期，不加可写 `phase/entered`。
4. Created CLOSE 直接组合原 CreatedCloseTest→真实 true edge→NoBodyFinish；不要再造另一 CreatedClose predictor。
5. 还必须补精确 CALL/INVOKE actual membership 和 caller→entry 原端口来源解析。否则 fixture 中 caller 的 known SEND(None) 到 driver 入口后只能未知；不能靠相同类型、名称或一个常量宣称对应。

本报告负责 Created NEXT、Created SEND 的 None/non-None 分支、Created CLOSE，以及 Running 四请求：**7 个矩阵格、8 个主要路径**。Created THROW 有旧 foundation 部分证据，仍非本报告已关闭的一格；不把分支数冒充完整 16 格通过。

## 2. 当前真实保留能力与精确缺口

| 范围 | 现源码事实 | 本门缺口 / 预期处理 |
| --- | --- | --- |
| raw arity/顺序 | `drivers.py:73–92`：NEXT/CLOSE 0、SEND 1、THROW 1–3；`driver_validation.py:101–120`：原 RAW operation result、所有 operands 必须 Reference、op.uses 顺序恰为 operands、纯 constructor shape | **保留**。不是缺 arity。外部 entry RAW 没有本地 definition 时不能假称 arity 已解析，公开具体 gap。 |
| 本次 raw operand | `protocol_validation.py:312–340`：known raw kind、ordinal、must-copy；`protocol_flow.py:203–276`：producer 再执行清旧 copy、原 CFG 平行 rename | **保留**，但 expanded target 只 owned_use，INVOKE 中可能是 edge-only forwarding Use，未必 actual 参数；见第 3 节。 |
| BodyStart | `driver_validation.py:240–273` 核 body、entry Reference/state captures、Location、Start 无 resume inputs；`driver_flow.py:48–52` 返回原 body entry | **漏** raw NEXT / SEND(None) 准入、current Created/非 Running 条件。`protocol_validation.py:504–521` 只对 BodyResume 做 delivery 连接。 |
| Ref 的 None | 新 literal payload 与附件可精确声明；`literal_validation.py:7–51` 保 original direct/NORMAL result，不许 RAISE/forward/state 冒 literal result | **漏** protocol 消费 None/non-None 原 operand 的判定/来源闭环。不能用 ExactLiteralOrigin 给 Reference 预装，也不能拿同型另一 None 声明代替 source。 |
| 阶段判断 | `RequestProcessing` 只有 raw/operand/result/state_sites/rule（`protocols.py:304–322`）；`_state_sites` 仅 FK/类型（`protocol_validation.py:124–137`） | **漏** 固定 owner/current state read、bool 语义、bool→实际分支与 Start/reject 的连接。当前没有独立阶段证明。 |
| Running / Closed | `closed_request_program():432–488` 自己说明 Closed 是 source applicability，输入是外部 RAW；helper N/R→本次 host payload 可校 | **不能**当 Running/Closed 阶段来源正例；当前只校结果路线。源码同名、同类型都不能给出 Running 条件。 |
| Created CLOSE | `no_body_validation.py:43–121` 已核固定 owner/raw、原 bool、complete callback-free READ、全 lifecycle 当前域、紧邻真实 BRANCH；`:123–156` 核 true 私有 landing 首 NoBodyFinish、精确 owner/body 写 | **复用**。new profile 的 `_derived(CREATED_CLOSE_BRANCH)` 当前 `protocol_query.py:63–65` 按 region 列出所有 tests，未按 OperationSiteSubject.operation 精确过滤；同 region 另一个 test 不能填本站义务。 |
| F 的来源 | `protocol_validation.py:577–595` 仅两条 INITIAL_THROW clause 的 validated 精确 edge 种 F；PREENTRY_REJECT 不种 | **保留**。Running/initial SEND 拒绝不借 INITIAL_THROW 种 F；Created CLOSE 的 F 来自真实 NoBodyFinish。 |
| ledger | `protocol_query.py:82–147` 保固定 clauses、缺行/budget 和 unproved source；但 derived ingress 只列 target/inputs，未显示 phase/None 准入义务 | **扩展** derived 原阶段条件与分支义务；未知不抹掉已知 Start/拒绝错误，不将 DECLARED 当 source verified。 |

### 3. actual membership：准确区分已有 guard 与漏项

`protocol_validation.py:312–347` 的 RequestProcessing / ProtocolCall 只调用 `owned_use`。原 core `validation.py:232–253` 将 INVOKE 的 actual Uses 与 edge-forward Uses 一起视作合法 owned inputs，但两者用途不同。因此可以保持原 core 图合法，只把协议 raw/expanded/receiver/argument 指向一个**只给 edge 转发、未入 invoke_arguments**的独立 Use，协议声明仍可能错误通过。

对真正 direct CALL，原 core `validation.py:594–599` 已要求全部 owned Uses = call_arguments；不宣称它也存在该 membership 漏洞。另 `ProtocolCall` 当前没有强制 real CALL/INVOKE shape，普通 primitive 也可能被标为协议 call。

建议：

- RequestProcessing：ordinary intrinsic 仍合法；若 op 为 INVOKE，raw/expanded roles 必须是准确 invoke_arguments 的成员；若 real CALL，使用原 call_arguments。按原 actual 顺序派生，不复制 actuals。
- ProtocolCall：必须 real direct CALL 或 INVOKE；receiver/argument Uses 必须参与对应 actual list，并保原协议所声明的有序 roles；不要求它们是所有 state 等辅助 actual 的全部集合。
- 对独立 edge Uses 的错误标注，建议新 issue `protocol_actual_operand`；普通 primitive 被 ProtocolCall 冒充用 `protocol_call_shape`。这些是**建议码，尚非已运行/已存在码**。

## 4. 两种 phase 连接方案与推荐

### A. 只复用五 contract

保留 RequestProcessing，增加规则名，把 result 指 bool，state_sites 指 read，然后要求原 BRANCH。

这个方案可以表示 bool dataflow，但现字段缺 instance，无法唯一指认阶段 owner。可强制每个 StateAccess.reference 非 None 且为固定 receiver 来补，但这会把合法粗 world / 多 owner 的 `reference=None` 表达硬性缩掉；InvokeStateOperand 本身也无 owner。若改成按“第一个 Reference Use”猜 owner，又在创造未声明端口语义。只有精确、明确写入合同的 builtin operand recipe 才可这么做，不能无提示地推断。

**不推荐维持当前五 variant 不变然后声称问题已解决。** P1 §6.3 已要求 current phase + 原分支，但五变体只绑定 raw/result/state，没有 phase predicate/owner 的 typed 连接。真实矩阵反证的是这个接口遗漏，不是原 SSA。

### B. 推荐：一个只读原端口附件

以下是建议的可实施最小字段；仍待根代理定稿：

```text
AdmissionPredicate(
    instance_use: UseID,
    raw_use: UseID,
    operand_bindings: tuple[RequestOperandBinding, ...],
    result: OperationResult,
    state_sites: tuple[ExistingAccess, ...],
    rule: AdmissionPredicateRule)

AdmissionPredicateRule = IS_CREATED | IS_RUNNING | SEND_ARGUMENT_IS_NONE
```

放现 `ProtocolOperation.contract` union；outer.operation 唯一 owner，outer scope 仍原 GENERATOR_BODY_V1/DriverSubject。这里没有 phase 值、entered flag、额外 producer 或存储状态。result 必须指此 op 唯一原 `DataValue(builtins.bool)` result；rule 定义**这个原只读 predicate 的合同**，不是用户设置对象当前 phase。

**共同结构检查**：

1. instance/raw 为 independent owned Uses，分别 must-forward 原 interface receiver/scheduler；owned 不等 actual，若选 ordinary readonly intrinsic 则其输入全集须明确等于角色+展开 operands+原 state-before Uses。
2. predicate 是 complete、ordinary、callback-free、没有 callee/INVOKE/写入；state_sites 覆盖原 interface.lifecycle 每域 READ 一次，`after=None`。复用 CreatedCloseTest 的 state/shape 规则，不把 callback-capable helper 冒作稳定读取。
3. predicate 紧邻本 block 原 BRANCH；condition 为该原 bool 的独立 Use；branch 本身 complete control forwarding、无 effects。精确 true/false edges 从原 successor 0/1 派生，不再复制保存 CFG。
4. 沿原 CFG 派生当前条件支持。到相应 gate/拒绝 consumer 时，owner/raw 必须仍是这些原端口的 must-copy，依赖域版本必须仍当前；unknown callback/write 后旧 predicate 不可继续作为当前 admission 支持，需重读。原 gate 自身的 admit 后 state 仍照 D1 传 BodyDrive，不要求它和 predicate before 是同一个 ValueID。
5. `IS_RUNNING` true 路在本次协议完成前不得出现该 owner 的 BodyDrive/Start/Resume，也不得种 F；从拒绝 helper 的选定 N/R 本次 packet→host RAISE，携带真实最新 states。false 路没有独立的“允许所有 Start”结论。
6. `IS_CREATED` true 的 NEXT/SEND(None) 才允许 BodyStart；已知 incompatible raw 或 non-None 到 Start 为 issue。SEND_IS_NONE 必须准确 raw ordinal0；true/false 按原分支区分准入/初入拒绝，不调用 Python `==`，不把 False/0 当 None。
7. SEND_ARGUMENT_IS_NONE 的已知 payload 必须从第 5 节原 literal/copy 来源解析；未知不是 None，也不是 non-None。保 `send_operand_content_unresolved` 条件，不能据此把完整 SEND 格写 PASS。

若根代理决定把 SEND_IS_NONE 分成一个没有 state read 的纯 identity predicate，shape 应明确该 rule 是 pure immutable payload 检查，阶段仍来自单独 IS_CREATED/IS_RUNNING 的当前 read；不能把“少 state_sites”当可绕过阶段检查。一个 type 内的固定 rule 形状足够，不需新语言或第二历史机。

**版本建议**：如果本轮采纳第六种 contract 或新规则，Program schema18 显式 capability；旧 v1–v17 必须拒新 tag/rule/字段并保原五变体 bytes。仅原17图仍编码17或更早。若新 predicate 放原表，能力检测须逐 contract variant，而非只看 protocol_scopes 非空。修正已知 wrong wiring 不要求旧17图自动取得新的 phase completeness；旧无 predicate 图保缺口，不因 parser 版本变了而升格。

## 5. None 与跨调用来源：必须一起解决的连接

`driver_validation.py:215–219` 要 receiver/scheduler 是 driver **entry** 参数。旧 `_with_creator()` 在 `program_driver_graphs.py:226–274` 真实 caller 建 raw pack 后 INVOKE driver。因此不能为了 fixture 把 driver 内 raw result 假装是 entry scheduler。

现在 `raw_definition()` 只看本 Region 或本地 copy（`protocol_validation.py:109–121`）；`ProtocolFlow.forwards():269–270` 跨 Region 返回 None。caller 的 known SEND/ordinal/literal 没有被自动解释进 driver。

最小补法是派生 **每个静态 callsite 的 recipe**：由 callee 原 entry formal 的准确位置，反查原 caller.call_arguments / invoke_arguments 的原 Use；继续准确 pack/CFG copy/literal source。复用 core 已验 entry 与参数顺序（含环境、state partition），不存第二份 actual、producer、ValueID 对照表。一个 callee 被 NEXT 与 SEND 多次调用时保多条 source routes，不取第一条、不把一个 callsite 的 known raw 应用到全部调用。recursive/unbound/external/callback path 没闭合保具体 gap 和预算 cursor。

None 内容判定只复用：

- 旧合法 `ReferenceValue(...,LiteralOrigin(None),targets=())`（明确这是兼容来源，不扩其对象身份）。
- 正常新路径：真实 OperationResult 或 NORMAL CompletionResult 的 Reference result，附 `LiteralEvaluation(...,PythonLiteral.NONE,definition)`；再沿准确 must-copy 到 raw ordinal0/expanded Use。原 source/code definition 未 replay 仍为独立条件。
- `ExactLiteralOrigin(None)` 只 DATA，不能为满足 raw Reference type 偷改成 Ref。UninterpretedConstant/普通未知 Ref 不等于 None。False、0、空 tuple 等 exact builtin payload 是**已知非 None**，不能用 Python equality 当判定。
- 改成同型另一个 known None/old loop occurrence 不自动相容：先查本次 raw ordinal 的准确来源，再查其内容。内容都为 None 不是 raw port correspondence 的替代证明。

## 6. 每个指定 cell 的有限正反图

每行的“issue/gap”是建议的验收要求；表内建议新 code 并未在基线执行。已有 code 明确标 existing。

| Cell/path | 最小正图（同一 Program，原端口不断） | 必需同型错来源/错路由反例与期望 |
| --- | --- | --- |
| Created NEXT | caller 成功 Create NORMAL handle→driver entry；NEXT raw0→IS_RUNNING false→IS_CREATED true→final gate N/R；N 私有 landing只 BodyStart，无 resume slot；首 YIELD/Return/Raise 原输出与 host adapter | 保所有 D1 类型/门关系，把 Created-true 的消费者换同 body 的 BodyResume：`protocol_admission_target`；raw换已知 SEND(nonNone)但保 Start：同码。未知 raw source 是 `raw_request_source_unresolved` gap，不猜 NEXT。 |
| Created SEND(None) | caller真实产出 Ref None（含原 literal 附件）→SEND raw ordinal0→driver exact call route→IS_CREATED true及SEND_IS_NONE true→gate→BodyStart，无交付 resume payload | 用同型 Ref known False/0 替换**原 ordinal0**，保另一个未使用 None可用：`protocol_initial_send`；只把 expanded target改另一同型Ref且raw保持None：existing `protocol_raw_operand` / 新 `protocol_actual_operand`。缺内容或跨calljoin必须 gap。 |
| Created SEND(nonNone) 拒绝后可启动 | 同一 caller：Create→INVOKE send-driver；Created+SEND_IS_NONE false→本次拒绝 helper packet/最新 RAISE states→caller handler→再次以同owner+currentRAISEstates INVOKE NEXT-driver，重新读阶段后合法 BodyStart | 首次拒绝夹 BodyDrive、NoBodyFinish 或 INITIAL_THROW_F：`protocol_admission_route`/拒绝不种F；后续用旧 pre-reject StateVersion 原 core应拒（exact existing code按实际验收记录）；换 unrelated same-type owner时必须拒已知wrong copy，未知 alias保gap。拒绝后的下一次读取不能复用失败前 predicate。 |
| Created CLOSE | CREATED_CLOSE_V1 OperationSite准确指原 CreatedCloseTest；当前owner/raw CLOSE→bool→BRANCH true→私有首 NoBodyFinish→原 None Ref结果→host RETURN，真实 poststates；不进入 body | false edge/同型另owner finish：existing `no_body_precondition`/`no_body_owner`；把本站subject换同region无关op，不能由region内另一test填义务：需 `protocol_predicate_site` 或明确 MISSING。host返回旧非Nonecarrier需 `protocol_host_result`，不是只有finish就算整格。 |
| Running NEXT | 精确owner/current lifecycle READ→IS_RUNNING true；NEXT raw0；拒绝 helper的本次packet/最新states→host RAISE；没有BodyDrive/NoBodyFinish/F | 让该trueedge进入Start/Resume：`protocol_admission_route`；用oldpacket替换own result：existing `protocol_copy`；predicate读取另一同型owner为`protocol_predicate_owner`。 |
| Running SEND | 同Running guard；SEND raw恰1 Ref，拒绝不把它交付 body；helper当前结果→RAISE | raw ordinal正确但helper annotation指edge-only同值Use：`protocol_actual_operand`；trueedge存在BodyResume(SENT)即拒，不因payload None而允许重入。 |
| Running THROW | 同Running guard；THROW 1–3 Ref原pack顺序完整；reject当前结果→RAISE；不能通过规范化结果假装已进入body | 模型不能以“Running”标签隐藏原代码里已存在的 constructor/callback：若有它们，保真实N/R及partialstate。拒绝路线不能把该packet交到THROWN_PACKET resume，不能把factory失败自动当finished。native具体校验/规范化先后沿版本source条件，不在本报告臆造。 |
| Running CLOSE | 同Running guard；CLOSE raw0；当前拒绝packet→RAISE、无GeneratorExit body injection、无CreatedClose finish | 借CreatedCloseTest true/NoBodyFinish宣终结或GeneratorExit BodyResume：`protocol_admission_route`；相同state Location不代表同owner；真实source条件未解保gap，不能改名Closed fixture。 |

retry 的正图必须 caller 捕获第一次 driver 的真实 **RAISE completion** 后继续，不能把一个 host RAISE terminal 后凭空接 NEXT。可以两个共享 body 的 driver Regions，各有自己的固定 entry roles，call inputs/results/state 均由原端口派生；这不要求 P3 动态 O 已完成，更不证明真实对象身份。若 callback 可能改阶段，后续 NEXT 的新读可选仍 Created 路线，但不能声称该路径必发生。

## 7. 预算、分母与验收先后

1. 先加 actual membership / call-shape guards 和本次 raw/literal 来源 helper；同型错来源负例必须原 core仍合法，否则只测到早期 core 拒绝。
2. 根代理冻结只读 predicate amendment及schema18边界；复用 CreatedCloseTest，先有 current owner/state→own bool→原branch 的正反原图。
3. 才写上述8条主要路线与retry组合；Running四类必须各有真实 guard read/branch，不复用“闭合输出但阶段无来源”的旧 Closed helper充数。每cell单列 source适用条件与已知已拒矛盾。
4. 查询保原 scope/operation/Uses/state accesses、predicate result/branch/edge、resolvedraw/literal来源 recipes、准确 route/seed 和 budgets；固定16格/28组保持。删除predicate或整row后变 MISSING/PARTIAL，不变“此义务不存在”。
5. 所有 stale/read/copy/source扫描预算共享；在 native/source 不完整条件下可声明机械路由，但不可写 phase/runtime/transform VERIFIED。没有以 false proof flags取代真实连接验收。

## 8. 本次阅读绑定

以下 SHA 由只读 sha256sum 获取；未在读后运行产品，也不声称后来修改的根代理源码仍同hash。

```text
docs/M1_PROTOCOL_CONTRACT.md       2a5d982907ed8d9d9e93586f8cf9979002cbac6e27c73de8aac8ce4d0c45c4ac
docs/M1_PROTOCOL_FOUNDATION.md     82c7844b394ab924fe5ac6da723f07ea9d1b4fa86090ec0d85487871bbac2b6c
program/protocols.py               9dd2832716269f86ce9f98b73dea6a634caa084a18d0f974ccaec401322dcacb
program/protocol_rules.py          e72627e8d6b2ab215e057c29f8f2774e8484da16b26960af6d6d3d99a3f35064
program/protocol_flow.py           3410733f931ba9f15340ea4af30f7f5b92860258a00d94ad78d60250b455c4bd
program/protocol_validation.py     0dd22732e03bf6824c8c3551060814013e96ce693fedaad95cdbba1b7a3825c7
program/protocol_query.py          d0a7976bc920c95c2286368cbc5d41341cefae6dfd70619bd85abed7b9488eab
program/driver_validation.py       4a195bab83850b5101c596ef92848a9081e8f3704b05374618b92d1e64a00bd3
program/no_body_validation.py      22669aec4d7c608b1b60c7d161908452f1135e4a1b434b7b80fccccca12607ea
program/literal_validation.py      1c0cc6ce2464804dfb29fced4cdf9ba7f4f0ffa65407b62073e0f17fd91436ca
fixtures/program_protocol_graphs.py 7e15b2955336a0f82e406189ae7ec55c6dc12dbfbb25f7c20660c2f8a50110e9
fixtures/program_driver_graphs.py   2882200ec4dba4a37136e0091f7bae8bbc3a24d9d99a3fa249473a91d64f82bb
fixtures/program_no_body_graphs.py  6d41be9a1bbe6992eba8571f871ebdec436b29ae52cbe964433017b8659b5b67
fixtures/program_literals.py       42c6746a48c9aa23d279d6af4b88a49b070100cca85cd072dfc8c775c3e38f40
```

`program/` 全指 `scar/ir/program/`，`fixtures/` 全指 `tests/fixtures/`。CPython 具体 Running 四方法先后和异常细节由另 agent 的独立语言见证提供；本报告不假冒已观察到的 native 行为。收到设计分工前停止，不实施 fixture 或产品。

## 9. 字段收敛修订：只引用操作真正消费的输入

**本节替代第 4 节 B 的字段和“每 predicate 都拥有 instance/raw、读全 lifecycle”建议，保留原稿以说明修正原因。** 根代理指出的反例成立：读取 `gi_running` 的原操作只消费 body 与状态；`arg is None` 只需原 arg（若原图是二元 IS_OP，其 None 操作数也留在原图）。强制它们消费 raw pack/body 会伪造原程序输入，不能采纳。phase 与 raw 的联系属于 scope/consumer 路由，不能塞进不读取 raw 的 predicate。

### 9.1 推荐冻结的 records

```text
BodyStateCondition(
    instance_use: UseID,
    state_sites: tuple[ExistingAccess, ...],
    rule: BodyStateConditionRule)

BodyStateConditionRule = IS_CREATED | IS_RUNNING | IS_SUSPENDED | IS_CLOSED

ReferenceIsNoneCondition(input_use: UseID)

AdmissionPredicate(
    subject: BodyStateCondition | ReferenceIsNoneCondition,
    result: OperationResult,
    branch: OperationID)
```

全部 frozen/slots/exact records，现 ProtocolOperation 仍提供所属 scope、owner operation、slot、source；不重复存 operation/result ValueID、branch condition Use、true/false edges、state versions、raw operand 或 phase。**新增第六种 contract 有必要**：P1 五变体没有只读 predicate 的实际 owner/输入语义及 intended branch 连接。它们不是另一个 request normalizer、call、packet、adapter 或 no-entry transition。

### 9.2 各字段机械规则

- `result` 必须为 outer.operation 自身准确普通 OperationResult，解得 `DataValue(builtins.bool)`，slot=0；不接受 Reference/protocol/state、INVOKE completion、StaticProtocolGap 或另一同型 bool。附件不生产新值。
- `branch` 是明确的原 BRANCH OperationID，不是其结果或一个新节点。验证精确 `branch.terminator.condition` 的 original Use，从本次 `result` 沿原 CFG must-copy 到该 Use；只搜索“某个同型 bool consumer”会把 expected join 缺失隐藏掉，故保留显式 branch 字段。true/false 仍由原 successor0/1 派生，不能存第二套 targets。
- 不要求二者紧邻。允许已支持的 block/formal 纯转发后消费，原 `_fresh_copies` 清掉 loop 的旧 producer evaluation；同 ValueID 不足以通过。若跨 region 需真实 call 参数/结果路由而当前 helper 不支持，保准确 join gap，不能按名字猜或用本地 forwards 的未知充真。
- predicate operation 必须确为 ordinary、effects_complete、无 callback/callee/INVOKE 的只读或纯计算 intrinsic；未知 getattr/descriptor/自定义 `__getattribute__` 调用保持原 INVOKE 边界及缺口，不能把这种原操作标成 callback-free predicate。原 operation 有哪些 actual/effects 仍全部保留，subject 的角色字段不是对 op.uses 的替代编码。
- `BodyStateCondition.instance_use` 必须该操作拥有的 Reference Use，并按原 driver-role/call recipes 对应 scope 的 receiver；unknown identity/source 保 gap，已知 wrong fixed receiver/copy 拒。独立 Use 可 alias 同 Value，不强迫共用 UseID。
- `state_sites` 非空、无重复、均为该操作原 ExistingAccess；READ、无 after/full_overwrite，before 是原 owned STATE_CONTENT Use，原 SSA 负责它在 **读取点** current。只列实际读取；**不强制覆盖全部 interface.lifecycle**，那会伪造阶段读取未实际消费的其他域。非 None 的原 access.reference / state-address owner 已知与 instance 矛盾时拒；coarse `reference=None` 不是“已无 owner”，保该规则的 source/interpretation 条件。
- `ReferenceIsNoneCondition.input_use` 只引用这个 predicate 的真实 Reference 输入。没有额外 instance/raw/state_sites 字段，也不要求虚增 StateAccess。若原 primitive 是 binary IS_OP，另一实际输入及其 literal/source 仍由原操作保留；不能借单字段附件删除它，或把与任意非 None 对象的 `is` 声称为 IS_NONE。最小固定 intrinsic 形状可只读取 arg，但必须原 op 本来就是该形状。

这里没有要求 native implementation 已证。固定 predicate rule 给 supplied IR 一个有条件的读取合同；source code/对象家族/实际运行适用性仍独立未证。已知原端口错接不能以这些未证条件豁免。

### 9.3 branch 当前性与 final gate 是两个时刻

1. **predicate→其显式 branch**：bool 必须是本次读取的结果；读取依赖的原 StateVersion 沿已支持的纯 CFG copy 到 branch 时若仍当前，才能给 branch 的 true/false 条件记“当时 current”的支持。未知写/callback、缺支持路径或预算截断使当前性未证；保 `predicate_state_currentness_unproved` 等具体 gap，不拿旧读当当前。
2. 原程序 `r = g.gi_running; callback(); if r:` 可以合法计算一个历史 bool。核心图不能因此被误报为 Python 非法；但此附件不能仅凭这个 bool 为 callback **之后**的 Running/Created 准入证明。已知 wrong before Use/Location/FK 仍是结构 issue；“世界版本改变”本身不等于已知对象 phase 必变，不能从不同 StateVersion 推 phase 内容不等。
3. **branch→normalizer/callback→final gate**：branch 在 callback 前合法读取 current phase 后，原程序完全可以进入真实规范化/构造回调，再到 final gate。旧 predicate 的“当前性”不永久跨 callback 保留；**不能要求它的 state 与 callback 后或 gate 后永远同一个版本**。
4. final gate 已有独立 admit/recheck 合同：消费此时所有真实 current states，N/R 分别生产真实 poststates，NORMAL 私有 landing 仅含配对 BodyDrive（`driver_validation.py:307–365`）。它必须重新处理当前 owner 的重入/关闭/准入；无须把 gate 改成 phase predicate 的无写延伸。回调后重新检查的 source applicability 仍具体未证，而不是用静态版本相同来冒充执行过检查。
5. 所以“分支当时 Created”与“最终执行 Start 的时刻允许启动”分别列义务。前者连接原 predicate/branch；后者由当前 gate 与所选 target/处理结果连接。回调后若有已知相反 current-phase 读取及错误选边/target，必须识别矛盾；若只有未知 callback，不捏造它改变或没改变了 phase。

### 9.4 raw / None / phase 的相遇位置

- phase predicate 不消费 raw。从 scope 的原 `DriverInterface.scheduler_request` 与实际 callsite recipes 找 raw definition/kind/ordinal，逐 call context 保留；其结果与 predicate 分支在 **consumer 的原 CFG 路线**相遇。
- None predicate 不消费整个 raw。其 input 通过原 must-copy/call recipe 对照 raw SEND ordinal0；known None/non-None 通过原 LiteralEvaluation/legacy compatible origin 或实际 IS_NONE 分支条件连接。unknown ordinal/content/call association 各自保 gap。
- `IS_RUNNING` true 路必须是该 receiver 的本次拒绝→host 路线，无该 owner 的 BodyDrive、NoBodyFinish 或新 F seed。不能普遍禁止其他独立对象在 callback 中被驱动；未展开 helper 的效果/失败仍原样保留。
- `IS_CREATED` true 与 NEXT，或 SEND+准确 `ReferenceIsNoneCondition` true，约束 BodyStart（无 resume inputs）。non-None false 路连接本次拒绝，捕获后再次 NEXT 需真实 caller RAISE states及新的检查，不继承旧 current-phase 许可。
- `IS_SUSPENDED`、`IS_CLOSED` 是同一只读 subject union 的固定规则；不能只加名称就算两行完成。它们也必须有对应 current READ、own bool、指定 branch、真实 request/结果/target 路由。
- Created CLOSE 保旧 CreatedCloseTest/NoBodyFinish 精确 true-edge，不再用新谓词替代旧已冻结的全部领域、首 mark 和 body-only intrinsic 检查。新查询只加准确 scope/site join。

### 9.5 必拒错与必须保留的缺口

**结构 issue**：subject Use 不属于 predicate；state site 外来/越界/WRITE；result 非 own bool；branch 不是 BRANCH；condition 必定来自同型另一 producer/旧迭代；known receiver 或 raw ordinal copy 错；ProtocolCall 非真实 CALL/INVOKE；INVOKE 协议角色只是 edge forward 并非 actual；Running true 选同 owner Drive/finish；Created non-None 被准确识别却接 Start；错误 None 来源被同型另值替代。

**不能伪造通过的 gaps**：external/raw/call mapping 未闭合、literal 内容未知、跨 scope 对象身份未证、coarse owner interpretation/source 未证、read→branch 当前性被 unknown effect 打断、最终 gate native recheck 未证、预算截断。gap 不能删除完整矩阵格，也不能豁免同时已知的 wrong Use/branch/target。

### 9.6 amendment / wire 决定

不改原 P1 文档的历史字段，以 P2 amendment 明确第六种 contract 和新 Program18 capability。v1–v17 原五变体字段/tag/bytes保持；旧 schema 拒新 predicate tag及嵌套 subject/rule。仅含旧 F 不自动升18或获得阶段完整性；新variant是18触发点。Execution 仍7，不提前实现 O。

此节是设计收敛建议，不是 records/codec 实施或验收。没有新增运行、测试、source edits 或 phase proof。后续以根代理冻结字段为准。
