# Await acquisition：建模审查与实施记录

2026-10-19；基线 `0bbc6235992e89e2a5735287e94622cfe0755cf8`。
依据 [冻结D0范围](M1_AWAIT_ACQUISITION_PLAN.md)，完整A–H单位尚未完成。
[D1精确合同](M1_AWAIT_ACQUISITION_CONTRACT.md)已冻结，1393项受影响定向通过；
完整A–H尚未验收。冻稿SHA为`bb9466c4b05ba7d7271eb423232184ed9fad62b9cdec14dd660d0965c710b72c`。
原十六组/P5/M2和完整第一阶段继续OPEN，不能以本文的语言例或首红关闭它们。

## 1. Observed / Verified：本机语言证据

root在conda lewm的Python3.14.7串行运行有限语言程序，**12例通过**，stderr为空，
没有使用GPU、SCAR profiler、LeWM或外部工作负载。

- native coroutine与generator-coroutine直接await可零次挂起完成；两cut时
  outer.cr_await确为原对象。一般协议则持有其返回的iterator，__await__仅调用一次。
- 普通generator直接await报TypeError，但可作一般__await__返回的iterator。
- 一般__await__返回native coroutine、generator-coroutine或非iterator，均TypeError；
  方法自身RuntimeError按本次异常传播。
- 显式coro.__await__产生独立wrapper：W不是B，iter(W)是W。手动驱动W可经历
  两cut后返回；没有在Python层观察native held-B字段，不能冒称该实例字段已验证。
- types.coroutine保持同一function对象，替换CodeType；本例bytecode相同，flags
  从35变291。这说明仅重编译源码或只比co_code不足以证明loaded code语义相同。

以上是实际语言证据，不是SCAR IR或自动建图已通过。具体环境、脚本/计划SHA、
原结果及异常保存在 `model_await_acquisition/native-evidence.json`。当前原CodeSnapshot
已包含flags，本轮不据此虚构一个旧CodeID bug，也不新建code registry。

## 2. Observed：原公开接口真实缺口

新fixture复用旧lookup→AWAIT_CALL→advance全链，增加合法ResumableCreate与
最小环境/FrameContext；其handle是原AWAIT_CALL的准确NORMAL结果。五个环境
capture均为真实owned invoke Uses，未给ProtocolCall增加用户参数或伪造Drive。
两张图只改body.kind：GENERATOR为合格方法返回；GENERATOR_COROUTINE不合格。
两者core均合法。前者原公开接口通过，后者却没有资格错误且继续被用作iterator。

| attempt | 实际结果 | 归因 |
| --- | --- | --- |
| red-original-return-qualification | collection1ERROR | 新test从错误module导入ResumableKind；非产品首红 |
| red-original-core-valid-return | 2F | 新fixture未解包旧helper返回tuple；非产品首红 |
| red-known-return-core | 2F | 新fixture漏import Operation；非产品首红 |
| red-existing-acquisition-contract | **1P / 1F** | GEN正例/core通过；GENCORO错误继续advance却无已知资格issue，真正首红 |
| first-contract-and-old-regression | **77P / 0F** | 原首红2项转绿；新records/codec75项，包括独立旧v22 archive encoder；未含完整P3组合 |
| first-self-pipeline | **83P / 2F** | 同图静态1+P3动态3首次通过；2F为root新测试错误要求空捕获budget1必截断；产品不改，只纠正测试预期 |
| final-focused（首次受影响回归，未通过） | **1389P / 4F** | 741源稳定；4F是漏迁移的严格binding集合与future23参数，无产品变更；失败原目录保留 |
| accepted-focused | **1393P / 0F / 0E / 0skip** | 原1308义务+新85；1305原case ID保留、3项future23→24明确迁移；供应self组合通过，完整A–H仍OPEN |

