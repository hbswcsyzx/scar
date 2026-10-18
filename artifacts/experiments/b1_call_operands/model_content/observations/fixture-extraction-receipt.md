# Q fixture 提取补充

root 在原报告完成后明确授权新增
`tests/fixtures/execution_observation_graphs.py`，供公开 query 测试复用。
原 `report.md` 和 attempt001/002 未改写。

- 原 unit `_observation` 函数原样移至公开 `observation_execution`。
- 返回 `(program, model, semantic_graphs)`；参数为 keyword-only：
  `output=False, external=False, activations=1, facet=ContractFacet.EXTERNAL,
  required=True, anchor_activation=0`。
- unit 改为 import as `_observation`，37 个 case 的 ID 与断言保持。
- fixture 不导入 unit。两份产品 module 未改变。

最终四文件 SHA256：

| 文件 | SHA256 |
| --- | --- |
| `scar/ir/execution/observations.py` | `8c8237c855680e78f6e1c256a30086105636c2af5ad6fb59958385840ed7d882` |
| `scar/ir/execution/observation_validation.py` | `eaae52e54664107ac7baa7aa5707fbf2a19be6e9b59346f0ce37040f563ff983` |
| `tests/fixtures/execution_observation_graphs.py` | `fef4e061a5af321f1173b34366df908495ed2505345994f19169e9baeaa419d9` |
| `tests/unit/test_execution_observations.py` | `e89e400a81ad680270632224755310781a204fe169df36b7357c903e2f4acbc8` |

提取后 `attempt003` 在 conda lewm 仅运行原所属单文件，结果
**37 passed in 0.82s，exit 0**。command/source.sha256/output/exit_code 全部保留。
这是相同 37 项的移函数回归，不应与先前尝试相加。
没有新增 full/component/其他测试，也没有 source/runtime/ready 证明。
