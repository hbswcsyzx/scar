# C1 v9 codec / CLI 接线报告

2026-10-16。实现依据 `docs/M1_CLEANUP_INTERFACES.md`，扩展 wire 差异已获 root 确认。
本子任务编辑 program/codec.py、cli.py，并经明确授权编辑 record_codec.py 与
tests/unit/test_record_codec_tags.py；未改 validator、fixtures、其他测试或环境。

## Implemented

- v9 承载六张 C1 表，以 handled_context_domains 选择能力；v8 及更早字段集合排除
  六表，旧版本只补空表。序列化仍运行完整 graph validator；缺 domain 的其他 C1
  表/route/保存 context 能力另有显式拒绝，不能降级丢字段。
- v1–v8 不能夹带 SAVED_HANDLED_CONTEXT 的 Value、exit/completion type 或 route tag；
  v9 必须有 handled_context_domains。既有 strict 顶层字段、JSON 和旧能力条件保留。
- 必需的 wire 修正：C0 PendingDispatch 与 C1 CleanupRoute 的 dataclass 字段形状相同，
  不能让 union decoder 按首个成功类型猜。仅 C1 route 的 v9 wire 显式增加
  `kind="CLEANUP_ROUTE"`；旧 C0 dispatch 保持原无 tag 格式。
- record_codec 增加局部、可选 `record_tags={RecordType: (field, tag)}`；默认 None 的
  编码不变，无全局 registry。递归贯穿 union、tuple/list/dict 和嵌套 records，严格
  拒绝缺/错 tag、重复 discriminator、与已有 field 冲突、错误配置与额外字段。
  tag 在构造前核验，只构造匹配类型；没有先误解为 dispatch 再 patch 的中间图。
- CLI 仅在完整 loads/validate 成功且有 domains 时设置 cleanup_structure_validated=True，
  并注明 declared static 范围；计数 interfaces、四种 actions、routes。实际 unwind、
  context、runtime、source recovery 与 transformation 权限保持未证明/False。

## Verified：首轮定向终态

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q \
  tests/unit/test_record_codec.py tests/unit/test_record_codec_tags.py \
  tests/unit/test_program_environment_codec.py tests/unit/test_program_control_codec.py \
  tests/unit/test_program_provider_codec.py tests/unit/test_program_native_codec.py
```

实际 **147 passed in 1.57s，exit 0**；唯一首轮日志 [pytest.initial.log](pytest.initial.log)。
覆盖默认旧编码、同形 dataclass 的显式判别、嵌套 union/容器、缺/错/重复 tag、
constructor 前选择、旧 wire 版本规则及既有 v7 frozen bytes。没有失败或重跑。
根提供的隔离 588ca84 原 v8 golden 已存在；本命令未包含新 C1 graph/CLI 或该 v8
golden 的专属验收，留待兄弟任务的新 fixtures/tests 与最终组件，不据此声称已通过。

本次文件 SHA256：

```text
2facc7de22eadf2c095181a6f258ecbb7a529079d5c92b6414bbb0a0968ec6c4  scar/ir/record_codec.py
d9d802cfa0791622f5c610432c03ca883bba16b807c9f18bebd251e81f47b350  scar/ir/program/codec.py
14f965b55c21522a5b14db6ab95d59ddf4f46337ac9b1aa61112d027fb3c264f  scar/cli.py
e5722da20a039ab94ccd0ef92957f0240b307686b4445291c6d0a3baccabfe28  tests/unit/test_record_codec_tags.py
```

## 范围

没有运行 full、LeWM/GPU、采集或真实 cleanup；没有提交/推送。类型/wire 接线及
147 项定向通过不等于 C1 全门、完整模型、自动源码恢复或任何可用优化/加速结论。
