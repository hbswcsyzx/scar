# candidate02：原 SG Call 分类窄修

原 attempt01/freeze/runner/失败收据保留；root归档commit e5e1013b。仅三源码guard改为识别原
OPAQUE + metadata.ast_type Call +准确唯一Call atom/source/code_id/source_atoms/单output定义，
不改原SG分类。计算语义及core source link仍单独要求Opcode.CALL；其它八源码原SHA不变。

新增恰一项真实接口检查：正常load_source_layers读取已用firstcontext，直接核真实SG定义与原
SourceSemantics Opcode.CALL，2.121s PASS；原三小检查只复用。没有body lower/target/新compile。

freeze SHA `c9991f4f5f6505aed8da79bb8f949d5c315cd9bea7cfd39e9f99a9cb616f68a0`；352源码与21原输入，所有输入与预算严格等于前门。256MB真实累计输入、
输出256MB、context/record64MB、composition96MB、4body/2source/4000ops每body16000总、
180s每body/600sworker/660souter、20sheartbeat，均不调整。旧源replay/cleanup/outer-prefix限制
与[上一门准备说明](../README.md)相同，仍不作publication/currentRun整合或全程序PASS。

由root持有session运行：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/zyf/AAA/scar-worktrees/source-call-model /home/zyf/miniconda3/envs/lewm/bin/python -B /home/zyf/AAA/scar-worktrees/source-call-model/artifacts/experiments/source_call_kwargs_bodies_20261025/candidate02/run_gate.py --execute --freeze-sha256 c9991f4f5f6505aed8da79bb8f949d5c315cd9bea7cfd39e9f99a9cb616f68a0
```

固定新`candidate02/attempt02/`，默认不执行。真实有限门尚未启动；不是复用attempt01 owner或结果。
