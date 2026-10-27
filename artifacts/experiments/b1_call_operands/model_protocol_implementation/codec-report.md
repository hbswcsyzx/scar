# P2 Program17 / 两表 / 旧wire实施回执

基线：`85aee70dd6217e61c03df54ef4ee154b0d662328`。本回执只覆盖model两表及codec；F消费者/完整P2仍由root独立验收，不因本31用例关闭全家族分母。

## Implemented

仅修改授权产品：

- `scar/ir/program/model.py`：`protocol_scopes` / `protocol_operations` 默认空tuple。逐row exact类型、递归重验；scope ID唯一；operation自然键 `(scope,clause,operation,slot)` 唯一。允许不同slot等合法不同键，不新造producer/state。
- A的protocols不top import model；model在OperationResult/InvokeLiteralResult定义后import新records并调用私有 `_bind_model_ports`。hook由A保证exact canonical与幂等，typed别名供现get_type_hints使用；没有复制port类或修改global record_codec。
- `scar/ir/program/codec.py`：schema max17，仅新两表任非空为F capability。v17 strict full fields/本地新tags；无F保持old1–16实际能力选择与原field/tag/byte profile。v17空F不能假升级；old1–16不收新字段（包括空表）。
- PROTOCOL_RECORD_TAGS仅v17局部合入，不建全局可执行registry。嵌套F复用旧InvokeLiteralResult tag及ExistingAccess/InvokeStateOperand tags：即使原literal/address附件表为空仍需这些typed wire。既有literal的NORMAL/Data/Reference语义未放宽。
- 新schema17 escaped JSON；旧schema各自encoding保持。Execution codec/模型未修改，max仍7，O归P3。

独占源/新增test和golden最终sha、size、mtime见 `codec-source.final.json`。没有修改root flow/validation/query/lifecycle、A records/rules/ids、旧fixture/test、docs或backend。

## 独立旧v16 golden

变更model/codec之前，从不可变85aee70的`scar`及`tests/fixtures`经git archive隔离抽取；child cwd/PYTHONPATH均archive，明确assert archived codec max16及模块路径。实际factory：

```text
literal_program(payload=(1,b"bytes",None,complex(-0.0,2),"\ud800\udc00"))
```

不是空图；包含Exact Data origin、typed来源和原direct/INVOKE结果附件及严格surrogate/complex/bytes表示。新golden15059bytes SHA `c1ad1ba55842b1b5451389275744212216a652231ace7e9106fd37ceb19f0351`。

准确生成命令/child script/stdout/stderr/exit0/archiveSHA位于 `golden/`；proof记录旧codec SHA及fixture源码SHA。只清理该生成器创建且child已结束的owned临时archive目录。没有用新encoder重造历史期望，没有改任何oldgolden。

聚焦测试同时验证旧golden loader重新编码字节，以及当前相同literal factory直接生成字节均等于这个历史payload。

## 实际聚焦与首次失败

只运行新 `tests/unit/test_program_protocol_codec.py`，两次尝试命令均由 `codec_focus.py` 原样记录：

```sh
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_protocol_implementation/codec_focus.py
```

- attempt001：30 passed / 1 failed / 1.44s，harness wall2.1648968318477273s。唯一失败为自有test把value factory中的OutcomeAdapter也当有`result`字段，KeyError。此时wire往返已成功；不是产品或fixture缺陷。
- 仅修owned test按RequestProcessing精确variant筛选，assert非空，并保留原N/R以及state tags检查；没有改产品或fixture来适应测试。
- attempt002：**31 passed / 1.29s / exit0**，harness wall1.9924889402464032s。

所有attempt留command、stdout/stderr、junit、report、source before/after；两次各自snapshot相等、changed_keys为空（见source-comparison.json），但这是共享开发期，**不冒充最终全局冻结组件/full**。最后owned-source mtime/sha另保存。

## 有限覆盖与不覆盖

覆盖：scope-only与真实N/R request/state端口；Packet/ContractResult/OwnedUse；NoEntry NORMAL/RAISE/前置拒绝的准确edge；空cap、old1–16新field/tag偷渡、v17缺table/伪authority/错tag；model自然键与嵌套私有篡改；全部五contract的strict record-only tag roundtrip；独立v16 bytes。

最后五contract组合测试明确是record-only，不调用graph适用声明，不把错误profile/clause组合当合法图。实际graph roundtrip复用root通用fixture，不另造独立model。此首测阶段F完整consumer/edge-seed/check还在root接线；当前codec调用的是实际existing `require_valid`，不mock/跳过validation，后续组件必须覆盖最终F接线后的同文件。

没有运行full/组件/LeWM/GPU/采集、安装、环境升级或提交git；没有新的运行identity、source/native、变换或加速结论。
