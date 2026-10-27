# Admission records / Program18 codec：有限实施记录

2026-10-18。合同：`docs/M1_ADMISSION_PREDICATE_CONTRACT.md`。基线：`b88670b8720875175550bbb60df42e6089960eca`。

状态：**owned records/codec focused 56 PASS；已冻结本分工文件**。不是完整 P2/16格、component/full、native/source/runtime 或变换验收。没有执行 full/component、LeWM/GPU/workload，也没有 commit。

## 实施

- `protocols.py` 新增 exact frozen/slots `BodyStatePredicateRule`（四个 IS_*）、`BodyStateCondition(instance_use,state_sites,rule)`、`ReferenceIsNoneCondition(input_use)`、`AdmissionPredicate(subject,result,branch)`。Body sites 为非空 exact ExistingAccess tuple，nested IDs/indices重新校验；None subject不含body/raw/state。第六 contract 进入原 ProtocolOperation union，不增 producer/Use/state表。
- `AdmissionPredicate.result` 仅原 canonical OperationResult，通过原 late-bind hook解析 postponed annotation；graph级 own bool/region/branch/READ/owner检查由根代理 validator负责。`state_sites` 是派生 property，不进 wire。
- `protocol_rules.py` 仅允许 GENERATOR_BODY_V1 / RAW_ADMISSION；其他 profile/clause不自动获得适用能力。
- `codec.py` 最大版本18，自动 capability仅 exact AdmissionPredicate variant。仅原五类 F仍17，旧其余profile保持。v18无新variant拒绝；v17使用独立旧tag集合，≤17不能包含新variant，连去tag后shape fallback也拒；能力不通过任意字符串匹配检测。
- 新 wire-only tags：`PROTOCOL_ADMISSION_PREDICATE`、`PROTOCOL_BODY_STATE_CONDITION`、`PROTOCOL_REFERENCE_IS_NONE_CONDITION`。没有可写verified/phase/entered字段。Execution仍7。
- 按授权机械修改九个旧codec测试的最大版本断言17→18，每文件仅该断言；原wire版本、fixture、case identities均未更改。未在本分工额外运行这些旧文件，它们保留给根代理组件与全仓。

## 真实原图 fixture

`admission_program(subject='body'|'none',rule=IS_RUNNING)` 引用同一旧 no-entry helper的真实NORMAL/RAISE端口，前置原 predicate+BRANCH；不借 INITIAL_THROW种 F。

- body predicate只拥有body Reference +一个真实coarse READ；原reference.targets未证，因此StateAccess.reference=None，不伪装精准物理alias，也不人为读取全部lifecycle域。
- None predicate只拥有独立Reference输入，未虚增body/raw输入。
- 原bool、true/false forwarding Uses、所有当前state、helper完成和host终端保留；fixture的外部raw/phase适用仍未证。它只验records/wire及原结构，不自称Running四格完成。

## 独立 v17 golden（先于 codec 修改）

`v17-golden/generate.py` 从不可变 `b88670b8720875175550bbb60df42e6089960eca` 执行 `git archive ... scar tests/fixtures`；子Python的cwd/PYTHONPATH都为独占archive，断言codec最大17及codec/fixture路径均在archive。真实调用 `generator_protocol_program(target='value')`，其含原SEND、body Return、StopIteration adapter正常/异常端口；不是空图。

生成器及child、原命令、stdout/stderr/result全部在 `v17-golden/`。成功子进程结束后只删除该独占archive目录。没有使用新codec生成历史期望值。

- `tests/fixtures/program_graph_v17_frozen.json`：83,719 bytes。
- SHA256：`26ce910cb4720898c47a3dc0f25abddb912ee63aa50cbf68fcd90d80a3cad57a`。
- proof SHA256：`e5a7de83e4a6a74d2f1cb0950dd47120627c440e11f202a077e7d235aa1ef815`。
- 最终聚焦直接比较 archived wire、当前loads/dumps、当前同factory生成wire三者字节相等。

## 所有聚焦尝试（不累计用例）

全部实际命令均先：

```text
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_generator_matrix/admission-codec/run_focus.py ...
```

| 尝试 | 自有selector | 实际结果 | 归因 |
| --- | --- | --- | --- |
| attempt001 | `tests/unit/test_program_admission_records.py` | 12 passed / 0.39s | exact records、嵌套篡改、union/规则/原结果类型、无假输入。 |
| attempt002 | `tests/unit/test_program_admission_codec.py` | 34 passed, 10 failed / 1.83s | 新测试一处把Operation.label写成不存在的kind；九处误将旧v2–v10 fixture的包装LF视作encoder原始字节。不是产品绕过，原日志/首版测试保留。 |
| attempt003 | 上述两个文件 | **56 passed / 1.94s** | 只修新测试字段名；对旧v2–v10先断言恰一个包装LF，再仅除该LF；旧golden均不改。v11–v17直接字节相等。 |

每次目录均有exact `command.json`、完整stdout/stderr、JUnit、registered source before/after清单及结果。三个实际进程期间注册指纹均相等；这是各自开发期聚焦事实，不能声称整个后续共享开发或最终候选已冻结。

最后attempt003进程注册指纹：`bf7735fd24e2f5414ebf297c39995314b1e8256152a6ee23ca0e756adc5fdc06`；harness wall time2.651s。此前body fixture精准reference会触原core incomplete_alias的风险由根代理**在首次codec前源审指出**，已先修为真实coarse reference=None；它不是一次已经运行失败的实验。

最终56是12构造+44codec的同一末次聚焦，不把前三次重跑计成额外独立通过数。codec覆盖新两subject、嵌套tag/字段/ID拒错、所有≤17降级、新shape无tag偷渡、18无cap、literal/label字符串不触cap、v2–v16历史profile及独立v17。

## 最终 owned SHA256

```text
a51bd800af0b767e8477b95a07aa77ff0a47a0de3222c2804818c295b215fc03  scar/ir/program/protocols.py
be4b601e16401f677b4cbf4e7ba4d2b2d895f4364ce4d1f90d68ed778f92dbe1  scar/ir/program/protocol_rules.py
471242b6cb56debcbaa659c64d667e271a9dac33cb8bb40f8a85f5503a62e14b  scar/ir/program/codec.py
1b31928b5770ee3fb1acac7f7c9894271a8dc18893c660aa7fe96e6532f11d84  tests/fixtures/program_admission_graphs.py
8d820d97b25d487e62716f0b773bcbc557aae507a1493fb41a5ab7e8ecf04d89  tests/unit/test_program_admission_records.py
c853daa1e6e74a6d39492a823c26046f21db1e54e5833eb5aadee212a80d34bf  tests/unit/test_program_admission_codec.py
```

独立review、准确phase消费者/静态caller来源、全16格与callback顺序由本门其他owner继续验收；上述56项不能替代这些分母。原source/native/runtime适用、对象identity、优化许可均未被本records/codec授予。
