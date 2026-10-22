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

## 全量验收与下一项

以`result/result.json`及独立`result/audit.json`最终实际内容为准；运行未完成前
不预填PASS或连接数。独立审核不import SCAR，按原AST重走每条字段路径并核
source atom、scope与原CFG端点；同时重算归档与原三图digest。

即便连接核验通过，原50个LOWERED_WITH_GAPS、206个UNSUPPORTED、1,961个
NOT_ATTEMPTED仍未增加。下一项是公共source→core恢复：现有structured profile
尚未接入inventory/calls，且BoolOp/IfExp等单个unsupported会清空整个body。按
真实缺口补连接和控制协议，不添加detector/backend，不手选业务函数、不同名规则。
Python/Torch实际Uses/状态/来源、OS/CUDA资源生命周期、ready与外部输出闭包仍OPEN。
