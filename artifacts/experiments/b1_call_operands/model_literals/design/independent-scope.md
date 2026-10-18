# L0：literal 的完整关系分母——独立只读范围审查

状态：**Proposed，尚无literal产品/验收结论。** root指定基线为clean `13201ad`，worktree
`/tmp/scar-structured-model-280qf4mi`。本轮只读仓库/既有编译见证报告与官方资料，
没有执行Python、compile、pytest、full、workload、OS采集或GPU；仅写本ignored报告。

## 1. 结论

仅加BYTES/COMPLEX enum不够。L门至少同时覆盖：**精确payload/type、AST与编译常量的来源区别、
Python求值的原producer/Use/实际completion、逐visit/activation对象身份、运行构造及观察边界**。
推荐复用PythonLiteral内容表示，新增exact内容origin只用于DataValue抽象内容；Python Reference
的求值仍由原OperationResult或准确INVOKE NORMAL结果产生，literal附件只细化其内容/来源。
不要把对象求值改成一个activation预装的literal Ref，也不要增加第二套producer/provenance图。

本门可以验收这些关系的手工声明与实际端口组合；M3自动source/code对应、M4运行身份/捕获真实性
仍须明确未证。保留未证不等于可省略本门的site/scope/type关系，也不能把后续完整编译器设成本门前提。

## 2. Observed：现接口与能直接复用的连接

- `program/model.py:157–165` LiteralOrigin只有None、exact bool/int/str、有限float；
  `DataValue:194–207`按exact Python type核data_type。ReferenceValue literal刻意保持identity未知、
  targets空、selector UNKNOWN。旧literal没有source/compile phase，也没有对象物化op。
- `execution/flow.py:155–170`把LiteralOrigin按activation预装；`execution/validation.py:316–318`
  允许其ValueOccurrence.origin为activation。这可表达抽象恒定内容，**不能单独表达每次Python对象求值**。
  同一source expression在loop两次执行或同code多次调用的对象不能据此强行合并。
- `scar/ir/literals.py`已有PythonLiteral：typed NONE/BOOL/INT/FLOAT64/STR/BYTES/TUPLE/ELLIPSIS，
  decimal int、float64 bits、bytes hex、tuple tree；不含complex，无统一depth/items/bytes预算。
  它不是对象identity、Python==、完整co_consts类型系统或可删除效果证明。
- `semantics_v2.OperationSemantics:178–207`已有原operation/scope/source/ordered operands/result和
  LITERAL opcode专属PythonLiteral。`source_semantics_v2.py:197–205`接AST Constant；
  `program_lowering.py:458–468`已有ValueSource/semantic_value连接，却把core常量建成literal Reference。
  复用原来源，不再建立一张“literal producer图”。
- `program/source.py`的OperationSource/ValueSource/UseSource/LoweringMetadata、
  `v2.common.SourceReference`、ProviderArtifact/FactReference/Binding已能保存准确来源及跨表示关联。
  CapturedCode/RuntimeCodeObservation保留版本/代码观察，但不是已验证的co_consts槽或literal身份。
- 原OperationResult、CompletionResult/Successor、CallActivation、UseOccurrence与flow已经区分
  真实producer/formal、实际边、loop visit和child activation。Reference→ObjectIdentity与
  Data→Version的denotation已存在（content_validation.py:404–427）；literal不应复制这些关系。
- 容器/格式字符串协议在数据分册§11–12已明确；tuple/list/dict/set的源构造与opaque/native边界
  可由现Operation/Uses/state/INVOKE保守表达，不必为literal再做构造前端。

## 3. 必须分开的语义关系

### 3.1 精确内容及类型

AST Constant标量分母是None、bool、int、float、complex、str、bytes、Ellipsis，不能把缺项记UNKNOWN
后宣称完整。复用PythonLiteral并补complex双binary64分量；signed zero、inf、NaN位型都保留。
tuple tree可作为有限不可变内容描述，但不意味着源Tuple node已无需运行构造；可变容器/任意对象不能
通过repr或对象str混入payload。frozenset/代码对象等编译常量可保留准确scoped来源ref与未解payload边界，
不伪装成AST Constant或把code对象序列化成可执行literal。

