# 第一阶段：源码上下文真实验收与临时目录恢复

日期：2026-10-22。**全程序建模仍 OPEN；不进入优化阶段。**

## 已确认的恢复事实

此前`/tmp/scar-structured-model-280qf4mi`已不存在，原query session无有效handle，
进程检查也未找到原query/audit。Git仍保存`ccf6cac`和其父提交，原SCAR checkout
为`84f165f`、LeWM为`f70fed8`且均clean。只移除该缺失worktree的Git登记，在
`~/AAA/scar-worktrees/structured-program-model`恢复同一分支；未重置或覆盖用户文件。

10月20日未入库的source-layer归档、上下文查询脚本/日志和部分文档改动无法复核。
不重建伪日志，不把口头计数当本次实测。现在从已入库原inventory重新验收。

## 本次对象与命令

输入是`../first_stage_model_20261020/inventory.json.gz`的全部151文件、2,217定义、
10,235调用、122,323个source atom。原source namespace/root、snapshot和三份
digest都不改变。目标源码只读，不import或执行LeWM，不采Tensor数值或GPU工作。

`run_contexts.py`在原公共`reconstruct_source_layers`的一次prepare调用结果上，
使用`index_source_control_contexts`查询每个原调用，再将未修改的PreparedSource交还
原writer核对snapshot/三图摘要并保存。避免第二遍prepare或昂贵的全三图typed读回。
observer只在实验脚本内安装，生产writer和原图语义不变。结果valid要求全部原
file、call、source atom分母及archive完整性匹配；它不是完整程序模型PASS。

可复现命令见`run.sh`。输出目录必须不存在；失败与部分记录保留。每个调用保存
SourceReference、原owner/phase、ordered operand→producer和structural context，
包括没有计算语义的调用。CPU/Python版本及代码SHA同时记录。

## 当前已有验证

恢复后在conda lewm / Python3.14.7实测：

```text
tests/unit/test_source_control_context.py
tests/unit/test_source_layers.py
tests/integration/test_source_layers_cli.py
17 passed in 6.18s
```

涵盖同一行多个语句、nested calls、default/decorator与call-time body分离、
class/with定义不污染未来函数体、短路/comprehension/lambda/await边界、漂移、
损坏、输入与缓存预算。测试不代表全LeWM已覆盖。日志保存在本目录。

## 全量实测与独立验收

输入原始压缩SHA256为
`1b29ba654226d6c374bebc2fe7ba212f4658b05b57b521c90590ac4d5384c422`。
实现版本`8de7988`。回建加查询exit0，wall542.37s、peak1,284,872KiB；输出gzip
归档和记录共约108MiB，没有写未压缩GB级重复档。三图的原snapshot/digest全部匹配。

| 实际项目 | 数量 |
| --- | ---: |
| 文件 / source atom / computational operation | 151 /122,323 /82,299 |
| 原调用分母 | 10,235 |
| 有 /无计算语义的调用 | 9,763 /472 |
| 按CALL operation ID直接匹配语句CFG | **0** |
| 新结构查询有 /无语句CFG对应 | **9,116 /1,119** |
| 有计算语义且有语句对应 | 8,960 |
| 无计算语义但恢复语句对应 | 156 |
| 带gap的context | 2,218；可与已连接项重叠，不是完成率 |

`result/result.json`保全部file行、gap及边界，`contexts.jsonl.gz`保每个原调用的
完整结构查询；未连接项没有从分母消失。不能把上述数量写成实际运行依赖已证明。

### 独立审核中的实际失败与修正

第一次标准库审核在第71个文件失败（exit1，37.31s），原脚本及日志保留为
`audit_contexts.initial.py`、`audit.*`。它错误要求lambda body继承创建语句外层的
短路边界。精确反例的AST路径跨越`BoolOp → ... → Lambda.body`；程序模型已按
独立call-time scope保留`LAMBDA_BODY_FRAME`和缺suite gap，且没有CFG对应。定义时
的条件不能直接当作未来函数体执行时的条件。`diagnose_boundaries.py`和输出保存
了这些原调用位置，未使用函数名规则，也未修改生产记录迁就审核。

修正审核：只在跨`Lambda.body`处重置所需的外层控制标签，并强制检查延迟body
标签、未建suite gap和空CFG对应；进入body后的短路仍逐项核验。其余所有字段路径、
scope、端点和摘要检查不变。最终全151文件审核**PASS**，exit0、wall62.80s、
peak912,004KiB，结果在`result/audit.json`。核对63,541条operand、82,299条
result→producer、65,880个CFG节点和78,691条控制边，未证明动态依赖或优化合法性。
诊断脚本首版还因TypeIgnore无end_lineno退出，修正为仅索引完整位置节点；这不是
目标程序或模型缺陷，不将该辅助诊断算作验收。

## 下一项

独立审核不import SCAR，按原AST重走每条字段路径并核source atom、scope与
原CFG端点，同时重算归档与原三图digest。本项只验收这些结构事实。

即便连接核验通过，原50个LOWERED_WITH_GAPS、206个UNSUPPORTED、1,961个
NOT_ATTEMPTED仍未增加。下一项是公共source→core恢复：现有structured profile
尚未接入inventory/calls，且BoolOp/IfExp等单个unsupported会清空整个body。按
真实缺口补连接和控制协议，不添加detector/backend，不手选业务函数、不同名规则。
Python/Torch实际Uses/状态/来源、OS/CUDA资源生命周期、ready与外部输出闭包仍OPEN。
