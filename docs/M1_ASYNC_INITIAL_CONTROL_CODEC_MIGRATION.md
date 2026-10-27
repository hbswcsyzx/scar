# Program26 的旧测试精确迁移

2026-10-19。基线 `96b8a322590217151ff6a5e839c7ab17d068f560`。
本合同及机器 ledger 在修改任何旧测试之前冻结；仅适用本门授权的版本字面量。

Program26 复用已有 BodyStateCondition / ReferenceIsNoneCondition 的 record/tag，
仅为 ASYNC_GENERATOR_BODY_V1 的 ASYNC_REQUEST_SOURCE / ASYNC_REQUEST_DELIVERY
新准入组合选择版本。旧 CHECK_INITIAL_ASEND 单行不选 26。无新组合的 1–25
wire、字段与编码字节不变；25 仍要求非空 call_effect_expansions，Execution8 不变。

## 精确允许范围：17 个旧文件、22 处替换

### 16 个 reader 最大版本断言

以下七文件仅将 `assert codec.SCHEMA_VERSION == 25` 替换为
`assert codec.SCHEMA_VERSION == 26`；尾部原 document 版本断言保持原值：

- `tests/unit/test_program_await_acquisition_records.py`
- `tests/unit/test_program_lookup_fallback_codec.py`
- `tests/unit/test_program_exception_match_codec.py`
- `tests/unit/test_program_admission_codec.py`
- `tests/unit/test_program_protocol_codec.py`
- `tests/unit/test_program_await_acquisition_codec.py`
- `tests/unit/test_program_session_occupancy_codec.py`

以下八文件仅将 `assert SCHEMA_VERSION == 25` 替换为
`assert SCHEMA_VERSION == 26`：

- `tests/unit/test_lifecycle_composition_codec.py`
- `tests/unit/test_program_driver_codec.py`
- `tests/unit/test_program_session_release_codec.py`
- `tests/unit/test_program_resumption_codec.py`
- `tests/unit/test_program_state_address_codec.py`
- `tests/unit/test_program_publication_codec.py`
- `tests/unit/test_program_no_body_codec.py`
- `tests/unit/test_program_literal_codec.py`

第十六个 reader 是 `tests/unit/test_program_call_effect_expansion_codec.py`，
只将 `assert codec.SCHEMA_VERSION == document['schema_version'] == 25` 替换为
`assert codec.SCHEMA_VERSION == 26 and document['schema_version'] == 25`。
其原 Program25 fixture/wire 断言仍为 25，不把历史测试升级成 Program26。

### 六个真实 future testcase 身份

| 文件 | before | after |
| --- | --- | --- |
| test_program_await_acquisition_codec.py | `@pytest.mark.parametrize("version", (True, 26))` | `@pytest.mark.parametrize("version", (True, 27))` |
| test_program_lookup_fallback_codec.py | `@pytest.mark.parametrize("version", (26, True))` | `@pytest.mark.parametrize("version", (27, True))` |
| test_program_exception_match_codec.py | `@pytest.mark.parametrize("version", (26, True))` | `@pytest.mark.parametrize("version", (27, True))` |
| test_program_method_lookup_codec.py | `@pytest.mark.parametrize("version", [26, True])` | `@pytest.mark.parametrize("version", [27, True])` |
| test_program_session_occupancy_codec.py | `@pytest.mark.parametrize('version', (True, 26))` | `@pytest.mark.parametrize('version', (True, 27))` |
| test_program_call_effect_expansion_codec.py | `@pytest.mark.parametrize('version', (True, 26))` | `@pytest.mark.parametrize('version', (True, 27))` |

上述文件均在 `tests/unit/`。真实参数 ID `[26]`→`[27]`，不能用自定义 ID
伪装原身份。原 2016 项义务由 2010 个精确原 testcase 身份及六个显式迁移保留。

机器 ledger 为
`artifacts/experiments/b1_call_operands/model_async_initial_control/test-input-migrations.json`，
逐项保存 file/before/after 和六组完整 selector 身份。checker 应从基线实际字节
逐项、恰一次重放后比对；没有整文件豁免。不改旧 fixture、golden、原 wire 字段集、
独立旧 encoder 子进程的 SCHEMA_VERSION 断言或其它逻辑。

## 新验收与停止点

新增 codec 测试独立核 Program26 组合准入、旧 header 拒绝同形新能力、
26 无能力拒绝、25 原非空表要求和旧合同不误选 26。旧 96b8a32 encoder 在
隔离 archive 中生成真实 Program25 字节 oracle；原 v24/v23 oracle 原样保留。
本作者不运行解释器、测试或 Git；全部作者 FROZEN 后 root 串行执行。
本迁移不等于 F16、P4/P5/M2、自动建图或 native/runtime 权限验收完成。
