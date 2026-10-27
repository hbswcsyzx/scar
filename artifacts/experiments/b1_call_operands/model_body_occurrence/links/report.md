# P3：canonical 组合 fixture 与强语义反例

2026-10-18。实施基线 `a740661`；仅 owned fixture/unit 与本报告。未改产品、旧 fixtures、旧 tests；无 component/full、GPU、LeWM 工作负载、环境安装或 commit。

## 交付及接口

- `tests/fixtures/execution_resumable_graphs.py` SHA256 `456a35baaac263a2b812eea8646c30bcfd8a84ec7b8cf5a6d7b7ccb9abdbde3a`
- `tests/unit/test_execution_resumable_links.py` SHA256 `6f809e44111bbc7e8d8bfea78fd526dacbff51d4028ee42f970572ac7df18dae`
- `resumable_execution(resume='value'|'packet', instances=1, switched_thread=False, known_creation=True, extra_domain=False) -> (program, model, details)`。
- `empty_frontier_execution() -> (program, model, details)`：无有限静态 outcome 的 Attached 自环及有限捕获前缀。

两源码从本报告起冻结，等 root 统一 gate。报告不将 33 项数目当作 O01–O16 或完整 M0–M2 自动关闭。

## 一个实际组合模型

默认同一 Program 包括 factory、Start driver、Resume driver 和唯一 canonical body。factory 实际 NORMAL Create handle → 第一次同步 INVOKE Start driver → 第一次返回 → 第二次同步 INVOKE Resume driver；两次普通 caller→driver 用原 CallActivation，body 不伪装成普通 callee。

执行有三个 ordinary activation 和一个持续 body activation。body 的 InitialEntry visit 运行至真实 Suspend occurrence；同一个持续 activation 沿该发生的准确 temporal ControlTransfer 进入新的 ResumeIngress segment，再至实际 RETURN 或 RAISE。每个 driver 的实际 BODY_DRIVE source 及 landing 来自自己的真实 ControlTransfer，不使用 common AFTER。captures、原 saved Uses、current state、delivered slot 和 output/forward 全部保留原 UseOccurrence/ValueOccurrence/producer。extra_domain=True 时 body 仍只有3个结果，额外 driver state 是独立 forward。

instances=2 重复动态发生而不复制 canonical body 或认同实例。同 scope EEG OBJECT registry 声明分别提供 owner/capture identity；所有 basis/source 未证，不能当 runtime identity。没有伪造 DataIdentity 或 tensor pointer 内容。

跨次换线程正例：同一 body 的第二段及本次 Resume driver 移到 thread2。原 factory 只捕获到第一次同步调用的返回入口，第二次 caller 操作/landing及其 CallActivation 不被伪造；第二 driver 是外部入口声明，缺来源保条件。这避免把同步 CALL 强行跨线程当合法。

## 实际分母与结果

最终 `links/attempt003`：**33 passed / 6.14s**。原命令、完整 stdout/stderr、JUnit、before/after 注册源码清单均保留。

| selector 范围 | 个数 | 实质断言 |
| --- | ---: | --- |
| 剥两新表的 value/packet×1/2实例×同/跨次线程 | 8 | 旧 canonical flow 仍有效，关系不是新 producer/SSA |
| value/packet×同/跨次线程（含额外state） | 4 | Start 8 / Resume 5 输入；Create captures6；body outputs3、driver forward1；所有实际 Uses、formals、state、outcome/selected landing |
| 同code两实例；缺一端错线程 | 3 | 不同 activation、creation、owner；entry未知不豁免已知 outcome，反之亦然 |
| entry未知仍两个首出口；同Create双claim | 2 | `body_multiple_outcome` / `body_creation_reused`，旧图不因删除新关系就重造证据 |
| Start错Resume入口；CaptureIngress；旧Suspend；缺temporal；实际wrongcase/source | 5 | 已知误接拒；缺采集精确 gap，不猜入口/当前代次；wrongcase模型剥新表仍valid |
| owner/capture/saved/delivered/output scoped对象冲突 | 5 | 同 artifact 已知不同 ObjectID 精确 `body_reference_conflict`；owner使用外部origin以检持续实例比较 |
| 缺capture、删关联/双端未知、缺Drive transfer、旧state | 4 | 固定原输入/frontier分母；不自绑formal，不补normal/landing；旧状态由原canonical guard拒 |
| 空frontier；detached/strictID/budget | 2 | 无假completion；预算1仍全tuple/count及NOT_CHECKED/cursor；返回修改不污染原模型 |

所有查询保留 source/runtime/value_identity/transformation False。DECLARED 仅 supplied-model 对应相容，不是 runtime 或物理内容证明。packet 路径测试保原 protocol payload，不把 packet 冒成对象/内容版本。

## 所有尝试与归因

- attempt001：最初8个旧 canonical 剥表组合 **8P / 1.26s**；尚非 O 查询验收。
- attempt002：33项 **31P2F / 5.90s**。两失败均 owned 断言预期：错旧 Suspend 被更早的准确 `transfer_resume` guard 拒绝，不是之后的 `resume_source`；公开 unknown typed query ID 使用 ValueError 而非预想 KeyError。保存原输出后改为准确 guard/异常 message，未改产品或放宽语义。
- attempt003：同33项 **33P / 6.14s**。仅共享开发中的 `execution_body_order_graphs.py` 与 `test_execution_body_order.py` 在运行期间变动；before `92d30abfe9d5b1aa516e3dab003b0db4b3929167c0dc1d196b00d19df1bfae09`、after `51dd370d9ec120ca021dedd168fdcd355bb7deddfb6e8dc6ef108c3a627ced0f`，source_unchanged=False已原样记录，不冒称全局冻结。root 仍需统一组件/clean full。

上述重复运行不累计成74个独立用例。

## 受测产品 / 剩余归属

本轮读到的产品 hash：resumable_flow `e74ce73938bca668c4690b0f2df2e1c5278f34a11a8b5963a7fbaf85896bcca9`；resumable_validation `c64013d76c96ebb5dfc81a8fa03a6d74dfbbb700c20fe7fc1f496396b3e0fcbe`；resumable_identity `ff08277950afc4a41c8a81b8bfdabab7ad084ed0167ffe0d26e2a4b5cf87fc2e`；resumable_query `2eabe8577aee3be016b13ba90d7a614c5aad52f77afbbf455595180716fa3d02`。精确测试时全部源码 hash 见 attempt003 清单，root后续变更不能归到此 focused 结果。

本 owner 范围 PASS_WITH_SCOPE。O01 records/wire归A；DataVersion（不同版本不推数值不等）、fresh external catalog、更多 invalid routes归root；conditional host order及联合因果环归独立C。此报告不替代那些分母，亦不将 missing 同步 caller 关系、unknown identity、native/source capture或空frontier前缀宣称为已运行/已终止/已自动恢复。P4/P5及完整模型验收继续开放。
