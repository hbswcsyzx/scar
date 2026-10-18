# R3.1 文档与公开范围独立只读审查

范围：只读两份R3文档、当前调用查询/validator相关端点和root物化集合helper；复用已经归档的11querycases，**没有新增pytest/probe/产品或文档编辑**。所列hash是此次读入版本，不是最终全局冻结版本；validator作者仍可作末次修正。

结论：**文档的声明/运行证明及R3分门边界可接受（PASS_WITH_SCOPE）**；以下有小型文字澄清和一项需validator owner核对的scope一致性问题，不据此宣称全组件/整个模型已通过。

## 已明确且与实现一致

- Plan开头是计划；R3.1不关闭R3.2/3.3或M0–M2。API末尾没有自动恢复LeWM或性能提升承诺。既有649/4826结果明确属于上轮V，不是本轮刚执行的验收。
- CallActivation是显式关联，原callee/Use/results/state/ControlTransfer仍唯一；DECLARED不等于实际caller绑定、ObjectID/内容相同或可复用。相同输入/source/span不自动选activation。
- entry/completion的Unresolved没有解释成running、无返回、FAILED或无副作用；缺callertransfer不默认NORMAL。11cases实际覆盖childRAISE已见、callertransfer未见，child payload保留而landing/formal不造。
- Mat集合关系正确区分retention.target为MaterializationRef与只拿Mat作AllocationTarget佐证。COMPLETE只约束该ticket自己的明确声明；PARTIAL/UNKNOWN遗漏为gap，其它ticket不补项；URI不同但hash/schema/size/MatID相同不产生新身份。没有由此授held/free/quiescence/物理capture完整性。
- 文件read/flush/persist、whole-ticket native边界和完整Q分母仍在后续R3.2，不把本门端口查询当端点协议解释器。

## 建议的最小文档修正（不改产品）

1. **API §4/当前87–88行补齐第四个false字段。** 现只列source_runtime_verified、value_identity_verified、transformation_authorized；call_query同时公开runtime_identity_verified=False。建议列出四者，尤其强调真实caller→child绑定未证，不只说内容identity未证。
2. **API §2/49–51行明确两种位置。** “相同CompletionResult位置”容易被读成输出槽与landing物理位置相同。建议：`按CompletionResult.index选child出口槽，再沿该argument在实际successor中的位置回查target formal；不能按landing序号或默认NORMAL位置配对。` 现11cases的NORMAL/RAISE反排签名已覆盖此具体风险。
3. **API §2/52–53行补一个缺采矩阵/短句。** completion未解析时当前view.completion=None、outputs=()，这表示未能选定实际出口，不是零结果；静态caller/callee接口可从call_entries.operation/callee回查。entry未解析时input静态Use/formal定义仍保留；childcompletion已解析但callertransfer未知时保留childUse，caller_transfer/formal/edge_argument=None。不要把这些None统一叫pending。
4. **API §3 owner行收窄“callback”措辞。** 目前“BodyDrive、callback或opaque内部事件不能借此冒充整次同步调用”意图正确，但可能被读成任何真正的回调调用都禁止。建议：`BodyDrive使用其专用入口；内部callback/native span本身不能冒充外围整次同步调用。具有独立canonical同步caller和静态callee的真实回调可另按本接口声明。` 当前validator无名称/业务callback黑名单，文档不应暗加它。
5. **API §4/NO_DECLARED_CALLEE语义可补一句。** 这只表示原core没有显式callee，不是证明该operation实际无调用、纯或无外部效果。MISSING也不是执行失败；DECLARED的gaps仍是完整性分母。

以上都不要求增加新records/接口或endpoint parser；Plan的Mat target段与完成边界无需实质改写。

## S1：已知thread范围句与当前校验需owner核对

文档Plan52–54/API64写“已知host thread冲突是错误”。当前call_validation中只在entry为BlockVisitID时比较caller_segment与entry_segment（读入源码313–317附近）；_terminal_kind/outputs不比较completion segment的thread。

最小静态情况：CallActivation.entry=Unresolved；childcompletion明确指该activation一个已捕获RETURN/RAISE，但其segment具有与caller不同的已知HostThreadInstance。声明是同步直接callee，按上述合同这不该只保留thread未知；当前entry分支被跳过时可能没有这条已知冲突检查。另一种情况是known entry相同thread，但completion来自不同thread的partial/capture segment，path只得到gap。

此处**未执行反例**、未改validator，不能写成已运行失败；也没有从不同thread推出物理不可能的所有native程序。问题只限本接口已经写定的“同步callee/已知线程一致”范围，跨线程工作另有WorkSubmission协议。已发root；请validator owner在本轮既有合同内核对/关闭，或明确解释现有其它guard为何阻断，不用把文档默默收窄来掩盖。

## 11querycases的准确边界

本agent已有focused首次11P/0.66s，query_calls/attempt001；并非本审查重跑。覆盖两次共享body的原input/output/state路由、f(x,x)独立Use同actual、INVOKE N/R真实CompletionResult反排、entry/completion缺采、calleractual缺采、childRAISE但callertransfer未采、无关联不择同body、detached污染隔离、strictID/FK。
没有借这11P声称递归/所有scope冲突、native身份或任意child交换均可识别。两个child若同callee/scope/type且没有nativeidentity依据，交换声明pair可能结构仍合法；所有identity/runtime/transform false必须继续保留。
本轮不额外跑套件；最终组件/clean冻结/full由root统一，本文不是该验收的替身。

## 读入源码/文档指纹（非最终冻结）

- `docs/M1_RESOURCE_COMPOSITION_PLAN.md` SHA256 `1d115816998115cd3a3f8893ea7b01d0d9ab0c260b4f4e11416a8128d2ebd3de`
- `docs/M1_CALL_ACTIVATION_API.md` SHA256 `6a14c6cacf1470768be4df00cc41d3abdfdacccdf61ce26824aa5aae3ec0731f`
- `scar/ir/execution/call_query.py` SHA256 `9cecb45f6da0ee59a4e86faa1ae05fe5de3d019ed362d5e42aa91830cf1ebe42`
- `scar/ir/execution/call_validation.py` SHA256 `abd53a5b75591e34e4ed76529f0a62af0ad99129cf1eff84c1dac0b0cc868222`
- `scar/ir/execution/work_validation.py` SHA256 `1cccc760cb93268f4e282417e1d5fe8f1034870c474866237246ea7bae9e6984`
- `scar/ir/execution/query.py` SHA256 `94b098d75a0568cf48240ff7078f8d4a99b9353c5abd73ccbef804c28803400a`
- `tests/unit/test_execution_call_query.py` SHA256 `d2f0236c58e155092506be4a08e3323dbb2a21672bfdc62c74c69de2ccd6609a`
