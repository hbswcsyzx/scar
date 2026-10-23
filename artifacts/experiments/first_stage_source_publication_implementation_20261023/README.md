# Source-language正式发布接口：实现冻结

2026-10-23。Implemented / 尚待根统一真实 publication→currentRun gate。
`freeze.json` 保存6个拥有文件的实际SHA、HEAD、完整patch和最小import链源码收据。
`implementation.patch` 包括新增publisher；没有自行commit。

6文件 stdlib AST、`git diff --check`、必要public import/API检查均PASS。
`minimal_check.py`/`minimal-check.json` 只导入API和核nullable成本字段，未读取程序原档、
CodeWitness或目标source，未prepare/compile/execute，也未运行测试suite/真实发布。

API：`publish_source_programs(baseComp, tuple(paths), out_dir, code_witnesses=readonlyStore, ...)`
写 `out_dir/manifest.json`；公共默认128program/64source，门可限2/1。
`compose_source_publication(baseComp, newManifest, out_dir, ...)` 写`out_dir/index.json.gz`。

实现显式partition2/file2/CP2准入，CP2引用真实SourceProgram5字段，不复制PG；namespace
取真实artifact/#/graph。UNKNOWN construction cost用None，旧1–8/CP1仍拒新能力/未知成本。
原code-source origin按实际parent manifest/原组件收据核对，dict相等检查保留。
composition3 delta只重建变化file，未变source/PG/组件沿原引用。失败BUILDING临时目录保留，
写failure receipt并保原异常；不删除失败CP2/checkpoints。

SameRunSourceProof只允许runtime agent公共orchestrator的正式类安装；此模块不自建已核bool
缓存，不替代resolve_definition/source_view原图查询。当前模型完整性仍OPEN。
