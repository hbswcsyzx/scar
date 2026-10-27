# D2.1 publication codec / queries / CLI

2026-10-18；根代理指定冻结设计基线 `38d2968`。本报告仅记录本子组件实施和定向
结果，不宣布完整 D2.1/D2/C2/M1、source/runtime 对应或自动程序建图通过。
没有改 root model/validator/fixture、另一 agent records 或旧 golden；没有 git、
full、LeWM/GPU、安装、native capture 或新语言实验。

## 实施内容

- `codec.py` 最大 schema 升至12，**只有** `driver_lifecycles` /
  `body_outcome_commits` 两个已实施表的非空能力触发v12；没有预放 NoBody/Session/
  FrameRelease 字段、value type、terminator 或 tag。仍复用原 D1 record tags。
- v11字段集显式减去两新表，随后递推所有历史字段集；旧版 decode 填空，不改变
  历史编码。v1–v11严格拒两表，包括空字段偷带；v12必须有真实新能力，不能用空表
  将普通 D1 图升级。完整 record+graph 验证继续先行，缺 scope 不会静默丢 commit。
- `queries.py`：driver_lifecycle(region)、body_outcome_commit(operation)返回原 row；
  body_publication(operation)派生 BodyPublication，包含原 commit/drive、原 instance
  UseSite、实际 body source/kind/公开 Uses，以及 PublicationAccess：原 StateAccess、
  原 before UseSite、真正 StateVersion after。READ 的 after=None，未伪造写、producer
  或状态快照。无声明返回None；原 typed ID/存在性检查和首次完整validate保留。
- source 派生复用 D1 drive_outcomes，因此未公开 saved private frame/pending。
  view classes 只在 queries.__all__ 导出，保持 records 包不耦合 validator 的 API 习惯。
- CLI program summary 增加 counts 与 body_publication_structure_validated；默认False，
  只有完整decode/validate后的scope为True。普通D1和invalid图不获新成功标志；
  driver_lifecycle_verified/body source/runtime/exclusivity/transform始终False。
- 两份旧 codec 测试仅把全局最大 SCHEMA_VERSION 断言从11改12，**原 graph document
  的v11/v10期望及golden未改**；不把最大支持版本冒充每张图的编码版本。

## 实际运行与所有尝试

conda `lewm`，CPython3.14.7 conda-forge，`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.`：

```text
python -m pytest -q tests/unit/test_program_publication_codec.py tests/unit/test_program_publication_queries.py
```

| 尝试 | 真实终态 | 说明 |
| --- | --- | --- |
| initial | 38PASS / 1FAIL，1.51s，exit1 | 唯一失败为v11 proof字段名仍按旧v10格式读取；wire逐字节断言已先通过，无产品拒绝/接纳错误。 |
| corrected | **39PASS / 1.49s，exit0** | 只修测试使用实际immutable archive/schema/fixture hash+bytes/source字段；未修改产品或golden。 |

`initial.log/json`、`corrected.log/json`保留准确argv/Python/exit/harness wall-clock。
corrected harness为2.140998s；这些是测试成本，不是workload性能或加速比。

验收覆盖：Suspend/Return/Raise，Create+额外域，direct/forward owner，原对象`is`，
READ无after、W⊊L、source公开端口不含saved；旧v1–v11各版拒两新表，v2–v11 frozen
wire字节保持；v12空能力/缺表/未来表/缺scope/自授proof/篡改嵌套ID拒绝；CLI新旧
结构范围、invalid旗标及全部权限False。未额外运行旧套件，交root统一组件回归。

v11 golden为root从immutable
`38d29681170f481cc9d8682ca7786dfc924dee1a`隔离codec生成；fixture64700bytes，
SHA256 `2342e990c70ce43a1363db82dd5de4d313ce27f8f3acb05ea6ba3e3df9d3e26a`。
测试核对原proof的codec_path_inside_immutable_archive=True、schema11、hash/bytes和
revision；没有用当前v12生成旧版本期望。

## 冻结文件SHA256

```text
3c96ccb9fd126c56e0d9805072e1c54a98e8d557a5c8e72beef34d3491399cd1  scar/ir/program/codec.py
2676d76ed534bba21136ce59a18419c56e2d3465131252c2940793336779ba54  scar/ir/program/queries.py
41427de5c14651ffea4aed9514f510b8d549fced605b7a60d2027bfd063e29f3  scar/cli.py
eab1a16382745aab4f016e53dfee79c8b600d5bebd50ce566ff1cfd46708554c  tests/unit/test_program_publication_codec.py
9c5ee30488767ee6c20b2539fdc6543a1c90f81b669deabd6460742830a8f438  tests/unit/test_program_publication_queries.py
0133b10e5e689b1293328bcbe5e843dd64026262733745818b881ddad1a95531  tests/unit/test_program_driver_codec.py
2c87d56e62cf6470cf10a783ecaca8c2ba5d8f24622832cf493bc11e33c6e239  tests/unit/test_program_resumption_codec.py
```

范围严格限于声明body publication。没有SessionUpdate、NoBodyFinish、reference-drop、
E/F/P历史分析、native字段真实写证明、生命周期完整验收或优化变换；这些仍按根计划
后续门实施，不由本查询/CLI或39个定向测试授予。