“payload相同”应明示为**类型+内容表示相同**，不能重载成Python==/is。例如bool True与int1标签不同，
Python相等语义却不由标签决定；-0.0/+0.0表示不同；同bits NaN不因record相等就有Python自反相等。
字符串须保留全部代码点、NUL/非ASCII及孤立surrogate，不做Unicode normalization；bytes是任意字节。
新表示的JSON→snapshot UTF8路径不能因surrogate崩溃或有损替换，旧wire字节兼容另保留。

必须先定义固定总bytes/nodes/depth/integer-digit等预算，校验/解析在昂贵转换前计费；超额明确拒绝或
报告TRUNCATED，不能截成另一个合法literal。INT decimal转换不能依赖进程默认十进制digit阈值，
也不能临时修改全局set_int_max_str_digits。无必要时不调用to_python、更不eval/unpickle/marshal执行对象。

### 3.2 AST、compile constant与运行构造

来源至少区别：AST Constant；确切code artifact/owning code scope/constant slot（可嵌套）；
仅手工声明的内容。SourceReference保留fingerprint/span/原scope，前缀/拼接spelling需要时引用原源码，
不能由解析后payload逆推出。编译来源须保留实现/版本、mode/flags/future/optimization等原上下文引用；
filename/qualname/同payload/hash不是code scope identity。

`-0.0`的源UnaryOp、`1+2j`的BinOp、tuple display可在特定编译器中落到常量池；AST形状与编译结果
是两份不同事实。前门literals_probe的编译见证支持这种区别，但本轮没有重跑，亦不推导运行is结果。
docstring/optimized-away source仍有compile/definition归属，不能捏造成每次body执行或删除source义务。
名称`Ellipsis`/`NotImplemented`是lookup；`...`才是相应常量atom，不按名字字符消去环境依赖。