首红当时730源前后固定指纹：
`fe3d773acd22b6d30e1f0364a3ce13dfca21d55970d406c22b2e30067f933939`；
pytest0.97s、runner1.71901570353657s。首红运行时产品仍为基线；之后已经开始
产品实施，不能将首红或上一门1308项结果归给当前工作树。原命令、日志、JUnit和
前后source清单全部保留；本轮完整A–H仍未通过，不能由受影响定向绿测代替。

首次实现定向77项的736源固定SHA为
`b75729b8b451758dc52dfad864ab8badce677120728d7a79c344e4f711466db0`，
pytest3.70s、runner4.418994691222906s，前后一致。此后root又修订执行投影，故
77项只适用于当次字节，不能冒作当前源码或完整A–H的绿测。

Program23使当前reader最大版本变化；12项旧codec测试只迁移max-reader断言
22→23，原case ID、原输入和各旧wire版本/字节断言不变。独立archive子encoder的
max22断言不迁移。详见证据目录`test-migration.md`。

首次受影响回归SHA为
`9a9751344b85d23061055fb50b6512e8b04bfde6d88bcde3dec01a766465a5b7`，
pytest94.33s、runner95.30443513207138s。随后三项future参数23→24保持未知版本/
bool拒绝语义，三case ID映射明确归档；严格binding全集仅显式增加AwaitBodyLink，
不放松为subset。独立复审确认四项为词汇/版本迁移遗漏，不需改变产品。

最终受影响定向为741源固定SHA
`7f7e7d77c5fdff3f62d25cee8dc69aa08f1b3cc7f4bd0500d01754aa92fc6f66`，
前后一致；pytest93.17s、runner94.0708432905376s。1393项包含全部上一门1308
义务及新85；不是component/full，不是LeWM运行时间或加速数据。充分验证后停止
额外pytest复跑；归档核验不启动测试或workload。

## 3. Inferred / Proposed：模型修订

缺口不是多一个名为iterator的Reference节点。至少要区分独立operand、方法
未检查候选、资格接受/失败腿、实际iterator与可选held B。native/self、一般协议
和显式W不能共用一条强制lookup路径。旧helper作用域也不能冒完整F12/F15。

原实际callee/operation/Use/result/state/occurrence足以承载多数端口；确实缺少
的非普通copy关系是W持有B与本次真实驱动的对应。D1以薄closed附件表示，
不复制producer、state SSA或phase。一般call返回坏对象再真实TypeError应是合法图；
错误继续执行才拒绝。多caller/多出口/共享incoming须保完整来源，而非ANY或唯一猜测。

## 4. 下一验收节点

三路复审的阻断已纳入D1：parent/child完整相关链、bool成功源与接受边、无lookup
的native构造合同、ABI-only边界、精确发生join。独立freeze记录及此前审查稿原字节
均归档。实施分record/codec、静态resolver、全矩阵fixture及root P3桥独立拥有文件。
所有作者只读写源码，root在作者冻结后串行执行，禁止边测边改。

有限源审指出四项执行初稿风险：查询前全做调用树搜索、一般awaitable A误作
iterator B、未投影case.guard、截断后来源分母变成已查前缀。root已在查询内使用
同shared budget，分离真实qualification返回B与self路径，保原case选择和完整
source occurrence计数；这些改动尚待新组合实际验证，源审不冒作运行复现。

下一步继续完整静态解析和P3组合；A–H
包含零cut、多cut、同B direct/await、显式W、正常与异常、缺失关系、budget及fresh。
保留上一门1308原义务；全十六组齐备后才component/frozen-full，再P5/M2原清单。
当前没有新backend、LeWM特例、自动完整LeWM模型或新加速比。

### 当前组合的明确边界

已运行供应IR中的单次self获取→原driver调用→首次body挂起。getter/qualification
等类型与wire已实现，但真实general parent/callee全链、合法TypeError消费、零cut、
同B direct/await多cut、显式W→held B完整发生及更复杂共享caller/失效组合仍未完成
对应A–H实际矩阵，不能因为首次self组合绿测就关闭本完整单位或原F12/F15。
