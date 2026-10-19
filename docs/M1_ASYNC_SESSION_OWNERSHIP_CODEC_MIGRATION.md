# Program24：既有测试能力上限的必要迁移

2026-10-19，在任何本门测试运行前记录；补充冻结的
[本门计划](M1_ASYNC_SESSION_OWNERSHIP_PLAN.md)，不覆盖其原字节。

新增typed subject需要Program24，不能既发布24又让公共reader上限仍为23。
源码审查发现14个既有测试硬断 `SCHEMA_VERSION == 23`，另4个参数化测试以
24作为“future unsupported”值。它们必须随能力升级同步迁移：

- 仅14处公共reader上限断言由23变24；所有旧图选择的wire version（1–23）、
  原golden fixture、字段/tag/roundtrip/原生producer断言均不变。
- 仅4个future-version参数24变25，保相同unsupported错误及拒绝断言。
  其实际pytest参数身份会由 `[24]` 变 `[25]`，不伪造历史ID来掩盖输入迁移。
- 旧1907义务保留，其中1903身份原样、4项以明确old→new映射核验；最终报告
  不能写“1907精确身份全部未变”。新的总数另加本轮新例。

14处文件为test_program_await_acquisition_records、await_acquisition_codec、
lookup_fallback_codec、exception_match_codec、admission_codec、protocol_codec、
driver_codec、session_release_codec、resumption_codec、state_address_codec、
publication_codec、no_body_codec、literal_codec，以及test_lifecycle_composition_codec。
4个future文件为test_program_await_acquisition_codec、lookup_fallback_codec、
exception_match_codec、method_lookup_codec。均在tests/unit/，加.py后缀。

B被明确授权这些精确常量修改，不改其他测试逻辑/selector/原始wire fixture；
checkpoint必须对基线逐字重放这18项替换并比当前字节，不能给整文件豁免。
历史失败快照按每次真实执行前源码保存。当前版本24没有新subject则拒绝；
旧<=23偷带新subject也拒绝。独立旧版reader/encoder归档上限断言保持原样。

这是原“future schema拒绝”和“公共reader能力上限”义务的版本迁移，不删除
case、不降低拒绝条件，也不把旧wire升级为24。F16/完整模型仍依原分母验收。