官方当前资料说明数值/字节/字符串atom、负数/复合complex表达式的语法区别，以及同值literal多次
求值可同对象或不同对象；文档当前显示3.14.8，不冒称本机3.14.7的实测行为。
见[表达式与identity](https://docs.python.org/3.14/reference/expressions.html#literals-and-object-identity)、
[AST Constant](https://docs.python.org/3.14/library/ast.html#ast.Constant)。

### 3.3 对象identity与原producer不可替代

建议方向与root一致：ExactLiteralOrigin仅DataValue抽象内容；Reference literal-evaluation附件
标记**已有返回端口**，不更改其origin。普通op选已有OperationResult；INVOKE选准确NORMAL
CompletionResult逻辑槽及其原formal。payload/type不应让既有effects_complete/behaviors/current state改变。
若原值来自一个可能分配、回调或raise的operation，内容已知也不删除这些原输入/效果。

附件字段可收敛为 `site + payload + typed sourcekind/scoped source references`，不复制producer、Uses、
before/after或runtime object。普通site须真实reference result；INVOKE site须NORMAL signature的准确
REFERENCE槽，不把RAISE异常packet、state或旁路forward Use贴作新产出的literal对象。
后态只由实际completion/transfer派生：未观察completion保持gap，不能给RAISE路径补normal literal值。

language singleton内容与运行关联分别保留：None/True/False/...有语言身份规则，但仅一条未验证附件
不证明真实native返回就是该singleton。其它str/int/bytes/tuple的常量池复用不由payload直接推导。
已给的实际ObjectIdentity继续通过原ValueDenotation表达；相同对象内容/物化版本也不由literal永久固定。

## 4. 直接、INVOKE、loop和call的最小组合正反例

这些都是待实施的声明IR分母，不是本轮运行结果。

1. **direct result**：两个原literal-evaluation op返回同payload Reference，保留两个OperationResult。
   两个independent Uses消费同一个result允许alias；两个result不能因payload相同自动同identity。
   错result index/foreign op/Data/State槽须拒绝；附件不能把一个旧OperationResult改成LiteralOrigin。
2. **INVOKE**：NORMAL `(STATE,REFERENCE)`，实际edge对formal反排；RAISE另有packet/state。
   site沿准确CompletionResult index找reference，不能按第0槽/边序猜。分别captured NORMAL、RAISE及
   缺transfer：只有真实NORMAL有该结果；RAISE保留partial后态，未见NORMAL不补ValueOccurrence。
3. **loop两visit**：同静态evaluation result在两visit有两个原ValueOccurrence。
   可声明同或不同ObjectIdentity（依实际证据），payload相同不能替这项证据作选择。
   把第一visit result接第二visit Use时由原flow拒绝stale incarnation；缺denotation明确unknown。
4. **同callee两调用**：保留两个child activation、两个返回producer及准确CallActivation路线。
   同source/code constant/payload不能让第二调用借第一child结果；wrongactivation实参/返回拒绝。
   同一次result的重复Use不去重；缺child/completion关联保留gap，不凭staticcallee补出对象。
5. **容器与is观察**：运行`[f(), f()]`、`(f(), f())`和`{k():v(), **m}`保留ordered Uses及可能partial
   write/raise；不能以观察到的tuple/list内容代替构造。`(x,x)`保留两Use和元素alias；mutable元素不成为
   PythonLiteral的递归“值快照”。相同tuple payload仍不能消去原creation/identity与release义务。
6. **f/t-string边界**：格式化/模板虽属字符串语法，包含conversion/format或interpolation求值与保存的引用。
   不编码成普通STR payload从而丢调用、状态、identity。分册已有协议，L门要有保守组合/拒绝误贴反例，
   不要求为本门新增完整格式化解释器。

## 5. 有限L门验收分母

| ID | 本门必须实际交付/组合 | 必须拒绝或明确保留 |
| --- | --- | --- |
| L01 | 八类AST Constant标量、tuple内容；exacttype/complex双bits | bool/int串型、非法hex/bytes/NaN标签、有损数值相等代替表示 |
| L02 | 空bytes、NUL/Unicode/surrogate str、signedzero/inf/NaN/complex分量，严格wire/snapshot往返 | repr fallback、UTF8崩溃/替换、Python==或is自证 |
| L03 | 固定bytes/nodes/depth/int预算、嵌套重校验 | 无界递归/转换；隐式依赖或改动全局integer digit限制；截断伪成功 |
| L04 | typed sourcekind的SourceReference/原scope与compiled const-slot ref | AST Unary/BinOp/容器伪报AST Constant；跨code/scope/同名artifact混用 |
| L05 | direct literal-evaluation已有reference result+原effects/Uses | foreign producer/错槽、改origin、借constant内容改pure/complete |
| L06 | INVOKE normal准确reference槽、N/R实际与缺completion | default NORMAL、RAISE/state/forwardUse冒新producer、partial post回退 |
| L07 | 两loopvisit、两childactivation实际denotation与原Use路由 | 同静态Value/source/payload替代identity；旧visit/另child借值 |
| L08 | 同result重复Uses、两个同payload results与is/alias观察 | 端口去重、常量池slot/相同内容当跨执行对象identity |
| L09 | runtime tuple/list/dict/set/展开与partialraise、f/t边界 | 可变容器inline literal、删除构造/回调/输入/release；code constant抹AST归属 |
| L10 | shared PythonLiteral所有消费者兼容、旧core wire、新能力strict tags和public query | 只升program schema却静默扩旧v2/OIR的kind；无附件/缺source变空证明 |

L04不要求实现全编译器；如没有可解析source/code catalog，仍要保存准确scoped ref及“未验证slot/阶段”
条件，不能将FactRef存在当重放成功。编译frozenset/code对象不是新scalar literal类型，必须有准确边界落点。
L07是构造IR+existing execution接口的组合测试，不是自动采集两次真实Python identity的证明。
测试总数/重复focused子集不代替这10组关系分母；未覆盖direct/INVOKE/loop/call/构造边界时不关闭L门。

## 6. M3/M4仍未证明、但接口不能丢掉的事实

- M3：源码decode/token拼接/AST/优化/异常到exact code常量池和原canonical求值op的自动对应；
  常量折叠的合法条件、函数defaults/docstring/注解等阶段归属；真实完整frontend不是本门前提。
- M4：实际load/构造次数、运行ObjectIdentity/interning/constpool复用、真实call/activation/loop对应与捕获完整性。
  相同payload、code hash或source span不能代替这些证据；缺观测不等于没有identity consumer。
- 内容已知不关闭初始化/import/环境状态、异常、分配/release、alias/lifetime、native/source authority。
  无自动constant folding/hoist/cache/DSE授权；保留全部原producer和有序Uses、不新增第二套provenance。

## 7. 阅读范围与实际SHA256

选读源码/协议/既有报告如下；旧probe JSON这里只绑定已有产物，不是本轮重跑。

```text
6b9f662c0e3b6be23ccc331937b3448067ffa3d9e656505faba7d0b8890186dd docs/FIRST_STAGE_COMPLETION_MATRIX.md
ea4bb6cd1d4976ad7e6d1b7ccd214c5cdeafa0f657623e2363fd110bada9e509 docs/WHOLE_PROGRAM_MODEL.md
d4f73652212373e7a9cb1b62ce06f481b82b3d4c0089cbf4768969808258419b docs/WHOLE_PROGRAM_MODEL_PLAN.md
1a5f87dce26236a97e41ad24e0085ec2d73a634b9ce0bd709ce9fc693100fb4a docs/model/PYTHON_DATA_DEFINITION_PROTOCOLS.md
343c49507b3ce3961a4e5239adc47a5c7f7fb0c35f7a4620298c0af356e047f8 artifacts/experiments/b1_call_operands/model_state_locations/design/literals.md
c8aa29aec97fd42bf6f8950bc43b823c252c0b394b6ce39b10c73e8021be1568 artifacts/experiments/b1_call_operands/model_state_locations/design/literals_probe.json
3e1c8e95c1a32e8454007f0b8c35e3724028732d376a5550ca1c5d6e7ce949d3 scar/ir/literals.py
bb9993520ee76ab6dd5531884944f96a990379fff74d7935c81a10b818df4d61 scar/ir/program/model.py
81cac8e544bfab868d95b037bd8149c4e73cb9e18b128c244bdc104136084089 scar/ir/program/codec.py
dbff369035e06452de1f6c0e741e68553f188addac8483859ae47a444f5a002b scar/ir/program/source.py
fb96fe41a8c5f6cf33a01fd6974830b9dd73ee622107b3659411cc0c4f8d1343 scar/ir/program/providers.py
f938bc3635b50e2a4a1efe29b5e364f82ff274931bd2f857beab71e93969a9a2 scar/ir/semantics_v2.py
2b6189a1ad658072176a00bc4c72a4c5af4c66e96edc844bad904471c8eb0501 scar/ir/execution/flow.py
4b828b9a95b5d46b82c5fb3045d514b277dd586bfa3747376807e64f2a624896 scar/ir/execution/validation.py
e54ec95c69d80b5e00d4b59e4f98aca1bf3c9a9029bde28f0b7bae0f9043071f scar/ir/execution/content_validation.py
4d81202f298142b766034d2907262d05cd44d40a825ff54a0c4609f1702dece8 scar/analysis/source_semantics_v2.py
5ab3f166d4f949fe3efa0905dfacc39657562cf3dc0bc96bb1193c1a94b75068 scar/analysis/program_lowering.py
691a7ec169c81cb51e271731ea11ee4c2aed38b5553b1f48f072a8ff368979b9 scar/ir/v2/common.py
7882dfa21e7877f41dc441f40875433d6b340f4fdb657df547ca57fc34953de5 scar/ir/v2/correspondence.py
b2a414942e7d236596e088bdf36396a86afaf247cc1cf3b069978d93f0499063 scar/ir/program/call_edges.py
74843e78617e5a76f6f671df344b5843af3d332323893a97407d6ee06cb537a6 scar/ir/program/runtime_sources.py
2924eb78ece2c6fa3c993f84a0f84f29768ad9d19b835b3e34ab3aba9c57058c scar/ir/program/compilation.py
511daa3a5d1ee89ae7f7c545dd5f7161ea3a3a6c9f3c1b01b4224c0ba751fcc1 scar/ir/v2/codec.py
4e981786c52d9bbc50cb76f8b469153d035692daed2c2941e27b3e7fea8dcdc5 scar/ir/v2/optimization.py
```

只读额外核对v2.codec的_python_literal与v2.optimization的StaticValueSubstitution使用共享PythonLiteral，
未做完整消费者审计，L10实施时须用实际受影响清单闭合。官方链接为本轮主源阅读，不是本机运行证据。
本报告到此冻结；完整第一阶段仍OPEN，SourceAuthority/transform均不授予。

## L0 计划冻结前补充：Data结果与来源变体（保留原建议历史）

root提出两处扩展后，本次仅只读点评并追加，不修改源码/测试、不运行任何代码。
**结论：支持；没有与本报告关系分母冲突的具体阻断。** 本补充将上文§3.3/§4中过窄的
“literal-evaluation只标Reference结果”建议扩展为以下准入，不能以对象only缩窄数据来源模型。

### A. 保留原producer的Data与Reference均可附内容

- 普通LiteralEvaluation可指原OperationResult的DataValue或ReferenceValue。计算结果的内容已知时
  保留原producer、输入Uses、效果/状态/异常，不强迫改为无producer的ExactLiteralOrigin。
- INVOKE可指NORMAL signature真正产生的DATA或REFERENCE槽；RAISE、STATE、LOCAL_BINDING、
  PROTOCOL及边上forward Use均不能冒此新结果。原completion_slots约束已保证produced槽与formal
  的准确对应，继续沿该index解析，不需要再存一份fanout/actual/formal图。
- 对typed PythonLiteral，DataValue.data_type必须由精确kind匹配；bool不是int，FLOAT64不隐式匹配
  任意native float type，tuple内容树也不隐式转换成其它容器。比较载荷表示而非先to_python后用==。
  Reference没有data_type字段：附件只声明对象内容，不因此获得目标、已知Python runtime类型、identity或alias授权。
- ExactLiteralOrigin仍只用于Data抽象内容。State/Binding/Protocol不能借literal附件成为常量，
  Data/Reference两种合法site都不改变原origin，不从内容已知推出操作无效应、无依赖或可删。

最小新增正反分母：有RW状态的普通op返回Data(int1)，附件合法且原current/Uses/producer不变；
同slot贴bool payload拒绝。INVOKE NORMAL反排DATA/REFERENCE/STATE槽分别按原index核对，
DATA/REFERENCE合法，STATE/RAISE/forward-use拒绝；只捕获RAISE或缺completion时不补NORMAL值。
loop/call的两实例原则同时适用于Data与Reference：同内容不把两次effect/producer消为一次，
Reference更不能据此合并ObjectIdentity。

### B. sourcekind用表达式来源、代码常量引用与准确未定位边界

建议采用root提出的三个来源variant：

```text
SourceExpression(SourceReference)
CodeConstant(original scoped ProviderFactReference to code-object record, index)
UnlocatedLiteral(reason)
```

SourceExpression不声称节点为AST Constant，因而可保存unary/binary folded expression或computed
constant的源归属；它也不声称表达式无状态/纯性。SourceReference和原scope/operation对应继续复用既有
来源接口，不能再保存一套producer/求值顺序。CodeConstant的index须exact非bool非负整数，坐标属于
所引准确code-object record；相同index/filename在另code artifact中不是同一个常量。
FactRef存在本身不验证slot、编译选项或内容，缺解析时保留准确未证条件，不借此升级SourceAuthority。
UnlocatedLiteral必须给reason，不伪造AST/代码来源，也不能在来源闭合分母中算作已找到source。

`UninterpretedConstant(reason)`可给编译frozenset/code等保留准确的未解payload边界，
不把code对象塞进scalar literal、不新增执行/反序列化器。它不是ExactLiteralOrigin的精确内容，
没有可据以核对的kind时，DATA的“payload/type已匹配”也必须未证；query不能将其当已建立精确恒值。
八类标量payload的明确支持仍是本门必需分母，不能拿UninterpretedConstant掩盖未实现类型。

这两处扩展提高表达完整性，不改变L01–L10原分母；direct/INVOKE、loop/call、容器与is/alias、
共享wire族和有界校验仍须实际组合。M3/M4的自动编译/运行对应继续OPEN。本补充不授产品PASS或测试结果。
