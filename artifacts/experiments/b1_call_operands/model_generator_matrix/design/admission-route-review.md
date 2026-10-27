# Admission routes 有限独立源码复审

**仅只读：没有Python、probe、pytest或产品/fixture编辑。**
对象为 `admission.py::admission_routes`、`admission_view`、`admission_errors`，
原 `ProtocolFlow` copy/预算接线及 `test_program_admission_routes.py`。
不是P2全矩阵/typed phase/native gate验收；源/native/transformation flags必须继续False。

## 1. 有限结果与精确语义

当前图上类型/结构不变；历史bool可以跨合法后续state写继续控制分支，不能因phase已变化便硬拒原程序。
predicate bool→BRANCH必须是本次evaluation的原must-copy；状态support另外比较READ before Use与
最终gate的 **invoke input**，不比较gate自己生产的RUNNING后态。

- `admission.py:151–155` 遇原predicate重执行就cut，不把下轮静态同ID当上轮事实。
- `:156–190` 每个原read精确按Location找gate输入，再用同源evaluation相对copy求解；
  state写或opaque INVOKE的新版本不被普通result当copy。未知/预算中断时不授兼容True。
- `:182–190` 只在全部read support unchanged时给相对于该判词truth分支的target兼容值；
  `IS_RUNNING/IS_CLOSED true`与真实BodyStart/Resume不兼容只是query gap，不改变原CFG合法性。
- `:193–205` 首Drive/host exit切断；不跨drive去捞下一次entry、别的helper或GPU完成。
- `:214–245` 原已访问CFG做有限Kahn：有退出替代仍可能循环，不能因找到某gate便冒充所有路径到达。

`read_snapshot_current=False` 应理解为“未建立相同canonical read snapshot”，
包括确实新state与unknown，不是断言内容不同。`target_compatible_at_snapshot=True`也只是条件兼容，
不是gate一定NORMAL、已准入、实际路径选择或当前native phase已证明。
Reference-is-None无state read时state support可vacant，phase兼容保持None，不凭它推body阶段。

## 2. Owner / region / 合流 / callback 边界

ProgramIndex先core validation：跨region普通Uses/边被拒；原BRANCH必须same region，
predicate输入仍Reference。当前AdmissionPredicate只允许GENERATOR_BODY_V1/BODY，
`admission_errors:56–58` 以原固定receiver must-copy核owner，不把另Reference当同实例。
ASYNC_REQUEST不在该规则准入范围，不能把此receiver检查直接推广成R==B。

merge使用原ProtocolFlow全真实incoming must，不按source集合union；某路径写phase支持时可保守None。
它不是selected-truth path-sensitive alias分析；这种保守性不应被“精化”为忽略其他incoming。
callback若真实写该domain，后态不是copy；若source宣称只读/不触及该domain，则unchanged仍是
**supplied summary的条件结果**，不自动证明native callback没有隐藏写。
BOOL与owner身份不由sourceFactRef或Operation名证明。

## 3. 本轮唯一具体预算发现与关闭

初审源：

```text
961771aabf920d5df2e6cdc6b65df20e2e3ff21ffa1ef75bf05dfd7e01c5f3a5  admission.py
fd4898482a81852c6fd30668aa5dd2548dc7dfe761b9616a937d5635a0bc84af  protocol_flow.py
```

原 `admission_routes:126` 在每个predicate、首次 `ctx.spend` 之前全量重建所有FinalBodyGate dict。
即shared预算已耗尽仍遍历完整gate表；多predicate造成重复N×G准备工作，derived预算不能约束该扫描。
这是具体源推断成本问题，**未运行反例，不是native语义bug**。

已报告root并由root修：`ProtocolFlow.__init__:61` 一次建立 `ctx.gates`，
`:73–75` preparation单列 `final_body_gates` 数量；admission只查该索引。
末次只读当前源确认关闭该重复扫描，没有本owner代码修改或新增测试。
记录/FK/初始索引成本仍是preparation，不应宣称整个CPU开销受4096封顶。

## 4. 当前test映射与仍需root统一验收

实际阅读的unit有4种BodyStateRule×2 target×2 branch truth的16组合，以及一个write插入后历史bool仍合法的case。
它们检查gate INPUT snapshot和所有authority false。该 `write=True` 是普通StateAccess写，
虽然label写callback，**不能把它报为真实INVOKE callback组合测试**。
本审查没有读取任何该文件运行日志，未把源码case当已通过。
当前所读文件尚无cycle/预算截断/merge/真实callback单独用例；root已告准备cycle/budget，
其后应由统一focused/component实际验，不从本只读报告借测试结论。

## 5. 最后源receipt与有界结论

```text
3f3d49ed938273588f0350ee2a813ee23d2dcf2ff669e332a9441e0364f93838  scar/ir/program/admission.py
abc14e9d662e64354bf33d847b94a785cec990eae161b638893500263918cf71  scar/ir/program/protocol_flow.py
10b3e3903eb8e6047587f497f5297f58337758dbf13fc32cc2c5bb36ca8a2997  scar/ir/program/protocol_query.py
5a81aea05d4952c61c9eb846a7d8e07bf80c3567d7bea2bf8e79185eaac5f376  tests/unit/test_program_admission_routes.py
be4b601e16401f677b4cbf4e7ba4d2b2d895f4364ce4d1f90d68ed778f92dbe1  scar/ir/program/protocol_rules.py
1815918ff1419257a33d19060ec3d7ca941fb84f80af8fc8733612d4c3f244aa  scar/ir/program/driver_flow.py
```

**SOURCE_PASS_WITH_SCOPE**：未见本有限scope剩余已知false-proof阻断，重复gate建索引问题已静态关闭。
这不是产品测试PASS、native phase/gate证明、全source inventory或完整P2/C2/D3/M0–M2验收。
