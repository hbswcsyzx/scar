# 原 source 三图与 typed body 的真实组合

状态：结构索引已自动生成；第一阶段 OPEN。没有运行优化，没有运行测试套件。

输入：

- `first_stage_environment_inventory_20261022/inventory.json.gz`
- `first_stage_source_context_20261022/result/source-layers`

命令在 conda `lewm` 中执行：

```bash
python -m scar.analysis.program_composition \
  --inventory artifacts/experiments/first_stage_environment_inventory_20261022/inventory.json.gz \
  --source-layers artifacts/experiments/first_stage_source_context_20261022/result/source-layers \
  --out artifacts/experiments/first_stage_program_composition_20261023/result
```

exit 0。逐文件运行原 source archive 验证器，逐已恢复 body 运行原 canonical
ProgramGraph codec/validator。组合期间源仓库未修改，目标程序未执行。

| 项目 | 原图数目 |
| --- | ---: |
| 文件 | 151 / 151 |
| SourceAtom | 122,323 |
| Semantic Operation | 114,560 |
| CFG suite | 6,916 |
| CFG node | 65,880 |
| CFG edge | 78,691 |
| Definition/body 清单 | 2,217 |
| 可引用的原 canonical body | 54 |
| 条件调用目标 | 201 |

缺口没有消失：1,961 个 body NOT_ATTEMPTED、202 个 UNSUPPORTED、151 个模块
初始化 canonical body 未恢复；SourceSemantics/CFG/effect gap 和跨函数绑定仍未
闭合。`summary.json` 保留完整计数。这不是完整 ProgramSnapshot/ExecutionModel。

`query.py` 从产物自动选择一项已恢复 body，通过当前 CompositionIndex 真实查询：
源 definition → 原 typed region → 23 个 operation，原 operation 的 9 个有序 Use
和 1 个 StateAccess；effects_complete=False 保留。另自动选择具有可引用目标 body
的跨文件源调用，得到 1 个条件目标 canonical region，actual/formal/return 连接
仍为 false。原结果在 `query-result.json`；它不证明调用目标已在真实执行中确认。

组装进程启动后完善的查询投影、coverage frontier、summary 分母和 metadata 更严
格核对已在当前代码中；本次整范围组装是初版适配器，当前入口的查询已实际运行。
不宣称这些增补已重新逐文件运行。后续新 inventory 组装应使用当前代码。
