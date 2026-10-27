# L2 有限实施报告

基线：13201ad24e0d8236623e28709f86e13a887ed4fb。实现遵循 M1_LITERAL_PLAN；本报告不关闭整个 L/M0–M2。

## Implemented

- ExactLiteralOrigin 仅 DataValue，精确 payload 调用共享 require_exact_literal/literal_builtin_type，Reference/State/Binding/Protocol 不预装。
- SourceExpression/CodeConstant/UnlocatedLiteral 保留来源阶段；CodeConstant.fact 指 code 容器记录、index 是 co_consts 选择，不解析 URI、code 或 source。
- LiteralEvaluation 附着原 OperationResult，或原 INVOKE NORMAL CompletionResult；不新增 producer/ValueID/Use、effects_complete、state 或 identity。原 core completion_slots 仍要求每 produced slot 恰一次绑定。
- UninterpretedConstant 不授 content/type exact-match；query 对未解内容、未定位、未重放 code 槽和 source span 给分别的条件。
- Program wire16 只由 Exact origin/附件能力选择；其他 schema1–15 字段、tags、bytes 保持。v16 escaped JSON，surrogate 内容复用共享 STR_CODEPOINTS 协议，不自制第二字符串协议。
- ProgramIndex.literal_evaluation 返回原结果、原 NORMAL edge/argument、原有序 UseSite 和附件；source_runtime_verified/value_identity_verified/transformation_authorized 恒 False。

## Verified

精确命令和全部原输出：attempt001/command.json、stdout.log、stderr.log、junit.xml、report.json。

```sh
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_literals/focus.py core_literal tests/unit/test_program_literals.py tests/unit/test_program_literal_codec.py tests/unit/test_program_literal_query.py
```

终态：65 passed in 1.07s，child returncode0，harness wall1.7690678853541613s。
此总数包含参数化边界，不冒称65个独立语言协议或全分母已覆盖。

覆盖：八标量/tuple payload 的 core 接入；surrogate pair 与单 U+10000 分开、NUL、complex NaN/signed-zero 表示往返；Exact Data-only/type；state/RAISE/错边/缺 producer/越界；来源字段/私有嵌套篡改；重复 site；原重复 Uses 不去重；NORMAL signature 与 landing 物理顺序反排；缺附件仍保留原端口；两种 capability 独立选择16；old1–15 空新field拒绝；旧15 Origin偷渡拒绝；伪tag/额外authority/缺字段拒绝。

独立 v15 golden 从冻结旧 codec 的既有证据复制到新增 fixture，来源 proof 未改；SHA0bd50636fb4f18c85239917b2895f71b9a0cfff0b0c1fdf77cb715068851dd8e，15511bytes。本轮既核 loader重新编码字节，也核当前 state_address_program 直接编码字节相同。没有重造旧 fixture 期望。

## 首败保留

preflight.initial.log 保留一次共享 helper 在 tuple 分支 size 未赋值的原构造 traceback；作者修复后轻量 smoke 校验空issues、14791char roundtrip True。另首次非激活 shell 的 python未找到，脚本未执行且未改文件；其后全部 Python 激活lewm。第一次 pytest 已65PASS，无覆盖失败日志。

## 边界

没有执行 LeWM/GPU/full/新采集/目标代码编译；未验证 source AST classification、code fact/slot实际存在、对象 identity、native effects、优化纯性/替换合法性或任何速度提升。共享 L1 budgets、旧family边界，以及跨loop/call/resume动态应用由其各自作者/最终联合门验收，不用本65PASS代替。focused期间其他作者可能改其独占文件，最终统一 source freeze/组件/full 归root。

独占源码和新增fixture/test的终态 hash见 source.final.json。源审如发现具体问题，将保存此报告/首跑并追加修正与后续attempt，不回写历史。
