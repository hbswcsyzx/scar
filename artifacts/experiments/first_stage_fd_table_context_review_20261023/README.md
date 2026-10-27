# R2后续：FD table/context只读审查

设计见`docs/FD_TABLE_CONTEXT_REVIEW.md`。本实验没有改生产代码、R2已冻结文档/产物，
没有新target、GPU、采集、全表扫描、refinement publication或优化。

`evidence.json`保存原R1/R2/coordinates/archive receipts、35个selector的精确分组、
两个小raw档完整stored/raw SHA核验，以及公共reader核验的唯一birth chunk/row。
4/35个container具备机械补全条件，但**实际仍35个Unresolved**；31个端口连续性保OPEN。
拟议252档/9,264,445bytes补证扫描没有执行。

首次`read_evidence.py`以绝对script路径启动未设置PYTHONPATH，import前即失败exit1；
`read.stderr.txt`和`read.time.txt`保留。`read-attempt02.*`显式设置worktree PYTHONPATH，
实际exit0；未修改script或覆盖首次日志。此次仅只读metadata、394,970bytes小raw和一个
15,999,783decoded-byte既有chunk，不是target或测试套件。

复现入口（新输出目录或移出原结果后才可执行；脚本以`x`拒绝覆盖evidence）：

```bash
PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model \
  /home/zyf/miniconda3/envs/lewm/bin/python \
  artifacts/experiments/first_stage_fd_table_context_review_20261023/read_evidence.py
```

全程序建模和完整ExecutionModel语义仍为OPEN。
