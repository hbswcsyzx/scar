# R3.1 调用边界：独立测试矩阵

状态：**Verified within declared structural contract**，首次focused **10 PASS / 0.60s**。
本任务仅新增 `tests/unit/test_execution_call_boundary_review.py`；未改产品、已冻结query文件、既有validation测试或共享fixture。没有lowerer/新source采集/目标或GPU执行。

## 从源审到修后验证

最初 api-scope-review 的S1与peer call-core-review只是**source-inferred**：entry=Unresolved可跳过旧entry-only thread比较、caller thread unknown可能掩盖child两个已知线程冲突；未运行旧产品反例，也不伪造修前失败日志。
validator作者随后修复 `_check_threads`（按同activation已知segment线程集合比较）、预索引实际terminal并拒一activation多个captured RETURN/RAISE，取消以source FactRef不等来判wrongentry。
本文件测试在修后产品上首次执行，以下是本轮实际Verified，不把它倒写成已测旧版本失败。

| 风险/合法情况 | 原记录构造与准确断言 | 本轮结果 |
| --- | --- | --- |
| entry未知、completion thread已知冲突 | 原INVOKE child完成保留，entry用Unresolved，child segment改为同process另一thread；必须 `call_thread` + entry缺口。 | PASS |
| caller线程未知、child两known threads冲突 | 将child completion visit移到同activation新CaptureIngress/另一thread，删普通跨段transfer；caller线程Unresolved；必须 `call_thread`，不是借 `transfer_segment` 假阳性。 | PASS |
| 同activation两种实际terminal | 保留NORMAL路径，再从同原程序的RAISE夹具接入独立CaptureIngress、重命名visit，保留原literal/producer与Uses；必须 `call_multiple_completion`，不能靠duplicate-ID/definition失败。 | PASS |
| 同caller或同activation重复关联 | 两条不同CallActivation ID的exact端重复；分别必须 `call_caller_reused` / `call_activation_reused`。 | 2 PASS |
| dynamic身份环 | 单Region有base case的合法递归程序，将唯一child关联回parent自身entry/terminal；必须 `call_activation_cycle`，非错误staticcallee/entry/completion owner替代。 | PASS |
| static递归、不同activation合法 | 同程序：bool true→recursive CALL(False)→return；child false→base return。复用原fixture _model派生parent/child真实canonical路径。report.valid，source/runtime/transform未证。 | PASS |
| entry不同FactRef或URI别名 | activation.entry与InitialEntry.source两个EvidencePoint同scope但不同locators，或同hash/schema/size的不同URI；必须结构合法，仍source-runtime-unverified。 | 2 PASS |
| completion另一次同body发生 | caller/静态callee同类型，completion改为另child activation的terminal；必须 `call_completion_activation`。 | PASS |

递归正例有真正的base-case程序结构，不用 `f(): f(); return` 加缺采集伪造可终止执行。这里只核手工声明的有限结构路径；未执行其Python/native源码，也没有实现通用终止证明。thread/terminal反例中的CaptureIngress明确保留partial/path缺口，不伪造普通跨段CFG关系。

## 真实执行与有限范围

```
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_resource_composition/focus.py boundary_calls tests/unit/test_execution_call_boundary_review.py
```

attempt001 exit0；pytest **10 passed in 0.60s**，driver外部1.2823873749002814s。原command/environment/Python、source.before/after、JUnit、stdout/stderr/report均已保存；子进程退出后只删除该driver创建的独占basetemp。没有此前失败尝试被覆盖。
调度曾暂停/恢复新文件授权；第一份boundary文件只在root最终统一授权后落盘，此前未创建/执行另一个boundary测试。现已冻结，无可选扩测或额外probe。

未把声明pair当真实caller/对象/内容身份；两个same-scope/type child无native依据的恶意交换不必可识别。没有关闭Endpoint协议、wholeWork native extent、source/capture闭合、整个R3或M0–M2；没有LeWM A/B结果。旧query11P和作者baseline/records属于各自归档，不与本10P合并冒充fullgate。

## 本次精确指纹

- `tests/unit/test_execution_call_boundary_review.py` SHA256 `2214e4f0678ed22c282edd38431b6f5b3a85ab89c65102c25b148f6c50e99558`；首跑前/后/报告时一致 `True`。
- `scar/ir/execution/call_validation.py` SHA256 `79febd82eea06447ad045e8302a62a17164bb04771c9a2ef852b28640a127f4b`；首跑前/后/报告时一致 `True`。
- `scar/ir/execution/calls.py` SHA256 `a287446babd077c072f51182d12ecc5e670bd2e1700b6396e914e134d95a183f`；首跑前/后/报告时一致 `True`。
- `tests/fixtures/execution_call_graphs.py` SHA256 `6fa0d2eca706edc3a371d4d8d8581973b7e28b94ce5623e89048789e3fc8c90b`；首跑前/后/报告时一致 `True`。
- `tests/unit/test_execution_call_validation.py` SHA256 `843b486b8cdeb917aa230056c6c88731a07e4cf100a1174dfe01ba95ab1e964c`；首跑前/后/报告时一致 `True`。
