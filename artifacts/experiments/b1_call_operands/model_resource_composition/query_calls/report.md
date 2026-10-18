# R3.1 动态调用查询实施报告

状态：**Implemented / owned focused 11 PASS / 0.66s**，不是整个R3或native/runtime签核。
基线348d182；独占变更仅新call_query.py、query.py两delegate、新test_execution_call_query.py。没有另建参数/结果/state/producer表，没有新source恢复、detector/backend或LeWM规则。

## 公开接口与规范归属

- `ExecutionIndex.call_activation(CallActivationID)`：从已validate的 `ctx.resolved_call_activations` 返回detached声明及原caller/activation/entry/completion，输入、正常或异常输出路由和具体gaps。entry/completion未采仍DECLARED，原association保留Unresolved；不是“正在运行/没有返回/FAILED”。
- `ExecutionIndex.call_entries(OperationOccurrenceID)`：按validator一次派生的 `call_activations_by_caller` 索引列原关联，无反复全表scan；显式静态callee存在但无row时MISSING+ExecutionIssue，callee未声明时NO_DECLARED_CALLEE。绝不根据source/name/内容denotation自动匹配child。
- input routes直接复用validator从原call_arguments/invoke_arguments、准确callee.entry formal和本次Use/ValueOccurrence派生的顺序；`actual_definition`保留原core Use，缺actual记录时仍能区分f(x,x)两个端口。
- output routes直接复用child真实Return/Raise Use→caller原OperationResult，或INVOKE真实taken CompletionResult→landing formal；不默认NORMAL/index0，不存在common AFTER。缺callertransfer保留child出口payload及transfer gap，不补landing。
- 查询返回plain dict（detached）与原ExecutionIssue/code/path/message接口；无混合dict gap。ID要求exact namespace及内部exact非空str，未知FK KeyError；不做字符串coercion。
- source_runtime_verified/runtime_identity_verified/value_identity_verified/transformation_authorized均False。DECLARED指原声明可回查，不证明真实call身份、值相等、object alias或优化适用。同scope/同静态callee/同type的恶意交换可能结构合法；没有把无依据交换全拒列为通过。

## 真实定向执行

```
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_resource_composition/focus.py query_calls tests/unit/test_execution_call_query.py
```

attempt001：exit0，pytest **11 passed in 0.66s**；driver外部1.3277714839205146秒，子进程退出后仅删除独占basetemp。command/env/Python、前后源码SHA、JUnit、stdout/stderr/report全部保存。所有owned文件首次/本轮唯一pytest即此结果；未跑full/GPU/LeWM/安装/git。
此前query_preflight仅compile两个源码、未import执行；设计审查只读，不将compile当功能测试。

11cases覆盖：两次调用共享同静态body却有不同activation/formal/result/currentstate；f(x,x)两个ownedUse同actual但不同formal；INVOKE NORMAL/RAISE各自真实且反排的completion槽；entry/completion各自Unresolved；calleractual缺采仍保留原Use；childRAISE已见但callertransfer未采；缺关联不按同body推断；noncallee状态及返回对象深层污染隔离；strict namespace/子类/内部strSubclass/错误FK。

输入/输出端口复用C的canonical fixture `execution_call_graphs`。f(x,x)在owned测试里以通用canonical增量添加原第二Data formal/独立Use及动态ValueOccurrence，重新生成snapshot；未改共享fixture或产品validator，也不存tensor数值。

## 保留的边界与独立审查

动态关系是明确声明并逐原端口派生，尚非source/runtime自动恢复。R3.2全过程/Q分母、Endpoint协议/read/flush/persist、whole-work native extent、真实资源identity/coherence/capture closure仍独立，不因11P关闭。
物化集合连接独立源审见 `review/materialization-crossreview.md`（SHA 1a8a2c5cadd577772764d61661a375cc3a9fd7bd231a5ce9ee72625dfc9c4a4d）：root helper只比较exact ticket/原Mat集合，URI非身份，PARTIAL/UNKNOWN保持gap；无确定阻断。未重复root 148P，不将Endpoint/fresh graph组合静态审读冒充新实测。
设计报告（含静态调用能力/动态缺口、Endpoint保守表达、Q/来源完整分母及两处提案边界修正）SHA `65f33d214a70bd1c1625270b67760ad22e8bcc49968341e3ce938440fd5bf26c`。

## 最终指纹

- `scar/ir/execution/call_query.py` SHA256 `9cecb45f6da0ee59a4e86faa1ae05fe5de3d019ed362d5e42aa91830cf1ebe42`
- `scar/ir/execution/query.py` SHA256 `94b098d75a0568cf48240ff7078f8d4a99b9353c5abd73ccbef804c28803400a`
- `tests/unit/test_execution_call_query.py` SHA256 `d2f0236c58e155092506be4a08e3323dbb2a21672bfdc62c74c69de2ccd6609a`
- `scar/ir/execution/calls.py` SHA256 `a287446babd077c072f51182d12ecc5e670bd2e1700b6396e914e134d95a183f`
- `scar/ir/execution/call_validation.py` SHA256 `3c1fb48e63c9ac4a206e8e9f7545fe03ef208d5bd5dd34d712c4dba0d9d0ea69`
- `tests/fixtures/execution_call_graphs.py` SHA256 `6fa0d2eca706edc3a371d4d8d8581973b7e28b94ce5623e89048789e3fc8c90b`

owned源码首跑前/后/报告时一致：True。这些是focused源指纹，不替代root统一冻结组件的全体fingerprint。
