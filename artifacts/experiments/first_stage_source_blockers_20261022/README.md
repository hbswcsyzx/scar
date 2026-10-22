# 真实源码阻塞回查：写入与短路控制

2026-10-22，产品 `2b805c2`。**不是全量 inventory，也不是第一阶段完成。**

输入是前一份真实 inventory8。脚本从终止缺口机械选出三族：66 heap 写、15 BoolOp、
9 IfExp；不提供函数名单、不执行目标、不注入手工图。31个文件各 prepare 一次，
每个body独立10000op上限。这个诊断预算不同于全量inventory的总构图预算，因此
不能把这里的37直接加到54，宣称全量已得到91个body。

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
python artifacts/experiments/first_stage_source_blockers_20261022/recover.py \
  --inventory artifacts/experiments/first_stage_environment_inventory_20261022/inventory.json.gz \
  --out /your/new/result/directory
```

## Observed / Implemented

- **90个body：37 LOWERED_WITH_GAPS，53 UNSUPPORTED，0 ERROR**。
- wall139.69s、peak RSS602140KiB、exit0；全部正常/失败路径和源/owner检查由
  原 canonical validator 和对应 source profile validator 实际执行。
- `LeWM.__init__`、`FeedForward.__init__`、部分环境构造等已实际生成typed body；
  这是外部源码结果，不是内部名字匹配规则。完整逐项列表及图见result/。
- 原来缺失的receiver/key来源恢复为准确SG Name/scalar leaf；多级缺失表达式
  不猜接。值BoolOp返回原operand；条件BoolOp/IfExp避免再次truth，分支只携本路径值。
- 原始SourceProgram/frame/structured算法分支保持；新ENV规则的复现须绑定记录commit。
  未扩大单元测试，也未额外重跑全量public inventory/check-inventory。

## 剩余实际断点

53个中的首个缺口：解构/其它写25、Dict4、Raise3、ImportFrom3、AugAssign2、
JoinedStr2、缺失target-child Call2、expanded Call2、Try2；其它各1，见summary。
这些只是首个阻塞，不证明通过它们后整个body就一定能展开。

`bodies.jsonl.gz` 保存每个构造结果的原source、canonical graph、metadata、interface
和structured overlay；`summary.json`保留全部90项状态和下一终止点。
完整程序、运行环境actual、细effects、逻辑版本、OS/CUDA资源/ready闭包均未建立。
没有做优化、推理重跑或加速测量；继续第一阶段。
